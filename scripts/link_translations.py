"""
Assign translation_group_id across parallel chunks in different languages.

For Scripture this is deterministic (same canonical verse ID across translations).
For Patristics it uses section-level alignment or a manual mapping table.

TODO: Implement translation linking logic (Milestone 2+).
"""

from __future__ import annotations

import argparse
import logging

log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Link translation groups across languages.")
    parser.add_argument("--chunks-dir", default="data/chunks")
    parser.add_argument("--force", action="store_true")
    _args = parser.parse_args()

    # TODO: align chunks by canonical_ref across languages, assign translation_group_id
    raise NotImplementedError("link_translations.py is not yet implemented")


if __name__ == "__main__":
    main()
