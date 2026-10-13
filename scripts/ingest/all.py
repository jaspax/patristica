"""
Run ingestion modules — all at once, or a single named source.

Usage
-----
    # Run every ingestor:
    python -m scripts.ingest.all

    # Run a single source:
    python -m scripts.ingest.all --source scripture/oshb

    # Force re-download:
    python -m scripts.ingest.all --source scripture/kjv --force

Individual sources can also be run directly:
    python -m scripts.ingest.oshb
    python -m scripts.ingest.kjv  --force
    python -m scripts.ingest.sblgnt
"""

from __future__ import annotations

import argparse
import importlib
import logging
import pkgutil
from pathlib import Path

import scripts.ingest as _ingest_pkg
from patristica.models import Work

log = logging.getLogger(__name__)

# Private helpers and orchestration modules — never treated as ingestors
_NON_INGESTOR_PREFIXES = {"_"}
_NON_INGESTOR_NAMES = {"all"}


def discover_ingestors() -> list[str]:
    """Return module names for every ingestor in the scripts.ingest package.

    Excludes private modules (``_common``, ``_scrollmapper``, etc.) and this
    orchestration module (``all``).
    """
    modules = []
    for info in pkgutil.iter_modules(_ingest_pkg.__path__):
        if info.name in _NON_INGESTOR_NAMES:
            continue
        if any(info.name.startswith(p) for p in _NON_INGESTOR_PREFIXES):
            continue
        modules.append(f"scripts.ingest.{info.name}")
    return sorted(modules)


def _source_id_to_module(source_id: str) -> str:
    """Convert a source_id like ``"scripture/oshb"`` to a module name.

    The mapping is: take the last path component, replace ``-`` with ``_``.
    ``"scripture/oshb"`` → ``"scripts.ingest.oshb"``
    ``"scripture/lxx-rahlfs"`` → ``"scripts.ingest.lxx_rahlfs"``
    ``"scripture/coptic-nt"`` → ``"scripts.ingest.coptic_nt"``
    """
    name = source_id.split("/")[-1].replace("-", "_")
    return f"scripts.ingest.{name}"


def run_one(source_id: str, output_dir: Path, force: bool = False) -> list[Work]:
    """Run a single ingestor by source_id and return its Work records."""
    module_name = _source_id_to_module(source_id)
    log.info("Running ingestor: %s", module_name)
    mod = importlib.import_module(module_name)
    works = mod.ingest(output_dir, force=force)
    log.info("  → %d works from %s", len(works), module_name)
    return works


def run_all(output_dir: Path, force: bool = False) -> list[Work]:
    """Import and run every discovered ingestor, returning all Work records."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    ingestors = discover_ingestors()
    if not ingestors:
        log.warning("No ingestor modules found in scripts/ingest/")
        return []

    all_works: list[Work] = []
    for module_name in ingestors:
        log.info("Running ingestor: %s", module_name)
        try:
            mod = importlib.import_module(module_name)
            works = mod.ingest(output_dir, force=force)
            log.info("  → %d works from %s", len(works), module_name)
            all_works.extend(works)
        except Exception:
            log.exception("Ingestor %s failed", module_name)

    return all_works


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Run Patristica ingestors.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m scripts.ingest.all\n"
            "  python -m scripts.ingest.all --source scripture/oshb\n"
            "  python -m scripts.ingest.all --source scripture/kjv --force\n"
        ),
    )
    parser.add_argument(
        "--output-dir",
        default="data/raw",
        help="Root directory for raw output files (default: data/raw)",
    )
    parser.add_argument(
        "--source",
        default=None,
        metavar="SOURCE_ID",
        help="Run only this source (e.g. 'scripture/oshb'). Omit to run all.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download and re-parse even if output already exists",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Transitional (#102): refuse to write a second copy next to old-layout raw data.
    from scripts.migrate_layout import MigrationError, check_raw_layout

    try:
        check_raw_layout(output_dir)
    except MigrationError as exc:
        parser.error(str(exc))

    if args.source:
        works = run_one(args.source, output_dir, force=args.force)
        print(f"Ingestion complete. {len(works)} works from {args.source}.")
    else:
        works = run_all(output_dir, force=args.force)
        print(f"Ingestion complete. {len(works)} total works.")


if __name__ == "__main__":
    main()
