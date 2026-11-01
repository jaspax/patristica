"""The Würzburg glosses (#539): gloss text, editorial spans, refs, folio fixes."""

from __future__ import annotations

import pytest

from patristica import editorial
from scripts.ingest import _wb_glosses as wb


def _gloss(no: str, tags: str, trans: str = "i.e. it.", lemma: str = "meo",
           lat_line: str = "Rom. I. 8") -> dict:
    return {"glossNo": no, "glossFullTags": tags, "glossText": "", "glossTrans": trans,
            "lemma": lemma, "latLine": lat_line}


def _epistle(*folios: tuple[str, list[dict]], title: str = "EPISTOLA AD ROMANOS.") -> dict:
    return {"epistle": title,
            "folios": [{"folio": f"f. {f}", "glosses": gs} for f, gs in folios]}


def _marked(text: str, spans: list) -> list[tuple[str, str]]:
    return [(text[s:e], k) for s, e, k in spans]


def test_irish_text_keeps_latin_and_drops_footnote_letters() -> None:
    text, spans = wb.irish_text(
        "[ie].i.[/ie] isdiasom do[Con]m[/Con]sa [GLat]christo ut ipse dixit[/GLat][a] "
        "[etc]rl.[/etc]")
    assert text == ".i. isdiasom domsa christo ut ipse dixit rl."
    assert spans == []


def test_irish_text_marks_comments_and_supplements() -> None:
    text, spans = wb.irish_text(
        "asnolcc [Com]in marg.[/Com] [ie].i.[/ie] nam[Res]mi[/Res]tter [vel]ɫ.[/vel] "
        "[GLat]sine in[Sup]termisione[/Sup][/GLat][d]")
    assert text == "asnolcc [in marg.] .i. nam(mi)tter ɫ. sine in[termisione]"
    assert _marked(text, spans) == [
        ("[in marg.]", "note"), ("(mi)", "supplement"), ("[termisione]", "supplement")]
    chunk = {"text": text, "editorial": [list(s) for s in spans]}
    assert editorial.source_text(chunk) == "asnolcc .i. nammitter ɫ. sine intermisione"


def test_irish_text_rejects_unknown_tags() -> None:
    with pytest.raises(wb.WbFormatError):
        wb.irish_text("[Foo]x[/Foo]")
    with pytest.raises(wb.WbFormatError):
        wb.irish_text("[Res]x")


def test_has_irish() -> None:
    assert not wb.has_irish("[ie].i.[/ie] [GLat]deus pater[/GLat]")
    assert not wb.has_irish("[Com]in marg.[/Com] [GLat]sermo[/GLat][b]")
    assert wb.has_irish("[ie].i.[/ie] sain[a]")
    assert wb.has_irish("[ie].i.[/ie] do[GLat]moysi[/GLat]")


def test_english_text_drops_footnote_letters_and_markup() -> None:
    assert wb.english_text(
        "i.e. <em>generaliter</em>, because He has imparted<sup>g</sup> <em>Spiritum</em>, etc."
    ) == "i.e. generaliter, because He has imparted Spiritum, etc."


@pytest.mark.parametrize(("lat_line", "label"), [
    ("Rom. I. 8", "Rom. 1:8"),
    ("Rom. XIV. 19", "Rom. 14:19"),
    ("Rom. IX. 20, 21", "Rom. 9:20–21"),
    ("Rom. - No Chapter or Verse Information Available", None),
])
def test_verse_label(lat_line: str, label: str | None) -> None:
    assert wb.verse_label(lat_line, "Rom.") == label


def test_parse_refs_prefix_and_skipped_latin() -> None:
    data = [_epistle(
        ("1a", [_gloss("1", "[ie].i.[/ie] airisdia [GLat]deo[/GLat]",
                       "i.e. <em>Deo</em> he is God."),
                _gloss("2", "[GLat]deus pater[/GLat]"),
                _gloss("2a", "ní mebul"),
                _gloss("3, 4", "precept soscéli", lemma="euangelium", lat_line="Rom. I. 16")]),
    )]
    (rom,), skipped = wb.parse(data)
    assert skipped == 1
    assert rom.local_id == "rom"
    assert [u["ref"] for u in rom.irish] == ["Wb.1a.1", "Wb.1a.2a", "Wb.1a.3-4"]
    assert [u["ref"] for u in rom.english] == [u["ref"] for u in rom.irish]
    first = rom.irish[0]
    assert first["text"] == "Rom. 1:8 meo] .i. airisdia deo"
    assert _marked(first["text"], first["editorial"]) == [("Rom. 1:8 meo]", "note")]
    assert rom.english[0]["text"] == "Rom. 1:8 meo] i.e. Deo he is God."
    assert rom.irish[2]["text"].startswith("Rom. 1:16 euangelium] ")


def test_misfiled_glosses_go_back_to_their_folio() -> None:
    data = [_epistle(
        ("2a", [_gloss("20", "a"), _gloss("21", "b")]),
        ("2b", [_gloss("22", "c"), _gloss("23", "d"), _gloss("1", "e"), _gloss("2", "f")]),
    )]
    (rom,), _ = wb.parse(data)
    assert [u["ref"] for u in rom.irish] == [
        "Wb.2a.20", "Wb.2a.21", "Wb.2a.22", "Wb.2a.23", "Wb.2b.1", "Wb.2b.2"]


def test_restart_that_does_not_continue_raises() -> None:
    data = [_epistle(("2a", [_gloss("20", "a")]), ("2b", [_gloss("5", "c"), _gloss("1", "e")]))]
    with pytest.raises(wb.WbFormatError):
        wb.parse(data)


def test_duplicate_ref_raises() -> None:
    data = [_epistle(("1a", [_gloss("1", "a"), _gloss("1", "b")]))]
    with pytest.raises(wb.WbFormatError):
        wb.parse(data)


def test_works() -> None:
    (rom,), _ = wb.parse([_epistle(("1a", [_gloss("1", "a")]))])
    irish, english = wb.make_work(rom, english=False), wb.make_work(rom, english=True)
    assert (irish.work_id, irish.language, irish.translation_of) == ("wb-glosses/rom", "sga", None)
    assert (english.work_id, english.language, english.translation_of) == (
        "wb-glosses-eng/rom", "eng", "wb-glosses/rom")
    assert irish.title == english.title == "Würzburg Glosses on Romans"
    assert irish.license == english.license == "cc-by-4.0"
