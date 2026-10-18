"""Unit tests for the OCR n-gram PoC scorers (scripts/ocr_poc)."""

from __future__ import annotations

from scripts.ocr_poc.corpus import norm
from scripts.ocr_poc.models import (
    AccentLexicon,
    CharNgram,
    ScriptUnigram,
    Unigram,
    accent_key,
    foreign,
    prep,
)

GREEK = [
    "ἐν ἀρχῇ ἦν ὁ λόγος, καὶ ὁ λόγος ἦν πρὸς τὸν θεόν, καὶ θεὸς ἦν ὁ λόγος.",
    "οὗτος ἦν ἐν ἀρχῇ πρὸς τὸν θεόν. πάντα δι’ αὐτοῦ ἐγένετο.",
] * 50


def test_norm_unifies_encoding_variants() -> None:
    assert norm("διʼ αὐτοῦ  ἀϐουλίας") == "δι’ αὐτοῦ ἀβουλίας"


def test_prep_masks_latin_apparatus_but_not_ocr_damage() -> None:
    assert (
        prep("Petro (Matth. xiv. 29)? Joanne (Joan. XIII, 23)", "lat")
        == "petro (matth. 0. 0)? joanne (joan. 0, 0)"
    )
    # Words made of numeral letters stay; digits glued to letters stay.
    assert prep("dic mihi, id est vi", "lat") == "dic mihi, id est vi"
    assert prep("magni1 (b) Victorius :", "lat") == "magni1 victorius:"
    # In Greek only footnote markers go; a lone digit is OCR damage (6 for ὁ).
    assert prep("ἀπέναντι (58) ὑμῶν 6 τὴν", "grc") == "ἀπέναντι ὑμῶν 6 τὴν"


def test_prep_keeps_polytonic_letters_composed() -> None:
    # Bare casefold() turns ῶ into ω + U+0342.
    assert prep("ὑμῶν", "grc") == "ὑμῶν"
    assert len(prep("ῶ", "grc")) == 1


def test_foreign_letters_by_script() -> None:
    assert foreign("o", "grc") and foreign("6", "grc")
    assert not foreign("ο", "grc") and not foreign("·", "grc")
    assert foreign("ο", "lat") and not foreign("6", "lat")


def test_script_unigram_flags_latin_lookalike_even_if_seen() -> None:
    texts = GREEK + ["apparatus criticus"]  # Latin letters do occur in the reference
    plain, script = Unigram(texts), ScriptUnigram(texts, "grc")
    damaged = "καὶ at λόγος"
    assert script.score(damaged) > plain.score(damaged)
    assert script.score(damaged) > script.score("καὶ ὁ λόγος")


def test_bigram_flags_bad_context_of_common_letters() -> None:
    bi = CharNgram(GREEK, 2)
    # Same letters, impossible order: word-initial smooth breathing read as grave.
    assert bi.score("ὲν ἀρχῇ") > bi.score("ἐν ἀρχῇ")
    assert ["ὲ"] == [g.strip() for g in bi.explain("ὲν ἀρχῇ", bi.score("ἐν ἀρχῇ"))]


def test_accent_lexicon_folds_grave_but_keeps_breathing() -> None:
    assert accent_key("γὰρ") == accent_key("γάρ")
    lex = AccentLexicon(GREEK)
    assert lex.score("ἐν ἀρχῇ") == 0.0
    assert lex.score("έν ἀρχῇ") == 0.5  # breathing dropped
