"""
Shared parser for Ælfric's *Catholic Homilies* I in Thorpe's edition (#566, #223).

Source: Benjamin Thorpe, *The Homilies of the Anglo-Saxon Church*, Part I
(London: Ælfric Society, 1844), "the Sermones Catholici, or Homilies of
Ælfric, in the original Anglo-Saxon, with an English version", as Project
Gutenberg eBook #38334 (2011, Distributed Proofreaders). Public domain. The
HTML edition is used: it keeps þ ð æ ǽ and the accents, which the plain-text
edition transliterates to ASCII.

Thorpe prints the Old English and his English on facing pages. The HTML has
one ``<table class="nobctr">`` for the Old English preface and one for each
of the 40 homilies; every row has a ``td.saxonice`` and a ``td.anglice`` cell
holding the same sequence of elements (``h3`` headings, ``p.cenhead``
headings inside a homily, ``p`` paragraphs, ``blockquote`` pericopes), so the
two sides are paired element by element. A row whose two cells have
different numbers of elements raises.

Two sources are made from it:

- ``aelfric-ch`` (``scripts.ingest.aelfric_ch``): the Old English (``ang``)
  preface and 40 homilies, plus Ælfric's Latin preface (``lat``), which
  Thorpe prints alone, with no English;
- ``aelfric-ch-eng`` (``scripts.ingest.aelfric_ch_eng``): Thorpe's English,
  each work ``translation_of`` its Old English work.

**Units and refs.** Each element is one unit (ingested as ``paragraphs``, so
long paragraphs get derived verses). Refs are ``AECHomI.{n}.{k}`` for the
k-th element of homily n (``AECHomI.Praef.{k}`` for the Old English preface,
``AECHomI.PraefLat.{k}`` for the Latin one); ``AECHomI`` is the Dictionary
of Old English short title (ÆCHom I). The Old English and English works
share their refs, so the paragraphs align one to one.

**Text.** Latin inside the homilies (pericopes, quotations, the closing
note of the preface) stays as text, on both sides: Thorpe leaves the Latin
pericopes untranslated. Page numbers (``{25}``) are layout and are dropped.
Thorpe's errata, which the transcribers applied (``span.correction``), are
kept as corrected. Italics and small capitals are plain text. The edition's
overline over abbreviated letters (``S<span class="over">ca</span>`` for
*Sancta*, ``X<span class="over">po</span>`` for *Christo*, and in the
calendar rubrics) is rendered with a combining overline (U+0305) on each
letter, not expanded; ``fold()`` drops it, so search sees the bare letters.

**Editorial spans (#236).** Every ``h3`` (the manuscript's Latin rubrics on
the Old English side, Thorpe's English headings on the other) is a whole-unit
``title`` span, and every ``p.cenhead`` inside a homily (``EUANGELIUM.``,
``PASSIO EJUSDEM.``) a whole-unit ``heading`` span. A bracketed word Thorpe
supplied (``[on]``) is a ``supplement`` span. Thorpe's endnotes (pp. 621 ff.,
keyed to page and line, with no markers in the text) and his own preface are
not carried, and nor is the Gutenberg boilerplate.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from patristica.models import Work
from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

OE_SOURCE = "aelfric-ch"
ENGLISH_SOURCE = "aelfric-ch-eng"

GUTENBERG_PAGE = "https://www.gutenberg.org/ebooks/38334"
DOWNLOAD_URL = "https://www.gutenberg.org/cache/epub/38334/pg38334-images.html"
CACHE_PATH = Path("_cache") / "gutenberg-38334" / "pg38334-images.html"

REF_PREFIX = "AECHomI"
AUTHOR = "Ælfric of Eynsham"
SERIES = "Catholic Homilies I"
HOMILY_COUNT = 40

# Ælfric sent the First Series to Archbishop Sigeric (990–994); it is usually
# dated c. 989–991 (Clemoes, Ælfric's Catholic Homilies: The First Series,
# EETS s.s. 17, 1997, pp. 1, 70).
DATE_COMPOSED = 990
DATE_RANGE = (989, 991)

EDITION = (
    "Benjamin Thorpe (ed.), The Homilies of the Anglo-Saxon Church, Part I: the "
    "Sermones Catholici or Homilies of Ælfric (London: Ælfric Society, 1844); "
    "Project Gutenberg eBook #38334 (2011)"
)
ENGLISH_EDITION = (
    "English translation of Benjamin Thorpe, The Homilies of the Anglo-Saxon Church, "
    "Part I (London: Ælfric Society, 1844); Project Gutenberg eBook #38334 (2011)"
)

OVERLINE = "̅"

Span = tuple[int, int, str]


class AelfricFormatError(ValueError):
    """The HTML has a structure this parser doesn't know."""


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

def _text_of(node: Tag) -> str:
    """The text of an element: page numbers dropped, overlined letters marked
    with U+0305, ``<br>`` as a space."""
    out: list[str] = []

    def walk(n: Tag) -> None:
        for child in n.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                out.append(str(child))
                continue
            if not isinstance(child, Tag):
                continue
            classes = child.get("class") or []
            if "pagenum" in classes:
                continue
            if child.name == "br":
                out.append(" ")
            elif "over" in classes:
                out.append("".join(ch + OVERLINE if not ch.isspace() else ch
                                   for ch in child.get_text()))
            else:
                walk(child)

    walk(node)
    return " ".join("".join(out).split())


_SUPPLEMENT_RE = re.compile(r"\[[^\[\]]+\]")


def unit_of(el: Tag) -> dict:
    """A raw unit ``{"text", "editorial"?}`` (no ref yet) for one element of a
    cell."""
    text = _text_of(el)
    if not text:
        raise AelfricFormatError(f"empty <{el.name}> element")
    classes = el.get("class") or []
    spans: list[Span] = []
    if el.name == "h3":
        spans.append((0, len(text), "title"))
    elif el.name == "p" and "cenhead" in classes:
        spans.append((0, len(text), "heading"))
    elif el.name in ("p", "blockquote"):
        spans.extend((m.start(), m.end(), "supplement") for m in _SUPPLEMENT_RE.finditer(text))
    else:
        raise AelfricFormatError(f"unexpected <{el.name} class={classes}> in a cell")
    unit: dict = {"text": text}
    if spans:
        unit["editorial"] = [list(s) for s in spans]
    return unit


def _elements(cell: Tag) -> list[Tag]:
    """The block elements of a cell (page-number spans and whitespace left out)."""
    els: list[Tag] = []
    for child in cell.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            if child.strip():
                raise AelfricFormatError(f"bare text in a cell: {child.strip()[:60]!r}")
            continue
        if isinstance(child, Tag):
            if "pagenum" in (child.get("class") or []):
                continue
            if not _text_of(child):  # a paragraph holding only a page number
                continue
            els.append(child)
    return els


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

@dataclass
class Piece:
    """One work of the edition: its Old English (or Latin) units and, unless it
    is the Latin preface, Thorpe's English units with the same refs."""

    local_id: str
    number: int | None          # homily number, None for the prefaces
    title: str                  # Latin title (contents page)
    english_title: str | None   # Thorpe's English title
    language: str               # "ang" or "lat"
    units: list[dict] = field(default_factory=list)
    english: list[dict] = field(default_factory=list)


def paired_units(table: Tag, section: str) -> tuple[list[dict], list[dict]]:
    """The Old English and English units of one facing-page table, with shared
    refs ``AECHomI.{section}.{k}``."""
    oe: list[dict] = []
    en: list[dict] = []
    body = table.find("tbody") or table
    for row in body.find_all("tr", recursive=False):
        cells = row.find_all("td", recursive=False)
        if [c.get("class", [None])[0] for c in cells] != ["saxonice", "anglice"]:
            raise AelfricFormatError(f"§{section}: a row is not saxonice/anglice")
        left, right = _elements(cells[0]), _elements(cells[1])
        if len(left) != len(right):
            raise AelfricFormatError(
                f"§{section}: a row has {len(left)} Old English and {len(right)} English elements")
        for a, b in zip(left, right):
            ref = f"{REF_PREFIX}.{section}.{len(oe) + 1}"
            oe.append({"ref": ref, **unit_of(a)})
            en.append({"ref": ref, **unit_of(b)})
    return oe, en


def _contents(soup: BeautifulSoup) -> tuple[list[str], list[str]]:
    """The homily titles from the Latin and English contents tables (I–XL)."""
    out: list[list[str]] = []
    for label in ("Table of contents (Latin).", "Table of contents (English)."):
        table = soup.find("table", attrs={"title": label})
        if table is None:
            raise AelfricFormatError(f"no {label!r}")
        titles: list[str] = []
        for row in table.find_all("tr"):
            cells = [_text_of(c) for c in row.find_all("td")]
            if len(cells) == 3 and re.fullmatch(r"[IVXL]+\.", cells[0]):
                titles.append(cells[1])
        if len(titles) != HOMILY_COUNT:
            raise AelfricFormatError(f"{label}: {len(titles)} homilies, expected {HOMILY_COUNT}")
        out.append(titles)
    return out[0], out[1]


def latin_preface(soup: BeautifulSoup) -> list[dict]:
    """Ælfric's Latin preface: from its heading to the first facing-page table."""
    head = soup.find("h3", string=re.compile(r"INCIPIT PRÆFATIO"))
    if head is None:
        raise AelfricFormatError("no Latin preface heading")
    units: list[dict] = []
    for el in [head, *head.find_all_next(True)]:
        if el.name == "table":
            break
        if el.name in ("h3", "p") and el.find_parent("p") is None and _text_of(el):
            units.append({"ref": f"{REF_PREFIX}.PraefLat.{len(units) + 1}", **unit_of(el)})
    if len(units) < 3:
        raise AelfricFormatError(f"Latin preface: only {len(units)} units")
    return units


def parse(html: str) -> list[Piece]:
    """Every work of the edition, in order: the Latin preface, the Old English
    preface and the 40 homilies."""
    soup = BeautifulSoup(html, "lxml")
    latin_titles, english_titles = _contents(soup)
    tables = [t for t in soup.find_all("table", class_="nobctr")
              if not t.get("title") and t.find("td", class_="saxonice", recursive=True)
              and t.find_parent("td") is None]
    if len(tables) != HOMILY_COUNT + 1:
        raise AelfricFormatError(f"{len(tables)} facing-page tables, expected {HOMILY_COUNT + 1}")
    pieces = [Piece("ch1-praefatio-lat", None, "Praefatio (Latin)", None, "lat",
                    latin_preface(soup))]
    oe, en = paired_units(tables[0], "Praef")
    pieces.append(Piece("ch1-praefatio", None, "Praefatio", "Preface", "ang", oe, en))
    for n, table in enumerate(tables[1:], start=1):
        oe, en = paired_units(table, str(n))
        pieces.append(Piece(f"ch1-{n:02d}", n, latin_titles[n - 1], english_titles[n - 1],
                            "ang", oe, en))
    return pieces


# ---------------------------------------------------------------------------
# Works
# ---------------------------------------------------------------------------

def _roman(n: int) -> str:
    out = ""
    for value, numeral in ((40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= value:
            out += numeral
            n -= value
    return out


def work_title(piece: Piece, english: bool) -> str:
    name = piece.english_title if english else piece.title
    if piece.number is None:
        return f"{SERIES}, {name}"
    return f"{SERIES}, {_roman(piece.number)}: {name}"


def make_work(piece: Piece, english: bool) -> Work:
    source_id = ENGLISH_SOURCE if english else OE_SOURCE
    return Work(
        work_id=f"{source_id}/{piece.local_id}",
        source_id=source_id,
        author=AUTHOR,
        title=work_title(piece, english),
        date_composed=DATE_COMPOSED,
        date_range=DATE_RANGE,
        date_confidence="approximate",
        genre="patristic",
        language="eng" if english else piece.language,
        tradition="latin",
        license="public_domain",
        provenance_url=GUTENBERG_PAGE,
        edition=ENGLISH_EDITION if english else EDITION,
        translation_of=f"{OE_SOURCE}/{piece.local_id}" if english else None,
    )


def fetch(output_dir: Path, force: bool = False) -> Path:
    """The cached HTML file (downloaded once, shared by both ingestors)."""
    return download_file(DOWNLOAD_URL, output_dir / CACHE_PATH, force=force)


def ingest_source(output_dir: Path, force: bool, english: bool) -> list[Work]:
    """Write one raw file per work for the Old English (or the English) source."""
    source_id = ENGLISH_SOURCE if english else OE_SOURCE
    out_dir = output_dir / source_id
    out_dir.mkdir(parents=True, exist_ok=True)
    html = fetch(output_dir, force=force).read_text(encoding="utf-8")
    pieces = parse(html)
    works: list[Work] = []
    for piece in pieces:
        units = piece.english if english else piece.units
        if english and not units:
            continue  # the Latin preface has no English
        work = make_work(piece, english)
        out_path = out_dir / f"{piece.local_id}.json"
        works.append(work)
        if out_path.exists() and not force:
            continue
        out_path.write_text(
            json.dumps({"work": work.model_dump(), "paragraphs": units},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.debug("%s: %d units", work.work_id, len(units))
    log.info("%s: %d works, %d units", source_id, len(works),
             sum(len(p.english if english else p.units) for p in pieces))
    return works
