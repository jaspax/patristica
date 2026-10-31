"""Tests for the one-work-per-text TITUS ingest (scripts/ingest/_titus_works.py, #517)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scripts.ingest import _titus as T
from scripts.ingest import _titus_works as W

SOURCES = ["titus-shatberdi", "titus-liturgy", "titus-translations", "titus-chronicles"]


def _row(**kw: object) -> W.TextRow:
    base = dict(set="x/y.htm", select=(("Text", "A"),), slug="a", ref="Satb.A",
                units=("Chapter",), title="A", author="", genre="patristic",
                date_from=None, date_to=None, date_composed=None,
                date_confidence="uncertain", external_ids=(), edition_note="",
                rubrics=False, skip="")
    base.update(kw)
    return W.TextRow(**base)  # type: ignore[arg-type]


def _located(*items: tuple[dict[str, str], str, str]) -> list[T.Located]:
    return [T.Located(loc=loc, xloc={}, segment=T.Segment(cls=cls, text=text))
            for loc, cls, text in items]


def test_ref_part() -> None:
    assert W.ref_part("Intr.") == "Intr"
    assert W.ref_part("255_(45)") == "255"
    assert W.ref_part("A_3") == "A_3"
    assert W.ref_part(None) == "0"
    assert W.ref_part("(Zand.)") == "0"


def test_units_by_chapter_with_title_before_the_first() -> None:
    located = _located(
        ({"Text": "A"}, "mxagb22", "თქუმული"),
        ({"Text": "A", "Chapter": "1"}, "mxag16", "პირველი"),
        ({"Text": "A", "Chapter": "1"}, "mxag16", "სიტყუაჲ"),
        ({"Text": "B", "Chapter": "1"}, "mxag16", "სხუაჲ"),
        ({"Text": "A", "Chapter": "2"}, "mxagv12", "ვარიანტი"),
        ({"Text": "A", "Chapter": "2"}, "nc12", "C"),
        ({"Text": "A", "Chapter": "2"}, "mxag16", "მეორე"),
    )
    units = W.build_units(located, _row())
    assert [(u.ref, u.text) for u in units] == [
        ("Satb.A.0", "თქუმული"),
        ("Satb.A.1", "პირველი სიტყუაჲ"),
        ("Satb.A.2", "მეორე"),  # variant readings and sigla left out
    ]


def test_rubrics_only_in_liturgy_and_headings_always() -> None:
    located = _located(
        ({"Text": "A", "Chapter": "1"}, "mxagb16", "დიაკონი:"),
        ({"Text": "A", "Chapter": "1"}, "mxag16", "მშჳდობით"),
        ({"Text": "A", "Chapter": "2"}, "mxng16", "თავი"),
        ({"Text": "A", "Chapter": "2"}, "mxag16", "უფალო"),
    )
    lit = W.build_units(located, _row(rubrics=True))
    assert lit[0].text == "დიაკონი: მშჳდობით"
    assert lit[0].editorial == [[0, 8, "rubric"]]
    assert lit[1].editorial == [[0, 4, "heading"]]
    prose = W.build_units(located, _row(rubrics=False))
    assert prose[0].editorial == []
    assert prose[1].editorial == [[0, 4, "heading"]]


def test_repeated_location_gets_a_numbered_ref() -> None:
    located = _located(
        ({"Text": "A", "Chapter": "1"}, "mxag16", "ა"),
        ({"Text": "A", "Chapter": "2"}, "mxag16", "ბ"),
        ({"Text": "A", "Chapter": "1"}, "mxag16", "გ"),
    )
    assert [u.ref for u in W.build_units(located, _row())] == ["Satb.A.1", "Satb.A.2", "Satb.A.1_2"]


def test_quoted_hebrew_is_kept() -> None:
    located = _located(({"Text": "A", "Chapter": "1"}, "hborx16", "א"),
                       ({"Text": "A", "Chapter": "1"}, "mxag16", "ალეფ"))
    assert W.build_units(located, _row())[0].text == "א ალეფ"


@pytest.mark.parametrize("source_id", SOURCES)
def test_tables_are_well_formed(source_id: str) -> None:
    path = W.DATA_DIR / f"{source_id.replace('-', '_')}.csv"
    if not path.exists():
        pytest.skip(f"{path.name} not written yet")
    rows = W.read_table(source_id)
    with path.open(encoding="utf-8", newline="") as f:
        header = next(csv.reader(f))
    assert header[:16] == ["set", "select", "slug", "ref", "units", "title", "author", "genre",
                           "date_from", "date_to", "date_composed", "date_confidence",
                           "external_ids", "edition_note", "rubrics", "skip"]
    refs = set()
    for r in rows:
        assert r.set.endswith(".htm") and not T.is_restricted_url(T.BASE_URL + r.set)
        if r.skip:
            continue
        assert r.slug and r.ref and r.units and r.title, r
        assert r.genre in {"patristic", "liturgical", "apocrypha"}
        assert r.ref not in refs, r.ref
        refs.add(r.ref)
        if r.date_from is not None:
            assert r.date_to is not None and r.date_from <= r.date_to
        for x in r.external_ids:
            assert ":" in x


def test_every_source_module_has_a_label() -> None:
    from patristica.sources import SOURCE_LABELS

    for source_id in SOURCES:
        name = f"{source_id.replace('-', '_')}.py"
        module = Path(__file__).parents[1] / "scripts" / "ingest" / name
        if module.exists():
            assert source_id in SOURCE_LABELS
