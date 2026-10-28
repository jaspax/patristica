"""Digital Syriac Corpus ingestor (#79): sections, page units, verse lines, repeated books."""

from __future__ import annotations

from pathlib import Path

from scripts.ingest.dsc import WORKS, _section_ref, parse_file

_TEI = "http://www.tei-c.org/ns/1.0"


def _file(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "1.xml"
    path.write_text(f'<TEI xmlns="{_TEI}"><text><body>{body}</body></text></TEI>', encoding="utf-8")
    return path


def _units(tmp_path: Path, body: str, prefix: str) -> list[tuple[str, str]]:
    return [(u["ref"], u["text"]) for u in parse_file(_file(tmp_path, body), prefix)]


def test_sections_with_title_and_melody(tmp_path: Path) -> None:
    body = (
        '<div type="title" n="0"><ab>ܬܚܘܝܬܐ</ab></div>'
        '<div type="melody"><ab>ܩܠܐ</ab></div>'
        '<div type="section" n="1"><head type="editorial">1</head><p>ܐ</p><p>ܒ</p></div>'
        '<div type="section" n="2"><l>ܓ</l><l>ܕ</l><note>n</note></div>'
    )
    assert _units(tmp_path, body, "Aphr.Dem.1") == [
        ("Aphr.Dem.1", "ܬܚܘܝܬܐ"),
        ("Aphr.Dem.1.melody.1", "ܩܠܐ"),
        ("Aphr.Dem.1.1", "ܐ ܒ"),  # a section's paragraphs are one unit
        ("Aphr.Dem.1.2", "ܓ / ܕ"),  # its lines too
    ]


def test_a_file_without_sections_is_cut_at_its_pages(tmp_path: Path) -> None:
    body = '<div type="body"><pb n="5"/><p>ܐ ܒ<pb n="6"/>ܓ</p><ab>ܕ<pb n="7"/>ܗ</ab></div>'
    assert _units(tmp_path, body, "Addai") == [
        ("Addai.5", "ܐ ܒ"), ("Addai.6", "ܓ ܕ"), ("Addai.7", "ܗ"),
    ]


def test_a_repeated_book_is_read_once(tmp_path: Path) -> None:
    book = '<div type="book" n="8"><div type="section" n="8.1"><p>ܐ</p></div></div>'
    assert _units(tmp_path, book + book, "EusHE.8") == [("EusHE.8.1", "ܐ")]


def test_section_refs() -> None:
    assert _section_ref("Aphr.Dem.1", "3") == "Aphr.Dem.1.3"
    assert _section_ref("EusHE.1", "1.13") == "EusHE.1.13"


def test_works_have_unique_slugs_and_files() -> None:
    files = [n for w in WORKS for n, _ in w.files]
    assert len(files) == len(set(files))
    assert len({w.slug for w in WORKS}) == len(WORKS)
    assert sum(1 for w in WORKS if w.slug == "ephrem-carmina-nisibena" for _ in w.files) == 73
