"""OpenITI mARkdown helpers and the openiti ingestor (#480)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ingest import _openiti, openiti
from scripts.ingest._openiti import Block


def _doc(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "text"
    path.write_text(
        "﻿######OpenITI#\n\n#META# Title: كتاب\n~~ تتمة\n#META# Author: مؤلف\n\n"
        "#META#Header#End#\n\n" + body,
        encoding="utf-8",
    )
    return path


def test_read_document_header_and_continuation(tmp_path: Path) -> None:
    doc = _openiti.read_document(_doc(tmp_path, "# نص\n"))
    assert doc.meta == {"Title": "كتاب تتمة", "Author": "مؤلف"}
    assert "# نص" in doc.lines


def test_read_document_rejects_other_files(tmp_path: Path) -> None:
    path = tmp_path / "x"
    path.write_text("<html>404</html>", encoding="utf-8")
    with pytest.raises(ValueError, match="not an OpenITI"):
        _openiti.read_document(path)


def test_blocks_join_paragraphs_and_drop_milestones_and_pages() -> None:
    lines = [
        "### |PARATEXT|",
        "# ذكر أنه كان",
        "~~في زمن ms001 المأمون PageV01P002",
        "### | رسالة الهاشمي",
        "# بسم الله",
        "### || التثليث",
        "# وأقول",
    ]
    assert _openiti.blocks(lines) == [
        Block(1, "PARATEXT|"),
        Block(0, "ذكر أنه كان في زمن المأمون"),
        Block(1, "رسالة الهاشمي"),
        Block(0, "بسم الله"),
        Block(2, "التثليث"),
        Block(0, "وأقول"),
    ]


def test_pages_split_at_closing_tags() -> None:
    pages = _openiti.pages(["a", "b", "", "PageV01P001", "c", "PageV02P007", "tail"])
    assert [(p.volume, p.page, [ln for ln in p.lines if ln]) for p in pages] == [
        (1, 1, ["a", "b"]), (2, 7, ["c"]),
    ]


ARABIC = [
    "~~فى زمان اوغسطس قيصر ملك الروم ولاجل ذهاب مالهما وما نزل عليهما من البلايا رحلا",
    "~~من تلك الكورة ms036 واهتما بخلاص انفسهما وانتجعا الى بلاد اليهود وكان لارسطوبولس",
    "~~ا1",
    "~~ولد ذكر يسمى يوحنا فاما سكنوا فى اعمال فالسطين بالقرب من مدينة اورشليم وكان",
    "~~ودحض",
]
NOISE = [
    "~~47d76رr0 111017 4116- 16 0,6/ 64 6/166 116 11 61110 11161",
    "~~14115 662 122116r f 2110 1466960 11 6611r 2 461066",
    "~~10r62. 6d 1116 1216151:r 11d16111 41600 11 46160",
    "~~11 1161 1 96 41161 1126 6d 462616 0 216118 2 41d 106",
]


def test_page_body_keeps_the_arabic_and_drops_heads_margins_and_translation() -> None:
    page = ["~~11151)111 11241", "~~باوا", "~~ر", *ARABIC, "", *NOISE, "~~لا نجد هنا شيئا"]
    body = _openiti.page_body(page)
    assert body.kept == [
        "فى زمان اوغسطس قيصر ملك الروم ولاجل ذهاب مالهما وما نزل عليهما من البلايا رحلا",
        "من تلك الكورة واهتما بخلاص انفسهما وانتجعا الى بلاد اليهود وكان لارسطوبولس",
        "ولد ذكر يسمى يوحنا فاما سكنوا فى اعمال فالسطين بالقرب من مدينة اورشليم وكان",
        "ودحض",
        # a clean Arabic line after the translation: Kraken's reading order
        "لا نجد هنا شيئا",
    ]
    assert "باوا" in body.dropped and "ا1" in body.dropped


def test_page_body_stops_at_the_apparatus() -> None:
    page = [*ARABIC[:2], "~~1. Oت drrr 11eaddrd -2 ابر بانولة اير باتولوس ابر بابولة", "~~الى الا"]
    assert len(_openiti.page_body(page).kept) == 2


def test_page_body_marginal_number_glued_to_text_is_not_the_apparatus() -> None:
    page = [ARABIC[0], "~~1-911", ARABIC[1]]
    assert len(_openiti.page_body(page).kept) == 2


def test_clean_ocr_line_strips_footnote_numbers_and_debris() -> None:
    line = "الامير وجاء الى قلاية البعلرك ومعه13 سرارى فاكل11 وشرب معهن 15 ثم (1 *اته dd توخيا(1"
    assert _openiti.clean_ocr_line(line) == (
        "الامير وجاء الى قلاية البعلرك ومعه سرارى فاكل وشرب معهن ثم اته توخيا"
    )
    # real punctuation and brackets stay; letter errors are not corrected
    assert _openiti.clean_ocr_line("( والخمس مدن ) قال: ايصا") == "( والخمس مدن ) قال: ايصا"


def test_kindi_units_refs_and_editorial() -> None:
    blocks = [
        Block(1, "PARATEXT|"), Block(0, "ذكر"),
        Block(1, "رسالة الهاشمي الى الكندي"), Block(0, "بسم الله (بقرة 129) آمين"),
        Block(1, ""), Block(0, "فأجابه"), Block(0, "ثم"),
        Block(2, "التثليث"), Block(0, "وأقول"), Block(0, "ثانيا"),
        Block(2, "نبوة محمد"), Block(0, "ولقد"),
    ]
    units = openiti.kindi_units(blocks)
    assert [u["ref"] for u in units] == [
        "1.1", "2", "2.1", "3.1", "3.2", "3.3", "3.3.1", "3.3.2", "3.4", "3.4.1",
    ]
    assert units[1]["editorial"] == [[0, 24, "heading"]]
    assert units[2]["editorial"] == [[9, 19, "note"]]
    assert units[2]["text"][9:19] == "(بقرة 129)"
    assert "editorial" not in units[3]


def test_hop_units_sections_by_patriarch_and_page() -> None:
    L = openiti.Line
    lines = [
        L(1, "مقدمة الكتاب"), L(2, "تتمة المقدمة"),
        L(2, "السيرة الاولى سيرة مرقس"), L(2, "الحوارى"), L(2, "لما كان"), L(3, "فى زمان"),
        L(3, "انيانوس البطرك وهو الثانى من العدد"), L(4, "فلما توفى"),
    ]
    pats = [
        openiti.Patriarch(1, 1, "Mark", "السيرة الاولى", 0, 1),
        openiti.Patriarch(2, 1, "Anianus", "وهو الثانى من العدد", 0, 0),
    ]
    units = openiti.hop_units(lines, pats)
    assert [(u["ref"], u["text"]) for u in units] == [
        ("0.1", "مقدمة الكتاب"), ("0.2", "تتمة المقدمة"),
        ("1", "السيرة الاولى سيرة مرقس الحوارى"), ("1.1", "لما كان"), ("1.2", "فى زمان"),
        ("2", "انيانوس البطرك وهو الثانى من العدد"), ("2.1", "فلما توفى"),
    ]


def test_hop_units_refuses_an_ambiguous_marker() -> None:
    L = openiti.Line
    lines = [L(1, "وهو الثانى من العدد"), L(2, "وهو الثانى من العدد")]
    with pytest.raises(ValueError, match="found 2 times"):
        openiti.hop_units(lines, [openiti.Patriarch(2, 1, "Anianus", "وهو الثانى", 0, 0)])


def test_patriarch_table_covers_evetts_parts_1_to_4() -> None:
    pats = openiti.load_patriarchs()
    assert len(pats) == 52 and pats[-1].name == "Joseph I"
    by_part = {part: [p.number for p in pats if p.part == part] for part in openiti.HOP_PARTS}
    assert {k: (v[0], v[-1]) for k, v in by_part.items()} == {
        1: (1, 16), 2: (17, 38), 3: (39, 46), 4: (47, 52),
    }


def test_works_metadata() -> None:
    work = openiti.hop_work(3)
    assert work.work_id == "openiti/history-of-the-patriarchs-3"
    assert work.license == "cc-by-nc-sa-4.0" and work.language == "arb"
    assert work.tradition == "coptic"  # the community, not the language
    assert openiti.HOP.commit in (work.provenance_url or "")
    assert "Patrologia Orientalis 5.1" in (work.edition or "")
    kindi = openiti.kindi_work()
    assert kindi.date_range is not None and kindi.date_range[1] <= 1050
    assert kindi.tradition == "syriac"


def test_cached_source_parses() -> None:
    """The pinned History file: every marker is found once and lives are in order."""
    path = (Path("data/raw/_cache") / openiti.SOURCE_ID / openiti.HOP.repo
            / openiti.HOP.commit[:10] / openiti.HOP.uri)
    if not path.exists() or path.read_bytes()[:40].startswith(b"version https://git-lfs"):
        pytest.skip("OpenITI cache not materialized")
    pages = _openiti.pages(_openiti.read_document(path).lines)
    pats = openiti.load_patriarchs()
    for part in openiti.HOP_PARTS:
        lines = openiti.ocr_lines([p for p in pages if p.volume == part], openiti.OcrStats())
        units = openiti.hop_units(lines, [p for p in pats if p.part == part])
        assert units
