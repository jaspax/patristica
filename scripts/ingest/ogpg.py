"""
Ingestor for Open Patrologia Graeca (OPG).

Source: GitHub organization OGL-PatrologiaGraecaDev — OCR'd Migne PG volumes 1–161
License: Public domain (19th-century Migne text; OCR by Open Greek and Latin project)
Language: Greek (grc), with interleaved Latin — Latin is filtered out at extraction time
Genre: patristic

Strategy: sparse git clone per volume (``*_ocr/*.txt`` from one OCR directory)
to minimise download size (~2–3 MB per volume vs 390 MB full clone).

Usage::

    python -m scripts.ingest.ogpg [--force]
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import unicodedata
from pathlib import Path

import httpx
from tqdm import tqdm

from patristica.models import Work
from scripts.ingest._common import slugify_ref

log = logging.getLogger(__name__)

SOURCE_ID = "patristic/ogpg"
_GITHUB_ORG = "OGL-PatrologiaGraecaDev"
_BASE_URL = f"https://github.com/{_GITHUB_ORG}"
_API_BASE = "https://api.github.com"

# ---------------------------------------------------------------------------
# PG Volume metadata table
# (vol_num) → (author, date_composed, date_range, date_confidence)
# ---------------------------------------------------------------------------

_PG_META: dict[int, tuple[str | None, int | None, tuple[int, int] | None, str]] = {
    1:  ("Apostolic Fathers", None, (50, 160), "approximate"),
    2:  ("Justin Martyr; Hermas", None, (100, 165), "approximate"),
    3:  ("Pseudo-Dionysius Areopagite", None, (480, 520), "approximate"),
    4:  ("Pseudo-Dionysius Areopagite", None, (480, 520), "approximate"),
    5:  ("Apostolic Fathers; Various Apologists", None, (100, 200), "approximate"),
    6:  ("Justin Martyr; Tatian; Athenagoras", None, (100, 190), "approximate"),
    7:  ("Irenaeus of Lyons", 202, (130, 202), "established"),
    8:  ("Clement of Alexandria", 215, (150, 215), "established"),
    9:  ("Clement of Alexandria", 215, (150, 215), "established"),
    10: ("Origen", 254, (184, 254), "established"),
    11: ("Origen", 254, (184, 254), "established"),
    12: ("Origen", 254, (184, 254), "established"),
    13: ("Origen", 254, (184, 254), "established"),
    14: ("Origen", 254, (184, 254), "established"),
    15: ("Origen", 254, (184, 254), "established"),
    16: ("Origen", 254, (184, 254), "established"),
    17: ("Origen", 254, (184, 254), "established"),
    18: ("Methodius of Olympus; Gregory Thaumaturgus; Pamphilus", None, (213, 311), "approximate"),
    19: ("Eusebius of Caesarea", 339, (260, 339), "established"),
    20: ("Eusebius of Caesarea", 339, (260, 339), "established"),
    21: ("Eusebius of Caesarea", 339, (260, 339), "established"),
    22: ("Eusebius of Caesarea", 339, (260, 339), "established"),
    23: ("Eusebius of Caesarea", 339, (260, 339), "established"),
    24: ("Eusebius of Caesarea", 339, (260, 339), "established"),
    25: ("Athanasius of Alexandria", 373, (296, 373), "established"),
    26: ("Athanasius of Alexandria", 373, (296, 373), "established"),
    27: ("Athanasius of Alexandria", 373, (296, 373), "established"),
    28: ("Athanasius of Alexandria", 373, (296, 373), "established"),
    29: ("Basil of Caesarea", 379, (330, 379), "established"),
    30: ("Basil of Caesarea", 379, (330, 379), "established"),
    31: ("Basil of Caesarea", 379, (330, 379), "established"),
    32: ("Basil of Caesarea", 379, (330, 379), "established"),
    33: ("Cyril of Jerusalem; Gregory Nazianzen", None, (313, 390), "established"),
    34: ("Gregory Nazianzen", 390, (329, 390), "established"),
    35: ("Gregory Nazianzen", 390, (329, 390), "established"),
    36: ("Gregory Nazianzen", 390, (329, 390), "established"),
    37: ("Gregory Nazianzen", 390, (329, 390), "established"),
    38: ("Gregory Nazianzen", 390, (329, 390), "established"),
    39: ("Didymus the Blind", 398, (313, 398), "established"),
    40: ("Amphilochius of Iconium; Evagrius of Pontus; Various", None, (340, 400), "approximate"),
    41: ("Various", None, (340, 420), "approximate"),
    42: ("Epiphanius of Salamis", 403, (310, 403), "established"),
    43: ("Epiphanius of Salamis", 403, (310, 403), "established"),
    44: ("Gregory of Nyssa", 395, (335, 395), "established"),
    45: ("Gregory of Nyssa", 395, (335, 395), "established"),
    46: ("Gregory of Nyssa", 395, (335, 395), "established"),
    47: ("John Chrysostom", 407, (349, 407), "established"),
    48: ("John Chrysostom", 407, (349, 407), "established"),
    49: ("John Chrysostom", 407, (349, 407), "established"),
    50: ("John Chrysostom", 407, (349, 407), "established"),
    51: ("John Chrysostom", 407, (349, 407), "established"),
    52: ("John Chrysostom", 407, (349, 407), "established"),
    53: ("John Chrysostom", 407, (349, 407), "established"),
    54: ("John Chrysostom", 407, (349, 407), "established"),
    55: ("John Chrysostom", 407, (349, 407), "established"),
    56: ("John Chrysostom", 407, (349, 407), "established"),
    57: ("John Chrysostom", 407, (349, 407), "established"),
    58: ("John Chrysostom", 407, (349, 407), "established"),
    59: ("John Chrysostom", 407, (349, 407), "established"),
    60: ("John Chrysostom", 407, (349, 407), "established"),
    61: ("John Chrysostom", 407, (349, 407), "established"),
    62: ("John Chrysostom", 407, (349, 407), "established"),
    63: ("John Chrysostom", 407, (349, 407), "established"),
    64: ("John Chrysostom", 407, (349, 407), "established"),
    65: ("Theodore of Mopsuestia; Various", None, (350, 466), "approximate"),
    66: ("Theodoret of Cyrrhus", 466, (393, 466), "established"),
    67: ("Theodoret of Cyrrhus", 466, (393, 466), "established"),
    68: ("Theodoret of Cyrrhus", 466, (393, 466), "established"),
    69: ("Theodoret of Cyrrhus", 466, (393, 466), "established"),
    70: ("Theodoret of Cyrrhus", 466, (393, 466), "established"),
    71: ("Theodoret of Cyrrhus", 466, (393, 466), "established"),
    72: ("Theodoret of Cyrrhus", 466, (393, 466), "established"),
    73: ("Cyril of Alexandria", 444, (376, 444), "established"),
    74: ("Cyril of Alexandria", 444, (376, 444), "established"),
    75: ("Cyril of Alexandria", 444, (376, 444), "established"),
    76: ("Cyril of Alexandria", 444, (376, 444), "established"),
    77: ("Cyril of Alexandria", 444, (376, 444), "established"),
    78: ("Proclus of Constantinople; Various", None, (390, 450), "approximate"),
    79: ("Nilus of Ancyra; Various", None, (390, 430), "approximate"),
    80: ("Various", None, (400, 500), "approximate"),
    81: ("Theodoret of Cyrrhus", 466, (393, 466), "established"),
    82: ("Theodoret of Cyrrhus", 466, (393, 466), "established"),
    83: ("Theodoret of Cyrrhus", 466, (393, 466), "established"),
    84: ("Theodoret of Cyrrhus", 466, (393, 466), "established"),
    85: ("Various (5th–6th century)", None, (400, 600), "approximate"),
    86: ("Leontius of Byzantium; Various", None, (480, 620), "approximate"),
    87: ("John of Damascus", 749, (676, 749), "established"),
    88: ("John of Damascus", 749, (676, 749), "established"),
    89: ("John of Damascus", 749, (676, 749), "established"),
    90: ("Maximus the Confessor", 662, (580, 662), "established"),
    91: ("Maximus the Confessor", 662, (580, 662), "established"),
    92: ("George of Pisidia; Various", None, (575, 650), "approximate"),
    93: ("Anastasius Sinaita; Various", None, (610, 700), "approximate"),
    94: ("John of Damascus (continued)", 749, (676, 749), "established"),
    95: ("John of Damascus (continued)", 749, (676, 749), "established"),
    96: ("John of Damascus (continued)", 749, (676, 749), "established"),
    97: ("Theodore Studites; Various", None, (759, 850), "approximate"),
    98: ("Various (8th–9th century)", None, (700, 900), "approximate"),
    99: ("Photius of Constantinople", 893, (820, 893), "established"),
    100: ("Photius of Constantinople", 893, (820, 893), "established"),
    101: ("Photius of Constantinople", 893, (820, 893), "established"),
    102: ("Various (9th–10th century)", None, (800, 1000), "uncertain"),
    103: ("Various (9th–10th century)", None, (800, 1000), "uncertain"),
    104: ("Various (9th–10th century)", None, (800, 1054), "uncertain"),
    105: ("Various (9th–10th century)", None, (800, 1054), "uncertain"),
    106: ("Various (9th–10th century)", None, (850, 1054), "uncertain"),
    107: ("Various (10th–11th century)", None, (900, 1054), "uncertain"),
    108: ("Various (10th–11th century)", None, (900, 1054), "uncertain"),
    109: ("Various (10th–11th century)", None, (900, 1054), "uncertain"),
    110: ("Various (10th–11th century)", None, (900, 1054), "uncertain"),
    111: ("Symeon the New Theologian; Various", None, (949, 1022), "approximate"),
    # PG 112+: mostly post-schism Byzantine (date_range[0] > 1054 → post_schism=True in normalize)
    **{v: ("Various (post-schism Byzantine)", None, (1055, 1440), "uncertain")
       for v in range(112, 162)},
    # Known post-schism authors with more specific dating
    # (override the default above)
}
_PG_META[120] = ("Theophylact of Ohrid", None, (1055, 1108), "approximate")
_PG_META[121] = ("Theophylact of Ohrid", None, (1055, 1108), "approximate")
_PG_META[122] = ("Theophylact of Ohrid", None, (1055, 1108), "approximate")
_PG_META[129] = ("Euthymius Zigabenus", 1118, (1055, 1118), "approximate")
_PG_META[138] = ("Nicephorus I of Constantinople; Various", None, (758, 829), "established")
_PG_META[144] = ("Nicetas Stethatos; Various", None, (1055, 1090), "approximate")
_PG_META[150] = ("Gregory Palamas", 1359, (1296, 1359), "established")
_PG_META[151] = ("Gregory Palamas", 1359, (1296, 1359), "established")


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


def _vol_meta(vol_nums: list[int]) -> tuple[str | None, int | None, tuple[int, int] | None, str]:
    """Return (author, date_composed, date_range, date_confidence) for a set of volumes."""
    primary = vol_nums[0]
    meta = _PG_META.get(primary)
    if meta:
        return meta
    return None, None, None, "uncertain"


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


def _get_ocr_dirs(repo_name: str) -> list[str]:
    """Return top-level *_ocr directory names in the repo (via GitHub tree API)."""
    headers = _github_headers()
    with httpx.Client(timeout=30) as client:
        r = client.get(
            f"{_API_BASE}/repos/{_GITHUB_ORG}/{repo_name}/git/trees/HEAD",
            headers=headers,
        )
        if r.status_code != 200:
            return []
        data = r.json()
    return [
        item["path"]
        for item in data.get("tree", [])
        if item["type"] == "tree" and item["path"].endswith("_ocr")
    ]


def _preferred_ocr_dir(ocr_dirs: list[str]) -> str | None:
    """Pick the best *_ocr directory: prefer hvd*, then coo*, then first alphabetically."""
    if not ocr_dirs:
        return None
    for prefix in ("hvd", "coo", "mdp", "njp", "nnc", "nyp", "pst"):
        for d in sorted(ocr_dirs):
            if d.startswith(prefix):
                return d
    return sorted(ocr_dirs)[0]


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
        log.error("git checkout failed for %s: %s", repo_name, exc.stderr[:300] if exc.stderr else "")
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


def _extract_paragraphs(txt_files: list[Path], vol_slug: str) -> list[dict[str, str]]:
    """Process sorted OCR page files → list of {"ref": ..., "text": ...}."""
    paragraphs: list[dict[str, str]] = []
    current_lines: list[str] = []
    para_idx = 0

    def _flush(lines: list[str]) -> None:
        nonlocal para_idx
        text = " ".join(lines).strip()
        # Quality filters: length, Greek char ratio, meaningful word ratio,
        # and presence of real Greek function words (rejects garbled-OCR noise)
        if (len(text) >= 60
                and _greek_ratio(text) >= 0.40
                and _meaningful_greek_word_ratio(text) >= 0.25
                and _has_function_words(text, min_count=2)):
            para_idx += 1
            ref = f"ogpg.{vol_slug}.{para_idx:05d}"
            paragraphs.append({"ref": ref, "text": text})

    for page_path in sorted(txt_files, key=lambda p: p.stem):
        # Flush at each page boundary to prevent cross-page concatenation
        if current_lines:
            _flush(current_lines)
            current_lines = []

        # Skip first 8 pages (title pages, copyright, table of contents)
        stem = page_path.stem
        if stem.isdigit() and int(stem) < 9:
            continue

        try:
            raw = page_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        raw = _fix_hyphenation(raw)
        for line in raw.splitlines():
            line = _clean_line(line)
            if not line:
                if current_lines:
                    _flush(current_lines)
                    current_lines = []
                continue

            if len(line) < 12:
                if current_lines:
                    _flush(current_lines)
                    current_lines = []
                continue

            if _greek_ratio(line) >= 0.35:
                current_lines.append(line)
            else:
                if current_lines:
                    _flush(current_lines)
                    current_lines = []

    if current_lines:
        _flush(current_lines)

    return paragraphs


# ---------------------------------------------------------------------------
# Work factory
# ---------------------------------------------------------------------------

def _make_work(repo_name: str, vol_nums: list[int], vol_slug: str) -> Work:
    author, date_composed, date_range, date_conf = _vol_meta(vol_nums)
    primary = vol_nums[0]
    title = f"Patrologia Graeca Vol. {primary}" if len(vol_nums) == 1 \
        else f"Patrologia Graeca Vol. {vol_nums[0]}–{vol_nums[-1]}"

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
        edition="Patrologiae Cursus Completus, Series Graeca, ed. Migne",
        translation_of=None,
    )


# ---------------------------------------------------------------------------
# Per-volume ingestion
# ---------------------------------------------------------------------------

def _ingest_volume(
    repo_name: str,
    repos_dir: Path,
    output_dir: Path,
    force: bool = False,
) -> Work | None:
    vol_nums, vol_slug = _parse_repo(repo_name)
    out_path = output_dir / f"{vol_slug}.json"

    if out_path.exists() and not force:
        try:
            saved = json.loads(out_path.read_text(encoding="utf-8"))
            return Work(**saved["work"])
        except Exception:
            pass

    clone_dir = repos_dir / repo_name
    existing_txts = sorted(clone_dir.rglob("*.txt")) if clone_dir.exists() else []

    if not existing_txts or force:
        ok = _sparse_clone(repo_name, clone_dir)
        if not ok:
            return None
        existing_txts = sorted(clone_dir.rglob("*.txt"))

    if not existing_txts:
        log.warning("No .txt files found for %s", repo_name)
        return None

    paragraphs = _extract_paragraphs(existing_txts, vol_slug)
    if not paragraphs:
        log.warning("No Greek paragraphs extracted from %s", repo_name)
        return None

    work = _make_work(repo_name, vol_nums, vol_slug)
    payload = {"work": work.model_dump(), "paragraphs": paragraphs}
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("OPG %s: %d paragraphs → %s", vol_slug, len(paragraphs), out_path.name)
    return work


# ---------------------------------------------------------------------------
# Main ingest function
# ---------------------------------------------------------------------------

def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Sparse-clone and process all OPG volumes. Returns list of Work records.

    ``output_dir`` is the raw data root (typically ``data/raw``).
    Clones are stored under ``output_dir/_repos/ogpg/{repo_name}/``.
    Output JSON files go to ``output_dir/patristic/ogpg/``.
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

    works: list[Work] = []
    for repo_name in tqdm(repo_names, desc="ogpg volumes"):
        try:
            w = _ingest_volume(repo_name, repos_dir, ogpg_dir, force=force)
            if w:
                works.append(w)
        except Exception as exc:
            log.error("Error processing %s: %s", repo_name, exc)

    log.info("OPG ingestion complete: %d works from %d repos", len(works), len(repo_names))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
