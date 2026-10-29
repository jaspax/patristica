"""First1KGreek's English translations (#343): units per section, editorial spans, metadata."""

from __future__ import annotations

import json
from pathlib import Path

from lxml import etree

from patristica import editorial
from scripts.ingest.first1k_eng import _extract_units, ingest

_TEI_NS = "http://www.tei-c.org/ns/1.0"


def _translation(body: str) -> etree._Element:
    return etree.fromstring(
        f'<div xmlns="{_TEI_NS}" type="translation" '
        f'n="urn:cts:greekLit:tlg9999.tlg001.1st1K-eng1" xml:lang="eng">{body}</div>')


def _units(body: str) -> list[dict]:
    result = _extract_units(_translation(body), "tlg9999.tlg001")
    assert result.problems == []
    for unit in result.units:  # every span list is valid for its text
        editorial.check(unit["text"], unit.get("editorial", []), unit["ref"])
    return result.units


def _marked(unit: dict) -> list[tuple[str, str]]:
    return [(kind, unit["text"][s:e]) for s, e, kind in unit.get("editorial", [])]


def _section(n: int | str, inner: str) -> str:
    return f'<div type="textpart" subtype="section" n="{n}">{inner}</div>'


def test_title_is_a_heading_record_and_sections_are_units() -> None:
    units = _units(
        "<head><title>A TREATISE ON THE GIANTS.</title></head>"
        "<ab><title type='sub'>PART I.</title></ab>"
        + _section(1, '<p><milestone unit="chapter" n="1"/> Of other   lawgivers,</p>')
        + _section(2, "<p>But Moses</p><p>rejecting both.</p>"))
    assert [(u["ref"], u["text"]) for u in units] == [
        ("tlg9999.tlg001", "A TREATISE ON THE GIANTS. PART I."),
        ("tlg9999.tlg001.1", "Of other lawgivers,"),
        ("tlg9999.tlg001.2", "But Moses rejecting both."),  # one unit per section
    ]
    assert _marked(units[0]) == [("title", "A TREATISE ON THE GIANTS. PART I.")]
    assert "editorial" not in units[1]


def test_book_heads_and_heads_inside_a_section() -> None:
    units = _units(
        '<div type="textpart" subtype="book" n="2"><head>BOOK II.</head>'
        + _section(1, '<milestone unit="chapter" n="12"/><head>THE FIRST FESTIVAL.</head><p>The law</p>')
        + "</div>")
    assert [u["ref"] for u in units] == ["tlg9999.tlg001.2", "tlg9999.tlg001.2.1"]
    assert _marked(units[0]) == [("title", "BOOK II.")]
    assert units[1]["text"] == "THE FIRST FESTIVAL. The law"
    assert _marked(units[1]) == [("heading", "THE FIRST FESTIVAL.")]
    assert editorial.source_text(units[1]) == "The law"


def test_notes_stay_in_brackets_and_repeats_are_left_out() -> None:
    units = _units(
        _section(1, '<p>philosophy,<note resp="Yonge" n="7.1">Genesis iv. 2. </note> and who'
                    '<note n="7.1">Genesis iv. 2.</note></p>')
        + _section(2, '<p>it <note n="7.1">Genesis iv. 2.</note>was<note n="7.2"> Ibid.</note></p>'))
    assert units[0]["text"] == "philosophy, [Genesis iv. 2.] and who"
    assert _marked(units[0]) == [("note", "[Genesis iv. 2.]")]
    assert editorial.source_text(units[0]) == "philosophy, and who"
    assert units[1]["text"] == "it was [Ibid.]"  # 7.1 repeated after its page
    assert editorial.source_text(units[1]) == "it was"


def test_note_with_verse_lines_and_empty_unclear() -> None:
    units = _units(_section(
        1, "<p>Tantalus,<note><p>told in <cit><bibl>Od. xi.</bibl> <quote><l>καὶ μὴν</l> "
           "<l>ἑστεῶτʼ</l></quote></cit></p></note> and <unclear/> means</p>"))
    assert units[0]["text"] == "Tantalus, [told in Od. xi. καὶ μὴν / ἑστεῶτʼ] and […] means"
    assert [k for k, _ in _marked(units[0])] == ["note", "lacuna"]


def test_text_outside_a_section_is_a_problem() -> None:
    result = _extract_units(_translation("<p>stray</p>" + _section(1, "<p>x</p>")), "tlg9999.tlg001")
    assert result.problems


_HEADER = """<teiHeader><fileDesc><titleStmt><title>On the Giants</title>
<author>Philo Judaeus</author><editor role="translator">Charles Duke Yonge</editor></titleStmt>
<sourceDesc><listBibl><biblStruct><monogr><editor role="translator">Charles Duke Yonge</editor>
<title>The Works of Philo Judaeus</title><imprint><publisher>Henry G. Bohn</publisher>
<pubPlace>London</pubPlace><date>1854</date></imprint><biblScope unit="volume">1</biblScope>
</monogr></biblStruct></listBibl></sourceDesc></fileDesc></teiHeader>"""


def _repo(tmp_path: Path) -> Path:
    """A raw tree with one Greek work (as first1k writes it) and its English file."""
    raw = tmp_path / "raw"
    work_dir = raw / "first1k" / "data" / "tlg0018" / "tlg007"
    work_dir.mkdir(parents=True)
    (raw / "first1k" / "data" / "tlg0018" / "__cts__.xml").write_text(
        '<ti:textgroup xmlns:ti="http://chs.harvard.edu/xmlns/cts">'
        '<ti:groupname xml:lang="eng">Philo Judaeus</ti:groupname></ti:textgroup>')
    (work_dir / "tlg0018.tlg007.1st1K-eng1.xml").write_text(
        f'<TEI xmlns="{_TEI_NS}">{_HEADER}<text><body>'
        '<div type="translation" n="urn:cts:greekLit:tlg0018.tlg007.1st1K-eng1" xml:lang="eng">'
        "<head>A TREATISE ON THE GIANTS.</head>" + _section(1, "<p>And when men began</p>")
        + "</div></body></text></TEI>", encoding="utf-8")
    greek = raw / "first1k" / "tlg0018" / "tlg007"
    greek.mkdir(parents=True)
    (greek / "tlg0018.tlg007.1st1K-grc1.json").write_text("{}")
    return raw


def test_ingest_writes_an_english_work_linked_to_the_greek(tmp_path: Path) -> None:
    raw = _repo(tmp_path)
    works = ingest(raw, force=True)
    assert len(works) == 1
    work = works[0]
    assert work.work_id == "first1k-eng/tlg0018/tlg007/1st1K-eng1"
    assert work.translation_of == "first1k/tlg0018/tlg007/1st1K-grc1"
    assert (work.language, work.license, work.author, work.title) == (
        "eng", "cc-by-sa-4.0", "Philo Judaeus", "On the Giants")
    assert work.edition is not None
    assert work.edition.startswith(
        "tr. Charles Duke Yonge, The Works of Philo Judaeus, vol. 1 (London: Henry G. Bohn, 1854); "
        "Bohn's Ecclesiastical Library")
    out = raw / "first1k-eng" / "tlg0018" / "tlg007" / "tlg0018.tlg007.1st1K-eng1.json"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert [p["ref"] for p in data["paragraphs"]] == ["tlg0018.tlg007", "tlg0018.tlg007.1"]


def test_ingest_without_the_greek_work_logs_an_error(tmp_path: Path, caplog) -> None:
    raw = _repo(tmp_path)
    (raw / "first1k" / "tlg0018" / "tlg007" / "tlg0018.tlg007.1st1K-grc1.json").unlink()
    assert ingest(raw, force=True) == []
    assert any(r.levelname == "ERROR" for r in caplog.records)
