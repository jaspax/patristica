"""Tests for the OGLT Patrologia Latina attribution index."""

from __future__ import annotations

from pathlib import Path

import pytest

from patristica.models import Work
from scripts.ingest import oglt_pl


def _work(stem: str) -> Work:
    return Work(
        work_id=f"oglt_pl/unknown/{stem.lower()}",
        source_id=oglt_pl.SOURCE_ID,
        author=None,
        title=stem,
        genre="patristic",
        language="lat",
        tradition="latin",
        license="cc-by-sa-4.0",
    )


def test_index_rows_are_complete() -> None:
    index = oglt_pl._load_pl_index()
    assert len(index) >= 500
    for stem, entry in index.items():
        assert stem.startswith("PL")
        assert entry.author and entry.title
        assert entry.title != stem
        if entry.basis == "editorial":
            # Editorial apparatus must always fall to the post-schism filter.
            assert entry.date_range is not None and entry.date_range[0] > 1054


def test_apply_index_resolves_author_and_title() -> None:
    work = oglt_pl._apply_pl_index(_work("PL23_13_UNKNOWN"), "PL23_13_UNKNOWN")
    assert work is not None
    assert work.author == "Hieronymus"
    assert work.title == "Liber de perpetua virginitate B. Mariae"
    assert work.work_id == "oglt_pl/hieronymus/pl23_13_unknown"
    assert work.date_range == (370, 420)
    assert work.date_composed == 395
    assert work.date_confidence == "approximate"


def test_apply_index_without_dates_is_uncertain() -> None:
    work = oglt_pl._apply_pl_index(_work("PL23_42_DEDEOETNOMINIBUS"), "PL23_42_DEDEOETNOMINIBUS")
    assert work is not None
    assert work.author == "Pseudo-Hieronymus"
    assert work.date_range is None and work.date_composed is None
    assert work.date_confidence == "uncertain"


@pytest.mark.parametrize("stem", ["PL10_20_NI", "PL31_1_UNK", "PL80_79_CH"])
def test_apply_index_drops_post_schism(stem: str) -> None:
    assert oglt_pl._apply_pl_index(_work(stem), stem) is None


def test_apply_index_leaves_unindexed_work_alone() -> None:
    work = _work("PL16_0_SAN")
    assert oglt_pl._apply_pl_index(work, "PL16_0_SAN") is work


def test_loader_rejects_incomplete_rows(tmp_path: Path) -> None:
    bad = tmp_path / "index.csv"
    bad.write_text(
        "# comment\n"
        "stem,author,title,date_start,date_end,basis,cts_urn,note\n"
        "PL1_0_X,,Some title,300,400,curated,,\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="lacks author or title"):
        oglt_pl._load_pl_index.__wrapped__(bad)


def test_loader_rejects_half_open_dates(tmp_path: Path) -> None:
    bad = tmp_path / "index.csv"
    bad.write_text(
        "stem,author,title,date_start,date_end,basis,cts_urn,note\n"
        "PL1_0_X,Anonymus,Some title,300,,curated,,\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="both or neither"):
        oglt_pl._load_pl_index.__wrapped__(bad)
