"""Tests for the per-book and per-chapter scheme overrides of patristica.versification (#186)."""

from __future__ import annotations

import pytest

from patristica import versification as vz


def test_chapter_override_beats_book_and_source() -> None:
    # Armenian Numbers is English-style (book override) except chapter 13, Vulgate-style.
    assert vz.scheme_for("armenian", "Num") == "eng"
    assert vz.scheme_for("armenian", "Num", 30) == "eng"
    assert vz.scheme_for("armenian", "Num", 13) == "vul"
    assert vz.to_org_ref("armenian", "Num.13.1") == "Num.12.16"
    assert vz.to_org_ref("armenian", "Num.30.1") == "Num.30.2"


def test_chapter_override_leaves_other_chapters() -> None:
    # Coptic Isaiah 9 is numbered as in English (9:1 = Hebrew 8:23); the rest is LXX.
    assert vz.to_org_ref("coptic-nt", "Isa.9.1") == "Isa.8.23"
    assert vz.to_org_ref("coptic-nt", "Isa.9.2") == "Isa.9.1"
    assert vz.scheme_for("coptic-nt", "Isa", 8) == "lxx"


def test_overrides_name_known_sources_books_and_schemes() -> None:
    books = set(vz._OSIS_TO_USFM)
    for source, book, *_ in [*vz.BOOK_SCHEME_OVERRIDES, *vz.CHAPTER_SCHEME_OVERRIDES]:
        assert source in vz.SOURCE_SCHEMES
        assert book in books
    for scheme in [*vz.BOOK_SCHEME_OVERRIDES.values(), *vz.CHAPTER_SCHEME_OVERRIDES.values()]:
        assert scheme in ("org", "eng", "lxx", "vul")


def test_english_psalm_title_maps_to_org_title_verse() -> None:
    """ASV Ps.N.0 (the title as its own unit, #220) pairs with org verse 1."""
    assert vz.to_org_ref("asv", "Ps.3.0") == "Ps.3.1"    # org title is its own verse
    assert vz.to_org_ref("asv", "Ps.3.1") == "Ps.3.2"
    assert vz.to_org_ref("asv", "Ps.23.0") == "Ps.23.1"  # org title starts verse 1
    assert vz.to_org_ref("asv", "Ps.23.1") == "Ps.23.1"
    assert vz.to_org_ref("asv", "Ps.51.0") == "Ps.51.1"  # org title is verses 1–2
    assert vz.to_org_ref("asv", "Ps.51.1") == "Ps.51.3"


def test_unregistered_source_still_raises() -> None:
    with pytest.raises(vz.VersificationError):
        vz.scheme_for("nope", "Gen", 1)
