"""
Coverage of every OGPG work: how much of its Migne column range has text, and
why each missing page is missing (#706, step 1 of #705).

The OGPG ingestor (``scripts/ingest/ogpg.py``) cuts each Migne volume into
works by the column ranges of ``scripts/ingest/data/ogpg_index.csv``.  A work
whose range has pages without text has lost them somewhere: to another work
(a boundary problem), to the page → column map, or to the OCR.  This measures
it, from local data only (``data/raw``, so it runs where the data is, not in
CI)::

    uv run python -m scripts.ogpg_coverage [--raw-dir data/raw/ogpg] [--scans]
        [--works] [--holes] [--json FILE]

Migne prints two columns per page, so a page is counted by its first, odd
column; a unit's column is in its ref (``ogpg.vol-075.c0459.2``).  Per work:
expected pages (its index ranges; the last row of a volume runs to the last
column the scan maps), pages with text, the *holes* (runs of missing pages) and
the boundary flags of ``scripts.ogpg_boundaries``.  Each missing page gets a
cause, the first that applies:

``elsewhere``
    the page's text is in another work file of the volume (another work or
    ``other.json``): a boundary or assignment problem, not missing text;
``unplaced``
    the column map gave no column to some page of the primary scan around
    here, and that page's text is in the volume under a page ref
    (``ogpg.{vol}.p0203.1``): the text exists but its column is unknown;
``unmapped``
    no page of the primary scan maps to this column, and no unplaced text is
    near it (a leaf the scan lacks, or one the map lost, #578);
``no_text``
    a page of the primary scan maps here, but the extraction kept nothing of
    it.  With ``--scans`` (the clones in ``data/raw/_repos/ogpg``) this splits
    by the page's own OCR into ``blank`` (almost no text), ``latin`` (mostly
    Latin letters: a page that is legitimately not Greek), ``dropped`` (Greek
    that passes the dictionary filter, so the cross-scan vote or the repeat
    check removed it) and ``garbled`` (Greek the filters rejected).

With ``--scans`` a missing page that is not ``elsewhere`` is also *fillable*
when another scan of the volume has Greek passing the dictionary filter on a
page its own column map puts there: such holes can be filled from the scans we
have (#90), the rest need new OCR (#94).  The other scans' maps leave out
their repeated leaves' handling, so this is an estimate.

Columns where Migne prints no Greek (a text that survives only in Latin, the
editor's Latin prefaces and indices; the index's ``latin`` column, #708) are
not expected to have text: a page there without text is counted as
``latin_only``, not as missing, so ``latin`` afterwards counts only the
unexplained Latin pages.  A page there with text still counts as present.

Volumes without index rows are one work ``ogpg/{vol}``, measured over the
columns its scan maps.  Index rows dated after the collection period are left
out (their text is not written).  The output is deterministic.
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import logging
import re
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from patristica.console import setup_logging

log = logging.getLogger(__name__)

RAW_DIR = Path("data/raw/ogpg")
REPOS_DIR = Path("data/raw/_repos/ogpg")
EXTRACT_DIR = "_extract"
# Each volume's page → column map (gitignored): the repeat check and the map
# take ~15 s a volume, so they are kept per extract and per version of the code.
CACHE_DIR = Path("data/cache/ogpg_coverage")
_MAP_CODE = ("scripts/ingest/_ogpg_columns.py", "scripts/ingest/_ogpg_repeats.py",
             "scripts/ingest/ogpg.py")
_REPO_ROOT = Path(__file__).resolve().parents[1]

CAUSES = ("elsewhere", "unplaced", "unmapped", "no_text")
SCAN_CAUSES = ("blank", "latin", "dropped", "garbled")

_COL_REF = re.compile(r"\.c(\d+)\.\d+$")
_PAGE_REF = re.compile(r"\.p(\d+)\.\d+$")
# A page with fewer letters than this is blank (a plate, an empty OCR page).
_BLANK_LETTERS = 200
# A page whose letters are less than this share Greek is a Latin page.
_LATIN_GREEK_SHARE = 0.2


def page_of(col: int) -> int:
    """The page a column is printed on, by its first (odd) column."""
    return col if col % 2 else col - 1


def pages_in(ranges: list[tuple[int, int]]) -> list[int]:
    """Pages of column ranges ``[(first, last)]``, sorted."""
    return sorted({page_of(c) for a, b in ranges for c in range(a, b + 1)})


# ---------------------------------------------------------------------------
# Latin-only columns (the index's ``latin`` column, #708)
# ---------------------------------------------------------------------------

LatinRanges = dict[str, list[tuple[int, int | None]]]
_LATIN_RANGE = re.compile(r"^(\d+)-(\d+)$")


def parse_latin(lines: list[str], index: dict) -> LatinRanges:
    """Latin-only column ranges per volume from the CSV text of ``ogpg_index.csv``.

    ``index`` is the same text parsed by ``_ogpg_index.parse_index``: ``all``
    stands for its row's resolved range (``None`` as the end: to the end of
    the volume), and a range must lie inside its row.
    """
    import csv

    from scripts.ingest import _ogpg_index as pgi

    reader = csv.DictReader(line for line in lines if not line.startswith("#"))
    out: LatinRanges = defaultdict(list)
    for n, rec in enumerate(reader, 2):
        value = (rec.get("latin") or "").strip()
        if not value:
            continue
        where = f"ogpg_index.csv row {n}"
        vol, slug, start = rec["volume"].strip(), rec["slug"].strip(), int(rec["col_start"])
        row = next((r for r in index.get(vol, []) if r.slug == slug and r.col_start == start),
                   None)
        if row is None:
            raise pgi.OgpgIndexError(f"{where}: latin on a row the index doesn't have")
        if value == "all":
            out[vol].append((row.col_start, row.col_end))
            continue
        for part in value.split():
            m = _LATIN_RANGE.match(part)
            if not m:
                raise pgi.OgpgIndexError(f"{where}: bad latin range {part!r}")
            a, b = int(m.group(1)), int(m.group(2))
            if not row.col_start <= a <= b or (row.col_end is not None and b > row.col_end):
                raise pgi.OgpgIndexError(
                    f"{where}: latin range {part} outside the row's columns "
                    f"{row.col_start}–{row.col_end if row.col_end is not None else ''}")
            out[vol].append((a, b))
    return {vol: sorted(rs) for vol, rs in out.items()}


def load_latin(path: Path | None = None) -> LatinRanges:
    """Latin-only column ranges of the repository's ``ogpg_index.csv``."""
    from scripts.ingest import _ogpg_index as pgi

    path = path or pgi.INDEX_PATH
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    return parse_latin(lines, pgi.parse_index(lines))


def in_latin(page: int, ranges: list[tuple[int, int | None]]) -> bool:
    """Whether a page (first column) has a column in one of the Latin-only ranges."""
    return any(a <= page + 1 and (b is None or page <= b) for a, b in ranges)


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@dataclass
class Hole:
    """A run of missing pages of one work."""

    first: int                  # first column of the first missing page
    last: int                   # last column of the last missing page
    causes: Counter[str] = field(default_factory=Counter)
    fillable: int = 0           # pages another scan has Greek for (``--scans``)

    @property
    def pages(self) -> int:
        return (self.last - self.first + 1) // 2

    def to_json(self) -> dict:
        return {"cols": [self.first, self.last], "pages": self.pages,
                "causes": dict(sorted(self.causes.items())), "fillable": self.fillable}


@dataclass
class WorkCoverage:
    work: str
    expected: int
    present: int
    holes: list[Hole]
    start_mid: bool | None = None
    end_mid: bool | None = None
    end_apparatus: bool | None = None
    latin_only: int = 0         # pages without text in Latin-only columns (not expected)

    @property
    def missing(self) -> int:
        return self.expected - self.present

    @property
    def coverage(self) -> float:
        return self.present / self.expected if self.expected else 1.0

    @property
    def causes(self) -> Counter[str]:
        total: Counter[str] = Counter()
        for h in self.holes:
            total.update(h.causes)
        return total

    @property
    def fillable(self) -> int:
        return sum(h.fillable for h in self.holes)

    @property
    def largest_hole(self) -> Hole | None:
        return max(self.holes, key=lambda h: (h.pages, -h.first), default=None)

    def to_json(self) -> dict:
        return {"work": self.work, "expected": self.expected, "present": self.present,
                "coverage": round(self.coverage, 4), "latin_only": self.latin_only,
                "causes": dict(sorted(self.causes.items())), "fillable": self.fillable,
                "start_mid": self.start_mid, "end_mid": self.end_mid,
                "end_apparatus": self.end_apparatus,
                "holes": [h.to_json() for h in self.holes]}


# ---------------------------------------------------------------------------
# One volume
# ---------------------------------------------------------------------------


@dataclass
class _File:
    path: Path
    pages: set[int]             # pages with text (first column)
    stems: set[int]             # scan pages of units with a page ref (no column)


def _read_file(path: Path) -> _File:
    data = json.loads(path.read_text(encoding="utf-8"))
    pages: set[int] = set()
    stems: set[int] = set()
    for unit in data.get("paragraphs") or []:
        ref = unit["ref"]
        if m := _COL_REF.search(ref):
            pages.add(page_of(int(m.group(1))))
        elif m := _PAGE_REF.search(ref):
            stems.add(int(m.group(1)))
    return _File(path, pages, stems)


@dataclass
class _ScanMap:
    """The primary scan's page → column map of one volume."""

    stems_of: dict[int, list[str]]   # page (first column) → scan page stems
    unmapped_stems: list[int]        # numeric stems with no column, sorted
    mapped: list[tuple[int, int]]    # (page, stem) of mapped numeric stems, by page
    last_col: int | None


def _map_key(extract_bytes: bytes) -> str:
    h = hashlib.sha256(extract_bytes)
    for rel in _MAP_CODE:
        h.update((_REPO_ROOT / rel).read_bytes())
    return h.hexdigest()


def _cached_scan_map(vol: str, extract_bytes: bytes, extract: dict,
                     cache_dir: Path | None) -> _ScanMap:
    """``_scan_map``, kept in ``cache_dir`` under the extract's and the code's hash."""
    if cache_dir is None:
        return _scan_map(extract)
    key = _map_key(extract_bytes)
    path = cache_dir / f"{vol}.json"
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        if cached.get("key") == key:
            m = cached["map"]
            return _ScanMap({int(k): v for k, v in m["stems_of"].items()},
                            m["unmapped_stems"], [tuple(x) for x in m["mapped"]],
                            m["last_col"])
    except (OSError, ValueError, KeyError):
        pass
    smap = _scan_map(extract)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"key": key, "map": asdict(smap)}), encoding="utf-8")
    return smap


def _scan_map(extract: dict) -> _ScanMap:
    from scripts.ingest import _ogpg_columns as cols
    from scripts.ingest import ogpg

    repeats = ogpg.volume_repeats(extract)
    heads = [(stem, nums) for stem, nums in extract["page_heads"]]
    skip = set(repeats.pages) | set(repeats.moved)
    cmap = cols.map_columns(heads, skip=skip)
    stems_of: dict[int, list[str]] = defaultdict(list)
    unmapped: list[int] = []
    mapped: list[tuple[int, int]] = []
    last: int | None = None
    for stem, _ in heads:
        span = cmap.columns.get(stem)
        if span is None:
            if stem.isdigit() and stem not in skip:
                unmapped.append(int(stem))
            continue
        stems_of[page_of(span[0])].append(stem)
        if stem.isdigit():
            mapped.append((page_of(span[0]), int(stem)))
        last = span[1] if last is None else max(last, span[1])
    return _ScanMap(dict(stems_of), sorted(unmapped), sorted(mapped), last)


def _unplaced_near(page: int, smap: _ScanMap, text_stems: set[int]) -> bool:
    """Whether a page without a column, between the mapped pages around
    ``page``, has text in the volume."""
    pages = [p for p, _ in smap.mapped]
    i = bisect.bisect_left(pages, page)
    lo = smap.mapped[i - 1][1] if i > 0 else -1
    hi = smap.mapped[i][1] if i < len(smap.mapped) else 10**9
    return any(lo < s < hi for s in text_stems)


def _holes(missing: list[tuple[int, str]]) -> list[Hole]:
    holes: list[Hole] = []
    for page, cause in missing:
        if holes and holes[-1].last + 1 == page:
            holes[-1].last = page + 1
        else:
            holes.append(Hole(page, page + 1))
        holes[-1].causes[cause] += 1
    return holes


@dataclass
class VolumeResult:
    volume: str
    works: list[WorkCoverage]
    # (work, page, primary stems) of every ``no_text`` page, and the pages of
    # every other non-``elsewhere`` missing page, for ``--scans``.
    no_text: list[tuple[str, int, list[str]]] = field(default_factory=list)
    lost: list[tuple[str, int]] = field(default_factory=list)


def measure_volume(vol: str, rows: list, raw_dir: Path,
                   cache_dir: Path | None = None,
                   latin: list[tuple[int, int | None]] | None = None) -> VolumeResult | None:
    """Coverage of one volume's works (``rows``: its ``_ogpg_index`` rows;
    ``latin``: its Latin-only column ranges)."""
    from scripts import ogpg_boundaries as ob

    extract_path = raw_dir / EXTRACT_DIR / f"{vol}.json"
    extract_bytes = extract_path.read_bytes() if extract_path.exists() else b""
    extract = json.loads(extract_bytes) if extract_bytes else None
    if extract is not None and "paragraphs" not in extract:
        extract = None          # an empty repo (``"empty": true``)
    smap = (_cached_scan_map(vol, extract_bytes, extract, cache_dir) if extract
            else _ScanMap({}, [], [], None))

    files: dict[str, _File] = {}
    vol_dir = raw_dir / vol
    if vol_dir.is_dir():
        for path in sorted(vol_dir.glob("*.json")):
            files[path.stem] = _read_file(path)
    single = raw_dir / f"{vol}.json"
    if single.exists():
        files[""] = _read_file(single)
    if not files and extract is None:
        return None
    text_stems = set().union(*(f.stems for f in files.values())) if files else set()
    last_col = smap.last_col or max(
        (p + 1 for f in files.values() for p in f.pages), default=None)

    ranges: dict[str, list[tuple[int, int]]] = {}
    for row in rows:
        if not row.in_period:
            continue
        end = row.col_end if row.col_end is not None else last_col
        if end is None or end < row.col_start:
            continue
        ranges.setdefault(row.slug, []).append((row.col_start, end))
    if not rows and "" in files and smap.mapped:
        first = min(p for p, _ in smap.mapped)
        ranges[""] = [(first, last_col or first + 1)]

    result = VolumeResult(vol, [])
    for slug, rs in ranges.items():
        work = f"ogpg/{vol}/{slug}" if slug else f"ogpg/{vol}"
        own = files.get(slug)
        own_pages = own.pages if own else set()
        others = set().union(*(f.pages for k, f in files.items() if k != slug)) \
            if len(files) > (1 if own else 0) else set()
        expected = pages_in(rs)
        missing: list[tuple[int, str]] = []
        latin_only = 0
        for page in expected:
            if page in own_pages:
                continue
            if latin and in_latin(page, latin):
                latin_only += 1
                continue
            if page in others:
                cause = "elsewhere"
            elif page in smap.stems_of:
                cause = "no_text"
                result.no_text.append((work, page, smap.stems_of[page]))
            elif _unplaced_near(page, smap, text_stems):
                cause = "unplaced"
            else:
                cause = "unmapped"
            if cause != "elsewhere":
                result.lost.append((work, page))
            missing.append((page, cause))
        n = len(expected) - latin_only
        wc = WorkCoverage(work, n, n - len(missing), _holes(missing), latin_only=latin_only)
        if own is not None:
            b = ob.check_work(own.path, raw_dir)
            if b is not None:
                wc.start_mid, wc.end_mid, wc.end_apparatus = b.start_mid, b.end_mid, b.end_apparatus
        result.works.append(wc)
    return result


# ---------------------------------------------------------------------------
# Scans (--scans)
# ---------------------------------------------------------------------------


def classify_page(text: str, lexicon: frozenset[str]) -> str:
    """Why a primary page's OCR gave no text: ``blank``, ``latin``, ``dropped`` or ``garbled``."""
    from scripts.ingest import ogpg

    letters = [c for c in text if c.isalpha()]
    if len(letters) < _BLANK_LETTERS:
        return "blank"
    if sum(1 for c in letters if ogpg._is_greek(c)) < _LATIN_GREEK_SHARE * len(letters):
        return "latin"
    return "dropped" if has_passing_greek("500", text, lexicon) else "garbled"


def has_passing_greek(stem: str, text: str, lexicon: frozenset[str]) -> bool:
    """Whether a page has a paragraph the extraction's filters would keep."""
    from scripts.ingest import _greek_lexicon as lex
    from scripts.ingest import ogpg

    # _extract_candidates skips the front matter (stems below 9); the stem only
    # matters for that.
    stem = stem if stem.isdigit() and int(stem) >= 9 else "500"
    return any(lex.score_text(c.text, lexicon).score >= ogpg.LEXICON_THRESHOLD
               for c in ogpg._extract_candidates([(stem, text)]))


def apply_scans(result: VolumeResult, repos_dir: Path, raw_dir: Path,
                lexicon: frozenset[str]) -> bool:
    """Split ``no_text`` by the pages' OCR and count fillable pages.

    Returns False when the volume's clone isn't here (nothing changed).
    """
    from scripts.ingest import _ogpg_columns as cols
    from scripts.ingest import ogpg

    if not result.lost:
        return True
    extract = json.loads((raw_dir / EXTRACT_DIR / f"{result.volume}.json")
                         .read_text(encoding="utf-8"))
    clone = repos_dir / extract["repo"]
    if not (clone / ".git").exists():
        log.warning("%s: no clone at %s; --scans skipped", result.volume, clone)
        return False
    scans = ogpg._scan_files(clone)
    primary = extract["pipeline"].get("primary_scan")
    by_work = {w.work: w for w in result.works}

    def hole_of(work: str, page: int) -> Hole:
        return next(h for h in by_work[work].holes if h.first <= page <= h.last)

    if primary in scans and result.no_text:
        oid_of = dict(scans[primary])
        wanted = sorted({s for _, _, stems in result.no_text for s in stems if s in oid_of})
        text_of = dict(ogpg._read_scan(clone, [(s, oid_of[s]) for s in wanted]))
        for work, page, stems in result.no_text:
            texts = [text_of[s] for s in stems if s in text_of]
            if not texts:
                continue
            kinds = [classify_page(t, lexicon) for t in texts]
            # A Greek and a Latin page with the same columns (PG 47–64): the
            # Greek one decides.
            kind = min(kinds, key=SCAN_CAUSES.index)
            if "latin" in kinds and kind == "blank":
                kind = "latin"
            hole = hole_of(work, page)
            hole.causes[kind] += 1

    lost = defaultdict(list)
    for work, page in result.lost:
        lost[page].append(work)
    found: set[int] = set()
    for name, files in sorted(scans.items()):
        if name == primary:
            continue
        pages = ogpg._read_scan(clone, files)
        heads = [(stem, sorted(cols.head_numbers(text))) for stem, text in pages]
        cmap = cols.map_columns(heads)
        for stem, text in pages:
            span = cmap.columns.get(stem)
            if span is None:
                continue
            page = page_of(span[0])
            if page in lost and page not in found and has_passing_greek(stem, text, lexicon):
                found.add(page)
    for page in found:
        for work in lost[page]:
            hole_of(work, page).fillable += 1
    return True


# ---------------------------------------------------------------------------
# Whole corpus
# ---------------------------------------------------------------------------


def volumes(raw_dir: Path, index: dict) -> list[str]:
    """Every volume with raw data or an index entry, in order."""
    found = {p.name for p in raw_dir.iterdir() if p.is_dir() and not p.name.startswith("_")}
    found |= {p.stem for p in raw_dir.glob("*.json") if not p.name.startswith("_")}
    extracts = raw_dir / EXTRACT_DIR
    if extracts.is_dir():
        found |= {p.stem for p in extracts.glob("*.json")}
    return sorted(found | set(index))


def _measure_one(args: tuple[str, list, Path, Path | None, list]) -> VolumeResult | None:
    return measure_volume(*args)


def measure(raw_dir: Path = RAW_DIR, index: dict | None = None,
            scans: Path | None = None, cache_dir: Path | None = CACHE_DIR,
            workers: int | None = None, latin: LatinRanges | None = None) -> list[WorkCoverage]:
    """Coverage of every OGPG work, by volume and column order.

    ``index`` and ``latin`` default to the repository's ``ogpg_index.csv`` (a
    given ``index`` comes with no Latin-only ranges unless ``latin`` is given).
    ``workers`` > 1 measures volumes in parallel processes (default: one per
    CPU; 1 runs in this process).
    """
    import os

    from scripts.ingest import _ogpg_index as pgi

    if index is None:
        index = pgi.load_index()
        if latin is None:
            latin = load_latin()
    latin = latin or {}
    jobs = [(vol, index.get(vol, []), raw_dir, cache_dir, latin.get(vol, []))
            for vol in volumes(raw_dir, index)]
    workers = workers or min(len(jobs), os.cpu_count() or 1) or 1
    if workers > 1:
        with ProcessPoolExecutor(workers) as pool:
            results = list(pool.map(_measure_one, jobs))
    else:
        results = [_measure_one(job) for job in jobs]
    lexicon = None
    out: list[WorkCoverage] = []
    for result in results:
        if result is None:
            continue
        if scans is not None and result.lost:
            if lexicon is None:
                from scripts.ingest import _greek_lexicon as lex

                lexicon = lex.load_lexicon()
            apply_scans(result, scans, raw_dir, lexicon)
        out.extend(result.works)
    return out


def summary(works: list[WorkCoverage]) -> dict:
    causes: Counter[str] = Counter()
    for w in works:
        causes.update(w.causes)
    return {
        "works": len(works),
        "expected_pages": sum(w.expected for w in works),
        "missing_pages": sum(w.missing for w in works),
        "latin_only": sum(w.latin_only for w in works),
        "under_80": sum(1 for w in works if w.coverage < 0.8),
        "under_50": sum(1 for w in works if w.coverage < 0.5),
        "causes": dict(sorted(causes.items())),
        "fillable": sum(w.fillable for w in works),
        "start_mid": sum(1 for w in works if w.start_mid),
        "end_mid": sum(1 for w in works if w.end_mid or w.end_apparatus),
    }


def summary_line(s: dict) -> str:
    pct = s["missing_pages"] / s["expected_pages"] if s["expected_pages"] else 0.0
    causes = ", ".join(f"{k} {s['causes'][k]:,}" for k in CAUSES if k in s["causes"])
    split = ", ".join(f"{k} {s['causes'][k]:,}" for k in SCAN_CAUSES if k in s["causes"])
    if split:
        causes += f" (no_text by OCR: {split})"
    line = (f"OGPG coverage: {s['works']} works, {s['missing_pages']:,} of "
            f"{s['expected_pages']:,} pages missing ({pct:.1%}); {s['under_80']} works "
            f"under 80%, {s['under_50']} under 50%")
    if causes:
        line += f"; by cause: {causes}"
    if s["fillable"]:
        line += f"; {s['fillable']:,} fillable from other scans"
    if s.get("latin_only"):
        line += f"; {s['latin_only']:,} Latin-only pages not expected"
    return line


def works_tsv(works: list[WorkCoverage]) -> list[str]:
    lines = ["work\texpected\tpresent\tcoverage\tmissing\tlargest_hole\t"
             + "\t".join(CAUSES + SCAN_CAUSES) + "\tfillable\tlatin_only\tboundary"]
    for w in sorted(works, key=lambda w: (-w.missing, w.work)):
        big = w.largest_hole
        flags = [n for n, f in (("start", w.start_mid), ("end", w.end_mid),
                                ("apparatus", w.end_apparatus)) if f]
        c = w.causes
        lines.append("\t".join([
            w.work, str(w.expected), str(w.present), f"{w.coverage:.3f}", str(w.missing),
            f"{big.first}-{big.last}" if big else "",
            *(str(c.get(k, 0)) for k in CAUSES + SCAN_CAUSES),
            str(w.fillable), str(w.latin_only), ",".join(flags)]))
    return lines


def holes_tsv(works: list[WorkCoverage]) -> list[str]:
    lines = ["work\tcols\tpages\t" + "\t".join(CAUSES + SCAN_CAUSES) + "\tfillable"]
    for w in works:
        for h in w.holes:
            lines.append("\t".join([w.work, f"{h.first}-{h.last}", str(h.pages),
                                    *(str(h.causes.get(k, 0)) for k in CAUSES + SCAN_CAUSES),
                                    str(h.fillable)]))
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--scans", nargs="?", const=REPOS_DIR, type=Path, metavar="DIR",
                        help="classify missing pages by their OCR in the clones "
                             f"(default {REPOS_DIR})")
    parser.add_argument("--works", action="store_true", help="print a TSV per work")
    parser.add_argument("--holes", action="store_true", help="print a TSV per hole")
    parser.add_argument("--json", type=Path, metavar="FILE", help="write everything as JSON")
    parser.add_argument("--workers", type=int, help="parallel processes (default: one per CPU)")
    parser.add_argument("--no-cache", action="store_true",
                        help=f"don't read or write the column maps in {CACHE_DIR}")
    args = parser.parse_args()
    setup_logging()
    works = measure(args.raw_dir, scans=args.scans,
                    cache_dir=None if args.no_cache else CACHE_DIR, workers=args.workers)
    s = summary(works)
    if args.works:
        print("\n".join(works_tsv(works)))
    if args.holes:
        print("\n".join(holes_tsv(works)))
    if args.json:
        args.json.write_text(json.dumps({"summary": s, "works": [w.to_json() for w in works]},
                                        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    log.info("%s", summary_line(s))


if __name__ == "__main__":
    main()
