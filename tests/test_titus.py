# ruff: noqa: E501
"""Tests for the shared TITUS helpers (scripts/ingest/_titus.py, #514/#515). No network."""

from __future__ import annotations

import gzip
from pathlib import Path

import pytest

from scripts.ingest import _common
from scripts.ingest import _titus as T

PAGE = """<HTML><HEAD><TITLE>TITUS Texts: Tetraevangelium</TITLE></HEAD>
<BODY onload="JavaScript:frcheck()" background="/pergtxt.jpg">
<BR><DIV Align=CENTER><span id=n16>
<BR></span><span id=titus><a id=titus href="javascript:ci(895,'armazi')">ARMAZI</a></span><span id=n16>
<BR><span id=h1><!Level 1>Text collection: NT<A NAME="NT">&nbsp;</A></sPAN>
<BR></span><span id=title><a id=title href="javascript:ci(895,'novum')">Novum</a> <a id=title href="javascript:ci(895,'t')">Testamentum</a></span><span id=n16>
<BR></span><span id=bibliogr><a id=bibliogr href="x">Šaniʒe</a>, <a id=bibliogr href="x">Psalmunis</a>,
<BR>Tbilisi 1960</span><span id=n16>
<BR><a id=n16 href="x">TITUS</a> <a id=n16 href="x">version</a> <a id=n16 href="x">by</a> <a id=n16 href="x">Jost</a> <a id=n16 href="x">Gippert</a>,
<BR>Frankfurt a/M, 1.6.2000 / 20.3.2007
<BR></span><span id=nc12><a id=nc12 href="x">C</a>&nbsp;&nbsp;&nbsp;</span><span id=mxng12><a id=mxng12 href="x">ადიშის</a> (</span><span id=n16>
<BR><span id=h2><!Level 2>Book: Mt.<A NAME="NT_Mt.">&nbsp;</A></sPAN>
<BR></span><span id=mxag22><a id=mxag22 href="x">სახარებაჲ</a> <a id=mxag22 href="x">მა[თჱსი]</a></span><span id=n16>
<BR><span id=h3><!Level 3>Chapter: 1<A NAME="NT_Mt._1">&nbsp;</A></sPAN>
<BR></DIV>
<BR><span id=h4><!Level 4>Verse: 1<A NAME="NT_Mt._1_1">&nbsp;</A></sPAN> <a href="/database/titusinx/locate.asp?lxtext=ntkpl" target="hadd"><IMG SRC="/paraa.jpg" alt="Link to ntkpl"></a>&nbsp;&nbsp;&nbsp;</span><span id=mxagx16>[წ]იგნი შობისა იესუ ქრისტჱსი*, ძისა დავითისი.</span><span id=n16>
<BR><span id=h4><!Level 4>Verse: 1V<A NAME="NT_Mt._1_1V">&nbsp;</A></sPAN>&nbsp;</span><span id=mxagv12><a id=mxagv12 href="x">ქ̃სი</a> </span><span id=nc12><a id=nc12 href="x">C</a>; </span><span id=n16>
<BR><span id=h4><!Level 4>Verse: 2<A NAME="NT_Mt._1_2">&nbsp;</A></sPAN>&nbsp;</span><span id=mxagx16>აბრაჰამ შვა</span><span id=n16>
<BR><span id=h5><!XLevel 5>Ms. page: 2r<A NAME="x">&nbsp;</A></sPAN></span><span id=mxagx16> ისაკი ...</span><span id=n16>
<BR><DIV Align=CENTER>
<DIV ALIGN=RIGHT><A HREF="/texte/etca/cauc/ageo/nt/adisnt/adisn002.htm"><img src="/arribar.gif" alt="Next part"></A></DIV><BR>
<HR><BR>This text is part of the TITUS edition.
<BR>Copyright <A HREF="javascript:mm('TITUS')">TITUS Project</A>,
Frankfurt a/M, 16.2.2022.
 No parts of this document may be republished in any form
without prior permission by the copyright holder.</DIV></BODY></HTML>
"""

FRAME = """<frameset cols="*, 20%"><frameset rows="80%,*" noframes>
<frame src="adisn001.htm"
name="etatext"
scrolling="auto"></frameset></frameset>"""


def test_parse_page_markers_and_segments() -> None:
    events = T.parse_page(PAGE)
    markers = [e for e in events if isinstance(e, T.Marker)]
    assert [(m.level, m.label, m.value, m.extra) for m in markers] == [
        (1, "Text collection", "NT", False),
        (2, "Book", "Mt.", False),
        (3, "Chapter", "1", False),
        (4, "Verse", "1", False),
        (4, "Verse", "1V", False),
        (4, "Verse", "2", False),
        (5, "Ms. page", "2r", True),
    ]
    segs = [e for e in events if isinstance(e, T.Segment)]
    # header spans and the footer are not segments; concordance links are unwrapped
    assert all(s.cls not in T.HEADER_CLASSES for s in segs)
    assert not any("Copyright" in s.text for s in segs)
    title = next(s for s in segs if s.cls == "mxag22")
    assert title.text.strip() == "სახარებაჲ მა[თჱსი]"
    seg = next(s for s in segs if s.cls == "mxagv12")
    assert seg.script == "mx" and seg.lang == "ag" and seg.flags == "v" and seg.size == 12
    assert seg.is_variant and not T.is_main_text(seg)
    assert not T.Segment("mxng12", "ადიშის").is_old_georgian
    assert T.Segment("nc12", "C").script == ""


def test_collect_units_by_verse() -> None:
    located = list(T.locate(T.parse_page(PAGE)))
    units = T.collect_units(located, ("Book", "Chapter", "Verse"))
    by_key = {u.key: u for u in units}
    # the book title has no chapter/verse; the variant line is left out
    assert ("Mt.", None, None) in by_key
    assert ("Mt.", "1", "1V") not in by_key
    v1 = by_key[("Mt.", "1", "1")]
    assert v1.text == "[წ]იგნი შობისა იესუ ქრისტჱსი, ძისა დავითისი."
    assert v1.editorial == [[0, 3, "supplement"]]
    v2 = by_key[("Mt.", "1", "2")]
    # a manuscript page break inside a verse doesn't split it
    assert v2.text == "აბრაჰამ შვა ისაკი ..."
    assert v2.editorial == [[18, 21, "lacuna"]]
    assert v2.raw("Matt.1.2") == {
        "ref": "Matt.1.2", "text": v2.text, "editorial": [[18, 21, "lacuna"]],
    }
    assert by_key[("Mt.", "1", "1")].raw("x") == {
        "ref": "x", "text": v1.text, "editorial": [[0, 3, "supplement"]],
    }


def test_locate_clears_deeper_levels() -> None:
    events = [
        T.Marker(2, "Book", "Mt."), T.Marker(3, "Chapter", "1"), T.Marker(4, "Verse", "5"),
        T.Marker(3, "Chapter", "2"), T.Segment("mxag16", "ა"),
    ]
    (loc,) = list(T.locate(events))
    assert dict(loc.loc) == {"Book": "Mt.", "Chapter": "2"}


@pytest.mark.parametrize(("raw", "text", "spans"), [
    ("[წ]იგნი", "[წ]იგნი", [[0, 3, "supplement"]]),
    ("ვ(იდრ)ემდის", "ვ(იდრ)ემდის", [[1, 6, "supplement"]]),
    ("<...> იოტა", "<...> იოტა", [[0, 5, "lacuna"]]),
    ("მამისა [!] ჩუენისა", "მამისა [!] ჩუენისა", [[7, 10, "note"]]),
    ("ლოც{ვ}აჲ", "ლოც{ვ}აჲ", [[3, 6, "note"]]),
    ("მრ...", "მრ...", [[2, 5, "lacuna"]]),
    ("სასწა/ოჳლი  მც\\ველნი*", "სასწაოჳლი მცველნი", []),
    ("[ნე<ლ>ბ]ა", "[ნე<ლ>ბ]ა", [[0, 8, "supplement"]]),
    ("ნისა] და", "ნისა] და", [[0, 5, "supplement"]]),   # opened before the unit
    ("და [ნისა", "და [ნისა", [[3, 8, "supplement"]]),   # closed after it
    ("  plain   text ", "plain text", []),
])
def test_clean_text(raw: str, text: str, spans: list[list[int | str]]) -> None:
    assert T.clean_text(raw) == (text, spans)


def test_parse_header_and_edition_line() -> None:
    h = T.parse_header(PAGE)
    assert h.title == "Novum Testamentum"
    assert h.printed_edition == "Šaniʒe, Psalmunis, Tbilisi 1960"
    assert h.version_by == ["Jost Gippert"]
    assert h.last_changed == "2022-02-16"
    assert not h.restricted
    assert T.edition_line(h.printed_edition, editors=h.version_by, last_changed=h.last_changed) == (
        "TITUS (ed. Jost Gippert), after Šaniʒe, Psalmunis, Tbilisi 1960; last changed 2022-02-16"
    )
    assert T.edition_line("") == "TITUS (ed. Jost Gippert)"
    assert T.parse_header("… (TITUS Members only) …").restricted


def test_licence_is_unpublishable_until_permission() -> None:
    from scripts.translate import EXCLUDED_LICENSES  # noqa: PLC0415
    assert T.TITUS_LICENSE in EXCLUDED_LICENSES


def test_page_navigation() -> None:
    base = "https://titus.uni-frankfurt.de/texte/etca/cauc/ageo/nt/adisnt/"
    assert T.first_page_url(base + "adisn.htm", FRAME) == base + "adisn001.htm"
    assert T.next_page_url(base + "adisn001.htm", PAGE) == base + "adisn002.htm"
    assert T.next_page_url(base + "adisn002.htm", "<HTML>no next</HTML>") is None


def test_restricted_urls() -> None:
    assert T.is_restricted_url(
        "http://titus.fkidg1.uni-frankfurt.de/texte/etcc/cauc/ageo/xanmeti/vienna/vienn.htm")
    assert T.is_restricted_url("https://titus.uni-frankfurt.de/texte/etcc/x/y.htm")
    assert not T.is_restricted_url("https://titus.uni-frankfurt.de/texte/etcs/cauc/ageo/at/psa/psa.htm")
    with pytest.raises(T.TitusRestricted):
        T.fetch("https://titus.uni-frankfurt.de/texte/etcc/x/y.htm", Path("/nonexistent"))


def test_fetch_uses_gzip_cache_offline(tmp_path: Path) -> None:
    base = "https://titus.uni-frankfurt.de/texte/etca/cauc/ageo/nt/adisnt/"
    for name, body in (("adisn.htm", FRAME), ("adisn001.htm", PAGE.replace("adisn002", "adisn001x"))):
        dest = T.cache_path(base + name, tmp_path)
        assert dest == tmp_path / "_cache/titus/etca/cauc/ageo/nt/adisnt" / (name + ".gz")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(gzip.compress(body.encode()))
    (T.cache_path(base + "adisn001x.htm", tmp_path)).write_bytes(gzip.compress(b"<HTML>last</HTML>"))
    with _common.offline_mode():
        pages = list(T.iter_pages(base + "adisn.htm", tmp_path, force=True))
        assert [u.rsplit("/", 1)[1] for u, _ in pages] == ["adisn001.htm", "adisn001x.htm"]
        with pytest.raises(_common.OfflineError):
            T.fetch(base + "adisn003.htm", tmp_path)


def test_marker_indent_marks_paragraph_starts() -> None:
    page = (
        '<BODY><span id=h5><!Level 5>Line of ed.: 14<A NAME="a">&nbsp;</A></sPAN>&nbsp;&nbsp;&nbsp;</span>'
        '<span id=mxag16>ქრისტჱსსა.</span><span id=n16>\n<BR>'
        '<span id=h5><!Level 5>Line of ed.: 15<A NAME="b">&nbsp;</A><A NAME="c">&nbsp;</A></sPAN>'
        '&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;</span><span id=mxag16>ხოლო</span><span id=n16>\n<BR>'
        '<span id=h4><!Level 4>Page of ed.: 12<A NAME="d">&nbsp;</A></sPAN>  '
        '<span id=h5><!Level 5>Line of ed.: 1<A NAME="e">&nbsp;</A></sPAN></span><span id=mxag16>მის</span></BODY>'
    )
    markers = [e for e in T.parse_page(page) if isinstance(e, T.Marker)]
    assert [(m.value, m.indent) for m in markers] == [("14", 3), ("15", 6), ("12", 0), ("1", 0)]
    assert markers[0] == T.Marker(5, "Line of ed.", "14")  # indent is not compared


def test_segment_space_before_after_a_line_break_or_blank_span() -> None:
    page = (
        '<BODY><span id=mxagb16>იოვანე</span><span id=n16>\n<BR></span>'
        '<span id=mxagb16>ზედაძნელისა</span><span id=mxagp16> და</span><span id=mxagb16> </span>'
        '<span id=mxagq16>მისთაჲ</span><span id=n16>\n<BR>'
        '<span id=h5><!Level 5>Line of ed.: 2<A NAME="a">&nbsp;</A></sPAN>&nbsp;</span>'
        '<span id=mxag16>მოწაფეთა</span></BODY>'
    )
    segs = [e for e in T.parse_page(page) if isinstance(e, T.Segment)]
    assert [(s.text, s.space_before) for s in segs] == [
        ("იოვანე", False), ("ზედაძნელისა", True), (" და", False), ("მისთაჲ", True),
        ("მოწაფეთა", True)]
