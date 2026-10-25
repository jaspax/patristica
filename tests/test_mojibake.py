"""Double-encoded UTF-8 repair (#124)."""

from __future__ import annotations

import pytest
from lxml import etree

from patristica.mojibake import mojibake_runs, repair_double_utf8
from scripts.ingest.perseus import _extract_paragraphs


def _mangle(text: str) -> str:
    return text.encode("utf-8").decode("latin-1")


@pytest.mark.parametrize("original", [
    "λόγον", "οἰκονομίᾳ", "οἰκονομίας", "Αἰῶνα Τέλειον", "Προαρχὴν", "Israël", "poētica",
])
def test_repairs_double_encoded_words(original: str) -> None:
    text = f"quam {_mangle(original)} dicimus"
    assert repair_double_utf8(text) == f"quam {original} dicimus"
    assert mojibake_runs(text)
    assert mojibake_runs(repair_double_utf8(text)) == []


@pytest.mark.parametrize("text", [
    "Ἀρχὴ λόγου· καὶ «ταῦτα» — ἔστι",       # real Greek, guillemets, middle dot
    "café, naïve, Ægyptus, ½ et ¾",          # Latin-1 text that is not UTF-8 bytes
    "Ã alone, Ã« broken Ã",                   # a lone lead byte, then Ã« (ë) mid-word
    "é»",                                     # E9 BB: a three-byte lead with one continuation
    "PRÆ\u00adFATIO",                           # OCR soft hyphen: UTF-8 of U+01AD, implausible
])
def test_leaves_text_that_is_not_provably_double_encoded(text: str) -> None:
    expected = text.replace("Ã«", "ë")  # the one well-formed run
    assert repair_double_utf8(text) == expected


def test_perseus_paragraph_repaired_before_whitespace_collapse() -> None:
    # "Π" is CE A0: its second byte is a no-break space, which \s+ would eat.
    xml = (
        '<div xmlns="http://www.tei-c.org/ns/1.0" type="edition">'
        f'<div type="textpart" n="1"><p>vero {_mangle("Προαρχὴν")}  et\n{_mangle("Τὴν")}</p></div></div>'
    )
    records = _extract_paragraphs(etree.fromstring(xml), "stoa9999.stoa001", {})
    assert records == [{"ref": "stoa9999.stoa001.1", "text": "vero Προαρχὴν et Τὴν"}]
