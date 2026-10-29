"""Tests for the ANF works ingestor (table consistency and pure helpers)."""

from __future__ import annotations

import pytest
from lxml import etree

from scripts.ingest import anf_works as aw
from scripts.ingest._ccel_common import EXCLUDED_DIVS


def test_slugs_unique() -> None:
    slugs = [s.slug for s in aw._WORKS]
    assert len(slugs) == len(set(slugs))


def test_table_consistent_with_excluded_divs() -> None:
    """Every div the table reads is excluded from ccel-anf, and vice versa."""
    used: set[tuple[str, str]] = set()
    for spec in aw._WORKS:
        for part in spec.parts:
            assert EXCLUDED_DIVS[spec.volume].get(part.div_id) == aw.SOURCE_ID, (
                spec.slug, part.div_id,
            )
            used.add((spec.volume, part.div_id))
    registered = {
        (vol, div) for vol, divs in EXCLUDED_DIVS.items()
        for div, owner in divs.items() if owner == aw.SOURCE_ID
    }
    assert registered == used


def test_dates_and_labels() -> None:
    for spec in aw._WORKS:
        lo, hi = spec.date_range
        assert lo <= hi, spec.slug
        if spec.date_composed is not None:
            assert lo <= spec.date_composed <= hi, spec.slug
        labels = [p.label for p in spec.parts]
        assert len(spec.parts) == 1 or (all(labels) and len(set(labels)) == len(labels)), spec.slug


def test_non_text_exclusions_labelled() -> None:
    for vol in ("anf02", "anf07", "anf10"):
        assert EXCLUDED_DIVS[vol]
    assert EXCLUDED_DIVS["anf07"]["i"].startswith("non-text:")
    assert EXCLUDED_DIVS["anf07"]["xiii"].startswith("non-text:")


def _div(xml: str) -> dict[str, etree._Element]:
    return aw._index_ids(etree.fromstring(xml))


def test_extract_skips_editorial_and_separators() -> None:
    ids = _div(
        '<body><div2 id="a" title="The Work.">'
        "<p>Editor's preface</p><p>————</p>"
        '<div3 id="a.i" n="I" title="Chapter I."><p>One</p></div3>'
        '<div3 id="a.ii" n="II" title="Elucidations."><p>Editorial</p></div3>'
        "</div2></body>"
    )
    spec = aw.W("anf01", "t", "T", None, 100, (90, 110), "uncertain", "greek", "Pfx",
                aw.P("a", "the work", drop_leading=1))
    assert aw.extract_work(spec, ids) == [{"ref": "Pfx.I", "text": "One"}]


def test_extract_title_check() -> None:
    ids = _div('<body><div2 id="a" title="Something  Else"><p>x</p></div2></body>')
    ok = aw.W("anf01", "t", "T", None, 1, (1, 1), "uncertain", "greek", "X",
              aw.P("a", "something else"))
    assert aw.extract_work(ok, ids) == [{"ref": "X", "text": "x"}]
    bad = aw.W("anf01", "t", "T", None, 1, (1, 1), "uncertain", "greek", "X",
               aw.P("a", "Other"))
    with pytest.raises(RuntimeError):
        aw.extract_work(bad, ids)


def test_split_commentary() -> None:
    paras = [{"ref": str(i), "text": t} for i, t in enumerate([
        "Canon I.", "Canon text one.", "Balsamon. Comment.", "More comment.",
        "Zonaras. Other.", "Canon II.", "Canon text two.",
    ])]
    canons = [p["text"] for p in aw._split_commentary(paras, "canons")]
    comm = [p["text"] for p in aw._split_commentary(paras, "commentary")]
    assert canons == ["Canon I.", "Canon text one.", "Canon II.", "Canon text two."]
    assert comm == ["Balsamon. Comment.", "More comment.", "Zonaras. Other."]


def test_nested_work_split() -> None:
    """A nested work (#381) takes its div's paragraphs out of the outer work
    under a ref prefix of its own; the outer work keeps its other refs."""
    paras = [{"ref": r, "text": r} for r in (
        "Ep.I", "Ep.I.2", "Ep.I.3", "Ep.II", "Ep.II.1", "Ep.IX")]
    outer = aw._without("Ep.I", keep_root=True)(paras)
    assert [p["ref"] for p in outer] == ["Ep.I", "Ep.II", "Ep.II.1", "Ep.IX"]
    inner = aw._only("Ep.I", "Don", drop_root=True,
                     editorial=aw._marks({"Don.2": "heading"}))(paras)
    assert inner == [
        {"ref": "Don.2", "text": "Ep.I.2", "editorial": [[0, 6, "heading"]]},
        {"ref": "Don.3", "text": "Ep.I.3"},
    ]
    with pytest.raises(RuntimeError):
        aw._without("Ep.X")(paras)
    with pytest.raises(RuntimeError):
        aw._only("Ep.X", "Y")(paras)


def test_nested_works_share_their_outer_div() -> None:
    """Each nested row reads the same div as the row it is carved out of."""
    by_slug = {s.slug: s for s in aw._WORKS}
    for inner, outer in (("clement-fragments", "clement-stromata"),
                         ("cyprian-to-donatus", "cyprian-epistles"),
                         ("lactantius-epitome", "lactantius-divine-institutes")):
        assert by_slug[inner].parts == by_slug[outer].parts
        assert by_slug[inner].rechunk and by_slug[outer].rechunk
