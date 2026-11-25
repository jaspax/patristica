"""Write author bios and work descriptions (#795) to ``data/descriptions/``.

See ``patristica/descriptions.py`` for the format.

Usage::

    python -m scripts.describe placeholder   # lorem ipsum for every author and work (layout review)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path

from patristica import console, descriptions
from patristica.authors import author_index
from patristica.descriptions import PLACEHOLDER_MODEL, Description

log = logging.getLogger(__name__)

WORKS_MANIFEST = Path("data/normalized/_works.jsonl")

LOREM = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor "
    "incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud "
    "exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure "
    "dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. "
    "Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt "
    "mollit anim id est laborum. Curabitur pretium tincidunt lacus, nulla gravida orci a "
    "odio, nullam varius turpis et commodo pharetra est eros bibendum elit nec luctus magna "
    "felis sollicitudin mauris. Integer in mauris eu nibh euismod gravida, duis ac tellus "
    "et risus vulputate vehicula donec lobortis risus a elit."
).split()


def lorem(key: str) -> str:
    """50–100 words of lorem ipsum, the length fixed by *key*."""
    n = 50 + int(hashlib.sha256(key.encode()).hexdigest(), 16) % 51
    words = (LOREM * 2)[:n]
    return " ".join(words).rstrip(",.") + "."


def work_ids(manifest: Path = WORKS_MANIFEST) -> list[str]:
    with manifest.open(encoding="utf-8") as f:
        return [json.loads(line)["work"]["work_id"] for line in f if line.strip()]


def placeholder(root: Path) -> None:
    """Lorem ipsum for every author and work; every third gets a Wikipedia link."""
    authors = author_index().authors
    bios = [Description(aid, lorem(aid),
                        f"{descriptions.WIKIPEDIA_PREFIX}{a.name.replace(' ', '_')}",
                        PLACEHOLDER_MODEL)
            for aid, a in authors.items()]
    works = [Description(wid, lorem(wid),
                         f"{descriptions.WIKIPEDIA_PREFIX}Special:Random" if i % 3 == 0 else None,
                         PLACEHOLDER_MODEL)
             for i, wid in enumerate(work_ids())]
    descriptions.save(root / descriptions.AUTHORS_FILE, bios)
    descriptions.save(root / descriptions.WORKS_FILE, works)
    log.info("Wrote placeholders for %d authors and %d works", len(bios), len(works))


def main() -> None:
    console.setup_logging()
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dir", type=Path, default=descriptions.DEFAULT_DIR)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("placeholder", help="lorem ipsum for every author and work")
    args = parser.parse_args()
    if args.command == "placeholder":
        placeholder(args.dir)


if __name__ == "__main__":
    main()
