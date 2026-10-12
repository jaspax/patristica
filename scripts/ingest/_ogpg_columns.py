"""
Scan page → Migne column mapping for the Open Patrologia Graeca OCR.

Migne numbers columns, not pages, and prints the column numbers in the running
heads (``13  S. GREGORII NYSSENI  14``) or alone at the foot of the column
(``285``).  The OCR keeps these numbers, but noisily (``{85 DE (ΣοΜ MUNIBUS
NOTIONIBUS. £88``) and often not at all.

Within a run of consecutive scan pages the relation is linear,
``column = k * page + offset``.  ``k`` is 2 for most volumes: each page has
two columns, Greek and Latin side by side, the first one odd.  It is 1 where
the Latin translation is printed on the facing page instead (the Chrysostom
volumes, PG 47–64): a Greek page and its Latin page carry the same two column
numbers, so the columns advance by one per scan page on average.  Either way
a page is given the two columns ``(odd, odd + 1)`` it prints.  The offset
changes only where the scan inserts unnumbered leaves (plates, blank or title
pages) or skips a page.

So each number printed in head position votes for an offset, and a Viterbi
pass picks a piecewise-constant offset sequence: a page whose votes include
the state costs nothing, any other page costs 1, and changing the offset costs
``SWITCH_COST`` plus ``JUMP_COST`` per column of the jump (OCR misreads such
as 1305 → 1505 agree with each other too, but sit hundreds of columns off).  Chapter numbers, footnote marks and other stray numbers vote
for a different offset on every page, so they never add up to a state; real
column numbers agree with each other across pages.  A state is a
``(k, offset)`` pair, so a volume may switch layout part way (PG 47 does).

A number is in head position when it is the first or last token of a short
line (at most ``_MAX_HEAD_TOKENS`` tokens).  Bracketed numbers (``[216]``, the
page numbers of the edition Migne reprints) are ignored.

Columns must increase through a volume, so of the runs of pages on one state
only the best-supported increasing chain is kept (see ``map_columns``).
Gaps between kept pages are interpolated when their columns advance at a
plausible rate (``_interpolate``): there the column is an estimate.
Pages outside it, pages before the first column (front matter numbered in
roman numerals) and pages whose column would not exceed the previous page's
get no column.
The mapping is deterministic in the OCR text of the scan.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

_MAX_HEAD_TOKENS = 6
_NUM_TOKEN = re.compile(r"^\d{1,4}[.,]?$")
# Smallest number taken as a column.  Lower ones are mostly chapter and
# footnote numbers (and OCR of ``ὁ`` as ``6``); the first columns of a volume
# are front matter anyway.
_MIN_COLUMN = 7
# An offset must be voted for on this many distinct pages to be a state.
_MIN_SUPPORT = 3
# Cost of changing offset between consecutive pages, in units of "pages
# without a matching vote".  A new offset needs about five agreeing pages
# before the path switches to it.
SWITCH_COST = 4.0
# Extra switching cost per column the offset jumps.  A plate or a missing leaf
# moves it by 2; misread digits (3 ↔ 5, 1 ↔ 7) by hundreds, which then needs
# that much more evidence.
JUMP_COST = 0.25
# Extra cost of switching between the one- and two-columns-per-page layouts.
LAYOUT_COST = 4.0
# A run of pages on one state is kept only if at least this fraction of its
# pages that have any head numbers vote for it.
_MIN_DENSITY = 0.25


def head_numbers(text: str) -> set[int]:
    """Numbers in head position on one OCR page (see module docstring)."""
    out: set[int] = set()
    for line in text.splitlines():
        tokens = line.split()
        if not tokens or len(tokens) > _MAX_HEAD_TOKENS:
            continue
        for tok in {tokens[0], tokens[-1]}:
            if _NUM_TOKEN.match(tok):
                n = int(tok.rstrip(".,"))
                if n >= _MIN_COLUMN:
                    out.add(n)
    return out


def page_votes(numbers: set[int], page: int) -> set[tuple[int, int]]:
    """``(columns per page, offset)`` states voted for by a page's head numbers.

    A number stands for its page's pair of columns (odd, odd + 1), so the left
    and the right column number agree.  With two columns per scan page it votes
    for the page's first column; with one (facing Greek and Latin pages) for
    either column of the pair, since the page may be the first or the second of
    the two pages that print it.
    """
    votes: set[tuple[int, int]] = set()
    for n in numbers:
        odd = n if n % 2 else n - 1
        votes |= {(2, odd - 2 * page), (1, odd - page), (1, odd + 1 - page)}
    return votes


@dataclass(frozen=True)
class ColumnMap:
    """Result of :func:`map_columns` for one scan."""

    columns: dict[str, tuple[int, int] | None]  # page stem → (first, last) column, or None
    supported: int                   # numbered pages whose own votes include their state
    numbered: int                    # pages with a column (including interpolated ones)

    @property
    def support_ratio(self) -> float:
        return self.supported / self.numbered if self.numbered else 0.0


State = tuple[int, int]


def _nearest_switch(cost: list[float], states: list[State]) -> tuple[list[float], list[int]]:
    """For each state, the cheapest way to switch into it from another state.

    Switching costs ``SWITCH_COST`` plus ``JUMP_COST`` per column the offset
    moves (an L1 distance transform over the sorted offsets of each layout),
    or ``SWITCH_COST + LAYOUT_COST`` from the other layout.  Returns the cost
    and the state switched from.
    """
    n = len(states)
    best = [float("inf")] * n
    arg = list(range(n))
    groups: dict[int, list[int]] = {}
    for i, (k, _) in enumerate(states):
        groups.setdefault(k, []).append(i)
    for idx in groups.values():                    # states are sorted by offset
        for order in (idx, idx[::-1]):
            run_c, run_a, prev_o = float("inf"), -1, 0
            for i in order:
                o = states[i][1]
                if run_a >= 0:
                    run_c += JUMP_COST * abs(o - prev_o)
                if cost[i] < run_c:
                    run_c, run_a = cost[i], i
                prev_o = o
                if run_c < best[i]:
                    best[i], arg[i] = run_c, run_a
    group_min = {k: min(idx, key=lambda i: (cost[i], i)) for k, idx in groups.items()}
    for i, (k, _) in enumerate(states):
        for k2, g in group_min.items():
            if k2 != k and cost[g] + LAYOUT_COST < best[i]:
                best[i], arg[i] = cost[g] + LAYOUT_COST, g
    return [c + SWITCH_COST for c in best], arg


def _viterbi(votes: list[set[State]]) -> tuple[list[State], list[int]]:
    """Best piecewise-constant state path → (states, path of state indices)."""
    support: Counter[State] = Counter(o for v in votes for o in v)
    states = sorted(o for o, c in support.items() if c >= _MIN_SUPPORT)
    if not states or not votes:
        return states, []
    n = len(states)
    cost = [0.0 if states[s] in votes[0] else 1.0 for s in range(n)]
    back: list[list[int]] = []
    for v in votes[1:]:
        switch, frm = _nearest_switch(cost, states)
        new_cost: list[float] = []
        ptr: list[int] = []
        for s in range(n):
            c, p = (cost[s], s) if cost[s] <= switch[s] else (switch[s], frm[s])
            new_cost.append(c + (0.0 if states[s] in v else 1.0))
            ptr.append(p)
        cost = new_cost
        back.append(ptr)
    s = min(range(n), key=lambda k: (cost[k], k))
    path = [s]
    for ptr in reversed(back):
        s = ptr[s]
        path.append(s)
    path.reverse()
    return states, path


def _increasing_segments(segs: list[tuple[int, int, int]]) -> set[int]:
    """Indices of the segments kept: ``segs`` are ``(first pos, last pos, weight)``
    in page order; the result is the heaviest chain in which each segment
    starts and ends after the previous one.  Consecutive segments may overlap
    (the path switches state a few pages late at a plate or a missing leaf);
    the overlapping pages are dropped later.
    """
    best: list[tuple[int, int]] = []          # (chain weight, previous segment or -1)
    for i, (lo, _, w) in enumerate(segs):
        cand = (w, -1)
        for j in range(i):
            if segs[j][0] < lo and segs[j][1] < segs[i][1] and best[j][0] + w > cand[0]:
                cand = (best[j][0] + w, j)
        best.append(cand)
    keep: set[int] = set()
    i = max(range(len(segs)), key=lambda k: (best[k][0], -k), default=-1)
    while i >= 0:
        keep.add(i)
        i = best[i][1]
    return keep


def map_columns(heads: list[tuple[str, list[int]]]) -> ColumnMap:
    """Infer the Migne columns printed on every page of a scan.

    ``heads`` is ``[(stem, head numbers)]`` for every page of the scan in
    order (``head_numbers`` of the page text); stems are the page numbers of
    the scan's ``NNN.txt`` files.  Non-numeric stems get no column.
    """
    numeric = [(stem, int(stem), nums) for stem, nums in heads if stem.isdigit()]
    votes = [page_votes(set(nums), p) for _, p, nums in numeric]
    states, path = _viterbi(votes)
    columns: dict[str, tuple[int, int] | None] = {stem: None for stem, _ in heads}

    # Runs of pages on one state.  Columns must increase through the volume:
    # keep the best-supported chain of runs that does, and drop the rest
    # (numbers in front matter, e.g. the years of a Vita that advance with
    # the pages, and leaves scanned twice).
    runs: list[list[int]] = []                 # page indices per run
    for i, s in enumerate(path):
        if runs and path[runs[-1][-1]] == s and runs[-1][-1] == i - 1:
            runs[-1].append(i)
        else:
            runs.append([i])

    def pos(i: int) -> int:
        per_page, offset = states[path[i]]
        return per_page * numeric[i][1] + offset

    segs = []
    for r in runs:
        body = [i for i in r if pos(i) >= 1]       # the front matter has no columns
        support = sum(states[path[i]] in votes[i] for i in body)
        # A run carried by a few stray numbers over many pages is not evidence.
        voting = sum(1 for i in body if votes[i])
        weight = support if support >= max(_MIN_SUPPORT, _MIN_DENSITY * voting) else 0
        segs.append((pos(r[0]), pos(r[-1]), weight))
    keep = {k for k in _increasing_segments(segs) if segs[k][2] > 0}

    positions: dict[int, int] = {}            # page index → position
    supported = 0
    last = 0
    for k, run in enumerate(runs):
        if k not in keep:
            continue
        for i in run:
            p_ = pos(i)
            if p_ < 1 or p_ <= last:   # front matter, or a leaf at an offset change
                continue
            last = p_
            positions[i] = p_
            if states[path[i]] in votes[i]:
                supported += 1
    _interpolate(numeric, positions)

    for i, p_ in positions.items():
        # Every printed page carries an odd and an even column; in the
        # one-column-per-scan-page layout two consecutive pages share them.
        first = p_ if p_ % 2 else p_ - 1
        columns[numeric[i][0]] = (first, first + 1)
    return ColumnMap(columns, supported, len(positions))


# Interpolate across a gap only if its columns per page are within this
# fraction of 1 or 2.
_GAP_TOLERANCE = 0.15
# Only gaps of more than this many pages are interpolated.
_MIN_GAP = 3


def _interpolate(numeric: list[tuple[str, int, list[int]]], positions: dict[int, int]) -> None:
    """Fill gaps between numbered pages whose columns advance at a plausible rate.

    Stretches whose running heads did not survive the OCR, or whose numbers
    were outvoted (verse and psalm numbers), lie between two numbered pages;
    when the columns between those advance by about 1 or 2 per page, the
    pages in between get linearly interpolated positions.
    """
    known = sorted(positions)
    for a, b in zip(known, known[1:]):
        if b - a <= _MIN_GAP:       # a plate or two: leave unnumbered
            continue
        pa, pb = numeric[a][1], numeric[b][1]
        rate = (positions[b] - positions[a]) / (pb - pa)
        if not any(abs(rate - k) <= _GAP_TOLERANCE * k for k in (1, 2)):
            continue
        prev = positions[a]
        for i in range(a + 1, b):
            p_ = positions[a] + round((numeric[i][1] - pa) * rate)
            if prev < p_ < positions[b]:
                positions[i] = prev = p_
