"""
Ingestor for English translations on CCEL outside the ANF/NPNF volumes (#351).

Source: https://ccel.org (Christian Classics Ethereal Library)
Format: the book's single-file HTML (``/ccel/{author}/{book}/files/{book}.html``);
        CCEL offers no ThML for these books, so ``_ccel_common`` does not apply
License: public domain (US); CCEL marks the books it hosts as public domain in
        the US unless a book's information page says otherwise

So far one book: M. L. McClure and C. L. Feltoe (ed. and trans.), *The
Pilgrimage of Etheria* (London: SPCK, 1919; Translations of Christian
Literature, Series III: Liturgical Texts), Egeria's *Itinerarium*, in
A. K. M. Adam's transcription.  It renders the Latin of Geyer's CSEL 39 text
(``csel/stoa0111/stoa001/opp-lat3``) as edited by Gamurrini and Bernard; the
book prints no chapter or section numbers, only its own running headings, so
the units are numbered by those headings and the passage alignment pairs them
with the CSEL chapters.

The page is a 1990s transcription in Latin-1, page by page: each printed page
is the text, then its footnotes (``<SUP>n</SUP> …``), then ``<hr>`` and the
next page's number (``<2>``).  Greek words in the notes are in the SPIonic
font's encoding (``Fara&n``), converted here to Unicode (:func:`spionic`).

Units and editorial material (#236)
-----------------------------------
- ``Eth.{k}``: the translators' heading *k* ("THE APPROACH TO SINAI"), wholly
  ``heading``; ``Eth.{k}.{n}``: paragraph *n* under it.  A paragraph that runs
  over a page break is joined.
- Footnotes are carried where their markers are, in brackets, as ``note``
  spans; so are the translators' bracketed remarks in the text ("[Mr.
  Conybeare believes …]").  Their short bracketed supplements ("[because]")
  are ``supplement`` spans; the gaps of the manuscript (". . .", "(Much is
  wanting.)", "[A leaf is torn out.]") are ``lacuna`` spans.
- Page numbers are dropped.
"""

from __future__ import annotations

import html
import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from patristica.models import Work
from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

SOURCE_ID = "ccel-eng"


@dataclass(frozen=True)
class Book:
    slug: str
    url: str
    encoding: str
    work_title: str
    author: str
    edition: str
    translation_of: str | None
    date_composed: int | None
    date_range: tuple[int, int] | None
    date_confidence: str
    genre: str
    tradition: str
    units: int  # expected unit count, a check on the parse


ETHERIA = Book(
    slug="mcclure-etheria",
    url="https://ccel.org/ccel/mcclure/etheria/files/etheria.html",
    encoding="latin-1",
    work_title="The Pilgrimage of Etheria",
    author="Egeria",
    edition=("Translated by M. L. McClure and C. L. Feltoe, The Pilgrimage of Etheria "
             "(London: SPCK; New York: Macmillan, 1919), Translations of Christian "
             "Literature, Series III: Liturgical Texts; transcription by A. K. M. Adam, "
             "Christian Classics Ethereal Library; the translators' Introduction is not "
             "included"),
    translation_of="csel/stoa0111/stoa001/opp-lat3",
    date_composed=None,
    date_range=None,
    date_confidence="uncertain",
    genre="patristic",
    tradition="latin",
    units=163,
)

BOOKS: tuple[Book, ...] = (ETHERIA,)


# ---------------------------------------------------------------------------
# SPIonic Greek
# ---------------------------------------------------------------------------

_SPIONIC_LETTERS = dict(zip("abgdezhqiklmncoprstufxywvj", "αβγδεζηθικλμνξοπρστυφχψωςς"))
_SPIONIC_LETTERS.update({k.upper(): v.upper() for k, v in _SPIONIC_LETTERS.items()
                         if k not in "vj"})
_SMOOTH, _ROUGH = "̓", "̔"
_ACUTE, _GRAVE, _CIRC, _IOTA = "́", "̀", "͂", "ͅ"
# Marks that follow their letter; SPIonic has one glyph for narrow letters and
# one for wide ones (``/`` and ``&`` are both acute).
_SPIONIC_MARKS = {
    ")": _SMOOTH, "(": _ROUGH,
    "/": _ACUTE, "&": _ACUTE, "\\": _GRAVE, "_": _GRAVE, "=": _CIRC, "~": _CIRC,
    "|": _IOTA,
    "1": _SMOOTH + _ACUTE, "2": _SMOOTH + _GRAVE, "3": _ROUGH + _ACUTE, "4": _ROUGH + _GRAVE,
    "5": _SMOOTH + _CIRC, "6": _ROUGH + _CIRC,
}
# Breathings written before a capital.
_SPIONIC_PREFIX = {"'": _SMOOTH, "9": _ROUGH}


def spionic(text: str) -> str:
    """SPIonic-encoded Greek as Unicode (NFC)."""
    out: list[str] = []
    pending = ""
    for ch in text:
        if ch in _SPIONIC_PREFIX:
            pending += _SPIONIC_PREFIX[ch]
        elif ch in _SPIONIC_LETTERS:
            out.append(_SPIONIC_LETTERS[ch] + pending)
            pending = ""
        elif ch in _SPIONIC_MARKS:
            if not out:
                raise ValueError(f"SPIonic mark {ch!r} with no letter in {text!r}")
            out[-1] += _SPIONIC_MARKS[ch]
        elif ch.isspace() or ch in ".,;:-":
            if pending:
                raise ValueError(f"SPIonic breathing with no letter in {text!r}")
            out.append(ch)
        else:
            raise ValueError(f"unknown SPIonic character {ch!r} in {text!r}")
    if pending:
        raise ValueError(f"SPIonic breathing with no letter in {text!r}")
    # A sigma at the end of a word is final even where the font has the medial one.
    word = re.sub(r"σ(?=\s|$|[.,;:])", "ς", "".join(out))
    return unicodedata.normalize("NFC", word)


# ---------------------------------------------------------------------------
# HTML → units
# ---------------------------------------------------------------------------

_GREEK_RE = re.compile(r'<FONT[^>]*FACE="spionic[^"]*"[^>]*>(.*?)</FONT>', re.I | re.S)
_TAG_RE = re.compile(r"<[^>]*>")
_NOTE_START_RE = re.compile(r"^\s*(?:<SUP>\d+\s*</SUP>|\{(?:footnote )?continu)", re.I)
_MARKER_RE = re.compile(r"<SUP>(\d+)\s*</SUP>", re.I)
# The transcriber's marks on a footnote that runs over a page break.
_CONT_END_RE = re.compile(r"\{(?:footnote )?cont[^}]*\}\s*$", re.I)
_CONT_START_RE = re.compile(r"^\s*\{(?:footnote )?continu[^}]*\}", re.I)
_PAGE_RE = re.compile(r"<hr[^>]*>\s*<\d+>", re.I)
_NOTE_SPLIT_RE = re.compile(r"(?:^|\n)\s*<SUP>(\d+)\s*</SUP>", re.I)
_PARA_SPLIT_RE = re.compile(r"<BR>|<P>|\n\s*\n", re.I)
_LACUNA_RE = re.compile(r"\(Much is wanting\.\)|\[A leaf is (?:torn out|wanting)\.?\]\.?"
                        r"|(?:\.\s*){3,}|\*(?:\s*\*){2,}")
_SUBHEADING_RE = re.compile(r"^(?:\d{1,2}\.?|\([a-e]\))\s*\S")
_ROMAN_RE = re.compile(r"^[IVX]+$")
_BRACKET_RE = re.compile(r"\[[^\[\]]*\]")
_SUPPLEMENT_MAX_WORDS = 4


def _clean(fragment: str) -> str:
    """An HTML fragment as plain text: Greek converted, tags dropped, spaces collapsed."""
    fragment = fragment.replace("&nbsp;", " ")
    fragment = _GREEK_RE.sub(lambda m: "\x00" + spionic(m.group(1).strip()) + "\x01", fragment)
    text = _TAG_RE.sub("", fragment)
    # Greek is protected from unescaping (``Fara&n``).
    parts = re.split(r"(\x00[^\x01]*\x01)", text)
    text = "".join(p[1:-1] if p.startswith("\x00") else html.unescape(p) for p in parts)
    # Dashes: the transcription's Mac em dash (read as Latin-1 "ã") and "--".
    text = text.replace("ã", "—").replace("--", "—")
    # Control characters (two stray ESCs) go; the note placeholders stay.
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Cc" or ch in "\n\t")
    return re.sub(r"\s+", " ", text).strip()


def _pages(document: str) -> list[str]:
    start = document.find('<P CLASS="MH">')
    end = document.find('<P CLASS="TH">', start + 1)
    if start < 0 or end < 0:
        raise ValueError("no text between the title and the footer")
    body = document[document.index("</P>", start) + 4:end].replace("\r\n", "\n")
    return _PAGE_RE.split(body)


def _split_page(page: str) -> tuple[str, str, dict[str, str]]:
    """A page's text (HTML), the end of a footnote begun on the page before
    (plain text, or ""), and its own footnotes (number → plain text)."""
    blocks = re.split(r"\n\s*\n", page.strip())
    first_note = next((i for i, b in enumerate(blocks) if _NOTE_START_RE.match(b)
                       and i > 0), len(blocks))
    text = "\n\n".join(blocks[:first_note])
    notes: dict[str, str] = {}
    pieces = _NOTE_SPLIT_RE.split("\n\n".join(blocks[first_note:]))
    carried = ""
    if pieces[0].strip():
        if not _CONT_START_RE.match(pieces[0]):
            raise ValueError(f"text before the first footnote: {pieces[0][:60]!r}")
        carried = _clean(_CONT_START_RE.sub("", pieces[0]))
    for number, note in zip(pieces[1::2], pieces[2::2]):
        if number in notes:
            raise ValueError(f"footnote {number} twice on one page")
        notes[number] = note
    if notes:
        last = list(notes)[-1]
        notes[last] = _CONT_END_RE.sub("", notes[last])
    return text, carried, {k: _clean(v) for k, v in notes.items()}


_OPEN, _CLOSE = "", ""  # a footnote marker's placeholder: n
_PLACEHOLDER_RE = re.compile(f"{_OPEN}([\\d:]+){_CLOSE}")


def _mark_notes(text: str, notes: dict[str, str], where: str) -> str:
    """*text* with each footnote marker as a placeholder; every note must be referenced."""
    text = _MARKER_RE.sub(lambda m: f"{_OPEN}{m.group(1)}{_CLOSE}", text)
    for number in notes:
        if f"{_OPEN}{number}{_CLOSE}" in text:
            continue
        # A marker the transcription left as a plain digit: "Faran,4 our route".
        bare = list(re.finditer(rf"(?<=[A-Za-z,;:.])({number})(?=\s)", text))
        if len(bare) != 1:
            raise ValueError(f"{where}: footnote {number} has no marker")
        m = bare[0]
        text = f"{text[:m.start()]}{_OPEN}{number}{_CLOSE}{text[m.end():]}"
    for m in _PLACEHOLDER_RE.finditer(text):
        if m.group(1) not in notes:
            raise ValueError(f"{where}: marker {m.group(1)} has no footnote")
    return text


def _is_heading(text: str) -> bool:
    """A heading of the translators': capitals ("THE BUSH", "IV") or a numbered
    subheading ("2. Sext and None.", "(b) Station at Sion.")."""
    if len(text) >= 100:
        return False
    letters = [c for c in text if c.isalpha()]
    if letters and not any(c.islower() for c in letters):
        return True
    return bool(_SUBHEADING_RE.match(text))


class _Unit:
    """A unit's text with its editorial spans."""

    def __init__(self) -> None:
        self.text = ""
        self.spans: list[list] = []

    def add(self, text: str, kind: str | None = None) -> None:
        if not text:
            return
        if (self.text and not self.text.endswith((" ", "—"))
                and not re.match(r"[ ,;:—]|\.(?![\s.])", text)):
            self.text += " "
        start = len(self.text)
        self.text += text
        if kind:
            self.spans.append([start, len(self.text), kind])

    def record(self, ref: str) -> dict:
        rec: dict = {"ref": ref, "text": self.text}
        if self.spans:
            rec["editorial"] = self.spans
        return rec


def _plain_spans(text: str) -> list[tuple[str, str | None]]:
    """Running text cut into (piece, kind): lacunae, supplements and remarks marked."""
    marks: list[tuple[int, int, str]] = []
    for m in _LACUNA_RE.finditer(text):
        marks.append((m.start(), m.end(), "lacuna"))
    for m in _BRACKET_RE.finditer(text):
        if any(s < m.end() and m.start() < e for s, e, _ in marks):
            continue
        words = len(m.group(0).split())
        marks.append((m.start(), m.end(),
                      "supplement" if words <= _SUPPLEMENT_MAX_WORDS else "note"))
    marks.sort()
    pieces: list[tuple[str, str | None]] = []
    pos = 0
    for s, e, kind in marks:
        pieces.append((text[pos:s].strip(), None))
        pieces.append((text[s:e], kind))
        pos = e
    pieces.append((text[pos:].strip(), None))
    return [(p, k) for p, k in pieces if p]


def _unit(paragraph: str, notes: dict[str, str]) -> _Unit:
    unit = _Unit()
    parts = _PLACEHOLDER_RE.split(paragraph)
    for i, part in enumerate(parts):
        if i % 2:
            unit.add(f"[{notes[part]}]", "note")
        else:
            for piece, kind in _plain_spans(part):
                unit.add(piece, kind)
    return unit


def parse_etheria(document: str) -> list[dict]:
    """McClure and Feltoe's translation as raw units."""
    paragraphs: list[tuple[str, dict[str, str]]] = []  # (text with placeholders, its notes)
    join_next = False
    split = [_split_page(page) for page in _pages(document)]
    for i, (_, carried, _) in enumerate(split):
        if carried:
            if i == 0 or not split[i - 1][2]:
                raise ValueError(f"page {i + 1}: a footnote continued from no footnote")
            notes = split[i - 1][2]
            last = list(notes)[-1]
            notes[last] = f"{notes[last]} {carried}"
    for number, (text, _, notes) in enumerate(split, 1):
        # Notes are numbered per page: key them by page so a joined paragraph keeps both.
        text = _mark_notes(text, notes, f"page {number}")
        keyed = {f"{number}:{k}": v for k, v in notes.items()}
        text = _PLACEHOLDER_RE.sub(lambda m: f"{_OPEN}{number}:{m.group(1)}{_CLOSE}", text)
        pieces = [_clean(p) for p in _PARA_SPLIT_RE.split(text)]
        pieces = [p for p in pieces if p]
        if not pieces:
            continue
        if join_next and paragraphs and not _is_heading(pieces[0]):
            prev, prev_notes = paragraphs.pop()
            pieces[0] = f"{prev} {pieces[0]}"
            keyed = {**prev_notes, **keyed}
        paragraphs.extend((p, keyed) for p in pieces)
        last = pieces[-1]
        # A paragraph runs on over the page break unless the page ends a sentence
        # (the transcription ends nearly every page with <P>, so tags tell nothing).
        join_next = not re.search(r"[.?!][\"'”’\])]?\s*$", _PLACEHOLDER_RE.sub("", last))
    units: list[dict] = []
    section, n = 0, 0
    heading: _Unit | None = None
    opening: list[str] = []
    for text, notes in paragraphs:
        plain = _PLACEHOLDER_RE.sub("", text).strip()
        if not _LACUNA_RE.fullmatch(plain) and _is_heading(plain):
            if heading is None:
                heading = _Unit()
            elif not heading.text.endswith((".", ":")):
                heading.text += "."
            # The heading's words, then any footnote on it.
            for i, part in enumerate(_PLACEHOLDER_RE.split(text)):
                if i % 2:
                    heading.add(f"[{notes[part]}]", "note")
                elif part.strip():
                    heading.add(part.strip(), "heading")
            continue
        if heading is not None:
            section, n = section + 1, 0
            units.append(_merge_spans(heading).record(f"Eth.{section}"))
            heading = None
        if section == 0:
            # "(Much is wanting.)" and the dots before the first heading: they
            # go with the first paragraph after it.
            if not _LACUNA_RE.fullmatch(plain):
                raise ValueError(f"text before the first heading: {plain[:60]!r}")
            opening.append(text)
            continue
        if opening:
            text = " ".join([*opening, text])
            opening = []
        n += 1
        units.append(_unit(text, notes).record(f"Eth.{section}.{n}"))
    if heading is not None:
        raise ValueError("the text ends with a heading")
    return units


def _merge_spans(unit: _Unit) -> _Unit:
    """Adjacent spans of one kind as one span (headings joined with ". ")."""
    merged: list[list] = []
    for s, e, kind in unit.spans:
        if merged and merged[-1][2] == kind and unit.text[merged[-1][1]:s].strip(" .") == "":
            merged[-1][1] = e
        else:
            merged.append([s, e, kind])
    unit.spans = merged
    return unit


_PARSERS = {ETHERIA.slug: parse_etheria}


# ---------------------------------------------------------------------------
# Fetch and write
# ---------------------------------------------------------------------------

def _work(book: Book) -> Work:
    return Work(
        work_id=f"{SOURCE_ID}/{book.slug}",
        source_id=SOURCE_ID,
        author=book.author,
        title=book.work_title,
        date_composed=book.date_composed,
        date_range=book.date_range,
        date_confidence=book.date_confidence,  # type: ignore[arg-type]
        genre=book.genre,  # type: ignore[arg-type]
        language="eng",
        tradition=book.tradition,  # type: ignore[arg-type]
        license="public_domain",
        provenance_url=book.url,
        edition=book.edition,
        translation_of=book.translation_of,
    )


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Fetch the books (cached) and write one raw JSON file per work."""
    cache_dir = output_dir / "_cache" / SOURCE_ID
    works: list[Work] = []
    for book in BOOKS:
        out_path = output_dir / SOURCE_ID / f"{book.slug}.json"
        if out_path.exists() and not force:
            works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
            continue
        # The cached page is never re-fetched: the transcription is static.
        page = download_file(book.url, cache_dir / Path(book.url).name, etag_cache=False)
        units = _PARSERS[book.slug](page.read_bytes().decode(book.encoding))
        if len(units) != book.units:
            raise ValueError(f"{book.slug}: {len(units)} units, expected {book.units}")
        work = _work(book)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"work": work.model_dump(), "paragraphs": units},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
        works.append(work)
    log.info("CCEL (English): %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
