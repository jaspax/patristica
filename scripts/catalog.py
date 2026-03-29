"""
Print a table of ingestion status across all sources.

Usage
-----
    python -m scripts.catalog
    python -m scripts.catalog --data-dir data
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def count_files(directory: Path, suffix: str = ".json") -> dict[str, int]:
    """Return {source_id: file_count} for *directory*.

    Assumes the layout: ``{directory}/{source_id}/*.{suffix}``
    """
    counts: dict[str, int] = {}
    if not directory.exists():
        return counts
    for child in sorted(directory.iterdir()):
        if child.is_dir():
            # source_id may be two-level (e.g. "patristic/pta") stored as "patristic__pta"
            # or as nested dirs "patristic/pta/"
            source_id = child.name
            n = sum(1 for f in child.rglob(f"*{suffix}") if f.is_file())
            if n:
                counts[source_id] = n
    return counts


def build_catalog(data_dir: Path) -> list[dict]:
    """Build catalog rows by cross-referencing raw/ and normalized/."""
    raw_counts = count_files(data_dir / "raw")
    norm_counts = count_files(data_dir / "normalized", suffix=".json")

    # Union of all known source IDs
    all_ids = sorted(set(raw_counts) | set(norm_counts))

    rows = []
    for src_id in all_ids:
        raw_n = raw_counts.get(src_id, 0)
        norm_n = norm_counts.get(src_id, 0)
        if norm_n > 0:
            status = "normalized"
        elif raw_n > 0:
            status = "raw"
        else:
            status = "empty"
        rows.append({"source_id": src_id, "raw": raw_n, "normalized": norm_n, "status": status})

    return rows


def print_table(rows: list[dict]) -> None:
    if not rows:
        print("No ingested data found.")
        return

    # Column widths
    id_w = max(len(r["source_id"]) for r in rows)
    id_w = max(id_w, len("source_id"))
    header = f"{'source_id':<{id_w}}  {'raw':>6}  {'normalized':>10}  status"
    print(header)
    print("-" * len(header))
    for r in rows:
        print(
            f"{r['source_id']:<{id_w}}  {r['raw']:>6}  {r['normalized']:>10}  {r['status']}"
        )
    print("-" * len(header))
    total_raw = sum(r["raw"] for r in rows)
    total_norm = sum(r["normalized"] for r in rows)
    print(f"{'TOTAL':<{id_w}}  {total_raw:>6}  {total_norm:>10}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Print Patristica ingestion status.")
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Root data directory (default: data)",
    )
    args = parser.parse_args()

    rows = build_catalog(Path(args.data_dir))
    print_table(rows)


if __name__ == "__main__":
    main()
