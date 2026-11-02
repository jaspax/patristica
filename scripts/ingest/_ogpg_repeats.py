"""
Pages that a Patrologia Graeca scan contains twice (#96).

Many OGPG scans repeat runs of leaves: in the primary scan of PG 2, pages
73–82 are a second copy of pages 63–72, with slightly different OCR.  About
a hundred volumes have such runs, some of a single leaf (two pages), some of
fifty.  Left alone, the repeated text is in the corpus twice, and the running
heads of the repeated pages go back to earlier columns, which breaks the
page → column mapping (``_ogpg_columns``): the chain of increasing columns
loses the stretch, and the columns after it run ahead of the printed ones.

This module finds the repeated pages from the extracted paragraphs, so it
works on the cached extraction (no re-OCR, no new clone).  A paragraph is
matched with its most similar paragraph on an earlier page (shared word
trigrams to find candidates, then a character-level similarity, both on the
text without accents, where much of the OCR noise is).  A page is a repeat of
an earlier page when paragraphs holding at least ``PAGE_SHARE`` of its text
match paragraphs of that one page, and either the matches are close
(``STRONG_RATIO`` on average) or a neighbouring page repeats a page at the
same distance (a run of repeated leaves, where some pages are noisier).  Pages
without Greek paragraphs inside a run (a Latin page, a plate) are part of the
run too.

``ogpg.split_volume`` drops every paragraph of a repeated page and leaves the
page out of the column mapping, numbering the scan as if it were not there.
The earlier copy is kept.  A page inside a repeated run whose text didn't
match is new text, and stays where it is, except when the page of the first
copy it stands for has no text at all (its OCR failed): then this copy is the
only one, and it takes that page's place and columns (``Repeats.moved``).
The result is deterministic in the extraction.
"""

from __future__ import annotations

import bisect
import difflib
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field

# A candidate earlier paragraph must share this fraction of the paragraph's
# word trigrams.
MIN_SHARED = 0.15
# Candidates compared character by character, best first.
MAX_CANDIDATES = 5
# Characters compared (the start of each paragraph; enough to tell).
COMPARE_CHARS = 1500
# Similarity at which a paragraph counts as matching one on another page.
MATCH_RATIO = 0.6
# A page is a repeat when paragraphs holding this share of its text match
# paragraphs of one earlier page…
PAGE_SHARE = 0.5
# …and their mean similarity (weighted by length) is at least this,
STRONG_RATIO = 0.8
# …or a page within this many pages repeats a page at the same distance.
NEIGHBOUR_PAGES = 2
# Pages without paragraphs between two repeated pages at the same distance
# are part of the run when the gap is at most this many pages.
MAX_GAP = 3
# A repeated leaf repeats the whole page, so the page starts or ends as the
# page it repeats: the first or last ``ALIGN_CHARS`` characters of the two
# pages must be at least this similar.  A passage Migne prints twice (a
# quotation in a note, a florilegium, parallel chronicles) sits elsewhere on
# its page.
ALIGN_RATIO = 0.5
ALIGN_CHARS = 300
# Scans repeat leaves a few pages after the first copy.  A page repeating one
# more than ``NEAR_PAGES`` pages back is a repeat only inside a cluster of
# repeated pages (another one within ``NEIGHBOUR_PAGES + 1`` pages); a single
# such page is a passage Migne prints twice.
NEAR_PAGES = 30
# A page next to a repeated one continues its run when it starts or ends like
# the page at the run's distance, this closely (its two extractions may keep
# different paragraphs, so the shares above can miss it).
RUN_ALIGN_RATIO = 0.6

_WORD = re.compile(r"\w+")


def _fold(text: str) -> str:
    """Lower case without accents and breathings (OCR confuses them)."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _trigrams(folded: str) -> set[str]:
    words = _WORD.findall(folded)
    return {" ".join(words[i:i + 3]) for i in range(len(words) - 2)}


@dataclass(frozen=True)
class Repeats:
    """Result of :func:`find_repeats`."""

    pages: dict[str, str]        # repeated page stem → stem of the page it repeats
    # Page inside a repeated run → the page of the first copy whose place it
    # takes, when that page has no text of its own (its OCR failed): this copy
    # is the only one, so it is kept there.
    moved: dict[str, str] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return bool(self.pages)


def _page_number(stem: str) -> int | None:
    return int(stem) if stem.isdigit() else None


def _aligned(a: str, b: str, ratio: float = ALIGN_RATIO) -> bool:
    """Whether two pages start or end alike (see ``ALIGN_RATIO``)."""
    a, b = _fold(a).strip(), _fold(b).strip()
    return any(
        difflib.SequenceMatcher(None, x, y, autojunk=False).ratio() >= ratio
        for x, y in ((a[:ALIGN_CHARS], b[:ALIGN_CHARS]), (a[-ALIGN_CHARS:], b[-ALIGN_CHARS:])))


def _best_matches(paragraphs: list[dict]) -> list[tuple[int, float] | None]:
    """For each paragraph, the most similar paragraph on an earlier page."""
    folded = [_fold(p["text"]) for p in paragraphs]
    grams = [_trigrams(f) for f in folded]
    pages = [_page_number(p["stem"]) for p in paragraphs]
    index: dict[str, list[int]] = defaultdict(list)
    out: list[tuple[int, float] | None] = []
    for i, g in enumerate(grams):
        best: tuple[int, float] | None = None
        if g and pages[i] is not None:
            shared: Counter[int] = Counter()
            for t in g:
                shared.update(index.get(t, ()))
            need = MIN_SHARED * len(g)
            cands = [(n, j) for j, n in shared.items()
                     if n >= need and pages[j] is not None and pages[j] < pages[i]]
            cands.sort(key=lambda c: (-c[0], c[1]))
            a = folded[i][:COMPARE_CHARS]
            for _, j in cands[:MAX_CANDIDATES]:
                r = difflib.SequenceMatcher(None, a, folded[j][:COMPARE_CHARS],
                                            autojunk=False).ratio()
                if r >= MATCH_RATIO and (best is None or r > best[1]):
                    best = (j, r)
        out.append(best)
        for t in g:
            index[t].append(i)
    return out


def find_repeats(paragraphs: list[dict], page_stems: list[str]) -> Repeats:
    """Pages of a volume's extraction that repeat an earlier page.

    ``paragraphs`` are the extraction's ``{"stem", "text", …}`` in scan order;
    ``page_stems`` are the stems of every page of the scan (``page_heads``).
    """
    matches = _best_matches(paragraphs)
    length: Counter[str] = Counter()
    covered: dict[str, Counter[str]] = defaultdict(Counter)
    weighted: dict[str, Counter[str]] = defaultdict(Counter)
    for p, m in zip(paragraphs, matches):
        n = len(p["text"])
        length[p["stem"]] += n
        if m is not None:
            other = paragraphs[m[0]]["stem"]
            covered[p["stem"]][other] += n
            weighted[p["stem"]][other] += n * m[1]

    page_text: dict[str, list[str]] = defaultdict(list)
    for p in paragraphs:
        page_text[p["stem"]].append(p["text"])

    # Candidate repeats: page → (page repeated, distance, strong?)
    cand: dict[int, tuple[str, int, bool]] = {}
    stems: dict[int, str] = {}
    for stem, by_page in covered.items():
        other, n = max(by_page.items(), key=lambda kv: (kv[1], kv[0]))
        if n < PAGE_SHARE * length[stem]:
            continue
        if not _aligned(" ".join(page_text[stem]), " ".join(page_text[other])):
            continue
        p, q = int(stem), int(other)
        cand[p] = (other, p - q, weighted[stem][other] / n >= STRONG_RATIO)
        stems[p] = stem

    repeated: dict[int, tuple[str, int]] = {}
    for p, (other, dist, strong) in cand.items():
        if strong or any(cand.get(p + k, ("", 0, False))[1:] == (dist, True)
                         for k in range(-NEIGHBOUR_PAGES, NEIGHBOUR_PAGES + 1) if k):
            repeated[p] = (other, dist)
    near = NEIGHBOUR_PAGES + 1
    repeated = {p: v for p, v in repeated.items()
                if v[1] <= NEAR_PAGES
                or any(p + k in repeated for k in range(-near, near + 1) if k)}

    # A run goes on through pages whose second extraction kept less (or other)
    # text, as long as they start or end like the page at the run's distance.
    by_num = {int(s): s for s in page_text if s.isdigit()}
    grew = True
    while grew:
        grew = False
        for p in sorted(by_num):
            if p in repeated:
                continue
            for dist in sorted({repeated[p + k][1] for k in (-1, 1) if p + k in repeated}):
                q = by_num.get(p - dist)
                if q is not None and _aligned(" ".join(page_text[by_num[p]]),
                                              " ".join(page_text[q]), RUN_ALIGN_RATIO):
                    repeated[p] = (q, dist)
                    stems[p] = by_num[p]
                    grew = True
                    break

    # Pages without paragraphs inside a run.
    with_text = {int(p["stem"]) for p in paragraphs if p["stem"].isdigit()}
    numbered = {int(s): s for s in page_stems if s.isdigit()}
    by_page = sorted(repeated)
    for a, b in zip(by_page, by_page[1:]):
        dist = repeated[a][1]
        if repeated[b][1] != dist or not 1 < b - a <= MAX_GAP + 1:
            continue
        gap = range(a + 1, b)
        if any(k in with_text or k not in numbered or k - dist not in numbered for k in gap):
            continue
        for k in gap:
            stems[k] = numbered[k]
            repeated[k] = (numbered[k - dist], dist)

    # Pages inside a run whose first copy has no text: the only copy.
    moved: dict[str, str] = {}
    by_page = sorted(repeated)
    for p in sorted(with_text - set(repeated)):
        i = bisect.bisect_left(by_page, p)
        if i == 0 or i == len(by_page):
            continue
        a, b = by_page[i - 1], by_page[i]
        dist = repeated[a][1]
        if repeated[b][1] != dist or p - a > MAX_GAP + 1 or b - p > MAX_GAP + 1:
            continue
        if p - dist in numbered and p - dist not in with_text:
            moved[numbered[p]] = numbered[p - dist]

    return Repeats({stems[p]: other for p, (other, _) in sorted(repeated.items())}, moved)
