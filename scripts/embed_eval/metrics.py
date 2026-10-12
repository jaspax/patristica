"""
Score retrieval runs: rank of the first relevant hit, recall@k and MRR.

Results are grouped by (mode, target language, origin), so a weakness in one
language cannot hide behind a good average.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence

KS: tuple[int, ...] = (1, 3, 10, 50, 100)


def first_rank(hits: Sequence[str], relevant: Iterable[str]) -> int | None:
    """1-based rank of the first relevant id in *hits*, or None if absent."""
    rel = set(relevant)
    return next((i for i, h in enumerate(hits, start=1) if h in rel), None)


def summarize(ranks: Sequence[int | None], ks: Sequence[int] = KS) -> dict[str, float]:
    n = len(ranks)
    if n == 0:
        return {"n": 0}
    out: dict[str, float] = {"n": n}
    for k in ks:
        out[f"R@{k}"] = sum(1 for r in ranks if r is not None and r <= k) / n
    out["MRR"] = sum(1 / r for r in ranks if r is not None) / n
    return out


def breakdown(
    rows: Iterable[tuple[tuple[str, ...], int | None]], ks: Sequence[int] = KS
) -> dict[tuple[str, ...], dict[str, float]]:
    """Summarize ``(group_key, rank)`` rows per group key."""
    groups: dict[tuple[str, ...], list[int | None]] = defaultdict(list)
    for key, rank in rows:
        groups[key].append(rank)
    return {key: summarize(ranks, ks) for key, ranks in sorted(groups.items())}


def markdown_table(summary: dict[tuple[str, ...], dict[str, float]], header: Sequence[str]) -> str:
    ks = [c for c in next(iter(summary.values()), {}) if c != "n"] if summary else []
    lines = [
        "| " + " | ".join([*header, "n", *ks]) + " |",
        "|" + "---|" * (len(header) + 1 + len(ks)),
    ]
    for key, s in summary.items():
        vals = [f"{s[c]:.2f}" for c in ks]
        lines.append("| " + " | ".join([*key, str(s["n"]), *vals]) + " |")
    return "\n".join(lines)
