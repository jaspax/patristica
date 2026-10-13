"""Tests for scripts.ingest._scripture_meta."""

import pytest

from scripts.ingest._scripture_meta import (
    ALL_BOOKS,
    book_abbrev,
    BOOK_DATES,
    BOOK_TITLE,
    CATHOLIC_BOOKS,
    DEUTEROCANON_BOOKS,
    FULL_NAME_TO_ABBREV,
    NT_BOOKS,
    OT_BOOKS,
    PROTESTANT_BOOKS,
    book_work_id,
)


class TestBookLists:
    def test_ot_count(self):
        assert len(OT_BOOKS) == 39

    def test_nt_count(self):
        assert len(NT_BOOKS) == 27

    def test_protestant_count(self):
        assert len(PROTESTANT_BOOKS) == 66

    def test_deuterocanon_count(self):
        assert len(DEUTEROCANON_BOOKS) == 7

    def test_catholic_count(self):
        assert len(CATHOLIC_BOOKS) == 73

    def test_no_duplicates(self):
        assert len(PROTESTANT_BOOKS) == len(set(PROTESTANT_BOOKS))
        assert len(CATHOLIC_BOOKS) == len(set(CATHOLIC_BOOKS))

    def test_known_ot_books(self):
        assert "Gen" in OT_BOOKS
        assert "Mal" in OT_BOOKS
        assert "Ps" in OT_BOOKS

    def test_known_nt_books(self):
        assert "Matt" in NT_BOOKS
        assert "Rev" in NT_BOOKS
        assert "1John" in NT_BOOKS


class TestBookTitle:
    def test_all_protestant_have_titles(self):
        missing = [b for b in PROTESTANT_BOOKS if b not in BOOK_TITLE]
        assert missing == [], f"Missing titles for: {missing}"

    def test_known_titles(self):
        assert BOOK_TITLE["Gen"] == "Genesis"
        assert BOOK_TITLE["Matt"] == "Matthew"
        assert BOOK_TITLE["Rev"] == "Revelation"
        assert BOOK_TITLE["Ps"] == "Psalms"


class TestBookDates:
    def test_all_protestant_have_dates(self):
        missing = [b for b in PROTESTANT_BOOKS if b not in BOOK_DATES]
        assert missing == [], f"Missing dates for: {missing}"

    def test_ot_dates_are_pre_ce(self):
        for abbrev in OT_BOOKS:
            d = BOOK_DATES[abbrev]
            if d.get("date_composed") is not None:
                assert d["date_composed"] < 500, f"{abbrev} date seems wrong: {d}"

    def test_nt_dates_are_ce(self):
        for abbrev in NT_BOOKS:
            d = BOOK_DATES[abbrev]
            if d.get("date_composed") is not None:
                assert d["date_composed"] > 0, f"{abbrev} date seems wrong: {d}"

    def test_date_confidence_values(self):
        valid = {"established", "approximate", "uncertain"}
        for abbrev, d in BOOK_DATES.items():
            conf = d.get("date_confidence")
            assert conf in valid, f"{abbrev}: invalid confidence {conf!r}"

    def test_date_range_order(self):
        for abbrev, d in BOOK_DATES.items():
            dr = d.get("date_range")
            if dr is not None:
                assert dr[0] <= dr[1], f"{abbrev}: date_range not ordered: {dr}"


class TestFullNameToAbbrev:
    def test_common_names_resolve(self):
        assert FULL_NAME_TO_ABBREV["Genesis"] == "Gen"
        assert FULL_NAME_TO_ABBREV["Matthew"] == "Matt"
        assert FULL_NAME_TO_ABBREV["Psalms"] == "Ps"
        assert FULL_NAME_TO_ABBREV["1 Corinthians"] == "1Cor"
        assert FULL_NAME_TO_ABBREV["Revelation"] == "Rev"

    def test_variant_names(self):
        assert FULL_NAME_TO_ABBREV["Song of Solomon"] == "Song"
        assert FULL_NAME_TO_ABBREV["Song of Songs"] == "Song"
        assert FULL_NAME_TO_ABBREV["Ecclesiasticus"] == "Sir"

    def test_roman_numeral_prefixes(self):
        # scrollmapper CSVs (ASV, CopSahBible2) use roman numerals
        assert book_abbrev("I Samuel") == "1Sam"
        assert book_abbrev("III John") == "3John"
        assert book_abbrev("IV Maccabees") == "4Macc"
        assert book_abbrev("Revelation of John") == "Rev"
        assert book_abbrev("Isaiah") == "Isa"  # leading "I" of a name is not a numeral
        assert book_abbrev("Nonexistent Book") is None

    def test_all_values_are_known_abbrevs(self):
        for name, abbrev in FULL_NAME_TO_ABBREV.items():
            assert abbrev in ALL_BOOKS, f"Unknown abbrev {abbrev!r} for name {name!r}"


class TestBookWorkId:
    def test_simple(self):
        assert book_work_id("oshb", "Gen") == "oshb/gen"

    def test_nt(self):
        assert book_work_id("kjv", "Matt") == "kjv/matt"

    def test_numbered_book(self):
        assert book_work_id("asv", "1Cor") == "asv/1cor"
