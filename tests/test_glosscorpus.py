"""Gloss Corpus base texts (#540): the Félire's TEI to month headings and quatrains."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica import editorial
from scripts.ingest.glosscorpus import FELIRE, GlossCorpusError, _work, parse_basetext

_RAW = Path(__file__).resolve().parents[1] / "data" / "raw" / "glosscorpus" / "felire.json"

_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

_JAN = """
<div type="section" n="jan">
  <head>January</head>
  <ab xml:id="s0101" n="0101"><term xml:id="t1" xml:lang="ga">Re sil dalach</term> doine
    <term xml:id="t2" xml:lang="ga">remai<expan>n</expan></term> <persName><term xml:id="t3">cr<expan>ist</expan></term></persName> hi kł enair<lb break="yes"/></ab>
  <ab xml:id="s0201" n="0201">Hipais florian<supplied reason="missing">i</supplied> fail coṅgili<lb break="yes"/><pb n="211v" break="yes"/></ab>
  <ab xml:id="s0301" n="0301">inmaccradai<expan>n</expan> o<gap/><lb break="yes"/></ab>
  <ab xml:id="s0401" n="0401">Ecen c<expan>h</expan>arcra<lb break="yes"/>Ecen c<expan>h</expan>arcra<lb break="yes"/></ab>
</div>
"""


def _tei(jan: str = _JAN, months: list[str] = _MONTHS) -> bytes:
    other = "".join(
        f'<div type="section" n="{m}"><head>{m.title()}</head>'
        f'<ab n="01{i:02d}">quatrain {m}</ab></div>'
        for i, m in enumerate(months, start=1) if m != "jan")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader/><text><body>'
        f"{jan}{other}</body></text></TEI>").encode("utf-8")


def test_units_headings_and_text() -> None:
    units = parse_basetext(_tei(), "Fel")
    by_ref = {u["ref"]: u for u in units}
    assert [u["ref"] for u in units[:6]] == [
        "Fel.Jan", "Fel.Jan.1", "Fel.Jan.2", "Fel.Jan.3", "Fel.Jan.4", "Fel.Feb"]
    assert len(units) == 4 + 1 + 11 * 2
    assert by_ref["Fel.Jan"] == {"ref": "Fel.Jan", "text": "January",
                                 "editorial": [[0, 7, "heading"]]}
    # Expansions keep their letters, the manuscript's word division and whitespace collapsed.
    assert by_ref["Fel.Jan.1"] == {"ref": "Fel.Jan.1",
                                   "text": "Re sil dalach doine remain crist hi kł enair"}
    assert by_ref["Fel.Dec.1"]["text"] == "quatrain dec"


def test_supplied_and_gap_are_marked() -> None:
    by_ref = {u["ref"]: u for u in parse_basetext(_tei(), "Fel")}
    jan2 = by_ref["Fel.Jan.2"]
    assert jan2["text"] == "Hipais florian⟨i⟩ fail coṅgili"  # combining dot kept as given
    assert jan2["editorial"] == [[14, 17, "supplement"]]
    assert editorial.source_text(jan2) == "Hipais floriani fail coṅgili"
    jan3 = by_ref["Fel.Jan.3"]
    assert jan3["text"] == "inmaccradain o[…]"
    assert jan3["editorial"] == [[14, 17, "lacuna"]]
    for unit in by_ref.values():
        editorial.check(unit["text"], unit.get("editorial", []), unit["ref"])


def test_line_given_twice_is_kept_once() -> None:
    by_ref = {u["ref"]: u for u in parse_basetext(_tei(), "Fel")}
    assert by_ref["Fel.Jan.4"] == {"ref": "Fel.Jan.4", "text": "Ecen charcra"}


def test_structure_errors() -> None:
    with pytest.raises(GlossCorpusError, match="month"):
        parse_basetext(_tei(months=_MONTHS[:-1]), "Fel")
    with pytest.raises(GlossCorpusError, match="follows"):
        parse_basetext(_tei(jan=_JAN.replace('n="0301"', 'n="0501"')), "Fel")
    with pytest.raises(GlossCorpusError, match="not a day"):
        parse_basetext(_tei(jan=_JAN.replace('n="0301"', 'n="0302"')), "Fel")
    with pytest.raises(GlossCorpusError, match="unexpected element <note>"):
        parse_basetext(_tei(jan=_JAN.replace("doine", "doine<note>x</note>")), "Fel")


def test_work_record() -> None:
    work = _work(FELIRE)
    assert work.work_id == "glosscorpus/felire"
    assert (work.language, work.genre, work.tradition) == ("sga", "liturgical", "latin")
    assert work.license == "cc-by-nc-sa-4.0"


def test_raw_felire() -> None:
    try:
        record = json.loads(_RAW.read_text(encoding="utf-8"))
    except (FileNotFoundError, UnicodeDecodeError, json.JSONDecodeError):
        pytest.skip("raw glosscorpus data not present")
    units = record["verses"]
    days = [u for u in units if u["ref"].count(".") == 2]
    assert len(days) == 365
    assert len(units) == 365 + 12
    assert days[0]["ref"] == "Fel.Jan.1" and days[-1]["ref"] == "Fel.Dec.31"
    for unit in units:
        editorial.check(unit["text"], unit.get("editorial", []), unit["ref"])
