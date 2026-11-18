"""OCR eval scorer (#718): CER, accent share, WER, real-word substitutions."""

import unicodedata

import pytest

from scripts.ocr.eval.metrics import Counts, clean, score_page, strip_marks

LEX = frozenset({"λογοσ", "νομοσ", "και", "θεοσ", "ην", "εν", "αρχη", "ο"})


def test_identical_page_scores_zero() -> None:
    c = score_page("Ἐν ἀρχῇ ἦν ὁ λόγος", "Ἐν ἀρχῇ ἦν ὁ λόγος", LEX)
    assert (c.char_errors, c.word_errors, c.cer, c.wer) == (0, 0, 0.0, 0.0)
    assert c.accent_share == 0.0


def test_nfc_and_whitespace_are_not_errors() -> None:
    nfd = unicodedata.normalize("NFD", "ἀρχῇ  ἦν")
    c = score_page("ἀρχῇ ἦν", nfd + "\n", LEX)
    assert c.char_errors == 0


def test_accent_error_counts_in_cer_not_base_cer() -> None:
    # λόγος → λογός: two character errors, both accents.
    c = score_page("ὁ λόγος", "ὁ λογός", LEX)
    assert c.char_errors == 2
    assert c.base_errors == 0
    assert c.accent_share == 1.0
    assert (c.word_subs, c.accent_words, c.realword_subs) == (1, 1, 0)


def test_breathing_error_is_an_accent_error() -> None:
    c = score_page("ἐν", "ἑν", LEX)
    assert c.char_errors == 1 and c.base_errors == 0


def test_real_word_substitution() -> None:
    # νόμος is a valid form, so a dictionary check would pass it.
    c = score_page("ὁ λόγος ἦν", "ὁ νόμος ἦν", LEX)
    assert c.realword_subs == 1
    assert c.examples == [("λόγος", "νόμος")]
    assert c.accent_share == 0.0


def test_non_word_substitution_is_not_real_word() -> None:
    c = score_page("ὁ λόγος", "ὁ λόγοc", LEX)
    assert (c.word_subs, c.realword_subs, c.accent_words) == (1, 0, 0)


def test_split_word_is_two_word_errors() -> None:
    c = score_page("ὁ λόγος ἦν", "ὁ λό γος ἦν", LEX)
    assert c.word_errors == 2
    assert c.realword_subs == 0 and c.accent_words == 0


def test_dehyphenate_applies_to_both_sides() -> None:
    ref = "ὁ λό-\nγος ἦν"
    assert score_page(ref, "ὁ λόγος ἦν", LEX).char_errors == 2
    assert score_page(ref, "ὁ λόγος ἦν", LEX, dehyphenate=True).char_errors == 0


def test_columns() -> None:
    c = score_page("ὁ", "ὁ", LEX, ref_columns=(11, 12), hyp_columns=(11, 12))
    assert (c.column_pages, c.column_hits) == (1, 1)
    c = score_page("ὁ", "ὁ", LEX, ref_columns=(11, 12), hyp_columns=(11, 13))
    assert (c.column_pages, c.column_hits) == (1, 0)
    assert score_page("ὁ", "ὁ", LEX, ref_columns=(11, 12)).column_accuracy is None


def test_counts_sum() -> None:
    a = score_page("ὁ λόγος", "ὁ λογός", LEX)
    b = score_page("καὶ θεὸς", "καὶ θεὸς", LEX)
    total = a + b
    assert total.pages == 2
    assert total.chars == a.chars + b.chars
    assert total.cer == pytest.approx(2 / total.chars)
    assert Counts().cer == 0.0


def test_helpers() -> None:
    assert clean(" a\n\tb  ") == "a b"
    assert strip_marks("ἀρχῇ") == "αρχη"


def test_unrelated_pair_is_not_a_real_word_substitution() -> None:
    # Both are valid forms, but nothing alike: an alignment artefact.
    c = score_page("ὁ θεὸς ἦν", "ὁ καὶ ἦν", LEX)
    assert (c.word_subs, c.realword_subs) == (1, 0)


def test_fold_conventions() -> None:
    ref = "δι´ οὗ ἡμῖν"
    hyp = "δι' οὗ ¹⁸ ἡμῖν (3)"
    assert score_page(ref, hyp, LEX).char_errors > 0
    assert score_page(ref, hyp, LEX, conventions=True).char_errors == 0
