"""
Ingest stamps (#130): which ingestor code produced a source's raw data.

After an ingestor runs, ``data/raw/{source_id}/_ingest.json`` records the hash
of its code (``patristica.fingerprint.code_hash`` of the ingestor module's
import closure, leaving out the shared runners). ``scripts.normalize`` copies
the stamp into the tracked ``data/normalized/_fingerprint.json``, so
``scripts.status`` can warn, even in CI, when an ingestor changed after its
source's data was normalized: the raw data, and so the corpus, may be out of
date (as with the ``translation_of`` links of #150, set in ingestor code).

Ingestors skip files that already exist unless ``force``, so re-running a
changed ingestor without ``--force`` leaves the old raw data. A stamp is
therefore written only by a ``--force`` run or into a source with no works
yet; otherwise a changed ingestor is logged and the old stamp kept.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

from patristica import fingerprint

log = logging.getLogger(__name__)

STAMP = "_ingest.json"
#: Shared runners: not part of any ingestor's code.
RUNNERS = ("scripts.ingest._ingestor_main", "scripts.ingest._stamp", "scripts.ingest.all")


def module_for(source_id: str) -> str:
    """The ingestor module of *source_id* (``lxx-rahlfs`` → ``scripts.ingest.lxx_rahlfs``)."""
    return "scripts.ingest." + source_id.split("/")[-1].replace("-", "_")


def ingest_code_hash(source_id: str) -> str | None:
    """Hash of *source_id*'s ingestor code, or None if it has no ingestor module."""
    try:
        return fingerprint.code_hash(module_for(source_id), ignore=RUNNERS)
    except fingerprint.FingerprintError:
        return None


def read_stamp(raw_root: Path, source_id: str) -> str | None:
    """The ingestor code hash recorded for *source_id*'s raw data, if any."""
    path = raw_root / source_id / STAMP
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("code")


def _has_works(source_dir: Path) -> bool:
    return source_dir.is_dir() and any(
        not any(part.startswith("_") for part in p.relative_to(source_dir).parts)
        for p in source_dir.rglob("*.json"))


def run_stamped(ingest_fn: Callable[..., list], output_dir: Path, source_id: str,
                force: bool = False) -> list:
    """Run an ingestor and stamp its raw data with its code hash (see above)."""
    source_dir = output_dir / source_id
    fresh = force or not _has_works(source_dir)
    works = ingest_fn(output_dir, force=force)
    code = ingest_code_hash(source_id)
    if code is None or not source_dir.is_dir():
        return works
    old = read_stamp(output_dir, source_id)
    if fresh:
        if old != code:
            (source_dir / STAMP).write_text(json.dumps({"code": code}) + "\n", encoding="utf-8")
    elif old != code:
        log.warning("%s: the ingestor changed since its raw data was produced%s; existing "
                    "files were kept, so re-run with --force to regenerate them",
                    source_id, "" if old else " (or the data predates ingest stamps)")
    return works
