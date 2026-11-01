"""CELT Old Irish texts (#541): header, layout stripping, editorial spans, unit builders."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica.period import work_in_period
from scripts.ingest import _celt as C
from scripts.ingest import celt

_RAW = Path(__file__).resolve().parents[1] / "data" / "raw" / "celt"


def _page(text_id: str, body: str, *, header_extra: str = "") -> str:
    return (
        "<html><body><h1>Test text</h1><h2>Author:\tUnknown</h2>"
        f"<p>Text ID Number: {text_id}<p>Availability [RESTRICTED] \n<p>Available with prior "
        "consent of the CELT programme for purposes of academic research and teaching only.</p>"
        "<h4>Sources</h4><ol><lh><b>The edition used in the digital edition</b></lh>"
        "<li> <cite>Test</cite>. Ed. A. Editor (Dublin 1900) </li></ol>"
        "<h3>Profile Description</h3><p>Created:  Date range: c.800&#0150;850.<h4>Use</h4>"
        f"{header_extra}"
        f'<hr><h4 align="center">Corpus of Electronic Texts Edition: {text_id}</h4>\n'
        f"<h3><cite>Test text</cite>: Author:\tUnknown</h3>\n{body}</body></html>"
    )


def _text(**kw: object) -> celt.Text:
    base: dict[str, object] = dict(
        celt_id="G999999",
        slug="t",
        prefix="T",
        title="T",
        author="Anonymous",
        date_range=(800, 900),
        date_confidence="approximate",
        genre="patristic",
        mode="stanzas",
    )
    base.update(kw)
    return celt.Text(**base)  # type: ignore[arg-type]


class TestHeader:
    def test_fields(self) -> None:
        h = C.parse_header(_page("G999999", ""))
        assert h.title == "Test text"
        assert h.author == "Unknown"
        assert "prior consent" in h.availability
        assert h.edition == "Test. Ed. A. Editor (Dublin 1900)"
        assert h.created == "Date range: c.800–850."

    def test_body_needs_edition_line(self) -> None:
        with pytest.raises(C.CeltError):
            C.body_html(_page("G999999", "x"), "G111111")

    def test_page_url(self) -> None:
        assert C.page_url("G200001") == "https://celt.ucc.ie/published/G200001.html"
        assert C.page_url("G207009A").endswith("G207009A.html")
        with pytest.raises(C.CeltError):
            C.page_url("../etc")

    def test_decode_latin1(self) -> None:
        assert C.decode(b"Ca\xefn") == "Caïn"
        assert C.decode("Caín".encode()) == "Caín"


class TestInline:
    def test_layout_and_tags(self) -> None:
        html = (
            '<br>12] ro <i>d&aacute;matar</i> s&aacute;ethu,<sup><a href="javascript:'
            "footNote('G1/note001.html')\">1</a></sup> co n-\n\ningen"
        )
        assert C.inline(html) == ("ro dámatar sáethu, co n-ingen", [])

    def test_gap_is_lacuna(self) -> None:
        text, spans = C.inline("[<i>gap: acephalous text</i>] miracula vulgata s<i>unt</i>.")
        assert text == "[gap: acephalous text] miracula vulgata sunt."
        assert spans == [[0, 22, "lacuna"]]

    def test_brackets_are_supplements(self) -> None:
        text, spans = C.inline("<i>-glanfait[h]er</i> in fer")
        assert text == "-glanfait[h]er in fer"
        assert spans == [[9, 12, "supplement"]]

    def test_marginal_reference_and_deletion_are_notes(self) -> None:
        text, spans = C.inline(
            'cor uestrum.</p><p align="right">Psalm 30.</p> Unde <s>: as</s> doibh'
        )
        assert text == "cor uestrum. [Psalm 30.] Unde : as doibh"
        assert [s[2] for s in spans] == ["note", "note"]
        assert text[spans[0][0] : spans[0][1]] == "[Psalm 30.]"
        assert text[spans[1][0] : spans[1][1]] == ": as"

    def test_character_placeholders(self) -> None:
        assert C.inline("co feib l[macr  ]thair, Bath&uacute;ail [excl  ]") == (
            "co feib l\u0304thair, Bathúail!",
            [],
        )

    def test_strip_layout(self) -> None:
        body = (
            'a<hr><p align="right"><small><a name="p18">p.18</a></small></P>\n{folio 22 a 1}b'
            '<div align="right">Charlottenburg. <address>Kuno Meyer.</address></div>'
        )
        assert C.inline(C.strip_layout(body))[0] == "a b"

    def test_join_units_shifts_spans(self) -> None:
        assert C.join_units([("ab", [[0, 2, "note"]]), ("cd", [[1, 2, "supplement"]])]) == (
            "ab cd",
            [[0, 2, "note"], [4, 5, "supplement"]],
        )


class TestBuilders:
    def test_stanzas_with_prose_frame(self) -> None:
        body = (
            "<h3>The Bell</h3><b>&Iacute;te</b> co t&aacute;inic, as-bert-si:<ol>"
            '<li value="1">&Iacute;suc&aacute;n\n<br>alar lium</li>'
            '<li value="2">Altram\n<br>alar<p>Tuc.</p></li></ol><p>Finit.</p>'
        )
        units = celt.parse(_text(), _page("G999999", body))
        assert [u["ref"] for u in units] == ["T.0", "T.1", "T.2"]
        assert units[0]["text"] == "Íte co táinic, as-bert-si:"
        assert units[2]["text"] == "Altram alar Tuc. Finit."

    def test_stanzas_without_values_and_sections(self) -> None:
        body = '<ol><li>a b</li><li>c d</li></ol><h2>De monur.</h2><ol><li value="9">e</li></ol>'
        units = celt.parse(_text(sections=True), _page("G999999", body))
        assert [u["ref"] for u in units] == ["T.1.1", "T.1.2", "T.2", "T.2.9"]
        assert units[2]["editorial"] == [[0, 9, "heading"]]

    def test_paras_by_pilcrow(self) -> None:
        body = (
            '<p>&#182;1] \n<br>1] Accinge</p><p>Unde</p><ol><li value="1">Mallacht</li></ol>'
            "<p>&#182;2] Is ann</p>"
        )
        units = celt.parse(_text(mode="paras"), _page("G999999", body))
        assert [(u["ref"], u["text"]) for u in units] == [
            ("T.1", "Accinge Unde Mallacht"),
            ("T.2", "Is ann"),
        ]

    def test_marginal_reference_joins_paragraph(self) -> None:
        body = '<p>Beati qui lugent</p><p align="right">Matt. 5:5</p><p>Next</p>'
        units = celt.parse(_text(mode="paras"), _page("G999999", body))
        assert [u["text"] for u in units] == ["Beati qui lugent [Matt. 5:5]", "Next"]
        assert units[0]["editorial"] == [[17, 28, "note"]]

    def test_numbered_sections_parts_and_repeats(self) -> None:
        body = (
            "<h4>1</h4><p>\n<br>1] Bai</p><h4>2</h4><p>Fecht</p><p>ale</p><h4>2</h4><p>X</p>"
            "<h2>Slicht sain</h2><h4>1</h4><p>Tecar</p>"
        )
        units = celt.parse(
            _text(mode="numbered", parts=(("Slicht sain", "Slicht"),)), _page("G999999", body)
        )
        assert [(u["ref"], u["text"]) for u in units] == [
            ("T.1", "Bai"),
            ("T.2", "Fecht ale"),
            ("T.2b", "X"),
            ("T.Slicht", "Slicht sain"),
            ("T.Slicht.1", "Tecar"),
        ]

    def test_numbered_rejects_stray_heading(self) -> None:
        with pytest.raises(C.CeltError):
            celt.parse(_text(mode="numbered"), _page("G999999", "<h4>1</h4><p>a</p><h3>Intro</h3>"))

    def test_start_and_end_markers(self) -> None:
        body = '<p>Vorwort.</p><hr>START<ol><li value="1">a</li></ol>END<p>Nachwort</p>'
        units = celt.parse(_text(start="START", end="END"), _page("G999999", body))
        assert [u["text"] for u in units] == ["a"]

    def test_saltair_quatrains_by_first_line(self) -> None:
        body = (
            "<h3>Preface</h3><p>Stokes.</p><h2>Saltair na Rann</h2><h2>1.</h2>\n<ol>\n"
            "<li>Mor&iacute;se\n<br>b\n<br>c\n<br>d\n<br>5] e\n<br>f\n<br>g\n<br>h</li></ol>"
            "<h3>2.</h3>\n<br>9] i\n<br>j"
        )
        units = celt.parse(_text(mode="saltair"), _page("G999999", body))
        assert [(u["ref"], u["text"]) for u in units] == [
            ("T.1.1", "Moríse b c d"),
            ("T.1.5", "e f g h"),
            ("T.2.9", "i j"),
        ]

    def test_felire_calendar_line_is_metadata(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(celt, "_MONTH_DAYS", {m: 1 for m in celt._MONTH_DAYS})
        body = (
            "<h2>DA REMFHOCUL.</h2><p>later prose preface</p>"
            '<h3>IN PROLACH.</h3><ol><li value="1">1] S&Eacute;N a Chr&iacute;st</li></ol>'
            + "".join(
                f'<h4>M&Iacute; {m}.</h4><ol><li value="1"><b>A. Kalendis.</b>'
                "<br>1] Re s&iacute;l</li></ol>"
                for m in celt._MONTHS
            )
            + '<h3>EPILOGUE</h3><ol><li value="1">Is</li></ol><p>A note.</p>'
        )
        units = celt.parse(_text(mode="felire", prefix="Fel"), _page("G999999", body))
        refs = [u["ref"] for u in units]
        assert refs[:3] == ["Fel.Prol.1", "Fel.Jan", "Fel.Jan.1"]
        jan1 = units[2]
        assert jan1["text"] == "A. Kalendis. Re síl"
        assert jan1["editorial"] == [[0, 12, "metadata"]]
        assert units[-1]["ref"] == "Fel.Epil.1"
        assert units[-1]["editorial"] == [[3, 10, "note"]]
        assert "later prose preface" not in json.dumps(units)


class TestSelection:
    def test_every_text_in_period_and_unpublished(self) -> None:
        for t in celt.ALL_TEXTS:
            assert t.date_range is not None
            assert work_in_period(t.date_range), t.celt_id
        assert C.CELT_LICENSE == "unknown"

    def test_owner_exclusions_stay_out(self) -> None:
        assert not set(celt.OWNER_EXCLUDED) & {t.celt_id for t in celt.ALL_TEXTS}

    def test_unique_ids_and_translations(self) -> None:
        slugs = [t.slug for t in celt.ALL_TEXTS]
        assert len(set(slugs)) == len(slugs)
        assert len({t.celt_id for t in celt.ALL_TEXTS}) == len(slugs)
        for t in celt.ALL_TEXTS:
            assert t.language == ("eng" if t.celt_id.startswith("T") else "sga")
            if t.translation_of:
                assert t.translation_of in slugs


@pytest.mark.skipif(
    not (_RAW / "felire-oengusso.json").exists()
    or (_RAW / "felire-oengusso.json").read_bytes().startswith(b"version https://git-lfs"),
    reason="CELT raw data not materialized",
)
class TestRawData:
    def test_felire_has_every_day(self) -> None:
        data = json.loads((_RAW / "felire-oengusso.json").read_text(encoding="utf-8"))
        days = [
            u
            for u in data["verses"]
            if u["ref"].count(".") == 2 and u["ref"].split(".")[1] not in ("Prol", "Epil")
        ]
        assert len(days) == 365
        assert data["work"]["license"] == "unknown"
