"""Passage alignment between the versions of a work (#179).

The works of a version group (``patristica.versions``, #178) are the same
text in different languages or editions. This module aligns their passages:
an *alignment group* is a set of chunk spans, one contiguous run of units per
version (or none), that render the same passage. Scripture's verse groups
(``chunks.translation_group_id``) are the 1:1 case; elsewhere units differ in
size (derived verses, #2, are cut per language) and translators merge, split
and leave out sentences, so groups are n:m.

**Pairwise alignment** (``align_pair``) is a monotonic dynamic program over
the units of two versions, in the style of vecalign/Bleualign. A step (a
*bead*) takes ``a`` units of one version and ``b`` of the other (``BEADS``:
1:1 up to 4 units on one side and 5 in all), or skips one unit of either
side. A bead scores how much the cosine of its two summed vectors
(``patristica.embeddings``: cross-lingual Voyage vectors, the English
translation's vector for Syriac, Coptic, Armenian and Ge'ez) exceeds the
*baseline* of its units (each unit's mean similarity to the other version,
which corrects for units that are close to everything), less ``margin``, per
unit it covers. Skips score 0, so a passage one version lacks is left out
instead of forced, and a short version can align with part of a long one.
``merge_penalty`` is charged for every bead other than 1:1. An optional
``prior`` adds a bonus for every pair of units whose reference keys match: for
Scripture these are versification-mapped refs, so the refs act as soft
anchors that content can overrule.

The program runs in a band around *anchors*: mutual nearest neighbours whose
margin is high, cut down to their longest monotonic chain. Rows between two
anchors may use the columns between the anchors on either side, so a wrong
anchor only widens the band. Small pairs use the full matrix.

**Reordering.** A monotonic alignment cannot follow a block that one version
puts elsewhere (LXX Exodus 35-40, chapters of Ge'ez Proverbs). After the first
pass, the units left unaligned on both sides are aligned again, as two
shorter sequences, for up to ``passes`` passes. A bead from a later pass is
kept only if its units are contiguous in both versions and it is part of a
run of at least ``min_run`` such beads.

**Confidence.** Each bead's confidence comes from its margin (``confidence``),
calibrated on Scripture with the refs hidden (``scripts.align_eval``). A
weak bead between two confident beads, with no gap on either side, takes the
lower of their confidences: monotonicity vouches for it.

**Groups** (``merge``). Every other version is aligned with one *pivot*
version (``choose_pivot``). Pivot units that one bead covers belong to one
group, so the groups are runs of pivot units, and every version's beads are
attached to the group of their pivot units. A version's units in one group
are a contiguous run. The file format is in ``patristica.alignment_store``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

#: Bead shapes (units of A, units of B) besides the two skips.
BEADS: tuple[tuple[int, int], ...] = (
    (1, 1), (1, 2), (2, 1), (1, 3), (3, 1), (2, 2), (1, 4), (4, 1), (2, 3), (3, 2))
MAX_SPAN = max(max(a, b) for a, b in BEADS)
_UP, _LEFT = -1, -2  # back pointers for skipping a unit of A / of B
NEG = -1e18


@dataclass(frozen=True)
class Params:
    """Settings of the aligner. Recorded with every run (``asdict``)."""

    margin: float = 0.05  # cosine above the baseline a bead must reach to score
    merge_penalty: float = 0.06  # per unit a bead has beyond 1:1
    size_weight: float = 0.5  # a bead's gain is weighted by (its units / 2) ** size_weight
    prior: float = 0.0  # bonus per pair of units whose reference keys match
    band: int = 24  # extra columns on each side of the anchor band
    full_cells: int = 4_000_000  # pairs up to this size skip the anchors
    anchor_margin: float = 0.25  # an anchor's cosine above the baseline
    passes: int = 3  # alignment passes (later passes find reordered blocks)
    min_run: int = 3  # beads in a run for a later pass to keep them
    block: int = 1024  # rows per block when computing the full similarity

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


@dataclass
class Version:
    """One version as the aligner sees it: its units' vectors in order.

    ``vecs`` are unit rows; a unit without a vector has a zero row. ``keys``
    are optional reference keys for the prior (−1: none), equal keys meaning
    the refs correspond.
    """

    work_id: str
    vecs: np.ndarray  # float32, units × dims
    keys: np.ndarray | None = None  # int64, one per unit

    def __len__(self) -> int:
        return len(self.vecs)

    def subset(self, idx: np.ndarray) -> Version:
        return Version(self.work_id, self.vecs[idx],
                       None if self.keys is None else self.keys[idx])


@dataclass(frozen=True)
class Bead:
    """Units ``[i0, i1)`` of A and ``[j0, j1)`` of B render the same passage."""

    i0: int
    i1: int
    j0: int
    j1: int
    sim: float  # cosine of the summed vectors
    margin: float  # sim − baseline
    conf: float = 0.0


# --------------------------------------------------------------------- scoring


@dataclass
class _Side:
    """Per-version arrays for scoring windows of up to MAX_SPAN units."""

    vecs: np.ndarray
    has: np.ndarray  # 1.0 where the unit has a vector
    base: np.ndarray  # baseline similarity per unit
    keys: np.ndarray | None
    norm: dict[int, np.ndarray] = field(default_factory=dict)  # a → |Σ window| by end
    count: dict[int, np.ndarray] = field(default_factory=dict)  # a → units with vectors
    base_sum: dict[int, np.ndarray] = field(default_factory=dict)  # a → Σ baseline

    @classmethod
    def build(cls, vecs: np.ndarray, base: np.ndarray, keys: np.ndarray | None) -> _Side:
        n = len(vecs)
        has = (np.abs(vecs).sum(axis=1) > 0).astype(np.float64)
        side = cls(vecs, has, base * has, keys)
        lags = {lag: np.einsum("ij,ij->i", vecs[:-lag], vecs[lag:]).astype(np.float64)
                if n > lag else np.zeros(0) for lag in range(1, MAX_SPAN)}
        c_has = np.concatenate([[0.0], np.cumsum(has)])
        c_base = np.concatenate([[0.0], np.cumsum(side.base)])
        c_lag = {lag: np.concatenate([[0.0], np.cumsum(v)]) for lag, v in lags.items()}
        ends = np.arange(n + 1)
        for a in range(1, MAX_SPAN + 1):
            start = np.maximum(ends - a, 0)
            valid = ends >= a
            sq = c_has[ends] - c_has[start]
            for lag in range(1, a):
                # pairs (k, k+lag) with both in [start, end): k in [start, end-lag)
                hi = np.maximum(ends - lag, start)
                sq = sq + 2 * (c_lag[lag][np.minimum(hi, len(c_lag[lag]) - 1)]
                               - c_lag[lag][np.minimum(start, len(c_lag[lag]) - 1)])
            side.norm[a] = np.where(valid, np.sqrt(np.maximum(sq, 0.0)), 0.0)
            side.count[a] = np.where(valid, c_has[ends] - c_has[start], 0.0)
            side.base_sum[a] = np.where(valid, c_base[ends] - c_base[start], 0.0)
        return side


def similarity_stats(a: np.ndarray, b: np.ndarray, block: int
                     ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray,
                                np.ndarray, np.ndarray]:
    """Row/column means, maxima and argmaxima of ``a @ b.T``, computed in blocks.

    Means are over the units of the other side that have a vector.
    """
    n, m = len(a), len(b)
    has_b = np.abs(b).sum(axis=1) > 0
    has_a = np.abs(a).sum(axis=1) > 0
    nb, na = max(int(has_b.sum()), 1), max(int(has_a.sum()), 1)
    row_mean = np.zeros(n)
    row_max = np.full(n, -np.inf)
    row_arg = np.zeros(n, dtype=np.int64)
    col_sum = np.zeros(m)
    col_max = np.full(m, -np.inf)
    col_arg = np.zeros(m, dtype=np.int64)
    for s in range(0, n, block):
        sim = a[s:s + block] @ b.T
        row_mean[s:s + block] = sim.sum(axis=1) / nb
        sim[:, ~has_b] = -np.inf
        row_arg[s:s + block] = sim.argmax(axis=1)
        row_max[s:s + block] = sim.max(axis=1)
        sim[~has_a[s:s + block]] = -np.inf
        sim_f = np.where(np.isfinite(sim), sim, 0.0)
        col_sum += sim_f.sum(axis=0)
        bm = sim.max(axis=0)
        better = bm > col_max
        col_max[better] = bm[better]
        col_arg[better] = sim.argmax(axis=0)[better] + s
    return row_mean, row_max, row_arg, col_sum / na, col_max, col_arg


def anchor_chain(pairs: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    """The longest chain of *pairs* increasing strictly in both coordinates."""
    pts = sorted(set(pairs), key=lambda p: (p[0], -p[1]))
    tails: list[int] = []  # index into pts of the chain tail of each length
    prev = [-1] * len(pts)
    import bisect
    tail_vals: list[int] = []
    for k, (_, j) in enumerate(pts):
        pos = bisect.bisect_left(tail_vals, j)
        if pos > 0:
            prev[k] = tails[pos - 1]
        if pos == len(tail_vals):
            tail_vals.append(j)
            tails.append(k)
        else:
            tail_vals[pos] = j
            tails[pos] = k
    chain = []
    k = tails[-1] if tails else -1
    while k >= 0:
        chain.append(pts[k])
        k = prev[k]
    return chain[::-1]


def band_from_anchors(n: int, m: int, anchors: Sequence[tuple[int, int]], width: int
                      ) -> tuple[np.ndarray, np.ndarray]:
    """Per DP row ``i`` (0..n), the inclusive column range ``[lo_i, hi_i]``.

    *anchors* are unit pairs ``(p, q)`` in a monotonic chain; a bead through
    them ends at grid cell ``(p + 1, q + 1)``. Rows between two anchors may
    use every column between the anchors before and after them, ± *width*.
    """
    pts = [(0, 0)] + [(p + 1, q + 1) for p, q in anchors] + [(n, m)]
    lo = np.full(n + 1, m, dtype=np.int64)
    hi = np.zeros(n + 1, dtype=np.int64)
    for k in range(len(pts) - 1):
        (i0, j0), (i1, j1) = pts[k], pts[k + 1]
        if k == 0:
            j0 = 0  # before the first anchor anything is possible
        if k == len(pts) - 2:
            j1 = m
        r0, r1 = max(i0 - width, 0), min(i1 + width, n)
        lo[r0:r1 + 1] = np.minimum(lo[r0:r1 + 1], max(j0 - width, 0))
        hi[r0:r1 + 1] = np.maximum(hi[r0:r1 + 1], min(j1 + width, m))
    lo = np.minimum.accumulate(lo[::-1])[::-1]  # non-decreasing from the top
    hi = np.maximum.accumulate(hi)
    lo[0], hi[n] = 0, m
    return lo, hi


def _window_sums(row: np.ndarray, offset: int, js: np.ndarray, b: int) -> np.ndarray:
    """Σ row[q - offset] for q in [j - b, j), for every j in *js* (row starts at column offset)."""
    cs = np.concatenate([[0.0], np.cumsum(row)])
    hi = js - offset
    lo = hi - b
    ok = lo >= 0
    out = np.zeros(len(js))
    out[ok] = cs[hi[ok]] - cs[lo[ok]]
    return out


def _dp(sa: _Side, sb: _Side, p: Params, lo: np.ndarray, hi: np.ndarray,
        full: np.ndarray | None = None) -> list[tuple[int, int, int, int]]:
    """Run the banded program; return the beads (i0, i1, j0, j1) in order.

    *full* is the whole similarity matrix, when it is small enough to keep.
    """
    n, m = len(sa.vecs), len(sb.vecs)
    rows: dict[int, np.ndarray] = {}
    bps: list[np.ndarray] = []
    use_prior = p.prior > 0 and sa.keys is not None and sb.keys is not None
    for i in range(n + 1):
        lo_i, h = int(lo[i]), int(hi[i])
        js = np.arange(lo_i, h + 1)
        best = np.full(len(js), NEG)
        bp = np.full(len(js), _LEFT, dtype=np.int8)
        if i == 0:
            best[js == 0] = 0.0
        else:
            prev = _fetch(rows, lo, i - 1, js)
            best = np.maximum(best, prev)
            bp[prev >= best] = _UP
            p0 = max(i - MAX_SPAN, 0)
            q0 = max(lo_i - MAX_SPAN, 0)
            q1 = max(h, q0)
            blk = (full[p0:i, q0:q1] if full is not None
                   else sa.vecs[p0:i] @ sb.vecs[q0:q1].T).astype(np.float64)
            if use_prior:
                kb = sb.keys[q0:q1]
                match = ((sa.keys[p0:i, None] == kb[None, :]) & (kb[None, :] >= 0)).astype(float)
            acc_s = np.zeros(q1 - q0)
            acc_m = np.zeros(q1 - q0)
            for a in range(1, min(MAX_SPAN, i) + 1):
                acc_s = acc_s + blk[i - p0 - a]
                if use_prior:
                    acc_m = acc_m + match[i - p0 - a]
                na, ca, ba = sa.norm[a][i], sa.count[a][i], sa.base_sum[a][i]
                for k, (aa, b) in enumerate(BEADS):
                    if aa != a:
                        continue
                    prev = _fetch(rows, lo, i - a, js - b)
                    ok = prev > NEG / 2
                    if not ok.any():
                        continue
                    dot = _window_sums(acc_s, q0, js, b)
                    nb = sb.norm[b][js]
                    cb = sb.count[b][js]
                    with np.errstate(divide="ignore", invalid="ignore"):
                        cos = np.where(nb * na > 0, dot / (na * nb), 0.0)
                        base = (np.where(ca > 0, ba / max(ca, 1), 0.0)
                                + np.where(cb > 0, sb.base_sum[b][js] / np.maximum(cb, 1), 0.0)) / 2
                    gain = ((ca + cb) / 2) ** p.size_weight * (cos - base - p.margin)
                    empty = (ca == 0) | (cb == 0)  # a side without vectors: no content score
                    gain = np.where(empty, NEG, gain)
                    gain = gain - p.merge_penalty * (a + b - 2)
                    if use_prior:
                        bonus = p.prior * _window_sums(acc_m, q0, js, b)
                        gain = np.where(bonus > 0, np.where(empty, 0.0, gain) + bonus, gain)
                    cand = np.where(ok & (js - b >= 0), prev + gain, NEG)
                    better = cand > best
                    best[better] = cand[better]
                    bp[better] = k
        # skips of B units: D[j] = max(D[j], D[j-1])
        run = np.maximum.accumulate(best)
        left = run > best
        bp[left] = _LEFT
        best = run
        rows[i] = best
        rows.pop(i - MAX_SPAN - 1, None)
        bps.append(bp)
    beads = []
    i, j = n, m
    while i > 0 or j > 0:
        code = int(bps[i][j - lo[i]])
        if code == _LEFT:
            j -= 1
        elif code == _UP:
            i -= 1
        else:
            a, b = BEADS[code]
            beads.append((i - a, i, j - b, j))
            i, j = i - a, j - b
    return beads[::-1]


def _fetch(rows: dict[int, np.ndarray], lo: np.ndarray, i: int, js: np.ndarray) -> np.ndarray:
    """D[i][js], with NEG outside row *i*'s band."""
    row = rows[i]
    idx = js - lo[i]
    ok = (idx >= 0) & (idx < len(row))
    out = np.full(len(js), NEG)
    out[ok] = row[idx[ok]]
    return out


def bead_score(sa: _Side, sb: _Side, i0: int, i1: int, j0: int, j1: int) -> tuple[float, float]:
    """(cosine, margin over the baseline) of the summed vectors of a bead."""
    va = sa.vecs[i0:i1].sum(axis=0)
    vb = sb.vecs[j0:j1].sum(axis=0)
    na, nb = float(np.linalg.norm(va)), float(np.linalg.norm(vb))
    if na == 0 or nb == 0:
        return 0.0, 0.0
    cos = float(va @ vb) / (na * nb)
    ca, cb = sa.has[i0:i1].sum(), sb.has[j0:j1].sum()
    base = (sa.base[i0:i1].sum() / ca + sb.base[j0:j1].sum() / cb) / 2
    return cos, cos - base


# ------------------------------------------------------------------ alignment


def confidence(margin: float) -> float:
    """Estimated probability that a bead with this *margin* is right (``CONFIDENCE_FIT``)."""
    mid, slope = CONFIDENCE_FIT
    return float(1.0 / (1.0 + np.exp(-slope * (margin - mid))))


#: (margin at 50 %, slope) of ``confidence``. Set from two measurements
#: (``scripts.align_eval``, 2026-10-19): on Scripture with the refs hidden
#: (273k beads of 82 books, leaving out the 42 works whose refs disagree with
#: their content on over 10 % of beads) the beads the program takes are right
#: 90 % of the time at margin 0.05, 97 % at 0.15 and 99.6 % above 0.3; in a
#: hand-checked sample of patristic beads under 0.15, mostly OCR'd Migne Greek,
#: about half were right. The curve follows the patristic sample at low
#: margins: 0.5 at 0.1, 0.78 at 0.15, 0.92 at 0.2.
CONFIDENCE_FIT: tuple[float, float] = (0.1, 25.0)
#: Margin added for a bead whose ref keys match (Scripture's prior): the refs
#: are evidence too, so a short verse that the content barely tells apart
#: stays confident, while one the refs force against the content does not.
KEYED_BONUS = 0.2


def _align_once(a: Version, b: Version, p: Params) -> tuple[list[Bead], _Side, _Side]:
    n, m = len(a), len(b)
    row_mean, row_max, row_arg, col_mean, col_max, col_arg = similarity_stats(
        a.vecs, b.vecs, p.block)
    sa = _Side.build(a.vecs, row_mean, a.keys)
    sb = _Side.build(b.vecs, col_mean, b.keys)
    full = None
    if n * m <= p.full_cells:
        lo, hi = np.zeros(n + 1, dtype=np.int64), np.full(n + 1, m, dtype=np.int64)
        full = a.vecs @ b.vecs.T
    else:
        pairs = [(i, int(row_arg[i])) for i in range(n)
                 if np.isfinite(row_max[i]) and col_arg[row_arg[i]] == i
                 and row_max[i] - (row_mean[i] + col_mean[row_arg[i]]) / 2 >= p.anchor_margin]
        if a.keys is not None and b.keys is not None and p.prior > 0:
            pairs += _key_pairs(a.keys, b.keys)
        lo, hi = band_from_anchors(n, m, anchor_chain(pairs), p.band)
    beads = []
    for i0, i1, j0, j1 in _dp(sa, sb, p, lo, hi, full):
        sim, margin = bead_score(sa, sb, i0, i1, j0, j1)
        beads.append(Bead(i0, i1, j0, j1, sim, margin))
    return beads, sa, sb


def _key_pairs(ka: np.ndarray, kb: np.ndarray) -> list[tuple[int, int]]:
    pos = {int(k): j for j, k in enumerate(kb) if k >= 0}
    return [(i, pos[int(k)]) for i, k in enumerate(ka) if k >= 0 and int(k) in pos]


def align_pair(a: Version, b: Version, params: Params | None = None) -> list[Bead]:
    """Align versions *a* and *b*; return the beads, sorted by their units of *a*.

    Beads of the first pass are monotonic in both versions; later passes add
    blocks that one version moved (see the module docstring).
    """
    p = params or Params()
    if len(a) == 0 or len(b) == 0:
        return []
    beads, _, _ = _align_once(a, b, p)
    for _ in range(1, p.passes):
        used_a = np.zeros(len(a), bool)
        used_b = np.zeros(len(b), bool)
        for bd in beads:
            if bd.margin > p.margin:
                used_a[bd.i0:bd.i1] = True
                used_b[bd.j0:bd.j1] = True
        ia, ib = np.flatnonzero(~used_a), np.flatnonzero(~used_b)
        if len(ia) < p.min_run or len(ib) < p.min_run:
            break
        sub, _, _ = _align_once(a.subset(ia), b.subset(ib), p)
        keep = _contiguous_runs(sub, ia, ib, p)
        if not keep:
            break
        weak = [bd for bd in beads if bd.margin <= p.margin]
        beads = [bd for bd in beads if bd.margin > p.margin]
        taken_a = np.zeros(len(a), bool)
        taken_b = np.zeros(len(b), bool)
        for bd in keep:
            taken_a[bd.i0:bd.i1] = True
            taken_b[bd.j0:bd.j1] = True
        beads += keep + [bd for bd in weak
                         if not taken_a[bd.i0:bd.i1].any() and not taken_b[bd.j0:bd.j1].any()]
        beads.sort(key=lambda bd: (bd.i0, bd.j0))
    return _with_confidence(beads, a, b, p)


def _contiguous_runs(sub: list[Bead], ia: np.ndarray, ib: np.ndarray, p: Params) -> list[Bead]:
    """Beads of a later pass mapped back, kept if contiguous and in a run of ``min_run``."""
    mapped: list[Bead | None] = []
    for bd in sub:
        a0, a1, b0, b1 = ia[bd.i0], ia[bd.i1 - 1] + 1, ib[bd.j0], ib[bd.j1 - 1] + 1
        if (a1 - a0 != bd.i1 - bd.i0 or b1 - b0 != bd.j1 - bd.j0 or bd.margin <= p.margin):
            mapped.append(None)
        else:
            mapped.append(Bead(int(a0), int(a1), int(b0), int(b1), bd.sim, bd.margin))
    keep: list[Bead] = []
    run: list[Bead] = []
    for bd in mapped + [None]:
        if bd is not None and run and (bd.i0 != run[-1].i1 or bd.j0 != run[-1].j1):
            if len(run) >= p.min_run:
                keep += run
            run = []
        if bd is None:
            if len(run) >= p.min_run:
                keep += run
            run = []
        else:
            run.append(bd)
    return keep


def _keyed(bd: Bead, a: Version, b: Version) -> bool:
    if a.keys is None or b.keys is None:
        return False
    ka = {int(k) for k in a.keys[bd.i0:bd.i1] if k >= 0}
    return bool(ka & {int(k) for k in b.keys[bd.j0:bd.j1] if k >= 0})


def _with_confidence(beads: list[Bead], a: Version, b: Version, p: Params) -> list[Bead]:
    """Set each bead's confidence; a bead sandwiched between confident ones inherits."""
    use_keys = p.prior > 0
    own = [confidence(bd.margin + (KEYED_BONUS if use_keys and _keyed(bd, a, b) else 0.0))
           for bd in beads]
    out = []
    for k, bd in enumerate(beads):
        c = own[k]
        if 0 < k < len(beads) - 1:
            before, after = beads[k - 1], beads[k + 1]
            if (before.i1 == bd.i0 and before.j1 == bd.j0
                    and after.i0 == bd.i1 and after.j0 == bd.j1):
                c = max(c, min(own[k - 1], own[k + 1]))
        out.append(Bead(bd.i0, bd.i1, bd.j0, bd.j1, bd.sim, bd.margin, round(c, 3)))
    return out


# ---------------------------------------------------------------------- groups


@dataclass
class Merged:
    """The alignment groups of a version group.

    ``group_of[work_id][u]`` is the group of unit *u* of that version, or −1;
    ``conf[work_id][g]`` the confidence of the version's span in group *g*
    (pivot: the best of the other versions'). Groups are numbered in pivot
    order.
    """

    pivot: str
    n_groups: int
    group_of: dict[str, np.ndarray]
    conf: dict[str, dict[int, float]]

    def spans(self, work_id: str) -> dict[int, tuple[int, int]]:
        """group → [start, end) units of *work_id*."""
        out: dict[int, tuple[int, int]] = {}
        for u, g in enumerate(self.group_of[work_id]):
            if g >= 0:
                s, _ = out.get(int(g), (u, u))
                out[int(g)] = (s, u + 1)
        return out


def merge(pivot: str, n_pivot: int, pairs: dict[str, tuple[int, list[Bead]]],
          fit: Callable[[str, Bead, int, int], float] | None = None) -> Merged:
    """Build groups from each version's beads against the pivot.

    *pairs* maps a version's work id to (its unit count, its beads), where a
    bead's A side is that version and its B side the pivot.

    Groups are runs of pivot units. Two neighbouring pivot units are in one
    group when at least as many versions put them in one bead as put them in
    two, so one version that renders two verses as one doesn't merge them for
    every other version. A bead that covers pivot units of several groups is
    attached to the one its units fit best (*fit*: the similarity of the
    bead's units with pivot units ``[j0, j1)``; without it, the first).
    """
    covered = np.zeros(n_pivot, bool)
    joins = np.zeros(max(n_pivot - 1, 0), dtype=np.int64)  # boundary q | q+1
    cuts = np.zeros(max(n_pivot - 1, 0), dtype=np.int64)
    for _, beads in pairs.values():
        by_pivot = sorted(beads, key=lambda bd: bd.j0)
        for k, bd in enumerate(by_pivot):
            covered[bd.j0:bd.j1] = True
            joins[bd.j0:bd.j1 - 1] += 1
            if k and by_pivot[k - 1].j1 == bd.j0:
                cuts[bd.j0 - 1] += 1
    joined = (joins > 0) & (joins >= cuts)
    pivot_group = np.full(n_pivot, -1, dtype=np.int64)
    starts: list[int] = []
    for q in range(n_pivot):
        if not covered[q]:
            continue
        if not (q and covered[q - 1] and joined[q - 1]):
            starts.append(q)
        pivot_group[q] = len(starts) - 1
    group_of = {pivot: pivot_group}
    conf: dict[str, dict[int, float]] = {pivot: {}}
    for wid in sorted(pairs):
        n, beads = pairs[wid]
        g_of = np.full(n, -1, dtype=np.int64)
        c_of: dict[int, float] = {}
        units: dict[int, list[tuple[int, int]]] = {}  # group → its beads' units
        for bd in beads:
            gs = sorted({int(g) for g in pivot_group[bd.j0:bd.j1]})
            g = gs[0]
            if len(gs) > 1 and fit is not None:
                def score(g: int, bd: Bead = bd) -> float:
                    run = np.flatnonzero(pivot_group[bd.j0:bd.j1] == g) + bd.j0
                    return fit(wid, bd, int(run[0]), int(run[-1]) + 1)
                g = max(gs, key=lambda g: (score(g), -g))
            units.setdefault(g, []).append((bd.i0, bd.i1))
            c_of[g] = min(c_of.get(g, 1.0), bd.conf)
        # A version's units in one group must be one run. Only the units its
        # beads assign count (a gap between two beads is not filled in); a
        # group whose units are not contiguous is left out for this version.
        for g, runs in units.items():
            runs.sort()
            if any(a1 != b0 for (_, a1), (b0, _) in zip(runs, runs[1:])):
                c_of.pop(g, None)
                continue
            g_of[runs[0][0]:runs[-1][1]] = g
        group_of[wid] = g_of
        conf[wid] = c_of
        for g, c in c_of.items():
            conf[pivot][g] = max(conf[pivot].get(g, 0.0), c)
    return Merged(pivot, len(starts), group_of, conf)


def span_fit(vecs: dict[str, np.ndarray], pivot_vecs: np.ndarray
             ) -> Callable[[str, Bead, int, int], float]:
    """A ``fit`` for ``merge``: the cosine of a bead's summed units with pivot units [j0, j1)."""
    def fit(wid: str, bd: Bead, j0: int, j1: int) -> float:
        va = vecs[wid][bd.i0:bd.i1].sum(axis=0)
        vb = pivot_vecs[j0:j1].sum(axis=0)
        d = float(np.linalg.norm(va) * np.linalg.norm(vb))
        return float(va @ vb) / d if d else 0.0
    return fit


LANGUAGE_PREFERENCE: tuple[str, ...] = ("eng", "grc", "lat", "hbo")


def choose_pivot(members: dict[str, tuple[str, int]]) -> str:
    """The pivot of a version group: *members* maps work id → (language, units with vectors).

    The longest version, so that the others' passages are in it; among those
    within 10 % of the longest, by ``LANGUAGE_PREFERENCE`` (English has the
    strongest vectors, and the rare languages are compared through English
    translations), then the most units, then the smallest work id.
    """
    longest = max(n for _, n in members.values())
    near = [w for w, (_, n) in members.items() if n >= 0.9 * longest]

    def rank(w: str) -> tuple[int, int, str]:
        lang, n = members[w]
        pref = LANGUAGE_PREFERENCE.index(lang) if lang in LANGUAGE_PREFERENCE else len(
            LANGUAGE_PREFERENCE)
        return (pref, -n, w)

    return min(near, key=rank)
