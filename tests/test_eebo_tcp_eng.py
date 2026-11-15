"""EEBO-TCP English translations (#354): Wither's Nemesius, TEI to units."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica import editorial
from scripts.ingest.eebo_tcp_eng import BOOKS, NEMESIUS, parse_nemesius

_RAW = Path(__file__).resolve().parents[1] / "data" / "raw" / "eebo-tcp-eng"

# A cut-down copy of the TCP markup: front matter (left out), a chapter with
# sections and arguments, a chapter without, long s, end-of-line hyphens, the
# abbreviation stroke, a page break, unreadable punctuation, an illegible
# letter and Greek the keyboarders left out.
_TEI = """<TEI xmlns="http://www.tei-c.org/ns/1.0"><teiHeader/><text>
<front><div type="preface"><head>A PREFACE</head><p>Wither's own words.</p></div></front>
<body><div type="text"><head>NEMESIVS of the Nature of MAN.</head>
<div n="1" type="chapter">
 <head>CAP. 1.</head>
 <div n="1" type="section">
  <head>SECT. 1.</head>
  <argument><p>I. The Definition of MAN: A quaere touching
the Under<g ref="char:EOLhyphen"/>ſtanding.</p></argument>
  <p><seg rend="decorInit">G</seg>Ood men have defined
<hi>Man</hi> to con<g ref="char:EOLhyphen"/>ſiſt
<pb n="2" facs="tcp:13463:24"/>of a Soul and a Body<g ref="char:punc">▪</g>
and ſo this co<g ref="char:cmbAbbrStroke">̄</g>meth.</p>
  <p><milestone type="tcpmilestone" unit="unspecified" n="II"/> Such things as the Greeks
call <gap reason="foreign"><desc>〈 in non-Latin alphabet 〉</desc></gap>, that is,
b<gap reason="illegible" extent="1 letter"><desc>•</desc></gap>dily things.</p>
 </div>
</div>
<div n="2" type="chapter">
 <head>CAP. 2.</head>
 <argument><p>Of the hollow<g ref="char:punc">▪</g>worke.</p></argument>
 <p>One paragraph.</p>
 <gap reason="duplicate" extent="1 page"><desc>〈1 page duplicate〉</desc></gap>
</div>
</div></body></text></TEI>"""


def _units(xml: str = _TEI) -> dict[str, dict]:
    return {u["ref"]: u for u in parse_nemesius(xml.encode(), chapters=2)}


def test_units_and_refs() -> None:
    units = _units()
    assert list(units) == ["Nem.1", "Nem.1.1", "Nem.1.1.1", "Nem.1.1.2", "Nem.2", "Nem.2.1"]
    for unit in units.values():
        editorial.check(unit["text"], unit.get("editorial", []), unit["ref"])
    assert "Wither's own words" not in json.dumps(list(units.values()))


def test_headings() -> None:
    units = _units()
    assert units["Nem.1"]["text"] == "CAP. 1."
    sect = units["Nem.1.1"]
    assert sect["text"] == ("SECT. 1. I. The Definition of MAN: A quaere touching the "
                            "Understanding.")
    assert sect["editorial"] == [[0, len(sect["text"]), "heading"]]
    assert units["Nem.2"]["text"] == "CAP. 2. Of the hollow worke."


def test_text_marks() -> None:
    units = _units()
    assert units["Nem.1.1.1"]["text"] == ("GOod men have defined Man to consist of a Soul and "
                                          "a Body and so this cōmeth.")
    assert "editorial" not in units["Nem.1.1.1"]
    two = units["Nem.1.1.2"]
    assert two["text"] == ("Such things as the Greeks call 〈in non-Latin alphabet〉, that is, "
                           "b•dily things.")
    assert [(two["text"][s:e], k) for s, e, k in two["editorial"]] == [
        ("〈in non-Latin alphabet〉", "lacuna"), ("•", "lacuna")]


def test_checks() -> None:
    with pytest.raises(ValueError, match="2 chapters, expected 3"):
        parse_nemesius(_TEI.encode(), chapters=3)
    with pytest.raises(ValueError, match="chapter 2 is numbered '3'"):
        _units(_TEI.replace('<div n="2" type="chapter">', '<div n="3" type="chapter">'))


def test_books() -> None:
    assert BOOKS == (NEMESIUS,)
    assert NEMESIUS.translation_of == "ogpg/vol-040/nemesius"
    assert len(NEMESIUS.commit) == 40


def test_raw_file() -> None:
    path = _RAW / f"{NEMESIUS.slug}.json"
    if not path.exists() or path.read_bytes().startswith(b"version https://git-lfs"):
        pytest.skip("raw data not present")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["work"]["translation_of"] == NEMESIUS.translation_of
    refs = [u["ref"] for u in data["paragraphs"]]
    assert len(refs) == len(set(refs)) == NEMESIUS.units
    assert [r for r in refs if r.count(".") == 1] == [f"Nem.{c}" for c in range(1, 45)]
    for unit in data["paragraphs"]:
        editorial.check(unit["text"], unit.get("editorial", []), unit["ref"])
        assert "ſ" not in unit["text"]
