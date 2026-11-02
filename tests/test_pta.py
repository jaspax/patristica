"""Tests for the PTA ingestor's catalogue identifiers (#178) and licences (#366)."""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from patristica import editorial
from scripts.ingest._slavonic import glagolitic_to_cyrillic
from scripts.ingest.pta import (
    _convert,
    _extract_paragraphs,
    _flatten,
    _license_from_prose,
    _license_from_target,
    read_work_ids,
)

CTS = """<ti:work xmlns:ti="http://chs.harvard.edu/xmlns/cts"
         xmlns:cpt="http://purl.org/capitains/ns/1.0#"
         xmlns:dc="http://purl.org/dc/elements/1.1/"
         urn="urn:cts:pta:pta0005.pta001">
   <cpt:structured-metadata>
      <dc:identifier>PTA:pta0005.pta001</dc:identifier>
      <dc:identifier>TLG:tlg4090.tlg096</dc:identifier>
      <dc:identifier>CPG:3243; 8596</dc:identifier>
      <dc:identifier>Pinakes-Oeuvre:1956</dc:identifier>
      <dc:identifier>BHG:</dc:identifier>
      <dc:identifier>TLG:tlg4090.tlg096</dc:identifier>
   </cpt:structured-metadata>
</ti:work>
"""


def test_read_work_ids(tmp_path: Path) -> None:
    path = tmp_path / "__cts__.xml"
    path.write_text(CTS, encoding="utf-8")
    assert read_work_ids(path) == [
        "TLG:tlg4090.tlg096", "CPG:3243", "CPG:8596", "Pinakes-Oeuvre:1956"]


def test_read_work_ids_without_catalogue(tmp_path: Path) -> None:
    assert read_work_ids(tmp_path / "__cts__.xml") == []


def _availability(licence: str) -> etree._Element:
    return etree.fromstring(
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc><publicationStmt>'
        f'<availability>{licence}</availability>'
        '</publicationStmt></fileDesc></teiHeader></TEI>')


_PROSE = "Available under a Creative Commons Attribution ShareAlike 4.0 International License"


@pytest.mark.parametrize(("target", "license"), [
    ("https://creativecommons.org/licenses/by-sa/4.0/", "cc-by-sa-4.0"),
    ("https://creativecommons.org/licenses/by/4.0/", "cc-by-4.0"),
    ("https://creativecommons.org/licenses/by-nc/4.0/", "cc-by-nc-4.0"),
    ("https://creativecommons.org/licenses/by-nc-sa/3.0/deed.de", "cc-by-nc-sa-3.0"),
    # A jurisdiction port (CC BY-NC 3.0 Germany) is a licence we can't record.
    ("https://creativecommons.org/licenses/by-nc/3.0/de/", None),
    ("", None),
])
def test_license_from_target(target: str, license: str | None) -> None:
    # The prose says ShareAlike whatever the target is; the target decides.
    root = _availability(f'<licence target="{target}">{_PROSE}</licence>')
    assert _license_from_target(root) == license


def test_license_from_prose_without_a_target() -> None:
    # PTA's prose spells ShareAlike out, never "by-sa" (#366).
    root = _availability(f"<licence>{_PROSE}</licence>")
    assert _license_from_prose(root.find(".//{*}availability")) == "cc-by-sa-4.0"
    root = _availability("<licence>Creative Commons Attribution 4.0</licence>")
    assert _license_from_prose(root.find(".//{*}availability")) == "cc-by-4.0"


APPARATUS = """<div xmlns="http://www.tei-c.org/ns/1.0" type="edition">
  <div type="textpart" n="1"><p>ὁ <persName>ἀπόστολος
     <app><lem wit="#V"/><rdg wit="#s" type="addition">паулъ</rdg></app></persName>
     διερχόμενος<!--TODO: Eus. d.e.--> κατήντησεν
     <app><lem>μέσῃ Βιδάνῃ</lem><rdg wit="#V">μέσῳ Διαβανῇ</rdg>
       <rdg wit="#M">Μεσοβηδάνῃ</rdg><witDetail wit="#M">M 203,7</witDetail></app> τῇ κώμῃ.</p></div>
</div>"""


def test_apparatus_marked_as_editorial_notes() -> None:
    # #376, #415: readings, witness details and comments become note spans (#236).

    [p] = _extract_paragraphs(etree.fromstring(APPARATUS), "pta0041.pta001", {})
    text, spans = p["text"], [tuple(s) for s in p["editorial"]]
    assert text == ("ὁ ἀπόστολος паулъ διερχόμενος TODO: Eus. d.e. κατήντησεν μέσῃ Βιδάνῃ "
                    "μέσῳ Διαβανῇ Μεσοβηδάνῃ M 203,7 τῇ κώμῃ.")
    assert [text[s:e] for s, e, _ in spans] == [
        "паулъ", "TODO: Eus. d.e.", "μέσῳ Διαβανῇ Μεσοβηδάνῃ M 203,7"]
    assert {k for _, _, k in spans} == {"note"}
    editorial.check(text, spans)
    assert editorial.strip(text, spans) == "ὁ ἀπόστολος διερχόμενος κατήντησεν μέσῃ Βιδάνῃ τῇ κώμῃ."


def _tei(xml: str) -> etree._Element:
    return etree.fromstring(f'<p xmlns="http://www.tei-c.org/ns/1.0">{xml}</p>')


def test_paragraph_without_apparatus_has_no_spans() -> None:
    text, spans = _flatten(
        _tei("ὁ <persName>Παῦλος</persName>\n   λέγει.<pb n='3'/> καὶ"))
    assert (text, spans) == ("ὁ Παῦλος λέγει. καὶ", [])


def test_inline_note_and_comment() -> None:
    # Severian, pta0001.pta005 and pta004 (#415): Montfaucon's notes and a "sic?".
    text, spans = _flatten(_tei(
        "ὁ δὲ Σωτὴρ<note type='commentary'>Reg. ὁ δὲ Χριστός.</note>\n  διὰ\n"
        " μίαν χάριν ἡ <!-- sic?--> δευτέραν."))
    assert text == "ὁ δὲ Σωτὴρ Reg. ὁ δὲ Χριστός. διὰ μίαν χάριν ἡ sic? δευτέραν."
    assert [text[s:e] for s, e, _ in spans] == ["Reg. ὁ δὲ Χριστός.", "sic?"]
    assert editorial.strip(text, [tuple(s) for s in spans]) == (
        "ὁ δὲ Σωτὴρ διὰ μίαν χάριν ἡ δευτέραν.")


def test_paragraph_that_is_only_a_note_is_wholly_editorial() -> None:
    # pta0001.pta041 §15.1: a scribe's note on where the preacher stopped.
    text, spans = _flatten(
        _tei("\n  <note type='gloss'>Ἀρχὴν γὰρ λαβόντος\n κατέπαυσεν.</note>\n"))
    assert spans == [[0, len(text), "note"]]


def test_choice_keeps_the_expansion() -> None:
    # The manuscript transcriptions write nomina sacra as <choice> (#415).
    text, spans = _flatten(_tei(
        "τοῦ <choice>\n <expan>θεοῦ</expan>\n"
        " <abbr type='nomSac'><hi rend='overline'>θυ</hi></abbr>\n"
        "</choice> λόγος, <choice><sic>ἐστιν</sic><corr>ἐστὶν</corr></choice>"))
    assert (text, spans) == ("τοῦ θεοῦ λόγος, ἐστὶν", [])


def test_deletion_inside_a_word_dropped() -> None:
    text, spans = _flatten(_tei(
        "ἐγκω<lb break='no'/>\n      μιάσαι τ<subst>\n <del rend='strikethrough'>ἀ</del>"
        "<add place='above'>ε</add></subst>λος ἡμέρᾳ<lb/> καὶ"))
    assert (text, spans) == ("ἐγκωμιάσαι τελος ἡμέρᾳ καὶ", [])


def test_deletion_of_words_marked() -> None:
    # pta0001.pta014: the editor's athetesis of whole words; a letter at a word's end.
    text, spans = _flatten(_tei(
        "ἀλλ’ ἀληθινὴ\n  <del>ἡ</del>\n μαρτυρία. λέγει·\n <del>Πνεῦμα θεοῦ,</del>\n"
        " πνεῦμα Πάσῃ<del>ν</del> ἡμέρᾳ"))
    assert text == "ἀλλ’ ἀληθινὴ ἡ μαρτυρία. λέγει· Πνεῦμα θεοῦ, πνεῦμα Πάσῃν ἡμέρᾳ"
    assert [text[s:e] for s, e, _ in spans] == ["ἡ", "Πνεῦμα θεοῦ,", "ν"]
    assert editorial.strip(text, [tuple(s) for s in spans]) == (
        "ἀλλ’ ἀληθινὴ μαρτυρία. λέγει· πνεῦμα Πάσῃ ἡμέρᾳ")


def test_convert_keeps_spans_on_their_text() -> None:
    # Yer + i becomes one letter, ꙑ: the span after it moves left.
    text = "\u2c4f\u2c3b x NOTE y"
    spans: list[list[int | str]] = [[5, 9, "note"]]
    new, new_spans = _convert(text, spans, glagolitic_to_cyrillic)
    assert new == "ꙑ x NOTE y"
    assert [new[s:e] for s, e, _ in new_spans] == ["NOTE"]


def test_empty_reading_leaves_no_space() -> None:
    # pta0003.pta017: <witStart/>/<witEnd/> readings mark a witness's extent.
    text, spans = _flatten(_tei(
        "ἀδόκιμον<app type='witnesses'><rdg wit='#C'><witEnd/></rdg></app>, δηλαδὴ<!---->."))
    assert (text, spans) == ("ἀδόκιμον, δηλαδὴ.", [])
