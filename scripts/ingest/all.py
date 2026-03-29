"""
Run all registered ingestion modules.

Usage
-----
    python -m scripts.ingest.all
    python -m scripts.ingest.all --output-dir data/raw --force
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


def discover_ingestors() -> list[str]:
    """Return module names for every ingestor in the scripts.ingest package.

    Excludes ``_common`` and ``all`` (this module).
    """
    skip = {"_common", "all"}
    modules = []
    for info in pkgutil.iter_modules(_ingest_pkg.__path__):
        if info.name not in skip and not info.name.startswith("_"):
            modules.append(f"scripts.ingest.{info.name}")
    return sorted(modules)


def run_all(output_dir: Path, force: bool = False) -> list[Work]:
    """Import and run every ingestor, returning all Work records produced."""
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

    parser = argparse.ArgumentParser(description="Run all Patristica ingestors.")
    parser.add_argument(
        "--output-dir",
        default="data/raw",
        help="Root directory for raw output files (default: data/raw)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download and re-parse even if output already exists",
    )
    args = parser.parse_args()

    works = run_all(Path(args.output_dir), force=args.force)
    print(f"Ingestion complete. {len(works)} total works.")


if __name__ == "__main__":
    main()
