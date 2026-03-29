"""
Chunk normalized JSON records → chunk records ready for embedding.

Applies per-genre chunking rules (see DATA_COLLECTION_PLAN.md §5).

TODO: Implement chunking logic (Milestone 2+).
"""

from __future__ import annotations

import argparse
import logging

log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Chunk normalized data.")
    parser.add_argument("--input-dir", default="data/normalized")
    parser.add_argument("--output-dir", default="data/chunks")
    parser.add_argument("--force", action="store_true")
    _args = parser.parse_args()

    # TODO: load normalized records, apply chunking rules, write Chunk JSON
    raise NotImplementedError("chunk.py is not yet implemented")


if __name__ == "__main__":
    main()
