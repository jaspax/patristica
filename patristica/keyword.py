"""
The keyword index for quoted (phrase) search (#86).

Quotes are found by matching words, not by meaning: in the embedding eval
(#3) keyword matching found the source of a quote at rank 1 in 0.94 of cases,
and no embedder came above 0.5. The index is ``chunks.text_folded``, the
chunk's text through ``patristica.textfold.fold`` with a space at each end,
under a ``pg_trgm`` GIN index. A phrase matches when its folded form occurs
in it as whole words: ``text_folded LIKE '% {fold(phrase)} %'``.

``fold`` drops accents, breathings, vowel points and overlines, case, and
punctuation, and evens out Latin spelling, so a quote typed in any of those
forms matches. ``scripts.build_index`` writes ``text_folded``; the search
API builds the patterns. Both must use the functions here.
"""

from __future__ import annotations

import unicodedata

from patristica.textfold import fold, fold_spans

#: Bump when ``fold`` changes, so ``scripts.build_index`` refolds every chunk.
FOLD_VERSION = 1

#: Shorter phrases (letters, not counting spaces) have too few trigrams to use the index.
MIN_PHRASE_CHARS = 3


class PhraseError(ValueError):
    """A phrase that can't be searched (too short once folded)."""


def index_text(text: str) -> str:
    """The value of ``chunks.text_folded`` for *text*: folded, with a space at each end."""
    return f" {fold(text)} "


def phrase_pattern(phrase: str) -> str:
    """The ``LIKE`` pattern matching *phrase* as whole words in ``text_folded``.

    ``fold`` turns every punctuation mark and symbol into a space, so the
    pattern holds no ``LIKE`` wildcards other than its own.
    """
    folded = fold(phrase)
    if len(folded.replace(" ", "")) < MIN_PHRASE_CHARS:
        raise PhraseError(f"a quoted phrase needs at least {MIN_PHRASE_CHARS} letters")
    return f"% {folded} %"


def match_spans(text: str, phrases: list[str]) -> list[tuple[int, int]]:
    """Where *phrases* occur in *text* as the keyword index matches them (for highlighting).

    Returns sorted, merged ``(start, end)`` spans of *text*, in code points.
    A span also covers the marks after its last letter (vowel points,
    accents), so it never splits a letter from its marks.
    """
    folded, starts, ends = fold_spans(text)
    hay = f" {folded} "
    spans: list[tuple[int, int]] = []
    for phrase in phrases:
        needle = fold(phrase)
        if not needle:
            continue
        # hay[i] is the space before a match, so the match is folded[i:i + len(needle)].
        i = hay.find(f" {needle} ")
        while i != -1:
            start, end = starts[i], ends[i + len(needle) - 1]
            while end < len(text) and unicodedata.category(text[end]) in ("Mn", "Me", "Cf"):
                end += 1
            spans.append((start, end))
            i = hay.find(f" {needle} ", i + 1)
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged
