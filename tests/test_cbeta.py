# ruff: noqa: E501  (the TEI fixture keeps CBETA's long lines)
"""Tests for the CBETA Taishō ingestor (#651)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from lxml import etree

from patristica.models import Work
from scripts.ingest import cbeta
from scripts.ingest.cbeta import Part, Text, char_table, is_verse, part_units, units

_RAW = Path(__file__).resolve().parents[1] / "data" / "raw" / "cbeta"

FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<TEI xmlns="http://www.tei-c.org/ns/1.0" xmlns:cb="http://www.cbeta.org/ns/1.0" xml:id="T99n0001">
<teiHeader><encodingDesc><charDecl>
  <char xml:id="CB00001"><charProp><localName>composition</localName><value>[口*笑]</value></charProp>
    <mapping type="unicode">U+35DB</mapping><mapping type="PUA">U+F02FC</mapping></char>
  <char xml:id="CB00002"><charProp><localName>composition</localName><value>[這-言+(衣-〦)]</value></charProp>
    <charProp><localName>normalized form</localName><value>延</value></charProp>
    <mapping type="normal_unicode">U+2E785</mapping></char>
  <char xml:id="CB00003"><charProp><localName>composition</localName><value>[A]</value></charProp>
    <charProp><localName>normalized form</localName><value>灟</value></charProp></char>
  <char xml:id="CB07751"><charProp><localName>composition</localName><value>[涺-十+(土/此/土)]</value></charProp>
    <mapping type="PUA">U+F1E47</mapping></char>
  <char xml:id="CB09999"><charProp><localName>composition</localName><value>[X]</value></charProp></char>
</charDecl></encodingDesc></teiHeader>
<text><body>
<milestone n="1" unit="juan"/>
<pb n="0001a" ed="T"/>
<lb n="0001a01" ed="T"/><cb:docNumber>No. 1</cb:docNumber><cb:div type="other">
<lb n="0001a02" ed="T"/><cb:juan n="001" fun="open"><cb:mulu n="1" type="卷"></cb:mulu><cb:jhead><anchor xml:id="a1"/>讚<note place="inline">并序</note></cb:jhead></cb:juan>
<lb n="0001a03" ed="T"/><lg type="regular"><l>無上諸天<caesura/>大地重念</l>
<lb n="0001a04" ed="T"/><l>其座<g ref="#CB00001">x</g>高<caesura/>助諸<g ref="#CB00002">y</g></l></lg>
<lb n="0001a05" ed="T"/><cb:juan n="001" fun="close"><cb:jhead>讚一卷</cb:jhead></cb:juan></cb:div>
<lb n="0001a06" ed="T"/><cb:div type="w"><cb:mulu level="1" type="附文">尊經</cb:mulu><head>尊經</head>
<lb n="0001a07" ed="T"/><p>敬禮妙身　應身
<pb n="0001b" ed="T"/>
<lb n="0001b01" ed="T"/>　證身<g ref="#CB00003">z</g>火<anchor xml:id="beg1"/><app><lem wit="#wit.cbeta">浣<note type="cf1">T32</note></lem><rdg wit="#wit.orig">綄</rdg></app>布</p>
<lb n="0001b02" ed="T"/><p>僧元□　僧□□<note n="1" type="orig">【原】apparatus</note></p>
<lb n="0001b03" ed="T"/><p>銀神像并<g ref="#CB07751">q</g>神像</p>
<lb n="0001b04" ed="T"/><p>後一千七十九年</p></cb:div>
</body></text></TEI>
"""

HYMN = Part(slug="hymn", title="讚", author="Anonymous", date_range=(700, 845),
            date_confidence="uncertain", genre="liturgical", note="a manuscript", divs=(0, 1))
REST = Part(slug="rest", title="尊經", author="Anonymous", date_range=(800, 1000),
            date_confidence="uncertain", genre="liturgical", note="a manuscript", divs=(1, None),
            drop={"0001b04": "a later colophon"})


@pytest.fixture()
def root() -> etree._Element:
    return etree.fromstring(FIXTURE.encode("utf-8"))


def test_char_table_prefers_unicode_then_normal_unicode_then_normalized_form(root) -> None:
    chars = char_table(root)
    assert chars["CB00001"] == ("㗛", "[口*笑]")
    assert chars["CB00002"][0] == "\U0002e785"
    assert chars["CB00003"][0] == "灟"
    assert chars["CB07751"] == (None, "[涺-十+(土/此/土)]")


def test_hymn_lines_refs_and_titles(root) -> None:
    hymn = part_units(units(root, "T1"), HYMN, "0001")
    assert [u["ref"] for u in hymn] == ["T0001.p0001a02", "T0001.p0001a03", "T0001.p0001a04",
                                        "T0001.p0001a05"]
    assert hymn[0] == {"ref": "T0001.p0001a02", "text": "讚并序", "editorial": [[0, 3, "title"]]}
    assert hymn[1]["text"] == "無上諸天　大地重念"
    assert hymn[2]["text"] == "其座㗛高　助諸\U0002e785"
    assert hymn[3]["editorial"] == [[0, 3, "title"]]
    assert is_verse(units(root, "T1"), HYMN)


def test_prose_joins_lines_drops_apparatus_and_marks(root, caplog) -> None:
    with caplog.at_level(logging.WARNING):
        rest = part_units(units(root, "T1"), REST, "0001")
    assert not is_verse(units(root, "T1"), REST)
    by_ref = {u["ref"]: u for u in rest}
    assert list(by_ref) == ["T0001.p0001a06", "T0001.p0001a07", "T0001.p0001b02",
                            "T0001.p0001b03"]  # the dropped colophon is left out
    assert by_ref["T0001.p0001a06"]["editorial"] == [[0, 2, "title"]]
    # lines joined without spaces, ideographic spaces kept, <lem> kept and <rdg> dropped
    assert by_ref["T0001.p0001a07"]["text"] == "敬禮妙身　應身　證身灟火浣布"
    # □ is a lacuna; the apparatus note is gone
    assert by_ref["T0001.p0001b02"] == {"ref": "T0001.p0001b02", "text": "僧元□　僧□□",
                                        "editorial": [[2, 3, "lacuna"], [5, 7, "lacuna"]]}
    # a reviewed character with no Unicode form: its composition, marked note, a warning
    unit = by_ref["T0001.p0001b03"]
    assert unit["text"] == "銀神像并[涺-十+(土/此/土)]神像"
    assert unit["editorial"] == [[4, 17, "note"]]
    assert any("CB07751" in r.message and r.levelno == logging.WARNING for r in caplog.records)
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)


def test_unreviewed_unencoded_character_is_an_error(root, caplog) -> None:
    g = root.find(".//{http://www.tei-c.org/ns/1.0}g[@ref='#CB07751']")
    g.set("ref", "#CB09999")
    with caplog.at_level(logging.ERROR):
        units(root, "T1")
    assert any("CB09999" in r.message and r.levelno == logging.ERROR for r in caplog.records)


def test_undeclared_character_raises(root) -> None:
    g = root.find(".//{http://www.tei-c.org/ns/1.0}g[@ref='#CB07751']")
    g.set("ref", "#CB12345")
    with pytest.raises(ValueError, match="CB12345"):
        units(root, "T1")


def test_unknown_element_raises(root) -> None:
    p = root.find(".//{http://www.tei-c.org/ns/1.0}p")
    etree.SubElement(p, "{http://www.tei-c.org/ns/1.0}foreign").text = "x"
    with pytest.raises(ValueError, match="foreign"):
        units(root, "T1")


def test_a_dropped_line_must_exist(root) -> None:
    part = Part(**{**REST.__dict__, "drop": {"0009z99": "nothing there"}})
    with pytest.raises(ValueError, match="0009z99"):
        part_units(units(root, "T1"), part, "0001")


def test_parse_writes_works(tmp_path: Path) -> None:
    path = tmp_path / "T99n0001.xml"
    path.write_text(FIXTURE, encoding="utf-8")
    text = Text(no="0001", vol="99", pages="1a–b", parts=(HYMN, REST))
    out = cbeta.parse(path, text)
    assert [(w.work_id, key) for w, key, _ in out] == [("cbeta/hymn", "verses"),
                                                       ("cbeta/rest", "paragraphs")]
    work = out[0][0]
    assert work.language == "lzh" and work.tradition == "syriac"
    assert work.license == "cc-by-nc-sa-4.0"
    assert work.external_ids == ["Taisho:T0001"]
    assert "CBETA" in (work.edition or "") and "Taishō" in (work.edition or "")


def test_table_is_consistent() -> None:
    slugs = [p.slug for t in cbeta.TEXTS for p in t.parts]
    assert len(slugs) == len(set(slugs))
    assert {t.no for t in cbeta.TEXTS} == {"2142", "2143", "2144"}  # T2141A/B are Manichaean
    for text in cbeta.TEXTS:
        starts = [p.divs[0] for p in text.parts]
        assert starts[0] == 0 and starts == sorted(starts)


def _raw(slug: str) -> dict:
    path = _RAW / f"{slug}.json"
    if not path.exists() or path.read_bytes().startswith(b"version https://git-lfs"):
        pytest.skip(f"{path} not materialized")
    return json.loads(path.read_text(encoding="utf-8"))


def test_raw_jingjiao_texts() -> None:
    hymn = _raw("t2143-sanwei-mengdu-zan")
    assert len(hymn["verses"]) == 24  # title, 22 couplets, colophon
    assert hymn["verses"][1]["text"] == "無上諸天深敬歎　大地重念普安和"
    zunjing = _raw("t2143-zunjing")
    assert zunjing["paragraphs"][0]["text"] == "尊經"
    assert zunjing["paragraphs"][-1]["text"].startswith("謹案諸經目錄")
    stele = _raw("t2144-jingjiao-stele")
    Work(**stele["work"])
    assert stele["work"]["author"] == "景淨"
    texts = [u["text"] for u in stele["paragraphs"]]
    assert texts[0] == "大秦景教流行中國碑頌并序"
    assert not any("咸豐" in t for t in texts)  # the 1859 colophon is left out
    assert "火浣布" in texts[2]
