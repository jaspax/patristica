"""The refinement of anchored derived verses (#304; ``docs/anchored-derived-verses.md`` §4).

Cuts a translation's derived verses on its original's derived verses, placing
the boundaries from Voyage vectors. ``scripts.anchor`` runs it and records the
result as a cut file (``patristica.anchor_store``); this module computes, it
writes nothing but the scratch vector store.

1. **Segments** (:func:`segments_of`). The translation's source paragraphs
   (rebuilt from its units) are cut into *segments* at every sentence and
   clause end (``versify``'s break strengths), at commas inside runs longer
   than the language's verse size, between words inside runs longer than
   twice that, and at the provisional cut. A derived verse of the result is
   always a run of whole segments inside one source paragraph.
2. **Vectors** (:class:`VectorCache`). Every segment is embedded once (text
   only). The cache maps the hash of an exact text (``translations.text_sha``)
   to its vector; it is seeded for free with the stored vectors of the
   provisional cut (``data/embeddings``), and what it embeds is kept in a
   gitignored scratch store (``data/anchor_vectors``).
3. **Anchored segmentation** (:func:`segment_dp`): a monotonic dynamic program
   over (original units consumed, segments consumed). A bead gives 1–3
   original units a run of 1–24 segments (which may cross a paragraph break;
   it is cut there on output). Its gain is the aligner's (#179):
   ``√a · (cos − baseline − margin) − merge_penalty · (a − 1)``, less small
   costs for ending on a weak break or crossing a paragraph. A piece whose
   exact text is in the cache is scored with its own vector, any other with
   the sum of its segments' vectors, mapped onto the exact scale by a linear
   :class:`Calibration` and charged a hysteresis. Skipping an original unit
   is free, skipping a segment costs a little. The program runs in a band
   around the provisional cut's alignment (:func:`provisional_band`), on the
   part of the original the translation covers (:func:`covered_span`, #394:
   the whole original unless the translation is partial).
4. **Rounds** (:func:`refine`). The chosen pieces that aren't in the cache are
   embedded and the program runs again, until a round chooses only cached
   pieces or after ``max_rounds``; then one exact-only round scores the final
   cut on real vectors alone.

Deterministic given the cache: float64 sums, ties to the shorter run and the
earlier position.

**Runtime.** The inner step is vectorized over the run lengths of a segment
end (one matrix product per segment, not one per run), which makes a round
roughly linear in segments × band; see :func:`segment_dp`.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from patristica import editorial
from patristica import embeddings as emb
from patristica.alignment import Bead, Params, Version, align_pair, anchor_chain
from patristica.anchoring import RefineParams
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

NEG = -1e18


class NeedsVectors(RuntimeError):
    """Texts need vectors, but there is no embedder (no ``--pay``) or the budget
    is spent. Carries the estimated tokens."""

    def __init__(self, message: str, tokens: int) -> None:
        super().__init__(message)
        self.tokens = tokens


def normalize_rows(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=1, keepdims=True)
    return np.divide(v, n, out=np.zeros_like(v, dtype=np.float32),
                     where=n > 0).astype(np.float32)


@dataclass
class Units:
    """A work's units as stored: refs, texts and (normalized) vectors (zero rows
    where there is none)."""

    work_id: str
    language: str
    refs: list[str]
    texts: list[str]
    vecs: np.ndarray  # float32, units × dims
    #: Editorial spans per unit (#236; offsets into its text), or None.
    spans: list[list[editorial.Span]] | None = None

    def version(self) -> Version:
        return Version(self.work_id, self.vecs)

    def slice(self, k0: int, k1: int) -> Units:
        """Units ``[k0, k1)`` (the part of an original a translation covers, #394)."""
        return Units(self.work_id, self.language, self.refs[k0:k1], self.texts[k0:k1],
                     self.vecs[k0:k1], None if self.spans is None else self.spans[k0:k1])

    def source_texts(self) -> list[str]:
        """The units' texts without editorial material: what is embedded."""
        if self.spans is None:
            return list(self.texts)
        return [editorial.strip(t, sp) for t, sp in zip(self.texts, self.spans)]


# --------------------------------------------------------------- vector cache


class VectorCache:
    """Vectors by the hash of the exact text embedded.

    *path* is the scratch shard (``data/anchor_vectors/{path}.npz``, an
    ``embeddings.WorkEmbeddings`` whose rows are keyed by the text hash);
    *embed* sends texts to the API (None: nothing may be sent, and
    :meth:`ensure` raises ``NeedsVectors``, unless *offline*: then texts
    without a vector simply stay without one, which lets an evaluation run on
    the vectors already known, for free). ``budget_tokens`` caps what one
    process sends. Every vector keeps the run (model, date) it came from, so a
    final unit's vector can be written into ``data/embeddings`` as is.
    """

    def __init__(self, path: Path | None, work_id: str, source_path: str,
                 embed: Callable[[list[str]], np.ndarray] | None, run: emb.EmbeddingRun,
                 count: Callable[[str], int], budget_tokens: int | None = None,
                 offline: bool = False) -> None:
        self.path = path  # scratch store directory, or None (in memory)
        self.work_id, self.source_path = work_id, source_path
        self._embed = embed
        self.run = run
        self._count = count
        self.budget_tokens = budget_tokens
        self.offline = offline and embed is None
        self.raw: dict[str, np.ndarray] = {}  # sha → float16 vector as stored
        self.runs: dict[str, emb.EmbeddingRun] = {}  # sha → its run
        self._unit: dict[str, np.ndarray] = {}  # sha → normalized float32
        self._own: set[str] = set()  # shas embedded here (saved to scratch)
        self.sent_tokens = 0  # cl100k estimate of what this cache sent
        if path is not None:
            shard = emb.load(path, source_path)
            if shard is not None and shard.vecs is not None:
                for row, v in zip(shard.rows, shard.vecs):
                    self._put(row.sha, v, shard.runs[row.run], own=True)

    def _put(self, sha: str, vec: np.ndarray, run: emb.EmbeddingRun, own: bool) -> None:
        if sha in self.raw:
            return
        if not run.same_space(self.run):
            return  # another model's vectors are not comparable
        self.raw[sha] = np.asarray(vec, dtype=np.float16)
        self.runs[sha] = run
        if own:
            self._own.add(sha)

    def seed(self, sha: str, vec: np.ndarray, run: emb.EmbeddingRun) -> None:
        """A stored production vector (free; not copied to the scratch store)."""
        self._put(sha, vec, run, own=False)

    def has(self, text: str) -> bool:
        return text_sha(text) in self.raw

    def get(self, text: str) -> np.ndarray | None:
        return self.get_sha(text_sha(text))

    def get_sha(self, sha: str) -> np.ndarray | None:
        v = self._unit.get(sha)
        if v is None:
            r = self.raw.get(sha)
            if r is None:
                return None
            v = r.astype(np.float32)
            n = float(np.linalg.norm(v))
            v = v / n if n > 0 else v
            self._unit[sha] = v
        return v

    def missing(self, texts: Sequence[str]) -> list[str]:
        seen: set[str] = set()
        out = []
        for t in texts:
            if not t.strip():
                continue  # wholly editorial: no vector, as in scripts.embed
            s = text_sha(t)
            if s not in self.raw and s not in seen:
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
        if self.offline:
            return 0
        if self._embed is None:
            raise NeedsVectors(f"{self.work_id}: {len(todo):,} texts (~{tokens:,} tokens) "
                               "need vectors: run scripts.anchor with --pay", tokens)
        if self.budget_tokens is not None and self.sent_tokens + tokens > self.budget_tokens:
            raise NeedsVectors(f"{self.work_id}: embedding ~{tokens:,} more tokens would "
                               f"exceed the budget ({self.sent_tokens:,} of "
                               f"{self.budget_tokens:,} used)", tokens)
        vecs = np.asarray(self._embed(todo), dtype=np.float32)
        if len(vecs) != len(todo):
            raise RuntimeError(f"asked for {len(todo)} vectors, got {len(vecs)}")
        for t, v in zip(todo, vecs):
            self._put(text_sha(t), v, self.run, own=True)
        self.sent_tokens += tokens
        self.save()
        return tokens

    def save(self) -> None:
        if self.path is None:
            return
        keys = sorted(self._own)
        runs = {self.runs[k].key: self.runs[k] for k in keys}
        rows = [emb.Row(k, emb.KIND_TEXT, k, self.runs[k].key) for k in keys]
        vecs = np.stack([self.raw[k] for k in keys]).astype(np.float16) if keys else None
        emb.save(self.path, emb.WorkEmbeddings(self.work_id, self.source_path, runs, rows, vecs))


# ------------------------------------------------------------------ segments


@dataclass
class Paragraph:
    """A translation source paragraph: its words (``_atoms``, whitespace kept),
    the provisional cut (word indices where its units start, 0 first) and its
    editorial spans (#236), as offsets into ``"".join(atoms)``."""

    ref: str
    atoms: list[str]
    today: list[int]
    spans: list[editorial.Span] = field(default_factory=list)
    _offsets: list[int] | None = None

    def offset(self, atom: int) -> int:
        """The character offset of *atom* in the joined paragraph."""
        if self._offsets is None or len(self._offsets) != len(self.atoms) + 1:
            offs = [0]
            for a in self.atoms:
                offs.append(offs[-1] + len(a))
            self._offsets = offs
        return self._offsets[atom]


def paragraphs_of(units: Units) -> list[Paragraph]:
    """The translation's source paragraphs, rebuilt from its units. Word indices
    agree with ``patristica.anchoring.words`` of the paragraph."""
    out: list[Paragraph] = []
    last: str | None = None
    spans = units.spans or [[] for _ in units.texts]
    for ref, text, sp in zip(units.refs, units.texts, spans):
        parent = ref.rsplit(".", 1)[0] if is_derived_ref(ref) else ref
        if parent != ref and parent == last and out:
            para = out[-1]
            at = len("".join(para.atoms)) + 1  # the unit follows a space
            para.today.append(len(para.atoms))
            para.atoms.extend(_atoms(" " + text))
            para.spans.extend((a + at, b + at, k) for a, b, k in sp)
        else:
            out.append(Paragraph(parent, _atoms(text), [0], list(sp)))
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
    key: str = ""  # the text embedded: without editorial material (``embed_text``)


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
                                   embed_text(paras, p, prev, stop)))
            elif out and out[-1].para == p:
                out[-1].a1 = stop
                out[-1].key = embed_text(paras, p, out[-1].a0, stop)
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


def embed_text(paras: Sequence[Paragraph], para: int, a0: int, a1: int) -> str:
    """What a piece embeds: its text without editorial material (#236), as
    ``editorial.source_text`` gives it for a unit with that text. Cut positions
    stay word positions of the full text."""
    pa = paras[para]
    raw = "".join(pa.atoms[a0:a1])
    text = raw.strip()
    if not pa.spans or not text:
        return text
    start = pa.offset(a0) + len(raw) - len(raw.lstrip())
    return editorial.strip(text, editorial.clip(pa.spans, start, start + len(text)))


def _parts(segs: Sequence[Segment], j0: int, j1: int) -> list[tuple[int, int, int]]:
    """Segments [j0, j1) as (paragraph, a0, a1), one per paragraph."""
    out: list[tuple[int, int, int]] = []
    for s in segs[j0:j1]:
        if out and out[-1][0] == s.para:
            out[-1] = (s.para, out[-1][1], s.a1)
        else:
            out.append((s.para, s.a0, s.a1))
    return out


# --------------------------------------------------------------- calibration


@dataclass(frozen=True)
class Calibration:
    """Maps a summed-segments margin onto the exact-vector margin scale: a·m + b."""

    a: float = 1.0
    b: float = 0.0

    def __call__(self, m: np.ndarray) -> np.ndarray:
        return self.a * m + self.b


def calibrate(paras: Sequence[Paragraph], segs: Sequence[Segment], seg_vecs: np.ndarray,
              today: Units, orig: Units, today_beads: Sequence[Bead],
              min_points: int = 20) -> Calibration:
    """Fit exact margin ≈ a · summed-segments margin + b on the provisional
    cut's confident 1:1 beads whose unit is more than one segment."""
    omean = orig.vecs.mean(axis=0)
    seg_of_unit: list[list[int]] = []
    u_index: dict[tuple[int, int], int] = {}
    for p, para in enumerate(paras):
        for a in para.today:
            u_index[(p, a)] = len(seg_of_unit)
            seg_of_unit.append([])
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
        norm = np.linalg.norm(s)
        if norm == 0:
            continue
        s = s / norm
        xs.append(float(s @ v) - float(s @ omean))
        ys.append(float(e @ v) - float(e @ omean))
    if len(xs) < min_points:
        return Calibration()
    a, b = np.polyfit(xs, ys, 1)
    return Calibration(float(a), float(b))


# --------------------------------------------------------------------- the DP


#: Partial translations (#394). The original is restricted to the span the
#: translation covers only when the part left out at either end is at least
#: this many units and this share of the original: a translation of the whole
#: work is refined on the whole original, exactly as before. Frozen like
#: ``RefineParams`` (changing them can re-cut partial translations), but kept
#: out of it and out of the method hash, since they leave every whole
#: translation's cut unchanged; a restricted cut records its span in its stats.
COVER_MIN_GAP = 20
COVER_MIN_SHARE = 0.05
#: The provisional cut's alignment is trusted only when its confident
#: monotone chain has this many beads and holds this share of the
#: translation's units; else the whole original is used. Weak vectors (a rare
#: language's own text against English) align a tenth or less of the units,
#: and their stray matches would make a whole translation look partial.
COVER_MIN_BEADS = 3
COVER_MIN_ALIGNED = 0.5
#: An end of the chain is set aside as a stray match when it is reached by a
#: jump on the original side this much longer than on the translation side…
COVER_JUMP = 12
#: …and the beads beyond the jump are at most this share of the chain.
COVER_MAX_STRAY = 0.1


def covered_span(today_beads: Sequence[Bead], n_orig: int, n_trans: int,
                 pad: int) -> tuple[int, int]:
    """The original units ``[k0, k1)`` the translation covers (#394).

    Read from the provisional cut's alignment with the whole original
    (*today_beads*, ``align_pair``: the passage aligner on the stored vectors,
    so no extra vectors and no dependence on ``data/alignments``, which is
    made after this step): the original units from the first to the last bead
    of its confident monotone chain, less a stray match at either end (a few
    end beads reached by a long jump on the original side only, such as a
    similar passage in an untranslated part), widened by *pad* units. An end
    is moved in only when it leaves out at least ``COVER_MIN_GAP`` units and
    ``COVER_MIN_SHARE`` of the original; otherwise it stays at 0 or
    *n_orig*, so a whole translation gets ``(0, n_orig)``, and so does one
    whose alignment is too thin to trust (``COVER_MIN_BEADS``,
    ``COVER_MIN_ALIGNED``).
    """
    confident = [bd for bd in today_beads if bd.conf >= 0.5]
    chain = set(anchor_chain([(bd.i0, bd.j0) for bd in confident]))
    beads = sorted((bd for bd in confident if (bd.i0, bd.j0) in chain), key=lambda b: b.i0)
    if (len(beads) < COVER_MIN_BEADS
            or sum(bd.i1 - bd.i0 for bd in beads) < COVER_MIN_ALIGNED * n_trans):
        return 0, n_orig
    stray = max(1, int(COVER_MAX_STRAY * len(beads)))

    def jump(a: Bead, b: Bead) -> bool:
        return (b.j0 - a.j1) - (b.i0 - a.i1) > COVER_JUMP

    first, last = 0, len(beads)
    for t in range(1, stray + 1):  # the innermost jump among the last *stray* beads
        if jump(beads[-t - 1], beads[-t]):
            last = len(beads) - t
    for t in range(stray):
        if jump(beads[t], beads[t + 1]):
            first = t + 1
    k0, k1 = beads[first].j0, beads[last - 1].j1
    gap = max(COVER_MIN_GAP, COVER_MIN_SHARE * n_orig)
    lo = max(k0 - pad, 0) if k0 >= gap else 0
    hi = min(k1 + pad, n_orig) if n_orig - k1 >= gap else n_orig
    return lo, hi


def provisional_band(n_orig: int, segs: Sequence[Segment], paras: Sequence[Paragraph],
                     today_beads: Sequence[Bead], width: int) -> tuple[np.ndarray, np.ndarray]:
    """Per segment boundary j (0..M), the range of original units the DP may be at.

    Estimated from the provisional cut's alignment (*today_beads*: A = the
    translation's provisional units, B = original units; the confident
    monotone chain), interpolated where it is unaligned. A row is widened
    where the translation skips a block, so the band never cuts the path off.
    """
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
    hi[:-1] = np.maximum(hi[:-1], lo[1:])
    return lo, hi


@dataclass
class _Runs:
    """The candidate runs ending at one segment boundary j: run lengths, their
    paragraph crossings and the hashes of their parts (one per paragraph)."""

    lengths: np.ndarray  # int64
    crosses: np.ndarray  # float64
    keys: list[tuple[str, ...]]


def _candidate_runs(segs: Sequence[Segment], paras: Sequence[Paragraph], j: int,
                    p: RefineParams, max_tok: float) -> _Runs:
    lengths, crosses, keys = [], [], []
    tokens = 0
    cross = 0
    for L in range(1, min(p.max_segments, j) + 1):
        s = segs[j - L]
        if L > 1 and s.para != segs[j - L + 1].para:
            cross += 1
        tokens += s.tokens
        if tokens > max_tok and L > 1:
            break
        lengths.append(L)
        crosses.append(cross)
        parts = (embed_text(paras, q, a0, a1) for q, a0, a1 in _parts(segs, j - L, j))
        keys.append(tuple(text_sha(t) for t in parts if t.strip()))
    return _Runs(np.array(lengths, dtype=np.int64), np.array(crosses, dtype=np.float64), keys)


def segment_dp(orig: np.ndarray, orig_base: np.ndarray, segs: Sequence[Segment],
               seg_vecs: np.ndarray, paras: Sequence[Paragraph],
               lo: np.ndarray, hi: np.ndarray, cache: VectorCache, calib: Calibration,
               language: str, p: RefineParams, exact_only: bool = False,
               runs: Sequence[_Runs] | None = None,
               ) -> tuple[list[tuple[int, int, int, int]], list[int], list[bool]]:
    """The best beads (k0, k1, j0, j1), the skipped segments, and per bead
    whether it was scored with exact vectors.

    *orig* are the original's unit vectors (normalized), *orig_base* their
    baselines (mean similarity to the translation's units); a piece's baseline
    is its cosine with the mean of *orig*. For each segment boundary j, the
    vectors of every candidate run ending there are scored against the band's
    original units in one matrix product; candidates are ordered run length
    first, then original units, and the first best wins (as a plain loop
    would choose). *runs* are :func:`all_runs` (computed here when not given).
    """
    n, m = len(orig), len(segs)
    omean = orig.mean(axis=0).astype(np.float64)
    orig64 = orig.astype(np.float64)
    if runs is None:
        runs = all_runs(segs, paras, language, p)
    A = p.max_originals
    # |Σ of a consecutive original units ending before k|, for k = 0..n.
    vnorm: dict[int, np.ndarray] = {}
    window = np.zeros_like(orig64)
    for a in range(1, A + 1):
        if a == 1:
            window = orig64.copy()
        else:
            window = window[:-1] + orig64[a - 1:]
        norms = np.zeros(n + 1)
        norms[a:] = np.linalg.norm(window, axis=1)
        vnorm[a] = norms
    cb = np.concatenate([[0.0], np.cumsum(orig_base)])
    rows: dict[int, np.ndarray] = {}
    bps: list[np.ndarray] = []
    exact_at: list[np.ndarray] = []
    SKIP_SEG, SKIP_ORIG = -1, -2
    for j in range(m + 1):
        ks = np.arange(lo[j], hi[j] + 1)
        best = np.full(len(ks), NEG)
        bp = np.full(len(ks), SKIP_ORIG, dtype=np.int64)
        ex = np.zeros(len(ks), dtype=bool)
        if j == 0:
            best[ks == 0] = 0.0
        else:
            prev = _fetch(rows, lo, j - 1, ks) - p.skip_segment
            better = prev > best
            best[better] = prev[better]
            bp[better] = SKIP_SEG
            _score_runs(j, runs[j], ks, best, bp, ex, rows, lo, hi, orig64, omean, vnorm, cb,
                        segs, seg_vecs, cache, calib, p, exact_only)
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
            exact_beads.append(bool(exact_at[j][k - lo[j]]))
            j, k = j - L, k - a
    return beads[::-1], skipped[::-1], exact_beads[::-1]


def all_runs(segs: Sequence[Segment], paras: Sequence[Paragraph], language: str,
             p: RefineParams) -> list[_Runs]:
    """The candidate runs of every segment boundary 0..M (the same in every round)."""
    max_tok = p.max_tokens_verses * VERSE_TOKENS[language]
    empty = _Runs(np.zeros(0, dtype=np.int64), np.zeros(0), [])
    return [empty] + [_candidate_runs(segs, paras, j, p, max_tok)
                      for j in range(1, len(segs) + 1)]


def _score_runs(j: int, runs: _Runs, ks: np.ndarray, best: np.ndarray, bp: np.ndarray,
                ex: np.ndarray, rows: dict[int, np.ndarray], lo: np.ndarray, hi: np.ndarray,
                orig: np.ndarray, omean: np.ndarray, vnorm: dict[int, np.ndarray],
                cb: np.ndarray, segs: Sequence[Segment], seg_vecs: np.ndarray,
                cache: VectorCache, calib: Calibration, p: RefineParams,
                exact_only: bool) -> None:
    """Every bead ending at segment boundary *j*, in place on row *j*."""
    if not len(runs.lengths):
        return
    # The runs' vectors: exact where every part is cached, else the segments' sum.
    acc = np.cumsum(seg_vecs[j - runs.lengths[-1]:j][::-1], axis=0)
    W = acc[runs.lengths - 1].copy()
    exact = np.zeros(len(runs.lengths), dtype=bool)
    for r, key in enumerate(runs.keys):
        parts = [cache.get_sha(s) for s in key]
        if not parts:  # wholly editorial: no vector (dropped below)
            W[r] = 0.0
            exact[r] = True
        elif all(v is not None for v in parts):
            W[r] = np.sum(parts, axis=0)
            exact[r] = True
    keep = exact if exact_only else np.ones(len(exact), dtype=bool)
    norms = np.linalg.norm(W, axis=1)
    keep &= norms > 0
    if not keep.any():
        return
    Ls, crosses, exact, W = runs.lengths[keep], runs.crosses[keep], exact[keep], W[keep]
    W = W / norms[keep][:, None]
    A = p.max_originals
    k_lo = max(int(lo[j]) - A, 0)
    dots = orig[k_lo:int(hi[j])] @ W.T  # (band units × runs)
    cd = np.vstack([np.zeros((1, len(Ls))), np.cumsum(dots, axis=0)])
    tbase = W @ omean  # (runs)
    end_cost = p.break_cost[segs[j - 1].end]
    # Previous rows at k − a for every run: rows[j − L] fetched once per run.
    base_k = int(ks[0]) - A
    span = np.arange(base_k, int(ks[-1]) + 1)
    prev = np.stack([_fetch(rows, lo, j - int(L), span) for L in Ls], axis=1)  # (span × runs)
    cand = np.full((len(ks), len(Ls), A), NEG)
    for a in range(1, A + 1):
        sel = ks - a >= 0
        kk = ks[sel]
        if not len(kk):
            continue
        prevk = prev[kk - a - base_k]  # (kk × runs)
        num = cd[kk - k_lo] - cd[kk - a - k_lo]
        den = vnorm[a][kk][:, None]
        cos = np.where(den > 0, num / np.where(den > 0, den, 1.0), 0.0)
        base = (((cb[kk] - cb[kk - a]) / a)[:, None] + tbase[None, :]) / 2
        marg = cos - base
        marg = np.where(exact[None, :], marg, calib(marg) - p.unembedded)
        gain = (math.sqrt(a) * (marg - p.margin) - p.merge_penalty * (a - 1)
                - end_cost - p.cross_paragraph * crosses[None, :])
        cand[sel, :, a - 1] = np.where(prevk > NEG / 2, prevk + gain, NEG)
    flat = cand.reshape(len(ks), -1)  # run-major, then a: the order a plain loop takes
    pick = np.argmax(flat, axis=1)
    top = flat[np.arange(len(ks)), pick]
    better = top > best
    if better.any():
        r, a = np.divmod(pick[better], A)
        best[better] = top[better]
        bp[better] = Ls[r] * 16 + (a + 1)
        ex[better] = exact[r]


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
    no bead touches keeps its provisional cut (returned as a fallback).
    """
    owner = [-1] * len(segs)
    for b, (_, _, j0, j1) in enumerate(beads):
        for j in range(j0, j1):
            owner[j] = b
    for j in skipped:
        owner[j] = -1
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


# ------------------------------------------------------------------ the loop


@dataclass
class Result:
    """A refined cut: per translation paragraph, the atom ranges of its units."""

    paras: list[Paragraph]
    pieces: list[list[tuple[int, int]]]
    beads: list[tuple[int, int, int, int]]
    rounds: int
    converged: bool
    calibration: Calibration
    fallback_paragraphs: set[int] = field(default_factory=set)
    history: list[dict] = field(default_factory=list)
    #: The original units ``[k0, k1)`` the cut was refined on, when the
    #: translation covers only part of its original (#394; ``covered_span``),
    #: else None (the whole original). ``beads`` count units of the whole.
    span: tuple[int, int] | None = None

    def texts(self) -> list[str]:
        return [piece_text(self.paras, p, a0, a1)
                for p, ps in enumerate(self.pieces) for a0, a1 in ps]

    def embed_texts(self) -> list[str]:
        """The units' texts as embedded (without editorial material)."""
        return [embed_text(self.paras, p, a0, a1)
                for p, ps in enumerate(self.pieces) for a0, a1 in ps]

    def starts(self) -> list[list[int]]:
        """Per paragraph, the word index where each unit starts."""
        return [[a0 for a0, _ in ps] for ps in self.pieces]

    def stats(self, n_orig: int) -> dict:
        """What a cut file records of the run. ``one_one`` is the share of the
        original's units in a 1:1 bead: of the covered span's units when the
        original was restricted (#394), which is then recorded as ``span``."""
        if self.span is not None:
            n_orig = self.span[1] - self.span[0]
        one = sum(1 for k0, k1, j0, j1 in self.beads if k1 - k0 == 1)
        out = {"rounds": self.rounds, "converged": self.converged,
               "beads": len(self.beads),
               "one_one": round(one / n_orig, 4) if n_orig else 0.0,
               "units": sum(len(ps) for ps in self.pieces),
               "fallback_paragraphs": len(self.fallback_paragraphs),
               "calibration": [round(self.calibration.a, 4), round(self.calibration.b, 4)]}
        if self.span is not None:
            out["span"] = list(self.span)
        return out


def wants_vector(text: str) -> bool:
    """Whether ``scripts.embed`` gives a unit with this text a vector."""
    return len(text.strip()) >= emb.MIN_CHARS


def first_texts(today: Units, language: str) -> list[str]:
    """What the first embed sends at most: the segments and the provisional units."""
    paras = paragraphs_of(today)
    segs = segments_of(paras, language)
    return [s.key for s in segs] + [t for t in today.source_texts() if wants_vector(t)]


def refine(orig: Units, today: Units, cache: VectorCache, p: RefineParams = RefineParams(),
           params: Params | None = None, restrict: bool = True) -> Result:
    """Refine *today*'s (provisional) cut of the translation on *orig*.

    *cache* holds whatever vectors are known (seeded with the stored vectors of
    the provisional units); the segments and any provisional unit without a
    vector are embedded first (raising ``NeedsVectors`` without an embedder).

    When the translation covers only part of *orig* (:func:`covered_span` on
    the provisional cut's alignment, #394), the refinement runs on that part:
    the band, baselines, calibration and statistics see only the covered
    units, and ``Result.span`` records them. For a whole translation nothing
    changes. ``restrict=False`` always uses the whole original (as before
    #394; for ``scripts.anchor_eval``).
    """
    paras = paragraphs_of(today)
    segs = segments_of(paras, today.language)
    seg_texts = [s.key for s in segs]
    sources = today.source_texts()
    unit_texts = [t for t in sources if wants_vector(t)]
    log.info("%s: %d paragraphs, %d segments; first embed ~%d tokens",
             today.work_id, len(paras), len(segs), cache.estimate(seg_texts + unit_texts))
    cache.ensure(seg_texts + unit_texts)
    dims = orig.vecs.shape[1]
    seg_vecs = np.zeros((len(segs), dims))
    for j, t in enumerate(seg_texts):
        v = cache.get(t) if t.strip() else None
        if v is not None:
            seg_vecs[j] = v
    tvecs = np.zeros((len(today.texts), dims), dtype=np.float32)
    for u, t in enumerate(sources):
        v = cache.get(t) if t.strip() else None
        if v is not None:
            tvecs[u] = v
    today = Units(today.work_id, today.language, today.refs, today.texts, tvecs, today.spans)
    today_beads = align_pair(today.version(), orig.version(), params)
    # A partial translation (#394): refine on the part of the original it
    # covers, so its tail isn't cut against untranslated text. A whole
    # translation keeps the whole original (and this exact code path).
    n_all = len(orig.texts)
    span: tuple[int, int] | None = (covered_span(today_beads, n_all, len(today.texts), p.band)
                                    if restrict else (0, n_all))
    if span == (0, n_all):
        span = None
    else:
        log.info("%s covers original units %d–%d of %d (%s … %s): refining on those",
                 today.work_id, span[0], span[1], n_all, orig.refs[span[0]],
                 orig.refs[span[1] - 1])
        orig = orig.slice(*span)
        today_beads = align_pair(today.version(), orig.version(), params)
    shift = span[0] if span is not None else 0
    lo, hi = provisional_band(len(orig.texts), segs, paras, today_beads, p.band)
    calib = calibrate(paras, segs, seg_vecs, today, orig, today_beads, p.min_calibration)
    log.info("calibration: exact ≈ %.3f · summed + %.3f", calib.a, calib.b)
    have = tvecs[np.abs(tvecs).sum(axis=1) > 0]
    orig_base = orig.vecs @ (have.mean(axis=0) if len(have) else np.zeros(orig.vecs.shape[1]))
    runs = all_runs(segs, paras, today.language, p)
    history: list[dict] = []
    result: Result | None = None
    for r in range(1, p.max_rounds + 2):
        final = r == p.max_rounds + 1
        beads, skipped, exact = segment_dp(orig.vecs, orig_base.astype(np.float64), segs,
                                           seg_vecs, paras, lo, hi, cache, calib,
                                           today.language, p, exact_only=final, runs=runs)
        pieces, fallback = pieces_from(beads, skipped, segs, paras)
        if shift:
            beads = [(k0 + shift, k1 + shift, j0, j1) for k0, k1, j0, j1 in beads]
        result = Result(paras, pieces, beads, r, False, calib, fallback, history, span)
        texts = [t for t in result.embed_texts() if wants_vector(t)]
        todo = cache.missing(texts)
        history.append({"round": r, "exact_only": final, "units": len(result.texts()),
                        "beads": len(beads), "exact_beads": int(sum(exact)),
                        "new_units": len(todo), "new_tokens": cache.estimate(texts)})
        log.info("round %d: %s", r, history[-1])
        if not todo:
            result.converged = not final
            break
        # The final units are embedded anyway (they need production vectors).
        # After the exact-only round the only new texts are units that took in
        # a skipped segment (an addition of the translation).
        cache.ensure(texts)
        if final:
            break
    assert result is not None
    return result
