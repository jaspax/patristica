"""
Ingestor for R. H. Charles's English *Jubilees* and *1 Enoch* (#353).

Source: the Internet Sacred Text Archive's transcriptions (John Bruno Hare,
archive.sacred-texts.com) of the SPCK editions in *Translations of Early
Documents* (London, 1917): *The Book of Jubilees or the Little Genesis*,
with an introduction by G. H. Box, and *The Book of Enoch*, with an
introduction by W. O. E. Oesterley; both Charles's translations from the
Ethiopic (revising his 1902 Jubilees and 1912 Enoch).
Output: ``data/raw/charles-eng/{jub,1en}.json``
Language: eng  Tradition: ethiopic  Genre: apocrypha  License: public_domain

A Scripture source (``versification.SOURCE_SCHEMES``): one work per book,
its local id the OSIS book (``charles-eng/jub``), units are verses with the
Ge'ez works' refs (``Jub.3.2``, ``1En.1.1``), so each joins its Ge'ez book's
version group and its parallel rows by versification.  Its ``translation_of``
comes from ``scripture_translation_of.csv`` (``gez/jub``, ``gez/1en``).
Ingested as ``verses``, so no derived verses and no anchoring.  Jubilees's
Prologue is ``Jub.1.0`` (a superscription, as a psalm title).

Editorial material (#236): the section headings of the transcription
(Charles's analysis, "Paradise and the Fall (iii. 1-35 ...)", and Enoch's
book titles) open the next verse, marked ``heading``; Charles's and Box's
footnotes (Jubilees) and Charles's Anno Mundi dates in the margin are carried
in brackets at their place, marked ``note``.  The editions' introductions are
not ingested (as for the other Scripture sources' front matter).  Charles's
sigla (⌈ ⌉ for Greek-only words, ⌈⌈ ⌉⌉ for Ethiopic-only ones, † †, ( ) for
his supplements) are text.  The transcription of Enoch has no footnotes: the
1917 edition's few notes are not on the pages.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from patristica.models import Work
from scripts.ingest._sacred_texts import (
    BASE_URL,
    Page,
    SacredTextsParseError,
    fetch,
    mask,
    page_text,
    roman,
    unit,
)

log = logging.getLogger(__name__)

SOURCE_ID = "charles-eng"


@dataclass(frozen=True)
class Book:
    osis: str               # OSIS book code, the refs' prefix
    title: str
    directory: str          # under BASE_URL
    pages: tuple[str, ...]  # the pages with the text, in order
    chapters: int
    date_composed: int
    date_range: tuple[int, int]
    edition: str
    # Chapters start at "CHAPTER N" headings (Enoch), not at numbers in the text.
    chapter_headings: bool = False


BOOKS: tuple[Book, ...] = (
    Book(
        osis="Jub",
        title="Jubilees",
        directory="bib/jub",
        pages=tuple(f"jub{n:02d}.htm" for n in range(11, 88)),
        chapters=50,
        date_composed=-155,
        date_range=(-170, -140),
        edition=("R. H. Charles (tr.), The Book of Jubilees or the Little Genesis, with an introduction "
                 "by G. H. Box (Translations of Early Documents I.4; London: SPCK, 1917); translated "
                 "from the Ethiopic. Transcription: Internet Sacred Text Archive (J. B. Hare)."),
    ),
    Book(
        osis="1En",
        title="1 Enoch",
        directory="bib/boe",
        pages=tuple(f"boe{n:03d}.htm" for n in range(4, 113)),
        chapters=108,
        date_composed=-200,
        date_range=(-300, -100),
        edition=("R. H. Charles (tr.), The Book of Enoch, with an introduction by W. O. E. Oesterley "
                 "(Translations of Early Documents I.7; London: SPCK, 1917); translated from the "
                 "Ethiopic. Transcription: Internet Sacred Text Archive (J. B. Hare)."),
        chapter_headings=True,
    ),
)

# A verse number, or a chapter number before its first verse ("III. And ...").
_MARK_RE = re.compile(r"(?:(?<=[\s\[])|^)(?:([IVXLC]+)\.\s+)?(\d+)([a-z])? ?[.:](?:\s|(?=[A-Z⌈(]))")
_CHAPTER_ONLY_RE = re.compile(r"(?:(?<=\s)|^)([IVXLC]+)\.\s")
_CHAPTER_HEADING_RE = re.compile(r"^CHAPTER ([IVXLC]+)\.?$", re.I)
MAX_GAP = 3
_BARE_NUMBER_RE = re.compile(r"^(\d+) (?=[A-Z])")
_FN_AS_VERSE_RE = re.compile(r"\x05F\d+\|(\d+)\x06\.\s")
_BARE_MARK_RE = re.compile(r"(?:(?<=[\s\[])|^)(\d+)[a-z]?,? (?=[A-Z])")
_REF_LINE_RE = re.compile(r"^\([ivxlc]+\. \d[^()]*(?:\([^()]*\)[^()]*)*\)\.?$")
_SECTION_LINE_RE = re.compile(r"^\(?[IVXLC]+(?:\.|-[IVXLC]+\.?\)?)")

# Typos of the transcription that hide a chapter or verse number: (page, wrong, right).
TEXT_FIXES: tuple[tuple[str, str, str], ...] = (
    ("jub20.htm", "V1. And on the new moon", "VI. And on the new moon"),
    ("boe081.htm", "CHAPTER LXXVII.", "CHAPTER LXXVIII."),
    ("jub15.htm", "and covered his shame. 32. And God", "and covered his shame. 23. And God"),
    ("jub56.htm", "as my brother hath done. 19. Fear not", "as my brother hath done. 10. Fear not"),
)


def fix_page(name: str, src: str) -> str:
    for page, wrong, right in TEXT_FIXES:
        if page == name:
            if wrong not in src:
                raise SacredTextsParseError(f"{name}: fix {wrong!r} no longer applies")
            src = src.replace(wrong, right)
    return src


def split_verses(book: Book, pages: list[Page]) -> list[dict]:
    """The book's verses, from its pages in order.

    Verse numbers are found in sequence: the next verse (or up to
    ``MAX_GAP`` later, logged), or verse 1 of the next chapter, which a
    ``CHAPTER N`` heading (Enoch), a roman numeral ("III. And ..."), or a
    lone "1." after the chapter's last verse (Jubilees 1) announces.
    """
    records: list[dict] = []
    chapter, verse = 1, 0
    pending: list[str] = []          # headings for the next verse
    current: list[str] = []          # text of the current verse
    notes: dict[str, str] = {}
    used: set[tuple[int, int]] = set()
    ref = f"{book.osis}.1.0"

    def flush() -> None:
        nonlocal ref, verse
        text = re.sub(r"^\[\s+", "[", " ".join(current).strip())
        if text and book.chapter_headings and ref.endswith(".0"):
            # Text right after a CHAPTER heading, before any number: verse 1
            # (a one-verse chapter, or a number the transcription dropped).
            pending_for[ref[:-2] + ".1"] = pending_for.pop(ref, [])
            ref = ref[:-2] + ".1"
            verse = max(verse, 1)
        if text and not re.search(r"\w", text):
            log.warning("%s: stray %r dropped", ref, text)
            text = ""
        if text:
            records.append(unit(ref, text, notes, heading=" ".join(pending_for[ref]) or None))
        current.clear()

    pending_for: dict[str, list[str]] = {ref: []}

    for page in pages:  # a page's notes may be printed on the next page
        notes.update(page.notes)
    for page in pages:
        for kind, text in page.items:
            if kind == "H":
                m = _CHAPTER_HEADING_RE.match(text)
                if m:
                    new = roman(m.group(1))
                    if new == chapter and verse == 0:
                        continue
                    flush()
                    chapter, verse = new, 0
                    ref = f"{book.osis}.{chapter}.0"
                    pending_for[ref] = []
                    continue
                pending.append(text)
                continue
            if kind != "P":
                continue
            if (book.chapter_headings and _SECTION_LINE_RE.match(text) and len(text) < 120) \
                    or _REF_LINE_RE.match(text):
                # "LXXII. The Sun.", "(LXXII-LXXXII.)", "(i. 1-26: cf. Ex. xxiv. 15-18).":
                # part of a section title
                pending.append(text)
                continue
            text = text + " "  # line breaks stay: a verse of poetry may start a line
            bare = _BARE_NUMBER_RE.match(text)
            if bare and int(bare.group(1)) == verse + 1:
                text = f"{bare.group(1)}. {text[bare.end():]}"  # "2 And there was" (no period)
            masked = mask(text)
            if pending and not "".join(current).strip():
                first = _next_mark(masked, text, 0, chapter, verse, book.chapter_headings, used)
                if first is None or masked[:first[0]].strip(" [\n"):
                    # Headings before the first words of a unit that starts without a
                    # number (the Prologue) are its own.
                    pending_for.setdefault(ref, []).extend(pending)
                    pending.clear()
            pos = 0
            while True:
                m = _next_mark(masked, text, pos, chapter, verse, book.chapter_headings, used)
                if m is None:
                    current.append(text[pos:])
                    break
                start, end, new_ch, new_v = m
                before = text[pos:start]
                # Charles's bracket opening the verse ("[11. And ...") belongs to it.
                bracket = "[" if before.endswith("[") else ""
                current.append(before[:len(before) - len(bracket)])
                flush()
                if new_ch != chapter:
                    chapter = new_ch
                elif new_v > verse + 1:
                    log.warning("%s.%d: verses %d-%d missing", book.osis, chapter, verse + 1, new_v - 1)
                verse = new_v
                ref = f"{book.osis}.{chapter}.{verse}"
                if (chapter, verse) in used:
                    # A verse Charles splits and moves (51.5a, 51.5b): the later part keeps its letter.
                    letter = _MARK_RE.match(masked, start)
                    suffix = letter.group(3) if letter and letter.group(3) else ""
                    if not suffix:
                        raise SacredTextsParseError(f"{ref} twice")
                    ref += suffix
                used.add((chapter, verse))
                pending_for[ref] = pending[:]
                pending.clear()
                if bracket:
                    current.append(bracket)
                pos = end
    flush()
    # A verse "0" with nothing but a chapter heading is not a unit.
    if max(c for c, _ in used) != book.chapters:
        raise SacredTextsParseError(f"{book.osis}: {max(c for c, _ in used)} chapters, expected {book.chapters}")
    seen: set[str] = set()
    for rec in records:
        if rec["ref"] in seen:
            raise SacredTextsParseError(f"{rec['ref']} twice")
        seen.add(rec["ref"])
    return records


def _line_start(text: str, pos: int) -> bool:
    if pos > 0 and text[pos - 1] == "[":
        pos -= 1
    return pos == 0 or text[pos - 1] == "\n"


def _next_mark(masked: str, text: str, pos: int, chapter: int, verse: int, headings_only: bool = False,
               used: set[tuple[int, int]] | None = None) -> tuple[int, int, int, int] | None:
    """The earliest verse mark at or after *pos*: (start, end, chapter, verse).

    With *headings_only* (Enoch) only verses of the current chapter: the
    next ones (up to ``MAX_GAP``), or, at the start of a line, any verse not
    yet seen, since Charles cuts chapters into sections out of order (91, 93)
    and moves verses (60.25 after 60.6).  Otherwise also verse 1 of the next
    chapter, after a roman numeral or alone.  A number without its period
    ("2 And", "21, For") counts only for the next few verses.
    """
    used = used or set()
    found: tuple[int, int, int, int] | None = None
    for m in _MARK_RE.finditer(masked, pos):
        rom, num = m.group(1), int(m.group(2))
        hit = None
        if headings_only:
            if not rom and (verse < num <= verse + MAX_GAP
                            or (_line_start(masked, m.start()) and (chapter, num) not in used)):
                hit = (m.start(), m.end(), chapter, num)
        elif rom:
            if roman(rom) == chapter + 1 and num == 1:
                hit = (m.start(), m.end(), chapter + 1, 1)
            elif roman(rom) == chapter and verse == 0 and num == 1:
                hit = (m.start(), m.end(), chapter, 1)
        elif verse < num <= verse + MAX_GAP:
            hit = (m.start(), m.end(), chapter, num)
        elif num == 1 and verse > 1:
            hit = (m.start(), m.end(), chapter + 1, 1)
        if hit:
            found = hit
            break
    # A verse number the transcription made a footnote link ("other." [6]. And).
    for fn in _FN_AS_VERSE_RE.finditer(text, pos):
        if found and fn.start() >= found[0]:
            break
        if int(fn.group(1)) == verse + 1:
            found = (fn.end(1) + 1, fn.end(), chapter, verse + 1)
            break
    for bare in _BARE_MARK_RE.finditer(masked, pos):
        if found and bare.start() >= found[0]:
            break
        if verse < int(bare.group(1)) <= verse + MAX_GAP:
            found = (bare.start(), bare.end(), chapter, int(bare.group(1)))
            break
    if headings_only:
        return found
    # A roman numeral alone opens the next chapter's verse 1 ("XLIX. Remember ...").
    for m in _CHAPTER_ONLY_RE.finditer(masked, pos):
        if found and m.start() >= found[0]:
            break
        if roman(m.group(1)) == chapter + 1 and verse > 0:
            return m.start(), m.end(), chapter + 1, 1
    return found


def _work(book: Book) -> Work:
    return Work(
        work_id=f"{SOURCE_ID}/{book.osis.lower()}",
        source_id=SOURCE_ID,
        author=None,
        title=book.title,
        date_composed=book.date_composed,
        date_range=book.date_range,
        date_confidence="approximate",
        genre="apocrypha",
        language="eng",
        tradition="ethiopic",
        license="public_domain",
        provenance_url=f"{BASE_URL}{book.directory}/index.htm",
        edition=book.edition,
    )


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    out_dir = output_dir / SOURCE_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    works: list[Work] = []
    for book in BOOKS:
        out_path = out_dir / f"{book.osis.lower()}.json"
        if out_path.exists() and not force:
            works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
            continue
        pages = [page_text(fix_page(name, fetch(f"{book.directory}/{name}", output_dir, force=force)
                                    .read_text(encoding="utf-8", errors="replace")))
                 for name in book.pages]
        verses = split_verses(book, pages)
        work = _work(book)
        out_path.write_text(
            json.dumps({"work": work.model_dump(), "verses": verses}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("%s: %d verses", work.work_id, len(verses))
        works.append(work)
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
