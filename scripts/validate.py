"""
QC validation checks on normalized and chunk data.

Outputs data/validation_report.json.

Checks (see DATA_COLLECTION_PLAN.md §8):
- No empty text fields
- All language values are valid ISO 639-3 codes
- All canonical_refs parse against their expected schema
- No duplicate chunk_id values
- date_composed plausible for claimed genre/tradition
- Translation groups have ≥2 members

TODO: Implement validation logic (Milestone 7).
"""

from __future__ import annotations

import argparse
import logging

log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Validate normalized and chunk data.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output", default="data/validation_report.json")
    _args = parser.parse_args()

    # TODO: run QC checks, write validation_report.json
    raise NotImplementedError("validate.py is not yet implemented")


if __name__ == "__main__":
    main()
