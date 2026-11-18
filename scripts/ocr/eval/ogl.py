"""The existing OGL OCR of an eval page: the baseline row (#718).

An eval page from another source (Calfa's PDFs) is found in the volume's
primary OGL scan by text: the page whose folded Greek letter 4-grams contain
most of the ground truth's. Its Greek lines, chosen as the ingestor chooses
them (``_greek_ratio`` ≥ 0.35), are the baseline hypothesis.

Reads the upstream clones (``data/raw/_repos/ogpg``) and the ingestor's
extract cache (``data/raw/ogpg/_extract``), so it runs in the main checkout
(pass ``--data-root`` from a worktree).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from scripts.ingest import ogpg
from scripts.ingest._greek_lexicon import normalize_token

log = logging.getLogger(__name__)

# The ingestor's threshold for a Greek line in the mixed-language page text.
GREEK_LINE_RATIO = 0.35
# A match must contain at least this share of the ground truth's 4-grams.
MIN_CONTAINMENT = 0.3


@dataclass(frozen=True)
class Match:
    scan: str
    stem: str
    containment: float
    text: str  # the page's Greek lines
    ingested: bool  # from the primary scan of an ingested volume


def repo_dirs(data_root: Path, volume: str) -> list[Path]:
    """Every clone holding PG ``volume``.

    "16.3" → Vol.-16.3; "87" → Vol.-87, Vol.-87.1, …, Vol.-87-88.
    """
    base = data_root / "data" / "raw" / "_repos" / "ogpg"
    direct = base / f"Vol.-{volume}"
    if "." in volume and direct.is_dir():
        return [direct]
    main = int(volume.split(".")[0])
    out = []
    for d in sorted(base.glob("Vol.-*")):
        try:
            nums, _ = ogpg._parse_repo(d.name)
        except ValueError:
            continue
        if main in nums:
            out.append(d)
    if not out:
        raise FileNotFoundError(f"no OGPG clone for PG {volume} under {base}")
    return out


def primary_scan(data_root: Path, clone: Path) -> str | None:
    """The scan the ingestor voted primary for this clone.

    ``""`` when the ingestor read the clone but took no scan from it (an
    alias repo such as Vol.-87-88); None when it never read it (out of period).
    """
    _, slug = ogpg._parse_repo(clone.name)
    extract = data_root / "data" / "raw" / "ogpg" / "_extract" / f"{slug}.json"
    if not extract.exists():
        return None
    return json.loads(extract.read_text())["pipeline"].get("primary_scan", "")


def greek_lines(text: str) -> str:
    return "\n".join(
        ln for ln in text.splitlines() if ogpg._greek_ratio(ln) >= GREEK_LINE_RATIO
    )


def grams(text: str, n: int = 4) -> frozenset[str]:
    """Character n-grams of the folded Greek letters (no accents, spaces)."""
    letters = "".join(normalize_token(tok) for tok in text.split())
    return frozenset(letters[i:i + n] for i in range(len(letters) - n + 1))


def trim_to(text: str, reference: str, min_share: float = 0.5) -> str:
    """The run of ``text``'s lines that best covers ``reference``.

    Each line scores the share of its 4-grams found in the reference minus
    ``min_share``; the kept lines are the window with the largest sum (a
    maximum-subarray). That drops what the reference doesn't cover (titles,
    the running head, Greek notes, another column), so they don't count as
    insertions, while a garbled line inside the span is kept and counts.
    """
    ref = grams(reference)
    lines = text.splitlines()
    best, best_span = 0.0, None
    run, start = 0.0, 0
    for i, ln in enumerate(lines):
        g = grams(ln)
        score = (len(g & ref) / len(g) if g else 0.0) - min_share
        if run <= 0:
            run, start = 0.0, i
        run += score
        if run > best:
            best, best_span = run, (start, i)
    if best_span is None:
        return ""
    return "\n".join(lines[best_span[0]: best_span[1] + 1])


@lru_cache(maxsize=8)
def _scan_pages(clone: Path, scan: str) -> tuple[tuple[str, str, frozenset[str]], ...]:
    files = ogpg._scan_files(clone).get(scan)
    if not files:
        raise FileNotFoundError(f"scan {scan} not in {clone}")
    ogpg._fetch_scans(clone, [scan])
    out = []
    for stem, text in ogpg._read_scan(clone, files):
        g = greek_lines(text)
        out.append((stem, g, grams(g)))
    return tuple(out)


def find_page(data_root: Path, volume: str, reference: str) -> Match | None:
    """The OGL page of ``volume`` whose Greek best contains ``reference``.

    Searched in the primary scan of every clone of the volume that the
    ingestor read, and in every scan of a clone it didn't (out of period).
    """
    ref = grams(reference)
    if not ref:
        return None
    best: Match | None = None
    for clone in repo_dirs(data_root, volume):
        primary = primary_scan(data_root, clone)
        if primary == "":
            continue
        scans = [primary] if primary else sorted(ogpg._scan_files(clone))
        for scan in scans:
            for stem, text, g in _scan_pages(clone, scan):
                c = len(ref & g) / len(ref)
                if best is None or c > best.containment:
                    best = Match(scan=f"{clone.name}/{scan}", stem=stem, containment=c,
                                 text=text, ingested=primary is not None)
    if best is None or best.containment < MIN_CONTAINMENT:
        log.debug("PG %s: no OGL page matches (best %.2f)", volume, best.containment if best else 0)
        return None
    return best
