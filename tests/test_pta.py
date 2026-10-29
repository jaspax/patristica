"""Tests for the PTA ingestor's catalogue identifiers (#178) and licences (#366)."""

from __future__ import annotations

from pathlib import Path

import pytest
from lxml import etree

from scripts.ingest.pta import _license_from_prose, _license_from_target, read_work_ids

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
