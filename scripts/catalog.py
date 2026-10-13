"""
Print a table of ingestion status across all sources.

Shows raw and normalized file counts plus the last time each source was
successfully run (based on the newest .json file's mtime in data/raw/).

Usage
-----
    python -m scripts.catalog
    python -m scripts.catalog --data-dir data
"""

from __future__ import annotations

import argparse
import time
from datetime import datetime
from pathlib import Path


def count_files(directory: Path, suffix: str = ".json") -> dict[str, int]:
    """Return {source_id: file_count} for *directory*.

    Each top-level directory is one source (``data/raw/oshb/`` → source_id
    ``"oshb"``).  Skips ``_zips``, ``_csvs``, and other cache directories, and
    files under ``_``-prefixed subdirectories (``ogpg/_extract``).
    """
    counts: dict[str, int] = {}
    if not directory.exists():
        return counts

    for child in sorted(directory.iterdir()):
        if not child.is_dir() or child.name.startswith("_"):
            continue
        n = sum(
            1
            for f in child.rglob(f"*{suffix}")
            if f.is_file() and not any(p.startswith("_") for p in f.relative_to(child).parts)
        )
        if n:
            counts[child.name] = n

    return counts


def last_run_time(raw_dir: Path, source_id: str) -> datetime | None:
    """Return the mtime of the most recently written .json file for *source_id*.

    Returns None if no files are found.
    """
    source_path = raw_dir / source_id
    if not source_path.exists():
        return None
    json_files = list(source_path.rglob("*.json"))
    if not json_files:
        return None
    newest_mtime = max(f.stat().st_mtime for f in json_files)
    return datetime.fromtimestamp(newest_mtime)


def build_catalog(data_dir: Path) -> list[dict]:
    """Build catalog rows by cross-referencing raw/ and normalized/."""
    raw_dir = data_dir / "raw"
    norm_dir = data_dir / "normalized"

    raw_counts = count_files(raw_dir)
    norm_counts = count_files(norm_dir, suffix=".json")

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

        last_run = last_run_time(raw_dir, src_id)
        rows.append({
            "source_id": src_id,
            "raw": raw_n,
            "normalized": norm_n,
            "status": status,
            "last_run": last_run,
        })

    return rows


def print_table(rows: list[dict]) -> None:
    if not rows:
        print("No ingested data found.")
        return

    id_w = max(len(r["source_id"]) for r in rows)
    id_w = max(id_w, len("source_id"))

    header = (
        f"{'source_id':<{id_w}}  {'raw':>6}  {'normalized':>10}"
        f"  {'status':<10}  last_run"
    )
    sep = "-" * len(header)
    print(header)
    print(sep)

    for r in rows:
        last_run = r.get("last_run")
        last_run_str = (
            last_run.strftime("%Y-%m-%d %H:%M")
            if last_run else "never"
        )
        print(
            f"{r['source_id']:<{id_w}}  {r['raw']:>6}  {r['normalized']:>10}"
            f"  {r['status']:<10}  {last_run_str}"
        )

    print(sep)
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
