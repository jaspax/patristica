"""Tests for scripts.build_index (#137).

The database tests need ``PATRISTICA_TEST_DATABASE_URL`` (see ``conftest.pg_url``)
and skip without it.
"""

from __future__ import annotations

import json
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
    base = build_index.content_sha(entry, [f, tmp_path / "missing"], {})
    assert base == build_index.content_sha(entry, [f, tmp_path / "missing"], {})
    assert base != build_index.content_sha(entry, [f, tmp_path / "missing"], {"a#1": "Gen.1.1"})
    f.write_text("[1]")
    assert base != build_index.content_sha(entry, [f, tmp_path / "missing"], {})


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
    staged = [prepare for sql, prepare in calls
              if "FROM vector_stage" in sql or "FROM fold_stage" in sql]
    assert len(staged) == 3 + 3  # vectors for 3 works, then folds for 3 works
    assert set(staged) == {False}


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
