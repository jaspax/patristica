"""Tests for scripts.build_index (#137).

The database tests need ``PATRISTICA_TEST_DATABASE_URL`` (see ``conftest.pg_url``)
and skip without it.
"""

from __future__ import annotations

import json
import os
import struct
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from patristica import embeddings as emb  # noqa: E402
from patristica import translations as tr  # noqa: E402
from scripts import build_index  # noqa: E402
from tests import index_fixture as fx  # noqa: E402


def test_pg_range() -> None:
    assert build_index.pg_range([-900, -400]) == "[-900,-400]"
    assert build_index.pg_range(None) is None


def test_copy_binary_vectors_layout() -> None:
    vecs = np.array([[1.0, -0.5]], dtype=np.float32)
    data = build_index.copy_binary_vectors([("w#A.1", 1, 3)], vecs)
    assert data.startswith(b"PGCOPY\n\xff\r\n\x00")
    body = data[19:-2]
    assert data[-2:] == struct.pack(">h", -1)
    assert body[:2] == struct.pack(">h", 4)  # fields
    assert body[2:6 + 5] == struct.pack(">i", 5) + b"w#A.1"
    rest = body[11:]
    assert rest[:12] == struct.pack(">ihih", 2, 1, 2, 3)
    # halfvec: byte length, dims, unused, then big-endian float16
    assert rest[12:20] == struct.pack(">ihh", 8, 2, 0)
    assert rest[20:] == np.array([1.0, -0.5], dtype=">f2").tobytes()


def _shard(rows: list[tuple[str, int, str]]) -> emb.WorkEmbeddings:
    return emb.WorkEmbeddings("w", "w.json", {fx.RUN.key: fx.RUN},
                              [emb.Row(c, k, s, fx.RUN.key) for c, k, s in rows],
                              np.zeros((len(rows), 4), dtype=np.float16))


def test_fresh_vectors_skips_stale_rows() -> None:
    chunks = [{"chunk_id": "w#1", "text": "current text"},
              {"chunk_id": "w#2", "text": "another text"}]
    shard = _shard([
        ("w#1", emb.KIND_TEXT, tr.text_sha("current text")),
        ("w#1", emb.KIND_TRANSLATION, tr.text_sha("english")),
        ("w#2", emb.KIND_TEXT, tr.text_sha("old text")),          # text changed
        ("w#2", emb.KIND_TRANSLATION, tr.text_sha("english 2")),  # no fresh translation
        ("w#3", emb.KIND_TEXT, tr.text_sha("gone")),              # chunk removed
    ])
    keep, stale = build_index.fresh_vectors(chunks, {"w#1": "english"}, shard)
    assert keep == [0, 1]
    assert stale == 3


def test_fresh_vectors_match_the_text_without_editorial_material() -> None:
    """Vectors embed a unit's source text (#236), so that is what they are checked against."""
    chunks = [{"chunk_id": "w#1", "text": "a […] b", "editorial": [[2, 5, "lacuna"]]},
              {"chunk_id": "w#2", "text": "c […] d", "editorial": [[2, 5, "lacuna"]]}]
    shard = _shard([
        ("w#1", emb.KIND_TEXT, tr.text_sha("a b")),
        ("w#2", emb.KIND_TEXT, tr.text_sha("c […] d")),   # embedded before the mark
    ])
    keep, stale = build_index.fresh_vectors(chunks, {}, shard)
    assert keep == [0] and stale == 1


def test_scripture_groups(tmp_path: Path) -> None:
    norm, _, _ = fx.write_corpus(tmp_path)
    groups = build_index.scripture_groups(build_index.load_works(norm), norm)
    # Gen.1.1 is in both Bibles; Gen.1.2 only in the KJV, and patristic refs never group.
    assert groups == {"kjv/gen": {"kjv/gen#Gen.1.1": "Gen.1.1"},
                      "oshb/gen": {"oshb/gen#Gen.1.1": "Gen.1.1"}}


def test_content_sha_tracks_inputs(tmp_path: Path) -> None:
    f = tmp_path / "a.json"
    f.write_text("[]")
    entry = {"path": "a.json", "work": {"work_id": "a"}}
    base = build_index.content_sha(entry, [f, tmp_path / "missing"])
    assert base == build_index.content_sha(entry, [f, tmp_path / "missing"])
    assert base != build_index.content_sha({**entry, "path": "b.json"}, [f, tmp_path / "missing"])
    f.write_text("[1]")
    assert base != build_index.content_sha(entry, [f, tmp_path / "missing"])


def test_content_sha_ignores_external_ids(tmp_path: Path) -> None:
    """Catalogue ids aren't loaded, so adding them must not reload a work (#178)."""
    entry = {"path": "a.json", "work": {"work_id": "a"}}
    with_ids = {"path": "a.json", "work": {"work_id": "a", "external_ids": ["CPG:5200"]}}
    assert build_index.content_sha(entry, []) == build_index.content_sha(with_ids, [])


def _format1_sha(entry: dict, files: list[Path], groups: dict[str, str]) -> str:
    """content_sha as it was before #186 (hash format 1), verbatim."""
    import hashlib

    h = hashlib.sha256()
    h.update(json.dumps({"loader": 1, "schema": 1, "dims": 512,
                         "entry": entry, "groups": sorted(groups.items())},
                        sort_keys=True, ensure_ascii=False).encode("utf-8"))
    for path in files:
        if not path.exists():
            h.update(b"\x00")
            continue
        h.update(b"\x01")
        h.update(path.read_bytes())
    return h.hexdigest()


def test_content_shas_reproduces_format_1(tmp_path: Path) -> None:
    f = tmp_path / "a.json"
    f.write_text('[{"x": "ä"}]')
    entry = {"path": "a.json", "work": {"work_id": "a", "title": "Ἀρχή"}}
    files = [f, tmp_path / "missing"]
    groups = {"a#Gen.1.2": "Gen.1.2", "a#Gen.1.1": "Gen.1.1"}
    sha, old = build_index.content_shas(entry, files, groups)
    assert sha == build_index.content_sha(entry, files)
    assert old == _format1_sha(entry, files, groups)
    assert build_index.content_shas(entry, files)[1] is None


@pytest.fixture
def no_racy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cache files just written (a test's files are always newer than RACY_SECONDS)."""
    monkeypatch.setattr(build_index, "RACY_SECONDS", -60.0)


def _unreadable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(hashes, path):
        raise AssertionError(f"{path} was read")
    monkeypatch.setattr(build_index, "_file_digest", fail)


def test_hash_cache_reuses_hashes_of_unchanged_files(tmp_path: Path, no_racy,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """#607: an unchanged work's hash comes from the cache without reading its files."""
    f = tmp_path / "a.json"
    f.write_text("[1]")
    files = (f, tmp_path / "missing")
    entry = {"path": "a.json", "work": {"work_id": "s/a"}}
    cache_path = tmp_path / "cache" / "hashes.json"
    cache = build_index.HashCache(cache_path)
    sha = build_index.cached_content_sha(cache, entry, files)
    assert sha == build_index.content_sha(entry, files)
    cache.save()

    with monkeypatch.context() as m:
        _unreadable(m)
        again = build_index.HashCache(cache_path)
        assert build_index.cached_content_sha(again, entry, files) == sha

    # A changed record, a new file and a rewritten one each miss.
    other = {**entry, "path": "b.json"}
    assert build_index.cached_content_sha(cache, other, files) \
        == build_index.content_sha(other, files)
    (tmp_path / "missing").write_text("x")
    assert build_index.cached_content_sha(cache, entry, files) \
        == build_index.content_sha(entry, files) != sha
    (tmp_path / "missing").unlink()
    st = f.stat()
    f.write_text("[2]")  # same size, and the old mtime put back: ctime still differs
    os.utime(f, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert build_index.cached_content_sha(cache, entry, files) \
        == build_index.content_sha(entry, files) != sha


def test_hash_cache_skips_racy_files(tmp_path: Path) -> None:
    """A file changed within RACY_SECONDS could change again with the same stat."""
    f = tmp_path / "a.json"
    f.write_text("[1]")
    cache = build_index.HashCache(tmp_path / "hashes.json")
    build_index.cached_content_sha(cache, {"path": "a.json", "work": {"work_id": "s/a"}}, (f,))
    assert cache.entries == {}
    cache.save()
    assert not (tmp_path / "hashes.json").exists()


def test_hash_cache_survives_a_bad_file(tmp_path: Path, caplog) -> None:
    bad = tmp_path / "hashes.json"
    bad.write_text("{not json")
    assert build_index.HashCache(bad).entries == {}
    assert "unreadable hash cache" in caplog.text
    bad.write_text(json.dumps({"version": 0, "works": {"s/a": {}}}))
    assert build_index.HashCache(bad).entries == {}  # another format: ignored
    assert build_index.HashCache(None).entries == {}


def test_run_with_hash_cache_reads_only_changed_files(pg_url: str, tmp_path: Path, no_racy,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    psycopg = pytest.importorskip("psycopg")
    norm, trans, store = fx.write_corpus(tmp_path)
    cache = tmp_path / "cache.json"
    with psycopg.connect(pg_url, autocommit=True) as conn:
        build_index.run(conn, norm, trans, store, maintenance_work_mem="64MB", hash_cache=cache)
        assert set(json.loads(cache.read_text())["works"]) == {"kjv/gen", "oshb/gen",
                                                               "pta/hymns"}
        with monkeypatch.context() as m:
            _unreadable(m)
            again = build_index.run(conn, norm, trans, store, hash_cache=cache)
            dry = build_index.run(conn, norm, trans, store, dry_run=True, hash_cache=cache)
        assert (again.loaded, again.unchanged) == (0, 3)
        assert (dry.loaded, dry.unchanged) == (0, 3)

        path = norm / fx.work_path("kjv/gen")
        chunks = json.loads(path.read_text())
        chunks[1]["text"] = "And the earth was without form."
        path.write_text(json.dumps(chunks))
        read: list[Path] = []
        real = build_index._file_digest
        monkeypatch.setattr(build_index, "_file_digest",
                            lambda hashes, p: (read.append(p), real(hashes, p)))
        changed = build_index.run(conn, norm, trans, store, hash_cache=cache)
        assert (changed.loaded, changed.unchanged) == (1, 2)
        assert path in read
        assert {p for p in read if p.suffix == ".json" and "normalized" in p.parts} == {path}


def test_group_changes() -> None:
    assert build_index.group_changes({"a": "G1", "b": "G2"}, {"a": "G1", "b": "G3", "c": "G4"}) \
        == {"b": "G2", "c": None}
    assert build_index.group_changes({"a": "G1"}, {}) == {"a": "G1"}


# --- database -------------------------------------------------------------


def _counts(conn) -> dict[str, int]:
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
            for t in ("works", "chunks", "chunk_translations", "chunk_vectors")}


def test_load_and_reload(pg_url: str, tmp_path: Path) -> None:
    psycopg = pytest.importorskip("psycopg")
    norm, trans, store = fx.write_corpus(tmp_path)
    with psycopg.connect(pg_url, autocommit=True) as conn:
        stats = build_index.run(conn, norm, trans, store, maintenance_work_mem="64MB")
        # The unlicensed work is never loaded; the 1-letter chunk has no vector.
        assert (stats.works, stats.loaded, stats.vectors) == (3, 3, 5)
        assert _counts(conn) == {"works": 3, "chunks": 5, "chunk_translations": 1,
                                 "chunk_vectors": 5}
        assert conn.execute("SELECT count(*) FROM authors").fetchone()[0] > 100
        assert build_index.hnsw_indexes(conn) == ["chunk_vectors_hnsw_m1"]
        assert conn.execute("SELECT name, dims, input_type FROM embedding_models").fetchall() \
            == [("voyage/voyage-4-large", 512, "document")]

        row = conn.execute(
            "SELECT v.language, v.genre, v.author_ids, v.date_range::text, v.source_id, "
            "vector_dims(v.embedding) FROM chunk_vectors v "
            "WHERE chunk_id = 'pta/hymns#Hymn.1.1' AND kind = 1").fetchone()
        assert row == ("syc", "patristic", ["ephrem-the-syrian"], "[350,374)", "pta", 512)
        assert conn.execute(
            "SELECT text, model FROM chunk_translations").fetchone() == (
            "Our faith is true and glorious.", "gpt-6.1-sol")
        assert conn.execute(
            "SELECT translation_group_id FROM chunks WHERE chunk_id = 'oshb/gen#Gen.1.1'"
        ).fetchone() == ("Gen.1.1",)
        # The vector is the stored direction, cut to 512 dims.
        axis = fx.axis_of("kjv/gen", "Gen.1.2")
        q = "[" + ",".join("1" if i == axis else "0" for i in range(512)) + "]"
        assert conn.execute(
            "SELECT chunk_id, round((embedding <=> %s::halfvec)::numeric, 3) FROM chunk_vectors "
            "ORDER BY embedding <=> %s::halfvec LIMIT 1", (q, q)).fetchone() == (
            "kjv/gen#Gen.1.2", 0)

        again = build_index.run(conn, norm, trans, store)
        assert (again.loaded, again.unchanged) == (0, 3)

        # Change one text: that work reloads, and its vector (now stale) is skipped.
        path = norm / fx.work_path("kjv/gen")
        chunks = json.loads(path.read_text())
        chunks[1]["text"] = "And the earth was without form."
        path.write_text(json.dumps(chunks))
        changed = build_index.run(conn, norm, trans, store)
        assert (changed.loaded, changed.unchanged, changed.stale_vectors) == (1, 2, 1)
        assert _counts(conn)["chunk_vectors"] == 4
        assert conn.execute("SELECT text FROM chunks WHERE chunk_id = 'kjv/gen#Gen.1.2'"
                            ).fetchone() == ("And the earth was without form.",)


def test_removed_and_excluded_works_are_deleted(pg_url: str, tmp_path: Path) -> None:
    psycopg = pytest.importorskip("psycopg")
    norm, trans, store = fx.write_corpus(tmp_path)
    manifest = norm / "_works.jsonl"
    lines = manifest.read_text().splitlines()
    with psycopg.connect(pg_url, autocommit=True) as conn:
        build_index.run(conn, norm, trans, store)
        # A partial run keeps works outside its selection.
        manifest.write_text("".join(f"{line}\n" for line in lines if "pta/hymns" not in line))
        build_index.run(conn, norm, trans, store, sources=["kjv"])
        assert _counts(conn)["works"] == 3
        # A full run deletes them, with their chunks and vectors.
        stats = build_index.run(conn, norm, trans, store)
        assert stats.deleted == 1
        assert _counts(conn) == {"works": 2, "chunks": 3, "chunk_translations": 0,
                                 "chunk_vectors": 3}
        # A work whose licence becomes unpublishable is deleted even by a partial run.
        manifest.write_text("".join(
            f"{line.replace('cc-by-4.0', 'unknown')}\n" for line in lines
            if "pta/hymns" not in line))
        stats = build_index.run(conn, norm, trans, store, sources=["kjv"])
        assert (stats.deleted, stats.excluded) == (1, 1)
        assert [r[0] for r in conn.execute("SELECT work_id FROM works")] == ["kjv/gen"]


def test_rerun_after_failed_index_build(pg_url: str, tmp_path: Path) -> None:
    """A rerun that only builds the missing index also analyzes the tables (#166)."""
    psycopg = pytest.importorskip("psycopg")
    norm, trans, store = fx.write_corpus(tmp_path)
    analyzed = ("SELECT last_analyze FROM pg_stat_user_tables "
                "WHERE schemaname = current_schema() AND relname = 'chunk_vectors'")
    with psycopg.connect(pg_url, autocommit=True) as conn:
        build_index.run(conn, norm, trans, store, maintenance_work_mem="64MB")
        before = conn.execute(analyzed).fetchone()[0]
        conn.execute("DROP INDEX chunk_vectors_hnsw_m1")  # as if CREATE INDEX had failed
        stats = build_index.run(conn, norm, trans, store, maintenance_work_mem="64MB")
        assert (stats.loaded, stats.deleted) == (0, 0)
        assert build_index.hnsw_indexes(conn) == ["chunk_vectors_hnsw_m1"]
        assert conn.execute(analyzed).fetchone()[0] > before
        # Nothing to do at all: no index build and no ANALYZE.
        build_index.run(conn, norm, trans, store)
        assert not build_index.build_hnsw(conn, "64MB")


def test_staging_joins_are_never_prepared(pg_url: str, tmp_path: Path,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """The per-work staging joins are planned for each work (#170).

    A prepared statement (psycopg prepares one after 5 executions) keeps the
    plan made for one work's staging rows, which can be slow for all others.
    """
    psycopg = pytest.importorskip("psycopg")
    norm, trans, store = fx.write_corpus(tmp_path)
    calls: list[tuple[str, object]] = []
    real = psycopg.Cursor.execute

    def spy(self, query, params=None, *, prepare=None, binary=None):
        calls.append((str(query), prepare))
        return real(self, query, params, prepare=prepare, binary=binary)

    monkeypatch.setattr(psycopg.Cursor, "execute", spy)
    with psycopg.connect(pg_url, autocommit=True) as conn:
        build_index.run(conn, norm, trans, store, maintenance_work_mem="64MB")
        conn.execute("UPDATE chunks SET text_folded = NULL")
        build_index.run(conn, norm, trans, store)
        _swap_kjv_gen_1(monkeypatch)
        build_index.run(conn, norm, trans, store)
        _change_metadata(norm)
        build_index.run(conn, norm, trans, store)
    staged = [prepare for sql, prepare in calls
              if any(f"FROM {t}_stage" in sql for t in ("vector", "fold", "group", "meta"))
              or sql.startswith("UPDATE chunk_vectors")]
    # vectors for 3 works, then folds for 3 works, then the groups of kjv/gen;
    # then the chunk dates and vector filter columns of kjv/gen (#234), and the
    # groups of both Genesis works (kjv/gen is no longer Scripture)
    assert len(staged) == 3 + 3 + 1 + 2 + 2
    assert set(staged) == {False}


def _change_metadata(norm: Path) -> None:
    """Metadata-only changes to kjv/gen (#234): its record, and the dates of its chunks."""
    manifest = norm / "_works.jsonl"
    entries = [json.loads(line) for line in manifest.read_text().splitlines()]
    for e in entries:
        if e["work"]["work_id"] == "kjv/gen":
            e["work"].update(title="Genesis (KJV)", author_ids=["moses"], date_range=[-1000, -400],
                             date_composed=-700, date_confidence="uncertain", genre="apocrypha")
    manifest.write_text("".join(json.dumps(e) + "\n" for e in entries))
    path = norm / fx.work_path("kjv/gen")
    chunks = json.loads(path.read_text())
    chunks[0].update(date_range=None, date_composed=None, date_confidence="uncertain")
    chunks[1].update(date_range=[1100, 1200], out_of_period=True)
    path.write_text(json.dumps(chunks))


_VECTORS = "SELECT chunk_id, kind, embedding::text FROM chunk_vectors ORDER BY 1, 2"


def test_metadata_change_is_updated_in_place(pg_url: str, tmp_path: Path) -> None:
    """A change to a work's metadata only rewrites rows; no vector is re-sent (#234)."""
    psycopg = pytest.importorskip("psycopg")
    norm, trans, store = fx.write_corpus(tmp_path)
    with psycopg.connect(pg_url, autocommit=True) as conn:
        build_index.run(conn, norm, trans, store, maintenance_work_mem="64MB")
        vectors = conn.execute(_VECTORS).fetchall()
        _change_metadata(norm)
        dry = build_index.run(conn, norm, trans, store, dry_run=True)
        assert (dry.loaded, dry.updated, dry.unchanged) == (0, 1, 2)
        stats = build_index.run(conn, norm, trans, store)
        assert (stats.loaded, stats.updated, stats.updated_chunks, stats.vectors) == (0, 1, 2, 0)
        assert conn.execute(
            "SELECT title, author_ids, date_composed, date_range::text, date_confidence, genre "
            "FROM works WHERE work_id = 'kjv/gen'").fetchone() == (
            "Genesis (KJV)", ["moses"], -700, "[-1000,-399)", "uncertain", "apocrypha")
        assert conn.execute(
            "SELECT chunk_id, date_range::text, date_confidence, out_of_period FROM chunks "
            "WHERE work_id = 'kjv/gen' ORDER BY 1").fetchall() == [
            ("kjv/gen#Gen.1.1", None, "uncertain", False),
            ("kjv/gen#Gen.1.2", "[1100,1201)", "approximate", True)]
        # The filter columns copied into chunk_vectors follow (a chunk without a
        # date takes the work's), and the vectors are the ones loaded before.
        assert conn.execute(
            "SELECT chunk_id, genre, author_ids, date_range::text, out_of_period "
            "FROM chunk_vectors WHERE work_id = 'kjv/gen' ORDER BY 1").fetchall() == [
            ("kjv/gen#Gen.1.1", "apocrypha", ["moses"], "[-1000,-399)", False),
            ("kjv/gen#Gen.1.2", "apocrypha", ["moses"], "[1100,1201)", True)]
        assert conn.execute(_VECTORS).fetchall() == vectors
        again = build_index.run(conn, norm, trans, store)
        assert (again.loaded, again.updated, again.unchanged) == (0, 0, 3)

        # A text change is not metadata: the work is reloaded.
        path = norm / fx.work_path("kjv/gen")
        chunks = json.loads(path.read_text())
        chunks[0]["text"] = "In the beginning."
        path.write_text(json.dumps(chunks))
        changed = build_index.run(conn, norm, trans, store)
        assert (changed.loaded, changed.updated) == (1, 0)


def test_author_date_range_touches_works_only(pg_url: str, tmp_path: Path) -> None:
    """A derived author date (#151) is metadata of the work alone: updated in
    place, with no chunk and no chunk_vectors row rewritten."""
    psycopg = pytest.importorskip("psycopg")
    norm, trans, store = fx.write_corpus(tmp_path)
    with psycopg.connect(pg_url, autocommit=True) as conn:
        build_index.run(conn, norm, trans, store, maintenance_work_mem="64MB")
        rows = ("SELECT chunk_id, xmin::text, ctid::text FROM chunks UNION ALL "
                "SELECT chunk_id || '/' || kind, xmin::text, ctid::text FROM chunk_vectors "
                "ORDER BY 1")
        before = conn.execute(rows).fetchall()
        manifest = norm / "_works.jsonl"
        entries = [json.loads(line) for line in manifest.read_text().splitlines()]
        for e in entries:
            if e["work"]["work_id"] == "pta/hymns":
                e["work"]["author_date_range"] = [326, 373]
        manifest.write_text("".join(json.dumps(e) + "\n" for e in entries))
        stats = build_index.run(conn, norm, trans, store)
        assert (stats.loaded, stats.updated, stats.updated_chunks, stats.vectors) == (0, 1, 0, 0)
        assert conn.execute("SELECT author_date_range::text FROM works "
                            "WHERE work_id = 'pta/hymns'").fetchone() == ("[326,374)",)
        assert conn.execute(rows).fetchall() == before


def test_status_reports_metadata_updates_apart(pg_url: str, tmp_path: Path) -> None:
    psycopg = pytest.importorskip("psycopg")
    from scripts import status

    norm, trans, store = fx.write_corpus(tmp_path)
    with psycopg.connect(pg_url, autocommit=True) as conn:
        build_index.run(conn, norm, trans, store, maintenance_work_mem="64MB")
    _change_metadata(norm)
    (row,) = [r for r in status.db_rows(pg_url, norm, trans, store, tmp_path / "alignments")
              if r.check == "database"]
    assert row.level == "warn"
    assert row.detail.startswith("0 works to load (vectors re-sent), 1 to update in place")


@pytest.mark.parametrize("legacy", ["no body_sha column", "body_sha column empty"])
def test_body_hash_migration_reloads_nothing(pg_url: str, tmp_path: Path, legacy: str) -> None:
    """The first run on a database loaded before #234 (hash format 2) fills in
    every body_sha in place and reloads nothing; after it, metadata changes are
    updated in place."""
    psycopg = pytest.importorskip("psycopg")
    norm, trans, store = fx.write_corpus(tmp_path)
    with psycopg.connect(pg_url, autocommit=True) as conn:
        build_index.run(conn, norm, trans, store, maintenance_work_mem="64MB")
        # As the loader before #234 left it: format 2, no body hashes.
        if legacy == "no body_sha column":
            conn.execute("ALTER TABLE works DROP COLUMN body_sha")
        else:
            conn.execute("UPDATE works SET body_sha = NULL")
        conn.execute("UPDATE index_meta SET value = '2' WHERE key = 'hash_format'")
        shas = conn.execute("SELECT work_id, content_sha FROM works ORDER BY 1").fetchall()
        vectors = conn.execute(_VECTOR_ROWS).fetchall()

        dry = build_index.run(conn, norm, trans, store, dry_run=True)
        assert (dry.loaded, dry.updated, dry.unchanged, dry.backfilled) == (0, 0, 3, 3)
        # A partial run fills in the hashes it checks but leaves the format at 2.
        part = build_index.run(conn, norm, trans, store, sources=["pta"])
        assert (part.loaded, part.backfilled) == (0, 1)
        assert build_index.hash_format(conn) == 2
        stats = build_index.run(conn, norm, trans, store)
        assert (stats.loaded, stats.updated, stats.unchanged, stats.backfilled) == (0, 0, 3, 2)
        assert build_index.hash_format(conn) == build_index.HASH_FORMAT == 3
        assert conn.execute("SELECT count(*) FROM works WHERE body_sha IS NULL").fetchone() == (0,)
        assert conn.execute("SELECT work_id, content_sha FROM works ORDER BY 1").fetchall() \
            == shas
        assert conn.execute(_VECTOR_ROWS).fetchall() == vectors  # not a row rewritten
        again = build_index.run(conn, norm, trans, store)
        assert (again.loaded, again.unchanged, again.backfilled) == (0, 3, 0)
        # The filled-in hashes are the ones a fresh load stores.
        entries = {e["work"]["work_id"]: e for e in build_index.load_works(norm)}
        for work_id, body in conn.execute("SELECT work_id, body_sha FROM works"):
            e = entries[work_id]
            chunks = json.loads((norm / e["path"]).read_text())
            files = (tr.translation_path(trans, e["path"]), emb.shard_path(store, e["path"]))
            assert body == build_index.body_sha(e, chunks, files)
        _change_metadata(norm)
        changed = build_index.run(conn, norm, trans, store)
        assert (changed.loaded, changed.updated) == (0, 1)


def _swap_kjv_gen_1(monkeypatch: pytest.MonkeyPatch) -> None:
    """A versification change: KJV Gen 1:2 now maps onto org Gen 1:1, and 1:1 onto 1:2."""
    from scripts import link_translations

    real = link_translations.to_org_ref
    swap = {"Gen.1.1": "Gen.1.2", "Gen.1.2": "Gen.1.1"}

    def to_org_ref(source_id: str, ref: str) -> str:
        org = real(source_id, ref)
        return swap.get(org, org) if source_id == "kjv" else org

    monkeypatch.setattr(link_translations, "to_org_ref", to_org_ref)


def _groups(conn) -> dict[str, str | None]:
    return dict(conn.execute("SELECT chunk_id, translation_group_id FROM chunks "
                             "WHERE work_id IN ('kjv/gen', 'oshb/gen')"))


# Every row version of chunk_vectors: an UPDATE, DELETE or INSERT changes it.
_VECTOR_ROWS = "SELECT chunk_id, kind, xmin::text, ctid::text FROM chunk_vectors ORDER BY 1, 2"


def test_regrouping_updates_groups_in_place(pg_url: str, tmp_path: Path,
                                            monkeypatch: pytest.MonkeyPatch) -> None:
    """A change of translation groups reloads no work and touches no vector (#186)."""
    psycopg = pytest.importorskip("psycopg")
    norm, trans, store = fx.write_corpus(tmp_path)
    with psycopg.connect(pg_url, autocommit=True) as conn:
        build_index.run(conn, norm, trans, store, maintenance_work_mem="64MB")
        assert _groups(conn) == {"kjv/gen#Gen.1.1": "Gen.1.1", "kjv/gen#Gen.1.2": None,
                                 "oshb/gen#Gen.1.1": "Gen.1.1"}
        vectors = conn.execute(_VECTOR_ROWS).fetchall()
        shas = conn.execute("SELECT work_id, content_sha FROM works ORDER BY 1").fetchall()

        _swap_kjv_gen_1(monkeypatch)
        dry = build_index.run(conn, norm, trans, store, dry_run=True)
        assert (dry.loaded, dry.regrouped) == (0, 2)
        assert _groups(conn)["kjv/gen#Gen.1.2"] is None
        # A partial run regroups the works it selects, with the groups of the
        # whole manifest: kjv Gen 1:2 joins the Hebrew Gen 1:1 outside the selection.
        stats = build_index.run(conn, norm, trans, store, sources=["kjv"])
        assert (stats.loaded, stats.unchanged, stats.regrouped) == (0, 1, 2)
        assert _groups(conn) == {"kjv/gen#Gen.1.1": None, "kjv/gen#Gen.1.2": "Gen.1.1",
                                 "oshb/gen#Gen.1.1": "Gen.1.1"}
        assert conn.execute(_VECTOR_ROWS).fetchall() == vectors
        assert conn.execute("SELECT work_id, content_sha FROM works ORDER BY 1").fetchall() \
            == shas
        again = build_index.run(conn, norm, trans, store)
        assert (again.loaded, again.regrouped) == (0, 0)


@pytest.mark.parametrize("legacy", ["no hash_format row", "no index_meta table"])
def test_hash_format_transition_reloads_nothing(pg_url: str, tmp_path: Path,
                                                monkeypatch: pytest.MonkeyPatch,
                                                legacy: str) -> None:
    """The first run on a database loaded with format-1 hashes rewrites them in place.

    Even when the groups change in the same run (the overrides of #186): the
    format-1 hash is checked against the groups in the database. A database
    loaded before #168 has no index_meta table at all; the dry run must agree
    with the real run there too.
    """
    psycopg = pytest.importorskip("psycopg")
    norm, trans, store = fx.write_corpus(tmp_path)
    entries = {e["work"]["work_id"]: e for e in build_index.load_works(norm)}
    with psycopg.connect(pg_url, autocommit=True) as conn:
        build_index.run(conn, norm, trans, store, maintenance_work_mem="64MB")
        # As the loader before #186 left it: format-1 hashes, no hash_format row.
        groups = build_index.stored_groups(conn)
        for work_id in ("kjv/gen", "oshb/gen", "pta/hymns"):
            e = entries[work_id]
            files = [norm / e["path"], tr.translation_path(trans, e["path"]),
                     emb.shard_path(store, e["path"])]
            conn.execute("UPDATE works SET content_sha = %s WHERE work_id = %s",
                         (_format1_sha(e, files, groups.get(work_id, {})), work_id))
        if legacy == "no index_meta table":
            conn.execute("DROP TABLE index_meta")
        else:
            conn.execute("DELETE FROM index_meta WHERE key = 'hash_format'")
        assert build_index.hash_format(conn) == 1
        vectors = conn.execute(_VECTOR_ROWS).fetchall()

        _swap_kjv_gen_1(monkeypatch)
        dry = build_index.run(conn, norm, trans, store, dry_run=True)
        assert (dry.loaded, dry.unchanged, dry.rehashed, dry.regrouped) == (0, 3, 3, 2)
        # A partial run rewrites the hashes it checks but leaves the format at 1.
        part = build_index.run(conn, norm, trans, store, sources=["pta"])
        assert (part.loaded, part.rehashed) == (0, 1)
        assert build_index.hash_format(conn) == 1
        stats = build_index.run(conn, norm, trans, store)
        assert (stats.loaded, stats.unchanged, stats.rehashed, stats.regrouped) == (0, 3, 2, 2)
        assert build_index.hash_format(conn) == build_index.HASH_FORMAT
        assert conn.execute(_VECTOR_ROWS).fetchall() == vectors
        assert _groups(conn)["kjv/gen#Gen.1.2"] == "Gen.1.1"
        again = build_index.run(conn, norm, trans, store)
        assert (again.loaded, again.unchanged, again.rehashed, again.regrouped) == (0, 3, 0, 0)
        # The current format no longer accepts a format-1 hash: a stale one is a
        # change. Its body is the stored one, so it is rewritten in place (#234);
        # without a body hash it is reloaded.
        e = entries["pta/hymns"]
        files = [norm / e["path"], tr.translation_path(trans, e["path"]),
                 emb.shard_path(store, e["path"])]
        conn.execute("UPDATE works SET content_sha = %s WHERE work_id = 'pta/hymns'",
                     (_format1_sha(e, files, {}),))
        assert (lambda s: (s.loaded, s.updated))(build_index.run(conn, norm, trans, store)) \
            == (0, 1)
        conn.execute("UPDATE works SET content_sha = %s, body_sha = NULL "
                     "WHERE work_id = 'pta/hymns'", (_format1_sha(e, files, {}),))
        assert build_index.run(conn, norm, trans, store).loaded == 1


def test_new_database_starts_at_current_hash_format(pg_url: str, tmp_path: Path) -> None:
    psycopg = pytest.importorskip("psycopg")
    norm, trans, store = fx.write_corpus(tmp_path)
    with psycopg.connect(pg_url, autocommit=True) as conn:
        build_index.run(conn, norm, trans, store, sources=["kjv"], maintenance_work_mem="64MB")
        assert build_index.hash_format(conn) == build_index.HASH_FORMAT


def test_dry_run_writes_nothing(pg_url: str, tmp_path: Path) -> None:
    psycopg = pytest.importorskip("psycopg")
    norm, trans, store = fx.write_corpus(tmp_path)
    with psycopg.connect(pg_url, autocommit=True) as conn:
        stats = build_index.run(conn, norm, trans, store, dry_run=True)
        assert (stats.works, stats.loaded) == (3, 3)
        regclass = "SELECT to_regclass(current_schema() || '.works')"
        assert conn.execute(regclass).fetchone() == (None,)


def test_schema_version_mismatch(pg_url: str, tmp_path: Path) -> None:
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(pg_url, autocommit=True) as conn:
        build_index.apply_schema(conn)
        build_index.apply_schema(conn)  # idempotent
        conn.execute("UPDATE schema_version SET version = 99")
        with pytest.raises(build_index.SchemaVersionError):
            build_index.apply_schema(conn)


# ------------------------------------------------------- passage groups (#179)


def _alignment(tmp_path: Path, norm: Path, oshb_conf: int = 9, oshb_ids: str | None = None
               ) -> Path:
    """An alignment of the fixture's Genesis: KJV Gen 1:1 with OSHB Gen 1:1."""
    from patristica import alignment_store as al

    def ids(work_id: str) -> str:
        chunks = json.loads((norm / fx.work_path(work_id)).read_text(encoding="utf-8"))
        return al.ids_sha([c["chunk_id"] for c in chunks])

    a = al.Alignment("book:gen", "kjv/gen", 2, "x", {"aligner": 1})
    a.members["kjv/gen"] = al.Member("kjv/gen", 2, "k", [0, 1], {0: 9, 1: 9}, ids("kjv/gen"))
    a.members["oshb/gen"] = al.Member("oshb/gen", 1, "o", [0], {0: oshb_conf},
                                      oshb_ids or ids("oshb/gen"))
    align_dir = tmp_path / "alignments"
    al.save(align_dir, a)
    return align_dir


def _passages(conn) -> dict[str, tuple[str, int]]:
    return {cid: (g, c) for cid, g, c in conn.execute(
        "SELECT chunk_id, group_id, confidence FROM passage_groups ORDER BY 1")}


def test_passage_groups_are_synced_in_place(pg_url: str, tmp_path: Path) -> None:
    """A new or changed alignment writes passage_groups only: no work reloads, no vector (#179)."""
    psycopg = pytest.importorskip("psycopg")
    norm, trans, store = fx.write_corpus(tmp_path)
    empty = tmp_path / "no-alignments"
    with psycopg.connect(pg_url, autocommit=True) as conn:
        build_index.run(conn, norm, trans, store, maintenance_work_mem="64MB", align_dir=empty)
        assert _passages(conn) == {}
        vectors = conn.execute(_VECTOR_ROWS).fetchall()
        shas = conn.execute("SELECT work_id, content_sha FROM works ORDER BY 1").fetchall()

        align_dir = _alignment(tmp_path, norm)
        dry = build_index.run(conn, norm, trans, store, dry_run=True, align_dir=align_dir)
        assert (dry.loaded, dry.passages) == (0, 2)
        assert _passages(conn) == {}
        stats = build_index.run(conn, norm, trans, store, align_dir=align_dir)
        assert (stats.loaded, stats.unchanged, stats.passages) == (0, 3, 2)
        assert _passages(conn) == {"kjv/gen#Gen.1.1": ("book:gen@0", 9),
                                   "oshb/gen#Gen.1.1": ("book:gen@0", 9)}
        assert build_index.run(conn, norm, trans, store, align_dir=align_dir).passages == 0

        # Flagged: OSHB's span drops under MIN_CONFIDENCE, so the group goes.
        align_dir = _alignment(tmp_path, norm, oshb_conf=3)
        assert build_index.run(conn, norm, trans, store, align_dir=align_dir).passages == 2
        assert _passages(conn) == {}
        assert conn.execute(_VECTOR_ROWS).fetchall() == vectors
        assert conn.execute("SELECT work_id, content_sha FROM works ORDER BY 1").fetchall() \
            == shas


def test_stale_alignment_gives_no_passage_groups(pg_url: str, tmp_path: Path) -> None:
    psycopg = pytest.importorskip("psycopg")
    norm, trans, store = fx.write_corpus(tmp_path)
    align_dir = _alignment(tmp_path, norm, oshb_ids="0" * 16)
    with psycopg.connect(pg_url, autocommit=True) as conn:
        stats = build_index.run(conn, norm, trans, store, maintenance_work_mem="64MB",
                                align_dir=align_dir)
        assert stats.stale_alignments == ["oshb/gen"]
        assert _passages(conn) == {}


def test_passage_group_key(pg_url: str, tmp_path: Path) -> None:
    """Search folds by the passage group, else the Scripture verse group, else the chunk."""
    psycopg = pytest.importorskip("psycopg")
    from api.passages import passage_group

    norm, trans, store = fx.write_corpus(tmp_path)
    align_dir = _alignment(tmp_path, norm)
    with psycopg.connect(pg_url, autocommit=True) as conn:
        build_index.run(conn, norm, trans, store, maintenance_work_mem="64MB",
                        align_dir=align_dir)
        conn.execute("UPDATE chunks SET translation_group_id = 'Gen.1.2' "
                     "WHERE chunk_id = 'kjv/gen#Gen.1.2'")
        keys = dict(conn.execute(f"SELECT c.chunk_id, {passage_group('c')} FROM chunks c"))
    assert keys == {"kjv/gen#Gen.1.1": "book:gen@0", "oshb/gen#Gen.1.1": "book:gen@0",
                    "kjv/gen#Gen.1.2": "Gen.1.2", "pta/hymns#Hymn.1.1": "pta/hymns#Hymn.1.1",
                    "pta/hymns#Hymn.1.2": "pta/hymns#Hymn.1.2"}


def test_full_run_records_the_code_hash(pg_url: str, tmp_path: Path) -> None:
    """index_meta.code (#130) is written by full runs only and read by scripts.status."""
    psycopg = pytest.importorskip("psycopg")
    from scripts import status

    norm, trans, store = fx.write_corpus(tmp_path)
    with psycopg.connect(pg_url, autocommit=True) as conn:
        build_index.run(conn, norm, trans, store, sources=["pta"], maintenance_work_mem="64MB")
        assert build_index.stored_code(conn) is None  # a partial run doesn't record it
        build_index.run(conn, norm, trans, store, maintenance_work_mem="64MB")
        assert build_index.stored_code(conn) == build_index.build_index_code_hash()
    rows = status.db_rows(pg_url, norm, trans, store, tmp_path / "alignments")
    assert [(r.check, r.level) for r in rows] == [("code", "ok"), ("database", "ok")]
