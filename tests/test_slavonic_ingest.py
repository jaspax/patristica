"""Glagolitic → Cyrillic for Church Slavonic ingestors (#330)."""

import unicodedata

from patristica.textfold import fold
from scripts.ingest._slavonic import glagolitic_to_cyrillic, has_glagolitic
from scripts.validate import SCRIPT_RANGES, _script_ratio


def test_john_1_1():
    glag = "Ⰻⱄⰽⱁⱀⰻ ⰱⱑ ⱄⰾⱁⰲⱁ · ⰹ ⱄⰾⱁⰲⱁ ⰱⱑ ⱁⱅⱏ ⰱ҃ⰰ"
    assert glagolitic_to_cyrillic(glag) == "Искони бѣ слово · і слово бѣ отъ б҃а"
    assert fold(glagolitic_to_cyrillic(glag)) == fold("Искони бѣ слово. ꙇ слово бѣ отъ б҃а")


def test_digraphs_and_yery():
    assert glagolitic_to_cyrillic("ⱁⱆⱍⰵⱀⰹⰽⰹ") == "оученікі"
    assert glagolitic_to_cyrillic("ⰱⱏⰹⱅⰹ") == "бꙑті"
    assert glagolitic_to_cyrillic("Ⱏⰻ") == "Ꙑ"
    assert glagolitic_to_cyrillic("ⰱⱏ҃ⰻ") == "бꙑ҃"  # a mark on the yer stays


def test_case_is_kept():
    for lower in range(0x2C30, 0x2C60):
        upper = chr(lower - 0x30)
        assert glagolitic_to_cyrillic(upper) == glagolitic_to_cyrillic(chr(lower)).upper()


def test_every_glagolitic_letter_becomes_cyrillic():
    cyrillic = SCRIPT_RANGES["chu"]
    for cp in [*range(0x2C00, 0x2C60), *range(0x1E000, 0x1E030)]:
        ch = chr(cp)
        if unicodedata.category(ch) == "Cn":
            continue
        out = glagolitic_to_cyrillic(ch)
        assert out and not has_glagolitic(out), hex(cp)
        assert _script_ratio(out, cyrillic) == 1.0, hex(cp)
        if unicodedata.category(ch) == "Mn":
            assert all(unicodedata.category(c) == "Mn" for c in out), hex(cp)


def test_combining_letters():
    assert glagolitic_to_cyrillic("ⱈ\U0001e014") == "хⷭ"


def test_suprasliensis_strays():
    # TOROT's Suprasliensis writes some Cyrillic letters with Glagolitic ones.
    assert glagolitic_to_cyrillic("мѣсⱕца марта") == "мѣсѧца марта"
    assert glagolitic_to_cyrillic("амⰹн ⁘") == "амін ⁘"


def test_other_text_unchanged():
    for text in ("Искони бѣ слово", "Ἐν ἀρχῇ", "In principio", "", "ⲁⲛⲟⲕ"):
        assert glagolitic_to_cyrillic(text) == text
        assert not has_glagolitic(text)
