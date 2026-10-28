"""EXPERIMENTAL: evaluate the #304 refinement on #303's measurement pairs.

Compares three cuts of each translation against its original's derived
verses: **today** (independent per-language cuts), **#303** (the length-only
projection of draft PR #303, imported from a scratch copy of its branch with
``--pr303-dir``) and **refined** (``prototypes.anchored_verses.refine``).

Every cut is aligned with the original by the passage aligner (#179,
``align_pair``, default parameters), and the report gives per cut: units,
the share of original units in a confident (≥ 0.5) 1:1 bead, the mean margin
of those beads, the share of original units in any confident bead, and where
the internal cuts fall (sentence / clause / comma / word). With ``--sample N``
it writes, per pair, N random original units with the row each cut gives them
(``data/eval/anchor-refine/sample-*.txt``) for the hand check of #303
("is the row exactly 1:1 and right?").

Vectors: the original's and today's units come from ``data/embeddings``
(free). Segments, refined units and #303's units are embedded with Voyage
into a scratch cache (``data/eval/anchor-refine/cache.npz``, gitignored),
only with ``--pay`` and within ``--budget-usd``. Never writes
``data/embeddings`` or ``data/normalized``.

    uv run --extra embed python -m prototypes.anchored_verses.evaluate --dry-run
    uv run --extra embed python -m prototypes.anchored_verses.evaluate --pay \\
        --pr303-dir data/eval/anchor-refine/pr303 --sample 20
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import random
import sys
import time
from collections.abc import Sequence
from pathlib import Path

import numpy as np

from patristica import translations as tr
from patristica.alignment import Bead, align_pair
from patristica.versify import CLAUSE, COMMA, SENTENCE, _strength, count_tokens

from .refine import (
    RefineParams,
    Units,
    VectorCache,
    _normalize,
    load_units,
    paragraphs_of,
    refine,
    refined_units,
    work_paths,
)

log = logging.getLogger(__name__)

SCRATCH = Path("data/eval/anchor-refine")
PRICE_PER_M = 0.12  # USD per million Voyage tokens (voyage-4-large)
#: Voyage counts rare scripts at up to ~2x cl100k (``embedders.VoyageEmbedder``).
VOYAGE_FACTOR = {"hye": 2.0, "syc": 2.0, "cop": 2.0, "gez": 2.0}

PAIRS: tuple[tuple[str, str, str], ...] = (
    ("basil", "perseus/tlg2040/tlg004/perseus-grc2", "npnf-works/basil-letters"),
    ("tractates", "oglt-pl/augustinus/pl35_3_s.", "npnf-works/augustine-tractates-on-john"),
    ("severian014", "pta/pta0001/pta014/pta-grc1", "pta/pta0001/pta014/pta-xcl1"),
    ("severian031", "pta/pta0001/pta031/pta-grc1", "pta/pta0001/pta031/pta-xcl1"),
)


# ------------------------------------------------------------------ metrics


def metrics(beads: Sequence[Bead], n_orig: int, units: Units) -> dict[str, float]:
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
    counts = {"sentence": 0, "clause": 0, "comma": 0, "word": 0}
    paras = paragraphs_of(units)
    for para in paras:
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


# ------------------------------------------------------------------- #303


def pr303_units(pr303_dir: Path, orig: Units, today: Units) -> Units:
    """The translation cut by #303's length projection (its ``project``)."""
    sys.path.insert(0, str(pr303_dir.resolve()))
    anchoring = importlib.import_module("anchoring303")
    anchor = anchoring.Anchor(orig.work_id, orig.language,
                              tuple(zip(orig.refs, orig.texts)))
    paras = paragraphs_of(today)
    texts = ["".join(p.atoms).strip() for p in paras]
    proj = anchoring.project(anchor.paragraphs(), anchor.language, texts, today.language)
    refs, out = [], []
    for para, units in zip(paras, proj.units):
        for n, t in enumerate(units, start=1):
            refs.append(para.ref if len(units) == 1 else f"{para.ref}.s{n}")
            out.append(t)
    log.info("#303: sentence agreement %.2f, %d of %d boundaries projected",
             proj.sentence_agreement, len(proj.boundary), len(orig.texts) - 1)
    return Units(today.work_id, today.language, refs, out,
                 np.zeros((len(out), orig.vecs.shape[1]), dtype=np.float32))


def with_vectors(units: Units, cache: VectorCache) -> Units:
    cache.ensure(units.texts)
    vecs = np.stack([cache.get(t) for t in units.texts]).astype(np.float32)
    return Units(units.work_id, units.language, units.refs, units.texts, _normalize(vecs))


# ------------------------------------------------------------------ samples


def english_of(trans_id: str) -> dict[str, str]:
    """Machine translations of today's units (rare languages), by ref."""
    path = work_paths()[trans_id]
    t = tr.load(tr.DEFAULT_DIR, path)
    if t is None:
        return {}
    return {cid.split("#", 1)[1]: row.text for cid, row in t.by_chunk().items()}


def overlap_english(text_units: Units, today: Units, english: dict[str, str],
                    u0: int, u1: int) -> str:
    """For a run of units of a cut, the English of today's units it overlaps."""
    if not english:
        return ""
    # character spans per paragraph for both cuts
    def spans(units: Units) -> list[tuple[str, int, int]]:
        out = []
        paras = paragraphs_of(units)
        u = 0
        for para in paras:
            bounds = [*para.today, len(para.atoms)]
            for a0, a1 in zip(bounds, bounds[1:]):
                c0 = len("".join(para.atoms[:a0]))
                c1 = len("".join(para.atoms[:a1]))
                out.append((para.ref, c0, c1))
                u += 1
        return out
    mine = spans(text_units)[u0:u1]
    theirs = spans(today)
    lines = []
    for t, (ref, c0, c1) in enumerate(theirs):
        for pref, m0, m1 in mine:
            if pref == ref and c0 < m1 and m0 < c1:
                share = (min(c1, m1) - max(c0, m0)) / max(c1 - c0, 1)
                eng = english.get(today.refs[t], "?")
                lines.append(f"      [{today.refs[t]} {share:.0%}] {eng}")
                break
    return "\n".join(lines)


def write_sample(path: Path, orig: Units, cuts: dict[str, tuple[Units, list[Bead]]],
                 today: Units, english: dict[str, str], n: int, seed: int) -> None:
    ks = sorted(random.Random(seed).sample(range(len(orig.texts)), n))
    out = []
    for k in ks:
        out.append(f"=== original unit {k}: {orig.refs[k]}\n  {orig.texts[k]}")
        for name, (units, beads) in cuts.items():
            bd = bead_of(beads, k)
            if bd is None:
                out.append(f"  --- {name}: (no bead)")
                continue
            shape = f"{bd.j1 - bd.j0} orig : {bd.i1 - bd.i0} trans, conf {bd.conf}"
            out.append(f"  --- {name}: {shape}; original units {bd.j0}..{bd.j1 - 1}")
            for u in range(bd.i0, bd.i1):
                out.append(f"    [{units.refs[u]}] {units.texts[u]}")
            eng = overlap_english(units, today, english, bd.i0, bd.i1)
            if eng:
                out.append("    English of today's overlapping units:\n" + eng)
        out.append("")
    path.write_text("\n".join(out), encoding="utf-8")


# --------------------------------------------------------------------- main


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pair", action="append", help="name of a pair (default: all)")
    ap.add_argument("--pay", action="store_true", help="embed with Voyage (scratch cache)")
    ap.add_argument("--dry-run", action="store_true", help="estimate the segment cost only")
    ap.add_argument("--budget-usd", type=float, default=1.9)
    ap.add_argument("--pr303-dir", type=Path)
    ap.add_argument("--sample", type=int, default=0)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--env-file", type=Path, default=Path(".env"),
                    help="where to read VOYAGE_API_KEY from, if not in the environment")
    ap.add_argument("--tag", default="",
                    help="scratch file suffix (cache, spend log), for runs in parallel")
    ap.add_argument("--max-rounds", type=int, default=RefineParams.max_rounds)
    args = ap.parse_args()

    suffix = f"-{args.tag}" if args.tag else ""
    spent_path = SCRATCH / f"spent{suffix}.json"
    spent = json.loads(spent_path.read_text()) if spent_path.exists() else {"voyage_tokens": 0}
    # The budget covers every run so far (all spend logs).
    total = sum(json.loads(f.read_text())["voyage_tokens"] for f in SCRATCH.glob("spent*.json"))
    budget_tokens = int(args.budget_usd / PRICE_PER_M * 1e6) - total
    embedder = None
    if args.pay:
        from patristica.embedders import VoyageEmbedder, env_key
        os.environ.setdefault("VOYAGE_API_KEY", env_key("VOYAGE_API_KEY", args.env_file))
        embedder = VoyageEmbedder()

    rows = []
    for name, orig_id, trans_id in PAIRS:
        if args.pair and name not in args.pair:
            continue
        orig = load_units(orig_id)
        today = load_units(trans_id)  # native text vectors, even for rare languages
        factor = VOYAGE_FACTOR.get(today.language, 1.0)
        def embed(texts: list[str]) -> np.ndarray:
            """Embed, and log the billed tokens at once (a killed run keeps its count)."""
            assert embedder is not None
            vecs = embedder.embed_documents(texts)
            spent["voyage_tokens"] += embedder.tokens_used
            embedder.tokens_used = 0
            spent_path.parent.mkdir(parents=True, exist_ok=True)
            spent_path.write_text(json.dumps(spent))
            return vecs

        cache = VectorCache(SCRATCH / f"cache{suffix}.npz",
                            embed if embedder else None,
                            int(budget_tokens / factor),
                            count_tokens)
        if args.dry_run:
            from .refine import segments_of
            paras = paragraphs_of(today)
            segs = segments_of(paras, today.language)
            cache.seed(today.texts, today.vecs)
            est = cache.estimate([s.text for s in segs]) * factor
            print(f"{name}: {len(segs):,} segments, ~{est:,.0f} Voyage tokens "
                  f"(${est * PRICE_PER_M / 1e6:.3f}) for segments; refined units ≤ the same "
                  f"again; #303 units ≤ {sum(count_tokens(t) for t in today.texts) * factor:,.0f}")
            continue
        started = time.monotonic()
        result, paras, segs, calib, today_beads = refine(
            orig, today, cache, RefineParams(max_rounds=args.max_rounds))
        refined = refined_units(today, result, paras, cache)
        if not result.converged:
            refined = with_vectors(refined, cache)
        seconds = time.monotonic() - started
        cuts: dict[str, tuple[Units, list[Bead]]] = {"today": (today, today_beads)}
        if args.pr303_dir:
            p3 = with_vectors(pr303_units(args.pr303_dir, orig, today), cache)
            cuts["#303"] = (p3, align_pair(p3.version(), orig.version()))
        cuts["refined"] = (refined, align_pair(refined.version(), orig.version()))
        today_set = set(today.texts)
        row = {"pair": name, "langs": f"{orig.language}→{today.language}",
               "orig_units": len(orig.texts), "segments": len(segs),
               "rounds": result.rounds, "converged": result.converged,
               "history": result.log,
               "calibration": [round(calib.a, 3), round(calib.b, 3)],
               "fallback_paragraphs": len(result.fallback_paragraphs),
               "paragraphs": len(paras),
               "changed_units": sum(t not in today_set for t in refined.texts),
               "seconds": round(seconds, 1)}
        for cname, (units, beads) in cuts.items():
            row[cname] = metrics(beads, len(orig.texts), units)
        rows.append(row)
        print(json.dumps(row, indent=1), flush=True)
        if args.sample:
            english = english_of(trans_id) if today.language in tr.TRANSLATED_LANGUAGES else {}
            write_sample(SCRATCH / f"sample-{name}.txt", orig, cuts, today, english,
                         args.sample, args.seed)
        if embedder is not None:
            log.info("Voyage tokens billed so far: %s ($%.3f)", f"{spent['voyage_tokens']:,}",
                     spent["voyage_tokens"] * PRICE_PER_M / 1e6)
    if rows:
        (SCRATCH / "results.json").write_text(json.dumps(rows, indent=1))


if __name__ == "__main__":
    main()
