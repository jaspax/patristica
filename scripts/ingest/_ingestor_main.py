"""
Shared ``main()`` helper for individual ingestor entry points.

Each ingestor module calls this to become directly runnable::

    # In scripts/ingest/oshb.py:
    from scripts.ingest._ingestor_main import ingestor_main
    if __name__ == "__main__":
        ingestor_main(ingest, SOURCE_ID)

This allows:

    python -m scripts.ingest.oshb
    python -m scripts.ingest.oshb --output-dir data/raw --force
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
from typing import Callable

from patristica.models import Work
from scripts.ingest._stamp import run_stamped


def ingestor_main(
    ingest_fn: Callable[[Path, bool], list[Work]],
    source_id: str,
) -> None:
    """Parse CLI args and call *ingest_fn* with the resolved output dir."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(
        description=f"Run the '{source_id}' ingestor.",
    )
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

    works = run_stamped(ingest_fn, Path(args.output_dir), source_id, force=args.force)
    print(f"{source_id}: {len(works)} works written to {args.output_dir}")
