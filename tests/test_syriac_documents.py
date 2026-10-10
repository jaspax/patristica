"""Tests for the ANF08 Syriac documents ingestor's pure helpers."""

from __future__ import annotations

import pytest
from lxml import etree

from scripts.ingest import syriac_documents as sd
from scripts.ingest._ccel_common import EXCLUDED_DIVS


def test_roman_to_int() -> None:
    assert sd.roman_to_int("I") == 1
    assert sd.roman_to_int("IV") == 4
    assert sd.roman_to_int("viii") == 8
    assert sd.roman_to_int("XIV") == 14
    with pytest.raises(ValueError):
        sd.roman_to_int("12")


@pytest.mark.parametrize("text", [
    "Ancient Syriac Documents.", "————————————", "• • • • • •", "VII.",
])
def test_is_noise_true(text: str) -> None:
    assert sd.is_noise(text)


@pytest.mark.parametrize("text", [
    "Here endeth the teaching of Simon Cephas.", "I.e. the king", "Bardesan.",
])
def test_is_noise_false(text: str) -> None:
    assert not sd.is_noise(text)


def test_extract_sectioned_skips_and_numbers() -> None:
    div = etree.fromstring(
        '<div2 id="ix.v">'
        '<div3 id="ix.v.i" n="I"><p>Ancient Syriac Documents.</p><p>I.</p><p>One</p></div3>'
        '<div3 id="ix.v.ii" n="II"><p>Two <note>fn</note>a</p><p>Two b</p></div3>'
        '<div3 id="ix.v.iii" n="III"><p>Skipped</p></div3>'
        "</div2>"
    )
    spec = next(s for s in sd._WORKS if s.slug == "abgar-addai-extracts")
    spec = sd._WorkSpec(**{**spec.__dict__, "skip_ids": ("ix.v.iii",)})
    assert sd.extract_paragraphs(div, spec) == [
        {"ref": "AbgarExtr.1.1", "text": "One"},
        {"ref": "AbgarExtr.2.1", "text": "Two a"},
        {"ref": "AbgarExtr.2.2", "text": "Two b"},
    ]


def test_table_consistent_with_excluded_divs() -> None:
    """Every div the table reads or drops is registered for anf08, and all are pre-Schism."""
    excluded = EXCLUDED_DIVS["anf08"]
    for spec in sd._WORKS:
        covered = spec.div_id in excluded or any(
            spec.div_id.startswith(d + ".") and excluded[d] == sd.SOURCE_ID for d in excluded
        )
        assert covered, spec.div_id
        assert spec.date_range[0] <= spec.date_composed <= spec.date_range[1] <= 1054
    for div_id in sd.EDITORIAL_DIVS:
        assert excluded[div_id] == "non-text: editorial"
    assert len({s.slug for s in sd._WORKS}) == len(sd._WORKS)
    assert len({s.ref_prefix for s in sd._WORKS}) == len(sd._WORKS)
