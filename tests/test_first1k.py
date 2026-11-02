"""First1KGreek ingestor: heads as heading records (#71), per-work corrections (#123, #125)."""

from __future__ import annotations

import logging
import re

from lxml import etree

from scripts.ingest.first1k import _TEXT_CORRECTIONS, _apply_corrections, _extract_paragraphs

_NS = {"tei": "http://www.tei-c.org/ns/1.0"}


def _edition(body: str) -> etree._Element:
    xml = (
        '<div xmlns="http://www.tei-c.org/ns/1.0" type="edition" '
        f'n="urn:cts:greekLit:tlg9999.tlg001.1st1K-grc1">{body}</div>'
    )
    return etree.fromstring(xml)


def _extract(body: str) -> list[tuple[str, str]]:
    return [(r["ref"], r["text"]) for r in _extract_paragraphs(_edition(body), "tlg9999.tlg001", _NS)]


def test_work_head_becomes_a_heading_before_the_text() -> None:
    body = (
        "<head>Πράξεις <note>n.</note>Ἰωάννου</head>"
        '<div type="textpart" subtype="chapter" n="2"><p>2 ἀνήνεγκαν</p></div>'
        '<div type="textpart" subtype="chapter" n="3"><p>3 Αὐτοκράτορι</p></div>'
    )
    assert _extract(body) == [
        ("tlg9999.tlg001", "Πράξεις Ἰωάννου"),
        ("tlg9999.tlg001.2", "2 ἀνήνεγκαν"),
        ("tlg9999.tlg001.3", "3 Αὐτοκράτορι"),
    ]


def test_nested_heads_and_joined_title_and_subtitle() -> None:
    body = (
        "<head>ΦΙΛΩΝΟΣ</head><head>ΠΕΡΙ ΓΙΓΑΝΤΩΝ</head>"
        '<div type="textpart" subtype="book" n="1"><head>Λόγος α</head>'
        '<div type="textpart" subtype="chapter" n="1"><head>Κεφάλαιον</head>'
        '<div type="textpart" subtype="section" n="1"><p>πρῶτον</p></div>'
        "</div></div>"
    )
    assert _extract(body) == [
        ("tlg9999.tlg001", "ΦΙΛΩΝΟΣ ΠΕΡΙ ΓΙΓΑΝΤΩΝ"),
        ("tlg9999.tlg001.1", "Λόγος α"),
        ("tlg9999.tlg001.1.1", "Κεφάλαιον"),
        ("tlg9999.tlg001.1.1.1", "πρῶτον"),
    ]


def test_head_of_a_div_holding_its_paragraphs_opens_its_first_paragraph() -> None:
    # The paragraphs share the div's ref, so the head goes at the start of the
    # first one, marked (#259); their refs (reader URLs) don't move.
    body = (
        '<div type="textpart" subtype="chapter" n="1"><head>Κεφάλαιον α</head>'
        "<p>ἕν</p><p>δύο</p></div>"
    )
    recs = _extract_paragraphs(_edition(body), "tlg9999.tlg001", _NS)
    assert [(r["ref"], r["text"]) for r in recs] == [
        ("tlg9999.tlg001.1", "Κεφάλαιον α ἕν"), ("tlg9999.tlg001.1.1", "δύο")]
    assert recs[0]["editorial"] == [[0, 11, "heading"]]
    assert "editorial" not in recs[1]


def test_flat_work_keeps_its_refs() -> None:
    body = "<head>Τίτλος</head><p>ἕν</p><p>δύο</p>"
    recs = _extract_paragraphs(_edition(body), "tlg9999.tlg001", _NS)
    assert [(r["ref"], r["text"]) for r in recs] == [
        ("tlg9999.tlg001", "Τίτλος ἕν"), ("tlg9999.tlg001.1", "δύο")]
    assert recs[0]["editorial"] == [[0, 6, "title"]]


def test_heading_records_are_marked_whole() -> None:
    body = (
        "<head>Πράξεις</head>"
        '<div type="textpart" n="2"><head>Περὶ</head>'
        '<div type="textpart" n="1"><p>ἕν</p></div></div>'
    )
    recs = _extract_paragraphs(_edition(body), "tlg9999.tlg001", _NS)
    assert [r.get("editorial") for r in recs] == [
        [[0, 7, "title"]], [[0, 4, "heading"]], None]


def test_gap_becomes_a_marked_lacuna() -> None:
    body = '<p>ἕν <gap reason="omitted"/> δύο<gap/></p><p><gap/></p><p>τρία</p>'
    recs = _extract_paragraphs(_edition(body), "tlg9999.tlg001", _NS)
    assert [(r["text"], r.get("editorial")) for r in recs] == [
        ("ἕν […] δύο […]", [[3, 6, "lacuna"], [11, 14, "lacuna"]]),
        ("τρία", None),
    ]


def test_bare_number_head_is_dropped() -> None:
    body = '<div type="textpart" n="1"><head>1.</head><div type="textpart" n="1"><p>ἕν</p></div></div>'
    assert _extract(body) == [("tlg9999.tlg001.1.1", "ἕν")]


def test_corrections_apply_once_and_report_a_miss(caplog) -> None:
    work_id = "first1k/tlg1463/tlg001/1st1K-grc1"
    paras = [
        {"ref": "tlg1463.tlg001.1.2", "text": "⁰Καὶ ἀναλαβὼν τὴν παραβολὴν"},
        {"ref": "tlg1463.tlg001.5.5", "text": "τοιγὰρ already fixed"},
    ]
    with caplog.at_level(logging.WARNING):
        out = _apply_corrections(work_id, paras)
    assert out[0]["text"] == "Καὶ ἀναλαβὼν τὴν παραβολὴν"
    assert out[1] == paras[1]
    assert paras[0]["text"].startswith("⁰")  # input not mutated
    assert "tlg1463.tlg001.5.5" in caplog.text


def test_corrections_only_remove_superscript_markers() -> None:
    # Each correction drops noise and touches nothing else.
    for corrections in _TEXT_CORRECTIONS.values():
        for _ref, old, new in corrections:
            stripped = re.sub(r"\s*[⁰¹²³⁴⁵⁶⁷⁸⁹]+", "", old).strip()
            assert stripped == new.strip(), (old, new)
