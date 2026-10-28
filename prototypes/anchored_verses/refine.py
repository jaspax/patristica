"""EXPERIMENTAL prototype for #304: cut a translation's derived verses on its
original's derived verses, refining the boundaries from embeddings.

Not used by the pipeline; nothing here writes ``data/normalized`` or
``data/embeddings``. The design is ``docs/anchored-derived-verses.md``.

The algorithm (``refine``):

1. **Segments.** The translation's source paragraphs (rebuilt from its derived
   verses) are cut into *segments* at every sentence and clause end
   (``versify``'s break strengths), at commas inside runs longer than the
   language's verse size, and at today's cuts. A derived verse of the result is
   always a run of whole segments inside one source paragraph, so boundaries
   stay at sentence and clause breaks.
2. **Segment vectors.** Every segment is embedded once (Voyage, text only).
   Together with the vectors of the provisional cut (today's units, already in
   ``data/embeddings``) they are the *vector cache*, keyed by the hash of the
   exact text embedded.
3. **Anchored segmentation** (``segment_dp``): a monotonic dynamic program over
   (original units consumed, segments consumed). A bead gives 1-3 original
   units a run of segments (which may cross a translation paragraph break; it
   is cut there on output). Its gain is the aligner's (#179): the cosine of
   the summed vectors above both sides' baselines, less a margin, with a merge
   penalty, plus small costs for ending on a weak break. A piece whose exact
   text is in the cache is scored with its own vector, any other with the sum
   of its segments' vectors, calibrated (``Calibration``) onto the exact scale.
   Skipping an original unit is free (the translation leaves it out), skipping
   a segment costs a little (an addition; it is attached to its neighbour).
   The program runs in a band around the provisional cut's alignment.
4. **Iterate.** The chosen pieces that are not in the cache are embedded and
   the program is run again; it stops when every chosen piece was scored with
   its own vector (a fixed point), or after ``max_rounds``.

Deterministic given the cache: the same vectors give the same cut.
"""

from __future__ import annotations

import json
import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from patristica import embeddings as emb
from patristica.alignment import Bead, Params, Version, align_pair, anchor_chain
from patristica.translations import text_sha
from patristica.versify import (
    CLAUSE,
    COMMA,
    SENTENCE,
    VERSE_TOKENS,
    _atoms,
    _strength,
    _word_tokens,
    is_derived_ref,
)

log = logging.getLogger(__name__)

NORMALIZED = Path("data/normalized")
EMBEDDINGS = Path("data/embeddings")
NEG = -1e18


# ------------------------------------------------------------------ the corpus


def work_paths(norm: Path = NORMALIZED) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (norm / "_works.jsonl").read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        out[rec["work"]["work_id"]] = rec["path"]
    return out


@dataclass
class Units:
    """A work's units as stored: refs, texts and (normalized) vectors."""

    work_id: str
    language: str
    refs: list[str]
    texts: list[str]
    vecs: np.ndarray  # float32 units × dims, zero rows where there is no vector

    def version(self) -> Version:
        return Version(self.work_id, self.vecs)


def load_units(work_id: str, kind: int = emb.KIND_TEXT, norm: Path = NORMALIZED,
               store: Path = EMBEDDINGS) -> Units:
    """A work's stored units and their *kind* vectors (from ``data/embeddings``)."""
    path = work_paths(norm)[work_id]
    chunks = json.loads((norm / path).read_text(encoding="utf-8"))
    shard = emb.load(store, path)
    index = shard.by_key() if shard is not None else {}
    dims = shard.vecs.shape[1] if shard is not None else 1024
    vecs = np.zeros((len(chunks), dims), dtype=np.float32)
    for u, c in enumerate(chunks):
        k = index.get((c["chunk_id"], kind))
        if k is not None:
            vecs[u] = shard.vecs[k]
    return Units(work_id, chunks[0]["language"], [c["canonical_ref"] for c in chunks],
                 [c["text"] for c in chunks], _normalize(vecs))


def _normalize(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=1, keepdims=True)
    return np.divide(v, n, out=np.zeros_like(v), where=n > 0).astype(np.float32)


# --------------------------------------------------------------- vector cache


class VectorCache:
    """Vectors by the hash of the exact text embedded (``text_sha``).

    Seeded from the provisional cut's stored vectors (free); new texts are
    embedded through *embed* (paid) and saved to a scratch ``.npz``, never to
    ``data/embeddings``. ``budget_tokens`` stops a run before it overspends.
    """

    def __init__(self, path: Path, embed: Callable[[list[str]], np.ndarray] | None,
                 budget_tokens: int, count: Callable[[str], int]) -> None:
        self.path = path
        self._embed = embed
        self.budget_tokens = budget_tokens
        self._count = count
        self.vecs: dict[str, np.ndarray] = {}
        self.estimated_tokens = 0  # cl100k estimate of what this process sent
        if path.exists():
            with np.load(path, allow_pickle=False) as z:
                for s, v in zip(z["sha"], z["vec"]):
                    self.vecs[str(s)] = v.astype(np.float32)

    def seed(self, texts: Sequence[str], vecs: np.ndarray) -> None:
        for t, v in zip(texts, vecs):
            if v.any():
                self.vecs.setdefault(text_sha(t), v)

    def get(self, text: str) -> np.ndarray | None:
        return self.vecs.get(text_sha(text))

    def missing(self, texts: Sequence[str]) -> list[str]:
        seen: set[str] = set()
        out = []
        for t in texts:
            s = text_sha(t)
            if s not in self.vecs and s not in seen:
                seen.add(s)
                out.append(t)
        return out

    def estimate(self, texts: Sequence[str]) -> int:
        return sum(self._count(t) for t in self.missing(texts))

    def ensure(self, texts: Sequence[str]) -> int:
        """Embed the texts not in the cache; return the estimated tokens sent."""
        todo = self.missing(texts)
        if not todo:
            return 0
        tokens = sum(self._count(t) for t in todo)
        if self._embed is None:
            raise RuntimeError(f"{len(todo)} texts ({tokens:,} tokens) need vectors; "
                               "run with --pay")
        if self.estimated_tokens + tokens > self.budget_tokens:
            raise RuntimeError(f"embedding {tokens:,} more tokens would exceed the budget "
                               f"({self.estimated_tokens:,} of {self.budget_tokens:,} used)")
        vecs = _normalize(np.asarray(self._embed(todo), dtype=np.float32))
        for t, v in zip(todo, vecs):
            self.vecs[text_sha(t)] = v.astype(np.float16).astype(np.float32)
        self.estimated_tokens += tokens
        self.save()
        return tokens

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        keys = sorted(self.vecs)
        tmp = self.path.with_suffix(".tmp.npz")
        np.savez(tmp, sha=np.array(keys, dtype=str),
                 vec=np.stack([self.vecs[k] for k in keys]).astype(np.float16))
        tmp.replace(self.path)


# ------------------------------------------------------------------ segments


@dataclass
class Paragraph:
    """A translation source paragraph: its words and today's cuts (atom indices)."""

    ref: str
    atoms: list[str]
    today: list[int]  # starts of today's units, 0 first


def paragraphs_of(units: Units) -> list[Paragraph]:
    """The translation's source paragraphs, rebuilt from its derived verses."""
    out: list[Paragraph] = []
    last: str | None = None
    for ref, text in zip(units.refs, units.texts):
        parent = ref.rsplit(".", 1)[0] if is_derived_ref(ref) else ref
        if parent != ref and parent == last and out:
            para = out[-1]
            para.today.append(len(para.atoms))
            para.atoms.extend(_atoms(" " + text))
        else:
            out.append(Paragraph(parent, _atoms(text), [0]))
        last = parent if parent != ref else None
    return out


@dataclass
class Segment:
    para: int
    a0: int  # atoms [a0, a1) of its paragraph
    a1: int
    text: str
    tokens: int
    end: int  # break strength at its end (SENTENCE at a paragraph end)
    today_end: bool  # today's cut (or a paragraph end) falls at its end


def segments_of(paras: Sequence[Paragraph], language: str) -> list[Segment]:
    target = VERSE_TOKENS[language]
    out: list[Segment] = []
    for p, para in enumerate(paras):
        atoms = para.atoms
        n = len(atoms)
        if n == 0:
            continue
        tok = [_word_tokens(a) for a in atoms]
        st = [_strength(atoms[i], atoms[i + 1] if i + 1 < n else None, language)
              for i in range(n)]
        today = set(para.today[1:])
        stops = sorted({i + 1 for i in range(n - 1) if st[i] <= CLAUSE} | today | {n})
        # Commas (then words) inside long runs.
        fine: list[int] = []
        prev = 0
        for stop in stops:
            if sum(tok[prev:stop]) > target:
                commas = [i + 1 for i in range(prev, stop - 1) if st[i] == COMMA]
                fine.extend(commas)
                last = prev
                for c in [*commas, stop]:
                    if sum(tok[last:c]) > 2 * target:
                        fine.extend(_word_cuts(tok, last, c, target))
                    last = c
            fine.append(stop)
            prev = stop
        prev = 0
        for stop in sorted(set(fine)):
            text = "".join(atoms[prev:stop]).strip()
            if text:
                out.append(Segment(p, prev, stop, text, sum(tok[prev:stop]),
                                   SENTENCE if stop == n else st[stop - 1],
                                   stop == n or stop in today))
            elif out and out[-1].para == p:
                out[-1].a1 = stop
            prev = stop
    return out


def _word_cuts(tok: Sequence[int], a: int, b: int, target: int) -> list[int]:
    out = []
    acc = 0
    for i in range(a, b - 1):
        acc += tok[i]
        if acc >= target:
            out.append(i + 1)
            acc = 0
    return out


def piece_text(paras: Sequence[Paragraph], para: int, a0: int, a1: int) -> str:
    return "".join(paras[para].atoms[a0:a1]).strip()


# --------------------------------------------------------------- calibration


@dataclass(frozen=True)
class Calibration:
    """Maps a summed-segments margin onto the exact-vector margin scale: a·m + b."""

    a: float = 1.0
    b: float = 0.0

    def __call__(self, m: np.ndarray) -> np.ndarray:
        return self.a * m + self.b


# --------------------------------------------------------------------- the DP


@dataclass(frozen=True)
class RefineParams:
    margin: float = 0.05  # as the aligner
    merge_penalty: float = 0.06  # per extra original unit in a bead
    max_originals: int = 3  # original units per bead
    max_segments: int = 24
    max_tokens_verses: float = 12.0  # a piece is at most this many verses of its language
    skip_segment: float = 0.03  # cost of leaving a segment out of every bead (per segment)
    break_cost: tuple[float, float, float, float] = (0.0, 0.01, 0.03, 0.08)  # by end strength
    cross_paragraph: float = 0.02  # per translation paragraph break inside a bead
    band: int = 6  # original units either side of the provisional estimate
    #: Charged to a piece scored by its summed segments rather than its own
    #: vector: a hysteresis that keeps an embedded piece unless the estimate
    #: is clearly better, so the rounds converge.
    unembedded: float = 0.02
    max_rounds: int = 4  # exploring rounds; then one exact-only round


@dataclass
class Result:
    """A refined cut: per translation paragraph, the atom ranges of its units."""

    pieces: list[list[tuple[int, int]]]
    beads: list[tuple[int, int, int, int]]  # (k0, k1, j0, j1): originals, segments
    rounds: int
    converged: bool
    fallback_paragraphs: set[int] = field(default_factory=set)
    log: list[dict] = field(default_factory=list)

    def texts(self, paras: Sequence[Paragraph]) -> list[str]:
        return [piece_text(paras, p, a0, a1)
                for p, ps in enumerate(self.pieces) for a0, a1 in ps]


def provisional_band(n_orig: int, segs: Sequence[Segment], paras: Sequence[Paragraph],
                     today_beads: Sequence[Bead], width: int) -> tuple[np.ndarray, np.ndarray]:
    """Per segment boundary j (0..M), the range of original units the DP may be at.

    Estimated from the provisional cut's alignment (*today_beads*: A = today's
    translation units, B = original units, the confident ones), interpolated
    where today's units are unaligned.
    """
    # today's unit index of each segment
    unit_of_start: dict[tuple[int, int], int] = {}
    u = 0
    for p, para in enumerate(paras):
        for a in para.today:
            unit_of_start[(p, a)] = u
            u += 1
    seg_unit = []
    cur = -1
    for s in segs:
        cur = unit_of_start.get((s.para, s.a0), cur)
        seg_unit.append(cur)
    span_of: dict[int, tuple[int, int, int, int]] = {}
    confident = [bd for bd in today_beads if bd.conf >= 0.5]
    chain = set(anchor_chain([(bd.i0, bd.j0) for bd in confident]))
    for bd in confident:
        if (bd.i0, bd.j0) not in chain:
            continue  # a block moved by a later pass: not monotone
        for t in range(bd.i0, bd.i1):
            span_of[t] = (bd.i0, bd.i1, bd.j0, bd.j1)
    m = len(segs)
    est = np.full(m + 1, np.nan)
    # segments of each today unit
    by_unit: dict[int, list[int]] = {}
    for j, t in enumerate(seg_unit):
        by_unit.setdefault(t, []).append(j)
    for t, (i0, i1, k0, k1) in span_of.items():
        js = [j for tt in range(i0, i1) for j in by_unit.get(tt, [])]
        if not js:
            continue
        for r, j in enumerate(js):
            est[j] = k0 + (k1 - k0) * r / len(js)
        est[js[-1] + 1] = k1
    est[0] = 0 if np.isnan(est[0]) else est[0]
    est[m] = n_orig if np.isnan(est[m]) else est[m]
    known = np.flatnonzero(~np.isnan(est))
    est = np.interp(np.arange(m + 1), known, est[known])
    lo = np.clip(np.floor(est).astype(np.int64) - width, 0, n_orig)
    hi = np.clip(np.ceil(est).astype(np.int64) + width, 0, n_orig)
    lo = np.minimum.accumulate(lo[::-1])[::-1]
    hi = np.maximum.accumulate(hi)
    lo[0], hi[m] = 0, n_orig
    # A row must reach the next one's band: skips of original units happen
    # inside a row, so a jump (a block the translation leaves out) widens it.
    hi[:-1] = np.maximum(hi[:-1], lo[1:])
    return lo, hi


def segment_dp(orig: np.ndarray, orig_base: np.ndarray, segs: Sequence[Segment],
               seg_vecs: np.ndarray, paras: Sequence[Paragraph],
               lo: np.ndarray, hi: np.ndarray, cache: VectorCache, calib: Calibration,
               language: str, p: RefineParams, exact_only: bool = False
               ) -> tuple[list[tuple[int, int, int, int]], list[int], list[bool]]:
    """The best beads (k0, k1, j0, j1), the skipped segments, and per bead
    whether it was scored with exact vectors.

    *orig* are the original's unit vectors (normalized), *orig_base* their
    baselines (mean similarity to the translation's units); a piece's baseline
    is its cosine with the mean of *orig*.
    """
    n, m = len(orig), len(segs)
    omean = orig.mean(axis=0)
    max_tok = p.max_tokens_verses * VERSE_TOKENS[language]
    # Prefix sums of original vectors for windows of 1..max_originals.
    vsum = {a: np.stack([orig[max(k - a, 0):k].sum(axis=0) if k >= a else np.zeros(orig.shape[1])
                         for k in range(n + 1)]) for a in range(1, p.max_originals + 1)}
    vnorm = {a: np.linalg.norm(v, axis=1) for a, v in vsum.items()}
    cb = np.concatenate([[0.0], np.cumsum(orig_base)])
    rows: dict[int, np.ndarray] = {}
    bps: list[np.ndarray] = []
    exact_at: list[dict[int, bool]] = []
    SKIP_SEG, SKIP_ORIG = -1, -2
    for j in range(m + 1):
        ks = np.arange(lo[j], hi[j] + 1)
        best = np.full(len(ks), NEG)
        bp = np.full(len(ks), SKIP_ORIG, dtype=np.int64)
        ex: dict[int, bool] = {}
        if j == 0:
            best[ks == 0] = 0.0
        else:
            prev = _fetch(rows, lo, j - 1, ks) - p.skip_segment
            better = prev > best
            best[better] = prev[better]
            bp[better] = SKIP_SEG
            acc = np.zeros(orig.shape[1], dtype=np.float64)
            tokens = 0
            crosses = 0
            end_cost = p.break_cost[segs[j - 1].end]
            k_lo = max(int(lo[j]) - p.max_originals, 0)
            for L in range(1, min(p.max_segments, j) + 1):
                s = segs[j - L]
                if L > 1 and s.para != segs[j - L + 1].para:
                    crosses += 1
                acc += seg_vecs[j - L]
                tokens += s.tokens
                if tokens > max_tok and L > 1:
                    break
                exact = False
                vec = acc
                if crosses == 0:
                    e = cache.get(piece_text(paras, s.para, s.a0, segs[j - 1].a1))
                    if e is not None:
                        vec, exact = e.astype(np.float64), True
                else:  # the sum of its parts' own vectors, one per paragraph
                    parts = _parts(segs, j - L, j)
                    es = [cache.get(piece_text(paras, q, a0, a1)) for q, a0, a1 in parts]
                    if all(e is not None for e in es):
                        vec, exact = np.sum(es, axis=0).astype(np.float64), True
                if exact_only and not exact:
                    continue  # (a paragraph-crossing bead: its parts are scored apart)
                wn = float(np.linalg.norm(vec))
                if wn == 0:
                    continue
                w = vec / wn
                dots = orig[k_lo:int(hi[j])] @ w  # cos with each original unit
                tbase = float(w @ omean)
                cd = np.concatenate([[0.0], np.cumsum(dots)])
                for a in range(1, p.max_originals + 1):
                    kk = ks[ks - a >= 0]
                    if not len(kk):
                        continue
                    prevk = _fetch(rows, lo, j - L, kk - a)
                    ok = prevk > NEG / 2
                    if not ok.any():
                        continue
                    # cos(Σv, w) = Σ (v·w) / |Σv|
                    num = cd[kk - k_lo] - cd[kk - a - k_lo]
                    den = vnorm[a][kk]
                    cos = np.where(den > 0, num / np.where(den > 0, den, 1), 0.0)
                    base = ((cb[kk] - cb[kk - a]) / a + tbase) / 2
                    marg = cos - base
                    if not exact:
                        marg = calib(marg) - p.unembedded
                    gain = (math.sqrt(a) * (marg - p.margin) - p.merge_penalty * (a - 1)
                            - end_cost - p.cross_paragraph * crosses)
                    cand = np.where(ok, prevk + gain, NEG)
                    idx = kk - lo[j]
                    better = cand > best[idx]
                    if better.any():
                        sel = idx[better]
                        best[sel] = cand[better]
                        bp[sel] = L * 16 + a
                        for q in sel:
                            ex[int(q)] = exact
        run = np.maximum.accumulate(best)
        left = run > best
        bp[left] = SKIP_ORIG
        best = run
        rows[j] = best
        rows.pop(j - p.max_segments - 1, None)
        bps.append(bp)
        exact_at.append(ex)
    beads: list[tuple[int, int, int, int]] = []
    exact_beads: list[bool] = []
    skipped: list[int] = []
    j, k = m, n
    while j > 0 or k > 0:
        code = int(bps[j][k - lo[j]])
        if code == SKIP_ORIG:
            k -= 1
        elif code == SKIP_SEG:
            skipped.append(j - 1)
            j -= 1
        else:
            L, a = divmod(code, 16)
            beads.append((k - a, k, j - L, j))
            exact_beads.append(exact_at[j].get(k - lo[j], False))
            j, k = j - L, k - a
    return beads[::-1], skipped[::-1], exact_beads[::-1]


def _parts(segs: Sequence[Segment], j0: int, j1: int) -> list[tuple[int, int, int]]:
    """Segments [j0, j1) as (paragraph, a0, a1), one per paragraph."""
    out: list[tuple[int, int, int]] = []
    for s in segs[j0:j1]:
        if out and out[-1][0] == s.para:
            out[-1] = (s.para, out[-1][1], s.a1)
        else:
            out.append((s.para, s.a0, s.a1))
    return out


def _fetch(rows: dict[int, np.ndarray], lo: np.ndarray, j: int, ks: np.ndarray) -> np.ndarray:
    row = rows[j]
    idx = ks - lo[j]
    ok = (idx >= 0) & (idx < len(row))
    out = np.full(len(ks), NEG)
    out[ok] = row[idx[ok]]
    return out


def pieces_from(beads: Sequence[tuple[int, int, int, int]], skipped: Sequence[int],
                segs: Sequence[Segment], paras: Sequence[Paragraph]
                ) -> tuple[list[list[tuple[int, int]]], set[int]]:
    """Per paragraph, the atom ranges of the refined units.

    A bead's segments are one unit per paragraph they touch. A skipped segment
    joins the unit before it in its paragraph, else the one after. A paragraph
    no bead touches keeps today's cut (returned as a fallback).
    """
    owner = [-1] * len(segs)
    for b, (_, _, j0, j1) in enumerate(beads):
        for j in range(j0, j1):
            owner[j] = b
    for j in skipped:
        owner[j] = -1
    # resolve skipped: previous owned segment in the same paragraph, else next
    for j in range(len(segs)):
        if owner[j] == -1 and j > 0 and segs[j - 1].para == segs[j].para and owner[j - 1] >= 0:
            owner[j] = owner[j - 1]
    for j in range(len(segs) - 1, -1, -1):
        if (owner[j] == -1 and j + 1 < len(segs) and segs[j + 1].para == segs[j].para
                and owner[j + 1] >= 0):
            owner[j] = owner[j + 1]
    out: list[list[tuple[int, int]]] = [[] for _ in paras]
    fallback: set[int] = set()
    by_para: dict[int, list[int]] = {}
    for j, s in enumerate(segs):
        by_para.setdefault(s.para, []).append(j)
    for p, para in enumerate(paras):
        js = by_para.get(p, [])
        if not js or all(owner[j] == -1 for j in js):
            fallback.add(p)
            bounds = [*para.today, len(para.atoms)]
            out[p] = list(zip(bounds, bounds[1:]))
            continue
        cur: tuple[int, int] | None = None
        cur_owner = None
        for j in js:
            s = segs[j]
            if cur is not None and owner[j] == cur_owner:
                cur = (cur[0], s.a1)
            else:
                if cur is not None:
                    out[p].append(cur)
                cur, cur_owner = (s.a0 if cur is None else cur[1], s.a1), owner[j]
        assert cur is not None
        out[p].append((cur[0], len(para.atoms)))
        if out[p][0][0] != 0:
            out[p][0] = (0, out[p][0][1])
    return out, fallback


def calibrate(paras: Sequence[Paragraph], segs: Sequence[Segment], seg_vecs: np.ndarray,
              today: Units, orig: Units, today_beads: Sequence[Bead]) -> Calibration:
    """Fit exact margin ≈ a · summed-segments margin + b on today's 1:1 beads."""
    omean = orig.vecs.mean(axis=0)
    seg_of_unit: list[list[int]] = []
    u_index: dict[tuple[int, int], int] = {}
    u = 0
    for p, para in enumerate(paras):
        for a in para.today:
            u_index[(p, a)] = u
            seg_of_unit.append([])
            u += 1
    cur = -1
    for j, s in enumerate(segs):
        cur = u_index.get((s.para, s.a0), cur)
        seg_of_unit[cur].append(j)
    xs, ys = [], []
    for bd in today_beads:
        if bd.i1 - bd.i0 != 1 or bd.j1 - bd.j0 != 1 or bd.conf < 0.5:
            continue
        js = seg_of_unit[bd.i0]
        if len(js) < 2:
            continue
        v = orig.vecs[bd.j0]
        e = today.vecs[bd.i0]
        if not e.any():
            continue
        s = seg_vecs[js].sum(axis=0)
        s = s / np.linalg.norm(s)
        xs.append(float(s @ v) - float(s @ omean))
        ys.append(float(e @ v) - float(e @ omean))
    if len(xs) < 20:
        return Calibration()
    a, b = np.polyfit(xs, ys, 1)
    return Calibration(float(a), float(b))


def refine(orig: Units, today: Units, cache: VectorCache, p: RefineParams = RefineParams(),
           params: Params | None = None) -> tuple[Result, list[Paragraph], list[Segment],
                                                   Calibration, list[Bead]]:
    """Refine *today*'s cut of the translation on *orig* (see the module docstring)."""
    paras = paragraphs_of(today)
    segs = segments_of(paras, today.language)
    cache.seed(today.texts, today.vecs)
    seg_texts = [s.text for s in segs]
    log.info("%s: %d paragraphs, %d segments; embedding %d segments (~%d tokens)",
             today.work_id, len(paras), len(segs), len(cache.missing(seg_texts)),
             cache.estimate(seg_texts))
    cache.ensure(seg_texts)
    seg_vecs = np.stack([cache.get(t) for t in seg_texts]).astype(np.float64)
    today_beads = align_pair(today.version(), orig.version(), params)
    lo, hi = provisional_band(len(orig.texts), segs, paras, today_beads, p.band)
    calib = calibrate(paras, segs, seg_vecs, today, orig, today_beads)
    log.info("calibration: exact ≈ %.3f · summed + %.3f", calib.a, calib.b)
    # Baselines: an original unit's mean similarity to the translation's units.
    tvec = today.vecs[np.abs(today.vecs).sum(axis=1) > 0]
    orig_base = orig.vecs @ tvec.mean(axis=0)
    history: list[dict] = []
    result: Result | None = None
    for r in range(1, p.max_rounds + 2):
        final = r == p.max_rounds + 1
        beads, skipped, exact = segment_dp(orig.vecs, orig_base, segs, seg_vecs, paras,
                                           lo, hi, cache, calib, today.language, p,
                                           exact_only=final)
        pieces, fallback = pieces_from(beads, skipped, segs, paras)
        result = Result(pieces, beads, r, False, fallback, history)
        texts = result.texts(paras)
        todo = cache.missing(texts)
        history.append({"round": r, "exact_only": final, "units": len(texts),
                        "beads": len(beads), "exact_beads": sum(exact),
                        "new_units": len(todo), "new_tokens": cache.estimate(texts)})
        log.info("round %d: %s", r, history[-1])
        if not todo:
            result.converged = not final
            break
        # Final units are embedded anyway (they need production vectors). After
        # the exact-only round, the only new texts are units that took in a
        # skipped segment (an addition of the translation).
        cache.ensure(texts)
        if final:
            break
    assert result is not None
    return result, paras, segs, calib, today_beads


def refined_units(today: Units, result: Result, paras: Sequence[Paragraph],
                  cache: VectorCache) -> Units:
    """The refined cut as ``Units`` (refs ``para.sN``; vectors from the cache)."""
    refs, texts = [], []
    for p, ps in enumerate(result.pieces):
        for n, (a0, a1) in enumerate(ps, start=1):
            refs.append(paras[p].ref if len(ps) == 1 else f"{paras[p].ref}.s{n}")
            texts.append(piece_text(paras, p, a0, a1))
    vecs = np.zeros((len(texts), today.vecs.shape[1]), dtype=np.float32)
    for u, t in enumerate(texts):
        v = cache.get(t)
        if v is not None:
            vecs[u] = v
    return Units(today.work_id, today.language, refs, texts, _normalize(vecs))
