"""
Evaluate the passage aligner (#179) on Scripture, where versification gives
the answer, and print samples of other works for checking by hand.

``scripripture`` (default): align every Scripture book group as
``scripts.align`` does, but with the refs hidden (no prior), and score the
alignment groups against the versification groups (``translation_group_id``):
pairwise precision and recall per language pair, over all groups and over
the groups at ``MIN_CONFIDENCE``. ``--prior`` uses the production prior
instead. ``--calibrate`` fits ``alignment.CONFIDENCE_FIT`` to the beads.

``neighbours``: the measure of #186. For every unit of a Scripture version
other than the KJV, is a KJV verse next to the ones it is grouped with
clearly closer (cosine + 0.05) than the closest of those? Rare languages are
compared through their English translations. Reported for the versification
groups ("before") and for the alignment groups with the prior ("after").

``sample``: align the given version group and print a random sample of
alignment groups with their text, for checking by hand.

Usage::

    uv run --extra embed python -m scripts.align_eval scripture [--book prov] [--prior]
        [--calibrate] --embeddings-dir data/embeddings
    uv run --extra embed python -m scripts.align_eval neighbours [--book prov]
    uv run --extra embed python -m scripts.align_eval sample --group GROUP [--n 40]
"""

from __future__ import annotations

import argparse
import json
import logging
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path

from tqdm import tqdm

from patristica import translations as tr
from patristica.alignment import CONFIDENCE_FIT, Version, align_pair, choose_pivot, merge, span_fit
from patristica.alignment_store import MIN_CONFIDENCE
from scripts.align import (
    SCRIPTURE_PRIOR,
    Loaded,
    load_member,
    make_pool,
    params_for,
    version_groups,
)
from scripts.embed import load_works, select

log = logging.getLogger(__name__)
CALIBRATION_AGREEMENT = 0.9
NEAR = 0.05  # #186: a neighbour this much closer marks a verse as misaligned


@dataclass
class Score:
    tp: Counter = field(default_factory=Counter)  # language pair → true pairs predicted
    pred: Counter = field(default_factory=Counter)
    truth: Counter = field(default_factory=Counter)
    tp_conf: Counter = field(default_factory=Counter)
    pred_conf: Counter = field(default_factory=Counter)
    units: Counter = field(default_factory=Counter)  # language → units with a ref key
    units_conf: Counter = field(default_factory=Counter)  # … in a confident group
    calib: list[tuple[str, float, int]] = field(default_factory=list)  # (work, margin, right)

    def add(self, other: Score) -> None:
        for name in ("tp", "pred", "truth", "tp_conf", "pred_conf", "units", "units_conf"):
            getattr(self, name).update(getattr(other, name))
        self.calib += other.calib


def _pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def load_group(group: str, entries: list[dict], args: argparse.Namespace) -> list[Loaded]:
    return [m for e in entries
            if (m := load_member(e, args.input_dir, args.translations_dir, args.embeddings_dir,
                                 True))]


def score_group(job: tuple[str, list[dict], argparse.Namespace]) -> Score:
    group, entries, args = job
    members = [m for m in load_group(group, entries, args) if m.keys is not None]
    sc = Score()
    if len(members) < 2:
        return sc
    p = params_for(group) if args.prior else replace(params_for(group), prior=0.0)
    by_id = {m.work_id: m for m in members}
    lang = {m.work_id: m.language for m in members}
    pivot = choose_pivot({m.work_id: (m.language, m.vectored) for m in members})
    pv = by_id[pivot]
    hidden = (lambda m: None) if not args.prior else (lambda m: m.keys)
    pairs = {}
    for m in members:
        if m.work_id == pivot:
            continue
        beads = align_pair(Version(m.work_id, m.vecs, hidden(m)), Version(pivot, pv.vecs,
                                                                        hidden(pv)), p)
        pairs[m.work_id] = (m.units, beads)
        for bd in beads:
            ka = {int(k) for k in m.keys[bd.i0:bd.i1] if k >= 0}
            kb = {int(k) for k in pv.keys[bd.j0:bd.j1] if k >= 0}
            small = ka if len(ka) <= len(kb) else kb
            sc.calib.append((m.work_id, bd.margin, int(bool(small) and small <= (ka & kb))))
    merged = merge(pivot, pv.units, pairs, span_fit({m.work_id: m.vecs for m in members}, pv.vecs))
    # truth: units with equal keys, across works
    by_key: dict[int, Counter] = defaultdict(Counter)
    for m in members:
        for k in m.keys:
            if k >= 0:
                by_key[int(k)][m.work_id] += 1
                sc.units[m.language] += 1
    for cnt in by_key.values():
        ws = sorted(cnt)
        for x in range(len(ws)):
            for y in range(x + 1, len(ws)):
                sc.truth[_pair(lang[ws[x]], lang[ws[y]])] += cnt[ws[x]] * cnt[ws[y]]
    # predicted: units in one alignment group, across works
    spans: dict[int, dict[str, tuple[int, int]]] = defaultdict(dict)
    for wid in merged.group_of:
        for g, span in merged.spans(wid).items():
            spans[g][wid] = span
    for g, mem in spans.items():
        ws = sorted(mem)
        keys = {w: Counter(int(k) for k in by_id[w].keys[mem[w][0]:mem[w][1]] if k >= 0)
                for w in ws}
        conf = {w: merged.conf[w].get(g, 0.0) for w in ws}
        confident = {w for w in ws if w != pivot and conf[w] * 10 >= MIN_CONFIDENCE}
        if confident:
            confident.add(pivot)
        for w in confident if len(confident) >= 2 else ():
            sc.units_conf[lang[w]] += sum(keys[w].values())
        for x in range(len(ws)):
            for y in range(x + 1, len(ws)):
                a, b = ws[x], ws[y]
                lp = _pair(lang[a], lang[b])
                n = sum(keys[a].values()) * sum(keys[b].values())
                t = sum(c * keys[b][k] for k, c in keys[a].items())
                sc.pred[lp] += n
                sc.tp[lp] += t
                if a in confident and b in confident:
                    sc.pred_conf[lp] += n
                    sc.tp_conf[lp] += t
    return sc


def fit_logistic(points: list[tuple[float, int]]) -> tuple[float, float]:
    """(margin at 50 %, slope) of a logistic fit, by Newton's method."""
    import numpy as np

    x = np.array([p[0] for p in points])
    y = np.array([p[1] for p in points], dtype=float)
    w = np.array([0.0, 10.0])  # intercept, slope
    for _ in range(50):
        z = w[0] + w[1] * x
        q = 1 / (1 + np.exp(-z))
        g = np.array([(q - y).sum(), ((q - y) * x).sum()])
        h = np.array([[(q * (1 - q)).sum(), (q * (1 - q) * x).sum()],
                      [(q * (1 - q) * x).sum(), (q * (1 - q) * x * x).sum()]])
        w = w - np.linalg.solve(h + 1e-9 * np.eye(2), g)
    return float(-w[0] / w[1]), float(w[1])


def scripture(args: argparse.Namespace) -> None:
    entries, groups = _corpus(args)
    chosen = [g for g in groups if g.startswith("book:")
              and (not args.book or g.split(":", 1)[1] in args.book)]
    jobs = [(g, [entries[w] for w in groups[g] if w in entries], args) for g in chosen]
    total = Score()
    with make_pool(args.jobs) as pool:
        for sc in tqdm(pool.map(score_group, jobs), total=len(jobs), desc="books"):
            total.add(sc)
    mode = f"prior {SCRIPTURE_PRIOR}" if args.prior else "refs hidden"
    print(f"## Scripture, {mode}: {len(jobs)} books\n")
    print("| languages | precision | recall | precision (confident) | recall (confident) |")
    print("|---|---:|---:|---:|---:|")
    for lp in sorted(total.truth):
        def pct(a: int, b: int) -> str:
            return f"{100 * a / b:.1f}%" if b else "–"
        print(f"| {lp[0]}–{lp[1]} | {pct(total.tp[lp], total.pred[lp])} | "
              f"{pct(total.tp[lp], total.truth[lp])} | "
              f"{pct(total.tp_conf[lp], total.pred_conf[lp])} | "
              f"{pct(total.tp_conf[lp], total.truth[lp])} |")
    tp, pred, truth = (sum(c.values()) for c in (total.tp, total.pred, total.truth))
    tpc, predc = sum(total.tp_conf.values()), sum(total.pred_conf.values())
    print(f"| **all** | {100 * tp / pred:.1f}% | {100 * tp / truth:.1f}% | "
          f"{100 * tpc / predc:.1f}% | {100 * tpc / truth:.1f}% |\n")
    print("| language | units | in a confident group |")
    print("|---|---:|---:|")
    for lang in sorted(total.units):
        print(f"| {lang} | {total.units[lang]} | "
              f"{100 * total.units_conf[lang] / total.units[lang]:.1f}% |")
    if args.calibrate:
        # Where a version's refs and content disagree on many beads (Ge'ez
        # Proverbs), the refs are wrong, not the aligner: leave such works out.
        per_work: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for wid, _, ok in total.calib:
            per_work[wid][0] += ok
            per_work[wid][1] += 1
        bad = {w for w, (r, n) in per_work.items() if r < CALIBRATION_AGREEMENT * n}
        points = [(m, ok) for wid, m, ok in total.calib if wid not in bad]
        lo, slope = fit_logistic(points)
        print(f"\nconfidence fit over {len(points)} beads ({len(bad)} works left out, their "
              f"refs disagree with the content on over {100 - 100 * CALIBRATION_AGREEMENT:.0f}% "
              f"of beads: {', '.join(sorted(bad))}): margin at 50 % = {lo:.4f}, "
              f"slope = {slope:.2f} (in use: {CONFIDENCE_FIT})")
        bins = defaultdict(lambda: [0, 0])
        for m, ok in points:
            b = bins[round(min(max(m, -0.1), 0.5) * 20) / 20]
            b[0] += ok
            b[1] += 1
        for b in sorted(bins):
            print(f"  margin {b:+.2f}: {bins[b][0]}/{bins[b][1]} right")


# ------------------------------------------------------------------ neighbours


def _shift(org: str, d: int) -> str | None:
    book, ch, v = org.rsplit(".", 2)
    return f"{book}.{ch}.{int(v) + d}" if v.isdigit() else None


def neighbours_job(job: tuple[str, list[dict], argparse.Namespace]
                   ) -> tuple[Counter, Counter, Counter, Counter]:
    """(units, off) before and after, per source, for one book."""
    import numpy as np

    from patristica.versification import to_org_ref

    group, entries, args = job
    before_n, before_off, after_n, after_off = Counter(), Counter(), Counter(), Counter()
    book = group.split(":", 1)[1]
    members = [m for m in load_group(group, entries, args) if m.keys is not None]
    kjv = next((m for m in members if m.work_id == f"kjv/{book}"), None)
    if kjv is None:
        return before_n, before_off, after_n, after_off
    refs = {m.work_id: [c["canonical_ref"] for c in json.loads(
        (args.input_dir / e["path"]).read_text(encoding="utf-8"))]
        for m in members for e in entries if e["work"]["work_id"] == m.work_id}
    kjv_org = {to_org_ref("kjv", r): u for u, r in enumerate(refs[kjv.work_id])}
    has = np.abs(kjv.vecs).sum(axis=1) > 0
    # before: the versification groups
    for m in members:
        if m.work_id.startswith("kjv/"):
            continue
        source = m.work_id.split("/", 1)[0]
        for u, ref in enumerate(refs[m.work_id]):
            if not np.abs(m.vecs[u]).sum():
                continue
            org = to_org_ref(source, ref)
            k = kjv_org.get(org)
            if k is None or not has[k]:
                continue
            here = float(m.vecs[u] @ kjv.vecs[k])
            near = [float(m.vecs[u] @ kjv.vecs[kjv_org[n]]) for d in (-1, 1)
                    if (n := _shift(org, d)) in kjv_org and has[kjv_org[n]]]
            before_n[source] += 1
            if near and max(near) > here + NEAR:
                before_off[source] += 1
    # after: the alignment groups (production settings)
    from scripts.align import align_group
    a = align_group(group, members, "", "")
    groups = a.groups_of()
    kjv_span = {g: s[kjv.work_id] for g, s in groups.items() if kjv.work_id in s}
    for m in members:
        if m.work_id.startswith("kjv/"):
            continue
        source = m.work_id.split("/", 1)[0]
        for g, spans in groups.items():
            if m.work_id not in spans or g not in kjv_span:
                continue
            s, e = kjv_span[g]
            for u in range(*spans[m.work_id]):
                if not np.abs(m.vecs[u]).sum():
                    continue
                here_c = [float(m.vecs[u] @ kjv.vecs[k]) for k in range(s, e) if has[k]]
                if not here_c:
                    continue
                near = [float(m.vecs[u] @ kjv.vecs[k]) for k in (s - 1, e)
                        if 0 <= k < len(kjv.vecs) and has[k]]
                after_n[source] += 1
                if near and max(near) > max(here_c) + NEAR:
                    after_off[source] += 1
    return before_n, before_off, after_n, after_off


def neighbours(args: argparse.Namespace) -> None:
    entries, groups = _corpus(args)
    chosen = [g for g in groups if g.startswith("book:")
              and (not args.book or g.split(":", 1)[1] in args.book)]
    jobs = [(g, [entries[w] for w in groups[g] if w in entries], args) for g in chosen]
    tot = [Counter() for _ in range(4)]
    with make_pool(args.jobs) as pool:
        for res in tqdm(pool.map(neighbours_job, jobs), total=len(jobs), desc="books"):
            for t, r in zip(tot, res):
                t.update(r)
    bn, bo, an, ao = tot
    print("| source | before: off / units | after: off / units (confident groups) |")
    print("|---|---:|---:|")
    for s in sorted(bn, key=lambda s: -bo[s]):
        print(f"| {s} | {bo[s]} / {bn[s]} ({100 * bo[s] / bn[s]:.2f}%) | "
              f"{ao[s]} / {an[s]} ({100 * ao[s] / max(an[s], 1):.2f}%) |")
    print(f"| **total** | {sum(bo.values())} / {sum(bn.values())} | "
          f"{sum(ao.values())} / {sum(an.values())} |")


# ---------------------------------------------------------------------- sample


def sample(args: argparse.Namespace) -> None:
    from scripts.align import align_group

    entries, groups = _corpus(args)
    if args.group not in groups:  # a work id: its group
        args.group = next(g for g, mem in groups.items() if args.group in mem)
    members_ids = groups[args.group]
    ents = [entries[w] for w in members_ids if w in entries]
    members = [m for e in ents
               if (m := load_member(e, args.input_dir, args.translations_dir,
                                    args.embeddings_dir, False))]
    a = align_group(args.group, members, "", "")
    texts = {e["work"]["work_id"]: json.loads((args.input_dir / e["path"]).read_text(
        encoding="utf-8")) for e in ents}
    print(f"# {args.group}: pivot {a.pivot}, {a.groups} groups")
    for wid, mem in sorted(a.members.items()):
        aligned = sum(1 for g in mem.group_of if g >= 0)
        confident = sum(1 for g in mem.group_of if g >= 0 and mem.conf.get(g, 0) >= MIN_CONFIDENCE)
        print(f"- {wid}: {mem.units} units, {aligned} in a group, {confident} confident")
    rng = random.Random(args.seed)
    gs = sorted(a.groups_of(0))
    for g in sorted(rng.sample(gs, min(args.n, len(gs)))):
        print(f"\n## group {g}")
        for wid, (s, e) in a.groups_of(0)[g].items():
            c = a.members[wid].conf.get(g, 0)
            refs = f"{texts[wid][s]['canonical_ref']}–{texts[wid][e - 1]['canonical_ref']}"
            body = " ".join(t["text"] for t in texts[wid][s:e])
            print(f"[{wid} {refs} conf {c}] {body[:args.chars]}")


def _corpus(args: argparse.Namespace) -> tuple[dict[str, dict], dict[str, tuple[str, ...]]]:
    works = load_works(args.input_dir)
    entries = {e["work"]["work_id"]: e for e in select(works, [], [], include_unpublishable=False)}
    return entries, version_groups(works)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=("scripture", "neighbours", "sample"))
    parser.add_argument("--input-dir", type=Path, default=Path("data/normalized"))
    parser.add_argument("--translations-dir", type=Path, default=tr.DEFAULT_DIR)
    parser.add_argument("--embeddings-dir", type=Path, default=Path("data/embeddings"))
    parser.add_argument("--book", action="append", default=[], help="OSIS book, lower case")
    parser.add_argument("--prior", action="store_true", help="scripture: use the refs")
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--group", help="sample: a version group, or a work id in one")
    parser.add_argument("--n", type=int, default=40)
    parser.add_argument("--seed", type=int, default=179)
    parser.add_argument("--chars", type=int, default=300)
    parser.add_argument("--jobs", type=int, default=6)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING)
    {"scripture": scripture, "neighbours": neighbours, "sample": sample}[args.mode](args)


if __name__ == "__main__":
    main()
