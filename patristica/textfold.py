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


def fold_spans(text: str) -> tuple[str, list[int], list[int]]:
    """``fold(text)``, with the span of *text* each folded character came from.

    Returns ``(folded, starts, ends)``: ``folded[k]`` comes from
    ``text[starts[k]:ends[k]]``. It applies the steps of ``fold`` one
    character at a time, so a match found in the folded text can be shown in
    the original (search highlighting, #143). A space between words spans
    the gap between them, and a replaced word (*michi*) spans the whole word.
    """
    chars: list[tuple[str, int, int]] = []
    for i, ch in enumerate(text):
        for d in unicodedata.normalize("NFKD", ch).translate(_IN_WORD_MARKS):
            if _is_dropped_mark(d):
                continue
            for c in d.casefold():
                c = " " if _is_separator(c) else c.translate(_LATIN_LETTERS)
                chars.append((c, i, i + 1))
    # The digraphs ae/oe, left to right and not overlapping, as the regex does.
    merged: list[tuple[str, int, int]] = []
    k = 0
    while k < len(chars):
        c, start, end = chars[k]
        if c in "ao" and k + 1 < len(chars) and chars[k + 1][0] == "e":
            merged.append(("e", start, chars[k + 1][2]))
            k += 2
        else:
            merged.append((c, start, end))
            k += 1
    words: list[list[tuple[str, int, int]]] = []
    current: list[tuple[str, int, int]] = []
    for item in merged:
        if item[0].isspace():
            if current:
                words.append(current)
                current = []
        else:
            current.append(item)
    if current:
        words.append(current)
    folded: list[str] = []
    starts: list[int] = []
    ends: list[int] = []
    for n, word in enumerate(words):
        if n:
            folded.append(" ")
            starts.append(ends[-1])
            ends.append(word[0][1])
        spelled = "".join(c for c, _, _ in word)
        if spelled in _LATIN_WORDS:
            word = [(c, word[0][1], word[-1][2]) for c in _LATIN_WORDS[spelled]]
        for c, start, end in word:
            folded.append(c)
            starts.append(start)
            ends.append(end)
    return "".join(folded), starts, ends


def squash(text: str) -> str:
    """Return ``fold(text)`` without spaces, for word-boundary-insensitive containment.

    Coptic editions disagree on word division (bound groups vs. morphemes), so
    "does chunk X contain quote Q?" is checked on squashed strings.
    """
    return fold(text).replace(" ", "")
