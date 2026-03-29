"""
Normalize raw ingest output → normalized Chunk JSON records.

One normalized JSON file per work, written to data/normalized/{source_id}/.

TODO: Implement per-genre normalization logic (Milestone 2+).
"""

from __future__ import annotations

import argparse
import logging

log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Normalize raw ingested data.")
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--output-dir", default="data/normalized")
    parser.add_argument("--force", action="store_true")
    _args = parser.parse_args()

    # TODO: walk raw-dir, apply per-source normalizers, write Chunk JSON
    raise NotImplementedError("normalize.py is not yet implemented")


if __name__ == "__main__":
    main()
