"""Ge'ez ingestor: book codes mapped to OSIS books, excluded books, edition (#188, #76, #34)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ingest import gez


def _chapter(path: Path, verses: list[tuple[int, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"verses": [{"num": n, "geez": t} for n, t in verses]}),
                    encoding="utf-8")


@pytest.fixture()
def raw(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    data = tmp_path / "_repos" / "ethiopian-bible" / "public" / "data"
    chapters = data / "chapters"
    data.mkdir(parents=True)
    (data / "books.json").write_text(json.dumps([
        {"abbrev": "Kings", "name": "Kings", "geez": "ነገሥት፡", "chapters": 1},
        {"abbrev": "ApEz", "name": "Apocalypse of Ezra", "geez": "", "chapters": 2},
        {"abbrev": "TestLd", "name": "Testament of Our Lord", "geez": "ኪዳን፡", "chapters": 1},
        {"abbrev": "Gen", "name": "Genesis", "geez": "ኦሪት", "chapters": 1},
    ]), encoding="utf-8")
    _chapter(chapters / "Kings" / "1.json", [(1, "ወእምድኅረ፡ ሞተ፡ አካአብ፡")])
    _chapter(chapters / "ApEz" / "1.json", [(1, "Chapter 1")])
    _chapter(chapters / "ApEz" / "2.json", [(1, "ወአምጽአ፡ ኢዮስያስ፡ ፋሲካ፡"), (2, "ወአቀሞሙ፡")])
    _chapter(chapters / "TestLd" / "1.json", [(1, "Chapter 1: Of the Holy Spirit")])
    _chapter(chapters / "Gen" / "1.json", [(1, "በቀዳሚ፡ ገብረ፡ እግዚአብሔር፡")])
    monkeypatch.setattr(gez, "_ensure_repo", lambda repo_dir, force: None)
    # Raw from before the fix, which the ingestor must remove.
    (tmp_path / "gez").mkdir()
    for stale in ("kings", "apez", "testld"):
        (tmp_path / "gez" / f"{stale}.json").write_text("{}", encoding="utf-8")
    return tmp_path


def test_renamed_and_excluded_books(raw: Path) -> None:
    works = {w.work_id: w for w in gez.ingest(raw, force=True)}
    assert sorted(works) == ["gez/1esd", "gez/2kgs", "gez/gen"]
    assert sorted(p.name for p in (raw / "gez").iterdir()) == ["1esd.json", "2kgs.json", "gen.json"]

    kgs = json.loads((raw / "gez" / "2kgs.json").read_text(encoding="utf-8"))
    assert kgs["work"]["title"] == "2 Kings (4 Kingdoms)"
    assert [v["ref"] for v in kgs["verses"]] == ["2Kgs.1.1"]

    # ApEz chapter 1 is a heading; chapter N is 1 Esdras N - 1.
    esd = json.loads((raw / "gez" / "1esd.json").read_text(encoding="utf-8"))
    assert esd["work"]["title"] == "1 Esdras"
    assert [v["ref"] for v in esd["verses"]] == ["1Esd.1.1", "1Esd.1.2"]
    assert not any("Chapter" in v["text"] for v in esd["verses"])


def test_edition_is_the_edition_not_the_geez_title(raw: Path) -> None:
    for work in gez.ingest(raw, force=True):
        assert work.edition == gez.EDITION
