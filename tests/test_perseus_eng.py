"""Tests for the Perseus English ingestor (#344)."""

from __future__ import annotations

from pathlib import Path

from scripts.ingest import perseus_eng
from scripts.ingest.perseus_eng import EDITIONS, Edition, parse_edition

_EPIDOC = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0">
<teiHeader><fileDesc><titleStmt><title>Antiquities of the Jews</title>
<author>Flavius Josephus</author></titleStmt>
<publicationStmt><availability>
<licence target="https://creativecommons.org/licenses/by-sa/4.0/">CC BY-SA</licence>
</availability></publicationStmt></fileDesc></teiHeader>
<text><body>
<div type="translation" n="urn:cts:greekLit:tlg0526.tlg001.perseus-eng2" xml:lang="eng">
<div type="textpart" subtype="book" n="1">
<head>Book I <lb/> FROM THE CREATION</head>
<div type="textpart" subtype="section" n="1">
<milestone n="1" unit="Whiston_section"/>
<head>Preface<note resp="editor">An excellent preface.</note></head>
<p>Those who undertake
to write histories, <q>he said</q>.</p></div>
<div type="textpart" subtype="section" n="5">
<p>Now I have undertaken it for the Greeks <note resp="editor">That is, the Gentiles.</note>
worthy of study.</p></div>
</div></div></body></text></TEI>
"""

_TRACTATE = """<TEI.2><teiHeader><fileDesc><titleStmt>
<title>A Treatise</title><author>Boethius</author></titleStmt></fileDesc></teiHeader>
<text><body><pb id="p.73"/>
<head>A TREATISE AGAINST EUTYCHES</head><p>
</p><p>I have been waiting for you to
<pb id="p.5"/></p><p>DE TRINITATE
discuss the problem.</p>
<p>I. </p>
<p>Nature, then, may be affirmed.</p>
<p>And again.</p>
<p>II. </p>
<p>But Person.</p>
</body></text></TEI.2>
"""

_CONSOLATION = """<TEI.2><teiHeader><fileDesc><titleStmt>
<title>The Consolation of Philosophy</title><author>Boethius</author></titleStmt></fileDesc></teiHeader>
<text><body>
<div1 type="book" n="1">
<div2 type="chapter" n="praef"><p>I that with youthful heat did verses write</p></div2>
<div2 type="chapter" n="1"><p>While I ruminated.</p><p>This woman.</p></div2>
<div2 type="chapter" n="2"><p><quote><lb/>Alas, how thy dull mind</quote></p></div2>
<div2 type="chapter" n="2"><p>But it is rather time.</p></div2>
</div1>
<div1 type="book" n="3">
<div2 type="chapter" n="7"><p>Now what of pleasures.</p></div2>
<div2 type="chapter" n="7"><p><quote><lb/>All pleasure hath</quote></p></div2>
<div2 type="chapter" n="8"><p>Wherefore there is no doubt.</p></div2>
<div2 type="chapter" n="7"><p><quote><lb/>Alas, how ignorance</quote></p></div2>
</div1>
</body></text></TEI.2>
"""


def _parse(tmp_path: Path, name: str, xml: str, original: str = "perseus/x/y/z"):
    path = tmp_path / name
    path.write_text(xml, encoding="utf-8")
    return parse_edition(path, Edition("perseus-greeklit", name, original, "greek", "ed."))


def test_epidoc_sections_headings_and_notes(tmp_path: Path) -> None:
    work, units = _parse(tmp_path, "tlg0526.tlg001.perseus-eng2.xml", _EPIDOC,
                         "perseus/tlg0526/tlg001/perseus-grc2")
    assert work.work_id == "perseus-eng/tlg0526/tlg001/perseus-eng2"
    assert work.language == "eng"
    assert work.translation_of == "perseus/tlg0526/tlg001/perseus-grc2"
    assert work.license == "cc-by-sa-4.0"
    assert [u["ref"] for u in units] == ["tlg0526.tlg001.1", "tlg0526.tlg001.1.1", "tlg0526.tlg001.1.5"]

    book = units[0]
    assert book["text"] == "Book I FROM THE CREATION"
    assert book["editorial"] == [[0, len(book["text"]), "heading"]]

    first = units[1]
    assert first["text"] == ("Preface [An excellent preface.] Those who undertake "
                             "to write histories, “he said”.")
    spans = {(first["text"][s:e], k) for s, e, k in first["editorial"]}
    assert spans == {("Preface", "heading"), ("[An excellent preface.]", "note")}

    second = units[2]
    assert second["text"] == "Now I have undertaken it for the Greeks [That is, the Gentiles.] worthy of study."
    [(s, e, kind)] = second["editorial"]
    assert (second["text"][s:e], kind) == ("[That is, the Gentiles.]", "note")


def test_tractate_chapters_title_and_running_head(tmp_path: Path) -> None:
    _, units = _parse(tmp_path, "stoa0058.stoa023.perseus-eng1.xml", _TRACTATE)
    assert [(u["ref"], u["text"]) for u in units] == [
        ("stoa0058.stoa023.title", "A TREATISE AGAINST EUTYCHES"),
        ("stoa0058.stoa023.pr.1", "I have been waiting for you to discuss the problem."),
        ("stoa0058.stoa023.1", "I."),
        ("stoa0058.stoa023.1.1", "Nature, then, may be affirmed."),
        ("stoa0058.stoa023.1.2", "And again."),
        ("stoa0058.stoa023.2", "II."),
        ("stoa0058.stoa023.2.1", "But Person."),
    ]
    assert units[0]["editorial"] == [[0, len(units[0]["text"]), "title"]]
    assert units[2]["editorial"] == [[0, 2, "heading"]]
    assert "editorial" not in units[1]


def test_consolation_metres_and_proses(tmp_path: Path) -> None:
    _, units = _parse(tmp_path, "stoa0058.stoa001.perseus-eng1.xml", _CONSOLATION)
    assert [u["ref"] for u in units] == [
        "stoa0058.stoa001.1.M1", "stoa0058.stoa001.1.P1", "stoa0058.stoa001.1.P1.1",
        "stoa0058.stoa001.1.M2", "stoa0058.stoa001.1.P2",
        # the TEI numbers metre 3.8 as a second 7
        "stoa0058.stoa001.3.P7", "stoa0058.stoa001.3.M7", "stoa0058.stoa001.3.P8",
        "stoa0058.stoa001.3.M8",
    ]


def test_editions_point_at_their_originals() -> None:
    for spec in EDITIONS:
        textgroup, work, _ = Path(spec.path).name.split(".", 2)
        assert spec.path.startswith(f"{textgroup}/{work}/")
        # The original is the same CTS work in the original-language Perseus edition.
        assert spec.translation_of.startswith(f"perseus/{textgroup}/{work}/perseus-")
        assert not spec.translation_of.endswith(("eng1", "eng2"))
    assert perseus_eng.SOURCE_ID == "perseus-eng"
