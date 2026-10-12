"""
Compare retrievers: one markdown table per query mode, built from
``data/eval/results/*.json``.

Each mode is scored at its own success threshold (see #3): ``exact`` and
``near`` at R@1, ``paraphrase`` at R@3, ``topical`` at R@100. Rows are
retrievers, columns are target language / origin, cells are the share of
queries that met the threshold.

Usage::

    python -m scripts.embed_eval.report [--scope lang|all] > report.md
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_DIR = Path("data/eval/results")

THRESHOLDS: dict[str, str] = {
    "exact": "R@1", "near": "R@1", "paraphrase": "R@3", "topical": "R@100",
}


def load_results(results_dir: Path) -> list[dict]:
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(results_dir.glob("*.json"))]


def mode_table(results: list[dict], mode: str, scope: str) -> str:
    metric = THRESHOLDS[mode]
    cols: set[tuple[str, str]] = set()
    rows: dict[str, dict[tuple[str, str], tuple[float, int]]] = {}
    for r in results:
        cells = {}
        for s in r["summaries"].get(scope, []):
            if s["mode"] == mode and metric in s:
                key = (s["lang"], s["origin"])
                cells[key] = (s[metric], s["n"])
                cols.add(key)
        if cells:
            rows[r["retriever"]] = cells
    if not rows:
        return f"### {mode}\n\n(no results)\n"
    order = sorted(cols)
    header = ["retriever", *(f"{lang} {'scr' if origin == 'scripture' else 'uniq'}"
                            for lang, origin in order), "mean"]
    lines = [f"### {mode} ({metric}, scope: {scope})", "",
             "| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for name, cells in sorted(rows.items(), key=lambda kv: -_mean(kv[1])):
        vals = [f"{cells[c][0]:.2f}" if c in cells else "–" for c in order]
        lines.append("| " + " | ".join([name, *vals, f"{_mean(cells):.2f}"]) + " |")
    ns = [str(rows[next(iter(rows))].get(c, (0, 0))[1]) for c in order]
    lines.append("| *n* | " + " | ".join(ns) + " | |")
    return "\n".join(lines) + "\n"


def _mean(cells: dict[tuple[str, str], tuple[float, int]]) -> float:
    return sum(v for v, _ in cells.values()) / len(cells) if cells else 0.0


def report(results_dir: Path, scope: str) -> str:
    results = load_results(results_dir)
    return "\n".join(mode_table(results, mode, scope) for mode in THRESHOLDS)


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--results-dir", type=Path, default=DEFAULT_DIR)
    p.add_argument("--scope", choices=("lang", "all"), default="lang")
    args = p.parse_args()
    print(report(args.results_dir, args.scope))


if __name__ == "__main__":
    main()
