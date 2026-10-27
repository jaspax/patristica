"""Derived verses anchored on the original (#292, the go-forward part of #200).

Derived verses (#2, ``patristica.versify``) are cut in every work on its own,
at a per-language size, so the versions of one work are cut at different
places and parallel reading shows rows that start and end at different words.
An *anchored* work is cut where its text corresponds to the derived-verse
boundaries of its *anchor*, the work it was translated from, so that most rows
become 1:1. Existing works are not anchored (re-cutting them renumbers refs that
are reader URLs and translation keys; that migration is #200's): anchoring
applies only to the sources enrolled in :data:`ENROLMENT_PATH`.

**Enrolment** is per source (``patristica/data/anchored_sources.csv``,
``source_id,reason``). A new language arrives as a new source, so one row
enrols every work of it from its first normalize, and a work of an existing
source can't be enrolled by accident. A source is enrolled before its first
normalize, never after (that would re-cut published refs).

**The anchor** of an enrolled work is its ``Work.translation_of`` (curated or
set by the ingestor, #153): the edition the translator actually read, which
for an ancient version is the designated edition of #153's table. A work with
no ``translation_of``, or whose target is not in the corpus yet, is cut as
today. A target in the work's own language is another edition of the same
text, which needs a text-level alignment (#199): :func:`same_language_units`
is the hook for it and returns None until #199 lands, so such a work is cut
as today.

**Projection** (:func:`project`), with no vectors, deterministic, at
normalize time:

1. Both works are read as *source paragraphs* (a chunk before the split; the
   anchor's are rebuilt from its derived verses), and each paragraph as
   *segments*: runs of text ending at sentence or clause punctuation
   (``versify``'s break strengths). The anchor's unit boundaries are always
   segment boundaries.
2. The paragraphs are aligned by length (:func:`align_lengths`, Gale and
   Church 1993: a monotonic dynamic program whose beads join up to three items
   of either side and are scored by how far their lengths are from the
   expected ratio, which is the two texts' own overall ratio). Paragraph
   boundaries the alignment is sure of (a margin of at least
   ``PARAGRAPHS.min_margin`` over every alternative) cut the two works into
   *windows*.
3. Within each window the segments are aligned the same way, with bonuses
   where both sides start a paragraph, end a sentence or end a question.
   Every anchor unit boundary the alignment is sure of is *projected*: the
   translation is cut at the segment boundary it maps to.
4. A stretch of the translation between two projected boundaries one anchor
   unit apart is one derived verse (a 1:1 row). Any other stretch is cut by
   ``versify.split_text`` at the size of the anchor's units in this
   translation (the window's translation tokens per anchor unit), so units
   stay comparable in size; a paragraph with no counterpart at all is cut at
   the language's own verse size, as today. Derived verses never cross source
   paragraphs.
5. A *free* translation (a paraphrase, another recension) keeps few of the
   original's sentences, and lengths can't align it: when the best path maps
   fewer than :data:`MIN_SENTENCE_AGREEMENT` of the anchor's sentence ends to
   sentence ends, the whole work is cut as today.

Margins are sums of squares and constants (no ``exp``/``log``), so results
are the same on every platform.

**Why lengths at normalize time, not vectors.** The vectors that align
passages (#179) don't exist for a new work until after ``scripts.embed``, and
they are vectors of its units, so cutting on them would mean cutting, embedding
(paid), re-cutting and embedding the changed units again, with refs changing
after their first publish. Lengths need nothing but the two texts, so the refs
are final before anything is translated, embedded or published, and normalize
stays free and deterministic. A wrong projection only costs a 1:1 row: the
passage alignment still pairs the units by their vectors afterwards.

**Determinism and staleness (#130).** A work's split now also depends on its
anchor's cuts. ``scripts.normalize`` records ``{"work_id", "cuts"}``
(:func:`cuts_hash`, a hash of the anchor's refs and texts) in the work's line
of ``_fingerprints.jsonl``, normalizes enrolled works after every other work
(and anchors before the works anchored on them), and rebuilds an anchored work
whenever the record changes, so a change to an original re-splits its anchored
translations.
"""

from __future__ import annotations

import csv
import json
import math
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

from patristica import fingerprint
from patristica.models import Chunk
from patristica.versify import (
    _CLOSERS,
    CLAUSE,
    SENTENCE,
    _atoms,
    _strength,
    count_tokens,
    is_derived_ref,
    split_text,
)

ENROLMENT_PATH = Path(__file__).parent / "data" / "anchored_sources.csv"

_DERIVED_SUFFIX = re.compile(r"\.s\d+$")


class AnchoringError(ValueError):
    """The enrolment table is malformed, or anchors form a cycle."""


# ---------------------------------------------------------------- enrolment


def load_enrolment(path: Path = ENROLMENT_PATH) -> dict[str, str]:
    """``{source_id: reason}`` from the enrolment table."""
    sources: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            source = (row.get("source_id") or "").strip()
            reason = (row.get("reason") or "").strip()
            where = f"{path}:{line}"
            if not source or "/" in source:
                raise AnchoringError(f"{where}: bad source_id {source!r}")
            if not reason:
                raise AnchoringError(f"{where}: {source}: no reason given")
            if source in sources:
                raise AnchoringError(f"{where}: {source} is listed twice")
            sources[source] = reason
    return sources


@cache
def enrolled_sources() -> dict[str, str]:
    return load_enrolment()


def is_enrolled(source_id: str) -> bool:
    """True if the works of *source_id* get anchored derived verses."""
    return source_id in enrolled_sources()


def anchor_id(work: Mapping[str, object]) -> str | None:
    """The work an enrolled work is anchored on: its ``translation_of``, or None."""
    target = work.get("translation_of")
    return target if isinstance(target, str) and target else None


# ------------------------------------------------------------------ anchors


@dataclass(frozen=True)
class Anchor:
    """An anchor work as its normalized chunks: ``(canonical_ref, text)`` in order."""

    work_id: str
    language: str
    units: tuple[tuple[str, str], ...]

    @classmethod
    def from_chunks(cls, work_id: str, chunks: Sequence[Mapping[str, object]]) -> Anchor:
        if not chunks:
            raise AnchoringError(f"anchor {work_id} has no chunks")
        language = str(chunks[0]["language"])
        return cls(work_id, language,
                   tuple((str(c["canonical_ref"]), str(c["text"])) for c in chunks))

    @classmethod
    def load(cls, path: Path, work_id: str) -> Anchor:
        return cls.from_chunks(work_id, json.loads(path.read_text(encoding="utf-8")))

    @property
    def cuts(self) -> str:
        return cuts_hash(self.units)

    def record(self) -> dict[str, str | None]:
        """What ``_fingerprints.jsonl`` records for a work anchored on this one."""
        return {"work_id": self.work_id, "cuts": self.cuts}

    def paragraphs(self) -> list[list[str]]:
        """The anchor's source paragraphs, each as the texts of its units.

        Consecutive derived verses of one chunk (``ref.s1``, ``ref.s2``, …)
        are one paragraph; any other chunk is a paragraph of one unit.
        """
        paras: list[list[str]] = []
        last: str | None = None
        for ref, text in self.units:
            parent = _DERIVED_SUFFIX.sub("", ref)
            if parent != ref and parent == last:
                paras[-1].append(text)
            else:
                paras.append([text])
            last = parent if parent != ref else None
        return paras


def cuts_hash(units: Sequence[tuple[str, str]]) -> str:
    """Hash of an anchor's cuts: its units' refs and texts, in order."""
    return fingerprint.value_hash([[ref, text] for ref, text in units])


#: The anchor record of an enrolled work that is not anchored (no
#: ``translation_of``, an anchor not in the corpus, or one in its own language).
UNANCHORED: dict[str, str | None] = {"work_id": None, "cuts": None}


# ------------------------------------------------------- length alignment


@dataclass(frozen=True)
class AlignParams:
    """Settings of :func:`align_lengths`.

    ``beads`` are ``(items of A, items of B, cost)``; the cost is the prior
    (−ln P) of the bead shape, from Gale and Church's counts, with 3:1 and 1:3
    added for long periods translated as several sentences. ``variance`` is
    the variance of the length difference per character. ``band`` limits the
    search to cells whose positions (as a fraction of each side's length) are
    within ``band`` of each other, widened by ``min_band`` items.
    ``min_margin`` is how much worse every alternative must be for a boundary
    to count as sure.
    """

    beads: tuple[tuple[int, int, float], ...]
    variance: float
    band: float
    min_band: int
    min_margin: float
    #: Bonuses for a node (segments only) where both sides start a paragraph,
    #: end a sentence, or end a question.
    paragraph_bonus: float = 0.0
    sentence_bonus: float = 0.0
    question_bonus: float = 0.0


#: Chosen with ``scripts.anchor_eval`` on Augustine's Tractates (Latin → English)
#: and Basil's letters (Greek → English): a paragraph boundary needs a margin of
#: 10 to bound a window (lower lets misaligned windows through where a
#: translation leaves out a passage), a unit boundary 3 to be projected (2: more
#: boundaries, but ~6 points fewer agree with the passage alignment on Basil).
#: Changing them re-cuts every enrolled work.
PARAGRAPHS = AlignParams(
    beads=((1, 1, 0.12), (1, 0, 5.3), (0, 1, 5.3), (2, 1, 3.1), (1, 2, 3.1),
           (2, 2, 4.5), (3, 1, 5.3), (1, 3, 5.3)),
    variance=6.8, band=0.08, min_band=12, min_margin=10.0)
SEGMENTS = AlignParams(
    beads=((1, 1, 0.12), (1, 0, 5.3), (0, 1, 5.3), (2, 1, 2.4), (1, 2, 2.4),
           (2, 2, 4.5), (3, 1, 4.0), (1, 3, 4.0)),
    variance=6.8, band=0.15, min_band=12, min_margin=3.0, paragraph_bonus=2.0,
    sentence_bonus=1.5, question_bonus=1.5)


@dataclass(frozen=True)
class LengthAlignment:
    """Result of :func:`align_lengths`.

    ``boundary[i]`` for ``0 < i < len(a)``: the boundary of B that A's
    boundary ``i`` (between items ``i − 1`` and ``i``) maps to on the best
    path, and its margin: how much more the best path that doesn't map it
    there costs (≤ 0 when the best path joins items ``i − 1`` and ``i``).
    """

    total: float
    boundary: dict[int, tuple[int, float]] = field(default_factory=dict)


def _match_cost(la: float, lb: float, ratio: float, variance: float) -> float:
    """Gale–Church: (lb − ratio·la)² / (2·variance·mean length)."""
    mean = (la + lb / ratio) / 2.0
    if mean <= 0.0:
        return 0.0
    d = lb - ratio * la
    return d * d / (2.0 * variance * mean)


def _band(pa: Sequence[float], pb: Sequence[float], params: AlignParams
          ) -> tuple[list[int], list[int]]:
    """Per row ``i``, the columns ``lo[i] … hi[i]`` the search may use."""
    n, m = len(pa) - 1, len(pb) - 1
    ta, tb = pa[-1] or 1.0, pb[-1] or 1.0
    lo: list[int] = []
    hi: list[int] = []
    j_lo = j_hi = 0
    for i in range(n + 1):
        fa = pa[i] / ta
        while j_lo < m and pb[j_lo] / tb < fa - params.band:
            j_lo += 1
        j_hi = max(j_hi, j_lo)
        while j_hi < m and pb[j_hi + 1] / tb <= fa + params.band:
            j_hi += 1
        lo.append(max(0, j_lo - params.min_band))
        hi.append(min(m, j_hi + params.min_band))
    lo[0], hi[n] = 0, m
    for i in range(1, n + 1):  # monotone and connected
        lo[i] = max(lo[i], lo[i - 1])
    for i in range(n - 1, -1, -1):
        hi[i] = min(hi[i], hi[i + 1])
    for i in range(n):
        hi[i] = max(hi[i], lo[i + 1], lo[i])
    return lo, hi


def align_lengths(
    a: Sequence[float],
    b: Sequence[float],
    params: AlignParams,
    bonus: Callable[[int, int], float] | None = None,
) -> LengthAlignment:
    """Align two sequences of item lengths (Gale–Church), with margins.

    *bonus(i, j)* lowers the cost of every path through node ``(i, j)``.
    Runs a forward and a backward pass over the band; a boundary's margin is
    the cheaper of the best path through another node of its row and the
    best path whose bead spans it.
    """
    n, m = len(a), len(b)
    pa = [0.0]
    for x in a:
        pa.append(pa[-1] + x)
    pb = [0.0]
    for x in b:
        pb.append(pb[-1] + x)
    ratio = pb[-1] / pa[-1] if pa[-1] > 0 and pb[-1] > 0 else 1.0
    lo, hi = _band(pa, pb, params)
    inf = math.inf
    beads = params.beads

    def node_bonus(i: int, j: int) -> float:
        return bonus(i, j) if bonus is not None else 0.0

    def cost(i0: int, j0: int, i1: int, j1: int, prior: float) -> float:
        return prior + _match_cost(pa[i1] - pa[i0], pb[j1] - pb[j0], ratio, params.variance)

    fwd = [[inf] * (hi[i] - lo[i] + 1) for i in range(n + 1)]
    fwd[0][0] = 0.0
    for i in range(n + 1):
        row, li = fwd[i], lo[i]
        for j in range(li, hi[i] + 1):
            if i == 0 and j == 0:
                continue
            best = inf
            for da, db, prior in beads:
                i0, j0 = i - da, j - db
                if i0 < 0 or j0 < lo[i0] or j0 > hi[i0]:
                    continue
                f = fwd[i0][j0 - lo[i0]]
                if f == inf:
                    continue
                c = f + cost(i0, j0, i, j, prior)
                if c < best:
                    best = c
            if best < inf:
                best -= node_bonus(i, j)
            row[j - li] = best

    bwd = [[inf] * (hi[i] - lo[i] + 1) for i in range(n + 1)]
    bwd[n][m - lo[n]] = 0.0
    for i in range(n, -1, -1):
        row, li = bwd[i], lo[i]
        for j in range(hi[i], li - 1, -1):
            if i == n and j == m:
                continue
            best = inf
            for da, db, prior in beads:
                i1, j1 = i + da, j + db
                if i1 > n or j1 < lo[i1] or j1 > hi[i1]:
                    continue
                g = bwd[i1][j1 - lo[i1]]
                if g == inf:
                    continue
                c = g + cost(i, j, i1, j1, prior) - node_bonus(i1, j1)
                if c < best:
                    best = c
            row[j - li] = best

    total = fwd[n][m - lo[n]]
    # The best path whose bead spans boundary i (joins items i − 1 and i).
    spanned = [inf] * (n + 1)
    for i0 in range(n + 1):
        for j0 in range(lo[i0], hi[i0] + 1):
            f = fwd[i0][j0 - lo[i0]]
            if f == inf:
                continue
            for da, db, prior in beads:
                if da < 2:
                    continue
                i1, j1 = i0 + da, j0 + db
                if i1 > n or j1 < lo[i1] or j1 > hi[i1]:
                    continue
                g = bwd[i1][j1 - lo[i1]]
                if g == inf:
                    continue
                c = f + cost(i0, j0, i1, j1, prior) - node_bonus(i1, j1) + g
                for i in range(i0 + 1, i1):
                    if c < spanned[i]:
                        spanned[i] = c

    boundary: dict[int, tuple[int, float]] = {}
    for i in range(1, n):
        best_j, best, second = -1, inf, inf
        for j in range(lo[i], hi[i] + 1):
            c = fwd[i][j - lo[i]] + bwd[i][j - lo[i]]
            if c < best:
                best_j, best, second = j, c, best
            elif c < second:
                second = c
        if best_j < 0:
            continue
        rival = min(second, spanned[i])
        margin = rival - best if best <= total + 1e-9 else total - best
        boundary[i] = (best_j, round(margin, 6))
    return LengthAlignment(total, boundary)


# ------------------------------------------------------------- segmenting


@dataclass(frozen=True)
class _Para:
    """A paragraph as words (``versify._atoms``) and segments.

    ``ends`` are the atom indices where segments end (ascending, the last is
    ``len(atoms)``); ``lengths`` their non-space character counts.
    """

    atoms: tuple[str, ...]
    ends: tuple[int, ...]
    lengths: tuple[int, ...]
    #: Per segment: ``QUESTION``, ``STATEMENT`` (a sentence end) or ``OTHER``.
    kinds: tuple[int, ...]


OTHER, STATEMENT, QUESTION = range(3)

#: A translation whose best path keeps fewer of the anchor's sentence ends than
#: this is free (a paraphrase, a different recension) and is not anchored:
#: measured 0.88–0.94 for close translations (Augustine's Tractates Latin →
#: English, Basil's letters Greek → English) and ≈ 0.5 for the free Armenian
#: version of Severian's homilies (``scripts.anchor_eval``).
MIN_SENTENCE_AGREEMENT = 0.7

#: Question marks, where they differ from "?" (Greek and Church Slavonic use ";").
_QUESTION_MARKS: dict[str, str] = {
    "grc": ";\u037e",
    "chu": ";\u037e",
    "gez": "\u1367",  # ፧
}
_DEFAULT_QUESTION_MARKS = "?\u061f"  # ? ؟


def _letters(s: str) -> int:
    return sum(1 for ch in s if not ch.isspace())


def _segment(text: str, language: str) -> _Para:
    atoms = _atoms(text)
    n = len(atoms)
    questions = _QUESTION_MARKS.get(language, _DEFAULT_QUESTION_MARKS)
    ends: list[int] = []
    kinds: list[int] = []
    for k in range(n):
        strength = _strength(atoms[k], atoms[k + 1] if k + 1 < n else None, language)
        if k == n - 1 or strength <= CLAUSE:
            ends.append(k + 1)
            if strength != SENTENCE:
                kinds.append(OTHER)
            else:
                core = atoms[k].rstrip("፡").rstrip(_CLOSERS)
                kinds.append(QUESTION if core and core[-1] in questions else STATEMENT)
    if not ends:
        ends, kinds = [n], [OTHER]
    lengths: list[int] = []
    start = 0
    for e in ends:
        lengths.append(_letters("".join(atoms[start:e])))
        start = e
    return _Para(tuple(atoms), tuple(ends), tuple(lengths), tuple(kinds))


# ------------------------------------------------------------- projection


@dataclass
class Projection:
    """The result of :func:`project`.

    ``units`` holds, per translation paragraph, its derived verses' texts.
    ``boundary`` maps each internal anchor unit boundary (``u``: between the
    anchor's units ``u − 1`` and ``u``, counted over the whole work) that was
    projected to ``(paragraph, atom)`` of the translation, and ``margin`` has
    every boundary's margin (absent: no counterpart window).
    """

    units: list[list[str]]
    boundary: dict[int, tuple[int, int]]
    margin: dict[int, float]
    #: Translation paragraphs in a window with no anchor text (cut as today).
    unmatched: set[int]
    #: Where the best path puts every boundary, sure or not (for evaluation).
    candidate: dict[int, tuple[int, int]] = field(default_factory=dict)
    #: Per boundary, the cost per segment of its window's best path (how well
    #: the lengths fit: high for a free translation).
    fit: dict[int, float] = field(default_factory=dict)
    #: The share of the anchor's sentence ends that the best path maps to
    #: sentence ends of the translation; below ``MIN_SENTENCE_AGREEMENT`` the
    #: translation is taken to be free and cut as today.
    sentence_agreement: float = 1.0
    #: The windows ``(i0, i1, j0, j1)``: anchor paragraphs ``i0 … i1 − 1``
    #: against translation paragraphs ``j0 … j1 − 1``; ``window_of`` maps each
    #: anchor boundary aligned inside one to its index.
    windows: list[tuple[int, int, int, int]] = field(default_factory=list)
    window_of: dict[int, int] = field(default_factory=dict)


def project(
    anchor_paragraphs: Sequence[Sequence[str]],
    anchor_language: str,
    paragraphs: Sequence[str],
    language: str,
    paragraph_params: AlignParams = PARAGRAPHS,
    segment_params: AlignParams = SEGMENTS,
) -> Projection:
    """Cut *paragraphs* (a translation's source paragraphs) on the anchor's units.

    *anchor_paragraphs* are the anchor's source paragraphs, each as its
    units' texts (:meth:`Anchor.paragraphs`). See the module docstring.
    """
    # The anchor: segments per unit, so unit ends are segment ends.
    a_seg_len: list[int] = []  # per anchor segment
    a_seg_unit_end: list[int | None] = []  # global unit boundary at the segment's end
    a_seg_kind: list[int] = []
    a_unit_kind: list[int] = []  # per anchor unit: the kind of its last segment
    a_para_first_seg: list[int] = []
    a_para_units: list[int] = []
    a_para_len: list[int] = []
    u = 0
    for para in anchor_paragraphs:
        a_para_first_seg.append(len(a_seg_len))
        a_para_units.append(u)
        total = 0
        for text in para:
            seg = _segment(text, anchor_language)
            a_seg_len.extend(seg.lengths)
            a_seg_kind.extend(seg.kinds)
            a_unit_kind.append(seg.kinds[-1])
            a_seg_unit_end.extend([None] * (len(seg.lengths) - 1))
            u += 1
            a_seg_unit_end.append(u)
            total += sum(seg.lengths)
        a_para_len.append(total)
    n_units = u
    a_para_first_seg.append(len(a_seg_len))
    a_para_units.append(u)

    t_paras = [_segment(text, language) for text in paragraphs]
    t_first_seg: list[int] = []
    t_seg_pos: list[tuple[int, int]] = []  # per segment end: (paragraph, atom)
    t_seg_len: list[int] = []
    t_seg_kind: list[int] = []
    for p, seg in enumerate(t_paras):
        t_first_seg.append(len(t_seg_len))
        t_seg_len.extend(seg.lengths)
        t_seg_kind.extend(seg.kinds)
        t_seg_pos.extend((p, e) for e in seg.ends)
    t_first_seg.append(len(t_seg_len))

    # 1. Paragraph windows.
    para = align_lengths(a_para_len, [sum(s.lengths) for s in t_paras], paragraph_params)
    edges = [(0, 0)]
    for i in sorted(para.boundary):
        j, margin = para.boundary[i]
        if margin >= paragraph_params.min_margin and j >= edges[-1][1]:
            edges.append((i, j))
    edges.append((len(anchor_paragraphs), len(paragraphs)))

    boundary: dict[int, tuple[int, int]] = {}
    margins: dict[int, float] = {}
    candidate: dict[int, tuple[int, int]] = {}
    fit: dict[int, float] = {}
    unmatched: set[int] = set()
    window_target: dict[int, float] = {}  # translation paragraph → tokens per anchor unit
    windows: list[tuple[int, int, int, int]] = []
    window_of: dict[int, int] = {}
    for (i0, j0), (i1, j1) in zip(edges, edges[1:]):
        windows.append((i0, i1, j0, j1))
        if j0 == j1:
            continue
        if i0 == i1:
            unmatched.update(range(j0, j1))
            continue
        units_here = a_para_units[i1] - a_para_units[i0]
        tokens = sum(count_tokens(paragraphs[p]) for p in range(j0, j1))
        for p in range(j0, j1):
            window_target[p] = tokens / units_here
        # The window's edges map onto each other.
        if 0 < a_para_units[i0] < n_units:
            boundary[a_para_units[i0]] = (j0, 0)
            margins[a_para_units[i0]] = math.inf
        # 2. Segments inside the window.
        s0, s1 = a_para_first_seg[i0], a_para_first_seg[i1]
        r0, r1 = t_first_seg[j0], t_first_seg[j1]
        a_starts = {a_para_first_seg[i] - s0 for i in range(i0, i1 + 1)}
        b_starts = {t_first_seg[j] - r0 for j in range(j0, j1 + 1)}

        def bonus(i: int, j: int, a_starts: set[int] = a_starts, b_starts: set[int] = b_starts,
                  s0: int = s0, r0: int = r0) -> float:
            if i in a_starts and j in b_starts:
                return segment_params.paragraph_bonus
            if i == 0 or j == 0:
                return 0.0
            ka, kb = a_seg_kind[s0 + i - 1], t_seg_kind[r0 + j - 1]
            if ka == kb == QUESTION:
                return segment_params.sentence_bonus + segment_params.question_bonus
            if ka != OTHER and kb != OTHER:
                return segment_params.sentence_bonus
            return 0.0

        seg = align_lengths(a_seg_len[s0:s1], t_seg_len[r0:r1], segment_params, bonus)
        for k, (jb, margin) in seg.boundary.items():
            unit = a_seg_unit_end[s0 + k - 1]
            if unit is None:
                continue
            margins[unit] = margin
            window_of[unit] = len(windows) - 1
            fit[unit] = seg.total / (s1 - s0 + r1 - r0)
            pos = t_seg_pos[r0 + jb - 1] if jb > 0 else (j0, 0)
            candidate[unit] = _normal_position(pos, t_paras)
            if margin >= segment_params.min_margin:
                boundary[unit] = pos

    # A free translation doesn't keep the original's sentences, and lengths
    # can't align it: then the work is cut as today.
    t_kind_at = {pos: kind for pos, kind in zip(
        (_normal_position(p, t_paras) for p in t_seg_pos), t_seg_kind)}
    t_kind_at[(0, 0)] = STATEMENT
    ends = [u for u in candidate if a_unit_kind[u - 1] != OTHER]
    kept = sum(1 for u in ends if t_kind_at.get(candidate[u], OTHER) != OTHER)
    sentence_agreement = kept / len(ends) if ends else 0.0
    if sentence_agreement < MIN_SENTENCE_AGREEMENT:
        return Projection([split_text(text, language) for text in paragraphs], {}, margins,
                          set(range(len(paragraphs))), candidate, fit, sentence_agreement,
                          windows, window_of)

    # Monotone: drop a projected boundary that lands before an earlier one.
    last = (-1, -1)
    for unit in sorted(boundary):
        pos = _normal_position(boundary[unit], t_paras)
        if pos < last:
            del boundary[unit]
            continue
        boundary[unit] = pos
        last = pos

    # 3. Cut each translation paragraph. Marks: positions → anchor boundaries,
    # the window edges (also 0 and the end) included.
    marks: dict[tuple[int, int], list[int]] = {}
    for unit, pos in boundary.items():
        marks.setdefault(pos, []).append(unit)
    for i, j in edges:
        if j < len(paragraphs):
            marks.setdefault((j, 0), []).append(a_para_units[i])
        elif paragraphs:
            marks.setdefault((j - 1, len(t_paras[j - 1].atoms)), []).append(a_para_units[i])

    def mark(p: int, atom: int) -> list[int] | None:
        if atom == len(t_paras[p].atoms) and p + 1 < len(t_paras):
            return marks.get((p + 1, 0))
        return marks.get((p, atom))

    units: list[list[str]] = []
    for p, seg in enumerate(t_paras):
        if p in unmatched or p not in window_target:
            units.append(split_text(paragraphs[p], language))
            continue
        stops = sorted({0, len(seg.atoms), *(a for (q, a) in marks if q == p)})
        out: list[str] = []
        for start, stop in zip(stops, stops[1:]):
            text = "".join(seg.atoms[start:stop]).strip()
            if not text:
                continue
            left, right = mark(p, start), mark(p, stop)
            span = min(right) - max(left) if left and right else 0
            if span == 1:
                out.append(text)
            elif span > 1:
                out.extend(split_text(text, language, target=count_tokens(text) / span))
            else:
                out.extend(split_text(text, language, target=window_target[p]))
        units.append(out or [paragraphs[p].strip()])
    return Projection(units, boundary, margins, unmatched, candidate, fit, sentence_agreement,
                      windows, window_of)


def _normal_position(pos: tuple[int, int], paras: Sequence[_Para]) -> tuple[int, int]:
    """A position at the end of a paragraph is the start of the next one."""
    p, atom = pos
    while p + 1 < len(paras) and atom >= len(paras[p].atoms):
        p, atom = p + 1, 0
    return p, atom


# ------------------------------------------------------------------ hooks


def same_language_units(anchor: Anchor, paragraphs: Sequence[str], language: str
                        ) -> list[list[str]] | None:
    """Units of another edition of the anchor in its own language: the #199 hook.

    Two editions of one text share most of their words, so their cuts should
    come from a text-level alignment of the folded text (#199), not from
    lengths (``scripts.anchor_eval`` measures lengths on Basil's letters, Migne
    vs Perseus: far worse than across languages). Until #199 provides one,
    this returns None and the edition is cut as today. Its anchor is still
    recorded, so building this re-splits enrolled editions: build it before an
    enrolled source has same-language editions that are published.
    """
    return None


def anchored_units(
    chunks: Sequence[Chunk], anchor: Anchor
) -> dict[str, list[str]] | None:
    """Derived-verse texts per chunk id for a translation anchored on *anchor*.

    *chunks* are the work's ``Chunk`` objects before the split. Returns None
    when the work can't be anchored this way (same language: the #199 hook
    has nothing yet), so the caller cuts it as today.
    """
    own = [c for c in chunks if not is_derived_ref(c.canonical_ref)]
    if not own:
        return {}
    language = own[0].language
    texts = [c.text for c in own]
    if language == anchor.language:
        same = same_language_units(anchor, texts, language)
        if same is None:
            return None
        return {c.chunk_id: u for c, u in zip(own, same)}
    proj = project(anchor.paragraphs(), anchor.language, texts, language)
    return {c.chunk_id: u for c, u in zip(own, proj.units)}
