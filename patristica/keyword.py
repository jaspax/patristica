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

from patristica.textfold import fold

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
