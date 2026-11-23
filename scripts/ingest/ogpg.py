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

Each volume's extraction is cached in ``_extract/{vol}.json`` with the
pipeline version; re-running rebuilds a volume only when the version
(threshold, lexicon, voting) changed.  ``--force`` additionally re-clones.

Splitting (#67): the cached extraction is cut into works by
``data/ogpg_index.csv`` (``_ogpg_index``), with each page mapped to its Migne
columns (``_ogpg_columns``).  Refs are positional, ``ogpg.{vol}.c{column}.{n}``.
An unsplit volume is written as ``{vol}.json`` (work ``ogpg/{vol}``), a split
one as ``{vol}/{slug}.json`` plus ``{vol}/other.json`` for uncovered text.
Edits to the CSV take effect on a plain run (no re-extraction); work files
are rewritten only when their content changes, and stale ones are pruned.

Usage::

    python -m scripts.ingest.ogpg [--force]
"""

from __future__ import annotations

import fnmatch
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
from scripts.ingest import _ogpg_columns as cols
from scripts.ingest import _ogpg_index as pgi
from scripts.ingest import _ogpg_notes as notes
from scripts.ingest import _ogpg_repeats as rep
from scripts.ingest import _ogpg_volumes as pgv
from scripts.ingest._common import offline, require_network

log = logging.getLogger(__name__)


SOURCE_ID = "ogpg"
_GITHUB_ORG = "OGL-PatrologiaGraecaDev"
_BASE_URL = f"https://github.com/{_GITHUB_ORG}"
_API_BASE = "https://api.github.com"

# Dictionary filter: minimum fraction of words that must be attested Greek
# forms.  Tuned on hand-inspected samples (see tests / M8 notes): below 0.65
# roughly 4 in 5 paragraphs are garbled OCR or critical apparatus.
LEXICON_THRESHOLD = 0.65

# Fetch every scan of a volume and vote across them.  Off → primary scan only.
CROSS_SCAN = True

_PIPELINE_VERSION = 7

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
    if cache_file.exists() and (not force or offline()):
        return json.loads(cache_file.read_text())
    require_network("listing the OpenGreekAndLatin repositories")

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
    """Sparse-clone files matching ``pattern`` from the repo. Returns the count of
    .txt files found, or -1 if git failed."""
    clone_url = f"{_BASE_URL}/{repo_name}"
    require_network(f"cloning {clone_url}")

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
        return -1

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
        return -1

    return len(list(clone_dir.rglob("*.txt")))


def _tree_has_ocr(clone_dir: Path) -> bool:
    """Whether a local clone's tree has any path matching ``_SPARSE_PATTERNS``.

    True when that can't be told (git fails), so the caller doesn't treat an
    unreadable clone as empty.
    """
    tree = subprocess.run(["git", "ls-tree", "-r", "--name-only", "HEAD"], cwd=clone_dir,
                          capture_output=True, text=True)
    if tree.returncode != 0:
        return True
    return any(fnmatch.fnmatch(path, pattern)
               for path in tree.stdout.splitlines() for pattern in _SPARSE_PATTERNS)


def _sparse_clone(repo_name: str, clone_dir: Path) -> bool | None:
    """Sparse-clone .txt files from one *_ocr directory of the given repo.

    Tries glob patterns in preference order (hvd* first) without needing
    a GitHub API call to discover directory names. Returns True if any
    .txt files were successfully checked out, False if every pattern was
    tried and the repo has none, None if git failed.
    """
    existing_txts = list(clone_dir.rglob("*.txt")) if clone_dir.exists() else []
    if existing_txts:
        log.debug("Sparse clone already present: %s (%d files)", clone_dir, len(existing_txts))
        return True
    if offline() and (clone_dir / ".git").exists() and not _tree_has_ocr(clone_dir):
        # The clone (--filter=blob:none) has the whole tree: nothing to check out.
        log.warning("No .txt files found via any pattern in %s (its local tree)", repo_name)
        return False

    clone_dir.parent.mkdir(parents=True, exist_ok=True)

    failed = False
    for pattern in _SPARSE_PATTERNS:
        count = _sparse_clone_with_pattern(repo_name, pattern, clone_dir)
        if count > 0:
            log.debug("Cloned %s via pattern %r: %d .txt files", repo_name, pattern, count)
            return True
        failed = failed or count < 0
        log.debug("Pattern %r found no files in %s, trying next", pattern, repo_name)

    if failed:
        return None
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
    stem: str = ""               # the page's file stem (``NNN`` of ``NNN.txt``)
    title: str | None = None     # Greek capitals heading seen on the page just before

    @property
    def ok(self) -> bool:
        return self.score.score >= LEXICON_THRESHOLD


def _passes_basic_filters(text: str) -> bool:
    """Length, Greek ratio, meaningful-word ratio and function-word filters."""
    return (len(text) >= 60
            and _greek_ratio(text) >= 0.40
            and _meaningful_greek_word_ratio(text) >= 0.25
            and _has_function_words(text, min_count=2))


def _is_title_line(line: str) -> bool:
    """A heading in Greek capitals (``ΠΕΡΙ ΠΑΡΘΕΝΙΑΣ.``, ``ΛΟΓΟΣ Β'.``)."""
    letters = [c for c in line if c.isalpha()]
    greek = [c for c in letters if _is_greek(c)]
    if len(greek) < 4 or len(greek) < 0.6 * len(letters):
        return False
    return sum(1 for c in greek if c.islower()) <= 0.1 * len(greek)


def _is_body_line(line: str) -> bool:
    """Running Greek text: most of its Greek letters are small (not a heading in
    capitals, nor one whose capitals the OCR read partly as small letters or
    mixed with Latin, ``nam ΔΓΑΙΙΗΣ ιω εΓκΡΑτειΑΣ, im nu``)."""
    greek = [c for c in line if c.isalpha() and _is_greek(c)]
    return len(greek) >= 4 and sum(1 for c in greek if c.islower()) > 0.5 * len(greek)


def _extract_candidates(pages: list[tuple[str, str]]) -> list[Candidate]:
    """OCR pages ``[(stem, text)]`` (sorted) → Greek paragraph candidates.

    Applies column separation and the basic filters, but not the dictionary
    filter.  Pages with numeric stem < 9 (title pages, front matter) are
    skipped.  Each candidate records its page stem, and the Greek capitals
    heading lines seen on its page since the previous candidate (``title``);
    work boundaries inside a page are placed at such headings.  Heading
    detection does not change how paragraphs are built.
    """
    out: list[Candidate] = []
    current: list[str] = []
    headings: list[str] = []
    where = (0, "")                 # (page index, stem) of the current paragraph
    last_body = False               # whether the last line in ``current`` is running text
    carry: list[str] = []           # heading lines too short for a paragraph of their own

    def _flush() -> None:
        text = " ".join(current).strip()
        lines = list(current)
        current.clear()
        if _passes_basic_filters(text):
            out.append(Candidate(where[0], text, stem=where[1],
                                 title=" ".join(headings) if headings else None))
            headings.clear()
        elif lines and all(_is_title_line(ln) for ln in lines):
            carry.extend(lines)     # a title: it opens the next paragraph on the page

    for page_idx, (stem, raw) in enumerate(pages):
        if current:
            _flush()      # never join paragraphs across a page boundary
        headings.clear()
        carry.clear()
        if stem.isdigit() and int(stem) < 9:
            continue
        for line in _fix_hyphenation(raw).splitlines():
            line = _clean_line(line)
            title = _is_title_line(line)
            if title:
                # The heading belongs to the next paragraph: a heading after
                # running text starts one (#577: a long title line was run
                # into the end of the work before it); a heading of several
                # lines stays together, even with a line the OCR garbled.
                if current and (len(line) < 12 or last_body):
                    _flush()
                headings.append(line)
            if len(line) < 12:          # blank / short line ends a paragraph
                if current:
                    _flush()
                continue
            if _greek_ratio(line) >= 0.35:
                if not current:
                    where = (page_idx, stem)
                    current.extend(carry)
                    carry.clear()
                current.append(line)
                last_body = _is_body_line(line)
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
        # Numeric order: some scans have more than 999 pages ("1000.txt"), which
        # sort between "100.txt" and "101.txt" as strings.
        files.sort(key=_page_order)
    return scans


def _page_order(item: tuple[str, str]) -> tuple[int, str]:
    stem = item[0]
    return (int(stem) if stem.isdigit() else 10**9, stem)


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
# Text the primary already has (kept paragraphs within this many candidates)
# is not taken as a replacement: a garbled paragraph's position slack can reach
# a page whose text the primary has a few pages on, which then reads twice and
# its real copy is dropped as a repeat (#578: PG 18 col. 531 took the opening
# of Alexander's letter, cols. 547ff.).
_DUP_WINDOW = 15


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
    heads: list[tuple[str, list[int]]] = field(default_factory=list)

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
    misbound_pages: int = 0   # primary pages from another volume, dropped (#90)
    filled: int = 0           # paragraphs of other scans for columns the primary lacks (#90)
    truncated_pages: int = 0  # primary pages replaced by another scan's fuller copy


def _vote(scans: list[_Scan], lexicon: frozenset[str]
          ) -> tuple[_Scan, list[tuple[int, str]], VoteStats]:
    """Pick the primary scan and resolve its low-scoring paragraphs.

    Returns (primary scan, final paragraphs, stats).  Each final paragraph is
    ``(index of the primary candidate it stands for, text)``: a replacement
    from another scan keeps the position (page) of the paragraph it replaces.
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
    texts: list[tuple[int, str]] = []
    for i, cand in enumerate(primary.candidates):
        if cand.ok:
            stats.kept += 1
            texts.append((i, cand.text))
            continue
        best = _best_replacement(cand, i, primary, others, index, tri_cache, used,
                                 kept_tris, lexicon)
        if best is None:
            stats.dropped += 1
            continue
        used.add(best)
        stats.replaced += 1
        texts.append((i, others[best[0]].candidates[best[1]].text))
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
    for j in range(max(0, i - _DUP_WINDOW), min(len(kept_tris), i + _DUP_WINDOW + 1)):
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
# Cross-scan fill (#90)
# ---------------------------------------------------------------------------

# Columns either side of a page within which the same text is looked for in
# another scan (column mappings of two scans differ by a page or two).
_NEAR_COLS = 6
# A primary page is misbound (a leaf of another volume) when most other scans
# don't have its text near its columns (shared trigrams below
# ``_MISBOUND_SHARE``; unrelated pages share ~0.02, the same page in another
# scan 0.4–0.9) and their text for those columns is nowhere in the primary
# within ``_MISBOUND_FAR_COLS`` columns (so it isn't just a column offset);
# only runs of at least ``_MISBOUND_MIN_PAGES`` such pages count.
_MISBOUND_SHARE = 0.1
_MISBOUND_FAR_COLS = 60
_MISBOUND_MIN_PAGES = 4
# A page of another scan already present in the primary nearby (this share of
# its trigrams) is not filled in.
_FILL_DUP_SHARE = 0.3
# A filled page must be within this many pages of one whose columns are
# confirmed: by its head numbers, or by its text matching the primary's at the
# same columns (``_FILL_DUP_SHARE``; a scan whose heads OCR'd badly maps its
# pages as well as the primary does, PG 44 col. 1325).
_FILL_SUPPORT_PAGES = 2
# A primary page whose OCR lost part of its Greek (the column breaks off into
# the Latin, PG 44 col. 1323) is replaced by another scan's page on the same
# columns that holds the primary's text (``_TRUNCATED_CONTAINED`` of its
# trigrams) and is much longer (both length conditions).
_TRUNCATED_CONTAINED = 0.6
_TRUNCATED_RATIO = 1.5
_TRUNCATED_MIN_CHARS = 800


def _word_trigrams(text: str) -> set[str]:
    return rep._trigrams(rep._fold(text))


@dataclass
class _Layout:
    """A scan's Greek paragraphs placed on Migne columns."""

    name: str
    paras: list[dict]                       # {"stem", "title", "text"}
    pages: dict[str, tuple[int, int]]       # page stem with text → its columns
    grams: dict[str, set[str]]              # page stem → word trigrams of its text
    supported: set[int]                     # page numbers whose heads confirm the map

    def best_page(self, grams: set[str]) -> float:
        """The largest share of ``grams`` found on any one page of the scan."""
        return max((_share(grams, g) for g in self.grams.values()), default=0.0)

    def near(self, a: int, b: int) -> set[str]:
        """Trigrams of the pages whose columns fall within [a, b]."""
        out: set[str] = set()
        for stem, (c, _) in self.pages.items():
            if a <= c <= b:
                out |= self.grams[stem]
        return out


def _layout(name: str, paras: list[dict], heads: list[tuple[str, list[int]]]) -> _Layout:
    repeats = _page_repeats(paras, heads)
    cmap = cols.map_columns(heads, skip=set(repeats.pages) | set(repeats.moved))
    pages: dict[str, tuple[int, int]] = {}
    grams: dict[str, set[str]] = {}
    for p in paras:
        if p["stem"] in repeats.pages:
            continue
        span = cmap.columns.get(repeats.moved.get(p["stem"], p["stem"]))
        if span is None:
            continue
        pages[p["stem"]] = span
        grams.setdefault(p["stem"], set()).update(_word_trigrams(p["text"]))
    supported = {int(stem) for stem, nums in heads if stem.isdigit()
                 and (span := cmap.columns.get(stem))
                 and any(span[0] - 1 <= n <= span[1] + 1 for n in nums)}
    return _Layout(name, [p for p in paras if p["stem"] not in repeats.pages],
                   pages, grams, supported)


def _share(grams: set[str], other: set[str]) -> float:
    return len(grams & other) / len(grams) if grams else 0.0


def _misbound_pages(primary: _Layout, others: list[_Layout]) -> set[str]:
    """Primary pages that are leaves of another volume (see ``_MISBOUND_SHARE``).

    Another scan may share the misbinding (two copies bound alike), so a page
    is misbound when at least half of the other scans with text near its
    columns don't have its text anywhere, and their text for its columns is
    not in the primary nearby.
    """
    flagged: list[str] = []
    for stem, (a, b) in sorted(primary.pages.items(), key=lambda kv: kv[1]):
        theirs = [o for o in others if o.near(a - _NEAR_COLS, b + _NEAR_COLS)]
        if not theirs:
            continue
        # A misbound leaf is from another volume: the scans that lack it lack
        # it everywhere, not just at these columns (a page the primary maps to
        # the wrong columns is elsewhere in the other scans).
        lacking = [o for o in theirs
                   if _share(primary.grams[stem], o.near(a - _NEAR_COLS, b + _NEAR_COLS))
                   < _MISBOUND_SHARE]
        if 2 * len(lacking) < len(theirs):
            continue
        lacking = [o for o in lacking if o.best_page(primary.grams[stem]) < _MISBOUND_SHARE]
        if 2 * len(lacking) < len(theirs):
            continue
        ours = primary.near(a - _MISBOUND_FAR_COLS, b + _MISBOUND_FAR_COLS)
        same_cols = [g for o in lacking if (g := o.near(a, a))]
        if same_cols and all(_share(g, ours) < _MISBOUND_SHARE for g in same_cols):
            flagged.append(stem)
    # Keep runs of consecutive pages only.
    nums = sorted(int(s) for s in flagged)
    keep: set[int] = set()
    run: list[int] = []
    for n in nums + [None]:          # type: ignore[list-item]
        if run and (n is None or n != run[-1] + 1):
            if len(run) >= _MISBOUND_MIN_PAGES:
                keep.update(run)
            run = []
        if n is not None:
            run.append(n)
    return {s for s in flagged if int(s) in keep}


def _by_span(layout: _Layout) -> dict[tuple[int, int], list[str]]:
    """Page stems of a layout per column span (a span may have several pages)."""
    out: dict[tuple[int, int], list[str]] = {}
    for stem, span in layout.pages.items():
        out.setdefault(span, []).append(stem)
    return out


def _span_text(layout: _Layout, stems: list[str]) -> tuple[int, set[str]]:
    """Length and trigrams of the text a layout has on ``stems``."""
    length = sum(len(p["text"]) for p in layout.paras if p["stem"] in stems)
    grams: set[str] = set()
    for stem in stems:
        grams |= layout.grams[stem]
    return length, grams


def _truncated(ours: _Layout, theirs: list[_Layout], misbound: set[str]
               ) -> dict[tuple[int, int], tuple[list[str], _Layout, list[str]]]:
    """Primary spans whose Greek another scan has much more of (``_TRUNCATED_*``)
    → ``{span: (primary stems, other layout, its stems)}``, the longest such page."""
    out: dict[tuple[int, int], tuple[list[str], _Layout, list[str]]] = {}
    spans = [(other, _by_span(other)) for other in theirs]
    for span, stems in _by_span(ours).items():
        if any(stem in misbound for stem in stems):
            continue
        length, grams = _span_text(ours, stems)
        if not grams:
            continue
        best = 0
        for other, by_span in spans:
            ostems = by_span.get(span)
            if not ostems:
                continue
            olen, ograms = _span_text(other, ostems)
            if (olen >= max(_TRUNCATED_RATIO * length, length + _TRUNCATED_MIN_CHARS)
                    and olen > best and _share(grams, ograms) >= _TRUNCATED_CONTAINED):
                out[span] = (stems, other, ostems)
                best = olen
    return out


def _cross_scan(primary: _Scan, kept: list[dict], others: list[_Scan]
                ) -> tuple[set[str], list[dict], set[str]]:
    """Misbound primary pages, paragraphs of other scans for columns the
    primary lacks (#90), and truncated primary pages
    → ``(misbound page stems, fills, replaced page stems)``.

    The primary is the scan with the most dictionary-valid Greek, but it may
    stop early, lose part of a page or carry another volume's leaves while
    another scan has the text.  Each fill is
    ``{"cols", "scan", "stem", "title", "text"}``: a page of another scan
    whose columns no kept primary page covers, whose text the primary doesn't
    already have nearby, and whose scan's column mapping is confirmed within
    ``_FILL_SUPPORT_PAGES`` pages (by head numbers, or by text matching the
    primary's); or a page that holds the text of a truncated primary page
    (``_TRUNCATED_*``) on the same columns, which then stands for it: the
    replaced primary pages' paragraphs are to be dropped.  Scans are tried in
    order of dictionary-valid Greek.
    """
    ours = _layout(primary.name, kept, primary.heads)
    theirs = [_layout(s.name, [{"stem": c.stem, "title": c.title, "text": c.text}
                               for c in s.candidates if c.ok], s.heads)
              for s in sorted(others, key=lambda s: (-s.known_words, _scan_rank(s.name)))]
    misbound = _misbound_pages(ours, theirs)
    wrong: set[str] = set()                 # text of the misbound leaves
    for stem in misbound:
        wrong |= ours.grams[stem]
    covered: set[int] = set()
    for stem, (a, b) in ours.pages.items():
        if stem not in misbound:
            covered |= {a, b}
    fills: list[dict] = []
    replaced: set[str] = set()
    for span, (stems, other, ostems) in sorted(_truncated(ours, theirs, misbound).items()):
        replaced.update(stems)
        for p in other.paras:
            if p["stem"] in ostems:
                fills.append({"cols": list(span), "scan": other.name, "stem": p["stem"],
                              "title": p["title"], "text": p["text"]})
    for other in theirs:
        # Pages whose text the primary has on the same columns confirm the map.
        confirmed = set(other.supported) | {
            int(stem) for stem, (a, b) in other.pages.items()
            if stem.isdigit() and _share(other.grams[stem], ours.near(a, b)) >= _FILL_DUP_SHARE}
        taken: set[int] = set()
        by_page: dict[str, list[dict]] = {}
        for p in other.paras:
            if p["stem"] in other.pages:
                by_page.setdefault(p["stem"], []).append(p)
        for stem, paras in by_page.items():
            a, b = other.pages[stem]
            if a in covered or b in covered:
                continue
            if not any(abs(int(stem) - n) <= _FILL_SUPPORT_PAGES for n in confirmed):
                continue
            nearby = ours.near(a - _NEAR_COLS, b + _NEAR_COLS)
            for f in fills:
                if a - _NEAR_COLS <= f["cols"][0] <= b + _NEAR_COLS:
                    nearby |= _word_trigrams(f["text"])
            if (_share(other.grams[stem], nearby) >= _FILL_DUP_SHARE
                    or _share(other.grams[stem], wrong) >= _MISBOUND_SHARE):
                continue
            for p in paras:
                fills.append({"cols": [a, b], "scan": other.name, "stem": p["stem"],
                              "title": p["title"], "text": p["text"]})
            taken |= {a, b}
        covered |= taken
    fills.sort(key=lambda f: (f["cols"][0], f["scan"],
                              int(f["stem"]) if f["stem"].isdigit() else 0))
    return misbound, fills, replaced


# ---------------------------------------------------------------------------
# New OCR of the holes (#719, #705)
# ---------------------------------------------------------------------------

# Text for pages the OGL OCR lacks: one JSON-lines file per volume,
# ``{"cols", "lines", "source", …}`` per page (scripts.ogpg_calfa, later the
# OCR pipeline), and ``_sources.json``: each source's credit for the edition.
OCR_DIR = Path(__file__).resolve().parents[2] / "data" / "ocr" / "ogpg"


def ocr_pages(vol_slug: str, ocr_dir: Path = OCR_DIR) -> list[dict]:
    """A volume's pages of new OCR, as fills (``{"cols", "scan", "stem", "title",
    "text", "ocr_source"}``): each page one paragraph, its line-end hyphens joined.
    A page's ``notes`` (Migne's footnotes) follow its text, marked as an
    editorial ``note`` span (#236), so readers see them and search doesn't."""
    path = ocr_dir / f"{vol_slug}.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        text = " ".join(_fix_hyphenation("\n".join(r["lines"])).split())
        if not text:
            continue
        page = {"cols": tuple(r["cols"]), "scan": r["source"], "stem": None,
                "title": None, "text": text, "ocr_source": r["source"]}
        note = " ".join(" ".join(r.get("notes") or []).split())
        if note:
            page["text"] = f"{text} {note}"
            page["editorial"] = [[len(text) + 1, len(page["text"]), "note"]]
        out.append(page)
    return out


def ocr_credits(ocr_dir: Path = OCR_DIR) -> dict[str, str]:
    """Each OCR source's credit, for the ``edition`` of the works it adds to."""
    path = ocr_dir / "_sources.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _first_page(col: int) -> int:
    return col if col % 2 else col - 1


def _credited(work: Work, paras: list[dict], credits: dict[str, str] | None) -> Work:
    """``work`` with the credit of every OCR source among its paragraphs in its edition."""
    sources = sorted({p["ocr_source"] for p in paras if p.get("ocr_source")})
    if not sources:
        return work
    notes = [(credits or {}).get(s, f"pages from {s}") for s in sources]
    return work.model_copy(update={"edition": "; ".join([work.edition, *notes])})


def _merge_fills(paras: list[dict], fills: list[dict]) -> list[dict]:
    """Primary paragraphs (with ``cols``) and fills, in column order: each
    fill goes before the first primary paragraph of a later column."""
    if not fills:
        return paras
    out: list[dict] = []
    pending = sorted(fills, key=lambda f: f["cols"][0])
    i = 0
    for p in paras:
        if p.get("cols"):
            while i < len(pending) and pending[i]["cols"][0] < p["cols"][0]:
                out.append(pending[i])
                i += 1
        out.append(p)
    out.extend(pending[i:])
    return out


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


def _scan_note(scan: str | None) -> str:
    return f"; OCR of scan {scan} (Open Greek and Latin, {_GITHUB_ORG})" if scan else ""


def _make_work(repo_name: str, vol_nums: list[int], part: int | None, vol_slug: str,
               scan: str | None = None, remainder: bool = False) -> Work:
    """Volume-level work: a whole unsplit volume, or (``remainder``) the text of a
    split volume that no index row covers."""
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
    work_id = f"ogpg/{vol_slug}"
    if remainder:
        title = f"Other text in {label} (front matter, notes, unindexed pieces)"
        author = None
        work_id += f"/{pgi.REMAINDER_SLUG}"
    edition = f"{_EDITION}, {label.replace('PG Vol.', 'vol.')}" + _scan_note(scan)
    return Work(
        work_id=work_id,
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


def _cols_label(parts: list[pgi.IndexRow], last_col: int | None) -> str:
    spans = []
    for r in parts:
        end = r.col_end if r.col_end is not None else last_col
        spans.append(f"{r.col_start}–{end}" if end and end != r.col_start else f"{r.col_start}")
    if len(spans) > 3:
        return f"cols. {spans[0].split('–')[0]}–{spans[-1].split('–')[-1]} (in {len(spans)} parts)"
    return ("cols. " if len(spans) > 1 or "–" in spans[0] else "col. ") + ", ".join(spans)


def index_external_ids(row: pgi.IndexRow) -> list[str]:
    """Catalogue ids of an index row, as ``Work.external_ids`` (#192, BHG #375)."""
    return (([f"CPG:{row.cpg}"] if row.cpg else []) + ([f"TLG:{row.tlg}"] if row.tlg else [])
            + ([f"BHG:{row.bhg}"] if row.bhg else []))


def _make_index_work(repo_name: str, vol_nums: list[int], part: int | None,
                     parts: list[pgi.IndexRow], last_col: int | None,
                     scan: str | None) -> Work:
    """Work for a slug of ``ogpg_index.csv`` (one or more column ranges); missing
    dates come from the volume."""
    row = parts[0]
    meta = pgv.lookup(vol_nums, part)
    date_composed, date_range, conf = row.date_composed, row.date_range, row.date_confidence
    if date_range is None and meta is not None:
        date_range = meta.date_range
        if date_composed is None:
            date_composed = meta.date_composed
    if conf is None:
        conf = meta.date_confidence if meta is not None else "uncertain"
    label = _vol_label(vol_nums, part).replace("PG Vol.", "vol.")
    edition = f"{_EDITION}, {label}, {_cols_label(parts, last_col)}"
    edition += _scan_note(scan)
    if row.duplicate_of:
        edition += f"; a cleaner edition of this text is {row.duplicate_of}"
    return Work(
        work_id=f"ogpg/{row.volume}/{row.slug}",
        source_id=SOURCE_ID,
        author=row.author,
        title=row.title,
        date_composed=date_composed,
        date_range=date_range,
        date_confidence=conf,
        genre="patristic",
        language="grc",
        tradition="greek",
        license="public_domain",
        provenance_url=f"https://github.com/{_GITHUB_ORG}/{repo_name}",
        edition=edition,
        translation_of=None,
        external_ids=index_external_ids(row),
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


def _extract_volume(
    repo_name: str,
    repos_dir: Path,
    extract_dir: Path,
    force: bool = False,
) -> dict | None:
    """Extract one volume's Greek paragraphs (cached in ``extract_dir``).

    Returns ``{"repo", "pipeline", "page_heads", "paragraphs"}``.  Each
    paragraph is ``{"stem", "title", "text"}``: its page in the primary scan,
    the heading seen just before it on that page, and the text.
    ``page_heads`` lists the column numbers found on every page of the
    primary scan; ``split_volume`` maps pages to columns from them.  The
    cache is reused while the pipeline id is unchanged; ``force`` re-clones.
    """
    vol_nums, vol_slug = _parse_repo(repo_name)
    out_path = extract_dir / f"{vol_slug}.json"
    pipeline = _pipeline_id()

    clone_dir = repos_dir / repo_name
    has_clone = clone_dir.exists() and (clone_dir / ".git").exists()
    # Offline without a clone, --force reuses the extraction made with this same
    # pipeline: it is what re-extracting would produce (#215).
    saved = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else None
    current = saved is not None and saved.get("pipeline", {}).get("id") == pipeline
    if current and saved.get("empty") and (not force or offline()):
        log.debug("%s has no OCR text (recorded): skipping", repo_name)
        return None
    if current and (not force or (offline() and not has_clone)):
        return saved
    # Offline, --force re-extracts from the existing clone instead of re-cloning.
    refetch = (force and not offline()) or not has_clone or not any(clone_dir.rglob("*.txt"))
    if refetch:
        if force and clone_dir.exists() and not offline():
            shutil.rmtree(clone_dir)
        cloned = _sparse_clone(repo_name, clone_dir)
        if cloned is False:
            # Record it, so later runs (and offline ones) don't clone it again.
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps({"repo": repo_name, "pipeline": {"id": pipeline},
                                            "empty": True}) + "\n", encoding="utf-8")
        if not cloned:
            return None

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
        return None
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
        heads = [(stem, sorted(cols.head_numbers(text))) for stem, text in pages]
        scans.append(_Scan(label, cands, len(pages), heads))

    primary, kept, stats = _vote(scans, lexicon)
    if not kept:
        log.warning("No Greek paragraphs extracted from %s", repo_name)
        if out_path.exists():
            out_path.unlink()
        return None

    paragraphs = [
        {"stem": primary.candidates[i].stem, "title": primary.candidates[i].title, "text": text}
        for i, text in kept
    ]
    misbound, fills, replaced = _cross_scan(primary, paragraphs,
                                            [s for s in scans if s is not primary])
    if misbound:
        log.info("OPG %s: %d primary pages are misbound (another volume's leaves): dropped",
                 vol_slug, len(misbound))
    if replaced:
        log.debug("OPG %s: %d truncated primary pages replaced from another scan",
                  vol_slug, len(replaced))
    paragraphs = [p for p in paragraphs if p["stem"] not in misbound | replaced]
    stats.misbound_pages = len(misbound)
    stats.truncated_pages = len(replaced)
    stats.filled = len(fills)
    payload = {
        "repo": repo_name,
        "pipeline": {
            "id": pipeline,
            "primary_scan": primary.name,
            "scans": [s.name for s in scans],
            "stats": stats.__dict__,
        },
        # Column numbers in head position on every page of the primary scan,
        # for the page → column mapping (``_ogpg_columns``).
        "page_heads": primary.heads,
        "paragraphs": paragraphs,
        # Paragraphs of other scans for columns the primary lacks (#90).
        "fills": fills,
    }
    _write_if_changed(out_path, payload)
    log.info("OPG %s: %d paragraphs (kept %d, replaced %d, dropped %d; primary %s of %d scans)",
             vol_slug, len(kept), stats.kept, stats.replaced, stats.dropped, primary.name,
             stats.scans)
    return payload


def _write_if_changed(path: Path, payload: dict) -> None:
    content = json.dumps(payload, ensure_ascii=False, indent=2)
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


def _fits(span: tuple[int, int], numbers: list[int]) -> bool:
    return any(span[0] - 1 <= n <= span[1] + 1 for n in numbers)


def keep_placed_copies(repeats: rep.Repeats, heads: list[tuple[str, list[int]]]
                       ) -> rep.Repeats:
    """``repeats`` with a misplaced first copy dropped instead of the second.

    ``find_repeats`` keeps the first copy of a leaf scanned twice.  When that
    copy is bound out of place (PG 99: a leaf printing cols. 485–486 among
    461–484, #578), its head numbers don't fit the columns the map gives it,
    and the second copy, in its right place, is the one to keep.
    """
    head_of = dict(heads)
    pages = dict(repeats.pages)
    cmap: cols.ColumnMap | None = None
    for second, first in sorted(repeats.pages.items()):
        numbers = head_of.get(first, [])
        if not numbers or first in pages:
            continue
        if cmap is None:
            cmap = cols.map_columns(heads, skip=set(pages) | set(repeats.moved))
        span = cmap.columns.get(first)
        if span is None or _fits(span, numbers):
            continue
        swapped = (set(pages) - {second}) | {first}
        alt = cols.map_columns(heads, skip=swapped | set(repeats.moved)).columns.get(second)
        if alt is not None and _fits(alt, numbers + head_of.get(second, [])):
            del pages[second]
            pages[first] = second
            cmap = None
    return rep.Repeats(dict(sorted(pages.items(), key=lambda kv: _page_order((kv[0], "")))),
                       repeats.moved)


def _page_repeats(paras: list[dict], heads: list[tuple[str, list[int]]]) -> rep.Repeats:
    """Repeated pages of a scan: by text, with misplaced first copies swapped."""
    return keep_placed_copies(rep.find_repeats(paras, [stem for stem, _ in heads]), heads)


def volume_repeats(extract: dict) -> rep.Repeats:
    """Pages the volume's primary scan repeats (``_ogpg_repeats``, #96, #578)."""
    return _page_repeats(extract["paragraphs"],
                         [(stem, nums) for stem, nums in extract["page_heads"]])


def _in_place(paragraphs: list[dict], moved: dict[str, str]) -> list[dict]:
    """``paragraphs`` with those of each moved page at the place of the page it
    stands for (``_ogpg_repeats.Repeats.moved``), in page order otherwise."""
    if not moved:
        return paragraphs
    keyed: list[tuple[int, int, dict]] = []
    page = 0
    for i, p in enumerate(paragraphs):
        stem = moved.get(p["stem"], p["stem"])
        if stem.isdigit():
            page = int(stem)
        keyed.append((page, i, p))
    keyed.sort(key=lambda k: (k[0], k[1]))
    return [p for _, _, p in keyed]


def _unit(ref: str, text: str, editorial: list | None = None) -> dict:
    """A raw unit, with Migne's notes at its end marked editorial (#450), or the
    spans its source already marks (a page of new OCR with its notes)."""
    spans = editorial or notes.note_spans(text)
    return {"ref": ref, "text": text, "editorial": spans} if spans else {"ref": ref, "text": text}


def split_volume(
    repo_name: str,
    extract: dict,
    rows: list[pgi.IndexRow],
    repeats: rep.Repeats | None = None,
    ocr: list[dict] | None = None,
    credits: dict[str, str] | None = None,
) -> list[tuple[str, Work, list[dict]]]:
    """Cut an extracted volume into works → ``[(relative path, work, paragraphs)]``.

    Without index rows the volume is one work (``{vol}.json``).  With rows,
    each in-period row becomes ``{vol}/{slug}.json`` and uncovered text goes
    to ``{vol}/other.json``; rows dated after the collection period are
    dropped (their text is not written).  Paragraphs are ``{"ref", "text"}``
    with the positional refs of ``_ogpg_index.assign_refs``, and
    ``"editorial"`` note spans where a paragraph ends in Migne's notes
    (``_ogpg_notes``).  Pages the scan
    repeats (``repeats``, found here when not given) are left out.  Pages of
    new OCR (``ocr``, from ``ocr_pages``) are added where no paragraph has
    the page's columns, never in place of OGL text, so no ref moves; the
    works they go to credit their source (``credits``) in their edition.
    """
    vol_nums, vol_slug = _parse_repo(repo_name)
    part = _parse_repo_part(repo_name)
    scan = extract["pipeline"].get("primary_scan")
    if repeats is None:
        repeats = volume_repeats(extract)
    cmap = cols.map_columns([(stem, nums) for stem, nums in extract["page_heads"]],
                            skip=set(repeats.pages) | set(repeats.moved))
    paras = [{**p, "cols": cmap.columns.get(repeats.moved.get(p["stem"], p["stem"]))}
             for p in _in_place(extract["paragraphs"], repeats.moved)
             if p["stem"] not in repeats.pages]
    paras = _merge_fills(paras, [{**f, "cols": tuple(f["cols"])}
                                 for f in extract.get("fills", [])])
    if ocr:
        have = {_first_page(p["cols"][0]) for p in paras if p.get("cols")}
        paras = _merge_fills(paras, [p for p in ocr if _first_page(p["cols"][0]) not in have])
    if rows:
        paras = pgi.split_inline_headings(paras, rows)
    refs = pgi.assign_refs(paras, vol_slug)
    if not rows:
        work = _credited(_make_work(repo_name, vol_nums, part, vol_slug, scan), paras, credits)
        return [(f"{vol_slug}.json", work,
                 [_unit(r, p["text"], p.get("editorial")) for r, p in zip(refs, paras)])]

    owners = pgi.assign_works(paras, rows)
    last_col = max((p["cols"][1] for p in paras if p.get("cols")), default=None)
    buckets: dict[str | None, list[dict]] = {}
    sources: dict[str | None, list[dict]] = {}
    for ref, para, owner in zip(refs, paras, owners):
        key = None if owner is None else rows[owner].slug
        buckets.setdefault(key, []).append(_unit(ref, para["text"], para.get("editorial")))
        sources.setdefault(key, []).append(para)
    by_slug: dict[str, list[pgi.IndexRow]] = {}
    for row in rows:
        by_slug.setdefault(row.slug, []).append(row)
    out: list[tuple[str, Work, list[dict]]] = []
    for slug, parts in by_slug.items():
        row = parts[0]
        if slug not in buckets:
            log.warning("OPG %s/%s: no text found in cols %s–%s", vol_slug, slug,
                        row.col_start, parts[-1].col_end)
            continue
        if not row.in_period:
            log.info("OPG %s/%s: dropped (after the collection period, %s)",
                     vol_slug, slug, row.date_range)
            continue
        work = _credited(_make_index_work(repo_name, vol_nums, part, parts, last_col, scan),
                         sources[slug], credits)
        out.append((f"{vol_slug}/{slug}.json", work, buckets[slug]))
    if None in buckets:
        work = _credited(_make_work(repo_name, vol_nums, part, vol_slug, scan, remainder=True),
                         sources[None], credits)
        out.append((f"{vol_slug}/{pgi.REMAINDER_SLUG}.json", work, buckets[None]))
    return out


def _ingest_volume(
    repo_name: str,
    repos_dir: Path,
    output_dir: Path,
    force: bool = False,
) -> tuple[list[Work], set[str]]:
    """Extract (or reuse) one volume and write its works.

    Returns the works and the paths (relative to ``output_dir``) written.
    """
    vol_nums, vol_slug = _parse_repo(repo_name)
    part = _parse_repo_part(repo_name)

    # Out of scope: volumes whose contents were all composed after the collection
    # period (PG 121+), consistent with the other sources.  Straddling volumes are
    # kept and their chunks flagged out_of_period by date, or split by the index.
    meta = pgv.lookup(vol_nums, part)
    if meta is not None and not work_in_period(meta.date_range):
        return [], set()

    extract = _extract_volume(repo_name, repos_dir, output_dir / EXTRACT_DIR, force)
    if extract is None:
        return [], set()
    pipeline = {k: v for k, v in extract["pipeline"].items() if k != "id"}
    repeats = volume_repeats(extract)
    pipeline["column_pages"] = cols.map_columns(
        [(stem, nums) for stem, nums in extract["page_heads"]],
        skip=set(repeats.pages) | set(repeats.moved)).numbered
    pipeline["repeated_pages"] = len(repeats.pages)
    works: list[Work] = []
    written: set[str] = set()
    ocr = ocr_pages(vol_slug)
    for rel, work, paragraphs in split_volume(repo_name, extract,
                                              pgi.load_index().get(vol_slug, []), repeats,
                                              ocr, ocr_credits()):
        _write_if_changed(output_dir / rel, {
            "work": work.model_dump(),
            "pipeline": pipeline,
            "paragraphs": paragraphs,
        })
        works.append(work)
        written.add(rel)
    return works, written


def _prune(output_dir: Path, written: set[str], vol_slugs: set[str] | None) -> None:
    """Delete work files not written by this run (all, or only those of ``vol_slugs``)."""
    for path in sorted(output_dir.rglob("*.json")):
        rel = path.relative_to(output_dir).as_posix()
        if rel.startswith("_") or rel in written:
            continue
        vol = rel.split("/")[0].removesuffix(".json")
        if vol_slugs is not None and vol not in vol_slugs:
            continue
        log.info("Removing stale OPG output: %s", rel)
        path.unlink()
    for d in sorted((p for p in output_dir.iterdir() if p.is_dir()), reverse=True):
        if not d.name.startswith("_") and not any(d.iterdir()):
            d.rmdir()


# ---------------------------------------------------------------------------
# Main ingest function
# ---------------------------------------------------------------------------

EXTRACT_DIR = "_extract"


def ingest(output_dir: Path, force: bool = False, only: list[str] | None = None) -> list[Work]:
    """Clone and process all OPG volumes. Returns list of Work records.

    ``output_dir`` is the raw data root (typically ``data/raw``).
    Clones are stored under ``output_dir/_repos/ogpg/{repo_name}/``; per-volume
    extractions under ``output_dir/ogpg/_extract/``; work files under
    ``output_dir/ogpg/`` (``vol-NNN.json`` for an unsplit volume,
    ``vol-NNN/{slug}.json`` for the works of a split one).
    ``only`` restricts processing (and pruning) to the named repos.
    Edits to ``ogpg_index.csv`` are applied by a plain run, from the cached
    extractions.
    """
    ogpg_dir = output_dir / "ogpg"
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
    known = {_parse_repo(r)[1] for r in repo_names}
    unknown = set(pgi.load_index()) - known
    if unknown:
        raise ValueError(f"ogpg_index.csv names unknown volumes: {sorted(unknown)}")

    works: list[Work] = []
    written: set[str] = set()
    for repo_name in tqdm(selected, desc="ogpg volumes"):
        try:
            w, paths = _ingest_volume(repo_name, repos_dir, ogpg_dir, force=force)
            works.extend(w)
            written |= paths
        except (subprocess.CalledProcessError, RuntimeError, OSError) as exc:
            log.error("Error processing %s: %s", repo_name, exc)
            # keep whatever this volume had before
            slug = _parse_repo(repo_name)[1]
            written |= {p.relative_to(ogpg_dir).as_posix() for p in ogpg_dir.rglob("*.json")
                        if p.relative_to(ogpg_dir).as_posix().split("/")[0]
                        .removesuffix(".json") == slug}

    _prune(ogpg_dir, written,
           None if only is None else {_parse_repo(r)[1] for r in selected})

    log.info("OPG ingestion complete: %d works from %d repos (%d repos excluded)",
             len(works), len(selected), len(pgv.EXCLUDED_REPOS))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
