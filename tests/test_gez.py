"""Ge'ez ingestor: OSIS book codes, excluded books, edition, text cleanup (#188, #76, #34, #65)."""

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
        {"abbrev": "Ezra", "name": "Ezra", "geez": "ዕዝራ፡", "chapters": 13},
    ]), encoding="utf-8")
    for ch in range(1, 14):
        _chapter(chapters / "Ezra" / f"{ch}.json", [(1, f"ቃል፡ {ch}")])
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
    assert sorted(works) == ["gez/1esd", "gez/2kgs", "gez/4esr", "gez/ezra", "gez/gen"]
    assert sorted(p.name for p in (raw / "gez").iterdir()) == [
        "1esd.json", "2kgs.json", "4esr.json", "ezra.json", "gen.json"]

    kgs = json.loads((raw / "gez" / "2kgs.json").read_text(encoding="utf-8"))
    assert kgs["work"]["title"] == "2 Kings (4 Kingdoms)"
    assert [v["ref"] for v in kgs["verses"]] == ["2Kgs.1.1"]

    # ApEz chapter 1 is a heading; chapter N is 1 Esdras N - 1.
    esd = json.loads((raw / "gez" / "1esd.json").read_text(encoding="utf-8"))
    assert esd["work"]["title"] == "1 Esdras"
    assert [v["ref"] for v in esd["verses"]] == ["1Esd.1.1", "1Esd.1.2"]
    assert not any("Chapter" in v["text"] for v in esd["verses"])


def test_ezra_chapters_11_to_13_are_4_ezra_12_to_14(raw: Path) -> None:
    works = {w.work_id: w for w in gez.ingest(raw, force=True)}
    ezra = json.loads((raw / "gez" / "ezra.json").read_text(encoding="utf-8"))
    assert [v["ref"] for v in ezra["verses"]] == [f"Ezra.{ch}.1" for ch in range(1, 11)]
    esr = json.loads((raw / "gez" / "4esr.json").read_text(encoding="utf-8"))
    assert [v["ref"] for v in esr["verses"]] == ["4Esr.12.1", "4Esr.13.1", "4Esr.14.1"]
    assert [v["text"] for v in esr["verses"]] == ["ቃል፡ 11", "ቃል፡ 12", "ቃል፡ 13"]
    assert works["gez/4esr"].genre == "scripture"
    assert works["gez/4esr"].date_range == (90, 120)
    # A plain re-run skips both works and returns both.
    assert sorted(w.work_id for w in gez.ingest(raw)) == sorted(works)


def test_edition_is_the_edition_not_the_geez_title(raw: Path) -> None:
    for work in gez.ingest(raw, force=True):
        assert work.edition == gez.EDITION


def test_clean_text_whitespace_and_separator_spacing() -> None:
    assert gez.clean_text("ወአይድዖሙ ፡ እመቦ ፡ ብእሲ ፡\n                ") == "ወአይድዖሙ፡ እመቦ፡ ብእሲ፡"
    assert gez.clean_text("ምላክከ\n                  ።]") == "ምላክከ።]"
    assert gez.clean_text("አዕይንቲከ ፤ ወ   ቃል፡ ቃል።") == "አዕይንቲከ፤ ወ ቃል፡ ቃል።"
    # Editorial brackets stay (#236).
    assert gez.clean_text("አምላክነ ፡ [ወንሰምዕ ፡ ወንገብር ።]") == "አምላክነ፡ [ወንሰምዕ፡ ወንገብር።]"


def test_split_word_moves_to_next_verse() -> None:
    verses = [{"num": 2, "geez": "ወቦ፡ ነቢያትኒ።"}, {"num": 3, "geez": "አንስተ፡ ወ"},
              {"num": 4, "geez": "ተባዕተ፡ ወቦ፡ እምኔሆሙ።"}]
    gez._rejoin_split_words("1Meq", 28, verses)
    assert [v["geez"] for v in verses] == ["ወቦ፡ ነቢያትኒ።", "አንስተ፡", "ወተባዕተ፡ ወቦ፡ እምኔሆሙ።"]
    # Other chapters are untouched.
    other = [{"num": 3, "geez": "አንስተ፡ ወ"}, {"num": 4, "geez": "ተባዕተ፡"}]
    gez._rejoin_split_words("1Meq", 27, other)
    assert other[0]["geez"] == "አንስተ፡ ወ"


def test_split_word_that_no_longer_matches_raises() -> None:
    with pytest.raises(ValueError, match="_SPLIT_WORDS"):
        gez._rejoin_split_words("1Meq", 28, [{"num": 3, "geez": "አንስተ፡"}, {"num": 4, "geez": "ተ"}])
