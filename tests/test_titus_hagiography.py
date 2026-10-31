# ruff: noqa: E501
"""Tests for the TITUS Old Georgian hagiography ingestor (#516). No network."""

from __future__ import annotations

from patristica.authors import resolve_author
from patristica.period import work_in_period
from scripts.ingest import _titus as T
from scripts.ingest import titus_hagiography as H


def _page(body: str) -> str:
    return f"<HTML><BODY>{body}<HR><BR>This text is part of the TITUS edition.</BODY></HTML>"


def _marker(level: int, label: str, value: str, indent: int = 3, extra: bool = False) -> str:
    x = "X" if extra else ""
    return (f'<span id=h{level}><!{x}Level {level}>{label}: {value}<A NAME="a">&nbsp;</A></sPAN>'
            + "&nbsp;" * indent + "</span>")


PAGE = _page(
    _marker(2, "Text", "Mart._Sus.")
    + '<span id=mxagb12>თთუესა ოკდონბერსა: </span><span id=mxagbx12>ი^ზ</span><span id=mxagb12>:</span><span id=n16>\n<BR>'
    + _marker(5, "Line of ed.", "2")
    + '<span id=mxag22>წამებაჲ წმიდისა </span><span id=mxagp22>შუშანიკისი</span><span id=n16>\n<BR>'
    + _marker(5, "Line of ed.", "3", indent=6)
    + '<span id=mxag16>და აწ გითხრა თქუენ</span><span id=n16>\n<BR>'
    + _marker(3, "Chapter", "I")
    + _marker(5, "Line of ed.", "5", indent=6)
    + '<span id=mxag16>1. იყო მერვესა წელსა [</span><span id=mxagp16>მრ...</span><span id=mxag16>] სპარსთა</span><span id=n16>\n<BR>'
    + _marker(5, "Line of ed.", "6")
    + '<span id=mxag16>მეფისასა ცეცხლსა </span><span id=nc16>'
    + _marker(6, "Ms. page", "A_353v", indent=0, extra=True)
    + '<span id=mxag16>, რამეთუ</span><span id=n16>\n<BR>'
    + _marker(5, "Line of ed.", "7", indent=6)
    + '<span id=mxag16>ხოლო ამის</span><span id=mxagv12>ვარიანტი</span><span id=n16>\n<BR>'
    + _marker(2, "Text", "Mart._Eust.")
    + _marker(3, "Chapter", "XIV")
    + _marker(5, "Line of ed.", "1", indent=6)
    + '<span id=mxag16>მოვიდა კაცი</span><span id=n16>\n<BR>'
)


def test_split_texts_paragraphs_refs_and_spans() -> None:
    texts = list(H.split_texts([("u", PAGE)], {"Mart._Sus.": "Shush", "Mart._Eust.": "Eust"},
                               numbered=False))
    assert [t.name for t in texts] == ["Mart._Sus.", "Mart._Eust."]
    units = texts[0].units
    assert [u["ref"] for u in units] == ["Shush.0.1", "Shush.0.2", "Shush.1.1", "Shush.1.2"]
    # the feast date (a rubric) and the title, one unit, wholly editorial
    assert units[0]["text"] == "თთუესა ოკდონბერსა: იზ: წამებაჲ წმიდისა შუშანიკისი"
    assert units[0]["editorial"] == [[0, 22, "rubric"], [23, len(units[0]["text"]), "title"]]
    assert "editorial" not in units[1]
    # the editors' number is a heading, the restoration a supplement; no space
    # before the comma a manuscript-page marker left
    assert units[2]["text"] == "1. იყო მერვესა წელსა [მრ...] სპარსთა მეფისასა ცეცხლსა, რამეთუ"
    assert units[2]["editorial"] == [[0, 2, "heading"], [21, 28, "supplement"]]
    # variant readings are left out
    assert units[3]["text"] == "ხოლო ამის"
    assert [u["ref"] for u in texts[1].units] == ["Eust.14.1"]


def test_numbered_sets_use_the_paragraph_numbers() -> None:
    page = _page(
        _marker(2, "Text", "Io.Zed.")
        + _marker(3, "Chapter", "S") + _marker(4, "Paragraph", "01")
        + '<span id=mxagb16>ცხორებაჲ</span><span id=mxagb16> </span><span id=mxagq16>იოვანესი</span><span id=n16>\n<BR>'
        + _marker(3, "Chapter", "1.") + _marker(4, "Paragraph", "39-a")
        + _marker(8, "Line of edition", "1", extra=True)
        + '<span id=mxag16>ესე ნეტარი</span><span id=n16>\n<BR>'
        + _marker(8, "Line of edition", "2", extra=True)
        + '<span id=mxag16>მამაჲ</span><span id=n16>\n<BR>'
    )
    (text,) = H.split_texts([("u", page)], {"Io.Zed.": "AsIoZedA"}, numbered=True)
    assert [(u["ref"], u["text"], u.get("editorial")) for u in text.units] == [
        ("AsIoZedA.01", "ცხორებაჲ იოვანესი", [[0, 17, "rubric"]]),
        ("AsIoZedA.39-a", "ესე ნეტარი მამაჲ", None),
    ]


def test_chapter_key() -> None:
    assert [H.chapter_key(v) for v in ("I", "IV", "XIX", "XL", "12", "07", "1.", "Test.")] == [
        "1", "4", "19", "40", "12", "7", "1", "Test"]


def test_segment_kinds() -> None:
    kinds = {cls: H.segment_kind(T.Segment(cls, "ა")) for cls in (
        "mxag16", "mxagp16", "mxag22", "mxagb16", "mxagt16", "mxag12", "mxng12")}
    assert kinds == {"mxag16": None, "mxagp16": None, "mxag22": "title", "mxagb16": "rubric",
                     "mxagt16": "heading", "mxag12": "note", "mxng12": "note"}


def test_index_is_consistent() -> None:
    rows = H.load_index()
    assert {r.set for r in rows} == set(H.SETS)
    for r in rows:
        assert (r.set, r.text) not in H.SKIPPED
        if r.author:
            assert resolve_author(r.author), r.author
        assert work_in_period(date_range=r.date_range), r.local_id


def test_names_take_the_kind_of_the_title_around_them() -> None:
    pieces = [("ცხორებაჲ მამისა ", "rubric"), (" ", H._NAME), ("იოვანე", H._NAME),
              (" ", H._NAME), ("ზედაძნელისა", H._NAME), (" და მოწაფეთა", "rubric"),
              (" ", None), ("იოვანე", H._NAME), (" იყო", None)]
    assert [k for t, k in H.resolve_names(pieces) if t.strip()] == [
        "rubric", "rubric", "rubric", "rubric", None, None]
    assert H.resolve_names([("ცხორებაჲ", "rubric"), ("იოვანესი", H._NAME)])[1][1] == "rubric"
