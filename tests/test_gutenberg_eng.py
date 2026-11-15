"""Tests for the Project Gutenberg English ingestor (#349), on inline HTML fixtures."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from scripts.ingest import gutenberg_eng as g

HEADER = """<header class="pg-boilerplate pgheader" id="pg-header" lang="en">
<h2 id="pg-header-heading">The Project Gutenberg eBook of Something</h2>
<div>This eBook is for the use of anyone anywhere in the United States.</div>
<div>*** START OF THE PROJECT GUTENBERG EBOOK SOMETHING ***</div></header>"""
FOOTER = """<footer class="pg-boilerplate pgheader" id="pg-footer" lang="en">
<div>*** END OF THE PROJECT GUTENBERG EBOOK SOMETHING ***</div>
<h2 id="pg-footer-heading">THE FULL PROJECT GUTENBERG™ LICENSE</h2>
<p>Project Gutenberg License terms. Redistribution is subject to the trademark license.</p>
</footer>"""


def page(body: str) -> str:
    return f"<html><head><title>x</title></head><body>{HEADER}{body}{FOOTER}</body></html>"


def texts(book: g.Book) -> str:
    return " ".join(u["text"] for u in book.units)


def unit(book: g.Book, ref: str) -> dict:
    return next(u for u in book.units if u["ref"] == ref)


def marked(u: dict) -> list[tuple[str, str]]:
    return [(k, u["text"][s:e]) for s, e, k in u.get("editorial", [])]


# ---------------------------------------------------------------------------
# Boilerplate and text
# ---------------------------------------------------------------------------

def test_strip_boilerplate_removes_header_footer_and_licence() -> None:
    soup = g.load(page("<p>Body text.</p>"))
    text = soup.get_text(" ")
    assert "Body text." in text
    assert "Gutenberg" not in text
    assert "LICENSE" not in text and "trademark" not in text


def test_strip_boilerplate_rejects_unwrapped_licence() -> None:
    html = "<html><body><p>*** START OF THE PROJECT GUTENBERG EBOOK X ***</p><p>Text</p></body></html>"
    with pytest.raises(g.GutenbergFormatError):
        g.load(html)


def test_text_builder_collapses_whitespace_and_keeps_spans() -> None:
    tb = g.TextBuilder()
    tb.add("  Hello\n  world ")
    tb.add("[1]", "note")
    tb.add("   and   more  ")
    tb.add(" [1] A note. ", "note")
    text, spans = tb.build()
    assert text == "Hello world [1] and more [1] A note."
    assert [text[s:e] for s, e, _ in spans] == ["[1]", "[1] A note."]


def test_roman() -> None:
    assert g.roman("XIV") == 14
    assert g.roman("XL.") == 40
    with pytest.raises(g.GutenbergFormatError):
        g.roman("CHAPTER")


# ---------------------------------------------------------------------------
# Procopius, Wars
# ---------------------------------------------------------------------------

WARS_VOL1 = """
<h3><a id="INTRODUCTION">INTRODUCTION</a></h3>
<p>Procopius is known to posterity.<a id="FNanchor_1_9"></a><a class="fnanchor" href="#Footnote_1_9">[1]</a></p>
<p><a id="Footnote_1_9"></a><a href="#FNanchor_1_9"><span class="label">[1]</span></a> </p> <p> An intro note.</p>
<h3><a id="BIBLIOGRAPHY">BIBLIOGRAPHY</a></h3>
<p>Haury, 1905.</p>
<h2><a id="BOOK_I">HISTORY OF THE WARS: BOOK I</a></h2>
<h4>THE PERSIAN WAR</h4>
<div><span class="pagenum"><a id="PageI_i_1">[1-2]</a></span></div>
<p>I</p>
<p>Procopius of Caesarea has written<span class="pagenum"><a>[3-9]</a></span> the history.</p>
<p>It will be evident.<a id="FNanchor_2_2"></a><a class="fnanchor" href="#Footnote_2_2">[2]</a></p>
<p>II</p>
<p><span class="sidenote">408 A.D.</span>
When the Roman Emperor Arcadius was lying at Byzantium.</p>
<p>FOOTNOTES:</p>
<p><a id="Footnote_2_2"></a><a href="#FNanchor_2_2"><span class="label">[2]</span></a> </p> <p> Cf. <i>Iliad</i> v. 192.</p>
<p>Second paragraph of the note.</p>
<h2><a id="BOOK_II">HISTORY OF THE WARS: BOOK II</a></h2>
<p>I</p>
<p>Book two begins.</p>
<h3><a id="INDEX">INDEX</a></h3>
<p>Abasgi, the, II. xxix. 15</p>
"""

WARS_VOL3 = """
<h2>CONTENTS</h2>
<ul><li><p>BOOK V</p></li></ul>
<h3>HISTORY OF THE WARS:</h3>
<h3>BOOK V</h3>
<h2>HISTORY OF THE WARS: BOOK V</h2>
<h2>THE GOTHIC WAR</h2>
<h2>I</h2>
<p><a id="V_i_1"></a>Such, then, were the fortunes.<a id="FNanchor_1_1"></a><a class="fnanchor" href="#Footnote_1_1">[1]</a></p>
<div class="footnotes"><h3>FOOTNOTES:</h3>
<div class="footnote"><a id="Footnote_1_1"></a><a href="#FNanchor_1_1"><span class="label">[1]</span></a> Book III. ii. 7 ff.</div>
</div>
<h2>HISTORY OF THE WARS:</h2>
<h2>BOOK VI</h2>
<h2>XV</h2>
<p>The last chapter.</p>
<div class="tnote"><p>Transcriber's Note: about the index.</p></div>
<h2>INDEX</h2>
<p>Aemilia, V. i. 1</p>
"""


def test_wars_volume_books_chapters_and_notes() -> None:
    book = g.Book("ProcWars")
    g.parse_wars_volume(g.load(page(WARS_VOL1)), book, intro=True)
    refs = [u["ref"] for u in book.units]
    assert refs == ["ProcWars.TrPref.1", "ProcWars.1.1.1", "ProcWars.1.1.2", "ProcWars.1.2.1",
                    "ProcWars.2.1.1"]
    pref = unit(book, "ProcWars.TrPref.1")
    assert pref["text"] == "Procopius is known to posterity.[1] [1] An intro note."
    assert marked(pref) == [("note", pref["text"])]
    assert unit(book, "ProcWars.1.1.1")["text"] == "Procopius of Caesarea has written the history."
    u = unit(book, "ProcWars.1.1.2")
    assert u["text"] == ("It will be evident.[2] [2] Cf. Iliad v. 192. "
                         "Second paragraph of the note.")
    assert marked(u) == [("note", "[2]"),
                         ("note", "[2] Cf. Iliad v. 192. Second paragraph of the note.")]
    u = unit(book, "ProcWars.1.2.1")
    assert u["text"] == "[408 A.D.] When the Roman Emperor Arcadius was lying at Byzantium."
    assert marked(u) == [("note", "[408 A.D.]")]
    assert "Haury" not in texts(book) and "Abasgi" not in texts(book)


def test_wars_volume_three_style() -> None:
    book = g.Book("ProcWars")
    g.parse_wars_volume(g.load(page(WARS_VOL3)), book)
    assert [u["ref"] for u in book.units] == ["ProcWars.5.1.1", "ProcWars.6.15.1"]
    u = unit(book, "ProcWars.5.1.1")
    assert u["text"] == "Such, then, were the fortunes.[1] [1] Book III. ii. 7 ff."
    assert "Transcriber" not in texts(book) and "Aemilia" not in texts(book)


def test_wars_text_before_chapter_raises() -> None:
    html = page('<h2><a id="BOOK_I">BOOK I</a></h2><p>Orphan text.</p>')
    with pytest.raises(g.GutenbergFormatError):
        g.parse_wars_volume(g.load(html), g.Book("ProcWars"))


# ---------------------------------------------------------------------------
# Secret History
# ---------------------------------------------------------------------------

SECRET = """
<p>[Transcriber's Note: Macrons are indicated by [=e].]</p>
<h1>THE SECRET HISTORY</h1>
<h2>PREFACE</h2>
<p>Procopius was born at Caesarea.[1]</p>
<h2>CONTENTS</h2>
<h3>INTRODUCTION</h3>
<p>Arrangement of the work.</p>
<h2>CHAPTER I</h2>
<p>Birth of Antonina—</p>
<p>Her marriage.</p>
<h2>INTRODUCTION</h2>
<p>I have thus described the wars.</p>
<h2>CHAPTER I</h2>
<p>Belisarius had a wife, the Syn[=o]n[=e].[2]</p>
<h4>NOTES</h4>
<p>[1: By Mr. Hodgkin.]</p>
<p>[2: Spearmen, lancers.]</p>
"""


def test_secret_history() -> None:
    book = g.parse_secret_history(g.load(g.secret_history_macrons(page(SECRET))))
    assert [u["ref"] for u in book.units] == [
        "ProcAnec.TrPref.1", "ProcAnec.Intro.1", "ProcAnec.Intro.2", "ProcAnec.1.1", "ProcAnec.1.2"]
    assert marked(unit(book, "ProcAnec.TrPref.1")) == [
        ("note", "Procopius was born at Caesarea.[1] [1] By Mr. Hodgkin.")]
    assert marked(unit(book, "ProcAnec.1.1")) == [("heading", "Birth of Antonina— Her marriage.")]
    u = unit(book, "ProcAnec.1.2")
    assert u["text"] == "Belisarius had a wife, the Synōnē.[2] [2] Spearmen, lancers."
    assert marked(u) == [("note", "[2]"), ("note", "[2] Spearmen, lancers.")]
    assert "Transcriber" not in texts(book)


# ---------------------------------------------------------------------------
# Barlaam, Allies, Prudentius
# ---------------------------------------------------------------------------

BARLAAM = """
<h1>Barlaam and Ioasaph</h1>
<p>PREPARER'S NOTE: similarities with the Buddha.</p>
<h1>BARLAAM AND IOASAPH</h1>
<p class="intro">AN EDIFYING STORY BY JOHN THE MONK.</p>
<h3>INTRODUCTION</h3>
<p>"As many as are led by the Spirit."</p>
<h2>CONTENTS</h2>
<p><table><tr><td><a href="#chap01">CHAPTER I</a></td></tr></table></p>
<h3>I.</h3>
<p>The country of the Indians.</p>
<h3>X</h3>
<p>Chapter ten.</p>
"""


def test_barlaam() -> None:
    book = g.parse_barlaam(g.load(page(BARLAAM)))
    assert [u["ref"] for u in book.units] == [
        "BarlIoas.Praef.1", "BarlIoas.Praef.2", "BarlIoas.1.1", "BarlIoas.10.1"]
    assert marked(unit(book, "BarlIoas.Praef.1")) == [("title", "AN EDIFYING STORY BY JOHN THE MONK.")]
    assert "PREPARER" not in texts(book) and "CHAPTER I" not in texts(book)


ALLIES = """
<div class="level-2 section" id="translators-preface"><h2>TRANSLATOR'S PREFACE</h2>
<p>A Treatise on Images.</p></div>
""" + "".join(
    f'<div class="level-2 section" id="{sec}"><h2><span class="pageno" id="p{i}"></span>'
    f'<span>TITLE {i}.</span></h2><p>Text {i}.</p></div>'
    for i, sec in enumerate(g.ALLIES_SECTIONS)
).replace(
    "<p>Text 0.</p>",
    '<div class="level-3 section"><h3>Testimony.<a class="footnote-reference" href="#id52" '
    'id="id1"><sup>1</sup></a></h3><p>Text 0.</p>'
    '<blockquote><div><div class="line">Line one,</div><div class="line">line two.</div></div>'
    '</blockquote></div>',
) + """
<table class="docutils footnote" id="id52"><tbody><tr>
<td class="label"><a class="fn-backref" href="#id1">[<span>1</span>]</a></td>
<td><p>Omitted repetitions.</p></td></tr></tbody></table>
"""


def test_allies() -> None:
    books = g.parse_allies(g.load(page(ALLIES)))
    images = books["images"]
    assert [u["ref"] for u in images.units] == [
        "JDImag.TrPref.1", "JDImag.1.1", "JDImag.1.2", "JDImag.1.3", "JDImag.1.4",
        "JDImag.2.1", "JDImag.2.2", "JDImag.3.1", "JDImag.3.2"]
    assert marked(unit(images, "JDImag.1.1")) == [("title", "TITLE 0.")]
    assert marked(unit(images, "JDImag.1.2")) == [
        ("heading", "Testimony.[1] [1] Omitted repetitions.")]
    assert unit(images, "JDImag.1.4")["text"] == "Line one, line two."
    assert [u["ref"] for u in books["dormition-3"].units] == ["JDDorm3.1.1", "JDDorm3.1.2"]


CATH = """
<h3><a id="p00o">PRAEFATIO</a></h3>
<table class="poem"><tr><td><p class="t">Per quinquennia iam decem,</p></td></tr></table>
""" + "".join(
    f'<h3><a id="p{n:02d}t">{n}. HYMN</a></h3><table class="poem"><tbody><tr><td>'
    f'<p class="l">Line a {n},</p><p class="l">line b.</p><p class="l"> </p>'
    f'<p class="l">Second stanza.</p></td></tr></tbody></table>'
    for n in range(14)
) + """
<h3><a id="trn">TRANSLATOR'S NOTE</a></h3>
<p>Prudentius was born in 348.</p>
<h1>NOTES</h1>
<p>On line 1 of the Latin.</p>
"""


def test_cathemerinon() -> None:
    book = g.parse_cathemerinon(g.load(page(CATH)))
    refs = [u["ref"] for u in book.units]
    assert refs[:4] == ["PrudCath.TrPref.1", "PrudCath.Praef.1", "PrudCath.Praef.2", "PrudCath.Praef.3"]
    assert refs[-3:] == ["PrudCath.Epil.1", "PrudCath.Epil.2", "PrudCath.Epil.3"]
    assert unit(book, "PrudCath.1.2")["text"] == "Line a 1, line b."
    assert marked(unit(book, "PrudCath.1.1")) == [("title", "1. HYMN")]
    assert "quinquennia" not in texts(book) and "Latin" not in texts(book)


# ---------------------------------------------------------------------------
# Works and raw files
# ---------------------------------------------------------------------------

def test_metadata() -> None:
    works = {k: g.make_work(m) for k, m in g.METAS.items()}
    assert works["wars"].translation_of == "perseus/tlg4029/tlg001/perseus-grc2"
    assert works["barlaam"].translation_of == "perseus/tlg2934/tlg066/perseus-grc2"
    assert works["images"].translation_of is None  # the OGPG work is a container
    assert works["cathemerinon"].translation_of is None  # PL 59 container
    for w in works.values():
        assert w.language == "eng" and w.license == "public_domain"
        assert w.work_id.startswith("gutenberg-eng/")
        assert "Gutenberg" in (w.edition or "")


RAW = Path(__file__).resolve().parents[1] / "data" / "raw" / g.SOURCE_ID


def _materialized(path: Path) -> bool:
    return path.exists() and not path.read_bytes().startswith(b"version https://git-lfs")


@pytest.mark.skipif(not _materialized(RAW / "procopius-wars.json"), reason="raw data not present")
def test_raw_files_have_no_boilerplate() -> None:
    for meta in g.METAS.values():
        data = json.loads((RAW / f"{meta.local_id}.json").read_text(encoding="utf-8"))
        for u in data["paragraphs"]:
            assert "Gutenberg" not in u["text"], u["ref"]


def test_full_fixture_shapes_parse_without_bs4_warnings() -> None:
    # load() must accept a page with no header/footer at all
    assert isinstance(g.load("<html><body><p>x</p></body></html>"), BeautifulSoup)
