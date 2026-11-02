"""Tests for the Ælfric Catholic Homilies I ingestors (#566), on an inline
fixture shaped like Project Gutenberg #38334's HTML."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ingest import _aelfric_ch as ach
from scripts.ingest._aelfric_ch import AelfricFormatError, make_work, parse

_TOC_ROWS = "\n".join(
    f'<tr><td class="hspcsingle"> {ach._roman(n)}.</td><td class="hspcsingle"> {{lang}} {n}</td>'
    f'<td class="hspcsingle"> <a href="#page{n}" class="pginternal">{n}</a></td></tr>'
    for n in range(1, 41)
)


def _homily_table(n: int) -> str:
    return f"""
<table class="nobctr">
<tbody><tr><td class="saxonice">
<h3>VIII. K<span class="over">L</span>. JAN.</h3>
</td><td class="anglice">
<h3>DECEMBER XXV.</h3>
</td></tr>
<tr><td class="saxonice">
<blockquote class="b1n"><div>
<p>Cum descendisset Iesus de monte: et
  reliqua.</p>
</div></blockquote>
</td><td class="anglice">
<blockquote class="b1n"><div>
<p>Cum descendisset Jesus de monte: et reliqua.</p>
</div></blockquote>
</td></tr>
<tr><td class="saxonice">
<p><!-- Page 20 --><span class="pagenum"><a id="page20"></a>{{20}}</span></p>
<p>Homily {n}. He awecð ealle duna <!-- Page
  10 --><span class="pagenum"><a id="page10"></a>{{10}}</span>mid anre handa, to
  S<span class="over">ca</span> Marian, þæt hí magon beon [on] ðe gegladode.</p>
<p class="cenhead">EUANGELIUM.</p>
<p>Ða <span class="correction" title="Original reads 'ormatan'.">ormætan</span> ehtnyssa.</p>
</td><td class="anglice">
<p><!-- Page 21 --><span class="pagenum"><a id="page21"></a>{{21}}</span></p>
<p>He weigheth all hills with <i>one</i> hand, to St. Mary.</p>
<p class="cenhead">GOSPEL.</p>
<p>The great persecutions.</p>
</td></tr>
</tbody></table>"""


def _html(homilies: int = 40) -> str:
    return f"""<html><body>
<header class="pg-boilerplate">The Project Gutenberg eBook licence…</header>
<table class="nobctr" title="Table of contents (Latin)." data-summary="x"><tbody>
{_TOC_ROWS.replace('{lang}', 'De Homilia')}
</tbody></table>
<table class="nobctr" title="Table of contents (English)." data-summary="x"><tbody>
{_TOC_ROWS.replace('{lang}', 'On Homily')}
</tbody></table>
<p><!-- Page 1 --><span class="pagenum"><a id="page1"></a>{{1}}</span></p>
<h3>INCIPIT PRÆFATIO HUJUS LIBRI.</h3>
<p><br style="clear:both"></p>
<p class="cenhead">IN NOMINE DOMINI.</p>
<p>Ego Ælfricus, alumnus Adelwoldi, <!-- Page 2 --><span class="pagenum"><a id="page2"></a>{{2}}</span>salutem exopto.</p>
<hr class="full">
<table class="nobctr">
<tbody><tr><td class="saxonice">
<h3>PRÆFATIO.</h3>
</td><td class="anglice">
<h3>PREFACE.</h3>
</td></tr>
<tr><td class="saxonice"><p>Ic Ælfric munuc.</p></td><td class="anglice"><p>I Ælfric, monk.</p></td></tr>
</tbody></table>
{''.join(_homily_table(n) for n in range(1, homilies + 1))}
<footer class="pg-boilerplate">End of the Project Gutenberg eBook</footer>
</body></html>"""


@pytest.fixture(scope="module")
def pieces() -> list[ach.Piece]:
    return parse(_html())


def test_works_in_order(pieces: list[ach.Piece]) -> None:
    ids = [p.local_id for p in pieces]
    assert ids[:3] == ["ch1-praefatio-lat", "ch1-praefatio", "ch1-01"]
    assert ids[-1] == "ch1-40"
    assert len(pieces) == 42
    assert pieces[0].language == "lat" and pieces[0].english == []
    assert all(p.language == "ang" for p in pieces[1:])


def test_titles_from_contents(pieces: list[ach.Piece]) -> None:
    h7 = pieces[8]
    assert h7.number == 7
    assert make_work(h7, english=False).title == "Catholic Homilies I, VII: De Homilia 7"
    assert make_work(h7, english=True).title == "Catholic Homilies I, VII: On Homily 7"
    assert make_work(pieces[1], english=True).title == "Catholic Homilies I, Preface"


def test_shared_refs_and_pairing(pieces: list[ach.Piece]) -> None:
    for p in pieces[1:]:
        assert [u["ref"] for u in p.units] == [u["ref"] for u in p.english]
    h1 = pieces[2]
    assert [u["ref"] for u in h1.units] == [f"AECHomI.1.{k}" for k in range(1, 6)]
    assert h1.units[2]["text"].startswith("Homily 1.")
    assert h1.english[2]["text"] == "He weigheth all hills with one hand, to St. Mary."
    assert [u["ref"] for u in pieces[1].units] == ["AECHomI.Praef.1", "AECHomI.Praef.2"]


def test_text_cleanup(pieces: list[ach.Piece]) -> None:
    unit = pieces[2].units[2]
    # page numbers dropped, no word split; overline as U+0305; whitespace squeezed
    assert unit["text"] == ("Homily 1. He awecð ealle duna mid anre handa, to "
                            "Sc̅a̅ Marian, þæt hí magon beon [on] ðe gegladode.")
    assert pieces[2].units[4]["text"] == "Ða ormætan ehtnyssa."  # errata applied
    assert pieces[2].units[1]["text"] == "Cum descendisset Iesus de monte: et reliqua."
    assert "editorial" not in pieces[2].units[1]  # Latin pericope is text


def test_editorial_spans(pieces: list[ach.Piece]) -> None:
    h1 = pieces[2]
    title = h1.units[0]
    assert title["text"] == "VIII. KL̅. JAN."
    assert title["editorial"] == [[0, len(title["text"]), "title"]]
    assert h1.english[0]["editorial"] == [[0, len("DECEMBER XXV."), "title"]]
    assert h1.units[3]["editorial"] == [[0, len("EUANGELIUM."), "heading"]]
    assert h1.english[3]["editorial"] == [[0, len("GOSPEL."), "heading"]]
    text = h1.units[2]["text"]
    (s, e, kind), = h1.units[2]["editorial"]
    assert (text[s:e], kind) == ("[on]", "supplement")


def test_latin_preface(pieces: list[ach.Piece]) -> None:
    units = pieces[0].units
    assert [u["ref"] for u in units] == [f"AECHomI.PraefLat.{k}" for k in (1, 2, 3)]
    assert units[0]["editorial"][0][2] == "title"
    assert units[1]["editorial"][0][2] == "heading"
    assert units[2]["text"] == "Ego Ælfricus, alumnus Adelwoldi, salutem exopto."


def test_boilerplate_not_carried(pieces: list[ach.Piece]) -> None:
    for p in pieces:
        for u in p.units + p.english:
            assert "Gutenberg" not in u["text"]
            assert "{" not in u["text"]


def test_work_metadata(pieces: list[ach.Piece]) -> None:
    oe = make_work(pieces[2], english=False)
    en = make_work(pieces[2], english=True)
    lat = make_work(pieces[0], english=False)
    assert (oe.work_id, oe.language, oe.translation_of) == ("aelfric-ch/ch1-01", "ang", None)
    assert (en.work_id, en.language, en.translation_of) == (
        "aelfric-ch-eng/ch1-01", "eng", "aelfric-ch/ch1-01")
    assert (lat.work_id, lat.language) == ("aelfric-ch/ch1-praefatio-lat", "lat")
    for w in (oe, en, lat):
        assert w.license == "public_domain"
        assert w.genre == "patristic" and w.tradition == "latin"
        assert w.date_range == (989, 991) and w.date_confidence == "approximate"
        assert w.author == "Ælfric of Eynsham"


def test_mismatched_row_raises() -> None:
    html = _html().replace("<p>I Ælfric, monk.</p>", "<p>I Ælfric,</p><p>monk.</p>", 1)
    with pytest.raises(AelfricFormatError, match="Old English and 2 English"):
        parse(html)


def test_missing_homily_raises() -> None:
    with pytest.raises(AelfricFormatError, match="facing-page tables"):
        parse(_html(homilies=39))


def test_ingest_writes_raw_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    html_path = tmp_path / "page.html"
    html_path.write_text(_html(), encoding="utf-8")
    monkeypatch.setattr(ach, "fetch", lambda output_dir, force=False: html_path)
    oe_works = ach.ingest_source(tmp_path, force=False, english=False)
    en_works = ach.ingest_source(tmp_path, force=False, english=True)
    assert len(oe_works) == 42 and len(en_works) == 41
    raw = json.loads((tmp_path / "aelfric-ch-eng" / "ch1-03.json").read_text(encoding="utf-8"))
    assert raw["work"]["translation_of"] == "aelfric-ch/ch1-03"
    assert raw["paragraphs"][0] == {"ref": "AECHomI.3.1", "text": "DECEMBER XXV.",
                                    "editorial": [[0, 13, "title"]]}
    assert not (tmp_path / "aelfric-ch-eng" / "ch1-praefatio-lat.json").exists()
