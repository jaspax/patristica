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
``SWITCH_COST``.  Chapter numbers, footnote marks and other stray numbers vote
for a different offset on every page, so they never add up to a state; real
column numbers agree with each other across pages.  A state is a
``(k, offset)`` pair, so a volume may switch layout part way (PG 47 does).

A number is in head position when it is the first or last token of a short
line (at most ``_MAX_HEAD_TOKENS`` tokens).  Bracketed numbers (``[216]``, the
page numbers of the edition Migne reprints) are ignored.

Pages before the first column (front matter numbered in roman numerals) and
pages whose column would not exceed the previous page's get no column.
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
    numbered: int                    # pages with a column

    @property
    def support_ratio(self) -> float:
        return self.supported / self.numbered if self.numbered else 0.0


State = tuple[int, int]


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
        best_prev = min(range(n), key=lambda s: (cost[s], s))
        switch = cost[best_prev] + SWITCH_COST
        new_cost: list[float] = []
        ptr: list[int] = []
        for s in range(n):
            c, p = (cost[s], s) if cost[s] <= switch else (switch, best_prev)
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
    supported = numbered = 0
    last = 0
    for (stem, p, _), s, v in zip(numeric, path, votes):
        per_page, offset = states[s]
        pos = per_page * p + offset
        if pos < 1 or pos <= last:   # front matter, or a leaf at an offset change
            continue
        last = pos
        # Every printed page carries an odd and an even column; in the
        # one-column-per-scan-page layout two consecutive pages share them.
        first = pos if pos % 2 else pos - 1
        columns[stem] = (first, first + 1)
        numbered += 1
        if states[s] in v:
            supported += 1
    return ColumnMap(columns, supported, numbered)
