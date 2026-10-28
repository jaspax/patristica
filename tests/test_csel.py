"""CSEL ingestor (#77): text cleaning, verse lines, edition metadata, author overrides."""

from __future__ import annotations

from pathlib import Path

from lxml import etree

from scripts.ingest.csel import clean_text, extract_paragraphs, parse_file

_TEI = "http://www.tei-c.org/ns/1.0"


def _edition(body: str) -> etree._Element:
    return etree.fromstring(
        f'<div xmlns="{_TEI}" type="edition" xml:lang="lat" '
        f'n="urn:cts:latinLit:stoa9999.stoa001.opp-lat1">{body}</div>'
    )


def _extract(body: str) -> list[tuple[str, str]]:
    return [(r["ref"], r["text"]) for r in extract_paragraphs(_edition(body), "stoa9999.stoa001")]


def test_hyphenated_words_and_margin_line_numbers() -> None:
    assert clean_text("modus, si respondendum existi-\n 25 memus? Nam") == \
        "modus, si respondendum existimemus? Nam"
    assert clean_text("INCIPIT SE- CVNDVS") == "INCIPIT SECVNDVS"
    assert clean_text("annos 40 uixit") == "annos 40 uixit"  # only the margin numbers 5–35


def test_notes_page_breaks_and_line_breaks_are_dropped() -> None:
    body = (
        '<div type="textpart" subtype="book" n="1">'
        '<ab><title type="sub">LIBER PRIMVS.</title></ab>'
        '<div type="textpart" subtype="section" n="1">'
        '<p><milestone n="1" unit="altchapter"/>'
        'Magnus es, domine, et lau-<lb/>dabilis ualde: magna <lb/>'
        '<note type="footnote"> 2] Ps. 144, 3. </note>'
        '<note type="footnote"> 2 Magnus es-tua <hi rend="italic">minio depicta S</hi></note>'
        '<pb n="2"/>uirtus tua.</p></div></div>'
    )
    assert _extract(body) == [
        ("stoa9999.stoa001.1", "LIBER PRIMVS."),
        ("stoa9999.stoa001.1.1", "Magnus es, domine, et laudabilis ualde: magna uirtus tua."),
    ]


def test_bare_verse_lines_are_units_without_their_printed_numbers() -> None:
    body = (
        '<head><title type="main">DE IONA PROPHETA.</title></head>'
        '<l n="1"><milestone unit="para"/>Post Sodomum et Gomorum</l>'
        '<l n="40">40 conatusque animae tu nisi, Christe, regas,</l>'
    )
    assert _extract(body) == [
        ("stoa9999.stoa001", "DE IONA PROPHETA."),
        ("stoa9999.stoa001.1", "Post Sodomum et Gomorum"),
        ("stoa9999.stoa001.40", "conatusque animae tu nisi, Christe, regas,"),
    ]


def _write_tei(tmp_path: Path, author_id: str, body: str) -> Path:
    path = tmp_path / "data" / author_id / "stoa001" / f"{author_id}.stoa001.opp-lat1.xml"
    path.parent.mkdir(parents=True)
    path.write_text(
        f'<TEI xmlns="{_TEI}"><teiHeader><fileDesc>'
        "<titleStmt><title>Epigramma</title><author>Paul, the Apostle</author></titleStmt>"
        '<publicationStmt><availability><licence target="https://creativecommons.org/licenses/by-sa/4.0/">'
        "CC BY-SA</licence></availability></publicationStmt>"
        "<sourceDesc><listBibl><biblStruct><monogr><editor><persName><name>Karl Schenkl</name>"
        "</persName></editor><imprint><date>1888</date></imprint></monogr>"
        '<series><biblScope unit="volume">16.1</biblScope></series>'
        '<ref target="https://archive.org/details/x">IA</ref></biblStruct></listBibl></sourceDesc>'
        f'</fileDesc></teiHeader><text><body><div type="edition" xml:lang="lat" '
        f'n="urn:cts:latinLit:{author_id}.stoa001.opp-lat1">{body}</div></body></text></TEI>',
        encoding="utf-8",
    )
    return path


def test_work_record_from_the_header(tmp_path: Path) -> None:
    path = _write_tei(tmp_path, "stoa0222a", '<div type="textpart" n="1"><p>Iam dudum</p></div>')
    work, paragraphs = parse_file(path, "Paul, the Apostle, Saint")
    assert work.work_id == "csel/stoa0222a/stoa001/opp-lat1"
    assert work.author == "Paulinus of Béziers"  # the catalogue's "Paul" is overridden
    assert work.license == "cc-by-sa-4.0"
    assert work.edition == ("CSEL 16.1, ed. Karl Schenkl (1888); OGL csel-dev opp-lat1; "
                            "scan: https://archive.org/details/x")
    assert paragraphs == [{"ref": "stoa0222a.stoa001.1", "text": "Iam dudum"}]


def test_text_group_after_the_period_is_skipped(tmp_path: Path) -> None:
    path = _write_tei(tmp_path, "stoa0227b", '<div type="textpart" n="1"><p>Incipit</p></div>')
    assert parse_file(path, "Petrus Diaconus") is None
