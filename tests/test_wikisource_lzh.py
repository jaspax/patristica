"""Chinese Wikisource, Jingjiao texts (#650): wikitext to units, the stele's two scripts, editorial spans."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica import editorial
from scripts.ingest.wikisource_lzh import (
    PAGES,
    clean_markup,
    mark,
    paragraphs,
    parse_hymn,
    parse_stele,
    parse_xuanyuan,
    parse_xuting,
    parse_zhixuan,
    parse_zunjing,
)

_RAW = Path(__file__).resolve().parents[1] / "data" / "raw" / "wikisource-lzh"

_STELE = """{{Textquality|75%}}
{{header
|title=大秦[[景教流行中國碑]]
|section=㬌教流行中國碑頌{{*|并序}}
|noauthor=大秦寺僧[[作者:景淨|㬌淨]]述 {{Syriac|ܐܕܡ ܩܫܝܫܐ}}<!-- a comment -->
|notes=大秦㬌教流行中國碑是一座記述㬌教在唐代流傳情況的石碑。
}}
<onlyinclude>
粵若常然真寂，先先而-{无}-元；其唯我　　三一妙身无元真主阿羅訶歟！

詞曰︰

大唐{{YL|建中二年|781年}}嵗在作噩建立。{{Syriac|ܒܝܘܡ̈ܝ ܐܒܐ}}

{{Syriac|ܒܫܢܬ ܐܠܦ}}

'''左面第一行'''

大德曜輪

*

僧福壽

'''左面第二行'''

{{Syriac|ܡܢܫܥ⁎ܡܖ}} 僧仁惠

{{Syriac|}} 僧來威

後一千七十九年{{YL|咸豐己未}}[[w:杭州市|武林]]韓泰崋来觀。

'''左面第三行'''

'''左面第四行'''

'''右面第一行'''

{{Syriac|ܒܘܠ}}

'''右面第二行'''

'''右面第三行'''

'''右面第四行'''

{{YL|民國六年}}二月，[[w:李根源|根源]]受命長陝。
</onlyinclude>
{{PD-old}}
[[Category:景教]]
"""


def test_clean_markup_keeps_template_text() -> None:
    assert clean_markup("頌{{*|并序}}") == "頌并序"
    assert clean_markup("大唐{{YL|建中二年|781年}}嵗") == "大唐建中二年嵗"
    assert clean_markup("先先而-{无}-元") == "先先而无元"
    assert clean_markup("[[w:李根源|根源]]{{PD-old}}<small>王</small>") == "根源王"


def test_paragraphs_join_lines_without_space() -> None:
    assert paragraphs("  敬禮妙身、\n  證身盧訶寧俱沙\n\n  [敬禮]瑜罕難\n") == [
        "敬禮妙身、證身盧訶寧俱沙", "[敬禮]瑜罕難"]


def test_mark_lacunae_and_supplements() -> None:
    assert mark("時無上□□□河") == [[3, 6, "lacuna"]]
    assert mark("不滯……□盧訶") == [[2, 5, "lacuna"]]
    assert mark("[敬禮]瑜罕難法[王]") == [[0, 4, "supplement"], [8, 11, "supplement"]]
    assert mark("亦 作旨") == []
    assert mark("亦 作旨", gap_spaces=True) == [[1, 2, "lacuna"]]


def test_stele_chinese_and_syriac() -> None:
    chinese, syriac = parse_stele(_STELE)
    by_ref = {u["ref"]: u for u in chinese}
    assert [u["ref"] for u in chinese] == [
        "XianStele.0", "XianStele.1", "XianStele.2", "XianStele.3",
        "XianStele.Left.1", "XianStele.Left.1.1", "XianStele.Left.1.3",
        "XianStele.Left.2", "XianStele.Left.2.1", "XianStele.Left.2.2",
    ]
    assert by_ref["XianStele.0"] == {"ref": "XianStele.0", "text": "㬌教流行中國碑頌并序　大秦寺僧㬌淨述",
                                     "editorial": [[0, 18, "title"]]}
    # Honorific spaces inside the text stay; the trailing one goes.
    assert by_ref["XianStele.1"]["text"] == "粵若常然真寂，先先而无元；其唯我　　三一妙身无元真主阿羅訶歟！"
    assert by_ref["XianStele.3"]["text"] == "大唐建中二年嵗在作噩建立。"
    assert by_ref["XianStele.Left.1"]["editorial"] == [[0, 5, "heading"]]
    assert by_ref["XianStele.Left.2.1"]["text"] == "僧仁惠"
    assert not any("韓泰崋" in u["text"] or "根源" in u["text"] for u in chinese)

    assert [(u["ref"], u["text"]) for u in syriac] == [
        ("XianStele.0", "ܐܕܡ ܩܫܝܫܐ"),
        ("XianStele.3", "ܒܝܘܡ̈ܝ ܐܒܐ"),
        ("XianStele.4", "ܒܫܢܬ ܐܠܦ"),
        ("XianStele.Left.2.1", "ܡܢܫܥ⁎ܡܖ"),
        ("XianStele.Right.1.1", "ܒܘܠ"),
    ]
    assert syriac[3]["editorial"] == [[4, 5, "lacuna"]]


def test_stele_refuses_a_changed_page() -> None:
    with pytest.raises(ValueError, match="later inscriptions"):
        parse_stele(_STELE.replace("後一千七十九年", "後"))


def test_hymn_end_title() -> None:
    units = parse_hymn("无上諸天深敬歎，大地重念普安和。\n\n一切善衆至誠礼。\n\n大秦景教三威蒙度赞一卷\n\n"
                       "{{PD-old}}\n\n[[category:景教]]")
    assert [u["ref"] for u in units] == ["SanweiMengdu.1", "SanweiMengdu.2", "SanweiMengdu.3"]
    assert units[-1]["editorial"] == [[0, 11, "title"]]
    assert editorial.source_text(units[0]) == units[0]["text"]


def test_zunjing() -> None:
    units = parse_zunjing("{{cleanup}}\n尊經\n\n  敬禮妙身皇父阿羅訶、\n  證身盧訶寧俱沙，<small>已上三身同歸一體。</small>　　\n\n"
                          "  [敬禮]瑜罕難法<small>王</small>、賀薩耶法[王]。\n\n{{PD-old}}\n")
    assert [u["text"] for u in units] == [
        "尊經", "敬禮妙身皇父阿羅訶、證身盧訶寧俱沙，已上三身同歸一體。", "[敬禮]瑜罕難法王、賀薩耶法[王]。"]
    assert units[0]["editorial"] == [[0, 2, "title"]]
    assert units[2]["editorial"] == [[0, 4, "supplement"], [14, 17, "supplement"]]


def test_zhixuan_drops_header() -> None:
    units = parse_zhixuan("{{header\n| title    = 志玄安樂經\n| noauthor = 李盛铎藏\n}}\n\n"
                          "聞是至言,時無上□□□河。\n\n“岑穩僧伽！”\n")
    assert [(u["ref"], u["text"]) for u in units] == [
        ("ZhixuanAnle.1", "聞是至言,時無上□□□河。"), ("ZhixuanAnle.2", "“岑穩僧伽！”")]


def test_xuting_title_line() -> None:
    units = parse_xuting("序聽迷詩所經一卷\n　　爾時彌師訶說。亦 作旨尊旨樂。\n\n\n{{PD-old}}")
    assert units[0] == {"ref": "Xuting.0", "text": "序聽迷詩所經一卷", "editorial": [[0, 8, "title"]]}
    assert units[1]["text"] == "爾時彌師訶說。亦 作旨尊旨樂。"
    assert units[1]["editorial"] == [[8, 9, "lacuna"]]


_XUANYUAN = """{{header2
|title=大秦㬌教宣元至本經
|notes={{Wikipedia|宣元至本经}}
}}

== 敦煌文書《大秦景教宣元本經》 ==

時景通法王，在大秦國那薩羅城。

== 經幢《大秦景教宣元至本經》{{*|（唐元和九年十二月）}} ==

時景通法王，<sub>應樂咸通，</sub><small>七方</small>雲集。常存不易……

彌施訶應大慶原靈故……

== 大秦景教宣元至本經幢記 ==

夫至聖應現，利洽無方……

== 小島文書B（偽經）大秦景教宣元至本經 ==

□□□不滅除。

{{PD-old}}
"""


def test_xuanyuan_keeps_the_pillar_only() -> None:
    units = parse_xuanyuan(_XUANYUAN)
    assert [(u["ref"], u["text"]) for u in units] == [
        ("XuanyuanZhiben.1", "經幢《大秦景教宣元至本經》（唐元和九年十二月）"),
        ("XuanyuanZhiben.1.1", "時景通法王，應樂咸通，七方雲集。常存不易……"),
        ("XuanyuanZhiben.1.2", "彌施訶應大慶原靈故……"),
        ("XuanyuanZhiben.2", "大秦景教宣元至本經幢記"),
        ("XuanyuanZhiben.2.1", "夫至聖應現，利洽無方……"),
    ]
    assert units[0]["editorial"] == [[0, 23, "heading"]]
    assert units[1]["editorial"] == [[20, 22, "lacuna"]]


def test_xuanyuan_refuses_without_the_forgery_label() -> None:
    with pytest.raises(ValueError, match="unexpected sections"):
        parse_xuanyuan(_XUANYUAN.replace("（偽經）", ""))


def _raw(slug: str) -> dict:
    path = _RAW / f"{slug}.json"
    if not path.exists() or path.read_bytes().startswith(b"version https://git-lfs"):
        pytest.skip(f"{path} not materialized")
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.slug)
def test_raw_output(page) -> None:
    record = _raw(page.slug)
    assert record["work"]["language"] == page.language
    units = record["paragraphs"]
    refs = [u["ref"] for u in units]
    assert len(refs) == len(set(refs))
    for unit in units:
        for start, end, kind in unit.get("editorial", []):
            assert 0 <= start < end <= len(unit["text"]) and kind in editorial.KINDS


def test_raw_stele_counts() -> None:
    chinese = _raw("xian-stele")["paragraphs"]
    syriac = _raw("xian-stele-syriac")["paragraphs"]
    assert len(chinese) == 87 and len(syriac) == 59
    # Every Syriac unit sits at a position of the stele the Chinese numbering knows.
    assert all(u["text"] and "ܐ" <= u["text"][0] <= "ݏ" or u["text"][0] == "⁎" for u in syriac)
