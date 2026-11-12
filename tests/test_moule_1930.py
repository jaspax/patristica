"""The moule-1930 ingestor: Moule's English Jingjiao texts (#654)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.ingest import moule_1930
from scripts.ingest._ia_djvu import Leaf, Line

RAW = Path(__file__).resolve().parents[1] / "data" / "raw" / moule_1930.SOURCE_ID


def _line(text: str, top: int, height: float = 55.0, x0: int = 100) -> Line:
    return Line(text=text, x0=x0, x1=2100, top=top, bottom=top + int(height), height=height)


def test_body_lines_drop_the_running_head_and_the_footnotes() -> None:
    leaf = Leaf(index=0, width=2400, height=4100, lines=[
        _line("THE T’ANG DYNASTY 45", 180),
        _line("fifty days. He bade the hungry come and fed them; he", 320),
        _line("saving without bound.", 406),
        # set close to the next line but in the body type: kept
        _line("The sun rose, darkness was destroyed; all bore witness to", 443),
        _line("the true mysterious principle.", 530),
        # a note's first line read in a taller type, set close to the next
        _line("with kung-tien, ‘‘ palace’’, suggested by Tomaschek does not seem", 700, 53),
        _line("‘Satisfactory, and the explanation remains uncertain. The Sanskrit", 761, 44),
        _line("forms of other place-names noted in these vocabularies bear no", 822, 45),
        _line("resemblance to the Chinese.", 883, 44),
    ])
    assert [ln.text for ln in moule_1930.body_lines(leaf)] == [
        "fifty days. He bade the hungry come and fed them; he",
        "saving without bound.",
        "The sun rose, darkness was destroyed; all bore witness to",
        "the true mysterious principle.",
    ]


def test_join_mends_broken_words_but_keeps_hyphens_of_names() -> None:
    assert moule_1930._join("celebrate distin-", "guished services.") == \
        "celebrate distinguished services."
    assert moule_1930._join("Duke Fang Hsiian-", "ling, to take") == \
        "Duke Fang Hsiian-ling, to take"
    assert moule_1930._join("our", "T’ang.") == "our T’ang."


def test_list_lines_continue_a_name_only_when_the_layout_says_so() -> None:
    assert moule_1930._continues("Gigot priest and archdeacon of Khumdan and teacher",
                                 "monk Hsiian-lan", indented=False)
    assert moule_1930._continues("shiangtsua © monk", "Ching-t’ung", indented=True)
    assert moule_1930._continues("head of the church of", "Khumdan and of Sarag", indented=False)
    assert not moule_1930._continues("Moses priest and monk", "Simeon priest", indented=False)


def test_corrections_must_match_their_count(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(moule_1930.CORRECTIONS, "zunjing", (("Iidden", "hidden"),))
    assert moule_1930.apply_corrections("zunjing", ["to Iidden peace ;"]) == ["to hidden peace;"]
    with pytest.raises(ValueError, match="must match 1"):
        moule_1930.apply_corrections("zunjing", ["no such text"])
    with pytest.raises(ValueError, match="must match 1"):
        moule_1930.apply_corrections("zunjing", ["Iidden", "Iidden"])


def test_letters_restore_the_romanizations(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(moule_1930.CORRECTIONS, "zunjing", ())
    assert moule_1930.apply_corrections("zunjing", ["Chéng-kuan, Hsiian"]) == \
        ["Chêng-kuan, Hsüan"]


def _raw(slug: str) -> dict:
    path = RAW / f"{slug}.json"
    if not path.exists() or path.read_bytes().startswith(b"version https://git-lfs"):
        pytest.skip("raw moule-1930 not materialized")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("slug,count", [("xian-stele", 118), ("sanwei-mengdu-zan", 13),
                                        ("zunjing", 6)])
def test_raw_works(slug: str, count: int) -> None:
    record = _raw(slug)
    units = record["paragraphs"]
    assert len(units) == count
    assert record["work"]["translation_of"].startswith("wikisource-lzh/")
    for unit in units:
        # no OCR debris: footnote marks, margin marks, unmapped é / ii
        # (the only numbers Moule prints in these texts are listed here)
        text = re.sub(r"^\d\. |\(635\)|A\.D\. 781|530 works", "", unit["text"])
        assert not re.search(r"[®™©“”*%#|\\/_\d]|é|ii", text), unit
        for start, end, kind in unit.get("editorial", []):
            assert kind == "heading" and 0 <= start < end <= len(unit["text"])


def test_raw_hymn_is_titled_stanzas() -> None:
    units = _raw("sanwei-mengdu-zan")["paragraphs"]
    assert units[0]["text"].startswith("1. A Hymn") and units[0]["editorial"] == [[0, 2, "heading"]]
    assert units[1]["text"].startswith("[If] the highest heavens")
    assert units[-2]["text"].endswith("beyond thought or dispute.")
    assert units[-1]["text"].startswith("A Hymn of the Brilliant Teaching of Ta-ch’in")
