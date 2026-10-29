"""Tests for the PTA ingestor's catalogue identifiers (#178)."""

from __future__ import annotations

from pathlib import Path

from scripts.ingest.pta import read_work_ids

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
