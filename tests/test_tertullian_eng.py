"""Tests for the tertullian.org English translations (#347): ``scripts.ingest._tertullian_org``
and ``scripts.ingest.tertullian_eng``, on inline HTML (no network)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ingest import tertullian_eng as T
from scripts.ingest._tertullian_org import CACHE_DIR, decode

REPO = Path(__file__).resolve().parents[1]

_NAV = ('<p align="center"><a href="x.htm"><img SRC="mroonppv.gif" ALT="Previous Page"></a>'
        '<a href="index.htm"><img SRC="mroontoc.gif" ALT="Table Of Contents"></a></p>')
_FOOT = ('<p align="left" class="small">This text was transcribed by Roger Pearse, 2005.  All '
         'material on this page is in the public domain - copy freely.</p>')

PAGE = f"""<html><head><title>Test</title></head><body>
{_NAV}
<p align="center"><b>Somebody, Some Work (1900) Book 1</b></p>
<hr>
<p align="center">[Translated by A. Translator]</p>
<p><a href="#C1">CHAPTER 1. Of things</a></p>
<hr>
<h3 align="center">BOOK I.</h3>
<p class="smallish">This letter was written in a hurry.</p>
<p>First paragraph of the text,<A HREF="#1"><SUP>1</SUP></A> going on
<A NAME="p8"><SPAN CLASS=pb>|8</SPAN></A> across a page.</p>
<blockquote><p><b>CHAPTER <a name="C1"></a>I.</b></p></blockquote>
<p>Second paragraph.<a href="#_ftn2" name="_ftnref2">[2]</a> End.</p>
<p>p. 12 a</p>
<p>Third paragraph with a [bracketed remark] in it.</p>
<p>Ein deutscher Satz und so weiter.</p>
<hr>
<p><A NAME="#1"></A>1.&nbsp;A note on the first paragraph.</p>
<p><a href="#_ftnref2" name="_ftn2">[2]</a> The second note.</p>
<hr>
{_NAV}
{_FOOT}
</body></html>"""


@pytest.fixture()
def raw_dir(tmp_path: Path) -> Path:
    cache = tmp_path / CACHE_DIR
    cache.mkdir(parents=True)
    (cache / "page1.htm").write_text(PAGE, encoding="utf-8")
    return tmp_path


def _text(**kw) -> T.Text:
    spec = kw.pop("spec", T.PageSpec("page1.htm", "1"))
    return T.Text("some-work", "Some Work", "Origen", "Ed.", "first1k/x", "SW", (spec,), **kw)


def _units(raw_dir: Path, **kw) -> list[tuple[str, T.Unit]]:
    from scripts.ingest._common import offline_mode
    with offline_mode():
        return T.text_units(_text(**kw), raw_dir)


def _source(u: T.Unit) -> str:
    text = u.text
    for s, e, _ in sorted(u.spans, reverse=True):
        text = text[:s] + text[e:]
    return " ".join(text.split())


def test_largest_segment_notes_in_place_and_layout_dropped(raw_dir: Path) -> None:
    units = _units(raw_dir)
    texts = [u.text for _, u in units]
    assert texts[0] == "BOOK I."
    assert units[0][1].spans == [[0, 7, "heading"]]
    # the small-type introduction is a whole-unit note
    assert units[1][1].spans == [[0, len(texts[1]), "note"]]
    first = units[2][1]
    assert first.text.startswith("First paragraph of the text, [A note on the first paragraph.]")
    assert _source(first) == "First paragraph of the text, going on across a page."
    assert "|8" not in first.text
    # bold chapter title: heading
    assert units[3][1].editorial_only
    second = units[4][1]
    assert _source(second) == "Second paragraph. End."
    assert "[The second note.]" in second.text
    # the page reference line, the notes and the footer are gone
    assert not any("p. 12" in t or "public domain" in t for t in texts)
    assert not any(t.startswith("1. A note") or "The second note." == t for t in texts)
    assert [r for r, _ in units][:2] == ["SW.1.1", "SW.1.2"]


def test_contents_segment_is_skipped_unless_asked(raw_dir: Path) -> None:
    assert not any("CHAPTER 1. Of things" in u.text for _, u in _units(raw_dir))
    units = _units(raw_dir, spec=T.PageSpec("page1.htm", "1", segments=(1, 2)))
    toc = [u for _, u in units if u.text.startswith("CHAPTER 1. Of things")]
    assert toc and toc[0].editorial_only
    # the translator's credit line is dropped (it is in `edition`)
    assert not any("Translated by" in u.text for _, u in units)


def test_start_stop_strip_bracket_notes_and_language(raw_dir: Path) -> None:
    units = _units(raw_dir, spec=T.PageSpec("page1.htm", start=r"^Second", stop=r"^Ein "),
                   bracket_notes=True, strip=(r"\bEnd\.",))
    refs = [r for r, _ in units]
    assert refs == ["SW.1", "SW.2"]
    assert units[0][1].text.startswith("Second paragraph.")
    assert "End." not in units[0][1].text
    third = units[1][1]
    assert _source(third) == "Third paragraph with a in it."
    units = _units(raw_dir, english_only=True)
    assert not any(u.text.startswith("Ein deutscher") for _, u in units)


def test_missing_start_raises(raw_dir: Path) -> None:
    with pytest.raises(T.TertullianParseError):
        _units(raw_dir, spec=T.PageSpec("page1.htm", start=r"^Nowhere"))


def test_decode_falls_back_to_cp1252() -> None:
    assert decode("caf\xe9 —".encode("utf-8")) == "caf\xe9 —"
    assert decode(b"caf\xe9 \x97") == "caf\xe9 —"


def test_work_record() -> None:
    w = T.work(_text())
    assert w.work_id == "tertullian-eng/some-work"
    assert w.language == "eng" and w.license == "public_domain"
    assert w.translation_of == "first1k/x"
    assert w.provenance_url == "https://www.tertullian.org/fathers/page1.htm"


def test_config_is_consistent() -> None:
    slugs = [t.slug for t in T.TEXTS]
    assert len(slugs) == len(set(slugs))
    for t in T.TEXTS:
        assert t.edition and t.pages
        files = [(p.file, p.section, p.start, p.stop) for p in t.pages]
        assert len(files) == len(set(files)), t.slug


def test_originals_exist_and_are_not_english() -> None:
    works = {}
    for line in (REPO / "data/normalized/_works.jsonl").read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)["work"]
        works[rec["work_id"]] = rec
    for t in T.TEXTS:
        orig = works.get(t.translation_of)
        assert orig is not None, (t.slug, t.translation_of)
        assert orig["language"] != "eng"
