"""
Ingestor for the Library of the Fathers English *Moralia in Job* of Gregory
the Great (#348).

Source: *Morals on the Book of Job, by S. Gregory the Great, translated with
notes and indices* (A Library of Fathers of the Holy Catholic Church 18, 21,
23, 31; Oxford: John Henry Parker, 1844–1850), translated by James Bliss with
Charles Marriott, as transcribed on Lectionary Central
(https://lectionarycentral.com/gregorymoraliaindex.html): one Word-exported
HTML page for the Epistle to Leander, one for the Preface and one per book
(Book01–Book35), cached in ``data/raw/_cache/lectionarycentral/``.
Language: eng  Tradition: latin  Genre: patristic  License: public_domain
(published 1844–50; the site states no terms of its own).

Works
-----
Two works, one per Migne volume of the Latin in the corpus (OGLT PL), each
``translation_of`` it:

- ``lf-moralia-eng/moralia-pars-1``: the Epistle, the Preface and Books I–XVI,
  the English of ``oglt-pl/gregorius-i-magnus/pl75_5_san`` (PL 75);
- ``lf-moralia-eng/moralia-pars-2``: Books XVII–XXXV, the English of
  ``oglt-pl/gregorius-i-magnus/pl76_0_san`` (PL 76).

Refs and units
--------------
The translation keeps the Benedictine division: Gregory's chapters as
bracketed Roman numerals (``[vii]``) and the sections numbered through each
book (``9.``). One unit per section, ``Greg.Mor.{book}.{chapter}.{section}``,
holding the section's paragraphs and the Job verse (the lemma) printed just
before it; a section belongs to the chapter in force where it starts. The
Preface is ``Greg.Mor.Praef.{chapter}.{section}``, the Epistle
``Greg.Mor.Ep.{n}`` (its paragraphs I–V), and the prefaces of Books IV and
XXVIII ``Greg.Mor.{book}.Praef.{n}`` (their paragraphs in order).

The transcription is not proof-read: some section and chapter numbers are
misprinted (``5.`` twice, ``[xix]`` for ``[xxix]``), and a Job verse quoted
with its number (``32. For He is not a man``) looks like a section. The numbers
kept are the longest increasing run (:func:`validate_numbers`); one outside it
fills a gap in that run when there is one (a misprint) and is ignored
otherwise.

Editorial material (#236)
-------------------------
- a page's title (part, book and the book's argument; "THE PREFACE, Wherein
  …") is one unit at ``Greg.Mor.{book}`` (``Greg.Mor.Ep``, ``Greg.Mor.Praef``),
  wholly ``title``;
- the translators' interpretation headings ("[MORAL INTERPRETATION]") start the
  next section's unit as ``heading`` spans;
- everything else in square brackets is the translators' or the transcriber's:
  Scripture references (``[Job 1, 1]``), Latin words (``[sensum]``), remarks
  (``[so Vulg.]``). Marked ``note``. A chapter marker that falls inside a
  section stays in place, also as a ``note``; one that starts a section is in
  the ref and dropped;
- the Epistle's notes ([a]–[d]) replace their markers, in brackets, as
  ``note``; the note after Book XXIX ("Note from §. 74 above") ends section 74.
- Letter markers of notes the transcription doesn't carry (``[c]``), the
  site's navigation links and rules are noise and dropped.
"""

from __future__ import annotations

import bisect
import json
import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag
from bs4.element import Comment

from patristica.models import Work
from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

SOURCE_ID = "lf-moralia-eng"

BASE_URL = "https://lectionarycentral.com/GregoryMoralia/"
INDEX_URL = "https://lectionarycentral.com/gregorymoraliaindex.html"
CACHE_DIR = Path("_cache") / "lectionarycentral"

#: Pages are Word-exported HTML in Windows-1252, with no charset declared.
ENCODING = "cp1252"

REF_PREFIX = "Greg.Mor"

EDITION = (
    "Morals on the Book of Job, by S. Gregory the Great, translated with notes and "
    "indices (A Library of Fathers of the Holy Catholic Church 18, 21, 23, 31; Oxford: "
    "John Henry Parker, 1844–1850), translated by James Bliss with Charles Marriott, "
    "from the Benedictine text; {part}. Transcription by Lectionary Central "
    "(lectionarycentral.com), which carries few of the translators' notes"
)


@dataclass(frozen=True)
class WorkSpec:
    slug: str
    title: str
    original: str
    pages: tuple[str, ...]
    part: str


WORKS: tuple[WorkSpec, ...] = (
    WorkSpec(
        "moralia-pars-1",
        "Morals on the Book of Job, Part I (Epistle, Preface, Books I–XVI)",
        "oglt-pl/gregorius-i-magnus/pl75_5_san",
        ("Epistle", "Preface") + tuple(f"Book{n:02d}" for n in range(1, 17)),
        "the Epistle, the Preface and Books I–XVI (vols. 1 and 2)",
    ),
    WorkSpec(
        "moralia-pars-2",
        "Morals on the Book of Job, Part II (Books XVII–XXXV)",
        "oglt-pl/gregorius-i-magnus/pl76_0_san",
        tuple(f"Book{n:02d}" for n in range(17, 36)),
        "Books XVII–XXXV (vols. 2 and 3)",
    ),
)


class MoraliaParseError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Paragraphs
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")
_RULE_RE = re.compile(r"^_{4,}$")
_ROMAN_RE = re.compile(r"^\[\s*([ivxlcIVXLC]+)\s*\.?\s*\]\s*")
_HEADING_WORD = r"[A-Z][A-Z /]*INTE[A-Z]*ON"
_HEADING_RE = re.compile(rf"^\[\s*({_HEADING_WORD})\s*\.?\s*\]\s*")
_BARE_HEADING_RE = re.compile(rf"^({_HEADING_WORD})\s*\.?$")
_LETTER_MARK_RE = re.compile(r"\s?\[([a-z])\]")
_SECTION_RE = re.compile(r"^(\d+)\s*[.,]\s+")
_EPISTLE_RE = re.compile(r"^([IVX]+)\.\s+")
_BOOK_RE = re.compile(r"^BOOK\s+([IVXL]+)\.?$")
_PART_RE = re.compile(r"^VOLUME\s+[IVX]+\s*-\s*(THE\s+\w+\s+PART)\.?$")
_PREFACE_RE = re.compile(r"^(THE\s+)?PREFACE[.,]?$")
_LEMMA_RE = re.compile(r"^(Ver|Chap)\b")
_NOTE_RE = re.compile(r"^\[([a-z])\]\s*")
_SECTION_NOTE_RE = re.compile(r"^Note from §\.?\s*(\d+) above:?$")
_BRACKET_RE = re.compile(r"\[[^\[\]]*\]")

#: An unnumbered paragraph this short, just before a section, is the Job verse
#: Gregory expounds there (the lemma), not the end of the section before.
LEMMA_MAX_CHARS = 250

#: A book's argument is one paragraph or several short lines (the printed
#: line breaks); a long paragraph after them is the book's opening.
ARGUMENT_LINE_MAX_CHARS = 300

_ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}


def roman(s: str) -> int:
    s = s.lower()
    total = 0
    for i, ch in enumerate(s):
        v = _ROMAN[ch]
        total += -v if i + 1 < len(s) and _ROMAN[s[i + 1]] > v else v
    return total


def _is_nav(node: NavigableString) -> bool:
    """Text inside a link to another page (the site's navigation)."""
    for parent in node.parents:
        if isinstance(parent, Tag) and parent.name == "a":
            href = parent.get("href") or ""
            return bool(href) and not href.startswith("#")
    return False


def paragraphs(html_text: str) -> list[str]:
    """The page's paragraphs in order, whitespace collapsed, navigation dropped.

    Text outside any ``<p>`` (the HTML of Book X loses a tag) is a paragraph of
    its own.
    """
    soup = BeautifulSoup(html_text, "lxml")
    body = soup.body
    if body is None:
        raise MoraliaParseError("no <body>")
    for tag in body.find_all(["script", "style"]):
        tag.decompose()
    blocks: list[list[str]] = []
    keys: list[object] = []
    for node in body.descendants:
        if not isinstance(node, NavigableString) or isinstance(node, Comment):
            continue
        p = node.find_parent("p")
        key: object = p if p is not None else "stray"
        if not keys or keys[-1] is not key:
            keys.append(key)
            blocks.append([])
        if not _is_nav(node):
            blocks[-1].append(str(node))
    out = []
    for parts in blocks:
        text = _WS_RE.sub(" ", "".join(parts).replace("\xa0", " ")).strip()
        if text:
            out.append(text)
    return out


# ---------------------------------------------------------------------------
# Number validation
# ---------------------------------------------------------------------------

def validate_numbers(nums: list[int | None]) -> list[int | None]:
    """Section (or chapter) numbers as printed → the numbers to keep.

    The longest strictly increasing run of the printed numbers is kept. A
    number outside it takes the next free number of a gap in that run (a
    misprint: ``5, 5, 7`` → ``5, 6, 7``) and is dropped (``None``) where the
    run has no gap there (``58, 32, 59``: a verse number, not a section).
    """
    idx = [i for i, n in enumerate(nums) if n is not None]
    vals = [nums[i] for i in idx]
    # Longest strictly increasing subsequence (patience, O(n log n)).
    tails: list[int] = []
    tails_at: list[int] = []
    prev: list[int] = [-1] * len(vals)
    for k, v in enumerate(vals):
        pos = bisect.bisect_left(tails, v)
        if pos < len(tails) and tails[pos] == v:
            continue  # a repeated number: the first one stays in the run
        if pos == len(tails):
            tails.append(v)
            tails_at.append(k)
        else:
            tails[pos] = v
            tails_at[pos] = k
        prev[k] = tails_at[pos - 1] if pos > 0 else -1
    keep: set[int] = set()
    k = tails_at[-1] if tails_at else -1
    while k >= 0:
        keep.add(k)
        k = prev[k]
    out: list[int | None] = [None] * len(nums)
    for k in keep:
        out[idx[k]] = vals[k]
    # Fill gaps with the misprinted numbers.
    last = 0
    for pos, i in enumerate(idx):
        if pos in keep:
            last = vals[pos]
            continue
        nxt = next((vals[q] for q in range(pos + 1, len(vals)) if q in keep), None)
        if nxt is None or nxt - last >= 2:
            last += 1
            out[i] = last
    return out


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

@dataclass
class Unit:
    ref: str
    pieces: list[tuple[str, str | None]] = field(default_factory=list)

    def add(self, text: str, kind: str | None = None) -> None:
        text = text.strip()
        if text:
            self.pieces.append((text, kind))

    def record(self) -> dict:
        text = ""
        spans: list[list] = []
        for piece, kind in self.pieces:
            if text:
                text += " "
            start = len(text)
            text += piece
            if kind is not None:
                spans.append([start, len(text), kind])
            else:
                for m in _BRACKET_RE.finditer(piece):
                    spans.append([start + m.start(), start + m.end(), "note"])
        rec: dict = {"ref": self.ref, "text": text}
        if spans:
            rec["editorial"] = spans
        return rec


@dataclass
class _Para:
    """One body paragraph: its leading chapter markers and headings, its text."""

    chapters: list[int]
    headings: list[str]
    text: str
    number: int | None = None  # printed section number
    section: int | None = None  # kept section number


def _split_markers(text: str) -> _Para:
    chapters: list[int] = []
    headings: list[str] = []
    while True:
        m = _ROMAN_RE.match(text)
        if m:
            chapters.append(roman(m.group(1)))
            text = text[m.end():]
            continue
        m = _HEADING_RE.match(text)
        if m:
            headings.append(m.group(1))
            text = text[m.end():]
            continue
        break
    m = _BARE_HEADING_RE.match(text)
    if m:
        headings.append(m.group(1))
        text = ""
    m = _SECTION_RE.match(text)
    return _Para(chapters, headings, text, int(m.group(1)) if m else None)


@dataclass
class PageResult:
    key: str               # "Ep", "Praef" or the book number
    part: str | None       # "THE FIRST PART", as the page heads it
    title: str             # "BOOK I." / "THE PREFACE,"
    argument: str
    units: list[Unit]


def _header(paras: list[str]) -> tuple[str | None, str, str, list[str], int]:
    """(part, title, key, argument lines, index of the first body paragraph)."""
    part: str | None = None
    for i, p in enumerate(paras):
        m = _PART_RE.match(p)
        if m:
            part = m.group(1)
            continue
        m = _BOOK_RE.match(p)
        if m or p in ("THE EPISTLE,", "THE PREFACE,"):
            key = str(roman(m.group(1))) if m else ("Ep" if "EPISTLE" in p else "Praef")
            argument: list[str] = []
            j = i + 1
            while j < len(paras):
                q = paras[j]
                if _RULE_RE.match(q):
                    j += 1
                    break
                para = _split_markers(q)
                if (para.chapters or para.headings or para.number is not None
                        or _LEMMA_RE.match(q) or _PREFACE_RE.match(q)):
                    break
                if argument and len(q) >= ARGUMENT_LINE_MAX_CHARS:
                    break  # the book's unnumbered opening (Books XVIII, XXXV)
                argument.append(q)
                j += 1
            return part, p, key, argument, j
    raise MoraliaParseError("no BOOK / EPISTLE / PREFACE heading")


def _strip_letter_marks(text: str) -> str:
    return _LETTER_MARK_RE.sub("", text)


def _epistle_units(body: list[str], prefix: str) -> list[Unit]:
    """The Epistle: the address and paragraphs I–V, its notes [a]–[d] in place."""
    notes: dict[str, str] = {}
    main: list[str] = []
    in_notes = False
    last_note: str | None = None
    for p in body:
        if _RULE_RE.match(p):
            in_notes = True
            continue
        if not in_notes:
            main.append(p)
            continue
        m = _NOTE_RE.match(p)
        if m:
            last_note = m.group(1)
            notes[last_note] = p[m.end():]
        elif last_note is not None:
            notes[last_note] += " " + p
    units: list[Unit] = []
    address: list[str] = []
    used: set[str] = set()

    def with_notes(text: str) -> str:
        def repl(m: re.Match) -> str:
            letter = m.group(1)
            if letter not in notes:
                return ""
            used.add(letter)
            note = notes[letter].replace("[", "(").replace("]", ")")
            return f" [{note}]"
        return _LETTER_MARK_RE.sub(repl, text)

    for p in main:
        m = _EPISTLE_RE.match(p)
        if m is None:
            if units:
                units[-1].add(with_notes(p))
            else:
                address.append(with_notes(p))
            continue
        n = roman(m.group(1))
        if n != len(units) + 1:
            raise MoraliaParseError(f"Epistle paragraph {m.group(1)} out of order")
        unit = Unit(f"{prefix}.{n}")
        for a in address:
            unit.add(a)
        address = []
        unit.add(with_notes(p[m.end():]))
        units.append(unit)
    # A note whose marker the transcription lost ([e], cut off after one word).
    for letter in sorted(set(notes) - used):
        log.debug("Epistle: note [%s] has no marker (%r); left out", letter, notes[letter][:40])
    return units


def _body_units(body: list[str], prefix: str, book: str) -> list[Unit]:
    units: list[Unit] = []
    # Book preface (Books IV and XXVIII): its paragraphs, numbered in order.
    if body and _PREFACE_RE.match(body[0]):
        heading = body[0].rstrip(".,")
        marks: list[int] = []
        k = 1
        while k < len(body):
            para = _split_markers(body[k])
            if (para.headings or 1 in para.chapters or _LEMMA_RE.match(para.text)):
                break
            text = _strip_letter_marks(para.text)
            if para.number is not None:
                text = text[_SECTION_RE.match(text).end():]  # type: ignore[union-attr]
            marks.extend(para.chapters)
            k += 1
            if not text:
                continue
            unit = Unit(f"{prefix}.Praef.{len(units) + 1}")
            if not units:
                unit.add(heading, "heading")
            for c in marks:
                unit.add(f"[{_roman_str(c)}]", "note")
            marks = []
            unit.add(text)
            units.append(unit)
        body = body[k:]

    # Trailing note after a rule ("Note from §. 74 above:").
    tail_notes: dict[int, list[str]] = {}
    paras: list[_Para] = []
    in_tail: int | None = None
    started = False
    for p in body:
        if _RULE_RE.match(p):
            if started:
                in_tail = -1
            continue
        if in_tail is not None:
            m = _SECTION_NOTE_RE.match(p)
            if m:
                in_tail = int(m.group(1))
                tail_notes[in_tail] = []
            elif in_tail < 0:
                raise MoraliaParseError(f"{book}: text after the closing rule: {p[:60]!r}")
            else:
                tail_notes[in_tail].append(p)
            continue
        para = _split_markers(p)
        para.text = _strip_letter_marks(para.text)
        paras.append(para)
        if para.text:
            started = True

    for para, kept in zip(paras, validate_numbers([p.number for p in paras])):
        para.section = kept
        if kept is None:
            para.number = None
        elif para.number is not None:
            para.text = para.text[_SECTION_RE.match(para.text).end():]  # type: ignore[union-attr]
    chapter_kept = validate_numbers([c for p in paras for c in p.chapters])
    it = iter(chapter_kept)
    para_chapters = [[k for k in (next(it) for _ in p.chapters) if k is not None] for p in paras]

    def next_body(i: int) -> _Para | None:
        for q in paras[i + 1:]:
            if q.text:
                return q
        return None

    chapter = 1
    last_section = 0
    current: Unit | None = None
    pending_heads: list[str] = []
    pending_lemma: list[str] = []
    pending_marks: list[int] = []
    sections: dict[int, Unit] = {}

    def start(n: int) -> Unit:
        nonlocal current, last_section
        unit = Unit(f"{prefix}.{chapter}.{n}")
        for h in pending_heads:
            unit.add(h, "heading")
        for lemma in pending_lemma:
            unit.add(lemma)
        pending_heads.clear()
        pending_lemma.clear()
        pending_marks.clear()
        units.append(unit)
        sections[n] = unit
        current = unit
        last_section = n
        return unit

    for i, para in enumerate(paras):
        for c in para_chapters[i]:
            chapter = c
            pending_marks.append(c)
        pending_heads.extend(para.headings)
        if not para.text:
            continue
        if para.section is not None:
            start(para.section).add(para.text)
            continue
        nxt = next_body(i)
        is_lemma = (nxt is not None and nxt.section is not None
                    and (_LEMMA_RE.match(para.text) is not None or len(para.text) < LEMMA_MAX_CHARS))
        if is_lemma:
            pending_lemma.append(para.text)
            continue
        if current is None:
            # Text before the first numbered section: section 1 when the
            # numbering starts at 2 (Book VI), else the opening of section 1
            # (Book XII's introduction, printed before "1.").
            first = next((q.section for q in paras[i + 1:] if q.section is not None), None)
            if first == last_section + 1:
                pending_lemma.append(para.text)
            else:
                start(last_section + 1).add(para.text)
            continue
        # Continuation of the current section (or a lemma that isn't one).
        for lemma in pending_lemma:
            current.add(lemma)
        pending_lemma.clear()
        for c in pending_marks:
            current.add(f"[{_roman_str(c)}]", "note")
        pending_marks.clear()
        for h in pending_heads:
            current.add(h, "heading")
        pending_heads.clear()
        current.add(para.text)
    if current is not None:
        for lemma in pending_lemma:
            current.add(lemma)
    if pending_heads:
        raise MoraliaParseError(f"{book}: heading {pending_heads} with no text after it")

    for n, lines in tail_notes.items():
        if n not in sections:
            raise MoraliaParseError(f"{book}: note on §{n}, which isn't a section")
        sections[n].add("[Note: " + " ".join(lines) + "]", "note")
    return units


def _roman_str(n: int) -> str:
    out = ""
    for v, s in ((100, "c"), (90, "xc"), (50, "l"), (40, "xl"), (10, "x"), (9, "ix"),
                 (5, "v"), (4, "iv"), (1, "i")):
        while n >= v:
            out += s
            n -= v
    return out


def parse_page(html_text: str) -> PageResult:
    paras = paragraphs(html_text)
    part, title, key, argument, start = _header(paras)
    body = paras[start:]
    prefix = f"{REF_PREFIX}.{key}"
    if key == "Ep":
        units = _epistle_units(body, prefix)
    else:
        units = _body_units(body, prefix, key)
    if not units:
        raise MoraliaParseError(f"{key}: no text")
    return PageResult(key, part, title, " ".join(argument), units)


def page_records(page: PageResult, previous_part: str | None) -> list[dict]:
    """The page's raw units: its title, then its sections."""
    heading = Unit(f"{REF_PREFIX}.{page.key}")
    title = page.title.rstrip(",")
    if page.part and page.part != previous_part:
        title = f"{page.part}. {title}"
    if page.argument:
        title = f"{title.rstrip('.')}. {page.argument}"
    heading.add(title, "title")
    return [heading.record()] + [u.record() for u in page.units]


# ---------------------------------------------------------------------------
# Works
# ---------------------------------------------------------------------------

def page_url(page: str) -> str:
    return f"{BASE_URL}{page}.html"


def fetch(page: str, output_dir: Path, force: bool = False) -> Path:
    dest = output_dir / CACHE_DIR / f"{page}.html"
    existed = dest.exists()
    path = download_file(page_url(page), dest, force=force)
    if not existed:
        time.sleep(1.0)  # be polite to a small site
    return path


def _work(spec: WorkSpec) -> Work:
    return Work(
        work_id=f"{SOURCE_ID}/{spec.slug}",
        source_id=SOURCE_ID,
        author="Gregory the Great",
        title=spec.title,
        date_composed=586,
        date_range=(578, 595),
        date_confidence="approximate",
        genre="patristic",
        language="eng",
        tradition="latin",
        license="public_domain",
        provenance_url=INDEX_URL,
        edition=EDITION.format(part=spec.part),
        translation_of=spec.original,
    )


def work_records(spec: WorkSpec, pages: dict[str, str]) -> list[dict]:
    records: list[dict] = []
    part: str | None = None
    for name in spec.pages:
        page = parse_page(pages[name])
        records.extend(page_records(page, part))
        part = page.part or part
    refs = [r["ref"] for r in records]
    if len(set(refs)) != len(refs):
        dup = sorted({r for r in refs if refs.count(r) > 1})
        raise MoraliaParseError(f"{spec.slug}: duplicate refs {dup[:5]}")
    return records


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    out_dir = output_dir / SOURCE_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    works: list[Work] = []
    for spec in WORKS:
        out_path = out_dir / f"{spec.slug}.json"
        if out_path.exists() and not force:
            works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
            continue
        pages = {name: fetch(name, output_dir, force=force).read_bytes().decode(ENCODING)
                 for name in spec.pages}
        records = work_records(spec, pages)
        work = _work(spec)
        out_path.write_text(
            json.dumps({"work": work.model_dump(), "paragraphs": records},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("%s: %d units", work.work_id, len(records))
        works.append(work)
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
