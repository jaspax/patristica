"""Page layout of archive.org OCR and the evetts-hop-eng ingestor (#481)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.ingest import _ia_djvu, evetts_hop_eng
from scripts.ingest._ia_djvu import Leaf, Line

RAW = Path(__file__).resolve().parents[1] / "data" / "raw"

BODY, SPACING = 45.0, 80.0


def _line(text: str, top: int, height: float = BODY, x0: int = 100, x1: int = 2100) -> Line:
    return Line(text=text, x0=x0, x1=x1, top=top, bottom=top + int(height), height=height)


def _page(*lines: Line) -> Leaf:
    return Leaf(index=0, width=2500, height=4000, lines=list(lines))


ARABIC = [
    _line("Lau eS ke Ch ss ani dll AS LRU ae dax", 300, 70),
    _line("DM 5 2 he £a Yi GUY ke bel ce is SV", 400, 66),
]
APPARATUS = _line("1. F JLjLj 6 om. to SillL. — 2. ADF Jui E om. to — 3. E add.", 520, 38)


def test_page_layout_keeps_only_the_english_text() -> None:
    leaf = _page(
        _line("150 HISTORY OF THE PATRIARCHS. [52]", 100, 40, 300, 2000),
        *ARABIC,
        APPARATUS,
        _line("tongues of the veracious prophets, the elect apostles, and the holy fathers", 700),
        _line("and doctors of the Holy Catholic and Apostolic Church. Cyril also wrote", 780),
        _line("from his misbelief and hardness of heart and corrupt creed.", 860, x1=1600),
        _line("1. Eus., H. E., II, 24. — 2. Ibid., III, 14.", 1100, 39),
        _line("* P. 63", 760, 30, 2150, 2300),      # marginal note
    )
    layout = _ia_djvu.page_layout(leaf, BODY, SPACING)
    assert layout.head is not None and "HISTORY" in layout.head.text
    assert [ln.text[:9] for ln in layout.english] == ["tongues o", "and docto", "from his "]
    assert [ln.text[:4] for ln in layout.notes] == ["1. E"]
    assert APPARATUS in layout.dropped


def test_page_layout_keeps_the_headings_above_the_english() -> None:
    leaf = _page(
        *ARABIC,
        _line("CHAPTER XIII", 600, 45, 800, 1300),
        _line("DIOSCORUS I, THE TWENTY-FIFTH PATRIARCH. A. D. 444-458.", 700, 28, 300, 1800),
        _line("After the holy patriarch Cyril had departed to his rest, Dioscorus was", 800),
        _line("made patriarch in the see of the city of Alexandria. He endured severe", 880),
    )
    layout = _ia_djvu.page_layout(leaf, BODY, SPACING)
    assert [ln.text[:7] for ln in layout.english] == ["CHAPTER", "DIOSCOR", "After t", "made pa"]


def test_page_layout_drops_the_signature_and_debris() -> None:
    leaf = _page(
        *ARABIC,
        _line("the Lord Christ in the great city of Alexandria, and in the region of Egypt,", 700),
        _line("and in the regions of Ethiopia and Nubia, and in Pentapolis in the West,", 780),
        _line("te]", 820, 24, 300, 400),
        _line("PATR. OR. — T. I. 36", 900, 22, 300, 900),
    )
    layout = _ia_djvu.page_layout(leaf, BODY, SPACING)
    assert len(layout.english) == 2


def test_page_without_english_drops_everything() -> None:
    layout = _ia_djvu.page_layout(_page(*ARABIC, APPARATUS), BODY, SPACING)
    assert layout.english == [] and layout.notes == []


def test_clean_line_strips_marginal_marks_and_note_numbers() -> None:
    ln = _line("15 faithful, * and to foam * P. 6 at the city of Ammon1. He", 0, x0=40)
    assert evetts_hop_eng.clean_line(ln, left=100, col=2000) == \
        "faithful, and to foam at the city of Ammon. He"
    # a number in the column is text
    ln = _line("15 bishops came", 0, x0=100)
    assert evetts_hop_eng.clean_line(ln, left=100, col=2000) == "15 bishops came"


def test_join_lines_rejoins_broken_words_and_marks_headings() -> None:
    text, spans = evetts_hop_eng.join_lines([
        ("Thanks be to him for ever.", False),
        ("SECOND PREFACE", True),
        ("In the name of the Father, the con-", False),
        ("substantial; and the Cae-", False),
        ("Sarium", False),
    ])
    assert text == ("Thanks be to him for ever. SECOND PREFACE In the name of the Father, "
                    "the consubstantial; and the Cae- Sarium")
    assert spans == [[27, 41, "heading"]]
    assert text[27:41] == "SECOND PREFACE"


def test_heading_unit_marks_the_dates() -> None:
    unit = evetts_hop_eng.heading_unit(2, "CHAPTER III. ANNIANUS, THE SECOND PATRIARCH. A. D. 62-85.")
    s, e, kind = unit["editorial"][0]
    assert unit["text"][s:e] == "A. D. 62-85." and kind == "note"
    assert "editorial" not in evetts_hop_eng.heading_unit(1, "CHAPTER I. — SAINT MARK.")


def _pages() -> list[evetts_hop_eng.PageLines]:
    p1 = [
        _line("the end of the preface, and the beginning of the history of the Church", 700),
        _line("CHAPTER III", 800, 45, 800, 1300),
        _line("ANNIANUS, THE SECOND PATRIARCH. A. D. 62-83.", 880, 28, 300, 1800),
        _line("When the evangelist Mark, the apostle of the Lord Christ, died,", 960),
    ]
    p2 = [
        _line("and he ordained some of them priests and deacons, and went to his rest.", 700),
        _line("AVILIUS, THE THIRD PATRIARCH. A. D. 85-98.", 780, 28, 300, 1800),
        _line("Then the orthodox people assembled and consulted together and took a", 860),
    ]
    return [evetts_hop_eng.PageLines(i, lines, lines, 100) for i, lines in enumerate([p1, p2])]


def _patriarchs(*markers: str) -> list[evetts_hop_eng.Patriarch]:
    return [evetts_hop_eng.Patriarch(n, 1, re.compile(m), h) for n, (m, h) in enumerate(
        [(m, f"HEADING {i}") for i, m in enumerate(markers, 2)], 2)]


def test_part_units_split_lives_by_heading_and_page() -> None:
    part = evetts_hop_eng.PARTS[1]
    units = evetts_hop_eng.part_units(part, _pages(), _patriarchs("SECOND PATRIARCH",
                                                                  "THIRD PATRIARCH"), BODY)
    assert [u["ref"] for u in units] == ["0.1", "2", "2.1", "2.2", "3", "3.1"]
    assert units[0]["text"].startswith("the end of the preface")
    assert "CHAPTER" not in units[0]["text"]        # part of the curated heading
    assert units[1]["text"] == "HEADING 2"
    assert units[3]["text"].startswith("and he ordained")


def test_part_units_refuse_an_ambiguous_marker() -> None:
    with pytest.raises(ValueError, match="found 2 times"):
        evetts_hop_eng.part_units(evetts_hop_eng.PARTS[1], _pages(),
                                  _patriarchs("PATRIARCH\\. A"), BODY)


def test_patriarch_table_matches_the_arabic_sections() -> None:
    patriarchs = evetts_hop_eng.load_patriarchs()
    assert [p.number for p in patriarchs] == list(range(1, 53))
    for p in patriarchs:
        assert p.part == (1 if p.number <= 16 else 2 if p.number <= 38 else 3 if p.number <= 46 else 4)
        if p.number > 1:
            assert re.search(r"PATRIARCH\. A\. D\. \d{2,3}(-\d{2,3})?\.$", p.heading), p.heading


def test_works_translate_the_openiti_parts() -> None:
    for n, part in evetts_hop_eng.PARTS.items():
        work = evetts_hop_eng.hop_work(part)
        assert work.work_id == f"evetts-hop-eng/history-of-the-patriarchs-{n}"
        assert work.translation_of == f"openiti/history-of-the-patriarchs-{n}"
        assert work.language == "eng" and work.license == "public_domain"
        assert work.tradition == "coptic"
        assert work.date_range == evetts_hop_eng.HOP_DATES[n]


def _raw(source: str, n: int) -> list[dict] | None:
    path = RAW / source / f"history-of-the-patriarchs-{n}.json"
    if not path.exists() or path.read_bytes().startswith(b"version https://git-lfs"):
        return None
    return json.loads(path.read_text(encoding="utf-8"))["paragraphs"]


@pytest.mark.parametrize("n", [1, 2, 3, 4])
def test_raw_sections_match_the_arabic(n: int) -> None:
    eng, ara = _raw("evetts-hop-eng", n), _raw("openiti", n)
    if eng is None or ara is None:
        pytest.skip("raw History of the Patriarchs not materialized")
    headings = [u["ref"] for u in eng if "." not in u["ref"]]
    assert headings == [u["ref"] for u in ara if "." not in u["ref"]]
    assert len({u["ref"] for u in eng}) == len(eng)
