"""
Ingestor for Open Patrologia Graeca (OPG).

Source: GitHub organization OGL-PatrologiaGraecaDev — OCR'd Migne PG volumes 1–161
License: Public domain (19th-century Migne text; OCR by Open Greek and Latin project)
Language: Greek (grc), with interleaved Latin — Latin is filtered out at extraction time
Genre: patristic

Strategy: partial (``--filter=blob:none``) sparse git clone per volume repo
under ``data/raw/_repos/ogpg/``.  Each repo holds 5–9 independent scans of
the volume (``hvd.*_ocr``, ``coo.*_ocr``, …; one ``NNN.txt`` per page).

Pipeline per volume:

1. *Extraction* (``_extract_candidates``): Greek/Latin column separation by
   line-level Greek-character ratio, page-boundary flushes, and the
   length / Greek-ratio / function-word filters.
2. *Dictionary score* (``_greek_lexicon.score_text``): fraction of a
   paragraph's words that are attested Greek word forms (lexicon built from
   our clean Greek corpora).  Paragraphs scoring below ``LEXICON_THRESHOLD``
   are garbled OCR or critical apparatus.
3. *Cross-scan voting* (when ``CROSS_SCAN`` is on and the other scans are
   fetched): the scan with the most dictionary-valid Greek becomes primary;
   each primary paragraph below the threshold is replaced by the
   best-scoring matching paragraph of another scan at the same relative
   position, if one passes the threshold; otherwise it is dropped.

Secondary scans are fetched into the git object store only (the working tree
keeps just the primary scan's preferred directory), ~5–15 MB per repo.

Raw files record the pipeline version; re-running rebuilds a volume only when
the version (threshold, lexicon, voting) changed, and rewrites the file only
when its content changed.  ``--force`` additionally re-clones.

Usage::

    python -m scripts.ingest.ogpg [--force]
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import unicodedata
import zlib
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from tqdm import tqdm

from patristica.models import Work
from patristica.period import work_in_period
from scripts.ingest import _greek_lexicon as lex
from scripts.ingest import _ogpg_volumes as pgv

log = logging.getLogger(__name__)


SOURCE_ID = "patristic/ogpg"
_GITHUB_ORG = "OGL-PatrologiaGraecaDev"
_BASE_URL = f"https://github.com/{_GITHUB_ORG}"
_API_BASE = "https://api.github.com"

# Dictionary filter: minimum fraction of words that must be attested Greek
# forms.  Tuned on hand-inspected samples (see tests / M8 notes): below 0.65
# roughly 4 in 5 paragraphs are garbled OCR or critical apparatus.
LEXICON_THRESHOLD = 0.65

# Fetch every scan of a volume and vote across them.  Off → primary scan only.
CROSS_SCAN = True

_PIPELINE_VERSION = 2

# ---------------------------------------------------------------------------
# Repo name parsing helpers
# ---------------------------------------------------------------------------

def _parse_repo(repo_name: str) -> tuple[list[int], str]:
    """Parse a repo name into (vol_nums, slug).

    Examples::
        "Vol.-1"     → ([1], "vol-001")
        "Vol.-16.1"  → ([16], "vol-016-pt1")
        "Vol.-87-88" → ([87, 88], "vol-087-088")
    """
    # Strip "Vol.-" prefix
    s = repo_name.removeprefix("Vol.-")

    # Sub-volume (16.1, 86.2, etc.)
    sub_match = re.match(r'^(\d+)\.(\d+)$', s)
    if sub_match:
        n = int(sub_match.group(1))
        part = int(sub_match.group(2))
        return [n], f"vol-{n:03d}-pt{part}"

    # Combined volumes (87-88, 12-13, etc.)
    range_match = re.match(r'^(\d+)-(\d+)$', s)
    if range_match:
        a, b = int(range_match.group(1)), int(range_match.group(2))
        return list(range(a, b + 1)), f"vol-{a:03d}-{b:03d}"

    # Single volume
    n = int(s)
    return [n], f"vol-{n:03d}"


# ---------------------------------------------------------------------------
# GitHub helpers
# ---------------------------------------------------------------------------

def _github_headers() -> dict[str, str]:
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        return {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    return {"Accept": "application/vnd.github+json"}


def _list_repos(cache_file: Path, force: bool = False) -> list[str]:
    """Return list of all repo names in the OPG GitHub org (cached)."""
    if cache_file.exists() and not force:
        return json.loads(cache_file.read_text())

    repos: list[str] = []
    page = 1
    headers = _github_headers()
    with httpx.Client(timeout=30) as client:
        while True:
            r = client.get(
                f"{_API_BASE}/orgs/{_GITHUB_ORG}/repos",
                params={"per_page": 100, "page": page},
                headers=headers,
            )
            r.raise_for_status()
            batch = r.json()
            if not isinstance(batch, list) or not batch:
                break
            repos.extend(item["name"] for item in batch)
            page += 1
            if len(batch) < 100:
                break

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(repos))
    log.info("OPG: found %d repos", len(repos))
    return repos


# ---------------------------------------------------------------------------
# Sparse git clone
# ---------------------------------------------------------------------------

# Non-cone sparse-checkout glob patterns tried in preference order.
# git non-cone mode supports fnmatch globs, so "hvd*_ocr/*.txt" matches
# any hvd.XXXXXXXXX_ocr directory without needing an API call first.
_SPARSE_PATTERNS = [
    "hvd*_ocr/*.txt",
    "coo*_ocr/*.txt",
    "mdp*_ocr/*.txt",
    "njp*_ocr/*.txt",
    "nnc*_ocr/*.txt",
    "nyp*_ocr/*.txt",
    "pst*_ocr/*.txt",
    "*_ocr/*.txt",  # catch-all
]


def _sparse_clone_with_pattern(repo_name: str, pattern: str, clone_dir: Path) -> int:
    """Sparse-clone files matching ``pattern`` from the repo. Returns count of .txt files found."""
    clone_url = f"{_BASE_URL}/{repo_name}"

    # Remove any partial clone
    if clone_dir.exists():
        import shutil
        shutil.rmtree(clone_dir)

    try:
        subprocess.run(
            ["git", "clone", "--filter=blob:none", "--no-checkout", clone_url, str(clone_dir)],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as exc:
        log.error("git clone failed for %s: %s", repo_name, exc.stderr[:300])
        return 0

    sparse_cfg = clone_dir / ".git" / "info" / "sparse-checkout"
    sparse_cfg.write_text(pattern + "\n")

    try:
        subprocess.run(
            ["git", "config", "core.sparseCheckout", "true"],
            check=True, capture_output=True, cwd=clone_dir,
        )
        subprocess.run(
            ["git", "checkout", "HEAD"],
            check=True, capture_output=True, cwd=clone_dir,
        )
    except subprocess.CalledProcessError as exc:
        log.error("git checkout failed for %s: %s", repo_name,
                  exc.stderr[:300] if exc.stderr else "")
        return 0

    return len(list(clone_dir.rglob("*.txt")))


def _sparse_clone(repo_name: str, clone_dir: Path) -> bool:
    """Sparse-clone .txt files from one *_ocr directory of the given repo.

    Tries glob patterns in preference order (hvd* first) without needing
    a GitHub API call to discover directory names. Returns True if any
    .txt files were successfully checked out.
    """
    existing_txts = list(clone_dir.rglob("*.txt")) if clone_dir.exists() else []
    if existing_txts:
        log.debug("Sparse clone already present: %s (%d files)", clone_dir, len(existing_txts))
        return True

    clone_dir.parent.mkdir(parents=True, exist_ok=True)

    for pattern in _SPARSE_PATTERNS:
        count = _sparse_clone_with_pattern(repo_name, pattern, clone_dir)
        if count > 0:
            log.debug("Cloned %s via pattern %r: %d .txt files", repo_name, pattern, count)
            return True
        log.debug("Pattern %r found no files in %s, trying next", pattern, repo_name)

    log.warning("No .txt files found via any pattern in %s", repo_name)
    return False


# ---------------------------------------------------------------------------
# Greek text extraction
# ---------------------------------------------------------------------------

_GREEK_RANGES = (
    (0x0370, 0x03FF),   # Greek and Coptic
    (0x1F00, 0x1FFF),   # Greek Extended
)


def _is_greek(c: str) -> bool:
    cp = ord(c)
    return any(lo <= cp <= hi for lo, hi in _GREEK_RANGES)


def _greek_ratio(text: str) -> float:
    non_ws = [c for c in text if not c.isspace()]
    if not non_ws:
        return 0.0
    return sum(1 for c in non_ws if _is_greek(c)) / len(non_ws)


def _meaningful_greek_word_ratio(text: str) -> float:
    """Fraction of space-separated tokens that contain ≥3 Greek characters.

    Distinguishes real Greek prose (high ratio) from garbage OCR where Greek
    letters appear as isolated scattered characters (low ratio).
    """
    tokens = text.split()
    if not tokens:
        return 0.0
    meaningful = sum(
        1 for t in tokens if sum(1 for c in t if _is_greek(c)) >= 3
    )
    return meaningful / len(tokens)


def _clean_line(line: str) -> str:
    """NFC-normalize and strip leading/trailing whitespace."""
    return unicodedata.normalize("NFC", line).strip()


def _fix_hyphenation(text: str) -> str:
    """Join lines ending with a hyphen to the next line."""
    return re.sub(r'(\w)-\n(\w)', r'\1\2', text)


def _strip_diacritics(s: str) -> str:
    """Remove Greek diacritics, preserving base letters; lowercase result."""
    nfd = unicodedata.normalize("NFD", s)
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn").lower()


# Unaccented lowercase forms of common Greek function words (≥3 chars)
_GREEK_FUNCTION_WORDS = frozenset([
    "και", "γαρ", "αλλα", "οτι", "ουν", "μεν", "κατα", "προς",
    "απο", "περι", "αυτου", "αυτοις", "αυτον", "αυτης", "αυτη",
    "εστι", "εστιν", "ωστε", "ωσπερ", "εαν", "ουτε", "ωσαν",
    "παντα", "παντες", "παντων", "τουτο", "τουτοις", "τουτων",
    "ουτος", "αυτη", "εκει", "ωδε", "τοτε", "νυν", "ετι",
    "ουχι", "ουκ", "εκει", "παρα", "υπο", "μετα", "δια",
    "λεγει", "λεγω", "εχει", "εχω", "ειναι", "εστω",
])


def _has_function_words(text: str, min_count: int = 2) -> bool:
    """True if the text contains at least min_count Greek function words."""
    found = 0
    for token in text.split():
        clean = token.strip(".,;:!?'\"«»[]{}()-·—")
        if len(clean) < 3:
            continue
        if _strip_diacritics(clean) in _GREEK_FUNCTION_WORDS:
            found += 1
            if found >= min_count:
                return True
    return False


@dataclass
class Candidate:
    """One extracted paragraph of one scan, with its dictionary score."""

    page: int                    # 0-based index of the page within the scan
    text: str
    score: lex.LexScore = field(default_factory=lambda: lex.LexScore(0, 0, 0))

    @property
    def ok(self) -> bool:
        return self.score.score >= LEXICON_THRESHOLD


def _passes_basic_filters(text: str) -> bool:
    """Length, Greek ratio, meaningful-word ratio and function-word filters."""
    return (len(text) >= 60
            and _greek_ratio(text) >= 0.40
            and _meaningful_greek_word_ratio(text) >= 0.25
            and _has_function_words(text, min_count=2))


def _extract_candidates(pages: list[tuple[str, str]]) -> list[Candidate]:
    """OCR pages ``[(stem, text)]`` (sorted) → Greek paragraph candidates.

    Applies column separation and the basic filters, but not the dictionary
    filter.  Pages with numeric stem < 9 (title pages, front matter) are
    skipped.
    """
    out: list[Candidate] = []
    current: list[str] = []
    page_idx = 0

    def _flush() -> None:
        text = " ".join(current).strip()
        current.clear()
        if _passes_basic_filters(text):
            out.append(Candidate(page_idx, text))

    for page_idx, (stem, raw) in enumerate(pages):
        if current:
            _flush()      # never join paragraphs across a page boundary
        if stem.isdigit() and int(stem) < 9:
            continue
        for line in _fix_hyphenation(raw).splitlines():
            line = _clean_line(line)
            if len(line) < 12:          # blank / short line ends a paragraph
                if current:
                    _flush()
                continue
            if _greek_ratio(line) >= 0.35:
                current.append(line)
            elif current:
                _flush()
    if current:
        _flush()
    return out


# ---------------------------------------------------------------------------
# Reading scans from the git object store
# ---------------------------------------------------------------------------

def _git(clone_dir: Path, *args: str, input_: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=clone_dir, input=input_,
        check=True, capture_output=True,
    ).stdout


def _scan_files(clone_dir: Path) -> dict[str, list[tuple[str, str]]]:
    """``{scan_dir: [(page_stem, blob_oid), …]}`` for every ``*_ocr`` dir with .txt pages."""
    listing = _git(clone_dir, "ls-tree", "-r", "HEAD").decode()
    scans: dict[str, list[tuple[str, str]]] = {}
    for line in listing.splitlines():
        meta, _, path = line.partition("\t")
        top, _, name = path.partition("/")
        if not top.endswith("_ocr") or "/" in name or not name.endswith(".txt"):
            continue
        scans.setdefault(top, []).append((name[:-4], meta.split()[2]))
    for files in scans.values():
        files.sort()
    return scans


def _missing_scans(clone_dir: Path, scans: list[str]) -> list[str]:
    """Scans with at least one .txt blob not yet in the local object store."""
    if not scans:
        return []
    out = _git(clone_dir, "rev-list", "--objects", "--missing=print", "HEAD",
               "--", *[f"{s}/*.txt" for s in scans]).decode()
    missing_oids = {ln[1:] for ln in out.splitlines() if ln.startswith("?")}
    if not missing_oids:
        return []
    files = _scan_files(clone_dir)
    return [s for s in scans if any(oid in missing_oids for _, oid in files.get(s, []))]


def _fetch_scans(clone_dir: Path, scans: list[str]) -> None:
    """Batch-fetch the .txt blobs of ``scans`` without leaving them checked out.

    A sparse ``read-tree`` prefetches all missing blobs in one request; the
    sparse pattern is then restored so the working tree is unchanged.
    """
    missing = _missing_scans(clone_dir, scans)
    if not missing:
        return
    sparse_cfg = clone_dir / ".git" / "info" / "sparse-checkout"
    original = sparse_cfg.read_text() if sparse_cfg.exists() else "*_ocr/*.txt\n"
    try:
        sparse_cfg.write_text(original + "".join(f"{s}/*.txt\n" for s in missing))
        _git(clone_dir, "read-tree", "-mu", "HEAD")
    finally:
        sparse_cfg.write_text(original)
        _git(clone_dir, "read-tree", "-mu", "HEAD")
    log.debug("Fetched %d scans for %s", len(missing), clone_dir.name)


def _read_blobs(clone_dir: Path, oids: list[str]) -> list[str]:
    """Read blobs via ``git cat-file --batch`` (all must be present locally)."""
    data = _git(clone_dir, "cat-file", "--batch", input_=("\n".join(oids) + "\n").encode())
    out: list[str] = []
    pos = 0
    for _ in oids:
        nl = data.index(b"\n", pos)
        header = data[pos:nl].split()
        if len(header) < 3 or header[1] != b"blob":
            raise RuntimeError(f"git cat-file failed in {clone_dir}: {data[pos:nl]!r}")
        size = int(header[2])
        out.append(data[nl + 1: nl + 1 + size].decode("utf-8", errors="replace"))
        pos = nl + 1 + size + 1
    return out


def _read_scan(clone_dir: Path, files: list[tuple[str, str]]) -> list[tuple[str, str]]:
    texts = _read_blobs(clone_dir, [oid for _, oid in files])
    return [(stem, t) for (stem, _), t in zip(files, texts)]


def _scan_rank(scan: str) -> int:
    """Preference order used to break ties (and when voting is off)."""
    for i, prefix in enumerate(("hvd", "coo", "mdp", "njp", "nnc", "nyp", "pst")):
        if scan.startswith(prefix):
            return i
    return 99


# ---------------------------------------------------------------------------
# Cross-scan voting
# ---------------------------------------------------------------------------

# A replacement must sit within this fraction of the volume of the original's
# relative position (scans differ by plates, missing and front-matter pages).
_POSITION_SLACK = 0.04
# …share at least this many known-word trigrams with it…
_MIN_SHARED_TRIGRAMS = 2
# …and be of comparable length.
_LENGTH_RATIO = (0.4, 2.5)


def _known_trigrams(text: str, lexicon: frozenset[str]) -> set[int]:
    """Hashes of trigrams of consecutive attested Greek forms (≥ 8 letters in total)."""
    forms = [f for f in lex.tokens(text) if lex.is_greek_form(f)]
    out: set[int] = set()
    for a, b, c in zip(forms, forms[1:], forms[2:]):
        if a in lexicon and b in lexicon and c in lexicon and len(a) + len(b) + len(c) >= 8:
            out.add(zlib.crc32(f"{a} {b} {c}".encode()))
    return out


@dataclass
class _Scan:
    name: str
    candidates: list[Candidate]
    n_pages: int

    @property
    def known_words(self) -> int:
        return sum(c.score.known for c in self.candidates if c.ok)

    def rel(self, c: Candidate) -> float:
        return c.page / max(1, self.n_pages - 1)


@dataclass
class VoteStats:
    candidates: int = 0       # primary paragraphs passing the basic filters
    kept: int = 0             # primary paragraphs passing the dictionary filter
    replaced: int = 0         # low-scoring primary paragraphs replaced from another scan
    dropped: int = 0          # low-scoring primary paragraphs dropped
    scans: int = 0


def _vote(scans: list[_Scan], lexicon: frozenset[str]) -> tuple[_Scan, list[str], VoteStats]:
    """Pick the primary scan and resolve its low-scoring paragraphs.

    Returns (primary scan, final paragraph texts, stats).
    """
    primary = max(scans, key=lambda s: (s.known_words, -_scan_rank(s.name)))
    others = [s for s in scans if s is not primary]
    stats = VoteStats(candidates=len(primary.candidates), scans=len(scans))

    # Index good paragraphs of the other scans by known-word trigram.
    index: dict[int, list[tuple[int, int]]] = {}
    tri_cache: dict[tuple[int, int], set[int]] = {}
    for si, scan in enumerate(others):
        for ci, cand in enumerate(scan.candidates):
            if not cand.ok:
                continue
            tris = _known_trigrams(cand.text, lexicon)
            tri_cache[(si, ci)] = tris
            for t in tris:
                index.setdefault(t, []).append((si, ci))

    used: set[tuple[int, int]] = set()
    kept_tris = [(_known_trigrams(c.text, lexicon) if c.ok else set()) for c in primary.candidates]
    texts: list[str] = []
    for i, cand in enumerate(primary.candidates):
        if cand.ok:
            stats.kept += 1
            texts.append(cand.text)
            continue
        best = _best_replacement(cand, i, primary, others, index, tri_cache, used,
                                 kept_tris, lexicon)
        if best is None:
            stats.dropped += 1
            continue
        used.add(best)
        stats.replaced += 1
        texts.append(others[best[0]].candidates[best[1]].text)
    return primary, texts, stats


def _best_replacement(
    cand: Candidate,
    i: int,
    primary: _Scan,
    others: list[_Scan],
    index: dict[int, list[tuple[int, int]]],
    tri_cache: dict[tuple[int, int], set[int]],
    used: set[tuple[int, int]],
    kept_tris: list[set[int]],
    lexicon: frozenset[str],
) -> tuple[int, int] | None:
    tris = _known_trigrams(cand.text, lexicon)
    if not tris:
        return None
    hits: dict[tuple[int, int], int] = {}
    for t in tris:
        for key in index.get(t, ()):
            hits[key] = hits.get(key, 0) + 1
    rel = primary.rel(cand)
    # Text already kept nearby must not be duplicated by the replacement.
    neighbours: set[int] = set()
    for j in range(max(0, i - 3), min(len(kept_tris), i + 4)):
        if j != i:
            neighbours |= kept_tris[j]
    best: tuple[int, int] | None = None
    best_key: tuple[int, float] = (0, 0.0)
    for key, shared in hits.items():
        if shared < _MIN_SHARED_TRIGRAMS or key in used:
            continue
        scan = others[key[0]]
        other = scan.candidates[key[1]]
        if abs(scan.rel(other) - rel) > _POSITION_SLACK:
            continue
        ratio = len(other.text) / len(cand.text)
        if not _LENGTH_RATIO[0] <= ratio <= _LENGTH_RATIO[1]:
            continue
        otris = tri_cache[key]
        if otris and len(otris & neighbours) / len(otris) > 0.5:
            continue
        rank = (shared, other.score.score)
        if rank > best_key:
            best, best_key = key, rank
    return best


# ---------------------------------------------------------------------------
# Work factory
# ---------------------------------------------------------------------------

_EDITION = "Patrologiae Cursus Completus, Series Graeca, ed. J.-P. Migne (Paris, 1857–1866)"


def _vol_label(vol_nums: list[int], part: int | None) -> str:
    label = f"PG Vol. {vol_nums[0]}" if len(vol_nums) == 1 \
        else f"PG Vol. {vol_nums[0]}–{vol_nums[-1]}"
    if part is not None:
        label += f", Part {part}"
    return label


def _make_work(repo_name: str, vol_nums: list[int], part: int | None, vol_slug: str,
               scan: str | None = None) -> Work:
    label = _vol_label(vol_nums, part)
    meta = pgv.lookup(vol_nums, part)
    if meta is None:
        title, author = f"Unidentified works in {label}", None
        date_composed, date_range, date_conf = None, None, "uncertain"
    else:
        title = f"Works in {label} ({pgv.short_authors(meta.authors)})"
        author = "; ".join(meta.authors[:3]) + (" et al." if len(meta.authors) > 3 else "")
        date_composed, date_range, date_conf = meta.date_composed, meta.date_range, \
            meta.date_confidence
    edition = f"{_EDITION}, {label.replace('PG Vol.', 'vol.')}"
    if scan:
        edition += f"; OCR of scan {scan} (Open Greek and Latin, {_GITHUB_ORG})"
    return Work(
        work_id=f"ogpg/{vol_slug}",
        source_id=SOURCE_ID,
        author=author,
        title=title,
        date_composed=date_composed,
        date_range=date_range,
        date_confidence=date_conf,
        genre="patristic",
        language="grc",
        tradition="greek",
        license="public_domain",
        provenance_url=f"https://github.com/{_GITHUB_ORG}/{repo_name}",
        edition=edition,
        translation_of=None,
    )


# ---------------------------------------------------------------------------
# Per-volume ingestion
# ---------------------------------------------------------------------------

def _parse_repo_part(repo_name: str) -> int | None:
    m = re.match(r"^Vol\.-\d+\.(\d+)$", repo_name)
    return int(m.group(1)) if m else None


def _pipeline_id() -> dict[str, object]:
    digest = hashlib.sha256(lex.LEXICON_PATH.read_bytes()).hexdigest()[:12]
    return {
        "version": _PIPELINE_VERSION,
        "lexicon_threshold": LEXICON_THRESHOLD,
        "lexicon_min_count": lex.DEFAULT_MIN_COUNT,
        "lexicon_sha256": digest,
        "cross_scan": CROSS_SCAN,
    }


def _ingest_volume(
    repo_name: str,
    repos_dir: Path,
    output_dir: Path,
    force: bool = False,
) -> tuple[Work | None, VoteStats | None]:
    vol_nums, vol_slug = _parse_repo(repo_name)
    part = _parse_repo_part(repo_name)
    out_path = output_dir / f"{vol_slug}.json"
    pipeline = _pipeline_id()

    # Out of scope: volumes whose contents were all composed after the collection
    # period (PG 121+), consistent with the other sources.  Straddling volumes are
    # kept and their chunks flagged out_of_period by date.
    meta = pgv.lookup(vol_nums, part)
    if meta is not None and not work_in_period(meta.date_range):
        if out_path.exists():
            log.info("Removing %s (all contents after the collection period)", out_path)
            out_path.unlink()
        return None, None

    if out_path.exists() and not force:
        saved = json.loads(out_path.read_text(encoding="utf-8"))
        if saved.get("pipeline", {}).get("id") == pipeline:
            return Work(**saved["work"]), None

    clone_dir = repos_dir / repo_name
    has_clone = clone_dir.exists() and (clone_dir / ".git").exists()
    if force or not has_clone or not any(clone_dir.rglob("*.txt")):
        if force and clone_dir.exists():
            shutil.rmtree(clone_dir)
        if not _sparse_clone(repo_name, clone_dir):
            return None, None

    # (clone_dir, scan_dir, files) for every scan of this volume, preferred first
    sources: list[tuple[Path, str, list[tuple[str, str]]]] = []
    for repo in (repo_name, *pgv.EXTRA_SCAN_REPOS.get(repo_name, ())):
        rdir = repos_dir / repo
        if repo != repo_name and not (rdir / ".git").exists():
            if not _sparse_clone(repo, rdir):
                continue
        files = _scan_files(rdir)
        for name in sorted(files, key=lambda s: (_scan_rank(s), s)):
            sources.append((rdir, name, files[name]))
    if not CROSS_SCAN:
        present = [src for src in sources if (src[0] / src[1]).is_dir()]
        sources = present[:1] or sources[:1]
    if not sources:
        log.warning("No OCR scans found for %s", repo_name)
        return None, None
    for rdir in {src[0] for src in sources}:
        _fetch_scans(rdir, [name for d, name, _ in sources if d == rdir])

    lexicon = lex.load_lexicon()
    scans: list[_Scan] = []
    for rdir, name, files in sources:
        pages = _read_scan(rdir, files)
        cands = _extract_candidates(pages)
        for c in cands:
            c.score = lex.score_text(c.text, lexicon)
        label = name if rdir == clone_dir else f"{rdir.name}/{name}"
        scans.append(_Scan(label, cands, len(pages)))

    primary, texts, stats = _vote(scans, lexicon)
    if not texts:
        log.warning("No Greek paragraphs extracted from %s", repo_name)
        if out_path.exists():
            out_path.unlink()
        return None, stats

    work = _make_work(repo_name, vol_nums, part, vol_slug, primary.name)
    payload = {
        "work": work.model_dump(),
        "pipeline": {
            "id": pipeline,
            "primary_scan": primary.name,
            "scans": [s.name for s in scans],
            "stats": stats.__dict__,
        },
        "paragraphs": [
            {"ref": f"ogpg.{vol_slug}.{i:05d}", "text": t} for i, t in enumerate(texts, 1)
        ],
    }
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    if not out_path.exists() or out_path.read_text(encoding="utf-8") != content:
        out_path.write_text(content, encoding="utf-8")
    log.info("OPG %s: %d paragraphs (kept %d, replaced %d, dropped %d; primary %s of %d scans)",
             vol_slug, len(texts), stats.kept, stats.replaced, stats.dropped,
             primary.name, stats.scans)
    return work, stats


# ---------------------------------------------------------------------------
# Main ingest function
# ---------------------------------------------------------------------------

def ingest(output_dir: Path, force: bool = False, only: list[str] | None = None) -> list[Work]:
    """Clone and process all OPG volumes. Returns list of Work records.

    ``output_dir`` is the raw data root (typically ``data/raw``).
    Clones are stored under ``output_dir/_repos/ogpg/{repo_name}/``.
    Output JSON files go to ``output_dir/patristic/ogpg/``.
    ``only`` restricts processing to the named repos (no pruning then).
    """
    ogpg_dir = output_dir / "patristic" / "ogpg"
    ogpg_dir.mkdir(parents=True, exist_ok=True)

    repos_dir = output_dir / "_repos" / "ogpg"
    repos_dir.mkdir(parents=True, exist_ok=True)

    cache_file = ogpg_dir / "_volumes.json"
    repo_names = _list_repos(cache_file, force=force)

    if not repo_names:
        log.error("No OPG repos found — check GitHub API access")
        return []

    selected = [r for r in repo_names if r not in pgv.EXCLUDED_REPOS]
    if only is not None:
        selected = [r for r in selected if r in only]

    works: list[Work] = []
    for repo_name in tqdm(selected, desc="ogpg volumes"):
        try:
            w, _ = _ingest_volume(repo_name, repos_dir, ogpg_dir, force=force)
            if w:
                works.append(w)
        except (subprocess.CalledProcessError, RuntimeError, OSError) as exc:
            log.error("Error processing %s: %s", repo_name, exc)

    if only is None:
        produced = {f"{_parse_repo(r)[1]}.json" for r in selected}
        for path in ogpg_dir.glob("vol-*.json"):
            if path.name not in produced:
                log.info("Removing raw output of excluded repo: %s", path.name)
                path.unlink()

    log.info("OPG ingestion complete: %d works from %d repos (%d repos excluded)",
             len(works), len(selected), len(pgv.EXCLUDED_REPOS))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
