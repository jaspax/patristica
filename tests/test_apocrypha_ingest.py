"""Greek apocrypha ingestors (#78): Wikisource verse pages, OCP chapters."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ingest.ocp import Book
from scripts.ingest.ocp import parse as parse_ocp
from scripts.ingest.wikisource_apocrypha import PAGES, Page, parse, roman

_PAGE = Page("t", "T", 1, "ApX", "Title", "ed.", 500, (400, 600))


def test_roman() -> None:
    assert [roman(s) for s in ("I", "IV", "IX", "XIV", "XL")] == [1, 4, 9, 14, 40]


def test_chapters_and_bold_verse_numbers() -> None:
    text = ("{{Τίτλος|x}}\nΤοῦ ἁγίου λόγος.\n=== I ===\n'''1'''&nbsp;Ἀγαπητοί,\n"
            "'''2'''&nbsp;καὶ διὰ τοῦτο\nκαὶ ἔτι.\n;II\n'''1'''&nbsp;Ἐγένετο\n"
            "[[Κατηγορία:Απόκρυφα]]")
    assert parse(_PAGE, text) == [
        {"ref": "ApX.0", "text": "Τοῦ ἁγίου λόγος."},
        {"ref": "ApX.1.1", "text": "Ἀγαπητοί,"},
        {"ref": "ApX.1.2", "text": "καὶ διὰ τοῦτο καὶ ἔτι."},  # an unnumbered line joins its verse
        {"ref": "ApX.2.1", "text": "Ἐγένετο"},
    ]


def test_testaments_carry_the_patriarch() -> None:
    page = Page("t", "T", 1, "T12P", "Title", "ed.", 150, (-100, 200))
    text = "==ΔΙΑΘΗΚΗ ΡΟΥΒΗΜ ΠΕΡΙ ΕΝΝΟΙΩΝ==\n===ΚΕΦΑΛΑΙΟ 1===\n1. Ἀντίγραφον\n2.Μετὰ\n" \
           "==ΔΙΑΘΗΚΗ ΣΥΜΕΩΝ==\n===ΚΕΦΑΛΑΙΟ 1===\n1. Ἀντίγραφον"
    refs = [r["ref"] for r in parse(page, text)]
    assert refs == ["T12P.Reub.1.1", "T12P.Reub.1.2", "T12P.Sim.1.1"]


def test_unknown_heading_is_an_error() -> None:
    with pytest.raises(ValueError, match="unknown heading"):
        parse(_PAGE, "== Σχόλια ==\n'''1''' x")


def test_pages_are_pinned() -> None:
    assert all(p.revid > 0 for p in PAGES) and len({p.prefix for p in PAGES}) == len(PAGES)


def test_ocp_version_chapters(tmp_path: Path) -> None:
    path = tmp_path / "Book.xml"
    path.write_text(
        '<book><version title="Latin"><text><div number="1"><div number="0">'
        '<unit><reading>Latina</reading></unit></div></div></text></version>'
        '<version title="Greek"><text>'
        '<div number="Title"><div number="0">'
        '<unit><reading>APOCALYPSIS</reading></unit></div></div>'
        '<div number="Prologus"><div number="0">'
        '<unit><reading>Διήγησις</reading></unit></div></div>'
        '<div number="1"><div number="0 "><unit><reading>Αὕτη</reading></unit>'
        '<unit><reading>ἡ διήγησις</reading></unit></div></div>'
        '</text></version></book>', encoding="utf-8")
    book = Book("b", "Book", "Greek", "ApMos", "T", "ed.", 200, (100, 400))
    assert parse_ocp(book, path) == [
        {"ref": "ApMos", "text": "APOCALYPSIS"}, {"ref": "ApMos.0", "text": "Διήγησις"},
        {"ref": "ApMos.1", "text": "Αὕτη ἡ διήγησις"},
    ]
