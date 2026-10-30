"""
Ingestor for Evetts's English translation of the *History of the Patriarchs of
the Coptic Church of Alexandria* (#481, part of #83).

Source: B. Evetts, *History of the Patriarchs of the Coptic Church of
Alexandria* I–IV, Patrologia Orientalis 1.2 (1904), 1.4 (1905), 5.1 (1910) and
10.5 (1915): the Arabic text with Evetts's English translation below it on
every page.  The volumes were published in Paris in 1904–1915, before 1929:
public domain in the United States.  We take the English from archive.org's
existing OCR of the scans (``{item}_djvu.xml``, the word boxes of the text
layer); nothing is re-OCRed and OCR letter errors are left as they are.
Language: eng  Tradition: coptic (the original's)  Genre: patristic
License: public_domain

Items: ``patrologia-orientalis-volume-1``, ``-5`` and ``-10``, re-uploads
(2023) of the University of Toronto (PIMS) scans with a Tesseract 5 text
layer, much better on the English than the original PIMS items' ABBYY layer
(``patrologiaorient01pari``, ``patrologiaorien05pari``,
``patrologiaorien10pari``: on lines of English prose, 4 %, 6 % and 9 % of the
words are not in a corpus word list, against 13 %, 7 % and 13 %).  The
uploader's CC BY-NC-ND label cannot bind a mechanical transcription of a
public-domain text.

Each leaf of a part is split by :mod:`scripts.ingest._ia_djvu` into running
head, Arabic text and apparatus (read by a Latin-script OCR, so letter noise),
English text and footnotes.  Only the English text is kept.  The running
heads, page numbers, the Arabic, its apparatus and Evetts's footnotes are
dropped (the footnotes are mostly apparatus and references, and their OCR is
mixed with the apparatus noise), and so are the footnote numbers glued to
words, the manuscript page numbers in the margin (``* P. 45``) with their
asterisks, and the line numbers in the margin.

Works: one per part, ``evetts-hop-eng/history-of-the-patriarchs-{part}``, the
translation of ``openiti/history-of-the-patriarchs-{part}`` (the OpenITI OCR
of the Arabic of the same pages, #480), with its dates and author.

Refs follow the Arabic works': section ``{n}`` is the life of the n-th
patriarch, ``{n}`` its heading unit and ``{n}.{k}`` the English of the k-th
printed page of the life (a page shared by two lives is split at the
heading); part 1 opens with the compiler's prefaces and the *Priesthood of
Christ*, section ``0``.  Where a life starts is curated in
``scripts/ingest/data/evetts_hop_eng_patriarchs.csv`` (a pattern for the
OCR of the heading line and the heading as printed, read from the scans,
since the OCR of the small-capital headings is often damaged).  The date
range Evetts adds to each heading ("A. D. 62-85") is marked editorial
(``note``); a heading inside a page (a preface's title, a chapter that
continues a life) is marked ``heading``.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import statistics
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from patristica.models import Work
from scripts.ingest import _ia_djvu
from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

SOURCE_ID = "evetts-hop-eng"
LICENSE = "public_domain"

_DATA = Path(__file__).parent / "data" / "evetts_hop_eng_patriarchs.csv"


@dataclass(frozen=True)
class Item:
    """An archive.org item and the name of its files (before ``_djvu.xml``)."""
    identifier: str
    stem: str

    @property
    def url(self) -> str:
        return f"https://archive.org/download/{self.identifier}/{quote(self.stem)}_djvu.xml"

    @property
    def details(self) -> str:
        return f"https://archive.org/details/{self.identifier}"


VOL1 = Item("patrologia-orientalis-volume-1", "Patrologia orientalis, Volume 1")
VOL5 = Item("patrologia-orientalis-volume-5", "Patrologia orientalis, Volume 5")
VOL10 = Item("patrologia-orientalis-volume-10", "Patrologia orientalis, Volume 10")


@dataclass(frozen=True)
class Part:
    """One of Evetts's parts: its fascicle and the leaves of its translation."""
    number: int
    fascicle: str
    year: int
    span: str
    item: Item
    first_leaf: int        # the first leaf with English of the part
    last_leaf: int

    @property
    def openiti_id(self) -> str:
        return f"openiti/history-of-the-patriarchs-{self.number}"


PARTS: dict[int, Part] = {
    1: Part(1, "1.2", 1904, "Mark to Theonas (d. 300)", VOL1, 130, 236),
    2: Part(2, "1.4", 1905, "Peter I to Benjamin I (d. 661)", VOL1, 410, 545),
    3: Part(3, "5.1", 1910, "Agathon to Michael I (d. 766)", VOL5, 14, 226),
    4: Part(4, "10.5", 1915, "Mennas I to Joseph I (d. 849)", VOL10, 372, 562),
}
#: As the Arabic works (scripts/ingest/openiti.py, HOP_DATES): the Coptic
#: lives to the Arabic redaction of Mawhūb ibn Manṣūr (c. 1088).
HOP_DATES: dict[int, tuple[int, int]] = {1: (600, 1088), 2: (690, 1088), 3: (715, 1088), 4: (850, 1088)}
#: As the Arabic works: a compilation (author_strings.csv).
HOP_AUTHOR = "History of the Patriarchs of Alexandria (compilation)"


@dataclass(frozen=True)
class Patriarch:
    number: int
    part: int
    marker: re.Pattern[str]
    heading: str


def load_patriarchs(path: Path = _DATA) -> list[Patriarch]:
    rows = [ln for ln in path.read_text(encoding="utf-8").splitlines() if not ln.startswith("#")]
    out = [Patriarch(int(r["number"]), int(r["part"]), re.compile(r["marker"]), r["heading"])
           for r in csv.DictReader(rows)]
    if [p.number for p in out] != list(range(1, len(out) + 1)):
        raise ValueError(f"{path}: patriarchs must be numbered 1…n in order")
    return out


def fetch(output_dir: Path, item: Item, force: bool = False) -> Path:
    """The ``_djvu.xml`` of *item* (downloaded once into ``data/raw/_cache``)."""
    dest = output_dir / "_cache" / SOURCE_ID / item.identifier / f"{item.identifier}_djvu.xml"
    return download_file(item.url, dest, etag_cache=False, force=force)


# ---------------------------------------------------------------------------
# Leaves → English lines
# ---------------------------------------------------------------------------

def body_metrics(leaves: list[_ia_djvu.Leaf]) -> tuple[float, float]:
    """The English body type's line height and line spacing in these leaves."""
    heights: list[float] = []
    gaps: list[float] = []
    for leaf in leaves:
        prev = None
        for ln in leaf.lines:
            if len(ln.tokens) >= 8 and ln.english >= 0.25:
                heights.append(ln.height)
                if prev is not None and 0 < ln.top - prev.top < 4 * ln.height:
                    gaps.append(ln.top - prev.top)
                prev = ln
            else:
                prev = None
    if not heights or not gaps:
        raise ValueError("no English body text found")
    return statistics.median(heights), statistics.median(gaps)


@dataclass
class PageLines:
    """The English of one leaf, and every line of it (to find headings)."""
    leaf: int
    english: list[_ia_djvu.Line]
    all_lines: list[_ia_djvu.Line]
    left: float


def part_pages(part: Part, leaves: dict[int, _ia_djvu.Leaf]) -> tuple[list[PageLines], float]:
    """The English lines of every leaf of *part*, in order, and the body type's
    line height."""
    span = [leaves[i] for i in range(part.first_leaf, part.last_leaf + 1)]
    body, spacing = body_metrics(span)
    pages: list[PageLines] = []
    for leaf in span:
        layout = _ia_djvu.page_layout(leaf, body, spacing)
        lines = [ln for ln in leaf.lines if ln is not layout.head]
        pages.append(PageLines(leaf.index, layout.english, lines, layout.left))
    return pages, body


# ---------------------------------------------------------------------------
# Text cleanup
# ---------------------------------------------------------------------------

#: A manuscript page number in the margin, merged into the line by the OCR:
#: "* P. 45", "*P.103", "* p.15".
_MS_PAGE_RE = re.compile(r"\*\s*[PpF][.,]\s*\d{1,3}\b\.?")
#: The asterisk that marks the manuscript page break in the text, alone or
#: read as a stray quotation mark (Evetts quotes with « »).
_ASTERISK_RE = re.compile(r"(?:(?<=\s)|^)[*#”“‘’']+(?=\s|$)")
#: A footnote number glued to a word: "Ammon1.", "PATRIARCH1".
_NOTE_NUMBER_RE = re.compile(r"(?<=[A-Za-z])\d{1,2}(?=[\s.,;:!?)»]|$)")
#: The line numbers printed in the margin every five lines.
_LINE_NUMBERS = {"5", "10", "15", "20", "25", "30", "35"}
#: A chapter line (or the part's first line) printed above a patriarch's heading.
_CHAPTER_RE = re.compile(r"^\W{0,3}(?:[CG][HIl]{1,3}[AÀ][PB]T[EÉ]R|PART\s+[I1l]+\W*$)")


def clean_line(line: _ia_djvu.Line, left: float, col: float) -> str:
    text = line.text
    parts = text.split(" ", 1)
    if len(parts) == 2 and parts[0] in _LINE_NUMBERS and line.x0 < left - 0.01 * col:
        text = parts[1]
    text = _MS_PAGE_RE.sub(" ", text)
    text = _ASTERISK_RE.sub(" ", text)
    text = _NOTE_NUMBER_RE.sub("", text)
    return " ".join(text.split())


def join_lines(texts: list[tuple[str, bool]]) -> tuple[str, list[list]]:
    """Join a page's lines into one text: a word broken at a line end
    ("con-" + "ception") is rejoined.  Lines flagged True are headings inside
    the page: returns their spans."""
    out = ""
    spans: list[list] = []
    for text, heading in texts:
        if not text:
            continue
        if out.endswith(("-", "¬")) and text[:1].islower() and not heading:
            out = out[:-1]
        elif out:
            out += " "
        start = len(out)
        out += text
        if heading:
            spans.append([start, len(out), "heading"])
    return out, spans


#: Evetts's date range at the end of a heading: "A. D. 62-85.".
_HEADING_DATE_RE = re.compile(r"\s*A\. D\. [\d-]+\.$")


def heading_unit(n: int, heading: str) -> dict:
    unit: dict = {"ref": str(n), "text": heading}
    m = _HEADING_DATE_RE.search(heading)
    if m:
        unit["editorial"] = [[m.start() + (len(m.group()) - len(m.group().lstrip())), len(heading), "note"]]
    return unit


def is_inline_heading(line: _ia_djvu.Line, body: float) -> bool:
    return _ia_djvu.is_heading_line(line, body) and not line.english_hits >= 3


# ---------------------------------------------------------------------------
# Lives
# ---------------------------------------------------------------------------

def part_units(part: Part, pages: list[PageLines], patriarchs: list[Patriarch],
               body: float) -> list[dict]:
    """The raw units of one part (see the module doc)."""
    # where each life starts: (page index, the heading line)
    starts: list[tuple[int, _ia_djvu.Line, Patriarch]] = []
    for p in patriarchs:
        hits = [(i, ln) for i, pg in enumerate(pages) for ln in pg.all_lines
                if p.marker.search(ln.text)]
        if len(hits) != 1:
            raise ValueError(
                f"History of the Patriarchs (English): marker of patriarch {p.number} "
                f"({p.marker.pattern!r}) found {len(hits)} times in part {part.number}"
            )
        starts.append((hits[0][0], hits[0][1], p))
    order = [(i, ln.top) for i, ln, _ in starts]
    if order != sorted(order):
        raise ValueError(f"History of the Patriarchs (English): lives out of order in part {part.number}")

    units: list[dict] = []
    section = 0
    k = 0
    starts_at = {i: [] for i, _, _ in starts}
    for i, ln, p in starts:
        starts_at[i].append((ln, p))

    def flush(lines: list[tuple[str, bool]]) -> None:
        nonlocal k
        text, spans = join_lines(lines)
        if not text:
            return
        k += 1
        unit: dict = {"ref": f"{section}.{k}", "text": text}
        if spans:
            unit["editorial"] = spans
        units.append(unit)

    for i, pg in enumerate(pages):
        col = max((ln.x1 for ln in pg.english), default=pg.left + 1) - pg.left
        heads = sorted(starts_at.get(i, []), key=lambda h: h[0].top)
        current: list[tuple[str, bool]] = []
        english = list(pg.english)
        for head_line, p in heads:
            before = [ln for ln in english if ln.top < head_line.top]
            english = [ln for ln in english if ln.top > head_line.top and ln is not head_line]
            # the chapter line just above the heading is part of the curated heading
            while before and (_CHAPTER_RE.search(before[-1].text)
                              or _ia_djvu.is_heading_line(before[-1], body)) \
                    and head_line.top - before[-1].top < 6 * body:
                before.pop()
            current += [(clean_line(ln, pg.left, col), is_inline_heading(ln, body)) for ln in before]
            if section > 0 or units or any(t for t, _ in current):
                flush(current)
            current = []
            section, k = p.number, 0
            units.append(heading_unit(p.number, p.heading))
        current += [(clean_line(ln, pg.left, col), is_inline_heading(ln, body)) for ln in english]
        if section == 0 and part.number != 1:
            if any(t for t, _ in current):
                raise ValueError(f"part {part.number}: English before the first life (leaf {pg.leaf})")
            continue
        flush(current)
    return units


def hop_work(part: Part) -> Work:
    item = part.item
    edition = (
        f"B. Evetts, History of the Patriarchs of the Coptic Church of Alexandria "
        f"{'I II III IV'.split()[part.number - 1]}, Patrologia Orientalis {part.fascicle} "
        f"({part.year}), English translation; OCR of the University of Toronto scan "
        f"(archive.org {item.identifier}, Tesseract text layer"
    )
    edition += "), uncorrected; the Arabic text, apparatus, running heads and footnotes removed"
    return Work(
        work_id=f"{SOURCE_ID}/history-of-the-patriarchs-{part.number}",
        source_id=SOURCE_ID,
        author=HOP_AUTHOR,
        title=(f"History of the Patriarchs of the Coptic Church of Alexandria, "
               f"part {part.number}: {part.span}"),
        date_range=HOP_DATES[part.number],
        date_confidence="approximate",
        genre="patristic",
        language="eng",
        tradition="coptic",
        license=LICENSE,
        provenance_url=item.details,
        edition=edition,
        translation_of=part.openiti_id,
    )


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def _leaves(path: Path, lo: int, hi: int) -> dict[int, _ia_djvu.Leaf]:
    out: dict[int, _ia_djvu.Leaf] = {}
    for leaf in _ia_djvu.read_leaves(path):
        if leaf.index > hi:
            break
        if leaf.index >= lo:
            out[leaf.index] = leaf
    return out


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    out_dir = output_dir / SOURCE_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    slugs = {n: f"history-of-the-patriarchs-{n}" for n in PARTS}
    if not force and all((out_dir / f"{s}.json").exists() for s in slugs.values()):
        return [Work(**json.loads((out_dir / f"{s}.json").read_text(encoding="utf-8"))["work"])
                for s in slugs.values()]

    patriarchs = load_patriarchs()
    works: list[Work] = []
    files: dict[Item, Path] = {}
    for n, part in PARTS.items():
        if part.item not in files:
            files[part.item] = fetch(output_dir, part.item, force)
        leaves = _leaves(files[part.item], part.first_leaf, part.last_leaf)
        pages, body = part_pages(part, leaves)
        units = part_units(part, pages, [p for p in patriarchs if p.part == n], body)
        work = hop_work(part)
        path = out_dir / f"{slugs[n]}.json"
        record = {"work": work.model_dump(), "paragraphs": units}
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log.info("Wrote %s (%d units)", path, len(units))
        works.append(work)
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
