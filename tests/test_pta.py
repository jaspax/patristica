"""Tests for the PTA ingestor: catalogue identifiers (#178), English translations (#345)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ingest import pta
from scripts.ingest.pta import _parse_pta_file, read_work_ids

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


# --- English translations (#345) --------------------------------------------

def _tei(body: str, *, lang_header: str = "", licence: str = "by/4.0",
         date: str = '<date notBefore="0400" notAfter="0420"/>', extra_title: str = "") -> str:
    return f"""<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader><fileDesc>
  <titleStmt><title>De die dominica</title>{extra_title}
    <editor><persName>Jane Doe</persName><roleName>Translator</roleName></editor></titleStmt>
  <publicationStmt><availability>
    <licence target="https://creativecommons.org/licenses/{licence}/">Available under a
      Creative Commons Attribution ShareAlike 4.0 International License</licence>
  </availability><date>2023</date></publicationStmt>
  <sourceDesc><p>Born digital</p></sourceDesc></fileDesc>
  <profileDesc>{lang_header}<creation>{date}</creation></profileDesc>
</teiHeader><text><body>{body}</body></text></TEI>"""


ORIGINAL = _tei("""<div type="edition" xml:lang="grc" n="urn:cts:pta:pta0030.pta016.pta-grc2">
  <div type="textpart" subtype="section" n="1"><p>Μετὰ τὴν ἀπόλυσιν τῆς ἐκκλησίας.</p></div>
</div>""", date='<date notBefore="0030" notAfter="0800"/>')

TRANSLATION = _tei("""<div type="translation" xml:lang="eng"
     n="urn:cts:pta:pta0030.pta016.pta-eng1" corresp="urn:cts:pta:pta0030.pta016.pta-grc2">
  <head><title>Speech by the blessed bishop
     Eusebius on the day of the Lord.</title></head>
  <div type="textpart" subtype="section" n="1">
    <head>Chapter <supplied>1</supplied></head>
    <p>After the release <note type="explanation">from church</note> he sat
       down<note>Or: <note type="explanation">he</note> rested.</note>. <quote>Take,
       eat<ref cRef="NA:Mt:26:26"/>
       </quote>, he said (P: judgement) <!-- a comment --> and left.</p>
  </div>
</div>""", date='<date notBefore="0030" notAfter="1500"/>')


def _work_dir(tmp_path: Path) -> Path:
    work_dir = tmp_path / "data" / "pta0030" / "pta016"
    work_dir.mkdir(parents=True)
    (work_dir / "pta0030.pta016.pta-grc2.xml").write_text(ORIGINAL, encoding="utf-8")
    (work_dir / "pta0030.pta016.pta-eng1.xml").write_text(TRANSLATION, encoding="utf-8")
    return work_dir


def _spanned(unit: dict) -> list[tuple[str, str]]:
    return [(unit["text"][s:e], kind) for s, e, kind in unit.get("editorial", [])]


def test_translation_becomes_an_english_work(tmp_path: Path) -> None:
    work_dir = _work_dir(tmp_path)
    work, units = _parse_pta_file(work_dir / "pta0030.pta016.pta-eng1.xml", "Eusebius")
    assert work.work_id == "pta/pta0030/pta016/pta-eng1"
    assert work.language == "eng"
    assert work.translation_of == "pta/pta0030/pta016/pta-grc2"
    assert work.license == "cc-by-4.0"
    assert work.edition == (
        "pta-eng1: English translation by Jane Doe (Patristic Text Archive, 2023) "
        "of the Greek text pta-grc2")
    # Dated as its original, not by the translation's wider header range.
    assert work.date_range == (30, 800)

    title, heading, para = units
    assert title["ref"] == "pta0030.pta016"
    assert title["text"] == "Speech by the blessed bishop Eusebius on the day of the Lord."
    assert _spanned(title) == [(title["text"], "title")]
    assert (heading["ref"], heading["text"]) == ("pta0030.pta016.1", "Chapter 1")
    assert _spanned(heading) == [("Chapter 1", "heading")]
    assert para["ref"] == "pta0030.pta016.1.1"
    assert para["text"] == (
        "After the release from church he sat down [Or: he rested.]. "
        "Take, eat, he said (P: judgement) and left.")
    assert _spanned(para) == [
        ("from church", "supplement"), ("[Or: he rested.]", "note"), ("(P: judgement)", "note")]


def test_translation_licence_comes_from_the_target(tmp_path: Path) -> None:
    work_dir = _work_dir(tmp_path)
    path = work_dir / "pta0030.pta016.pta-eng1.xml"
    path.write_text(TRANSLATION.replace("licenses/by/4.0", "licenses/by-sa/4.0"), encoding="utf-8")
    work, _ = _parse_pta_file(path, None)
    assert work.license == "cc-by-sa-4.0"


def test_translation_of_a_version_outside_the_corpus_is_skipped(tmp_path: Path) -> None:
    work_dir = _work_dir(tmp_path)
    (work_dir / "pta0030.pta016.pta-grc2.xml").write_text(
        ORIGINAL.replace('notBefore="0030" notAfter="0800"', 'notBefore="1140" notAfter="1199"'),
        encoding="utf-8")
    assert _parse_pta_file(work_dir / "pta0030.pta016.pta-eng1.xml", None) is None


def test_translation_via_an_intermediary_uses_the_fallback(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work_dir = _work_dir(tmp_path)
    (work_dir / "pta0030.pta016.pta-chu1.xml").write_text(
        ORIGINAL.replace('xml:lang="grc"', 'xml:lang="chu"'), encoding="utf-8")
    (work_dir / "pta0030.pta016.pta-eng1.xml").write_text(
        TRANSLATION.replace('corresp="urn:cts:pta:pta0030.pta016.pta-grc2"',
                            'corresp="urn:cts:pta:pta0030.pta016.pta-chu1"'), encoding="utf-8")
    assert _parse_pta_file(work_dir / "pta0030.pta016.pta-eng1.xml", None) is None

    monkeypatch.setitem(pta._ORIGINAL_FALLBACK, "pta0030.pta016.pta-eng1", "pta-grc2")
    work, _ = _parse_pta_file(work_dir / "pta0030.pta016.pta-eng1.xml", None)
    assert work.translation_of == "pta/pta0030/pta016/pta-grc2"
    assert work.edition.endswith(
        "of the Greek text pta-grc2, made from the Church Slavonic version pta-chu1")


def test_translation_into_another_language_is_skipped(tmp_path: Path) -> None:
    work_dir = _work_dir(tmp_path)
    path = work_dir / "pta0030.pta016.pta-eng1.xml"
    path.write_text(TRANSLATION.replace('type="translation" xml:lang="eng"',
                                        'type="translation" xml:lang="lat"'), encoding="utf-8")
    assert _parse_pta_file(path, None) is None
