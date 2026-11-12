"""Text-level alignment of two editions in one language (#199).

Two editions of one text (Migne's OCR'd Greek and a critical text, a CSEL
volume and the Patrologia Latina) share most of their words. Aligning their
words directly is much more precise than comparing cross-lingual vectors
(``patristica.alignment``), which can tell which passage a unit renders but
not where inside near-identical sentences two editions cut their units.

**Words.** Each unit's source text (``editorial.source_text``) is folded
(``textfold.fold``: diacritics, spelling variants, case) and split on
whitespace (``tokens``); a word remembers its unit. Chinese has no spaces,
so each ideograph is a word of its own (#648); other text is split as before.

**Word alignment** (``align_words``) is monotonic, in the style of patience
diff: within a range of both word lists, the word n-grams that occur exactly
once on each side (trigrams, else bigrams, else words) are paired, cut down to
their longest chain increasing on both sides, and extended forward while the
words agree; the gaps between them are aligned the same way, and a gap small
enough (``Params.small``) is matched by ``difflib``. A range with nothing in
common is left unaligned, so a passage only one edition has stays out.

**Units** (``unit_beads``). Only matched words in runs of at least
``Params.min_run`` count: two different translations in one language match
many function words by chance, two editions match long runs. Two units are
*linked* when they share at least ``Params.link_min`` such words and at
least ``Params.link_frac`` of either unit's words, so a cut a few words apart
doesn't link a unit with its neighbour's. A *bead* is a connected set of
linked units, as a contiguous span on each side (crossing or overlapping
spans are joined, so beads are monotonic). Its *dice* is the share of the two
spans' words that are matched to each other; ``confidence`` maps it to
0–1.

``shared`` is the share of the shorter edition's words in such runs: about
0.6–0.9 for two editions, under 0.1 for different works or translations in
one language, and in between where one text contains part of the other.

The module needs no numpy and has no state; ``scripts.align`` uses it for
same-language members of a version group, and #200 can use ``align_words``
to project derived-verse boundaries from one edition onto another.
"""

from __future__ import annotations

import bisect
import difflib
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import asdict, dataclass

from patristica.textfold import IDEOGRAPH_RE, IDEOGRAPHS, fold

_IDEOGRAPH_SPLIT = re.compile(f"([{IDEOGRAPHS}])")


@dataclass(frozen=True)
class Params:
    """Settings of the text aligner. Recorded with every run (``asdict``)."""

    small: int = 400  # a gap of at most small × small words is matched by difflib
    min_run: int = 3  # matched words count only in runs of this many
    link_min: int = 2  # matched words two units must share to be linked
    link_frac: float = 0.3  # … and this share of either unit's words
    full_dice: float = 0.6  # a bead with this dice (or more) has confidence 1
    min_shared: float = 0.1  # ``shared`` below this: not the same text, don't use

    def to_dict(self) -> dict[str, float | int]:
        return asdict(self)


@dataclass(frozen=True)
class TextBead:
    """Units ``[i0, i1)`` of A and ``[j0, j1)`` of B are the same passage."""

    i0: int
    i1: int
    j0: int
    j1: int
    dice: float  # share of the spans' words matched to each other
    conf: float


@dataclass(frozen=True)
class TextAlignment:
    """The result of ``align_texts``."""

    beads: list[TextBead]
    shared: float  # share of the shorter text's words in matched runs
    matched: int  # words in matched runs (on each side)
    words_a: int
    words_b: int

    @property
    def clean_a(self) -> float:
        """Share of A's own words in matched runs: low where it carries text the
        other lacks (OCR'd page furniture, an apparatus, notes)."""
        return self.matched / self.words_a if self.words_a else 0.0

    @property
    def clean_b(self) -> float:
        return self.matched / self.words_b if self.words_b else 0.0


def tokens(text: str) -> list[str]:
    """The folded words of *text*: ``fold(text).split()``, with every ideograph
    a word of its own (Chinese is written without spaces, #648)."""
    folded = fold(text)
    if not IDEOGRAPH_RE.search(folded):
        return folded.split()
    return _IDEOGRAPH_SPLIT.sub(r" \1 ", folded).split()


def unit_words(texts: Sequence[str]) -> tuple[list[str], list[int]]:
    """The folded words of *texts* in order, and the unit of each word."""
    words: list[str] = []
    unit: list[int] = []
    for u, text in enumerate(texts):
        for w in tokens(text):
            words.append(w)
            unit.append(u)
    return words, unit


def _chain(pairs: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """The longest chain of *pairs* increasing strictly in both coordinates."""
    pairs = sorted(pairs, key=lambda p: (p[0], -p[1]))
    tail_vals: list[int] = []
    tails: list[int] = []
    prev = [-1] * len(pairs)
    for k, (_, j) in enumerate(pairs):
        pos = bisect.bisect_left(tail_vals, j)
        if pos:
            prev[k] = tails[pos - 1]
        if pos == len(tail_vals):
            tail_vals.append(j)
            tails.append(k)
        else:
            tail_vals[pos] = j
            tails[pos] = k
    out: list[tuple[int, int]] = []
    k = tails[-1] if tails else -1
    while k >= 0:
        out.append(pairs[k])
        k = prev[k]
    return out[::-1]


def _unique(words: Sequence[str], lo: int, hi: int, n: int) -> dict[tuple[str, ...], int]:
    """n-grams starting in ``[lo, hi - n]`` that occur once there, with their start."""
    seen: dict[tuple[str, ...], int] = {}
    dup: set[tuple[str, ...]] = set()
    for i in range(lo, hi - n + 1):
        g = tuple(words[i:i + n])
        if g in seen:
            dup.add(g)
        else:
            seen[g] = i
    return {g: i for g, i in seen.items() if g not in dup}


def align_words(a: Sequence[str], b: Sequence[str], params: Params | None = None
                ) -> list[tuple[int, int]]:
    """Pairs ``(i, j)`` of equal words ``a[i] == b[j]``, increasing in both."""
    p = params or Params()
    out: list[tuple[int, int]] = []
    stack = [(0, len(a), 0, len(b))]
    while stack:
        a0, a1, b0, b1 = stack.pop()
        if a0 >= a1 or b0 >= b1:
            continue
        if (a1 - a0) * (b1 - b0) <= p.small * p.small:
            sm = difflib.SequenceMatcher(None, a[a0:a1], b[b0:b1], autojunk=False)
            for blk in sm.get_matching_blocks():
                out.extend((a0 + blk.a + k, b0 + blk.b + k) for k in range(blk.size))
            continue
        chain: list[tuple[int, int]] = []
        for n in (3, 2, 1):
            ua, ub = _unique(a, a0, a1, n), _unique(b, b0, b1, n)
            chain = _chain([(i, ub[g]) for g, i in ua.items() if g in ub])
            if chain:
                break
        if not chain:
            continue  # nothing in common: leave the range unaligned
        pa, pb = a0, b0
        for i, j in chain:
            if i < pa or j < pb:
                continue  # inside the run of an earlier anchor
            stack.append((pa, i, pb, j))
            k = 0
            while i + k < a1 and j + k < b1 and a[i + k] == b[j + k]:
                out.append((i + k, j + k))
                k += 1
            pa, pb = i + k, j + k
        stack.append((pa, a1, pb, b1))
    out.sort()
    return out


def in_runs(pairs: Sequence[tuple[int, int]], min_run: int) -> list[tuple[int, int]]:
    """The *pairs* that are in runs of at least *min_run* consecutive words on both sides."""
    out: list[tuple[int, int]] = []
    start = 0
    for k in range(1, len(pairs) + 1):
        if (k < len(pairs) and pairs[k][0] == pairs[k - 1][0] + 1
                and pairs[k][1] == pairs[k - 1][1] + 1):
            continue
        if k - start >= min_run:
            out.extend(pairs[start:k])
        start = k
    return out


def confidence(dice: float, params: Params | None = None) -> float:
    """A bead's confidence from its *dice*: linear up to ``Params.full_dice``."""
    p = params or Params()
    return round(min(1.0, dice / p.full_dice), 3)


def unit_beads(pairs: Sequence[tuple[int, int]], unit_a: Sequence[int], unit_b: Sequence[int],
               params: Params | None = None) -> list[TextBead]:
    """Beads of units from word *pairs* (already cut to runs), sorted and monotonic."""
    p = params or Params()
    size_a = Counter(unit_a)
    size_b = Counter(unit_b)
    shared = Counter((unit_a[i], unit_b[j]) for i, j in pairs)
    links = sorted((u, v) for (u, v), n in shared.items()
                   if n >= p.link_min and (n >= p.link_frac * size_a[u]
                                           or n >= p.link_frac * size_b[v]))
    # Each link is a span pair; join those that overlap or cross on either side.
    beads: list[list[int]] = []
    for u, v in links:
        cur = [u, u + 1, v, v + 1]
        while beads and (cur[0] < beads[-1][1] or cur[2] < beads[-1][3]):
            last = beads.pop()
            cur = [min(last[0], cur[0]), max(last[1], cur[1]),
                   min(last[2], cur[2]), max(last[3], cur[3])]
        beads.append(cur)
    bead_of = {u: k for k, (i0, i1, _, _) in enumerate(beads) for u in range(i0, i1)}
    matched = Counter()
    for (u, v), n in shared.items():
        k = bead_of.get(u)
        if k is not None and beads[k][2] <= v < beads[k][3]:
            matched[k] += n
    out: list[TextBead] = []
    for k, (i0, i1, j0, j1) in enumerate(beads):
        words = sum(size_a[u] for u in range(i0, i1)) + sum(size_b[v] for v in range(j0, j1))
        dice = 2 * matched[k] / words if words else 0.0
        out.append(TextBead(i0, i1, j0, j1, round(dice, 3), confidence(dice, p)))
    return out


def align_texts(texts_a: Sequence[str], texts_b: Sequence[str], params: Params | None = None
                ) -> TextAlignment:
    """Align two editions given as their units' source texts."""
    p = params or Params()
    wa, ua = unit_words(texts_a)
    wb, ub = unit_words(texts_b)
    runs = in_runs(align_words(wa, wb, p), p.min_run)
    shorter = min(len(wa), len(wb))
    shared = len(runs) / shorter if shorter else 0.0
    return TextAlignment(unit_beads(runs, ua, ub, p), round(shared, 4), len(runs), len(wa),
                         len(wb))
