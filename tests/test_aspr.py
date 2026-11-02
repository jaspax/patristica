"""Anglo-Saxon Poetic Records (#565): TEI poems to sentence-group units with ASPR line refs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica import editorial
from scripts.ingest import aspr
from scripts.ingest.aspr import (
    DEFERRED,
    DROPPED,
    POEMS,
    AsprError,
    Poem,
    check_licence,
    make_work,
    parse_poems,
)

_ROOT = Path(__file__).resolve().parents[1]
_RAW = _ROOT / "data" / "raw" / "aspr"
_CACHE = _ROOT / "data" / "raw" / "_cache" / "aspr" / "3009.xml"

_C = "<caesura/>"


def _l(text: str) -> str:
    return f"<l>{text}</l>"


_POEM = "".join([
    "<head>Test Poem</head><bibl>Krapp, 1932a 1-2.</bibl>",
    _l(f"<unclear>Hwæt</unclear> ic swefna {_C} cyst secgan wylle,"),
    _l(f"hu me gemætte {_C} to midre nihte."),            # line 2 ends a sentence
    _l(f"Þuhte me {_C} þæt ic gesawe <gap/> treow;"),
    _l(f"syllic /es {_C} <foreign xml:lang=\"rune\">C</foreign>"
       f"<foreign xml:lang=\"rune\">EA</foreign> leohte bewunden!"),
    _l(f"ond w<g ref=\"ecaudata\">ę</g>gas {_C} [XXX] wintra."),
    _l("Amen."),                                          # unnumbered, joins the last unit
])

_CUES = "".join([
    "<head>Cue Poem</head>",
    _l("[Pater noster]."),
    _l(f"þu eart ure fæder, {_C} ealles wealdend."),
    _l(f"cyninc on wuldre {_C} ond on eorðan,"),
    _l("[Qui es in celis]."),
    _l(f"ðu eart on heofonum {_C} hiht and frofor,"),
    _l("[Amen]."),
])

_SPLIT = "".join(_l(f"line {n} {_C} half{'.' if n in (2, 4) else ','}") for n in range(1, 7))


def _meter(n: int, label: str, heads: int = 1) -> str:
    head = f"<head>The Meters of Boethius: {label}</head>" * heads
    return (f'<div rend="linenumber" xml:id="A6.{n}">{head}'
            f"{_l(f'metre {n} {_C} first,')}{_l(f'metre {n} {_C} second.')}</div>")


def _tei(divs: dict[str, str], licence: str = aspr.LICENSE_URL) -> bytes:
    body = "".join(f'<div rend="linenumber" xml:id="{i}">{d}</div>' for i, d in divs.items())
    return ('<?xml version="1.0" encoding="UTF-8"?><TEI xmlns="http://www.tei-c.org/ns/1.0">'
            "<teiHeader><fileDesc><publicationStmt><availability status=\"free\">"
            f'<licence target="{licence}">CC BY-SA 3.0</licence></availability>'
            "</publicationStmt></fileDesc></teiHeader>"
            f"<text><body>{body}{_meter(0, 'Proem')}{_meter(1, 'Meter 1', heads=2)}"
            "</body></text></TEI>").encode("utf-8")


_TEST_POEMS = (
    Poem("X1", "test-poem", "Test Poem", "Test", (800, 900)),
    Poem("X2", "cue-poem", "Cue Poem", "Cue", (950, 1050)),
    Poem("X3", "split-a", "Split A", "Split", (800, 900), lines=(1, 2)),
    Poem("X3", "split-b", "Split B", "Split", (800, 900), lines=(3, 6)),
    Poem("A6", "meters", "Meters", "MBo", (880, 950)),
)


def _parse(extra: dict[str, str] | None = None, **kw: dict[str, str]) -> dict[str, list[dict]]:
    divs = {"X1": _POEM, "X2": _CUES, "X3": _SPLIT, "R1": _l(f"riddle {_C} text.")}
    divs.update(extra or {})
    out = parse_poems(_tei(divs), poems=_TEST_POEMS, dropped=kw.get("dropped", {"R": "x"}),
                      deferred=kw.get("deferred", {}))
    return {poem.slug: units for poem, units, _ in out}


def _dropped_prefix() -> dict[str, str]:
    return {"R1": "riddle"}


def test_units_are_sentence_groups_with_line_refs() -> None:
    units = _parse(dropped=_dropped_prefix())["test-poem"]
    assert [u["ref"] for u in units] == ["Test.1", "Test.3", "Test.5"]
    assert units[0]["text"] == "Hwæt ic swefna cyst secgan wylle, hu me gemætte to midre nihte."
    # A rune becomes the futhorc letter; ę comes from <g>; brackets in a line stay as text.
    assert units[1]["text"] == "Þuhte me þæt ic gesawe […] treow; syllic /es ᚳᛠ leohte bewunden!"
    # The unnumbered closing Amen joins the last unit.
    assert units[2]["text"] == "ond węgas [XXX] wintra. Amen."
    assert "editorial" not in units[2]


def test_editorial_spans() -> None:
    units = _parse(dropped=_dropped_prefix())["test-poem"]
    assert units[0]["editorial"] == [[0, 4, "supplement"]]
    t = units[1]["text"]
    marks = [(t[s:e], k) for s, e, k in units[1]["editorial"]]
    assert marks == [("[…]", "lacuna"), ("/", "lacuna")]
    # The emendation stays in the source text; lacunae don't.
    assert editorial.source_text(units[0]) == units[0]["text"]
    assert "[…]" not in editorial.source_text(units[1])
    assert "/" not in editorial.source_text(units[1])


def test_latin_cues_are_unnumbered_rubrics_that_start_units() -> None:
    units = _parse(dropped=_dropped_prefix())["cue-poem"]
    assert [u["ref"] for u in units] == ["Cue.1", "Cue.2", "Cue.3"]
    assert units[0]["text"] == "[Pater noster]. þu eart ure fæder, ealles wealdend."
    assert units[0]["editorial"] == [[0, 15, "rubric"]]
    # The cue closes the open unit; the trailing [Amen] joins the last one.
    assert units[1]["text"] == "cyninc on wuldre ond on eorðan,"
    assert units[2]["text"] == "[Qui es in celis]. ðu eart on heofonum hiht and frofor, [Amen]."
    assert [k for _, _, k in units[2]["editorial"]] == ["rubric", "rubric"]
    assert editorial.source_text(units[2]) == "ðu eart on heofonum hiht and frofor,"


def test_split_div_keeps_continuous_line_numbers() -> None:
    parsed = _parse(dropped=_dropped_prefix())
    assert [u["ref"] for u in parsed["split-a"]] == ["Split.1"]
    assert [u["ref"] for u in parsed["split-b"]] == ["Split.3", "Split.5"]
    assert parsed["split-b"][-1]["text"] == "line 5 half, line 6 half,"


def test_meters_are_sections_with_heading_units() -> None:
    units = _parse(dropped=_dropped_prefix())["meters"]
    assert [u["ref"] for u in units] == ["MBo.0", "MBo.0.1", "MBo.1", "MBo.1.1"]
    assert units[2] == {"ref": "MBo.1", "text": "Meter 1", "editorial": [[0, 7, "heading"]]}
    assert units[3]["text"] == "metre 1 first, metre 1 second."


def test_every_div_must_be_listed_once() -> None:
    with pytest.raises(AsprError, match="R1"):
        _parse(dropped={})
    with pytest.raises(AsprError, match="R1"):
        _parse(dropped={"R1": "riddle"}, deferred={"R": "x", "R1": "twice"})
    # A prefix entry (ending in ".") covers a numbered group of divs.
    assert "test-poem" in _parse({"R1.1": _l(f"a {_C} b.")}, dropped={"R1": "r", "R1.": "rs"})


def test_unexpected_markup_raises() -> None:
    with pytest.raises(AsprError, match="unexpected element <note>"):
        _parse({"X1": _l(f"a <note>n</note> {_C} b.")}, dropped=_dropped_prefix())
    with pytest.raises(AsprError, match="rune"):
        _parse({"X1": _l(f'<foreign xml:lang="rune">K</foreign> {_C} b.')},
               dropped=_dropped_prefix())


def test_licence_is_checked_from_the_header() -> None:
    check_licence(_tei({}))
    with pytest.raises(AsprError, match="not CC BY-SA"):
        check_licence(_tei({}, licence="http://creativecommons.org/licenses/by-nc-sa/3.0/"))


def test_tables() -> None:
    slugs = [p.slug for p in POEMS]
    assert len(slugs) == len(set(slugs))
    prefixes = {p.prefix for p in POEMS if p.div != "A3.1"}
    assert len(prefixes) == len(POEMS) - 3
    assert [p.lines for p in POEMS if p.div == "A3.1"] == [(1, 439), (440, 866), (867, 1664)]
    for p in POEMS:
        assert p.slug == p.slug.lower() and " " not in p.slug
        assert p.date_range[1] <= 1050
        assert not aspr._listed(p.div, DROPPED) and not aspr._listed(p.div, DEFERRED)
    work = make_work(POEMS[0], "Krapp, 1931 1-87")
    assert work.work_id == "aspr/genesis" and work.language == "ang"
    assert work.license == "cc-by-sa-3.0" and work.edition.endswith("Krapp, 1931 1-87")


def _real_file() -> bytes:
    if not _CACHE.exists() or _CACHE.read_bytes()[:40].startswith(b"version https://git-lfs"):
        pytest.skip("ASPR TEI not materialized")
    return _CACHE.read_bytes()


def test_real_file_line_counts_match_aspr() -> None:
    xml = _real_file()
    check_licence(xml)
    by_slug = {p.slug: units for p, units, _ in parse_poems(xml)}
    assert len(by_slug) == len(POEMS)
    assert by_slug["christ-ii"][0]["ref"] == "Christ.440"
    assert by_slug["christ-iii"][0]["ref"] == "Christ.867"
    # Numbered lines (those with a caesura) are ASPR's line count.
    divs = {d.get(aspr._XML_ID): d for d in aspr._divs(xml)}
    expected = {"A1.1": 2936, "A1.4": 729, "A3.1": 1664, "A3.2": 1379, "A3.5": 731,
                "A3.9": 124, "A20": 123, "A23": 58, "A26": 157}
    for div_id, count in expected.items():
        lines = aspr.read_lines(divs[div_id], div_id)
        assert max(x.num or 0 for x in lines) == count, div_id
    # Cynewulf's runic signature in Juliana: ᚳ ᚣ ᚾ, then ᛖ ᚹ ᚢ, ᛚ, ᚠ.
    juliana = " ".join(u["text"] for u in by_slug["juliana"])
    assert all(r in juliana for r in "ᚳᚣᚾᛖᚹᚢᛚᚠ")


def test_raw_output() -> None:
    if not _RAW.is_dir():
        pytest.skip("data/raw/aspr not ingested")
    path = _RAW / "dream-of-the-rood.json"
    if path.read_bytes()[:40].startswith(b"version https://git-lfs"):
        pytest.skip("data/raw/aspr is git-lfs pointers")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["work"]["language"] == "ang"
    units = raw["paragraphs"]
    assert units[0]["ref"] == "Dream.1" and units[0]["text"].startswith("Hwæt! Ic swefna cyst")
