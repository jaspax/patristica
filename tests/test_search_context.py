"""Search results with the units around them and an English version (api/context.py, #209).

The pure tests choose and assemble English versions; the database tests load
``tests/index_fixture`` (through the fixtures of ``test_search_api``) and add
versions to it.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("psycopg")

from api import context as ctx  # noqa: E402
from api import search as s  # noqa: E402
from tests import index_fixture as fx  # noqa: E402
from tests.test_search_api import _searcher, _toward, corpus_url  # noqa: E402, F401

# --- pure ----------------------------------------------------------------


def _unit(work_id: str, index: int, text: str, source_id: str = "src",
          translation_of: str | None = None) -> ctx.EnglishUnit:
    return ctx.EnglishUnit(work_id, index, f"R.{index}", text, source_id, None, translation_of)


def _hit(genre: str = "patristic") -> dict[str, Any]:
    return {"chunk_id": "w#R.1", "work_id": "w", "work": {"genre": genre}}


def test_english_version_prefers_the_kjv_for_scripture() -> None:
    units = {"w#R.1": [_unit("asv/gen", 1, "ASV", "asv"), _unit("kjv/gen", 1, "KJV", "kjv")]}
    assert ctx.english_version(_hit("scripture"), None, None, units)["work_id"] == "kjv/gen"
    # Elsewhere the KJV has no precedence: the work id decides.
    assert ctx.english_version(_hit(), None, None, units)["work_id"] == "asv/gen"


def test_english_version_prefers_a_translation_of_the_work() -> None:
    units = {"w#R.1": [_unit("a/other", 1, "Other"),
                       _unit("z/npnf", 1, "NPNF", translation_of="w")]}
    assert ctx.english_version(_hit(), None, None, units)["text"] == "NPNF"


def test_english_version_maps_neighbours_without_repeating_the_hit() -> None:
    # The English unit 5 renders both the hit and the unit before it; unit 6 the one after.
    units = {
        "w#R.0": [_unit("e", 4, "Four."), _unit("e", 5, "Five.")],
        "w#R.1": [_unit("e", 5, "Five.")],
        "w#R.2": [_unit("e", 6, "Six."), _unit("f", 9, "Elsewhere.")],
    }
    version = ctx.english_version(_hit(), "w#R.0", "w#R.2", units)
    assert (version["before"], version["text"], version["after"]) == ("Four.", "Five.", "Six.")
    assert (version["machine"], version["canonical_ref"]) == (False, "R.5")
    # No English unit for the hit itself: no linked version (the machine translation stays).
    assert ctx.english_version(_hit(), "w#R.0", "w#R.2", {"w#R.0": units["w#R.0"]}) is None


def test_long_english_context_is_cut_next_to_the_hit() -> None:
    long = "x" * (ctx.CONTEXT_CHARS + 50)
    assert ctx._clip_context(long, -1) == "…" + "x" * ctx.CONTEXT_CHARS
    assert ctx._clip_context(long, 1) == "x" * ctx.CONTEXT_CHARS + "…"


def test_heading_is_not_context() -> None:
    assert ctx._is_heading_of("Hom.3", "Hom.3.1")
    assert not ctx._is_heading_of("Hom.3.1", "Hom.3.2")
    assert not ctx._is_heading_of("Hom.3", "Hom.30.1")


# --- database --------------------------------------------------------------

LXX = [("Gen.1.1", "Ἐν ἀρχῇ ἐποίησεν ὁ θεὸς τὸν οὐρανὸν καὶ τὴν γῆν."),
       ("Gen.1.2", "ἡ δὲ γῆ ἦν ἀόρατος καὶ ἀκατασκεύαστος."),
       ("Gen.1.3", "καὶ εἶπεν ὁ θεός Γενηθήτω φῶς.")]
ASV = [("Gen.1.1", "In the beginning God created the heavens and the earth."),
       ("Gen.1.2", "And the earth was waste and void."),
       ("Gen.1.3", "And God said, Let there be light: and there was light.")]
KJV_GEN_1_3 = "And God said, Let there be light: and there was light."


def _insert(conn: Any, work_id: str, language: str, index: int, ref: str, text: str,
            group: str | None, embedding: str | None = None, *, genre: str = "scripture",
            translation_of: str | None = None) -> str:
    from patristica.keyword import index_text

    source_id = work_id.split("/")[0]
    conn.execute(
        "INSERT INTO works (work_id, source_id, title, date_range, date_confidence, genre, "
        "language, license, edition, translation_of, path, content_sha) VALUES (%s, %s, 'T', "
        "'[-900,-400]', 'approximate', %s, %s, 'public_domain', %s, %s, 'x', 'x') "
        "ON CONFLICT DO NOTHING", (work_id, source_id, genre, language, f"{source_id} ed.",
                                   translation_of))
    cid = fx.chunk_id(work_id, ref)
    conn.execute(
        "INSERT INTO chunks (chunk_id, work_id, canonical_ref, chunk_index, language, text, "
        "date_range, date_confidence, out_of_period, translation_group_id, text_folded) "
        "VALUES (%s, %s, %s, %s, %s, %s, '[-900,-400]', 'approximate', false, %s, %s)",
        (cid, work_id, ref, index, language, text, group, index_text(text)))
    if embedding is not None:
        conn.execute(
            "INSERT INTO chunk_vectors SELECT %s, 0, model_id, %s::halfvec, %s, %s, %s, "
            "%s, '{}', '[-900,-400]', false FROM embedding_models",
            (cid, embedding, work_id, source_id, language, genre))
    return cid


@pytest.fixture
def scripture(corpus_url: str):  # noqa: F811
    """The corpus with Gen 1:1-3 in the LXX and the ASV, and KJV Gen 1:3."""
    import psycopg

    void = fx.axis_of("kjv/gen", "Gen.1.2")
    with psycopg.connect(corpus_url, autocommit=True) as conn:
        # The loader left KJV Gen 1:2 out of a verse group: no other work had that verse yet.
        conn.execute("UPDATE chunks SET translation_group_id = 'Gen.1.2' "
                     "WHERE chunk_id = 'kjv/gen#Gen.1.2'")
        _insert(conn, "kjv/gen", "eng", 2, "Gen.1.3", KJV_GEN_1_3, "Gen.1.3")
        for i, (ref, text) in enumerate(LXX):
            # Gen 1:2 is the closest Greek verse to "void".
            _insert(conn, "lxx-rahlfs/gen", "grc", i, ref, text, ref,
                    _toward(void, 0.9 if ref == "Gen.1.2" else 0.1))
        for i, (ref, text) in enumerate(ASV):
            _insert(conn, "asv/gen", "eng", i, ref, text, ref)
    searcher = _searcher(corpus_url)
    try:
        yield searcher
    finally:
        searcher.pool.close()


def test_results_carry_the_units_around_them(scripture: s.Searcher) -> None:
    top = scripture.search("void", s.Filters(), limit=1)["results"][0]
    assert top["chunk_id"] == "kjv/gen#Gen.1.2"
    assert top["context"] == {
        "before": {"chunk_id": "kjv/gen#Gen.1.1", "canonical_ref": "Gen.1.1",
                   "text": "In the beginning God created the heaven and the earth."},
        "after": {"chunk_id": "kjv/gen#Gen.1.3", "canonical_ref": "Gen.1.3", "text": KJV_GEN_1_3},
    }
    assert top["translation"] is None  # English already


def test_scripture_gets_the_kjv_with_its_context(scripture: s.Searcher) -> None:
    top = scripture.search("void", s.Filters(language=["grc"]), limit=1)["results"][0]
    assert top["chunk_id"] == "lxx-rahlfs/gen#Gen.1.2"
    refs = [top["context"][k]["canonical_ref"] for k in ("before", "after")]
    assert refs == ["Gen.1.1", "Gen.1.3"]
    assert top["translation"] == {
        "language": "eng", "machine": False, "model": None,
        "text": "And the earth was without form, and void.",
        "before": "In the beginning God created the heaven and the earth.",
        "after": KJV_GEN_1_3,
        "work_id": "kjv/gen", "canonical_ref": "Gen.1.2",
        "source_label": "King James Version", "edition": "King James Version (1769)",
    }


def test_keyword_results_carry_context_too(scripture: s.Searcher) -> None:
    top = scripture.search('"ἀόρατος"', s.Filters())["results"][0]
    assert top["chunk_id"] == "lxx-rahlfs/gen#Gen.1.2"
    assert top["context"]["after"]["text"] == LXX[2][1]
    assert top["translation"]["work_id"] == "kjv/gen"


def test_linked_translation_replaces_the_machine_one(corpus_url: str) -> None:  # noqa: F811
    """An aligned English work (#179) that is a translation_of the hit's work wins."""
    import psycopg

    with psycopg.connect(corpus_url, autocommit=True) as conn:
        # One English unit renders both hymn lines; another English work renders line 1 too.
        _insert(conn, "npnf/hymns", "eng", 0, "Hymn.1", "Our faith is true; praise be.", None,
                genre="patristic", translation_of="pta/hymns")
        _insert(conn, "aaa/hymns", "eng", 0, "H.1", "Another rendering.", None, genre="patristic")
        conn.execute("INSERT INTO passage_groups VALUES ('pta/hymns#Hymn.1.1', 'h@0', 9), "
                     "('pta/hymns#Hymn.1.2', 'h@0', 9), ('npnf/hymns#Hymn.1', 'h@0', 9), "
                     "('aaa/hymns#H.1', 'h@0', 9)")
    searcher = _searcher(corpus_url)
    try:
        top = searcher.search("faith", s.Filters(), limit=1)["results"][0]
        assert top["chunk_id"] == "pta/hymns#Hymn.1.1"
        assert top["context"]["after"]["canonical_ref"] == "Hymn.1.2"
        tr = top["translation"]
        assert (tr["machine"], tr["work_id"], tr["text"]) == (
            False, "npnf/hymns", "Our faith is true; praise be.")
        # The unit after the hit is in the same English unit, so it isn't repeated.
        assert (tr["before"], tr["after"]) == (None, None)
    finally:
        searcher.pool.close()


def test_machine_translation_brings_its_neighbours(corpus_url: str) -> None:  # noqa: F811
    import psycopg

    with psycopg.connect(corpus_url, autocommit=True) as conn:
        conn.execute("INSERT INTO chunk_translations VALUES ('pta/hymns#Hymn.1.2', 'eng', 'A.', "
                     "'gpt-6.1-sol', 'v1', '2026-10-14')")
    searcher = _searcher(corpus_url)
    try:
        tr = searcher.search("faith", s.Filters(), limit=1)["results"][0]["translation"]
        assert (tr["machine"], tr["text"], tr["before"], tr["after"]) == (
            True, "Our faith is true and glorious.", None, "A.")
    finally:
        searcher.pool.close()
