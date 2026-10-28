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


def test_several_titles_make_parts(tmp_path: Path) -> None:
    body = ('<div type="title"><ab>ܐ</ab></div><div type="section" n="1"><p>ܒ</p></div>'
            '<div type="title"><ab>ܓ</ab></div><div type="section" n="1"><p>ܕ</p></div>')
    assert _units(tmp_path, body, "T") == [
        ("T.1", "ܐ"), ("T.1.1", "ܒ"), ("T.2", "ܓ"), ("T.2.1", "ܕ")]


def test_english_and_footnotes_are_left_out(tmp_path: Path) -> None:
    body = ('<div type="title" xml:lang="en"><ab xml:lang="en">Nisibis I</ab></div>'
            '<div type="section" n="1"><p>ܐ</p><p xml:lang="en">a translation</p>'
            '<p rend="footnote text">M2 omits</p></div>')
    assert _units(tmp_path, body, "N") == [("N", "Nisibis I"), ("N.1", "ܐ")]


def test_a_number_used_again_later_gets_a_letter(tmp_path: Path) -> None:
    body = ('<div type="section" n="5"><p>ܐ</p></div><div type="section" n="6"><p>ܒ</p></div>'
            '<div type="section" n="5"><p>ܓ</p></div>')
    assert [r for r, _ in _units(tmp_path, body, "X")] == ["X.5", "X.6", "X.5b"]


def test_csv_works_are_well_formed() -> None:
    from scripts.ingest.dsc import load_csv_works
    works = load_csv_works()
    ids = [n for w in WORKS + works for n, _ in w.files]
    assert len(ids) == len(set(ids))
    assert len({w.slug for w in WORKS + works}) == len(WORKS) + len(works)
    assert all(w.genre in ("patristic", "apocrypha") for w in works)
    assert all(w.author or w.date_range for w in works)  # anonymous works carry their own dates
