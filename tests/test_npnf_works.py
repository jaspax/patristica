"""Tests for the NPNF works ingestor and the CCEL carving tables."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica.period import COMPOSED_BY
from scripts.ingest import anf_works, npnf_works
from scripts.ingest._ccel_common import EXCLUDED_DIVS, parse_thml_volume
from scripts.ingest._ccel_works import _series


def test_slugs_unique() -> None:
    slugs = [s.slug for s in npnf_works._WORKS]
    assert len(slugs) == len(set(slugs))


def test_table_consistent_with_excluded_divs() -> None:
    used: set[tuple[str, str]] = set()
    for spec in npnf_works._WORKS:
        for part in spec.parts:
            assert EXCLUDED_DIVS[spec.volume].get(part.div_id) == npnf_works.SOURCE_ID, (
                spec.slug, part.div_id,
            )
            used.add((spec.volume, part.div_id))
    registered = {
        (vol, div) for vol, divs in EXCLUDED_DIVS.items()
        for div, owner in divs.items() if owner == npnf_works.SOURCE_ID
    }
    assert registered == used


def test_rows_well_formed() -> None:
    for spec in npnf_works._WORKS:
        lo, hi = spec.date_range
        assert lo <= hi <= COMPOSED_BY, spec.slug
        if spec.date_composed is not None:
            assert lo <= spec.date_composed <= hi, spec.slug
        assert spec.author is None or spec.author.strip(), spec.slug
        labels = [p.label for p in spec.parts]
        assert len(spec.parts) == 1 or (all(labels) and len(set(labels)) == len(labels)), spec.slug


def test_council_divs_untouched() -> None:
    """npnf214 council divs stay owned by ecumenical."""
    for div in ("vii", "ix", "x", "xi", "xii", "xiii", "xiv", "xvi", "viii.iii", "xv.iii"):
        assert EXCLUDED_DIVS["npnf214"][div] == "ecumenical"


def test_series_labels() -> None:
    assert _series("anf05")[1] == "ANF Vol. 5"
    assert _series("npnf103")[1] == "NPNF Series 1 Vol. 3"
    assert _series("npnf214")[1] == "NPNF Series 2 Vol. 14"


_RAW = Path("data/raw")
_VOLUMES = (
    [("ccel-anf", f"anf{i:02d}") for i in range(1, 11)]
    + [("ccel-npnf1", f"npnf1{i:02d}") for i in range(1, 15)]
    + [("ccel-npnf2", f"npnf2{i:02d}") for i in range(1, 15)]
)


@pytest.mark.parametrize("series,volume", _VOLUMES)
def test_generic_blobs_fully_carved(series: str, volume: str) -> None:
    """With the carving tables and non-text exclusions, the generic per-div1
    ingestors leave nothing behind (every Work has its own title/author)."""
    xml = _RAW / series / f"{volume}.xml"
    if not xml.exists():
        pytest.skip("CCEL XML not cached")
    assert parse_thml_volume(xml, series, volume, volume) == []


def test_anf_table_still_registered() -> None:
    assert anf_works.SOURCE_ID == "anf-works"


_MANIFEST = Path(__file__).resolve().parents[1] / "data" / "normalized" / "_works.jsonl"


def _manifest_languages() -> dict[str, str]:
    """work_id → language for every Work in the tracked manifest."""
    out: dict[str, str] = {}
    for line in _MANIFEST.read_text(encoding="utf-8").splitlines():
        work = json.loads(line)["work"]
        out[work["work_id"]] = work["language"]
    return out


@pytest.mark.parametrize("module", [anf_works, npnf_works])
def test_translation_of_targets_exist(module) -> None:
    """Every translation_of resolves to an original-language Work in the corpus.

    OGPG targets must be split works (``ogpg/vol-NNN/{slug}``), never a
    volume's ``other`` remainder of unindexed text.
    """
    languages = _manifest_languages()
    linked = [s for s in module._WORKS if s.translation_of]
    assert linked
    for spec in linked:
        target = spec.translation_of
        assert target in languages, (spec.slug, target)
        assert languages[target] != "eng", (spec.slug, target)
        if target.startswith("ogpg/"):
            assert len(target.split("/")) == 3, (spec.slug, target)
            assert not target.endswith("/other"), (spec.slug, target)
    slugs = {s.slug for s in module._WORKS}
    assert set(module._UNLINKED) <= slugs
    assert not set(module._UNLINKED) & set(module._ORIGINALS)
