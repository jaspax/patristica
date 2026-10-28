"""
Evaluate anchored derived verses (#304) on existing version groups; writes no
tracked data.

For each pair (original, translation) it refines the translation's current
cut on the original (``patristica.anchor_refine``, as ``scripts.anchor`` does)
and compares **today**'s cut with the **refined** one. Both are aligned with
the original by the passage aligner (#179, ``align_pair``, default parameters,
text vectors on both sides), and the report gives per cut: units, the share of
original units in a confident (≥ 0.5) 1:1 bead, the mean margin of those
beads, the share of original units in any confident bead, and where the
internal cuts fall (sentence / clause / comma / word). With ``--sample N`` it
writes, per pair, N random original units with the row each cut gives them
(``data/eval/anchor-refine/sample-*.txt``) for the hand check ("is the row
exactly 1:1 and right?"); for a rare-language translation it adds the English
machine translations of today's units the row overlaps.

The design's numbers (``docs/anchored-derived-verses.md`` §8) come from the
prototype this replaced, which also compared #303's length projection.

Vectors: the original's and today's units come from ``data/embeddings``
(free). Segments and refined units are embedded with Voyage into a scratch
store (``data/eval/anchor-refine/``, gitignored), only with ``--pay`` and
within ``--budget-usd``. Never writes ``data/embeddings``, ``data/normalized``
or ``data/anchors``. Agents run ``--pay`` only with the owner's permission.

    uv run --extra embed python -m scripts.anchor_eval --dry-run
    uv run --extra embed python -m scripts.anchor_eval --pay --sample 20 [--pair basil]
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import time
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from patristica import anchoring
from patristica import translations as tr
from patristica.corpus import load_works
from patristica.versify import CLAUSE, COMMA, SENTENCE, _strength, count_tokens
from scripts import anchor

if TYPE_CHECKING:
    from patristica.alignment import Bead
    from patristica.anchor_refine import Units

log = logging.getLogger(__name__)

SCRATCH = Path("data/eval/anchor-refine")

#: The measurement pairs of #292/#304: (name, original, translation).
PAIRS: tuple[tuple[str, str, str], ...] = (
    ("basil", "perseus/tlg2040/tlg004/perseus-grc2", "npnf-works/basil-letters"),
    ("tractates", "oglt-pl/augustinus/pl35_3_s.", "npnf-works/augustine-tractates-on-john"),
    ("severian014", "pta/pta0001/pta014/pta-grc1", "pta/pta0001/pta014/pta-xcl1"),
    ("severian031", "pta/pta0001/pta031/pta-grc1", "pta/pta0001/pta031/pta-xcl1"),
)


# ------------------------------------------------------------------ metrics


def metrics(beads: Sequence[Bead], n_orig: int, units: Units) -> dict[str, float]:
    import numpy as np

    one = [bd for bd in beads if bd.i1 - bd.i0 == 1 and bd.j1 - bd.j0 == 1 and bd.conf >= 0.5]
    covered = sum(bd.j1 - bd.j0 for bd in beads if bd.conf >= 0.5)
    return {
        "units": len(units.texts),
        "one_one": len(one) / n_orig,
        "one_one_margin": float(np.mean([bd.margin for bd in one])) if one else 0.0,
        "covered": covered / n_orig,
        **cut_kinds(units),
    }


def cut_kinds(units: Units) -> dict[str, float]:
    """Where a paragraph's internal cuts fall: the strength of the word before."""
    from patristica.anchor_refine import paragraphs_of

    counts = {"sentence": 0, "clause": 0, "comma": 0, "word": 0}
    for para in paragraphs_of(units):
        for a in para.today[1:]:
            st = _strength(para.atoms[a - 1], para.atoms[a], units.language)
            key = {SENTENCE: "sentence", CLAUSE: "clause", COMMA: "comma"}.get(st, "word")
            counts[key] += 1
    total = max(sum(counts.values()), 1)
    return {f"cut_{k}": v / total for k, v in counts.items()}


def bead_of(beads: Sequence[Bead], k: int) -> Bead | None:
    for bd in beads:
        if bd.j0 <= k < bd.j1:
            return bd
    return None


# ------------------------------------------------------------------ samples


def english_of(path: str) -> dict[str, str]:
    """Machine translations of today's units (rare languages), by ref."""
    t = tr.load(tr.DEFAULT_DIR, path)
    if t is None:
        return {}
    return {cid.split("#", 1)[1]: row.text for cid, row in t.by_chunk().items()}


def _spans(units: Units) -> list[tuple[str, int, int]]:
    from patristica.anchor_refine import paragraphs_of

    out = []
    for para in paragraphs_of(units):
        bounds = [*para.today, len(para.atoms)]
        for a0, a1 in zip(bounds, bounds[1:]):
            out.append((para.ref, len("".join(para.atoms[:a0])), len("".join(para.atoms[:a1]))))
    return out


def overlap_english(cut: Units, today: Units, english: dict[str, str], u0: int, u1: int) -> str:
    """For units [u0, u1) of a cut, the English of today's units they overlap."""
    if not english:
        return ""
    mine = _spans(cut)[u0:u1]
    lines = []
    for t, (ref, c0, c1) in enumerate(_spans(today)):
        for pref, m0, m1 in mine:
            if pref == ref and c0 < m1 and m0 < c1:
                share = (min(c1, m1) - max(c0, m0)) / max(c1 - c0, 1)
                eng = english.get(today.refs[t], "?")
                lines.append(f"      [{today.refs[t]} {share:.0%}] {eng}")
                break
    return "\n".join(lines)


def write_sample(path: Path, orig: Units, cuts: dict[str, tuple[Units, list[Bead]]],
                 today: Units, english: dict[str, str], n: int, seed: int) -> None:
    ks = sorted(random.Random(seed).sample(range(len(orig.texts)), min(n, len(orig.texts))))
    out = []
    for k in ks:
        out.append(f"=== original unit {k}: {orig.refs[k]}\n  {orig.texts[k]}")
        for name, (units, beads) in cuts.items():
            bd = bead_of(beads, k)
            if bd is None:
                out.append(f"  --- {name}: (no bead)")
                continue
            out.append(f"  --- {name}: {bd.j1 - bd.j0} orig : {bd.i1 - bd.i0} trans, "
                       f"conf {bd.conf}; original units {bd.j0}..{bd.j1 - 1}")
            for u in range(bd.i0, bd.i1):
                out.append(f"    [{units.refs[u]}] {units.texts[u]}")
            eng = overlap_english(units, today, english, bd.i0, bd.i1)
            if eng:
                out.append("    English of today's overlapping units:\n" + eng)
        out.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(out), encoding="utf-8")


# --------------------------------------------------------------------- main


def refined_units(today: Units, result, cache) -> Units:
    """The refined cut as ``Units`` (refs ``para.sN``; vectors from the cache)."""
    import numpy as np

    from patristica.anchor_refine import Units, normalize_rows

    refs = []
    for p, ps in enumerate(result.pieces):
        for n in range(1, len(ps) + 1):
            refs.append(result.paras[p].ref if len(ps) == 1 else f"{result.paras[p].ref}.s{n}")
    texts, keys = result.texts(), result.embed_texts()
    cache.ensure([t for t in keys if anchor.wants_vector(t)])
    vecs = np.zeros((len(texts), anchor.DIMS), dtype=np.float32)
    for u, t in enumerate(keys):
        v = cache.get(t) if t.strip() else None
        if v is not None:
            vecs[u] = v
    return Units(today.work_id, today.language, refs, texts, normalize_rows(vecs))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pair", action="append", help="name of a pair (default: all)")
    ap.add_argument("--pay", action="store_true", help="embed with Voyage (scratch store)")
    ap.add_argument("--dry-run", action="store_true", help="estimate the first embed only")
    ap.add_argument("--budget-usd", type=float, default=1.0)
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--max-rounds", type=int, default=anchoring.RefineParams.max_rounds)
    ap.add_argument("--scratch-dir", type=Path, default=SCRATCH)
    args = ap.parse_args()

    import numpy as np

    from patristica.alignment import align_pair
    from patristica.anchor_refine import Units, first_texts, refine

    norm, store = anchor.NORMALIZED, anchor.EMBEDDINGS
    paths = {e["work"]["work_id"]: e["path"] for e in load_works(norm)}
    embedder = None
    if args.pay:
        from patristica.embedders import VoyageEmbedder

        embedder = VoyageEmbedder(anchor.MODEL, anchor.DIMS)
    budget = int(args.budget_usd / anchor.PRICE_PER_MTOK * 1e6)  # for all pairs together
    spent = 0
    rows = []
    for name, orig_id, trans_id in PAIRS:
        if args.pair and name not in args.pair:
            continue
        language = json.loads((norm / paths[trans_id]).read_text(encoding="utf-8"))[0]["language"]
        c = anchor.Candidate(paths[trans_id], trans_id, language, orig_id, paths[orig_id])
        orig, missing, _ = anchor.load_original(c, norm, store)
        cache = anchor.make_cache(c, args.scratch_dir, embedder.embed_documents if embedder
                                  else None, budget - spent)
        today = anchor.load_translation(c, norm, store, cache)
        if args.dry_run:
            est = cache.estimate(first_texts(today, language))
            usd = est * anchor.PRICE_PER_MTOK / 1e6
            print(f"{name}: first embed ~{est:,} tokens (${usd:.3f}); "
                  f"rounds ≤ ~{anchor.ROUNDS_FACTOR:.0f}× the text "
                  f"({sum(count_tokens(t) for t in today.texts):,} tokens); "
                  f"{missing} original units without a vector")
            continue
        started = time.monotonic()
        try:
            result = refine(orig, today, cache,
                            anchoring.RefineParams(max_rounds=args.max_rounds))
            refined = refined_units(today, result, cache)
        finally:
            spent += cache.sent_tokens
        seconds = time.monotonic() - started
        tvecs = np.zeros((len(today.texts), anchor.DIMS), dtype=np.float32)
        for u, t in enumerate(today.source_texts()):
            v = cache.get(t) if t.strip() else None
            if v is not None:
                tvecs[u] = v
        today = Units(today.work_id, today.language, today.refs, today.texts, tvecs,
                      today.spans)
        cuts = {"today": (today, align_pair(today.version(), orig.version())),
                "refined": (refined, align_pair(refined.version(), orig.version()))}
        today_set = set(today.texts)
        row = {"pair": name, "langs": f"{orig.language}→{today.language}",
               "orig_units": len(orig.texts), "rounds": result.rounds,
               "converged": result.converged, "history": result.history,
               "calibration": [round(result.calibration.a, 3), round(result.calibration.b, 3)],
               "fallback_paragraphs": len(result.fallback_paragraphs),
               "paragraphs": len(result.paras),
               "changed_units": sum(t not in today_set for t in refined.texts),
               "seconds": round(seconds, 1)}
        for cname, (units, beads) in cuts.items():
            row[cname] = metrics(beads, len(orig.texts), units)
        rows.append(row)
        print(json.dumps(row, indent=1), flush=True)
        if args.sample:
            english = english_of(c.path) if language in tr.TRANSLATED_LANGUAGES else {}
            write_sample(args.scratch_dir / f"sample-{name}.txt", orig, cuts, today, english,
                         args.sample, args.seed)
    if embedder is not None:
        log.info("Voyage tokens billed: %s (~$%.3f)", f"{embedder.tokens_used:,}",
                 embedder.tokens_used * anchor.PRICE_PER_MTOK / 1e6)
    if rows:
        args.scratch_dir.mkdir(parents=True, exist_ok=True)
        (args.scratch_dir / "results.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
