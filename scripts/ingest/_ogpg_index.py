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
``col_start``, ``col_end``
    First and last Migne column of the work.  ``col_end`` may be empty: the
    work then runs to the column before the next row's ``col_start`` (or to
    the end of the volume).
``author``, ``title``
    English author name (as in ``_ogpg_volumes``), title as printed by Migne
    (Latin), normalised.
``cpg``
    *Clavis Patrum Graecorum* number, when known.
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
split at the first Greek capitals heading (the new work's title); without a
heading the whole page goes to the new work if it starts in the page's first
column, and to the previous work otherwise.  Paragraphs on pages with no
column (plates, duplicated leaves, failed OCR heads) belong with the last
numbered page before them.
"""

from __future__ import annotations

import csv
import functools
from dataclasses import dataclass
from pathlib import Path

from patristica.models import DateConfidence
from patristica.period import work_in_period

INDEX_PATH = Path(__file__).parent / "data" / "ogpg_index.csv"
BASES = frozenset({"elenchus", "heads", "curated"})
_CONFIDENCES = frozenset({"established", "approximate", "uncertain"})
REMAINDER_SLUG = "other"


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
    date_composed: int | None
    date_range: tuple[int, int] | None
    date_confidence: DateConfidence | None
    basis: str
    duplicate_of: str | None
    note: str | None

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
    seen: set[tuple[str, str]] = set()
    for n, rec in enumerate(reader, 2):
        where = f"ogpg_index.csv row {n}"
        vol, slug = rec["volume"].strip(), rec["slug"].strip()
        if not vol or not slug or not rec["title"].strip():
            raise OgpgIndexError(f"{where}: volume, slug and title are required")
        if (vol, slug) in seen:
            raise OgpgIndexError(f"{where}: duplicate slug {vol}/{slug}")
        if slug == REMAINDER_SLUG or "/" in slug or slug != slug.lower():
            raise OgpgIndexError(f"{where}: bad slug {slug!r}")
        seen.add((vol, slug))
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
            cpg=rec["cpg"].strip() or None,
            date_composed=composed,
            date_range=(lo, hi) if lo is not None and hi is not None else None,
            date_confidence=conf,  # type: ignore[arg-type]
            basis=basis,
            duplicate_of=rec["duplicate_of"].strip() or None,
            note=rec["note"].strip() or None,
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
    spans: list[tuple[int, int] | None] = []
    last: tuple[int, int] | None = None
    for para in paragraphs:
        if para.get("cols"):
            last = (para["cols"][0], para["cols"][1])
        spans.append(last)

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
