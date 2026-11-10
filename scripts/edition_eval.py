"""
Evaluate projecting derived verses between editions of one text (#200); writes
no tracked data.

For each same-language edition that ``scripts.align`` aligned by its text with
another (#199: ``run.text.editions`` in ``data/alignments``), cut it where its
head cuts (``patristica.edition_projection``) and compare today's cut with
the projected one. The judge is #199's text alignment
(``patristica.text_alignment``): the share of the head's units, among those in
a confident bead with the edition, that are in a confident 1:1 bead.

Usage::

    uv run python -m scripts.edition_eval [--work WORK_ID] [--jobs 8]
"""

from __future__ import annotations

import argparse
import json
import logging
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from patristica import alignment_store as store
from patristica import anchoring
from patristica.corpus import load_works

log = logging.getLogger(__name__)


def score(head_units: list[str], units: list[str]) -> tuple[int, int]:
    """(head units in a confident 1:1 bead, head units in any confident bead)."""
    from patristica.text_alignment import align_texts

    r = align_texts(head_units, units)
    one = sum(1 for t in r.beads if t.i1 - t.i0 == 1 and t.j1 - t.j0 == 1 and t.conf >= 0.5)
    return one, sum(t.i1 - t.i0 for t in r.beads if t.conf >= 0.5)


def evaluate(job: tuple[Path, str, str, str, str]) -> dict:
    from patristica.edition_projection import project

    norm, edition, head, ed_path, head_path = job
    load = lambda p: json.loads((norm / p).read_text(encoding="utf-8"))  # noqa: E731
    hp, ep = anchoring.paragraphs(load(head_path)), anchoring.paragraphs(load(ed_path))
    proj = project(hp, ep)
    new: list[str] = []
    for p, st in zip(ep, proj.starts):
        new += list(p.units) if st is None else anchoring.cut_at(" ".join(p.units), st)
    head_units = [u for p in hp for u in p.units]
    (b, cb), (a, ca) = score(head_units, [u for p in ep for u in p.units]), score(head_units, new)
    return {"edition": edition, "head": head, "shared": proj.stats["shared"],
            "units": max(cb, ca), "before": b, "after": a, **proj.stats}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    ap.add_argument("--normalized-dir", type=Path, default=Path("data/normalized"))
    ap.add_argument("--alignments-dir", type=Path, default=store.DEFAULT_DIR)
    ap.add_argument("--work", action="append", default=[])
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--n", type=int, default=10, help="worst pairs to list")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)
    works = {e["work"]["work_id"]: e for e in load_works(args.normalized_dir)}
    jobs = []
    for _, a in store.iter_store(args.alignments_dir):
        for wid, info in a.run.get("text", {}).get("editions", {}).items():
            w = works[wid]["work"]
            if w.get("translation_of") or (args.work and wid not in args.work):
                continue
            jobs.append((args.normalized_dir, wid, info["head"], works[wid]["path"],
                         works[info["head"]]["path"]))
    with ProcessPoolExecutor(args.jobs) as ex:
        rows = list(ex.map(evaluate, jobs))
    units = sum(r["units"] for r in rows) or 1
    print(f"{len(rows)} editions; head units in a confident 1:1 bead, of those the edition "
          f"shares: {sum(r['before'] for r in rows) / units:.1%} -> "
          f"{sum(r['after'] for r in rows) / units:.1%} ({units:,} units)")
    for lo, hi in ((0.0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 1.01)):
        sub = [r for r in rows if lo <= r["shared"] < hi]
        n = sum(r["units"] for r in sub)
        if n:
            before = sum(r["before"] for r in sub) / n
            after = sum(r["after"] for r in sub) / n
            print(f"  shared {lo:.1f}-{min(hi, 1.0):.1f}: {len(sub)} editions, {n:,} units: "
                  f"{before:.1%} -> {after:.1%}; worse in "
                  f"{sum(r['after'] < r['before'] for r in sub)}")
    rows.sort(key=lambda r: (r["after"] - r["before"]) / max(r["units"], 1))
    for r in rows[:args.n]:
        print(f"  {r['edition']} <- {r['head']}: {r['before'] / max(r['units'], 1):.1%} -> "
              f"{r['after'] / max(r['units'], 1):.1%} ({r['units']} units, shared {r['shared']})")


if __name__ == "__main__":
    main()
