"""
Shared helpers for Church Slavonic (``chu``) ingestors (#29, #330).

The corpus stores Slavonic in Cyrillic: Glagolitic witnesses (Marianus,
Zographensis, Assemanianus, the Psalterium Sinaiticum, the Kiev Missal) are
stored in Cyrillic transliteration, the owner's decision on #29, since anyone
who reads Glagolitic reads Cyrillic. Sources mostly give Cyrillic or ASCII
already, but stray Glagolitic remains (Suprasliensis in TOROT has ~1,300
Glagolitic letters standing for Cyrillic ones), so every Slavonic ingestor
passes its text through :func:`glagolitic_to_cyrillic`. ``scripts.validate``
counts Glagolitic in a ``chu`` chunk as the wrong script.

Kept free of ``patristica`` imports: it is part of each Slavonic ingestor's
code hash (ingest stamps, #130).
"""

from __future__ import annotations

import re

# Glagolitic (U+2C00–2C5F) → Cyrillic, lower case; capitals map to the upper
# case of the same letter. The letter names are Unicode's. The three i-letters
# follow the CCMH/TOROT convention: izhe (value 10) → і, initial izhe (the
# broad variant) → ꙇ, i (value 20) → и. Uk is half of the digraph ⱁⱆ (оу).
# Rare letters: pe → п; yo → ꙗ (how TOROT's Suprasliensis uses it: тоⱖ,
# глѫбокъⱖ); small yus with tail → ѧ (Suprasliensis: тⱕ, мѣсⱕца); shtapic,
# the Croatian yer stroke → ъ; the Croatian angular forms → their letters.
_GLAGOLITIC_LOWER: dict[int, str] = {
    0x2C30: "а",  # azu
    0x2C31: "б",  # buky
    0x2C32: "в",  # vede
    0x2C33: "г",  # glagoli
    0x2C34: "д",  # dobro
    0x2C35: "е",  # yestu
    0x2C36: "ж",  # zhivete
    0x2C37: "ѕ",  # dzelo
    0x2C38: "з",  # zemlja
    0x2C39: "і",  # izhe
    0x2C3A: "ꙇ",  # initial izhe
    0x2C3B: "и",  # i
    0x2C3C: "ꙉ",  # djervi
    0x2C3D: "к",  # kako
    0x2C3E: "л",  # ljudije
    0x2C3F: "м",  # myslite
    0x2C40: "н",  # nashi
    0x2C41: "о",  # onu
    0x2C42: "п",  # pokoji
    0x2C43: "р",  # ritsi
    0x2C44: "с",  # slovo
    0x2C45: "т",  # tvrido
    0x2C46: "у",  # uku
    0x2C47: "ф",  # fritu
    0x2C48: "х",  # heru
    0x2C49: "ѡ",  # otu
    0x2C4A: "п",  # pe
    0x2C4B: "щ",  # shta
    0x2C4C: "ц",  # tsi
    0x2C4D: "ч",  # chrivi
    0x2C4E: "ш",  # sha
    0x2C4F: "ъ",  # yeru (the back yer)
    0x2C50: "ь",  # yeri
    0x2C51: "ѣ",  # yati (also ja: Glagolitic has one letter for both)
    0x2C52: "х",  # spidery ha
    0x2C53: "ю",  # yu
    0x2C54: "ѧ",  # small yus
    0x2C55: "ѧ",  # small yus with tail
    0x2C56: "ꙗ",  # yo
    0x2C57: "ѩ",  # iotated small yus
    0x2C58: "ѫ",  # big yus
    0x2C59: "ѭ",  # iotated big yus
    0x2C5A: "ѳ",  # fita
    0x2C5B: "ѵ",  # izhitsa
    0x2C5C: "ъ",  # shtapic
    0x2C5D: "а",  # trokutasti a
    0x2C5E: "м",  # latinate myslite
    0x2C5F: "ч",  # caudate chrivi
}

# Combining Glagolitic letters (U+1E000–1E02F, letters written above the line)
# → the combining Cyrillic letter of the same sound (U+2DE0–2DFF, U+A674–A69F).
_GLAGOLITIC_COMBINING: dict[int, str] = {
    0x1E000: "\u2df6",  # azu → a
    0x1E001: "\u2de0",  # buky → be
    0x1E002: "\u2de1",  # vede → ve
    0x1E003: "\u2de2",  # glagoli → ghe
    0x1E004: "\u2de3",  # dobro → de
    0x1E005: "\u2df7",  # yestu → ie
    0x1E006: "\u2de4",  # zhivete → zhe
    0x1E008: "\u2de5",  # zemlja → ze
    0x1E009: "\ua675",  # izhe → i
    0x1E00A: "\ua675",  # initial izhe → i
    0x1E00B: "\ua675",  # i → i
    0x1E00C: "\u2df8",  # djervi → djerv
    0x1E00D: "\u2de6",  # kako → ka
    0x1E00E: "\u2de7",  # ljudije → el
    0x1E00F: "\u2de8",  # myslite → em
    0x1E010: "\u2de9",  # nashi → en
    0x1E011: "\u2dea",  # onu → o
    0x1E012: "\u2deb",  # pokoji → pe
    0x1E013: "\u2dec",  # ritsi → er
    0x1E014: "\u2ded",  # slovo → es
    0x1E015: "\u2dee",  # tvrido → te
    0x1E016: "\ua677",  # uku → u
    0x1E017: "\ua69e",  # fritu → ef
    0x1E018: "\u2def",  # heru → ha
    0x1E01B: "\u2df3",  # shta → shcha
    0x1E01C: "\u2df0",  # tsi → tse
    0x1E01D: "\u2df1",  # chrivi → che
    0x1E01E: "\u2df2",  # sha → sha
    0x1E01F: "\ua678",  # yeru → hard sign
    0x1E020: "\ua67a",  # yeri → soft sign
    0x1E021: "\u2dfa",  # yati → yat
    0x1E023: "\u2dfb",  # yu → yu
    0x1E024: "\u2dfd",  # small yus → little yus
    0x1E026: "\u2dfc",  # yo → iotified a
    0x1E027: "\u2dfd",  # iotated small yus → little yus
    0x1E028: "\u2dfe",  # big yus → big yus
    0x1E029: "\u2dff",  # iotated big yus → iotified big yus
    0x1E02A: "\u2df4",  # fita → fita
}

_TABLE: dict[int, str] = {
    **_GLAGOLITIC_LOWER,
    **{cp - 0x30: s.upper() for cp, s in _GLAGOLITIC_LOWER.items()},
    **_GLAGOLITIC_COMBINING,
}

# Glagolitic writes ꙑ as yer + i (ⱏⰹ, ⱏⰺ, ⱏⰻ); Cyrillic editions (TOROT) as
# one letter. Combining marks may sit on the yer.
_YERY_RE = re.compile("([\u2c1f\u2c4f])([\u0300-\u036f\u0483-\u0489\ua66f-\ua67d]*)"
                      "[\u2c09-\u2c0b\u2c39-\u2c3b]")

_GLAGOLITIC_RE = re.compile("[\u2c00-\u2c5f\U0001e000-\U0001e02f]")


def has_glagolitic(text: str) -> bool:
    """True if *text* has any Glagolitic letter (U+2C00–2C5F, U+1E000–1E02F)."""
    return _GLAGOLITIC_RE.search(text) is not None


def glagolitic_to_cyrillic(text: str) -> str:
    """Transliterate the Glagolitic in *text* into Cyrillic; leave the rest.

    Letter for letter (case kept), except yer + i, which becomes ꙑ, as in
    TOROT's Cyrillic. Combining Glagolitic letters become combining Cyrillic
    letters. ``glagolitic_to_cyrillic(c) == c`` for text with no Glagolitic.
    """
    if not has_glagolitic(text):
        return text
    text = _YERY_RE.sub(lambda m: ("Ꙑ" if m.group(1) == "\u2c1f" else "ꙑ") + m.group(2), text)
    return text.translate(_TABLE)
