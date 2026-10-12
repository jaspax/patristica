"""
Orthographic folding for near-verbatim text matching.

``fold()`` maps a string to a canonical form so that the same words written
with different orthography compare equal: Greek with or without accents and
breathings, Hebrew with or without points, vocalized or unvocalized Syriac,
Coptic with or without supralinear strokes, and the common Latin spelling
variants (u/v, i/j, ae/oe/e, medieval *michi*/*nichil*).

It is deliberately lossy and language-independent: the same function is
applied to indexed text and to queries, so neither side needs language
detection. Use it for lexical matching only, never for display.
"""

from __future__ import annotations

import re
import unicodedata

# Punctuation that sits *inside* a word and is deleted rather than turned into
# a word break: Armenian emphasis/exclamation/question marks, the Coptic
# morphological divider, and the grave accent some Coptic editions use as a
# word-internal mark.
_IN_WORD_MARKS = dict.fromkeys(map(ord, "՛՜՞⳿`"), None)

# Latin letter-level variants, applied after lowercasing.
_LATIN_LETTERS = str.maketrans({"j": "i", "v": "u", "æ": "e", "œ": "e"})
_LATIN_DIGRAPHS = re.compile(r"ae|oe")

# Latin word-level variants (medieval spellings → classical).
_LATIN_WORDS = {"michi": "mihi", "nichil": "nihil"}


def _is_dropped_mark(ch: str) -> bool:
    # Mn/Me: combining accents, breathings, points, vowel marks, overlines.
    # Cf: zero-width joiners, bidi controls and similar format characters.
    return unicodedata.category(ch) in ("Mn", "Me", "Cf")


def _is_separator(ch: str) -> bool:
    cat = unicodedata.category(ch)
    return cat[0] in ("P", "S", "Z") or ch.isspace()


def fold(text: str) -> str:
    """Return the folded form of *text*: lowercase, unmarked, single-spaced words."""
    t = unicodedata.normalize("NFKD", text).translate(_IN_WORD_MARKS)
    t = "".join(ch for ch in t if not _is_dropped_mark(ch))
    t = t.casefold()  # also maps final sigma (ς) and long s (ſ) to σ / s
    t = "".join(" " if _is_separator(ch) else ch for ch in t)
    t = _LATIN_DIGRAPHS.sub("e", t.translate(_LATIN_LETTERS))
    return " ".join(_LATIN_WORDS.get(w, w) for w in t.split())


def squash(text: str) -> str:
    """Return ``fold(text)`` without spaces, for word-boundary-insensitive containment.

    Coptic editions disagree on word division (bound groups vs. morphemes), so
    "does chunk X contain quote Q?" is checked on squashed strings.
    """
    return fold(text).replace(" ", "")
