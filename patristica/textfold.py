"""
Orthographic folding for near-verbatim text matching.

``fold()`` maps a string to a canonical form so that the same words written
with different orthography compare equal: Greek with or without accents and
breathings, Hebrew with or without points, vocalized or unvocalized Syriac,
Coptic with or without supralinear strokes, the common Latin spelling
variants (u/v, i/j, ae/oe/e, medieval *michi*/*nichil*), and the letters
Church Slavonic witnesses and editions write differently (і/ꙇ/и, оу/ѹ/ꙋ/у,
ѡ/о, ꙑ/ъі/ы, ѥ/є/е, ꙗ/я/ѣ and ѣ/е by position, ѕ/ꙁ/з, ь/ъ and final
yers; see ``_CYRILLIC_LETTERS``).

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

# Church Slavonic (#330). Superscript letters (Cyrillic Extended-A/B
# combining letters) are letters of the word written above the line, so they
# become their base letter instead of being dropped as marks: хрⷭ҇тъ → хрстъ.
_CYRILLIC_COMBINING_LETTERS = {
    0x2DE0: "б", 0x2DE1: "в", 0x2DE2: "г", 0x2DE3: "д", 0x2DE4: "ж", 0x2DE5: "з",
    0x2DE6: "к", 0x2DE7: "л", 0x2DE8: "м", 0x2DE9: "н", 0x2DEA: "о", 0x2DEB: "п",
    0x2DEC: "р", 0x2DED: "с", 0x2DEE: "т", 0x2DEF: "х", 0x2DF0: "ц", 0x2DF1: "ч",
    0x2DF2: "ш", 0x2DF3: "щ", 0x2DF4: "ѳ", 0x2DF5: "ст", 0x2DF6: "а", 0x2DF7: "е",
    0x2DF8: "ꙉ", 0x2DF9: "ꙋ", 0x2DFA: "ѣ", 0x2DFB: "ю", 0x2DFC: "ꙗ", 0x2DFD: "ѧ",
    0x2DFE: "ѫ", 0x2DFF: "ѭ",
    0xA674: "є", 0xA675: "і", 0xA676: "ї", 0xA677: "у", 0xA678: "ъ", 0xA679: "ы",
    0xA67A: "ь", 0xA67B: "ѡ", 0xA69E: "ф", 0xA69F: "ѥ",
}

# Cyrillic letter variants, applied after lowercasing: what the OCS witnesses
# and their editions (TOROT, CCMH, Glagolitic transliterations) write
# differently for one sound. Cyrillic manuscripts write iotation of е, а and
# the nasals inconsistently (ꙓ is iotated, so it is я); ѕ/ꙁ/з vary by
# manuscript; ѵ, ѳ, ѯ, ѱ spell Greek loans. ѣ is folded by position below.
_CYRILLIC_LETTERS = str.maketrans({
    "і": "и", "ꙇ": "и", "ѵ": "и",
    "ѡ": "о", "ѻ": "о", "ѽ": "о", "ꙍ": "о", "ꙩ": "о", "ꙫ": "о", "ꙭ": "о", "ꙮ": "о",
    "ꚙ": "о", "ѿ": "от",
    "ѹ": "у", "ꙋ": "у",
    "ѥ": "е", "є": "е",
    "ꙗ": "я", "ꙓ": "я",
    "ꙑ": "ы",
    "ѕ": "з", "ꙁ": "з", "ꙃ": "з", "ꙅ": "з",
    "ꙙ": "ѧ", "ѩ": "ѧ", "ꙝ": "ѧ", "ѭ": "ѫ",
    "ѳ": "ф", "ѯ": "кс", "ѱ": "пс",
})
# Digraphs, after the letters: оу is one letter (u), ъі/ъи spell ꙑ.
_CYRILLIC_DIGRAPHS = {"оу": "у", "ъи": "ы"}
_CYRILLIC_DIGRAPH_RE = re.compile("|".join(_CYRILLIC_DIGRAPHS))
# Yers, after the digraphs: the front yer ь (and the neutral ꙏ) becomes ъ,
# since witnesses confuse the two; the paerok (ꙿ, ⸯ), which marks an omitted
# yer, is left out. Word-final yers are then left out too (written in OCS,
# not in modern spelling: богъ = бог); word-internal ones are kept.
_CYRILLIC_YERS = {ord("ь"): "ъ", ord("ꙏ"): "ъ", ord("ꙿ"): None, ord("ⸯ"): None}
_CYRILLIC_FINAL_YERS_RE = re.compile("ъ+(?= |$)")
# Glagolitic has one letter, Ⱑ, for ja (at the start of a word and after a
# vowel) and ě (after a consonant), and its Cyrillic transliterations write ѣ
# for both. So ѣ at a word start or after a vowel folds to я (ѣко = ꙗко =
# яко), and after anything else to е (тѣло = тело). The vowels are those left
# after the other Cyrillic folds (ѹ/оу → у, ꙑ → ы, і → и, ѥ → е, …); ѣ itself
# counts, since it has just become я or е; a yer does not.
_CYRILLIC_VOWELS = "аеиоуыюяѣѧѫ"
_CYRILLIC_YAT_JA_RE = re.compile(f"(?:^|(?<=[ {_CYRILLIC_VOWELS}]))ѣ")


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
    t = t.translate(_CYRILLIC_COMBINING_LETTERS)
    t = "".join(ch for ch in t if not _is_dropped_mark(ch))
    t = t.casefold()  # also maps final sigma (ς) and long s (ſ) to σ / s
    t = "".join(" " if _is_separator(ch) else ch for ch in t)
    t = _LATIN_DIGRAPHS.sub("e", t.translate(_LATIN_LETTERS))
    t = _CYRILLIC_DIGRAPH_RE.sub(
        lambda m: _CYRILLIC_DIGRAPHS[m.group()], t.translate(_CYRILLIC_LETTERS)
    ).translate(_CYRILLIC_YERS)
    t = _CYRILLIC_YAT_JA_RE.sub("я", t).replace("ѣ", "е")
    t = _CYRILLIC_FINAL_YERS_RE.sub("", t)
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
        nfkd = unicodedata.normalize("NFKD", ch).translate(_IN_WORD_MARKS)
        for d in nfkd.translate(_CYRILLIC_COMBINING_LETTERS):
            if _is_dropped_mark(d):
                continue
            for c in d.casefold():
                if _is_separator(c):
                    chars.append((" ", i, i + 1))
                    continue
                # A Cyrillic letter may become two (ѿ → от).
                for e in c.translate(_LATIN_LETTERS).translate(_CYRILLIC_LETTERS):
                    chars.append((e, i, i + 1))
    # The digraphs ae/oe and оу/ъи, left to right and not overlapping, as the
    # regexes do (they can't overlap each other: different letters).
    merged: list[tuple[str, int, int]] = []
    k = 0
    while k < len(chars):
        c, start, end = chars[k]
        pair = c + chars[k + 1][0] if k + 1 < len(chars) else ""
        if pair in ("ae", "oe"):
            merged.append(("e", start, chars[k + 1][2]))
            k += 2
        elif pair in _CYRILLIC_DIGRAPHS:
            merged.append((_CYRILLIC_DIGRAPHS[pair], start, chars[k + 1][2]))
            k += 2
        else:
            merged.append((c, start, end))
            k += 1
    # ь → ъ, paerok left out; then ѣ by the folded character before it.
    cyrillic: list[tuple[str, int, int]] = []
    for c, start, end in merged:
        c = c.translate(_CYRILLIC_YERS)
        if not c:
            continue
        if c == "ѣ":
            before = cyrillic[-1][0] if cyrillic else " "
            c = "я" if before in " " + _CYRILLIC_VOWELS else "е"
        cyrillic.append((c, start, end))
    # Word-final yers: a ъ followed only by ъ up to a space or the end.
    merged = []
    at_end = True
    for item in reversed(cyrillic):
        if item[0] == " ":
            at_end = True
        elif item[0] == "ъ" and at_end:
            continue
        else:
            at_end = False
        merged.append(item)
    merged.reverse()
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
