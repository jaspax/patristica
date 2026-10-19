"""Tests for the keyword index (#86): patristica.keyword, its loading in
scripts.build_index, and phrase search (api/keyword.py).

The database tests need ``PATRISTICA_TEST_DATABASE_URL`` (``conftest.pg_url``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from patristica import keyword as kw

# --- folding --------------------------------------------------------------


def test_index_text_is_folded_and_padded() -> None:
    assert kw.index_text("Ἐν ἀρχῇ ἦν ὁ λόγος.") == " εν αρχη ην ο λογοσ "
    assert kw.index_text("") == "  "


@pytest.mark.parametrize("phrase, pattern", [
    ("In the Beginning,", "% in the beginning %"),
    ("“ἐν  ἀρχῇ”", "% εν αρχη %"),
    ("vita æterna", "% uita eterna %"),
    ("100% _sure_", "% 100 sure %"),  # LIKE wildcards in the input fold to spaces
])
def test_phrase_pattern(phrase: str, pattern: str) -> None:
    assert kw.phrase_pattern(phrase) == pattern


@pytest.mark.parametrize("phrase", ["", "  ", "a b", "!!", "ὁ"])
def test_phrase_pattern_rejects_short_phrases(phrase: str) -> None:
    with pytest.raises(kw.PhraseError):
        kw.phrase_pattern(phrase)


def test_match_spans() -> None:
    text = "In the beginning God created the heaven and the earth."
    spans = kw.match_spans(text, ["THE heaven", "the earth", "and the"])
    assert [text[a:b] for a, b in spans] == ["the heaven", "and the earth"]  # overlaps merge
    assert kw.match_spans(text, ["the heave"]) == []  # whole words only
    assert kw.match_spans("et et et", ["et et"]) == [(0, 8)]
    # Pointed Hebrew: the span keeps the points after the last letter.
    hebrew = "כָּל־הָאָ֖רֶץ וְכָל"
    assert [hebrew[a:b] for a, b in kw.match_spans(hebrew, ["כל הארץ"])] == ["כָּל־הָאָ֖רֶץ"]
    # Latin spellings fold both ways.
    latin = "Dominus michi adiutor"
    assert [latin[a:b] for a, b in kw.match_spans(latin, ["mihi adjutor"])] == ["michi adiutor"]


# --- loading --------------------------------------------------------------

psycopg = pytest.importorskip("psycopg")
pytest.importorskip("numpy")

from api import keyword as api_kw  # noqa: E402
from api.search import Filters  # noqa: E402
from scripts import build_index  # noqa: E402
from tests import index_fixture as fx  # noqa: E402


@pytest.fixture
def corpus(pg_url: str, tmp_path: Path):
    """(connection, normalized dir, translations dir, embeddings dir) after a full load."""
    dirs = fx.write_corpus(tmp_path)
    with psycopg.connect(pg_url, autocommit=True) as conn:
        build_index.run(conn, *dirs, maintenance_work_mem="64MB")
        yield conn, *dirs


def _folded(conn) -> dict[str, str | None]:
    return dict(conn.execute("SELECT chunk_id, text_folded FROM chunks"))


def test_load_folds_every_chunk(corpus) -> None:
    conn, *_ = corpus
    folded = _folded(conn)
    # The Latin spelling rules (v → u) apply to every language, here and in queries.
    assert folded["kjv/gen#Gen.1.1"] == " in the beginning god created the heauen and the earth "
    assert folded["oshb/gen#Gen.1.1"] == " בראשית ברא אלהים את השמים ואת הארץ "
    assert all(v is not None for v in folded.values())
    assert build_index.has_index(conn, build_index.TRGM_INDEX)
    assert conn.execute("SELECT value FROM index_meta WHERE key = 'fold_version'"
                        ).fetchone() == (str(kw.FOLD_VERSION),)


def test_backfill_folds_in_place(corpus) -> None:
    """A database loaded before text_folded existed is folded without reloading works."""
    conn, *dirs = corpus
    expected = _folded(conn)
    conn.execute(f"DROP INDEX {build_index.TRGM_INDEX}")
    conn.execute("UPDATE chunks SET text_folded = NULL")
    conn.execute("DELETE FROM index_meta")
    vectors = conn.execute("SELECT count(*) FROM chunk_vectors").fetchone()[0]

    # A partial run folds only the works it checked; the rest stay NULL, to do.
    stats = build_index.run(conn, *dirs, sources=["kjv"])
    assert (stats.loaded, stats.folded) == (0, 2)
    folded = _folded(conn)
    assert folded["kjv/gen#Gen.1.1"] == expected["kjv/gen#Gen.1.1"]
    assert folded["oshb/gen#Gen.1.1"] is None
    assert conn.execute("SELECT value FROM index_meta WHERE key = 'fold_version'"
                        ).fetchone() == (str(kw.FOLD_VERSION),)

    stats = build_index.run(conn, *dirs)
    assert (stats.loaded, stats.folded) == (0, 3)
    assert _folded(conn) == expected
    assert build_index.has_index(conn, build_index.TRGM_INDEX)
    assert conn.execute("SELECT count(*) FROM chunk_vectors").fetchone()[0] == vectors
    assert build_index.run(conn, *dirs).folded == 0


def test_fold_upgrade_through_partial_runs(corpus, monkeypatch: pytest.MonkeyPatch) -> None:
    """After a FOLD_VERSION bump, runs over disjoint sources finish the upgrade together."""
    conn, *dirs = corpus
    monkeypatch.setattr(build_index, "FOLD_VERSION", kw.FOLD_VERSION + 1)
    assert build_index.run(conn, *dirs, sources=["kjv"]).folded == 2
    assert build_index.run(conn, *dirs, sources=["oshb"]).folded == 1  # kjv is not cleared again
    assert build_index.run(conn, *dirs, sources=["pta"]).folded == 2
    assert all(v is not None for v in _folded(conn).values())
    assert build_index.run(conn, *dirs).folded == 0
    assert build_index.has_index(conn, build_index.TRGM_INDEX)


def test_interrupted_upgrade_keeps_its_progress(corpus, monkeypatch: pytest.MonkeyPatch) -> None:
    conn, *dirs = corpus
    monkeypatch.setattr(build_index, "FOLD_VERSION", kw.FOLD_VERSION + 1)
    real = build_index.fold_missing

    def interrupted(conn, paths, mem):  # fold the KJV, then "crash"
        real(conn, {w: p for w, p in paths.items() if w.startswith("kjv/")}, mem)
        raise KeyboardInterrupt

    monkeypatch.setattr(build_index, "fold_missing", interrupted)
    with pytest.raises(KeyboardInterrupt):
        build_index.run(conn, *dirs)
    monkeypatch.setattr(build_index, "fold_missing", real)
    assert build_index.run(conn, *dirs).folded == 3  # only what the first run didn't do


def test_new_fold_version_refolds_everything(corpus, monkeypatch: pytest.MonkeyPatch) -> None:
    conn, *dirs = corpus
    monkeypatch.setattr(build_index, "FOLD_VERSION", kw.FOLD_VERSION + 1)
    assert build_index.run(conn, *dirs).folded == 5
    assert conn.execute("SELECT value FROM index_meta WHERE key = 'fold_version'"
                        ).fetchone() == (str(kw.FOLD_VERSION + 1),)


def test_index_handling_stays_in_its_schema(corpus, pg_url: str) -> None:
    """Another schema on the search path with the same index names is left alone."""
    from psycopg.conninfo import conninfo_to_dict, make_conninfo

    conn, *dirs = corpus
    schema = conn.execute("SELECT current_schema()").fetchone()[0]
    decoy = f"{schema}_decoy"
    conn.execute(f"CREATE SCHEMA {decoy}")
    try:
        conn.execute(f"CREATE TABLE {decoy}.chunks (text_folded text)")
        conn.execute(f"CREATE INDEX {build_index.TRGM_INDEX} ON {decoy}.chunks (text_folded)")
        options = conninfo_to_dict(pg_url)["options"].replace(
            f"search_path={schema},", f"search_path={schema},{decoy},")
        with psycopg.connect(make_conninfo(pg_url, options=options), autocommit=True) as other:
            build_index.drop_index(other, build_index.TRGM_INDEX)
            assert not build_index.has_index(other, build_index.TRGM_INDEX)
            build_index.drop_index(other, build_index.TRGM_INDEX)  # nothing left to drop here
            build_index.run(other, *dirs, maintenance_work_mem="64MB")
            assert build_index.has_index(other, build_index.TRGM_INDEX)
        assert conn.execute("SELECT count(*) FROM pg_indexes WHERE schemaname = %s",
                            (decoy,)).fetchone() == (1,)
    finally:
        conn.execute(f"DROP SCHEMA {decoy} CASCADE")


# --- phrase search --------------------------------------------------------


def _search(conn, *phrases: str, filters: Filters | None = None, limit: int = 20,
            offset: int = 0) -> tuple[list[str], int | None]:
    where, params = (filters or Filters()).sql()
    rows, total = api_kw.phrase_search(conn, list(phrases), where, params, limit, offset)
    return [chunk_id for chunk_id, _ in rows], total


def test_phrase_matches_folded_whole_words(corpus) -> None:
    conn, *_ = corpus
    assert _search(conn, "In the beginning") == (["kjv/gen#Gen.1.1"], 1)
    assert _search(conn, "IN THE BEGINNING, GOD") == (["kjv/gen#Gen.1.1"], 1)
    # Unpointed Hebrew finds the pointed text.
    assert _search(conn, "בראשית ברא") == (["oshb/gen#Gen.1.1"], 1)
    # Whole words only.
    assert _search(conn, "beginnin") == ([], None)
    assert _search(conn, "the heave") == ([], None)
    # Unpublishable works are not in the index at all.
    assert _search(conn, "ܫܘܒܚܐ ܠܐܠܗܐ") == ([], None)


def test_every_phrase_must_match(corpus) -> None:
    conn, *_ = corpus
    assert _search(conn, "in the beginning", "the earth") == (["kjv/gen#Gen.1.1"], 1)
    assert _search(conn, "in the beginning", "without form") == ([], None)


def test_filters_and_paging(corpus) -> None:
    conn, *_ = corpus
    assert _search(conn, "the earth") == (["kjv/gen#Gen.1.1", "kjv/gen#Gen.1.2"], 2)
    assert _search(conn, "the earth", limit=1, offset=1) == (["kjv/gen#Gen.1.2"], 2)
    assert _search(conn, "the earth", offset=2) == ([], None)
    assert _search(conn, "the earth", filters=Filters(language=["hbo"])) == ([], None)
    assert _search(conn, "the earth", filters=Filters(date_from=0)) == ([], None)


def test_scripture_first_then_earliest(corpus) -> None:
    conn, *_ = corpus
    # Two patristic chunks quoting Genesis, one older than the Bible's date estimate.
    conn.execute("INSERT INTO works (work_id, source_id, title, date_range, date_confidence, "
                 "genre, language, license, path, content_sha) VALUES "
                 "('pta/old', 'pta', 'Old', '[-1000,-1000]', 'approximate', 'patristic', 'eng', "
                 "'cc-by-4.0', 'x', 'x'), "
                 "('pta/new', 'pta', 'New', '[400,400]', 'approximate', 'patristic', 'eng', "
                 "'cc-by-4.0', 'x', 'x'), "
                 "('pta/undated', 'pta', 'Undated', NULL, 'uncertain', 'patristic', 'eng', "
                 "'cc-by-4.0', 'x', 'x')")
    for work_id in ("pta/new", "pta/undated", "pta/old"):
        conn.execute("INSERT INTO chunks (chunk_id, work_id, canonical_ref, chunk_index, "
                     "language, text, date_confidence, out_of_period, text_folded) VALUES "
                     "(%s, %s, '1', 0, 'eng', 'x', 'uncertain', false, %s)",
                     (f"{work_id}#1", work_id, kw.index_text("as it is written: the earth")))
    ids, total = _search(conn, "the earth")
    assert ids == ["kjv/gen#Gen.1.1", "kjv/gen#Gen.1.2", "pta/old#1", "pta/new#1",
                   "pta/undated#1"]
    assert total == 5


def test_phrase_search_uses_the_trigram_index(corpus) -> None:
    conn, *_ = corpus
    with conn.transaction():
        conn.execute("SET LOCAL enable_seqscan = off")
        plan = "\n".join(r[0] for r in conn.execute(
            "EXPLAIN SELECT chunk_id FROM chunks WHERE text_folded LIKE %s",
            (kw.phrase_pattern("in the beginning"),), prepare=False))
    assert build_index.TRGM_INDEX in plan


def test_short_and_broad_phrases(corpus, monkeypatch: pytest.MonkeyPatch) -> None:
    conn, *_ = corpus
    with pytest.raises(kw.PhraseError):
        _search(conn, "in")
    with pytest.raises(ValueError):
        _search(conn)

    class Canceling:
        def transaction(self):
            return conn.transaction()

        def execute(self, sql, params=None, prepare=None):
            if "statement_timeout" in sql:
                return conn.execute(sql, params)
            raise psycopg.errors.QueryCanceled("canceling statement due to statement timeout")

    where, params = Filters().sql()
    with pytest.raises(api_kw.PhraseTooBroad, match="too common"):
        api_kw.phrase_search(Canceling(), ["et dixit"], where, params, 20)
