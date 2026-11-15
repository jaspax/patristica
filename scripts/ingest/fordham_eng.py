"""
Ingestor for English translations on Paul Halsall's *Internet Medieval
Sourcebook* (Fordham University, sourcebooks.fordham.edu; #352).

Output: ``data/raw/fordham-eng/{slug}.json``
Language: eng  Genre: patristic (overrides in genre_overrides.csv)
License: academic-noncommercial (the transcriptions' non-commercial terms, #696)

Three works, each an English translation linked to its original
(``translation_of``):

- Mark the Deacon, *Life of Porphyry, Bishop of Gaza*, tr. G. F. Hill
  (Oxford, 1913), complete; of ``first1k/tlg2806/tlg001/1st1K-grc1``.
  Units are Hill's 103 chapters (``VPorph.{chapter}.{paragraph}``).
- Gregory of Tours, *History of the Franks*, tr. Ernest Brehaut (New York,
  1916), abridged selections; of ``oglt-pl/gregorius-turonensis/pl71_0_s.``.
  Units are ``HF.{book}.{chapter}.{paragraph}``; a book's chapter list and
  prologue are chapter 0, Gregory's preface is ``HF.0.{n}``.
- Isidore of Seville, *Etymologiae*, the extracts Brehaut translated in *An
  Encyclopedist of the Dark Ages* (New York, 1912), selections; of
  ``oglt-pl/isidorus-hispalensis/pl82_0_san``.  Fordham hosts David Badke's
  digital edition (bestiary.ca, 2003) as a PDF; only Brehaut's translated
  extracts are taken, not his study (Part I) or his per-book introductions
  and analyses.  Units are ``Etym.{book}.{chapter}.{section}`` with Isidore's
  own numbering, ``Etym.{book}.{chapter}`` the chapter's heading.

Not ingested: Robinson's two paragraphs of Gelasius I, *Duo sunt* (Ep. 12,
source/gelasius1.asp).  Its only Latin is ``oglt-pl/gelasius-i/pl59_0_gel``,
a container of Gelasius's letters and decrees, which a translation of one
letter may not be linked to (#341); unlinked, two paragraphs would add nothing.

Editorial material (#236):

- The translators' prefaces and introductions (Hill's, with his
  bibliography; Brehaut's to Gregory) are kept as wholly editorial units
  (``note``; their headings ``heading``): ``VPorph.int.{n}``, ``HF.int.{n}``.
- Hill's notes, printed after each chapter, are one wholly editorial unit at
  the end of the chapter.  Brehaut's footnotes (Gregory: inserted by Halsall
  as ``[note: ...]``; Isidore: the PDF's footnotes) are carried inline, in
  brackets, marked ``note``.
- Halsall's Scripture references (``[Eph. 6:13]``) are marked ``note``.
- Brehaut's bracketed summaries of the Gregory chapters he did not translate
  (``[7. Abraham ... 8. Isaac ...]``) are wholly editorial units (``note``).
- Gregory's incipits and explicits ("HERE BEGINS THE FIRST BOOK ...") are
  ``heading`` units; his chapter lists are text, as in the Latin.
- Halsall's own additions are left out (his introductions, comments in
  ``{braces}``, "Additional information" and bibliographies), as are page
  markers (Hill's Teubner pages ``T12``, Brehaut's ``[96]``).  So is Book
  VIII, ch. 20 of Gregory, which Halsall inserted from another source (the
  Latin and a later translation), not Brehaut.

Licence: the pages' footers say the Sourcebook is "a collection of public
domain and copy-permitted texts" and claim copyright in "the specific
electronic form" (non-commercial permission); the PDF claims the same for
Badke's digital edition.  The translations (1912, 1913, 1916) are public
domain in the US, and the transcribers' own additions are not ingested
(above), but to be on the safe side the works follow the transcriptions'
terms: ``academic-noncommercial``, the source's own terms (owner's decision,
#696).
"""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from patristica.models import Work
from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

SOURCE_ID = "fordham-eng"
BASE_URL = "https://sourcebooks.fordham.edu/"
CACHE_DIR = Path("_cache") / "fordham"

_SOURCEBOOK = "Internet Medieval Sourcebook (Paul Halsall, Fordham University)"


class FordhamParseError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

@dataclass
class Unit:
    ref: str
    text: str
    spans: list[list] = field(default_factory=list)

    def record(self) -> dict:
        rec: dict = {"ref": self.ref, "text": self.text}
        if self.spans:
            rec["editorial"] = self.spans
        return rec


_WS_RE = re.compile(r"\s+")


class _Builder:
    """Text with editorial spans, whitespace collapsed as it is built."""

    def __init__(self) -> None:
        self.text = ""
        self.spans: list[list] = []

    def add(self, piece: str, kind: str | None = None) -> None:
        piece = _WS_RE.sub(" ", piece)
        if not piece.strip():
            if piece and self.text and not self.text.endswith(" "):
                self.text += " "
            return
        if not self.text or self.text.endswith(" "):
            piece = piece.lstrip()
        if kind is None:
            self.text += piece
            return
        piece = piece.strip()
        if self.text and not self.text.endswith(" ") and not self.text.endswith(("(", "“", '"')):
            self.text += " "
        self.spans.append([len(self.text), len(self.text) + len(piece), kind])
        self.text += piece

    def unit(self, ref: str) -> Unit:
        text = self.text.strip()
        lead = len(self.text) - len(self.text.lstrip())
        spans = [[s - lead, min(e - lead, len(text)), k] for s, e, k in self.spans]
        # Punctuation glued to a span's end ("[note]." ) needs no space before it.
        text = re.sub(r" +([.,;:!?)])", r"\1", text) if not spans else text
        return Unit(ref, text, [sp for sp in spans if sp[0] < sp[1]])


def _whole(ref: str, text: str, kind: str) -> Unit:
    text = _WS_RE.sub(" ", text).strip()
    return Unit(ref, text, [[0, len(text), kind]])


# ---------------------------------------------------------------------------
# HTML pages: blocks with bold/italic sentinels
# ---------------------------------------------------------------------------

B, B_END, I, I_END = "\x01", "\x02", "\x03", "\x04"
_SENTINELS = re.compile("[\x01-\x04]")
_BLOCK_TAG = re.compile(
    r"(?is)</?(?:p|blockquote|center|h[1-6]|hr|li|ul|ol|div|table|tr|td)\b[^>]*>")


def html_blocks(src: str) -> list[str]:
    """The page's text blocks (paragraphs, list items, centred lines) in order.

    Bold and italic are kept as sentinels (``B``/``B_END``, ``I``/``I_END``),
    since chapter numbers are bold and notes' lemmata italic.  Whitespace is
    collapsed; ``<br>`` is a space.  The pages write a hyphen as a soft
    hyphen (``&#173;``: "eye&#173;witness"), so it becomes ``-``.
    """
    src = re.sub(r"(?is)<(script|style)\b.*?</\1>", "", src)
    src = re.sub(r"(?s)<!--.*?-->", "", src)
    src = _BLOCK_TAG.sub("\n\n", src)
    src = re.sub(r"(?i)<br\s*/?>", " ", src)
    src = re.sub(r"(?i)<(?:b|strong)\b[^>]*>", B, src)
    src = re.sub(r"(?i)</(?:b|strong)>", B_END, src)
    src = re.sub(r"(?i)<(?:i|em)\b[^>]*>", I, src)
    src = re.sub(r"(?i)</(?:i|em)>", I_END, src)
    src = re.sub(r"<[^>]+>", "", src)
    src = html.unescape(src).replace("\xad", "-")
    blocks = []
    for blk in re.split(r"\n\s*\n", src):
        text = _WS_RE.sub(" ", blk).strip()
        if plain(text):
            blocks.append(text)
    return blocks


def plain(block: str) -> str:
    return _WS_RE.sub(" ", _SENTINELS.sub("", block)).strip()


_BRACES_RE = re.compile(r"\s*\{[^{}]*\}")
_SCRIPTURE_RE = re.compile(
    r"\[(?:cf\. ?)?(?:[1-4] ?)?[A-Z][a-z]+\.? ?\d+[:.]\d+(?:[-–,;: ]+(?:[1-4] ?)?(?:[A-Z][a-z]+\.? ?)?\d+(?:[:.]\d+)?)*\]")


def _bracket_end(text: str, start: int) -> int:
    """Index just past the ``]`` closing the ``[`` at *start* (nesting)."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
            if depth == 0:
                return i + 1
    raise FordhamParseError(f"unclosed bracket: {text[start:start + 80]!r}")


_NOTE_START_RE = re.compile(r"\[\s*note\s*:\s*", re.I)


def inline_unit(ref: str, block: str) -> Unit:
    """A text paragraph: ``[note: …]`` and Scripture refs marked ``note``,
    Halsall's ``{comments}`` and Hill's ``T12`` page markers dropped."""
    block = re.sub(B + r"\s*T\d+\s*" + B_END, " ", block)
    text = plain(block)
    text = _BRACES_RE.sub("", text)
    b = _Builder()
    pos = 0
    while pos < len(text):
        note = _NOTE_START_RE.search(text, pos)
        scrip = _SCRIPTURE_RE.search(text, pos)
        hits = [m for m in (note, scrip) if m]
        if not hits:
            b.add(text[pos:])
            break
        m = min(hits, key=lambda m: m.start())
        b.add(text[pos:m.start()])
        if m is note:
            end = _bracket_end(text, m.start())
            b.add("[" + text[m.end():end - 1].strip() + "]", "note")
        else:
            end = m.end()
            b.add(m.group(0), "note")
        pos = end
    return b.unit(ref)


def _chapter_number(block: str) -> tuple[int, str] | None:
    """``«12.»`` alone, or ``«48.» text``: the chapter number and the rest."""
    m = re.match(B + r"\s*(\d+)\s*\.\s*" + B_END + r"\s*(.*)$", block)
    if not m:
        return None
    return int(m.group(1)), m.group(2)


# ---------------------------------------------------------------------------
# Mark the Deacon, Life of Porphyry (Hill)
# ---------------------------------------------------------------------------

def _front_matter(prefix: str, blocks: list[str]) -> list[Unit]:
    """A translator's preface or introduction: wholly editorial units."""
    units = []
    for n, blk in enumerate(blocks, 1):
        text = _BRACES_RE.sub("", plain(blk)).strip()
        bold = blk.startswith(B) and blk.rstrip().endswith(B_END)
        heading = len(text) < 60 and (text.isupper() or bold)
        units.append(_whole(f"{prefix}.int.{n}", text, "heading" if heading else "note"))
    return units


def parse_porphyry(blocks: list[str]) -> list[Unit]:
    texts = [plain(b) for b in blocks]
    try:
        start = texts.index("PREFACE")
        life = next(i for i, t in enumerate(texts) if t.startswith("THE LIFE OF SAINT PORPHYRY"))
        end = next(i for i, t in enumerate(texts) if t.startswith("Additional Information on"))
    except (ValueError, StopIteration) as exc:
        raise FordhamParseError("Porphyry: page structure not found") from exc

    units = _front_matter("VPorph", blocks[start:life])
    chapter = para = 0
    in_notes = False
    for blk, text in zip(blocks[life + 1:end], texts[life + 1:end]):
        num = _chapter_number(blk)
        if num and not num[1]:
            if num[0] != chapter + 1:
                raise FordhamParseError(f"Porphyry: chapter {num[0]} after {chapter}")
            chapter, para, in_notes = num[0], 0, False
            continue
        if chapter == 0:
            raise FordhamParseError(f"Porphyry: text before chapter 1: {text[:60]!r}")
        if text == "NOTES:":
            in_notes = True
            continue
        para += 1
        ref = f"VPorph.{chapter}.{para}"
        if in_notes:
            units.append(_whole(ref, "Notes: " + _BRACES_RE.sub("", text), "note"))
        else:
            units.append(inline_unit(ref, blk))
    if chapter != 103:
        raise FordhamParseError(f"Porphyry: {chapter} chapters, expected 103")
    return units


# ---------------------------------------------------------------------------
# Gregory of Tours, History of the Franks (Brehaut)
# ---------------------------------------------------------------------------

_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8,
          "IX": 9, "X": 10}
_BOOK_RE = re.compile(r"^BOOK ([IVX]+)$")
_RUBRIC_RE = re.compile(r"^(?:IN CHRIST'S NA\w+ |THE NAME OF OUR LORD JESUS CHRIST )?HERE (?:BEGIN|END)|^IN CHRIST'S NAME$|^-+$")

# Chapters Halsall inserted from elsewhere (not Brehaut): (book, chapter).
GREGORY_SKIP = {(8, 20)}


def parse_gregory(blocks: list[str]) -> list[Unit]:
    texts = [plain(b) for b in blocks]
    try:
        intro = texts.index("INTRODUCTION")
        eb = texts.index("E. B.", intro)
        preface = texts.index("PREFACE", eb)
        end = texts.index("Source:", preface)
    except ValueError as exc:
        raise FordhamParseError("Gregory: page structure not found") from exc
    if not texts[intro + 1].startswith("By Earnest Brehaut"):
        raise FordhamParseError(f"Gregory: unexpected introduction byline {texts[intro + 1]!r}")
    # Brehaut's introduction, without Halsall's bracketed warning after the byline.
    intro_blocks = [b for b in blocks[intro:eb + 1]
                    if not plain(b).startswith("[Note: Many of Brehaut")]
    units = _front_matter("HF", intro_blocks)

    book = chapter = para = 0
    in_capitula = False
    capitula: list[str] = []
    skipping = False

    def flush_capitula() -> None:
        nonlocal para
        if capitula:
            para += 1
            units.append(Unit(f"HF.{book}.0.{para}", " ".join(capitula)))
            capitula.clear()

    for blk, text in zip(blocks[preface + 1:end], texts[preface + 1:end]):
        m = _BOOK_RE.match(text)
        if m:
            flush_capitula()
            new = _ROMAN[m.group(1)]
            if new != book + 1:
                raise FordhamParseError(f"Gregory: book {new} after {book}")
            book, chapter, para, skipping = new, 0, 0, False
            units.append(_whole(f"HF.{book}", f"Book {m.group(1)}", "heading"))
            continue
        if _RUBRIC_RE.match(text):
            if set(text) <= {"-"}:
                continue
            if in_capitula:  # the list ends at the next rubric (Book IX has no explicit)
                flush_capitula()
                in_capitula = False
            if "BEGIN THE CHAPTERS" in text:
                in_capitula = True
            para += 1
            units.append(_whole(f"HF.{book}.{chapter}.{para}" if book else f"HF.0.{para}",
                                text, "heading"))
            continue
        if in_capitula:
            capitula.append(text)
            continue
        if text.startswith("[") and text.endswith("]") and not _NOTE_START_RE.match(text):
            # Brehaut's summary of chapters he did not translate.
            if text.startswith("[-see article"):
                continue  # Halsall's pointer after the inserted VIII 20
            skipping = False
            first = re.match(r"\[\s*(\d+)", text)
            if first and book and int(first.group(1)) > chapter:
                chapter, para = int(first.group(1)), 0  # filed under the first chapter it covers
            para += 1
            units.append(_whole(f"HF.{book}.{chapter}.{para}", text, "note"))
            continue
        num = _chapter_number(blk)
        if num and book:
            if num[0] < chapter:
                raise FordhamParseError(f"Gregory: book {book}, chapter {num[0]} after {chapter}")
            if num[0] > chapter:  # equal: translated after Brehaut's summary of its start
                chapter, para = num[0], 0
            skipping = (book, chapter) in GREGORY_SKIP
            if not num[1] or skipping:
                continue
            blk = num[1]
        if skipping:
            continue
        para += 1
        ref = f"HF.{book}.{chapter}.{para}" if book else f"HF.0.{para}"
        units.append(inline_unit(ref, blk))
    flush_capitula()
    if book != 10:
        raise FordhamParseError(f"Gregory: {book} books, expected 10")
    return units


# ---------------------------------------------------------------------------
# Isidore, Etymologiae: Brehaut's extracts (PDF of Badke's digital edition)
# ---------------------------------------------------------------------------

@dataclass
class Run:
    """Consecutive characters of one font size on a PDF line."""
    size: float
    text: str


@dataclass
class Line:
    page: int
    x: float
    y: float
    runs: list[Run]

    @property
    def text(self) -> str:
        return "".join(r.text for r in self.runs)

    @property
    def max_size(self) -> float:
        return max((r.size for r in self.runs if r.text.strip()), default=0.0)


BODY_SIZE = 9.0      # body text is 11 pt (small caps 9, headings 10 and 13)
NOTE_SIZE = 8.0      # footnotes, page numbers, print-page markers [96]
MARK_SIZE = 6.5      # footnote numbers (superscript in the text, labels below)
INDENT_X = 118.0     # a paragraph's first line is indented (122 vs 112)
CENTRE_X = 200.0     # headings are centred

_PRINT_PAGE_RE = re.compile(r"\s*\[\d+\]\s*")
_ROMAN_ANY = re.compile(r"^M{0,3}(CM|CD|D?C{0,3})(XC|XL|L?X{0,3})(IX|IV|V?I{0,3})$")
_ETYM_BOOK_RE = re.compile(r"^BOOKS? ([IVXL]+)\b")
_ETYM_CHAPTER_RE = re.compile(r"^(?:Book ([IVXL]+), )?Chapter (\d+)\.(?: |$)")
_ETYM_SECTION_RE = re.compile(r"^(\d+)\.\s+")


def _roman(s: str) -> int:
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
    total = 0
    for a, b in zip(s, s[1:] + " "):
        total += -vals[a] if vals.get(b, 0) > vals[a] else vals[a]
    return total


def _is_mark(run: Run) -> bool:
    return abs(run.size - MARK_SIZE) < 0.6 and run.text.strip().isdigit()


def pdf_notes(lines: list[Line]) -> dict[int, str]:
    """Footnote number → text, from the small print at the foot of each page.

    A label (a lone footnote number) starts a note; the note lines (8 pt)
    follow it.  Note lines above a page's first label continue the last note
    of the page before.
    """
    notes: dict[int, list[str]] = {}
    current: int | None = None
    for line in lines:
        text = line.text.strip()
        if not text or line.max_size > NOTE_SIZE + 0.5:
            continue
        if len(line.runs) and all(_is_mark(r) for r in line.runs if r.text.strip()):
            current = int(text)
            notes.setdefault(current, [])
            continue
        if text.isdigit() or _PRINT_PAGE_RE.fullmatch(text):
            continue  # the page number at the foot, a print page marker
        if current is None:
            continue
        notes[current].append(text)
    return {n: _join_lines(parts) for n, parts in notes.items()}


def _join_lines(parts: list[str]) -> str:
    out = ""
    for p in parts:
        p = _WS_RE.sub(" ", p).strip()
        if out.endswith("-") and not out.endswith(" -"):
            out += p
        elif out:
            out += " " + p
        else:
            out = p
    return out


def _fix_greek(text: str) -> str:
    # The digital edition's Greek font maps μ to the micro sign.
    return re.sub(r"(?<=[Ͱ-Ͽἀ-῿])µ|µ(?=[Ͱ-Ͽἀ-῿])", "μ", text)


def _body_pieces(line: Line, notes: dict[int, str]) -> list[tuple[str, str | None]]:
    """A body line as (text, kind) pieces: footnote markers become their
    notes (kind ``note``), print-page markers are dropped."""
    pieces: list[tuple[str, str | None]] = []
    for run in line.runs:
        if _is_mark(run):
            n = int(run.text.strip())
            if n not in notes:
                raise FordhamParseError(f"Isidore: footnote {n} has no text (page {line.page})")
            pieces.append(("[" + notes[n] + "]", "note"))
        elif run.size <= NOTE_SIZE + 0.5:
            rest = _PRINT_PAGE_RE.sub(" ", run.text)
            if rest.strip():
                raise FordhamParseError(f"Isidore: small print in the text, page {line.page}: {rest!r}")
            pieces.append((" ", None))
        else:
            pieces.append((run.text, None))
    return pieces


@dataclass
class _Para:
    ref: str
    lines: list[list[tuple[str, str | None]]] = field(default_factory=list)
    kind: str | None = None  # a wholly editorial unit (heading)

    def unit(self) -> Unit:
        b = _Builder()
        prev = ""
        for pieces in self.lines:
            if prev and not (prev.endswith("-") and not prev.endswith(" -")):
                b.add(" ")
            for text, kind in pieces:
                b.add(_fix_greek(text), kind or self.kind)
            prev = "".join(t for t, _ in pieces).rstrip()
        unit = b.unit(self.ref)
        if self.kind:
            # Merge adjacent spans of the same kind into one over the whole unit.
            unit.spans = [[0, len(unit.text), self.kind]]
        return unit


def _strip_section_number(pieces: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
    """Drop the leading ``12.`` of a section: it is the unit's ref."""
    for i, (text, kind) in enumerate(pieces):
        if not text.strip():
            continue
        if kind is None:
            pieces[i] = (_ETYM_SECTION_RE.sub("", text.lstrip(), count=1), None)
        break
    return pieces


def parse_isidore(lines: list[Line]) -> list[Unit]:
    """Brehaut's translated extracts, in Isidore's book/chapter/section numbering."""
    notes = pdf_notes(lines)
    paras: list[_Para] = []
    book = 0
    chapter: int | None = None
    mode = False      # inside EXTRACTS / TRANSLATION
    current: _Para | None = None
    seen: set[str] = set()

    def start(ref: str, kind: str | None = None) -> _Para:
        if ref in seen:
            # A section number printed twice (5.31 has two "3."): the second
            # gets a letter, as Scripture's 1 Kgs 2:35a.
            base = ref
            ref = next(f"{base}{c}" for c in "bcdefgh" if f"{base}{c}" not in seen)
            log.warning("Isidore: section %s printed twice; the second is %s", base, ref)
        seen.add(ref)
        para = _Para(ref, kind=kind)
        paras.append(para)
        return para

    for line in lines:
        if line.max_size <= NOTE_SIZE + 0.5:
            continue  # footnotes, page numbers
        text = _WS_RE.sub(" ", _PRINT_PAGE_RE.sub(" ", "".join(
            r.text for r in line.runs if not _is_mark(r)))).strip()
        if not text:
            continue
        centred = line.x > CENTRE_X
        m = _ETYM_BOOK_RE.match(text)
        if centred and m:
            book, chapter, mode, current = _roman(m.group(1)), None, False, None
            continue
        if centred and (text in ("INTRODUCTION", "ANALYSIS", "BIBLIOGRAPHY")
                        or text.startswith("APPENDIX")):
            mode, current = False, None
            continue
        if centred and (text == "EXTRACTS" or text.startswith("TRANSLATION")):
            mode, current = True, None
            if book == 10:
                chapter = 0  # Book X is one alphabetical list: Etym.10.{section}
            continue
        if not mode or not book:
            continue
        m = _ETYM_CHAPTER_RE.match(text)
        if m and not line.x > INDENT_X + 10:
            if m.group(1) and _roman(m.group(1)) != book:
                raise FordhamParseError(f"Isidore: {text!r} under book {book}")
            chapter = int(m.group(2))
            current = start(f"Etym.{book}.{chapter}", "heading")
            current.lines.append(_body_pieces(line, notes))
            continue
        if chapter is None and text.startswith("PREFACE.") and line.x > INDENT_X:
            current = start(f"Etym.{book}.0.1")  # the book's preface (Book III)
            current.lines.append(_body_pieces(line, notes))
            continue
        if chapter is None and current is not None:
            current.lines.append(_body_pieces(line, notes))
            continue
        if chapter is None:
            if centred:
                continue  # a book's subtitle
            raise FordhamParseError(f"Isidore: text before a chapter in book {book}: {text[:60]!r}")
        m = _ETYM_SECTION_RE.match(text)
        indented = line.x > INDENT_X
        if m and indented and (current is None or current.kind or line.x < CENTRE_X):
            section = int(m.group(1))
            ref = f"Etym.{book}.{section}" if chapter == 0 else f"Etym.{book}.{chapter}.{section}"
            current = start(ref)
            current.lines.append(_strip_section_number(_body_pieces(line, notes)))
            continue
        if current is None:
            raise FordhamParseError(f"Isidore: unnumbered text in {book}.{chapter}: {text[:60]!r}")
        if current.kind and indented:
            raise FordhamParseError(f"Isidore: unnumbered paragraph after {current.ref}: {text[:60]!r}")
        current.lines.append(_body_pieces(line, notes))
    return [p.unit() for p in paras]


def pdf_lines(path: Path) -> list[Line]:
    """The PDF's text lines in reading order, with their runs' font sizes.

    ``pdfminer.six`` comes with ``pdfplumber`` (a dependency); imported here,
    since only the Isidore text needs it.
    """
    from pdfminer.high_level import extract_pages
    from pdfminer.layout import LAParams, LTChar, LTTextContainer, LTTextLine

    out: list[Line] = []
    for pno, page in enumerate(extract_pages(str(path), laparams=LAParams()), 1):
        page_lines: list[Line] = []
        for el in page:
            if not isinstance(el, LTTextContainer):
                continue
            for tl in el:
                if not isinstance(tl, LTTextLine):
                    continue
                runs: list[Run] = []
                for ch in tl:
                    t = ch.get_text()
                    size = round(ch.size, 1) if isinstance(ch, LTChar) else (runs[-1].size if runs else 0.0)
                    if runs and runs[-1].size == size:
                        runs[-1].text += t
                    else:
                        runs.append(Run(size, t))
                if runs:
                    runs[-1].text = runs[-1].text.rstrip("\n")
                    page_lines.append(Line(pno, round(tl.x0, 1), round(tl.y0, 1), runs))
        page_lines.sort(key=lambda ln: (-ln.y, ln.x))
        out.extend(page_lines)
    return out


# ---------------------------------------------------------------------------
# Works
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Text:
    slug: str
    path: str               # under BASE_URL
    cache_name: str
    kind: str               # "porphyry" | "gregory" | "isidore"
    author: str
    title: str
    translation_of: str
    tradition: str
    date_range: tuple[int, int] | None
    date_confidence: str
    edition: str


TEXTS: tuple[Text, ...] = (
    Text(
        slug="mark-the-deacon-life-of-porphyry",
        path="basis/porphyry.asp",
        cache_name="porphyry.asp.html",
        kind="porphyry",
        author="Mark the Deacon",
        title="Life of Porphyry, Bishop of Gaza",
        translation_of="first1k/tlg2806/tlg001/1st1K-grc1",
        tradition="greek",
        date_range=None,
        date_confidence="uncertain",
        edition=("G. F. Hill (tr.), The Life of Porphyry, Bishop of Gaza, by Mark the Deacon, "
                 "translated with introduction and notes (Oxford: Clarendon Press, 1913); complete, "
                 "from the Teubner text of the Bonn Philological Society (Leipzig, 1895). "
                 f"Transcription: {_SOURCEBOOK}, 1997."),
    ),
    Text(
        slug="gregory-of-tours-history-of-the-franks",
        path="basis/gregory-hist.asp",
        cache_name="gregory-hist.asp.html",
        kind="gregory",
        author="Gregory of Tours",
        title="History of the Franks (abridged selections)",
        translation_of="oglt-pl/gregorius-turonensis/pl71_0_s.",
        tradition="latin",
        date_range=(573, 594),
        date_confidence="approximate",
        edition=("Ernest Brehaut (tr.), History of the Franks by Gregory, Bishop of Tours: Selections, "
                 "translated with notes (Records of Civilization 2; New York: Columbia University Press, "
                 "1916). Abridged selections: about half of the chapters are translated, the others "
                 "only summarised in brackets; Book VIII ch. 20 is left out (not Brehaut's on the page). "
                 f"Transcription: {_SOURCEBOOK}, 1997."),
    ),
    Text(
        slug="isidore-etymologies-brehaut",
        path="basis/Brehaut%20-%20Encyclopedist%20of%20the%20Dark%20Ages.pdf",
        cache_name="brehaut-encyclopedist-1912.pdf",
        kind="isidore",
        author="Isidore of Seville",
        title="Etymologies (selections)",
        translation_of="oglt-pl/isidorus-hispalensis/pl82_0_san",
        tradition="latin",
        date_range=(600, 636),
        date_confidence="approximate",
        edition=("Ernest Brehaut, An Encyclopedist of the Dark Ages: Isidore of Seville (Studies in "
                 "History, Economics and Public Law; New York: Columbia University, 1912): the "
                 "translated extracts of Part II only, selections from Books I-XVI and XVIII, not "
                 "Brehaut's study. Digital edition by David Badke (bestiary.ca, 2003), PDF hosted by "
                 f"the {_SOURCEBOOK}."),
    ),
)


def text_url(text: Text) -> str:
    return BASE_URL + text.path


def parse_text(text: Text, path: Path) -> list[Unit]:
    if text.kind == "isidore":
        lines = pdf_lines(path)
        return parse_isidore(lines)
    blocks = html_blocks(path.read_text(encoding="utf-8", errors="replace"))
    if text.kind == "porphyry":
        return parse_porphyry(blocks)
    if text.kind == "gregory":
        return parse_gregory(blocks)
    raise ValueError(f"unknown text kind {text.kind!r}")


def _work(text: Text) -> Work:
    return Work(
        work_id=f"{SOURCE_ID}/{text.slug}",
        source_id=SOURCE_ID,
        author=text.author,
        title=text.title,
        date_composed=None,
        date_range=text.date_range,
        date_confidence=text.date_confidence,
        genre="patristic",
        language="eng",
        tradition=text.tradition,
        license="academic-noncommercial",
        provenance_url=text_url(text),
        edition=text.edition,
        translation_of=text.translation_of,
    )


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    out_dir = output_dir / SOURCE_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    works: list[Work] = []
    for text in TEXTS:
        out_path = out_dir / f"{text.slug}.json"
        if out_path.exists() and not force:
            works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
            continue
        path = download_file(text_url(text), output_dir / CACHE_DIR / text.cache_name, force=force)
        units = parse_text(text, path)
        work = _work(text)
        out_path.write_text(
            json.dumps({"work": work.model_dump(), "paragraphs": [u.record() for u in units]},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("%s: %d paragraphs", work.work_id, len(units))
        works.append(work)
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
