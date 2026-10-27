"""Editorial material (#236): spans, source text, and their way through normalize
and the library export."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica import editorial
from patristica.editorial import EditorialError
from patristica.versify import split_text


def test_check_accepts_sorted_spans_and_rejects_bad_ones():
    text = "ⲁⲩⲱ […] ⲁϥ"
    assert editorial.check(text, [[4, 7, "lacuna"]]) == [(4, 7, "lacuna")]
    for bad in ([[4, 7, "lacunae"]],           # unknown kind
                [[4, 4, "lacuna"]],            # empty
                [[4, 99, "lacuna"]],           # past the end
                [[5, 7, "note"], [4, 6, "note"]],  # unsorted / overlapping
                [[4, 7]],                      # not [start, end, kind]
                [7],                           # not a list
                [[0, 1, []]],                  # unhashable kind
                [[True, 2, "note"]],           # bool offset
                "abc"):                        # not a list of spans
        with pytest.raises(EditorialError):
            editorial.check(text, bad, "w#1")


@pytest.mark.parametrize("text, spans, want", [
    ("a […] b", [(2, 5, "lacuna")], "a b"),
    ("a […]b", [(2, 5, "lacuna")], "a b"),
    ("a[…]b", [(1, 4, "lacuna")], "a b"),
    ("[…] a", [(0, 3, "lacuna")], "a"),
    ("a […]", [(2, 5, "lacuna")], "a"),
    ("a [x] [y] b", [(2, 5, "note"), (6, 9, "note")], "a b"),
    ("A Psalm.", [(0, 8, "title")], ""),
    ("a  b", [], "a  b"),  # no spans: unchanged, whitespace and all
    # Supplements stay in the source text; only their brackets go (owner, #236).
    ("ⲡⲁⲅⲅⲉ<ⲗⲟⲥ> ⲇⲉ", [(5, 10, "supplement")], "ⲡⲁⲅⲅⲉⲗⲟⲥ ⲇⲉ"),
    ("ⲥⲁϣϥⲉ <ⲛϣⲉ> ⲛⲣⲟⲙⲡⲉ", [(6, 11, "supplement")], "ⲥⲁϣϥⲉ ⲛϣⲉ ⲛⲣⲟⲙⲡⲉ"),
    ("ab cd", [(3, 5, "supplement")], "ab cd"),        # no brackets: unchanged
    ("<ab", [(0, 3, "supplement")], "ab"),             # cut by a derived verse
    ("a […] <b> c", [(2, 5, "lacuna"), (6, 9, "supplement")], "a b c"),
])
def test_strip(text: str, spans: list, want: str):
    assert editorial.strip(text, spans) == want


def test_source_text_is_the_text_without_spans():
    plain = {"text": "  ⲁⲩⲱ ⲁϥ "}
    assert editorial.source_text(plain) is plain["text"]   # untouched, so hashes don't move
    assert editorial.source_text({"text": "ⲁⲩⲱ […] ⲁϥ", "editorial": [[4, 7, "lacuna"]]}) \
        == "ⲁⲩⲱ ⲁϥ"


def test_unit_spans_follow_the_cleaned_text():
    raw = "  3. Hic [lacuna] est.  "
    text = "Hic [lacuna] est."     # stripped and without the repeated section number
    spans = [(9, 17, "lacuna")]
    assert raw[9:17] == "[lacuna]"
    moved = editorial.unit_spans(raw, text, spans, "w#3")
    assert moved == [(4, 12, "lacuna")] and text[4:12] == "[lacuna]"
    # A span in the cut prefix is dropped, one across the cut is clipped.
    assert editorial.unit_spans(raw, text, [(2, 4, "note"), (4, 8, "heading")], "w#3") \
        == [(0, 3, "heading")]
    with pytest.raises(EditorialError):
        editorial.unit_spans(raw, "something else", spans, "w#3")


def test_split_spans_divides_spans_between_derived_verses():
    text = "One two. [three four. five] six."
    pieces = ["One two.", "[three four.", "five] six."]
    out = editorial.split_spans(text, pieces, [(9, 27, "supplement")])
    assert out == [[], [(0, 12, "supplement")], [(0, 5, "supplement")]]
    assert [p[s:e] for p, spans in zip(pieces, out) for s, e, _ in spans] \
        == ["[three four.", "five]"]


def test_utf16_spans_count_astral_characters_twice():
    text = "𐌰𐌱 [...] 𐌲"   # Gothic: outside the BMP
    assert text[3:8] == "[...]"
    assert editorial.utf16_spans(text, [(3, 8, "lacuna")]) == [[5, 10, "lacuna"]]
    assert editorial.utf16_spans("ab [x]", [(3, 6, "note")]) == [[3, 6, "note"]]


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------

def _raw(units: list[dict], genre: str = "patristic", key: str = "paragraphs") -> dict:
    return {"work": {"work_id": "test/w", "source_id": "test", "title": "W", "author": None,
                     "genre": genre, "language": "eng", "license": "public_domain"},
            key: units}


def _normalize(tmp_path: Path, record: dict) -> list[dict]:
    from scripts.normalize import _normalize_record

    raw = tmp_path / "raw" / "test" / "w.json"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(json.dumps(record), encoding="utf-8")
    out = tmp_path / "normalized"
    _normalize_record(record, raw, out)
    return json.loads((out / "test" / "w.json").read_text(encoding="utf-8"))


def test_normalize_carries_spans_and_leaves_unmarked_chunks_alone(tmp_path: Path):
    text = " A heading added by the editor. The text itself. "
    chunks = _normalize(tmp_path, _raw([
        {"ref": "1", "text": text, "editorial": [[1, 31, "heading"]]},
        {"ref": "2", "text": "Nothing editorial here."},
    ]))
    assert chunks[0]["text"] == "A heading added by the editor. The text itself."
    assert chunks[0]["editorial"] == [[0, 30, "heading"]]
    assert editorial.source_text(chunks[0]) == "The text itself."
    assert "editorial" not in chunks[1]
    assert list(chunks[1]) == list(chunks[0])[:-1]   # the key is the only addition


def test_normalize_splits_spans_with_derived_verses(tmp_path: Path):
    sentence = "This sentence is about as long as a verse of English Scripture, give or take. "
    text = (sentence * 6 + "[…] " + sentence * 6).strip()
    gap = text.index("[…]")
    chunks = _normalize(tmp_path, _raw([{"ref": "1", "text": text,
                                         "editorial": [[gap, gap + 3, "lacuna"]]}]))
    # Split on the full text: marking never moves a derived verse.
    assert [c["text"] for c in chunks] == split_text(text, "eng")
    assert len(chunks) > 2
    marked = [c for c in chunks if "editorial" in c]
    assert len(marked) == 1
    (s, e, kind), = marked[0]["editorial"]
    assert marked[0]["text"][s:e] == "[…]" and kind == "lacuna"
    assert marked[0]["canonical_ref"].startswith("1.s")


def test_normalize_rejects_bad_spans(tmp_path: Path):
    with pytest.raises(EditorialError):
        _normalize(tmp_path, _raw([{"ref": "1", "text": "abc",
                                    "editorial": [[0, 2, "gloss"]]}]))


def test_scripture_verse_wholly_editorial(tmp_path: Path):
    chunks = _normalize(tmp_path, _raw(
        [{"ref": "Ps.3.0", "text": "A Psalm of David.", "editorial": [[0, 17, "title"]]},
         {"ref": "Ps.3.1", "text": "Lord, how are they increased that trouble me!"}],
        genre="scripture", key="verses"))
    assert chunks[0]["editorial"] == [[0, 17, "title"]]
    assert editorial.source_text(chunks[0]) == ""
    assert "editorial" not in chunks[1]


# ---------------------------------------------------------------------------
# library export
# ---------------------------------------------------------------------------

def test_export_writes_utf16_spans_by_ref_suffix(tmp_path: Path):
    from patristica.models import Work
    from scripts.export_library import load_chunks, slim_work

    work = Work(work_id="test/w", source_id="test", title="W", genre="patristic",
                language="got", license="public_domain")
    base = {"work_id": "test/w", "language": "got", "date_confidence": "uncertain",
            "out_of_period": False}
    path = tmp_path / "w.json"
    path.write_text(json.dumps([
        {**base, "chunk_id": "test/w#W.1", "canonical_ref": "W.1", "chunk_index": 0,
         "text": "𐌰𐌱 [...] 𐌲", "editorial": [[3, 8, "lacuna"]]},
        {**base, "chunk_id": "test/w#W.2", "canonical_ref": "W.2", "chunk_index": 1,
         "text": "𐌲𐌳"},
    ]), encoding="utf-8")
    chunks, marks = load_chunks(path)
    record = slim_work(work, chunks, marks)
    assert record["editorial"] == {"1": [[5, 10, "lacuna"]]}
    assert record["chunks"] == [["1", "𐌰𐌱 [...] 𐌲"], ["2", "𐌲𐌳"]]
    # A work without editorial material has no key at all.
    assert "editorial" not in slim_work(work, chunks, {})
