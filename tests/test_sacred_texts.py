"""Tests for the Internet Sacred Text Archive ingestors (#353), on inline fixtures."""

from __future__ import annotations

from scripts.ingest import _sacred_texts as st
from scripts.ingest import charles_eng, sacred_texts_eng
from scripts.ingest.charles_eng import Book


def _spans(rec: dict) -> list[tuple[str, str]]:
    return [(rec["text"][s:e], k) for s, e, k in rec.get("editorial", [])]


JUB_PAGE = """<html><body><p>nav</p>
<h3 align="center">Paradise and the Fall (iii. 1-35).</h3>
<p>III. And on the six days we brought unto Adam all the beasts. 2. And Adam named them
all.&nbsp;<A NAME="fr_1"></A><A HREF="#fn_1"><FONT SIZE="1">5</FONT></A> 3. And Adam saw these,</p>
<p><A NAME="page_47"><FONT SIZE=1 COLOR=GREEN>p. 47</FONT></A></p>
<p><FONT SIZE=-2 COLOR=GREEN>[paragraph continues]</FONT> but he was alone. 4. And the Lord
said<TABLE ALIGN="LEFT"><TR><TD>7 A.M.</TD></TR></TABLE> unto us.&nbsp;<A NAME="fr_2"></A><A HREF="#fn_2"><FONT SIZE="1">5</FONT></A>. And it was so.</p>
<HR><H3 ALIGN="CENTER">Footnotes</H3>
<P><A NAME="fn_1"></A><A HREF="x.htm#fr_1">46:5</A> Cf. Gen. ii. 19.</P>
<P><A NAME="fn_2"></A><A HREF="x.htm#fr_2">47:1</A> A note.</P>
<nav>Next</nav></body></html>"""


def test_page_text() -> None:
    page = st.page_text(JUB_PAGE)
    assert page.heading == "Paradise and the Fall (iii. 1-35)."
    assert page.notes == {"1": "Cf. Gen. ii. 19.", "2": "A note."}
    paras = [t for k, t in page.items if k == "P"]
    assert paras[0].startswith("III. And on the six days")
    assert "\x05F1|5\x06" in paras[0]
    assert paras[1].startswith("but he was alone.")
    assert "\x05M7 A.M.\x06" in paras[1]
    assert "p. 47" not in page.text and "paragraph continues" not in page.text


def _book(**kw) -> Book:
    base = dict(osis="Jub", title="Jubilees", directory="bib/jub", pages=(), chapters=3,
                date_composed=-155, date_range=(-170, -140), edition="ed.")
    base.update(kw)
    return Book(**base)


def test_split_verses_jubilees() -> None:
    pages = [st.page_text("<h3>Prologue</h3><p>THIS is the history.</p>"),
             st.page_text("<h3>Revelation (i. 1-2).</h3><p>1. And it came to pass. 2. And Moses went up.</p>"),
             st.page_text("<h3>Creation (ii. 1-2)</h3><p>II. And the angel spake. 2 And he said.</p>"),
             st.page_text(JUB_PAGE)]
    recs = charles_eng.split_verses(_book(), pages)
    by_ref = {r["ref"]: r for r in recs}
    assert list(by_ref) == ["Jub.1.0", "Jub.1.1", "Jub.1.2", "Jub.2.1", "Jub.2.2",
                            "Jub.3.1", "Jub.3.2", "Jub.3.3", "Jub.3.4", "Jub.3.5"]
    assert _spans(by_ref["Jub.1.0"]) == [("Prologue", "heading")]
    assert by_ref["Jub.1.0"]["text"] == "Prologue THIS is the history."
    assert by_ref["Jub.1.1"]["text"] == "Revelation (i. 1-2). And it came to pass."
    assert by_ref["Jub.2.2"]["text"] == "And he said."
    assert _spans(by_ref["Jub.3.2"]) == [("[Cf. Gen. ii. 19.]", "note")]
    assert by_ref["Jub.3.3"]["text"] == "And Adam saw these, but he was alone."
    # A margin date is a note; a verse number made a footnote link still opens verse 5.
    assert _spans(by_ref["Jub.3.4"]) == [("[7 A.M.]", "note"), ("[A note.]", "note")]
    assert by_ref["Jub.3.5"]["text"] == "And it was so."


def test_split_verses_enoch_sections_out_of_order() -> None:
    book = _book(osis="1En", chapters=93, chapter_headings=True)
    pages = [st.page_text("<h1>BOOK OF ENOCH</h1><h3>CHAPTER XCII.</h3><p>1. Written by Enoch. 2. Let not.</p>"),
             st.page_text("<h3>CHAPTER XCI.</h3><p>1. And now, my son.</p><p>[11. And after that.]</p>"
                          "<p>18. And now I tell you.</p>"),
             st.page_text("<h3>CHAPTER XCIII.</h3><p>1. And after that Enoch.</p>"),
             st.page_text("<p align=CENTER>XCI. 12-17. The Last Weeks.</p><h3>CHAPTER XCI.</h3>"
                          "<p>12. And after that there shall be.</p>")]
    recs = charles_eng.split_verses(book, pages)
    assert [r["ref"] for r in recs] == ["1En.92.1", "1En.92.2", "1En.91.1", "1En.91.11", "1En.91.18",
                                        "1En.93.1", "1En.91.12"]
    by_ref = {r["ref"]: r for r in recs}
    assert by_ref["1En.91.11"]["text"] == "[And after that.]"
    assert _spans(by_ref["1En.91.12"]) == [("XCI. 12-17. The Last Weeks.", "heading")]


def test_parallel_columns_of_enoch() -> None:
    page = st.page_text(
        "<h3>CHAPTER XXII.</h3><p>1. And thence I went.</p>"
        "<table><tr><td><p align=CENTER><b>E</b></p><p>2 And there was in it.</p></td>"
        "<td><b><p align=CENTER>G<sup>g</b></sup></p><p>2. And there were.</p></td></tr></table>"
        "<p>3. Then Raphael answered.</p>")
    recs = charles_eng.split_verses(_book(osis="1En", chapters=22, chapter_headings=True), [page])
    by_ref = {r["ref"]: r for r in recs}
    assert by_ref["1En.22.2"]["text"] == "And there was in it. [Gg: 2. And there were.]"
    assert _spans(by_ref["1En.22.2"]) == [("[Gg: 2. And there were.]", "note")]
    assert "1En.22.3" in by_ref


def test_fix_page() -> None:
    assert "VI. And on the new moon" in charles_eng.fix_page("jub20.htm", "<p>V1. And on the new moon</p>")


SIB_PAGE = """<H1>BOOK I.</H1><P>{p. 14}</P><H3>CONTENTS OF BOOK I.</H3><P>Announcement, 1-5.</P>
<H2>THE SIBYLLINE ORACLES.</H2><H3>BOOK I.</H3>
<P>BEGINNING with the generation first<BR>
Of mortal men down to the very last.<BR>
I'll prophesy each thing: what erst has been,<BR>
And what is now, and what shall yet befall<BR>
5 The world through the impiety of men.<BR>
First now God urges on me to relate<BR>
Truly how into being came the world.<BR>
And thou, shrewd mortal, prudently make known,<BR>
Lest ever thou should'st my commands neglect,<BR>
10 The King most high, who brought into existence<BR>
The whole world, saying, "Let there be," and there was.<BR>
For he the earth established, placing it</P>
<FONT SIZE=2><P>[1. This book appears late.</P><P>13. Tartarus is the prison.]</P></FONT>
<P ALIGN="CENTER">(1-10.)</P><P>{p. 16}</P>
<P>Round about Tartarus, and he himself.<BR>
Next: Book II.</P>"""


def test_sibyllines() -> None:
    page = st.page_text(SIB_PAGE)
    contents, lines = sacred_texts_eng.sibyl_lines(1, page)
    assert contents == "Announcement, 1-5."
    assert [ln.number for ln in lines] == list(range(1, 14))
    assert lines[4].text == "The world through the impiety of men."
    assert lines[11].notes == ["1. This book appears late. 13. Tartarus is the prison.", "Greek lines 1-10"]
    recs = sacred_texts_eng.sibyl_units(1, contents, lines)
    assert [r["ref"] for r in recs] == ["SibOr.1.0", "SibOr.1.1", "SibOr.1.12"]
    assert recs[0]["editorial"] == [[0, len(contents), "note"]]
    assert recs[1]["text"].endswith('and there was.')
    assert _spans(recs[2]) == [("[1. This book appears late. 13. Tartarus is the prison.]", "note"),
                               ("[Greek lines 1-10]", "note")]
    assert "Next:" not in recs[2]["text"]


def test_works() -> None:
    jub = charles_eng._work(charles_eng.BOOKS[0])
    assert jub.work_id == "charles-eng/jub" and jub.translation_of is None  # from scripture_translation_of.csv
    assert charles_eng._work(charles_eng.BOOKS[1]).work_id == "charles-eng/1en"
    sib = sacred_texts_eng._work(sacred_texts_eng.SIBYLLINES)
    assert sib.translation_of == "first1k/tlg1551/tlg001/1st1K-grc1"
    assert sib.license == "public_domain" and sib.language == "eng"
