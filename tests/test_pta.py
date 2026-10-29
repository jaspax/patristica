"""Tests for the PTA ingestor's catalogue identifiers (#178) and licences (#366)."""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from scripts.ingest.pta import (
    _extract_paragraphs,
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


def test_apparatus_runs_into_the_text_by_default() -> None:
    # The old flattening, kept for every edition but those in _MARK_APPARATUS (#415).
    [p] = _extract_paragraphs(etree.fromstring(APPARATUS), "pta0041.pta001", {})
    assert p == {"ref": "pta0041.pta001.1",
                 "text": "ὁ ἀπόστολος паулъ διερχόμενοςTODO: Eus. d.e. κατήντησεν μέσῃ Βιδάνῃ"
                         "μέσῳ Διαβανῇ ΜεσοβηδάνῃM 203,7 τῇ κώμῃ."}


def test_apparatus_marked_as_editorial_notes() -> None:
    # #376: readings, witness details and comments become note spans (#236).
    from patristica import editorial

    [p] = _extract_paragraphs(etree.fromstring(APPARATUS), "pta0041.pta001", {},
                              mark_apparatus=True)
    text, spans = p["text"], [tuple(s) for s in p["editorial"]]
    assert text == ("ὁ ἀπόστολος паулъ διερχόμενος TODO: Eus. d.e. κατήντησεν μέσῃ Βιδάνῃ "
                    "μέσῳ Διαβανῇ Μεσοβηδάνῃ M 203,7 τῇ κώμῃ.")
    assert [text[s:e] for s, e, _ in spans] == [
        "паулъ", "TODO: Eus. d.e.", "μέσῳ Διαβανῇ Μεσοβηδάνῃ M 203,7"]
    assert {k for _, _, k in spans} == {"note"}
    editorial.check(text, spans)
    assert editorial.strip(text, spans) == "ὁ ἀπόστολος διερχόμενος κατήντησεν μέσῃ Βιδάνῃ τῇ κώμῃ."
