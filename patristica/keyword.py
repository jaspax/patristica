"""
The keyword index for quoted (phrase) search (#86).

Quotes are found by matching words, not by meaning: in the embedding eval
(#3) keyword matching found the source of a quote at rank 1 in 0.94 of cases,
and no embedder came above 0.5. The index is ``chunks.text_folded``, the
chunk's text through ``patristica.textfold.fold`` with a space at each end,
under a ``pg_trgm`` GIN index. A phrase matches when its folded form occurs
in it as whole words: ``text_folded LIKE '% {fold(phrase)} %'``.

**Chinese** (#648) is written without spaces, so a phrase is a sequence of
characters, not of words. ``text_folded`` drops the spaces that ``fold``
leaves between two ideographs (where punctuation was), and a phrase whose
end is an ideograph matches there without a word boundary: ``景教流行``
gives ``LIKE '%景教流行%'``, found in a punctuated and an unpunctuated
edition alike. Text without ideographs is indexed and matched as before.

``fold`` drops accents, breathings, vowel points and overlines, case, and
punctuation, and evens out Latin spelling, so a quote typed in any of those
forms matches. ``scripts.build_index`` writes ``text_folded``; the search
API builds the patterns. Both must use the functions here.
"""

from __future__ import annotations

import re
import unicodedata

from patristica.textfold import IDEOGRAPH_RE, IDEOGRAPHS, fold, fold_spans

#: Bump when ``fold`` changes, so ``scripts.build_index`` refolds every work and rewrites
#: the chunks whose folded text changed (#607).
#: 2: Church Slavonic letters (#330); 3: Arabic letters (#83); 4: Old Georgian (#222);
#: 5: Old Georgian old/modern spellings (#511); 6: Old English, Old Saxon and
#: Old High German letters (ð/đ/þ, ƀ/b, ƿ/w, ȝ/g; #563); 7: Literary Chinese variant
#: characters, and no space between two ideographs in ``text_folded`` (#648).
FOLD_VERSION = 7

#: Shorter phrases (letters, not counting spaces) have too few trigrams to use the index.
MIN_PHRASE_CHARS = 3
#: A phrase of ideographs may be shorter: two characters are a real Chinese word
#: (景教, 真主). It has no trigram, so it is searched only in the chunks of
#: :data:`IDEOGRAPHIC_LANGUAGES`, which a partial index on ``chunks`` lists
#: (``db/schema.sql``), not by a scan of the whole table.
MIN_IDEOGRAPH_PHRASE_CHARS = 2
#: The languages written in ideographs (``chunks_ideographic`` in ``db/schema.sql``).
IDEOGRAPHIC_LANGUAGES = ("lzh",)

_BETWEEN_IDEOGRAPHS = re.compile(f"(?<=[{IDEOGRAPHS}]) (?=[{IDEOGRAPHS}])")


class PhraseError(ValueError):
    """A phrase that can't be searched (too short once folded)."""


def _keyword_fold(text: str) -> str:
    """``fold(text)`` without the spaces between two ideographs."""
    return _BETWEEN_IDEOGRAPHS.sub("", fold(text))


def index_text(text: str) -> str:
    """The value of ``chunks.text_folded`` for *text*: folded, with a space at each end."""
    return f" {_keyword_fold(text)} "


def _bounded(folded: str) -> tuple[str, str]:
    """The boundary before and after a folded phrase: a space (whole words), or
    nothing where the phrase starts or ends with an ideograph."""
    return ("" if IDEOGRAPH_RE.match(folded[:1]) else " ",
            "" if IDEOGRAPH_RE.match(folded[-1:]) else " ")


def is_short(phrase: str) -> bool:
    """Whether *phrase* is too short for the trigram index, though searchable: it
    is searched only in :data:`IDEOGRAPHIC_LANGUAGES` (``phrase_pattern``)."""
    return len(_keyword_fold(phrase).replace(" ", "")) < MIN_PHRASE_CHARS


def phrase_pattern(phrase: str) -> str:
    """The ``LIKE`` pattern matching *phrase* as whole words in ``text_folded``
    (as a sequence of characters where it starts or ends with an ideograph).

    ``fold`` turns every punctuation mark and symbol into a space, so the
    pattern holds no ``LIKE`` wildcards other than its own.
    """
    folded = _keyword_fold(phrase)
    letters = len(folded.replace(" ", ""))
    if letters < MIN_PHRASE_CHARS and not (
        letters >= MIN_IDEOGRAPH_PHRASE_CHARS and all(IDEOGRAPH_RE.match(c) for c in folded)
    ):
        raise PhraseError(f"A quoted phrase needs at least {MIN_PHRASE_CHARS} letters "
                          f"({MIN_IDEOGRAPH_PHRASE_CHARS} Chinese characters).")
    before, after = _bounded(folded)
    return f"%{before}{folded}{after}%"


def match_spans(text: str, phrases: list[str]) -> list[tuple[int, int]]:
    """Where *phrases* occur in *text* as the keyword index matches them (for highlighting).

    Returns sorted, merged ``(start, end)`` spans of *text*, in code points.
    A span also covers the marks after its last letter (vowel points,
    accents), so it never splits a letter from its marks.
    """
    folded, starts, ends = fold_spans(text)
    if IDEOGRAPH_RE.search(folded):  # as index_text: no space between two ideographs
        keep = [k for k in range(len(folded)) if not (
            folded[k] == " " and 0 < k < len(folded) - 1
            and IDEOGRAPH_RE.match(folded[k - 1]) and IDEOGRAPH_RE.match(folded[k + 1]))]
        folded = "".join(folded[k] for k in keep)
        starts = [starts[k] for k in keep]
        ends = [ends[k] for k in keep]
    hay = f" {folded} "
    spans: list[tuple[int, int]] = []
    for phrase in phrases:
        needle = _keyword_fold(phrase)
        if not needle:
            continue
        before, after = _bounded(needle)
        pattern = f"{before}{needle}{after}"
        i = hay.find(pattern)
        while i != -1:
            k = i - 1 + len(before)  # hay has a space before folded[0]: the match is folded[k:…]
            start, end = starts[k], ends[k + len(needle) - 1]
            while end < len(text) and unicodedata.category(text[end]) in ("Mn", "Me", "Cf"):
                end += 1
            spans.append((start, end))
            i = hay.find(pattern, i + 1)
    merged: list[tuple[int, int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged
