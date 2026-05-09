"""
Look up texts by canonical reference.

Usage
-----
    python -m scripts.lookup -q 1Cor
    python -m scripts.lookup -q 1Cor.4
    python -m scripts.lookup -q 1Cor.4.4
    python -m scripts.lookup -q Gen --lang hbo
    python -m scripts.lookup -q Gen --list-translations
    python -m scripts.lookup --list-works
    python -m scripts.lookup --list-works --lang grc
    python -m scripts.lookup --list-works --source-id scripture/sblgnt
    python -m scripts.lookup -q Gen --rebuild-index
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from patristica.lookup import (
    format_results,
    list_translations,
    list_works,
    lookup,
)

log = logging.getLogger(__name__)


def _print_works_table(entries: list) -> None:
    if not entries:
        print("No works found.")
        return
    prefix_w = max((len(e["canonical_prefix"]) for e in entries), default=16)
    prefix_w = max(prefix_w, len("CANONICAL_PREFIX"))
    source_w = max((len(e["source_id"]) for e in entries), default=20)
    source_w = max(source_w, len("SOURCE_ID"))
    title_w = max((len(e["title"]) for e in entries), default=5)
    title_w = max(title_w, len("TITLE"))

    header = (
        f"{'CANONICAL_PREFIX':<{prefix_w}}  {'LANG':<4}  "
        f"{'SOURCE_ID':<{source_w}}  {'TITLE':<{title_w}}"
    )
    print(header)
    print("-" * len(header))
    for e in entries:
        print(
            f"{e['canonical_prefix']:<{prefix_w}}  {e['language']:<4}  "
            f"{e['source_id']:<{source_w}}  {e['title']}"
        )
    print(f"\n{len(entries)} works")


def _print_translations_table(entries: list) -> None:
    if not entries:
        print("No works found.")
        return
    source_w = max((len(e["source_id"]) for e in entries), default=20)
    source_w = max(source_w, len("SOURCE_ID"))
    title_w = max((len(e["title"]) for e in entries), default=5)
    print(f"{'LANGUAGE':<10}  {'SOURCE_ID':<{source_w}}  TITLE")
    print("-" * (10 + 2 + source_w + 2 + max(title_w, 5)))
    for e in sorted(entries, key=lambda x: (x["language"], x["source_id"])):
        print(f"{e['language']:<10}  {e['source_id']:<{source_w}}  {e['title']}")


def main() -> None:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(
        description="Look up texts by canonical reference.",
        epilog=(
            "Examples:\n"
            "  python -m scripts.lookup -q 1Cor.4.4\n"
            "  python -m scripts.lookup -q Gen --lang hbo\n"
            "  python -m scripts.lookup --list-works --lang grc"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "-q", "--query",
        help='Canonical ref to look up, e.g. "1Cor", "1Cor.4", "1Cor.4.4"',
    )
    parser.add_argument(
        "--lang",
        default=None,
        help='Language code to filter (e.g. "eng", "grc", "hbo")',
    )
    parser.add_argument(
        "--source-id",
        default=None,
        metavar="SOURCE_ID",
        help='Restrict to a specific source (e.g. "scripture/kjv")',
    )
    parser.add_argument(
        "--list-translations",
        action="store_true",
        help="List all available languages and sources for -q QUERY, then exit",
    )
    parser.add_argument(
        "--list-works",
        action="store_true",
        help="List all works in the index, then exit (combinable with --lang/--source-id)",
    )
    parser.add_argument(
        "--rebuild-index",
        action="store_true",
        help="Force rebuild of the lookup index before querying",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Root data directory (default: data)",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)

    if args.list_works:
        entries = list_works(
            data_dir,
            lang=args.lang,
            source_id=args.source_id,
            rebuild_index=args.rebuild_index,
        )
        _print_works_table(entries)
        return

    if not args.query:
        parser.error("-q/--query is required unless --list-works is used")

    if args.list_translations:
        entries = list_translations(
            args.query,
            data_dir,
            rebuild_index=args.rebuild_index,
        )
        if not entries:
            print(f"No works found for query: {args.query!r}", file=sys.stderr)
            sys.exit(1)
        _print_translations_table(entries)
        return

    results = lookup(
        args.query,
        data_dir,
        lang=args.lang,
        source_id=args.source_id,
        rebuild_index=args.rebuild_index,
    )

    if not results:
        print(f"No results found for query: {args.query!r}", file=sys.stderr)
        sys.exit(1)

    print(format_results(results, args.query))


if __name__ == "__main__":
    main()
