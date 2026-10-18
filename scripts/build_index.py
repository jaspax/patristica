"""
Load the corpus and its vectors into the search database (#137).

Reads ``data/normalized/`` (via ``_works.jsonl``), the translation store
``data/translations/`` and the embedding store ``data/embeddings/`` (from
``scripts.embed``), and writes the tables of ``db/schema.sql`` (applied on
every run): ``authors``, ``works``, ``chunks``, ``chunk_translations``,
``embedding_models`` and ``chunk_vectors``. IMPLEMENTATION_PLAN.md §2.2–2.3.

- Works whose licence is in ``upload_library.EXCLUDED_LICENSES`` are never
  loaded, and are deleted if present.
- Scripture chunks get their ``translation_group_id`` from
  ``link_scripture_translations``, computed over every Scripture work in the
  manifest (a group needs two members, so it depends on all of them).
- A vector is loaded only while the text it embeds is the chunk's current
  text (or its current fresh translation); stale rows are counted, and
  ``scripts.embed`` refreshes them. Vectors are cut to ``DIMS`` and
  renormalized (``patristica.embedders.shorten``, #50), and each row names
  its model (``embedding_models``).
- It is incremental. Each work records a hash of everything loaded for it
  (its manifest record, normalized file, translations, vectors and groups);
  a work whose hash is unchanged is skipped, a changed one is deleted and
  reloaded in one transaction, so an interrupted run resumes where it
  stopped. A full run (no ``--source``/``--work``) deletes works that are no
  longer in the manifest.
- When ``chunk_vectors`` is empty (the first load), or with
  ``--rebuild-index``, the HNSW indexes are dropped first and built after the
  COPY; otherwise new rows go into the live index. There is one partial HNSW
  index per model, ``chunk_vectors_hnsw_m{model_id}``.
- Each chunk's ``text_folded`` (``patristica.keyword.index_text``) feeds the
  keyword index for quoted search (#86), a ``pg_trgm`` GIN index built after
  the load. Chunks loaded before that column existed, or folded by an older
  ``FOLD_VERSION``, are folded in place from the normalized files of works
  whose hash this run checked, so no vectors are reloaded.

Usage::

    python -m scripts.build_index --dry-run       # what would be loaded
    python -m scripts.build_index [--source gez] [--work oshb/] [--rebuild-index]

The database is ``--database-url``, else ``DATABASE_URL`` (environment or
``.env``). For the droplet, run it through the SSH tunnel:
``infra/db-tunnel.sh uv run --extra index python -m scripts.build_index``.
Needs the ``index`` extra.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import struct
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tqdm import tqdm

from patristica import embeddings as emb
from patristica import translations as tr
from patristica.authors import author_index
from patristica.embedders import env_key, shorten
from patristica.keyword import FOLD_VERSION, index_text
from patristica.models import Chunk
from scripts.embed import load_works, select
from scripts.link_translations import link_scripture_translations

if TYPE_CHECKING:
    import numpy as np
    import psycopg

log = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
SCHEMA_VERSION = 1
# Bump when what is loaded for a work changes, so every work is reloaded.
LOADER_VERSION = 1
DIMS = 512  # stored vector size (#50); chunk_vectors.embedding is halfvec(512)
HNSW_M = 16
HNSW_EF_CONSTRUCTION = 64
TRGM_INDEX = "chunks_text_folded_trgm"
# Folding more chunks than this rebuilds the trigram index instead of updating it.
BULK_FOLD = 100_000

_CHUNK_COLUMNS = ("chunk_id", "work_id", "canonical_ref", "chunk_index", "language", "text",
                  "date_composed", "date_range", "date_confidence", "out_of_period",
                  "translation_group_id", "text_folded")
_COPY_SIGNATURE = b"PGCOPY\n\xff\r\n\x00" + struct.pack(">ii", 0, 0)


class SchemaVersionError(RuntimeError):
    """The database was built with a different schema version."""


@dataclass
class Stats:
    works: int = 0
    unchanged: int = 0
    loaded: int = 0
    deleted: int = 0
    excluded: int = 0
    chunks: int = 0
    translations: int = 0
    vectors: int = 0
    stale_vectors: int = 0
    folded: int = 0  # chunks folded in place (not counting those loaded)
    no_vectors: list[str] = field(default_factory=list)  # works without a shard

    def summary(self) -> str:
        return (f"{self.works} works: {self.loaded} loaded, {self.unchanged} unchanged, "
                f"{self.deleted} deleted ({self.excluded} for their licence); "
                f"{self.chunks} chunks, {self.translations} translations, "
                f"{self.vectors} vectors loaded, {self.stale_vectors} stale vectors skipped, "
                f"{len(self.no_vectors)} works without vectors, "
                f"{self.folded} chunks folded in place")


def pg_range(r: list[int] | tuple[int, int] | None) -> str | None:
    """An inclusive (lo, hi) year range as an ``int4range`` literal."""
    return None if r is None else f"[{int(r[0])},{int(r[1])}]"


def scripture_groups(entries: Iterable[dict], input_dir: Path) -> dict[str, dict[str, str]]:
    """work_id → {chunk_id: translation_group_id} over the Scripture works in *entries*.

    Chunks in no group (a ref only one work has) are left out.
    """
    stubs: list[Chunk] = []
    paths = [e["path"] for e in entries if e["work"]["genre"] == "scripture"]
    for path in tqdm(paths, desc="scripture groups", unit="work"):
        with (input_dir / path).open(encoding="utf-8") as f:
            for c in json.load(f):
                stubs.append(Chunk(chunk_id=c["chunk_id"], work_id=c["work_id"],
                                   canonical_ref=c["canonical_ref"], language=c["language"],
                                   text="", chunk_index=c["chunk_index"]))
    groups: dict[str, dict[str, str]] = {}
    for c in link_scripture_translations(stubs):
        if c.translation_group_id is not None:
            groups.setdefault(c.work_id, {})[c.chunk_id] = c.translation_group_id
    return groups


def _file_digest(h: Any, path: Path) -> None:
    if not path.exists():
        h.update(b"\x00")
        return
    h.update(b"\x01")
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)


def content_sha(entry: dict, files: Iterable[Path], groups: dict[str, str]) -> str:
    """Hash of everything ``load_work`` loads for *entry*."""
    h = hashlib.sha256()
    h.update(json.dumps({"loader": LOADER_VERSION, "schema": SCHEMA_VERSION, "dims": DIMS,
                         "entry": entry, "groups": sorted(groups.items())},
                        sort_keys=True, ensure_ascii=False).encode("utf-8"))
    for path in files:
        _file_digest(h, path)
    return h.hexdigest()


def apply_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
    (version,) = conn.execute("SELECT version FROM schema_version").fetchone()
    if version != SCHEMA_VERSION:
        raise SchemaVersionError(
            f"database schema is version {version}, this loader expects {SCHEMA_VERSION}: "
            "see db/README.md")


def load_authors(conn: psycopg.Connection) -> int:
    """Replace the ``authors`` table with the author index."""
    from psycopg.types.json import Jsonb

    authors = author_index().authors.values()
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("DELETE FROM authors")
        with cur.copy("COPY authors (author_id, name, aliases, birth, death, floruit, "
                      "tradition, pseudo_of) FROM STDIN") as copy:
            for a in authors:
                j = a.to_json()
                copy.write_row((a.author_id, a.name, list(a.aliases),
                                *(Jsonb(j[k]) if j[k] else None
                                  for k in ("birth", "death", "floruit")),
                                a.tradition, a.pseudo_of))
    return len(authors)


def model_ids(conn: psycopg.Connection, runs: Iterable[emb.EmbeddingRun],
              cache: dict[tuple[str, str], int]) -> dict[str, int]:
    """run key → ``embedding_models.model_id`` (registering new models)."""
    out = {}
    for run in runs:
        if run.dims < DIMS:
            raise ValueError(f"{run.key}: {run.dims}-dim vectors cannot be cut to {DIMS}")
        key = (run.model, run.input_type)
        if key not in cache:
            row = conn.execute(
                "INSERT INTO embedding_models (name, dims, input_type) VALUES (%s, %s, %s) "
                "ON CONFLICT (name, dims, input_type) DO UPDATE SET name = EXCLUDED.name "
                "RETURNING model_id", (run.model, DIMS, run.input_type)).fetchone()
            cache[key] = row[0]
        out[run.key] = cache[key]
    return out


def fresh_vectors(chunks: list[dict], translations: dict[str, str],
                  shard: emb.WorkEmbeddings) -> tuple[list[int], int]:
    """Indices of the rows of *shard* that embed current text, and the number of stale rows."""
    text_sha = {c["chunk_id"]: tr.text_sha(c["text"]) for c in chunks}
    trans_sha = {cid: tr.text_sha(t) for cid, t in translations.items()}
    keep, stale = [], 0
    for i, row in enumerate(shard.rows):
        want = (text_sha if row.kind == emb.KIND_TEXT else trans_sha).get(row.chunk_id)
        if want is not None and row.sha == want:
            keep.append(i)
        else:
            stale += 1
    return keep, stale


def copy_binary_vectors(rows: list[tuple[str, int, int]], vecs: np.ndarray) -> bytes:
    """A binary COPY stream of (chunk_id text, kind int2, model_id int2, embedding halfvec)."""
    import numpy as np

    be = np.ascontiguousarray(vecs, dtype=">f2")
    dims = be.shape[1]
    vec_head = struct.pack(">ihh", 4 + 2 * dims, dims, 0)
    parts = [_COPY_SIGNATURE]
    for (chunk_id, kind, model_id), v in zip(rows, be):
        cid = chunk_id.encode("utf-8")
        parts.append(struct.pack(">hi", 4, len(cid)))
        parts.append(cid)
        parts.append(struct.pack(">ihih", 2, kind, 2, model_id))
        parts.append(vec_head)
        parts.append(v.tobytes())
    parts.append(struct.pack(">h", -1))
    return b"".join(parts)


def load_work(conn: psycopg.Connection, entry: dict, sha: str, chunks: list[dict],
              translations: tr.WorkTranslations | None, shard: emb.WorkEmbeddings | None,
              groups: dict[str, str], models: dict[tuple[str, str], int], stats: Stats) -> None:
    """Replace one work and everything under it, in one transaction."""
    import numpy as np

    w = entry["work"]
    fresh: dict[str, tr.ChunkTranslation] = {}
    if translations is not None:
        rows = translations.by_chunk()
        for c in chunks:
            t = rows.get(c["chunk_id"])
            if t is not None and t.source_sha256 == tr.text_sha(c["text"]) and t.text.strip():
                fresh[c["chunk_id"]] = t
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("DELETE FROM works WHERE work_id = %s", (w["work_id"],))
        cur.execute(
            "INSERT INTO works (work_id, source_id, title, author, author_ids, date_composed, "
            "date_range, date_confidence, genre, language, tradition, license, provenance_url, "
            "edition, translation_of, path, content_sha) VALUES (%s, %s, %s, %s, %s, %s, "
            "%s::int4range, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (w["work_id"], w["source_id"], w["title"], w.get("author"), w.get("author_ids", []),
             w.get("date_composed"), pg_range(w.get("date_range")), w["date_confidence"],
             w["genre"], w["language"], w.get("tradition"), w["license"],
             w.get("provenance_url"), w.get("edition"), w.get("translation_of"),
             entry["path"], sha))
        with cur.copy(f"COPY chunks ({', '.join(_CHUNK_COLUMNS)}) FROM STDIN") as copy:
            for c in chunks:
                copy.write_row((c["chunk_id"], c["work_id"], c["canonical_ref"],
                                c["chunk_index"], c["language"], c["text"],
                                c.get("date_composed"), pg_range(c.get("date_range")),
                                c["date_confidence"], c["out_of_period"],
                                groups.get(c["chunk_id"]), index_text(c["text"])))
        stats.chunks += len(chunks)
        if fresh:
            prov = translations.provenance
            with cur.copy("COPY chunk_translations (chunk_id, language, text, model, "
                          "prompt_version, date) FROM STDIN") as copy:
                for cid, t in fresh.items():
                    p = prov[t.provenance]
                    copy.write_row((cid, translations.target_language, t.text, p.model,
                                    p.prompt_version, p.date))
            stats.translations += len(fresh)
        if shard is None:
            stats.no_vectors.append(w["work_id"])
            return
        if shard.work_id != w["work_id"]:
            raise ValueError(f"{entry['path']}: shard is for {shard.work_id}, not {w['work_id']}")
        keep, stale = fresh_vectors(chunks, {k: t.text for k, t in fresh.items()}, shard)
        stats.stale_vectors += stale
        if not keep:
            return
        ids = model_ids(conn, (shard.runs[k] for k in {shard.rows[i].run for i in keep}), models)
        rows = [(shard.rows[i].chunk_id, shard.rows[i].kind, ids[shard.rows[i].run])
                for i in keep]
        vecs = shorten(shard.vecs[np.asarray(keep)], DIMS)
        with cur.copy("COPY vector_stage (chunk_id, kind, model_id, embedding) "
                      "FROM STDIN (FORMAT BINARY)") as copy:
            copy.write(copy_binary_vectors(rows, vecs))
        cur.execute(
            "INSERT INTO chunk_vectors (chunk_id, kind, model_id, embedding, work_id, source_id, "
            "language, genre, author_ids, date_range, out_of_period) "
            "SELECT s.chunk_id, s.kind, s.model_id, s.embedding, c.work_id, w.source_id, "
            "c.language, w.genre, w.author_ids, coalesce(c.date_range, w.date_range), "
            "c.out_of_period FROM vector_stage s JOIN chunks c USING (chunk_id) "
            "JOIN works w ON w.work_id = c.work_id")
        stats.vectors += len(rows)


def hnsw_indexes(conn: psycopg.Connection) -> list[str]:
    return [r[0] for r in conn.execute(
        "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema() "
        "AND tablename = 'chunk_vectors' AND indexname LIKE 'chunk_vectors_hnsw_m%'")]


def build_hnsw(conn: psycopg.Connection, maintenance_work_mem: str) -> bool:
    """Create the missing per-model HNSW indexes (IMPLEMENTATION_PLAN.md §2.3 step 6).

    Returns True if it built one. A parallel build keeps *maintenance_work_mem*
    in shared memory: the db container's ``shm_size`` must be larger (#166).
    """
    built = False
    model_rows = conn.execute("SELECT model_id, name FROM embedding_models m WHERE EXISTS "
                              "(SELECT FROM chunk_vectors v WHERE v.model_id = m.model_id) "
                              "ORDER BY model_id").fetchall()
    existing = set(hnsw_indexes(conn))
    for model_id, name in model_rows:
        index = f"chunk_vectors_hnsw_m{int(model_id)}"
        if index in existing:
            continue
        log.info("building %s for %s (this takes a while for the full corpus)", index, name)
        conn.execute("SELECT set_config('maintenance_work_mem', %s, false)",
                     (maintenance_work_mem,))
        conn.execute(
            f"CREATE INDEX {index} ON chunk_vectors USING hnsw (embedding halfvec_cosine_ops) "
            f"WITH (m = {HNSW_M}, ef_construction = {HNSW_EF_CONSTRUCTION}) "
            f"WHERE model_id = {int(model_id)}")
        built = True
    return built


def has_index(conn: psycopg.Connection, name: str) -> bool:
    return conn.execute("SELECT to_regclass(%s) IS NOT NULL", (name,)).fetchone()[0]


def fold_missing(conn: psycopg.Connection, paths: dict[str, Path],
                 maintenance_work_mem: str) -> int:
    """Fill ``text_folded`` where it is NULL, then make sure the trigram index exists.

    *paths* maps each work this run checked (its stored hash matches the
    files, or it was just loaded) to its normalized file, which therefore
    holds exactly the text in the database. Other works stay unfolded until
    a run that covers them. Returns the number of chunks folded.
    """
    meta = conn.execute("SELECT value FROM index_meta WHERE key = 'fold_version'").fetchone()
    if meta is not None and meta[0] != str(FOLD_VERSION):
        log.info("fold version %s -> %s: refolding every chunk", meta[0], FOLD_VERSION)
        conn.execute(f"DROP INDEX IF EXISTS {TRGM_INDEX}")
        conn.execute("UPDATE chunks SET text_folded = NULL")
    pending = conn.execute("SELECT count(*) FROM chunks WHERE text_folded IS NULL").fetchone()[0]
    todo = [w for (w,) in conn.execute(
        "SELECT DISTINCT work_id FROM chunks WHERE text_folded IS NULL") if w in paths]
    if pending > BULK_FOLD and has_index(conn, TRGM_INDEX):
        log.info("dropping %s to fold %d chunks", TRGM_INDEX, pending)
        conn.execute(f"DROP INDEX {TRGM_INDEX}")
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS fold_stage (chunk_id text, text_folded text) "
                 "ON COMMIT DELETE ROWS")
    folded = 0
    for work_id in tqdm(todo, desc="fold", unit="work"):
        with paths[work_id].open(encoding="utf-8") as f:
            chunks = json.load(f)
        with conn.transaction(), conn.cursor() as cur:
            with cur.copy("COPY fold_stage (chunk_id, text_folded) FROM STDIN") as copy:
                for c in chunks:
                    copy.write_row((c["chunk_id"], index_text(c["text"])))
            cur.execute("UPDATE chunks c SET text_folded = s.text_folded FROM fold_stage s "
                        "WHERE c.chunk_id = s.chunk_id AND c.text_folded IS NULL")
            folded += cur.rowcount
    if not has_index(conn, TRGM_INDEX):
        log.info("building %s (keyword index, #86)", TRGM_INDEX)
        conn.execute("SELECT set_config('maintenance_work_mem', %s, false)",
                     (maintenance_work_mem,))
        conn.execute(f"CREATE INDEX {TRGM_INDEX} ON chunks USING gin (text_folded gin_trgm_ops)")
    if not conn.execute("SELECT EXISTS (SELECT FROM chunks WHERE text_folded IS NULL)"
                        ).fetchone()[0]:
        conn.execute("INSERT INTO index_meta VALUES ('fold_version', %s) ON CONFLICT (key) "
                      "DO UPDATE SET value = EXCLUDED.value", (str(FOLD_VERSION),))
    if folded > BULK_FOLD:
        # Every folded row was rewritten: make the old versions' space reusable.
        conn.execute("VACUUM chunks")
    return folded


def run(conn: psycopg.Connection, input_dir: Path, trans_dir: Path, store_dir: Path, *,
        sources: Iterable[str] = (), prefixes: Iterable[str] = (), dry_run: bool = False,
        rebuild_index: bool = False, maintenance_work_mem: str = "4GB") -> Stats:
    """Bring the database in line with the inputs; see the module docstring.

    *conn* must be in autocommit mode: each work is its own transaction.
    """
    sources, prefixes = list(sources), list(prefixes)
    stats = Stats()
    entries = load_works(input_dir)
    publishable = select(entries, [], [], include_unpublishable=False)
    wanted = select(publishable, sources, prefixes, include_unpublishable=False)
    stats.works = len(wanted)
    excluded = {e["work"]["work_id"] for e in entries} - {e["work"]["work_id"] for e in publishable}

    if dry_run:
        have = conn.execute("SELECT to_regclass('works') IS NOT NULL").fetchone()[0]
        stored = dict(conn.execute("SELECT work_id, content_sha FROM works")) if have else {}
    else:
        apply_schema(conn)
        log.info("authors: %d", load_authors(conn))
        stored = dict(conn.execute("SELECT work_id, content_sha FROM works"))
        empty = conn.execute("SELECT NOT EXISTS (SELECT FROM chunk_vectors)").fetchone()[0]
        if empty or rebuild_index:
            for index in hnsw_indexes(conn):
                log.info("dropping %s for the bulk load", index)
                conn.execute(f"DROP INDEX {index}")
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS vector_stage (chunk_id text, "
                     "kind smallint, model_id smallint, embedding halfvec(512)) "
                     "ON COMMIT DELETE ROWS")

    gone = set(stored) & excluded
    if not sources and not prefixes:
        gone |= set(stored) - {e["work"]["work_id"] for e in publishable}
    stats.excluded = len(set(stored) & excluded)
    stats.deleted = len(gone)
    if gone and not dry_run:
        log.info("deleting %d works", len(gone))
        conn.execute("DELETE FROM works WHERE work_id = ANY(%s)", (sorted(gone),))

    groups = scripture_groups(publishable, input_dir)
    models: dict[tuple[str, str], int] = {}
    checked: dict[str, Path] = {}  # works whose stored text matches their file
    for entry in tqdm(wanted, desc="works", unit="work"):
        path = entry["path"]
        work_id = entry["work"]["work_id"]
        norm = input_dir / path
        tpath = tr.translation_path(trans_dir, path)
        spath = emb.shard_path(store_dir, path)
        work_groups = groups.get(work_id, {})
        sha = content_sha(entry, (norm, tpath, spath), work_groups)
        if stored.get(work_id) == sha:
            stats.unchanged += 1
            checked[work_id] = norm
            continue
        stats.loaded += 1
        if dry_run:
            continue
        with norm.open(encoding="utf-8") as f:
            chunks = json.load(f)
        load_work(conn, entry, sha, chunks, tr.load(trans_dir, path), emb.load(store_dir, path),
                  work_groups, models, stats)
        checked[work_id] = norm

    if not dry_run:
        stats.folded = fold_missing(conn, checked, maintenance_work_mem)
        # Also after an index build alone: a rerun after a failed build loads
        # nothing, and the first run never got to its ANALYZE.
        built = build_hnsw(conn, maintenance_work_mem)
        if built or stats.loaded or stats.deleted or stats.folded:
            conn.execute("ANALYZE works, chunks, chunk_translations, chunk_vectors")
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", help="default: DATABASE_URL (environment or .env)")
    parser.add_argument("--input-dir", type=Path, default=Path("data/normalized"))
    parser.add_argument("--translations-dir", type=Path, default=tr.DEFAULT_DIR)
    parser.add_argument("--embeddings-dir", type=Path, default=emb.DEFAULT_DIR)
    parser.add_argument("--source", action="append", default=[],
                        help="only works of this source_id (repeatable)")
    parser.add_argument("--work", action="append", default=[],
                        help="only works whose work_id starts with this (repeatable)")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be loaded; write nothing")
    parser.add_argument("--rebuild-index", action="store_true",
                        help="drop the HNSW indexes first and rebuild them after loading")
    parser.add_argument("--maintenance-work-mem", default="4GB",
                        help="memory for building the HNSW index (default 4GB, for 8 GB hosts)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    import psycopg

    url = args.database_url or env_key("DATABASE_URL")
    with psycopg.connect(url, autocommit=True) as conn:
        stats = run(conn, args.input_dir, args.translations_dir, args.embeddings_dir,
                    sources=args.source, prefixes=args.work, dry_run=args.dry_run,
                    rebuild_index=args.rebuild_index,
                    maintenance_work_mem=args.maintenance_work_mem)
    log.info("%s%s", "dry run: " if args.dry_run else "", stats.summary())
    if stats.stale_vectors:
        log.warning("%d vectors embed outdated text: run scripts.embed, then this again",
                    stats.stale_vectors)


if __name__ == "__main__":
    main()
