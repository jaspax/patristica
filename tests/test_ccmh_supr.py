"""Codex Suprasliensis from CCMH, split at TOROT's text divisions (#333)."""

import json
from pathlib import Path

import pytest

from patristica.editorial import source_text
from scripts.ingest import ccmh_supr
from scripts.ingest.ccmh_supr import (
    LACUNA,
    Division,
    Word,
    build_units,
    ccmh_to_cyrillic,
    find_starts,
    load_texts,
    page_ref,
    parse_ccmh,
)

RAW = Path(__file__).parent.parent / "data" / "raw" / "ccmh-supr"


def test_letters_and_marks():
    # 1001101: the first line of the codex (TOROT: мыи͑хъ бо о͑тъ бога ѥ͑свѣ.)
    assert ccmh_to_cyrillic("my(ix& bo (ot& boga (jesv@ .") == "мыи҅хъ бо о҅тъ бога ѥ҅свѣ ."
    assert ccmh_to_cyrillic("duSi pogyb@l)$") == "доуши погыбѣль҆"
    assert ccmh_to_cyrillic("^umol^ena") == "оу̑мол҄ена"  # kamora on a vowel, palatal arc on л
    assert ccmh_to_cyrillic("vy^jO svo^jO") == "выѭ̑ своѭ̑"
    assert ccmh_to_cyrillic("(ag'g^e") == "а҅гꙿг҄е"  # paerok
    assert ccmh_to_cyrillic('"I') == "ї"


def test_titlo_and_superscripts():
    assert ccmh_to_cyrillic("!g$ !\"Is !xs (i !b&") == "г҃ь ї҃с х҃с и҅ б҃ъ"
    assert ccmh_to_cyrillic("!bg&") == "бг҃ъ"
    assert ccmh_to_cyrillic("*!styi") == "Ст҃ыи"
    assert ccmh_to_cyrillic("ami!n") == "амиⷩ"  # a letter above the line
    assert ccmh_to_cyrillic("!p!a!C!e") == "паче"  # a word written above the line


def test_stops():
    assert ccmh_to_cyrillic("(amin& . : .") == "а҅минъ ⁘"


def test_page_refs_use_the_continuous_foliation():
    assert page_ref("1001101") == "Supr.1r"
    assert page_ref("1118230") == "Supr.118v"
    assert page_ref("2001101") == "Supr.119r"
    assert page_ref("3002205") == "Supr.136v"


def test_parse_joins_hyphens_stops_and_notes(tmp_path):
    src = tmp_path / "s.txt"
    src.write_text(
        "1090101 a raz&-\n"
        "1090102 b@ . v&z)$-\t\tjako (edn@mi\n"
        "1090103 r@v&Se Ze\t\tusty r@SE :\n"
        "1090104 (amin . : . 33 33\n",
        encoding="utf-8",
    )
    words = parse_ccmh(src)
    assert [w.cyrillic for w in words] == [
        "а", "разъбѣ.", "възь҆рѣвъше", "ꙗко е҅днѣми оусты рѣшѧ :", "же", "а҅мин⁘"]
    assert [w.line for w in words][:3] == ["1090101", "1090101", "1090102"]
    assert words[3].note and words[3].line == "1090102"


def test_units_mark_lacunae_and_notes():
    words = [Word("1078229", "a", "а"), Word("1078230", "b", "бо."),
             Word("1078230", "n", "note", note=True)]
    units = build_units(words, lacuna_before=True, lacuna_after=True)
    assert units == [{
        "ref": "Supr.78v",
        "text": f"{LACUNA} а бо. note {LACUNA}",
        "editorial": [[0, 3, "lacuna"], [10, 14, "note"], [15, 18, "lacuna"]],
    }]
    assert source_text(units[0]).split() == ["а", "бо."]


def test_lost_leaf_inside_a_text():
    words = [Word("1018230", "a", "а"), Word("1019101", "b", "б")]
    units = build_units(words, lacuna_before=False, lacuna_after=False)
    assert [u["ref"] for u in units] == ["Supr.18v", "Supr.19r"]
    assert units[0]["text"] == f"а {LACUNA}"


def test_find_starts_skips_an_editors_title():
    words = [Word("1000101", w, w) for w in
             "конецъ прѣжде а҅минъ похвала о҅ м҃ мѫченицѣхъ о мѫченичи памѧти како сытость бѫдетъ любѧштиїмъ мѫченикы".split()]
    div = Division("1", "", None, ccmh_supr._fold_words(
        "похвала на мченици в севастиѣ похвала о м мѫченицѣхъ о мѫченичи памѧти како сытость бѫдетъ любѧштиїмъ мѫченикы"))
    assert find_starts(words, [div]) == [3]


def test_index():
    texts = load_texts()
    assert len(texts) == 48
    assert len({t.slug for t in texts}) == 48
    assert [d for t in texts for d in t.divs].count("7163") == 1  # Pionius's second half


@pytest.mark.skipif(not (RAW / "vita-cononis.json").exists()
                    or (RAW / "vita-cononis.json").read_bytes().startswith(b"version https://git-lfs"),
                    reason="raw data not present")
def test_raw_konon():
    raw = json.loads((RAW / "vita-cononis.json").read_text(encoding="utf-8"))
    assert raw["work"]["license"] == "cc-by-4.0"
    assert raw["paragraphs"][0]["ref"] == "Supr.12r"
    assert raw["paragraphs"][0]["text"].startswith("мѣсѧца марта вь ѕ҃ дьнь҆ чоудотворениꙗ")
    # two leaves are lost after fol. 18v
    lost = [p["ref"] for p in raw["paragraphs"] if "editorial" in p]
    assert lost == ["Supr.18v"]
