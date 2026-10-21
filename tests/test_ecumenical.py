"""Tests for the NPNF2 vol. 14 councils ingestor's work records (#11)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from scripts.ingest import ecumenical

_PARAS = [{"ref": "CarthageCyp.1", "text": "Cyprian said: Ye have heard."}]


def _info() -> ecumenical._SynodInfo:
    return ecumenical._SARDICA["xv.vi"]


def test_translation_of_set_from_table() -> None:
    assert ecumenical._make_work(_info()).translation_of == (
        "oglt-pl/concilia-carthaginiensia/pl3_24_ann")
    assert ecumenical._make_work(ecumenical._PROVINCIAL["viii.iii"]).translation_of is None


def test_write_work_keeps_unchanged_file(tmp_path: Path) -> None:
    ecumenical._write_work(tmp_path, _info(), _PARAS, force=False)
    path = tmp_path / "carthage-cyprian.json"
    path.write_text(path.read_text(encoding="utf-8").replace("Ye have", "You have"),
                    encoding="utf-8")
    ecumenical._write_work(tmp_path, _info(), _PARAS, force=False)
    assert "You have" in path.read_text(encoding="utf-8")


def test_write_work_rewrites_changed_metadata(tmp_path: Path) -> None:
    """A new translation_of reaches an existing raw file without --force."""
    ecumenical._write_work(tmp_path, replace(_info(), translation_of=None), _PARAS, force=False)
    work = ecumenical._write_work(tmp_path, _info(), _PARAS, force=False)
    saved = json.loads((tmp_path / "carthage-cyprian.json").read_text(encoding="utf-8"))
    assert work is not None and work.translation_of == _info().translation_of
    assert saved["work"]["translation_of"] == _info().translation_of
