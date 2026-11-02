"""
Work index for the Open Patrologia Graeca: which Migne columns hold which work.

The OCR repos have no work boundaries, so ``ogpg.py`` extracts each volume as
one stream of paragraphs, each tagged with the Migne columns of its page
(``_ogpg_columns``) and with any Greek capitals heading just before it.  This
module cuts that stream into works using the curated table
``scripts/ingest/data/ogpg_index.csv``, one row per work:

``volume``
    The repo slug of the volume (``vol-045``, ``vol-016-pt1``).
``slug``
    Short, stable id of the work within the volume; the work id is
    ``ogpg/{volume}/{slug}``.  Don't rename slugs: they are in reader URLs.
    A slug may appear on several rows when a work is printed in pieces
    (Pachymeres's paraphrase after every chapter of Pseudo-Dionysius); its
    rows must then agree on everything but the columns and the note.
``col_start``, ``col_end``
    First and last Migne column of the work.  ``col_end`` may be empty: the
    work then runs to the column before the next row's ``col_start`` (or to
    the end of the volume).
``author``, ``title``
    English author name (as in ``_ogpg_volumes``), title as printed by Migne
    (Latin), normalised.
``cpg``, ``tlg``
    *Clavis Patrum Graecorum* number (``5200``) and TLG work id
    (``tlg4090.tlg096``), when the row is one whole work with a known number.
    Left empty for a row holding several works.  The ingestor writes them to
    ``Work.external_ids`` (``CPG:…``, ``TLG:…``), where the version-group
    crosswalk (``patristica/versions.py``) joins the work to its other
    editions; they come from the PTA catalogue and the TLG ids of First1K and
    Perseus works checked against the text (#192).
``bhg``
    *Bibliotheca Hagiographica Graeca* number (``882``, ``1205``) of a row that
    is one whole hagiographic text or homily, written to ``Work.external_ids``
    as ``BHG:…`` (#375).  It is the last column and may be left off the rows
    that have none.
``date_composed``, ``date_start``, ``date_end``, ``date_confidence``
    As in ``Work``.  Empty dates fall back to the volume's (``_ogpg_volumes``).
    A work whose range starts after the collection period
    (``patristica.period.work_in_period``) is dropped.
``basis``
    Where the row comes from: ``elenchus`` (the volume's printed table of
    contents, "Elenchus operum quae in hoc tomo continentur", read from the
    OCR and checked against the work's title in the text), ``heads`` (no
    Elenchus entry; boundaries from the OCR headings and running heads) or
    ``curated`` (other sources; see ``note``).
``duplicate_of``
    Work id of a cleaner edition of the same text already in the corpus
    (First1KGreek, PTA, Perseus).  Both are kept; see DATA_COLLECTION_PLAN.md.
``note``
    Free text: uncertainties, spuria, what the row covers.

Volumes without rows stay one work each (``ogpg/vol-NNN``, as before).  In a
volume with rows, text outside every row (front matter, prefaces, Migne's
notes, unindexed pieces, pages whose column is unknown before the first
numbered page) becomes the remainder work ``ogpg/{volume}/other``, so nothing
is dropped silently.

Boundaries inside a page
------------------------
Column numbers are known per scan page, so a page on which a work starts may
also hold the end of the previous one.  On such a page the paragraphs are
split at the first Greek capitals heading (the new work's title), or, when
the extraction found none, at the first paragraph that opens with a run of
Greek capitals (a heading run into its paragraph, ``ΠΡΟΟΙΜΙΟΝ. α’. …``; the
OCR may read some capitals as Latin ones or in lower case, ``UMIAIA ΕΙΣ ΤΟ``,
``οΜιΛιΑ ΠΡΟΣ ΤΟΥΣ``); without either, the whole page goes to the new work if
it starts in the page's first column, and to the previous work otherwise.
Before that, on such a page with fewer headings than works starting, a
paragraph that runs the end of one work into the next one's title (``…
Ἀμήν. ΤΟΥ ΑΥΤΟΥ ΟΜΙΛΙΑ …``) is cut before the title (``split_inline_headings``,
#577), so the title opens a paragraph of its own.  Paragraphs on pages with no
column (plates, duplicated leaves, failed OCR heads) belong with the last
numbered page before them.
"""

from __future__ import annotations

import csv
import functools
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from patristica.models import DateConfidence
from patristica.period import work_in_period

INDEX_PATH = Path(__file__).parent / "data" / "ogpg_index.csv"
BASES = frozenset({"elenchus", "heads", "curated"})
_CONFIDENCES = frozenset({"established", "approximate", "uncertain"})
REMAINDER_SLUG = "other"
_CPG = re.compile(r"^\d{4}[a-z]?(\.\d+)?$")
_TLG = re.compile(r"^tlg\d{4}\.tlg\d{3}$")
_BHG = re.compile(r"^\d{1,4}[a-z]{0,2}$")
# Columns that must agree between the rows of a work with several ranges.
_WORK_FIELDS = ("author", "title", "cpg", "tlg", "bhg", "date_composed", "date_start",
                "date_end", "date_confidence", "basis", "duplicate_of")


class OgpgIndexError(ValueError):
    """Malformed ``ogpg_index.csv``."""


@dataclass(frozen=True)
class IndexRow:
    volume: str
    slug: str
    col_start: int
    col_end: int | None
    author: str | None
    title: str
    cpg: str | None
    tlg: str | None
    date_composed: int | None
    date_range: tuple[int, int] | None
    date_confidence: DateConfidence | None
    basis: str
    duplicate_of: str | None
    note: str | None
    bhg: str | None = None

    @property
    def in_period(self) -> bool:
        return work_in_period(self.date_range)


def _int(value: str, what: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        raise OgpgIndexError(f"{what}: not an integer: {value!r}") from None


def parse_index(lines: list[str]) -> dict[str, list[IndexRow]]:
    """Parse the CSV text (``#`` comment lines allowed) → rows per volume.

    Rows are returned in column order, with ``col_end`` resolved against the
    next row (``None`` for the last row of a volume: to the end).
    """
    reader = csv.DictReader(line for line in lines if not line.startswith("#"))
    by_vol: dict[str, list[IndexRow]] = {}
    seen: dict[tuple[str, str], tuple[str, ...]] = {}
    for n, rec in enumerate(reader, 2):
        where = f"ogpg_index.csv row {n}"
        vol, slug = rec["volume"].strip(), rec["slug"].strip()
        if not vol or not slug or not rec["title"].strip():
            raise OgpgIndexError(f"{where}: volume, slug and title are required")
        if slug == REMAINDER_SLUG or "/" in slug or slug != slug.lower():
            raise OgpgIndexError(f"{where}: bad slug {slug!r}")
        # A slug may repeat: the work then consists of several column ranges
        # (e.g. a paraphrase printed after every chapter), with the same metadata.
        meta = tuple((rec.get(k) or "").strip() for k in _WORK_FIELDS)
        if (vol, slug) in seen and seen[(vol, slug)] != meta:
            raise OgpgIndexError(f"{where}: {vol}/{slug} repeats with different metadata")
        seen[(vol, slug)] = meta
        basis = rec["basis"].strip()
        if basis not in BASES:
            raise OgpgIndexError(f"{where}: unknown basis {basis!r}")
        conf = rec["date_confidence"].strip() or None
        if conf is not None and conf not in _CONFIDENCES:
            raise OgpgIndexError(f"{where}: unknown date_confidence {conf!r}")
        start = _int(rec["col_start"], where)
        if start is None:
            raise OgpgIndexError(f"{where}: col_start is required")
        lo, hi = _int(rec["date_start"], where), _int(rec["date_end"], where)
        if (lo is None) != (hi is None) or (lo is not None and hi is not None and lo > hi):
            raise OgpgIndexError(f"{where}: bad date range {lo}–{hi}")
        cpg, tlg = rec["cpg"].strip() or None, rec["tlg"].strip() or None
        if cpg is not None and not _CPG.match(cpg):
            raise OgpgIndexError(f"{where}: bad cpg {cpg!r}")
        if tlg is not None and not _TLG.match(tlg):
            raise OgpgIndexError(f"{where}: bad tlg {tlg!r}")
        bhg = (rec.get("bhg") or "").strip() or None  # the optional last column
        if bhg is not None and not _BHG.match(bhg):
            raise OgpgIndexError(f"{where}: bad bhg {bhg!r}")
        composed = _int(rec["date_composed"], where)
        if composed is not None and lo is not None and hi is not None \
                and not lo <= composed <= hi:
            raise OgpgIndexError(f"{where}: date_composed {composed} outside {lo}–{hi}")
        by_vol.setdefault(vol, []).append(IndexRow(
            volume=vol,
            slug=slug,
            col_start=start,
            col_end=_int(rec["col_end"], where),
            author=rec["author"].strip() or None,
            title=rec["title"].strip(),
            cpg=cpg,
            tlg=tlg,
            date_composed=composed,
            date_range=(lo, hi) if lo is not None and hi is not None else None,
            date_confidence=conf,  # type: ignore[arg-type]
            basis=basis,
            duplicate_of=rec["duplicate_of"].strip() or None,
            note=rec["note"].strip() or None,
            bhg=bhg,
        ))
    for vol, rows in by_vol.items():
        rows.sort(key=lambda r: r.col_start)
        resolved: list[IndexRow] = []
        for i, row in enumerate(rows):
            nxt = rows[i + 1].col_start if i + 1 < len(rows) else None
            end = row.col_end if row.col_end is not None else (
                nxt - 1 if nxt is not None else None)
            if end is not None and end < row.col_start:
                raise OgpgIndexError(f"{vol}/{row.slug}: ends (col {end}) before it starts "
                                  f"(col {row.col_start})")
            if nxt is not None and end is not None and end >= nxt:
                raise OgpgIndexError(f"{vol}/{row.slug}: overlaps the next row (col {nxt})")
            resolved.append(IndexRow(**{**row.__dict__, "col_end": end}))
        by_vol[vol] = resolved
    return by_vol


@functools.cache
def load_index(path: Path = INDEX_PATH) -> dict[str, list[IndexRow]]:
    """Rows of ``ogpg_index.csv`` per volume slug (cached)."""
    return parse_index(path.read_text(encoding="utf-8").splitlines(keepends=True))


# ---------------------------------------------------------------------------
# Refs
# ---------------------------------------------------------------------------

def assign_refs(paragraphs: list[dict], vol_slug: str) -> list[str]:
    """Positional refs for a volume's paragraphs, in order.

    ``ogpg.{vol}.c{first column:04d}.{n}``: the first Migne column of the
    paragraph's page and the paragraph's number on that page.  Pages with no
    known column use the scan page instead (``p{page:04d}``).  If a column
    recurs (a leaf scanned twice), numbering continues, so refs stay unique.
    """
    counts: dict[str, int] = {}
    refs: list[str] = []
    for para in paragraphs:
        span = para.get("cols")
        if span:
            key = f"c{span[0]:04d}"
        else:
            stem = para.get("stem", "")
            key = f"p{int(stem):04d}" if stem.isdigit() else f"p{stem or 'x'}"
        counts[key] = counts.get(key, 0) + 1
        refs.append(f"ogpg.{vol_slug}.{key}.{counts[key]}")
    return refs


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------

def _owner(rows: list[IndexRow], col: int) -> int | None:
    for i, row in enumerate(rows):
        if row.col_start <= col and (row.col_end is None or col <= row.col_end):
            return i
    return None


def assign_works(paragraphs: list[dict], rows: list[IndexRow]) -> list[int | None]:
    """Index into ``rows`` of the work each paragraph belongs to (None: remainder).

    ``paragraphs`` are dicts with ``cols`` (``[first, last]`` or None) and
    ``title`` (heading seen before the paragraph, or None), in volume order.
    See the module docstring for the rules.
    """
    # Effective span: own columns, else those of the last numbered page before.
    spans = _effective_spans(paragraphs)

    out: list[int | None] = [None] * len(paragraphs)
    i = 0
    while i < len(paragraphs):
        span = spans[i]
        j = i
        while j < len(paragraphs) and spans[j] == span:
            j += 1
        if span is not None:
            _assign_page(range(i, j), span, paragraphs, rows, out)
        i = j
    return out


# Greek capitals a paragraph must open with to count as headed; shorter runs
# are speaker labels (``ΚΥΡ.``) or numerals.
_HEADING_MIN_LETTERS = 8
# …of which at least this many must be Greek letters (a Latin running head or
# heading, ``HOMILIA``, is not one).
_HEADING_MIN_GREEK = 4
_HEADING_MAX_TOKENS = 12
# Latin capitals the OCR reads for Greek ones (``UMIAIA`` = ΟΜΙΛΙΑ), and Greek
# small letters it reads for capitals of the same shape (``οΜιΛιΑ``).
_LOOKALIKE_CAPITALS = frozenset("ABEHIKMNOPTUXYZ")
_SMALL_AS_CAPITAL = frozenset("οιυ")
_TOKEN = re.compile(r"\S+")
# Where an inline title may start: after the end of a sentence.
_SENTENCE_END = re.compile(r"(?:[.·;!]|Ἀμήν|ἀμήν)[\s’'\"»)]*\s")


def _is_greek_letter(c: str) -> bool:
    return "GREEK" in unicodedata.name(c, "")


def _caps_token(token: str) -> tuple[int, int] | None:
    """(letters, Greek letters) of a token in (OCR-read) Greek capitals, else None;
    (0, 0) for a token without letters (a numeral in brackets, punctuation)."""
    letters = [c for c in token if c.isalpha()]
    if not letters:
        return (0, 0)
    if not any(c.isupper() for c in letters):
        return None
    for c in letters:
        if c.isupper():
            if not (_is_greek_letter(c) or c in _LOOKALIKE_CAPITALS):
                return None
        elif c not in _SMALL_AS_CAPITAL:
            return None
    return len(letters), sum(1 for c in letters if _is_greek_letter(c))


def _heading_run(text: str, start: int = 0) -> tuple[int, int, int] | None:
    """The run of capitals tokens starting at ``start`` → (end offset, letters,
    Greek letters), if it is long enough for a heading; else None."""
    end, letters, greek, tokens = start, 0, 0, 0
    for m in _TOKEN.finditer(text, start):
        counts = _caps_token(m.group())
        # A run starts with letters: ``0 ΒΑΣΙΛΕΥΣ.`` is a speaker label (Ὁ).
        if counts is None or tokens >= _HEADING_MAX_TOKENS or (not letters and not counts[0]):
            break
        letters += counts[0]
        greek += counts[1]
        tokens += 1
        end = m.end()
    if letters >= _HEADING_MIN_LETTERS and greek >= _HEADING_MIN_GREEK:
        return end, letters, greek
    return None


def _opens_with_heading(text: str) -> bool:
    """Whether a paragraph opens with a heading in Greek capitals."""
    m = re.match(r"[^\w]{0,3}", text)
    return _heading_run(text, m.end() if m else 0) is not None


def _inline_heading(text: str) -> int | None:
    """Offset of a title run into a paragraph after the end of a sentence
    (two or more capitals tokens), or None."""
    for m in _SENTENCE_END.finditer(text):
        run = _heading_run(text, m.end())
        if run is not None and len(_TOKEN.findall(text[m.end():run[0]])) >= 2 \
                and run[0] < len(text.rstrip()):
            return m.end()
    return None


def _effective_spans(paragraphs: list[dict]) -> list[tuple[int, int] | None]:
    """Each paragraph's columns, else those of the last numbered page before it."""
    spans: list[tuple[int, int] | None] = []
    last: tuple[int, int] | None = None
    for para in paragraphs:
        if para.get("cols"):
            last = (para["cols"][0], para["cols"][1])
        spans.append(last)
    return spans


def split_inline_headings(paragraphs: list[dict], rows: list[IndexRow]) -> list[dict]:
    """``paragraphs`` with each one that runs into a work's title cut before it.

    Only on a page where works start and the extraction marked fewer of them
    (no heading line before a paragraph, and fewer paragraphs opening with a
    heading than works starting); see the module docstring.  The second part
    keeps the paragraph's page and columns.
    """
    spans = _effective_spans(paragraphs)
    need: dict[tuple[int, int], bool] = {}
    for span in set(spans):
        if span is None:
            continue
        starting = sum(1 for r in rows if span[0] <= r.col_start <= span[1])
        if not starting:
            continue
        on_page = [p for p, sp in zip(paragraphs, spans) if sp == span]
        if any(p.get("title") for p in on_page):
            continue
        marked = sum(1 for p in on_page if _opens_with_heading(p.get("text", "")))
        need[span] = marked < starting
    out: list[dict] = []
    for para, span in zip(paragraphs, spans):
        k = _inline_heading(para.get("text", "")) if need.get(span) else None
        if k is None:
            out.append(para)
            continue
        text = para["text"]
        out.append({**para, "text": text[:k].rstrip()})
        out.append({**para, "text": text[k:], "title": None})
    return out


def _assign_page(idx: range, span: tuple[int, int], paragraphs: list[dict],
                 rows: list[IndexRow], out: list[int | None]) -> None:
    a, b = span
    starting = [k for k, r in enumerate(rows) if a <= r.col_start <= b]
    # The work running in at the top of the page, if any.
    incoming = _owner(rows, a)
    if incoming is not None and incoming in starting:
        incoming = _owner(rows, a - 1) if a > 1 else None
    if not starting:
        for k in idx:
            out[k] = incoming
        return
    marks = [k for k in idx if paragraphs[k].get("title")]
    if not marks:
        # A heading the extraction ran into its paragraph (``ΠΡΟΟΙΜΙΟΝ. α’. …``).
        marks = [k for k in idx if _opens_with_heading(paragraphs[k].get("text", ""))]
    owner = incoming
    if not marks:
        if rows[starting[0]].col_start == a:
            owner = starting[0]
        for k in idx:
            out[k] = owner
        return
    # Split at the first len(starting) headings, in order.
    splits = dict(zip(marks, starting))
    for k in idx:
        if k in splits:
            owner = splits[k]
        out[k] = owner
