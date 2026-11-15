"""Tests for Brenton's English Septuagint and the KJV's 4 Ezra (#355)."""

from __future__ import annotations

import pytest

from patristica import versification as vz
from patristica.editorial import strip
from patristica.translation_links import curated_translation_of
from scripts.ingest.brenton_eng import BOOKS, make_work, parse_brenton_usfm
from scripts.ingest.kjv_apocrypha_eng import four_ezra_units

BOOK = """\\id PSA - Brenton English Septuagint
\\h Psalms
\\mt1 PSALMS
\\c 4
\\d
\\v 1 For the end, a Song of David among \\add the \\add*Psalms.
\\p
\\v 9 I will \\f + \\fr 4:9 \\fqa Or, \\ft at the same time.\\f*both lie down in peace.
\\v 9a And \\x + \\xo 4:9 \\xt Heb. 13. 5.\\x* I will not fail thee.
\\p And this goes on.
\\c 5
\\v 1 \\sc The Vision\\sc* of Esaias.
"""


def _units(text: str = BOOK, book: str = "Ps") -> dict[str, dict]:
    return {u["ref"]: u for u in parse_brenton_usfm(text, book)}


def test_verses_keep_lettered_numbers_and_continuation_lines() -> None:
    units = _units()
    assert list(units) == ["Ps.4.1", "Ps.4.9", "Ps.4.9a", "Ps.5.1"]
    assert units["Ps.4.1"]["text"] == "For the end, a Song of David among the Psalms."
    assert units["Ps.5.1"]["text"] == "The Vision of Esaias."
    assert "editorial" not in units["Ps.4.1"]


def test_notes_go_to_the_end_of_their_verse_marked() -> None:
    units = _units()
    u = units["Ps.4.9"]
    assert u["text"] == "I will both lie down in peace. [Or, at the same time.]"
    assert u["editorial"] == [[31, 54, "note"]]
    assert u["text"][31:54] == "[Or, at the same time.]"
    assert strip(u["text"], [tuple(s) for s in u["editorial"]]) == "I will both lie down in peace."
    x = units["Ps.4.9a"]
    assert x["text"] == "And I will not fail thee. And this goes on. [Heb. 13. 5.]"
    assert x["text"][x["editorial"][0][0]:] == "[Heb. 13. 5.]"


def test_unknown_line_marker_raises() -> None:
    with pytest.raises(ValueError, match="unexpected USFM line"):
        parse_brenton_usfm("\\c 1\n\\v 1 a\n\\s1 A heading\n", "Gen")


def test_duplicate_verse_raises() -> None:
    with pytest.raises(ValueError, match="twice"):
        parse_brenton_usfm("\\c 1\n\\v 1 a\n\\v 1 b\n", "Gen")


def test_book_codes_and_work_ids() -> None:
    assert BOOKS["EZR"] == "EzraNeh" and "NEH" not in BOOKS  # NEH repeats 2 Esdras 11-23
    assert BOOKS["DAG"] == "Dan" and BOOKS["LJE"] == "EpJer" and BOOKS["MAN"] == "PrMan"
    assert make_work("EzraNeh").work_id == "brenton-eng/ezraneh"
    assert make_work("BelDr").work_id == "brenton-eng/beldr"
    assert make_work("Dan").title == "Daniel (Theodotion)"
    assert make_work("Gen").license == "public_domain"


@pytest.mark.parametrize(("work_id", "original"), [
    ("brenton-eng/gen", "pta-lxx/gen"),
    ("brenton-eng/judg", "pta-lxx/judgvat"),
    ("brenton-eng/dan", "pta-lxx/danthdt"),
    ("brenton-eng/sus", "pta-lxx/susthdt"),
    ("brenton-eng/beldr", "pta-lxx/beldrthdt"),
    ("brenton-eng/tob", "pta-lxx/tobvatal"),
    ("brenton-eng/1esd", "pta-lxx/1esr"),
    ("brenton-eng/ezraneh", "pta-lxx/ezraneh"),
    ("brenton-eng/prman", None),
    ("kjv-apocrypha-eng/4esr", None),
])
def test_translation_of(work_id: str, original: str | None) -> None:
    assert curated_translation_of(work_id) == original


def test_versification() -> None:
    # LXX numbering for the books from the Greek: LXX Psalm 9:22 is Hebrew 10:1.
    assert vz.to_org_ref("brenton-eng", "Ps.9.22") == vz.to_org_ref("pta-lxx", "Ps.9.22")
    # The Apocrypha follow the KJV's numbering.
    assert vz.scheme_for("brenton-eng", "Tob") == "eng"
    assert vz.scheme_for("brenton-eng", "Sir") == "lxx"
    assert vz.to_org_ref("brenton-eng", "EzraNeh.11.1") == vz.to_org_ref("pta-lxx", "EzraNeh.11.1")


def test_four_ezra_keeps_chapters_3_to_14() -> None:
    usfm = "\\id 2ES\n\\c 2\n\\p\n\\v 1 Five Ezra.\n\\c 3\n\\p\n\\v 1 In the thirtieth year.\n" \
           "\\c 14\n\\v 48 End.\n\\c 15\n\\v 1 Six Ezra.\n"
    assert [u["ref"] for u in four_ezra_units(usfm)] == ["4Esr.3.1", "4Esr.14.48"]
