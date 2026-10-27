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
  manifest (a group needs two members, so it depends on all of them). Groups
  are not part of a work's hash: after the works are loaded, the chunks
  whose stored group differs are updated in place, one transaction per work,
  so a regrouping (a versification override, #186) reloads no vectors.
- A vector is loaded only while the text it embeds is the chunk's current
  text (or its current fresh translation); stale rows are counted, and
  ``scripts.embed`` refreshes them. Vectors are cut to ``DIMS`` and
  renormalized (``patristica.embedders.shorten``, #50), and each row names
  its model (``embedding_models``).
- It is incremental. Each work records a hash of everything loaded for it
  (its manifest record, normalized file, translations and vectors);
  a work whose hash is unchanged is skipped, a changed one is deleted and
  reloaded in one transaction, so an interrupted run resumes where it
  stopped. Unless only its metadata changed (#234): a second hash,
  ``body_sha``, leaves out the work record's metadata and the chunks' dates,
  and a work whose body is unchanged is updated in place
  (``update_metadata``) without re-sending a vector. A full run (no ``--source``/``--work``) deletes works that are no
  longer in the manifest.
- When ``chunk_vectors`` is empty (the first load), or with
  ``--rebuild-index``, the HNSW indexes are dropped first and built after the
  COPY; otherwise new rows go into the live index. There is one partial HNSW
  index per model, ``chunk_vectors_hnsw_m{model_id}``.
- Passage alignment groups (``data/alignments/``, #179) go into
  ``passage_groups`` (chunk → group), which search folds by
  (``api/passages.py``). Like the Scripture groups they are not part of a
  work's hash: the rows of every work this run checked are synced in place,
  so a new alignment touches neither works nor vectors. A member whose chunk
  ids no longer match its alignment (``Member.ids``) gets no rows until
  ``scripts.align`` runs again.
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

from patristica import alignment_store as al
from patristica import embeddings as emb
from patristica import translations as tr
from patristica.authors import author_index
from patristica.corpus import load_works, select
from patristica.editorial import source_text
from patristica.embedders import env_key, shorten
from patristica.keyword import FOLD_VERSION, index_text
from patristica.models import Chunk
from scripts.link_translations import link_scripture_translations

if TYPE_CHECKING:
    import numpy as np
    import psycopg

log = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"
SCHEMA_VERSION = 1
# Bump when what is loaded for a work changes, so every work is reloaded.
LOADER_VERSION = 1
# The format of works.content_sha. Format 1 also hashed the work's translation
# groups, so a regrouping reloaded the work; format 2 leaves them out
# (sync_groups, #186). index_meta.hash_format is the format of every stored
# hash (no row: 1). While it is 1, a stored hash that is the format-1 hash of
# the work's current inputs and its stored groups is rewritten in place, so
# the first run after the change reloads nothing. Format 3 keeps content_sha as
# in format 2 and adds works.body_sha (#234), the hash without the metadata: a
# work whose content_sha changed but whose body_sha didn't is updated in place
# (update_metadata). Below format 3, an unchanged work without a body_sha gets
# it computed and stored in place, so that migration reloads nothing either.
HASH_FORMAT = 3
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
# The joins against the per-work staging tables (vector_stage, fold_stage) run
# with prepare=False. psycopg prepares a statement after its 5th execution, and
# Postgres then reuses one plan for every later work: a plan made for one
# work's staging rows can walk millions of chunks for each of the others
# (#170: 6 s a work instead of a fraction of a second).


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
    regrouped: int = 0  # chunks whose translation_group_id was updated in place
    passages: int = 0  # passage_groups rows written or deleted in place
    stale_alignments: list[str] = field(default_factory=list)  # members whose ids changed
    rehashed: int = 0  # unchanged works whose format-1 hash was rewritten
    updated: int = 0  # works whose metadata was updated in place (#234)
    updated_chunks: int = 0  # chunks whose dates were updated in place
    backfilled: int = 0  # unchanged works whose body_sha was filled in (hash format 3)
    no_vectors: list[str] = field(default_factory=list)  # works without a shard

    def summary(self) -> str:
        return (f"{self.works} works: {self.loaded} loaded, "
                f"{self.updated} updated in place ({self.updated_chunks} chunks), "
                f"{self.unchanged} unchanged, "
                f"{self.deleted} deleted ({self.excluded} for their licence); "
                f"{self.chunks} chunks, {self.translations} translations, "
                f"{self.vectors} vectors loaded, {self.stale_vectors} stale vectors skipped, "
                f"{len(self.no_vectors)} works without vectors, "
                f"{self.folded} chunks folded in place, "
                f"{self.regrouped} chunks regrouped in place, "
                f"{self.passages} passage-group rows synced, "
                f"{self.rehashed} format-1 hashes rewritten, "
                f"{self.backfilled} body hashes filled in")


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


def _file_digest(hashes: list[Any], path: Path) -> None:
    if not path.exists():
        for h in hashes:
            h.update(b"\x00")
        return
    for h in hashes:
        h.update(b"\x01")
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            for h in hashes:
                h.update(block)


def _sha_head(entry: dict, groups: dict[str, str] | None) -> bytes:
    # ``external_ids`` (#178) isn't loaded, so recording a work's catalogue
    # ids must not change its hash and reload its chunks and vectors.
    work = entry.get("work")
    if isinstance(work, dict) and "external_ids" in work:
        entry = {**entry, "work": {k: v for k, v in work.items() if k != "external_ids"}}
    head: dict[str, Any] = {"loader": LOADER_VERSION, "schema": SCHEMA_VERSION, "dims": DIMS,
                            "entry": entry}
    if groups is not None:  # hash format 1
        head["groups"] = sorted(groups.items())
    return json.dumps(head, sort_keys=True, ensure_ascii=False).encode("utf-8")


def content_shas(entry: dict, files: Iterable[Path],
                 legacy_groups: dict[str, str] | None = None) -> tuple[str, str | None]:
    """``content_sha``, and its format-1 version with *legacy_groups* (None without them).

    Both come from one pass over the files.
    """
    hashes = [hashlib.sha256(_sha_head(entry, None))]
    if legacy_groups is not None:
        hashes.append(hashlib.sha256(_sha_head(entry, legacy_groups)))
    for path in files:
        _file_digest(hashes, path)
    return hashes[0].hexdigest(), (hashes[1].hexdigest() if legacy_groups is not None else None)


def content_sha(entry: dict, files: Iterable[Path]) -> str:
    """Hash of everything ``load_work`` loads for *entry*, except its translation groups."""
    return content_shas(entry, files)[0]


#: Work fields that only metadata depends on: ``update_metadata`` rewrites them
#: in place. Every other field of the manifest entry is part of ``body_sha``.
WORK_META_FIELDS = ("title", "author", "author_ids", "date_composed", "date_range",
                    "date_confidence", "genre", "language", "tradition", "license",
                    "provenance_url", "edition", "translation_of", "author_date_range")
#: Chunk fields that only metadata depends on (the dates); the rest is body.
CHUNK_META_FIELDS = ("date_composed", "date_range", "date_confidence", "out_of_period")


def body_sha(entry: dict, chunks: list[dict], files: Iterable[Path]) -> str:
    """Hash of what a work can't be updated in place without (#234).

    Like ``content_sha``, but without the metadata: the work fields in
    ``WORK_META_FIELDS`` (and ``path``, ``external_ids``) and the chunk fields
    in ``CHUNK_META_FIELDS``. What is left is the work's id and source, its
    chunks (ids, refs, order, languages, texts) and the translation and vector
    *files*. Two versions of a work with the same body differ only in what
    ``update_metadata`` writes, so no vector needs re-sending.
    """
    work = {k: v for k, v in entry["work"].items()
            if k not in WORK_META_FIELDS and k != "external_ids"}
    body = [{k: v for k, v in c.items() if k not in CHUNK_META_FIELDS} for c in chunks]
    head = {"loader": LOADER_VERSION, "schema": SCHEMA_VERSION, "dims": DIMS,
            "work": work, "chunks": body}
    h = hashlib.sha256(json.dumps(head, sort_keys=True, ensure_ascii=False).encode("utf-8"))
    for path in files:
        _file_digest([h], path)
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
    text_sha = {c["chunk_id"]: tr.text_sha(source_text(c)) for c in chunks}
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
              groups: dict[str, str], models: dict[tuple[str, str], int], stats: Stats,
              body: str | None = None) -> None:
    """Replace one work and everything under it, in one transaction."""
    import numpy as np

    w = entry["work"]
    fresh: dict[str, tr.ChunkTranslation] = {}
    if translations is not None:
        rows = translations.by_chunk()
        for c in chunks:
            t = rows.get(c["chunk_id"])
            if t is not None and t.source_sha256 == tr.text_sha(source_text(c)) and t.text.strip():
                fresh[c["chunk_id"]] = t
    with conn.transaction(), conn.cursor() as cur:
        cur.execute("DELETE FROM works WHERE work_id = %s", (w["work_id"],))
        cur.execute(
            "INSERT INTO works (work_id, source_id, title, author, author_ids, date_composed, "
            "date_range, date_confidence, genre, language, tradition, license, provenance_url, "
            "edition, translation_of, author_date_range, path, content_sha, body_sha) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s::int4range, %s, %s, %s, %s, %s, %s, %s, %s, "
            "%s::int4range, %s, %s, %s)",
            (w["work_id"], w["source_id"], w["title"], w.get("author"), w.get("author_ids", []),
             w.get("date_composed"), pg_range(w.get("date_range")), w["date_confidence"],
             w["genre"], w["language"], w.get("tradition"), w["license"],
             w.get("provenance_url"), w.get("edition"), w.get("translation_of"),
             pg_range(w.get("author_date_range")), entry["path"], sha, body))
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
            "JOIN works w ON w.work_id = c.work_id", prepare=False)
        stats.vectors += len(rows)


def update_metadata(conn: psycopg.Connection, entry: dict, sha: str, body: str,
                    chunks: list[dict]) -> int:
    """Rewrite one work's metadata in place, in one transaction (#234).

    For a work whose ``body_sha`` is unchanged: the ``works`` row, the date
    fields of its ``chunks`` and the filter columns ``chunk_vectors`` copies
    from them (``genre``, ``author_ids``, ``date_range``, ``out_of_period``).
    No row is deleted and no vector is sent. Returns the number of chunks
    whose dates changed. The staging joins are never prepared (#170).
    """
    w = entry["work"]
    with conn.transaction(), conn.cursor() as cur:
        cur.execute(
            "UPDATE works SET title = %s, author = %s, author_ids = %s, date_composed = %s, "
            "date_range = %s::int4range, date_confidence = %s, genre = %s, language = %s, "
            "tradition = %s, license = %s, provenance_url = %s, edition = %s, "
            "translation_of = %s, author_date_range = %s::int4range, path = %s, "
            "content_sha = %s, body_sha = %s WHERE work_id = %s",
            (w["title"], w.get("author"), w.get("author_ids", []), w.get("date_composed"),
             pg_range(w.get("date_range")), w["date_confidence"], w["genre"], w["language"],
             w.get("tradition"), w["license"], w.get("provenance_url"), w.get("edition"),
             w.get("translation_of"), pg_range(w.get("author_date_range")), entry["path"],
             sha, body, w["work_id"]))
        with cur.copy("COPY meta_stage (chunk_id, date_composed, date_range, date_confidence, "
                      "out_of_period) FROM STDIN") as copy:
            for c in chunks:
                copy.write_row((c["chunk_id"], c.get("date_composed"),
                                pg_range(c.get("date_range")), c["date_confidence"],
                                c["out_of_period"]))
        cur.execute(
            "UPDATE chunks c SET date_composed = s.date_composed, date_range = s.date_range, "
            "date_confidence = s.date_confidence, out_of_period = s.out_of_period "
            "FROM meta_stage s WHERE c.chunk_id = s.chunk_id AND c.work_id = %s "
            "AND (c.date_composed, c.date_range, c.date_confidence, c.out_of_period) "
            "IS DISTINCT FROM (s.date_composed, s.date_range, s.date_confidence, s.out_of_period)",
            (w["work_id"],), prepare=False)
        changed = cur.rowcount
        cur.execute(
            "UPDATE chunk_vectors v SET genre = w.genre, author_ids = w.author_ids, "
            "date_range = coalesce(c.date_range, w.date_range), out_of_period = c.out_of_period "
            "FROM chunks c JOIN works w ON w.work_id = c.work_id "
            "WHERE v.chunk_id = c.chunk_id AND v.work_id = %s AND c.work_id = %s "
            "AND (v.genre, v.author_ids, v.date_range, v.out_of_period) IS DISTINCT FROM "
            "(w.genre, w.author_ids, coalesce(c.date_range, w.date_range), c.out_of_period)",
            (w["work_id"], w["work_id"]), prepare=False)
    return changed


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
    """Whether index *name* exists in the current schema (not elsewhere on the search path)."""
    return conn.execute("SELECT EXISTS (SELECT FROM pg_indexes WHERE schemaname = "
                        "current_schema() AND indexname = %s)", (name,)).fetchone()[0]


def drop_index(conn: psycopg.Connection, name: str) -> None:
    """Drop index *name* of the current schema, if it exists.

    The name is schema-qualified: a bare name would drop the first index of
    that name on the search path, possibly another schema's.
    """
    from psycopg import sql

    schema = conn.execute("SELECT current_schema()").fetchone()[0]
    conn.execute(sql.SQL("DROP INDEX IF EXISTS {}.{}").format(sql.Identifier(schema),
                                                               sql.Identifier(name)))


def check_fold_version(conn: psycopg.Connection) -> None:
    """Make every stored ``text_folded`` current for ``FOLD_VERSION``, or NULL.

    ``index_meta.fold_version`` is the version every non-NULL
    ``text_folded`` was made with, and NULL rows are the folding still to
    do. When the version changes, the old text is cleared and the new
    version recorded in one transaction, so a later run, even one limited to
    some sources or an interrupted one, never clears work already done (#168).
    """
    meta = conn.execute("SELECT value FROM index_meta WHERE key = 'fold_version'").fetchone()
    if meta is not None and meta[0] == str(FOLD_VERSION):
        return
    with conn.transaction():
        if meta is not None:
            log.info("fold version %s -> %s: refolding every chunk", meta[0], FOLD_VERSION)
            drop_index(conn, TRGM_INDEX)
            conn.execute("UPDATE chunks SET text_folded = NULL")
        conn.execute("INSERT INTO index_meta VALUES ('fold_version', %s) ON CONFLICT (key) "
                      "DO UPDATE SET value = EXCLUDED.value", (str(FOLD_VERSION),))


def fold_missing(conn: psycopg.Connection, paths: dict[str, Path],
                 maintenance_work_mem: str) -> int:
    """Fill ``text_folded`` where it is NULL, then make sure the trigram index exists.

    *paths* maps each work this run checked (its stored hash matches the
    files, or it was just loaded) to its normalized file, which therefore
    holds exactly the text in the database. Other works stay unfolded until
    a run that covers them. Returns the number of chunks folded.
    """
    pending = conn.execute("SELECT count(*) FROM chunks WHERE text_folded IS NULL").fetchone()[0]
    todo = [w for (w,) in conn.execute(
        "SELECT DISTINCT work_id FROM chunks WHERE text_folded IS NULL") if w in paths]
    if pending > BULK_FOLD and has_index(conn, TRGM_INDEX):
        log.info("dropping %s to fold %d chunks", TRGM_INDEX, pending)
        drop_index(conn, TRGM_INDEX)
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
                        "WHERE c.chunk_id = s.chunk_id AND c.text_folded IS NULL", prepare=False)
            folded += cur.rowcount
    if not has_index(conn, TRGM_INDEX):
        log.info("building %s (keyword index, #86)", TRGM_INDEX)
        conn.execute("SELECT set_config('maintenance_work_mem', %s, false)",
                     (maintenance_work_mem,))
        conn.execute(f"CREATE INDEX {TRGM_INDEX} ON chunks USING gin (text_folded gin_trgm_ops)")
    if folded > BULK_FOLD:
        # Every folded row was rewritten: make the old versions' space reusable.
        conn.execute("VACUUM chunks")
    return folded


def stored_groups(conn: psycopg.Connection) -> dict[str, dict[str, str]]:
    """work_id → {chunk_id: translation_group_id} of the stored chunks that have a group."""
    groups: dict[str, dict[str, str]] = {}
    for work_id, chunk_id, group in conn.execute(
            "SELECT work_id, chunk_id, translation_group_id FROM chunks "
            "WHERE translation_group_id IS NOT NULL"):
        groups.setdefault(work_id, {})[chunk_id] = group
    return groups


def group_changes(want: dict[str, str], have: dict[str, str]) -> dict[str, str | None]:
    """chunk_id → new group (None: no group) for the chunks whose group differs."""
    return {cid: want.get(cid) for cid in want.keys() | have.keys()
            if want.get(cid) != have.get(cid)}


def sync_groups(conn: psycopg.Connection, changes: dict[str, dict[str, str | None]]) -> int:
    """Apply *changes* (work_id → ``group_changes``) to ``chunks``, one transaction per work.

    Only ``chunks.translation_group_id`` changes: no work is reloaded and no
    vector is touched (#186). Returns the number of chunks updated.
    """
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS group_stage (chunk_id text, "
                 "translation_group_id text) ON COMMIT DELETE ROWS")
    updated = 0
    for work_id in tqdm(sorted(changes), desc="regroup", unit="work"):
        with conn.transaction(), conn.cursor() as cur:
            with cur.copy("COPY group_stage (chunk_id, translation_group_id) FROM STDIN") as copy:
                for row in changes[work_id].items():
                    copy.write_row(row)
            cur.execute("UPDATE chunks c SET translation_group_id = s.translation_group_id "
                        "FROM group_stage s WHERE c.chunk_id = s.chunk_id AND c.work_id = %s "
                        "AND c.translation_group_id IS DISTINCT FROM s.translation_group_id",
                        (work_id,), prepare=False)
            updated += cur.rowcount
    return updated


PassageRows = dict[str, dict[str, tuple[str, int]]]  # work_id → chunk_id → (group, conf)


def passage_rows(align_dir: Path, paths: dict[str, Path],
                 stale: list[str] | None = None) -> PassageRows:
    """The ``passage_groups`` rows of the works in *paths* (work_id → normalized file).

    A group is ``{version group}@{n}`` and holds the spans at
    ``alignment_store.MIN_CONFIDENCE`` or more of the members in *paths* whose
    chunk ids are those the alignment counted; it needs two such members.
    Members whose ids changed are appended to *stale*.
    """
    rows: PassageRows = {}
    def wanted(work_ids: list[str]) -> bool:
        return sum(w in paths for w in work_ids) >= 2

    for _, a in al.iter_store(align_dir, wanted):
        live = [w for w in a.members if w in paths]
        ids: dict[str, list[str]] = {}
        for wid in live:
            with paths[wid].open(encoding="utf-8") as f:
                chunk_ids = [c["chunk_id"] for c in json.load(f)]
            if al.ids_sha(chunk_ids) == a.members[wid].ids:
                ids[wid] = chunk_ids
            elif stale is not None:
                stale.append(wid)
        a.members = {w: m for w, m in a.members.items() if w in ids}
        for g, spans in a.groups_of().items():
            gid = f"{a.group}@{g}"
            for wid, (start, end) in spans.items():
                conf = a.members[wid].conf.get(g, 0)
                if wid == a.pivot:
                    conf = max(a.members[w].conf.get(g, 0) for w in spans if w != wid)
                out = rows.setdefault(wid, {})
                for cid in ids[wid][start:end]:
                    out[cid] = (gid, conf)
    return rows


def stored_passages(conn: psycopg.Connection) -> PassageRows:
    rows: PassageRows = {}
    for work_id, chunk_id, group_id, conf in conn.execute(
            "SELECT c.work_id, p.chunk_id, p.group_id, p.confidence FROM passage_groups p "
            "JOIN chunks c USING (chunk_id)"):
        rows.setdefault(work_id, {})[chunk_id] = (group_id, conf)
    return rows


def passage_changes(want: PassageRows, have: PassageRows, works: Iterable[str]
                    ) -> dict[str, dict[str, tuple[str, int] | None]]:
    """work_id → chunk_id → new row (None: delete), for the *works* whose rows differ."""
    out: dict[str, dict[str, tuple[str, int] | None]] = {}
    for work_id in works:
        w, h = want.get(work_id, {}), have.get(work_id, {})
        diff = {cid: w.get(cid) for cid in w.keys() | h.keys() if w.get(cid) != h.get(cid)}
        if diff:
            out[work_id] = diff
    return out


def sync_passages(conn: psycopg.Connection,
                  changes: dict[str, dict[str, tuple[str, int] | None]]) -> int:
    """Apply *changes* to ``passage_groups``, one transaction per work.

    Only ``passage_groups`` is written: no work is reloaded and no vector is
    touched. Returns the number of rows written or deleted.
    """
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS passage_stage (chunk_id text, "
                 "group_id text, confidence smallint) ON COMMIT DELETE ROWS")
    n = 0
    for work_id in tqdm(sorted(changes), desc="passage groups", unit="work"):
        diff = changes[work_id]
        gone = sorted(cid for cid, row in diff.items() if row is None)
        with conn.transaction(), conn.cursor() as cur:
            if gone:
                cur.execute("DELETE FROM passage_groups WHERE chunk_id = ANY(%s)", (gone,),
                            prepare=False)
                n += cur.rowcount
            new = [(cid, *row) for cid, row in sorted(diff.items()) if row is not None]
            if new:
                with cur.copy("COPY passage_stage (chunk_id, group_id, confidence) "
                              "FROM STDIN") as copy:
                    for row in new:
                        copy.write_row(row)
                cur.execute("INSERT INTO passage_groups (chunk_id, group_id, confidence) "
                            "SELECT s.chunk_id, s.group_id, s.confidence FROM passage_stage s "
                            "JOIN chunks c ON c.chunk_id = s.chunk_id "
                            "ON CONFLICT (chunk_id) DO UPDATE SET group_id = EXCLUDED.group_id, "
                            "confidence = EXCLUDED.confidence", prepare=False)
                n += cur.rowcount
    return n


def _has_table(conn: psycopg.Connection, name: str) -> bool:
    return conn.execute("SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = "
                        "current_schema() AND tablename = %s)", (name,)).fetchone()[0]


def stored_bodies(conn: psycopg.Connection) -> dict[str, str | None]:
    """work_id → stored ``body_sha`` (None: not computed yet, hash format below 3).

    A dry run can see a database from before the column existed: every value
    is then None, as the real run will find it after adding the column.
    """
    has_column = conn.execute(
        "SELECT EXISTS (SELECT FROM information_schema.columns WHERE table_schema = "
        "current_schema() AND table_name = 'works' AND column_name = 'body_sha')").fetchone()[0]
    if not has_column:
        return {r[0]: None for r in conn.execute("SELECT work_id FROM works")}
    return dict(conn.execute("SELECT work_id, body_sha FROM works"))


def hash_format(conn: psycopg.Connection) -> int:
    """The format of the stored ``content_sha`` values (``HASH_FORMAT``).

    No ``index_meta`` table, or no ``hash_format`` row, means a database loaded
    before #186: format 1. (A dry run sees such a database before the schema is
    applied, so it must agree with the real run, which creates the table first.)
    An empty database has no hashes to migrate, and the real run records the
    current format as soon as it finds no works.
    """
    if not conn.execute("SELECT EXISTS (SELECT FROM pg_tables WHERE schemaname = "
                        "current_schema() AND tablename = 'index_meta')").fetchone()[0]:
        return 1
    row = conn.execute("SELECT value FROM index_meta WHERE key = 'hash_format'").fetchone()
    return 1 if row is None else int(row[0])


def set_hash_format(conn: psycopg.Connection) -> None:
    conn.execute("INSERT INTO index_meta VALUES ('hash_format', %s) ON CONFLICT (key) "
                 "DO UPDATE SET value = EXCLUDED.value", (str(HASH_FORMAT),))


CODE_KEY = "code"


def build_index_code_hash() -> str:
    """Hash of this step's code (``patristica.fingerprint``, #130)."""
    from patristica import fingerprint

    return fingerprint.code_hash("scripts.build_index")


def stored_code(conn: psycopg.Connection) -> str | None:
    """The code hash of the last full run (``index_meta.code``), if any.

    It is recorded for ``scripts.status`` only and never decides what is
    reloaded: a code change that should change the stored data bumps
    ``LOADER_VERSION`` (part of every work's ``content_sha``) instead.
    """
    if not _has_table(conn, "index_meta"):
        return None
    row = conn.execute("SELECT value FROM index_meta WHERE key = %s", (CODE_KEY,)).fetchone()
    return row[0] if row else None


def run(conn: psycopg.Connection, input_dir: Path, trans_dir: Path, store_dir: Path, *,
        sources: Iterable[str] = (), prefixes: Iterable[str] = (), dry_run: bool = False,
        rebuild_index: bool = False, maintenance_work_mem: str = "4GB",
        align_dir: Path = al.DEFAULT_DIR) -> Stats:
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
        fmt = hash_format(conn)
    else:
        apply_schema(conn)
        # Before loading, so works loaded below aren't cleared again.
        check_fold_version(conn)
        log.info("authors: %d", load_authors(conn))
        stored = dict(conn.execute("SELECT work_id, content_sha FROM works"))
        if not stored:
            set_hash_format(conn)  # every hash will be new
        fmt = hash_format(conn)
        empty = conn.execute("SELECT NOT EXISTS (SELECT FROM chunk_vectors)").fetchone()[0]
        if empty or rebuild_index:
            for index in hnsw_indexes(conn):
                log.info("dropping %s for the bulk load", index)
                drop_index(conn, index)
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS vector_stage (chunk_id text, "
                     "kind smallint, model_id smallint, embedding halfvec(512)) "
                     "ON COMMIT DELETE ROWS")
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS meta_stage (chunk_id text, "
                     "date_composed integer, date_range int4range, date_confidence text, "
                     "out_of_period boolean) ON COMMIT DELETE ROWS")
    bodies = stored_bodies(conn) if stored else {}

    gone = set(stored) & excluded
    if not sources and not prefixes:
        gone |= set(stored) - {e["work"]["work_id"] for e in publishable}
    stats.excluded = len(set(stored) & excluded)
    stats.deleted = len(gone)
    if gone and not dry_run:
        log.info("deleting %d works", len(gone))
        conn.execute("DELETE FROM works WHERE work_id = ANY(%s)", (sorted(gone),))

    groups = scripture_groups(publishable, input_dir)
    have_groups = stored_groups(conn) if stored else {}
    models: dict[tuple[str, str], int] = {}
    checked: dict[str, Path] = {}  # works whose stored text matches their file
    rehash: dict[str, str] = {}  # work_id → new hash, for unchanged works with a format-1 hash
    backfill: dict[str, str] = {}  # work_id → body_sha, for unchanged works without one
    loaded: set[str] = set()
    for entry in tqdm(wanted, desc="works", unit="work"):
        path = entry["path"]
        work_id = entry["work"]["work_id"]
        norm = input_dir / path
        tpath = tr.translation_path(trans_dir, path)
        spath = emb.shard_path(store_dir, path)
        work_groups = groups.get(work_id, {})
        legacy = have_groups.get(work_id, {}) if fmt == 1 and work_id in stored else None
        sha, old_sha = content_shas(entry, (norm, tpath, spath), legacy)
        if work_id in stored and stored[work_id] in (sha, old_sha):
            if stored[work_id] != sha:
                rehash[work_id] = sha
            if bodies.get(work_id) is None:
                # Hash format 3 (#234): the stored work is the current one, so
                # its body hash can be computed from the files, in place.
                stats.backfilled += 1
                if not dry_run:
                    with norm.open(encoding="utf-8") as f:
                        backfill[work_id] = body_sha(entry, json.load(f), (tpath, spath))
            stats.unchanged += 1
            checked[work_id] = norm
            continue
        with norm.open(encoding="utf-8") as f:
            chunks = json.load(f)
        body = body_sha(entry, chunks, (tpath, spath))
        if work_id in stored and bodies.get(work_id) == body:
            # Only metadata changed: update it in place, no vector is re-sent.
            stats.updated += 1
            if not dry_run:
                stats.updated_chunks += update_metadata(conn, entry, sha, body, chunks)
            checked[work_id] = norm
            continue
        stats.loaded += 1
        if dry_run:
            continue
        load_work(conn, entry, sha, chunks, tr.load(trans_dir, path), emb.load(store_dir, path),
                  work_groups, models, stats, body)
        loaded.add(work_id)
        checked[work_id] = norm

    # Unchanged works keep their chunks: bring their groups up to date in place.
    changes: dict[str, dict[str, str | None]] = {}
    for work_id in checked.keys() - loaded:
        diff = group_changes(groups.get(work_id, {}), have_groups.get(work_id, {}))
        if diff:
            changes[work_id] = diff
    stats.rehashed = len(rehash)
    # Passage groups (#179) of the works whose stored chunks match their files.
    want_passages = passage_rows(align_dir, checked, stats.stale_alignments)
    # (A dry run can see a database from before the table existed.)
    have_passages = (stored_passages(conn) if stored and _has_table(conn, "passage_groups")
                     else {})
    passages = passage_changes(want_passages, have_passages, checked)
    if dry_run:
        stats.regrouped = sum(map(len, changes.values()))
        stats.passages = sum(map(len, passages.values()))
        return stats
    if rehash:
        conn.execute("UPDATE works w SET content_sha = r.sha FROM unnest(%s::text[], %s::text[]) "
                     "AS r(work_id, sha) WHERE w.work_id = r.work_id",
                     (list(rehash), list(rehash.values())))
    if backfill:
        conn.execute("UPDATE works w SET body_sha = r.sha FROM unnest(%s::text[], %s::text[]) "
                     "AS r(work_id, sha) WHERE w.work_id = r.work_id",
                     (list(backfill), list(backfill.values())))
    if fmt != HASH_FORMAT and not sources and not prefixes:
        # A full run: every stored hash is now of this format.
        set_hash_format(conn)
    stats.regrouped = sync_groups(conn, changes)
    stats.passages = sync_passages(conn, passages)
    stats.folded = fold_missing(conn, checked, maintenance_work_mem)
    # Also after an index build alone: a rerun after a failed build loads
    # nothing, and the first run never got to its ANALYZE.
    built = build_hnsw(conn, maintenance_work_mem)
    if (built or stats.loaded or stats.updated or stats.deleted or stats.folded
            or stats.regrouped or stats.passages):
        conn.execute("ANALYZE works, chunks, chunk_translations, chunk_vectors, passage_groups")
    if not sources and not prefixes:
        conn.execute("INSERT INTO index_meta VALUES (%s, %s) ON CONFLICT (key) "
                     "DO UPDATE SET value = EXCLUDED.value", (CODE_KEY, build_index_code_hash()))
    return stats


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--database-url", help="default: DATABASE_URL (environment or .env)")
    parser.add_argument("--input-dir", type=Path, default=Path("data/normalized"))
    parser.add_argument("--translations-dir", type=Path, default=tr.DEFAULT_DIR)
    parser.add_argument("--embeddings-dir", type=Path, default=emb.DEFAULT_DIR)
    parser.add_argument("--alignments-dir", type=Path, default=al.DEFAULT_DIR,
                        help="passage alignments (scripts.align, #179)")
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
                    maintenance_work_mem=args.maintenance_work_mem,
                    align_dir=args.alignments_dir)
    log.info("%s%s", "dry run: " if args.dry_run else "", stats.summary())
    if stats.stale_alignments:
        log.warning("%d works changed since they were aligned, so they have no passage groups: "
                    "run scripts.align (%s)", len(stats.stale_alignments),
                    ", ".join(sorted(stats.stale_alignments)[:10]))
    if stats.stale_vectors:
        log.warning("%d vectors embed outdated text: run scripts.embed, then this again",
                    stats.stale_vectors)


if __name__ == "__main__":
    main()
