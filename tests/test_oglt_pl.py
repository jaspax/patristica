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
    assert len(index) >= 1450
    for stem, entry in index.items():
        assert entry.author and entry.title
        assert entry.title != stem
        assert "\n" not in entry.author and "\t" not in entry.author
        if entry.basis == "editorial":
            # Editorial apparatus is also dated after the schism.
            assert entry.date_range is not None and entry.date_range[0] > 1054
            assert entry.excluded


def test_kept_works_have_unique_author_title_pairs() -> None:
    pairs = [
        (e.author, e.title.lower()) for e in oglt_pl._load_pl_index().values() if not e.excluded
    ]
    assert len(pairs) == len(set(pairs))


def test_divina_bibliotheca_keeps_only_prefaces() -> None:
    index = oglt_pl._load_pl_index()
    pl28_29 = {s: e for s, e in index.items() if s.startswith(("PL28_", "PL29_"))}
    kept = [e for e in pl28_29.values() if not e.excluded]
    assert kept and all(
        e.title.startswith(("Praefatio", "Prologus", "Abbreviatio")) for e in kept
    )
    assert sum(e.basis == "scripture" for e in pl28_29.values()) >= 40


def test_apply_index_resolves_author_and_title() -> None:
    applied = oglt_pl._apply_pl_index(_work("PL23_13_UNKNOWN"), "PL23_13_UNKNOWN", [])
    assert applied is not None
    work = applied[0]
    assert work.author == "Hieronymus"
    assert work.title == "Liber de perpetua virginitate B. Mariae"
    assert work.work_id == "oglt_pl/hieronymus/pl23_13_unknown"
    assert work.date_range == (370, 420)
    assert work.date_composed == 395
    assert work.date_confidence == "approximate"


def test_apply_index_without_dates_is_uncertain() -> None:
    applied = oglt_pl._apply_pl_index(_work("PL23_42_DEDEOETNOMINIBUS"), "PL23_42_DEDEOETNOMINIBUS", [])
    assert applied is not None
    work = applied[0]
    assert work.author == "Pseudo-Hieronymus"
    assert work.date_range is None and work.date_composed is None
    assert work.date_confidence == "uncertain"


@pytest.mark.parametrize(
    "stem",
    ["PL10_20_NI", "PL31_1_UNK", "PL80_79_CH", "PL30_4_APP", "PL27_1_", "PL64_23_GI", "PL28_1_", "PL16_26_IN"],
)
def test_apply_index_drops_excluded(stem: str) -> None:
    assert oglt_pl._apply_pl_index(_work(stem), stem, []) is None


def test_apply_index_corrects_volume_level_header() -> None:
    work = _work("PL59_6_aA").model_copy(update={"author": "Gelasius I", "title": "Epistolae Et Decreta"})
    applied = oglt_pl._apply_pl_index(work, "PL59_6_aA", [])
    assert applied is not None
    assert applied[0].author == "Avitus Viennensis"
    assert applied[0].work_id == "oglt_pl/avitus-viennensis/pl59_6_aa"


def test_apply_index_leaves_unindexed_work_alone() -> None:
    work = _work("PL999_0_X")
    paras = [{"ref": "a", "text": "x"}]
    assert oglt_pl._apply_pl_index(work, "PL999_0_X", paras) == (work, paras)


def test_filter_paragraphs_prefix_and_range_are_idempotent() -> None:
    paras = [{"ref": r, "text": r} for r in ["P.1", "P.1.1", "P.10", "P.2", "P.3", "P.4"]]
    once = oglt_pl._filter_paragraphs(paras, ("P.1", "P.3..P.4"), "X")
    assert [p["ref"] for p in once] == ["P.1", "P.1.1", "P.3", "P.4"]
    assert oglt_pl._filter_paragraphs(once, ("P.1", "P.3..P.4"), "X") == once
    with pytest.raises(ValueError, match="matches no paragraph"):
        oglt_pl._filter_paragraphs(paras, ("Q",), "X")


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
