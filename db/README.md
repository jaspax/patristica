# Search database

`schema.sql` is the schema of the Postgres + pgvector database behind search (#137, IMPLEMENTATION_PLAN.md §2.2). `scripts.build_index` applies it on every run and loads the corpus into it:

| Table | Rows | From |
|---|---|---|
| `authors` | one per person | `patristica/data/authors.csv` (#82), replaced on every run |
| `works` | one per publishable work | `data/normalized/_works.jsonl`; `content_sha` drives incremental reloads |
| `chunks` | every unit, including those too short to embed | `data/normalized/`; Scripture gets `translation_group_id`, updated in place when the groups change (#186) |
| `chunk_translations` | fresh machine translations | `data/translations/` (#93) |
| `passage_groups` | one per chunk in a passage alignment group: `group_id` (`{version group}@{n}`), `confidence` (tenths) | `data/alignments/` (#179), spans at confidence ≥ 5; synced in place |
| `index_meta` | settings the data was built with (`fold_version`, `hash_format`) | `scripts.build_index` |
| `embedding_models` | one per vector space (model, dims, input type) | the runs recorded in `data/embeddings/` |
| `chunk_vectors` | one per (chunk, kind, model), `halfvec(512)` | `data/embeddings/` (#136), cut to 512 dims and renormalized |

- `chunk_vectors.kind` is 0 for the chunk's own text and 1 for its English translation (Syriac, Coptic, Armenian, Ge'ez). A search scores a chunk by the better of the two.
- `chunk_vectors` repeats the filter columns of its chunk and work (`work_id`, `source_id`, `language`, `genre`, `author_ids`, `date_range`, `out_of_period`), so a filtered vector search reads a single table.
- Each model has a partial HNSW index, `chunk_vectors_hnsw_m{model_id}` (`halfvec_cosine_ops`, `m = 16`, `ef_construction = 64`, `WHERE model_id = …`). A query must use the same `model_id` condition to use it. `build_index` creates the index after a bulk load.
- `chunks.text_folded` is the keyword index for quoted search (#86): `' ' || fold(text) || ' '` (`patristica.keyword.index_text`) under the `pg_trgm` GIN index `chunks_text_folded_trgm`, which `build_index` creates after folding. A phrase matches as whole words: `text_folded LIKE '% folded phrase %'` (`api/keyword.py`). When `patristica.keyword.FOLD_VERSION` changes, `build_index` refolds every chunk.
- Year ranges are `int4range` with inclusive input (`[350,373]`), which Postgres shows as `[350,374)`.

## Loading

```bash
# Locally (DATABASE_URL in the environment or .env):
uv run --extra index python -m scripts.build_index --dry-run
uv run --extra index python -m scripts.build_index

# The droplet, through an SSH tunnel to the db container:
infra/db-tunnel.sh uv run --extra index python -m scripts.build_index
```

Only works whose inputs changed are reloaded. A change of Scripture translation groups (a versification override) is not a change of inputs: `build_index` compares the computed groups with `chunks.translation_group_id` and updates only the chunks that differ, so no vectors are re-sent (#186). Passage alignment groups (#179) work the same way: `build_index` computes the rows of `passage_groups` from `data/alignments/` for every work whose stored hash it checked, and writes or deletes only the rows that differ. A work whose chunk ids changed since it was aligned gets no rows until `scripts.align` runs again (the summary warns).

A work whose `content_sha` changed is reloaded only if its body changed too (#234). `works.body_sha` hashes what can't be rewritten in place: the work id and source, the chunks without their dates (ids, refs, order, languages, texts), and the translation and vector files. When only the metadata changed, `build_index` updates the work in place, in one transaction, and sends no vectors. The metadata is the rest of the work record (title, author, `author_ids`, dates, genre, language, tradition, licence, edition, provenance, `translation_of`, path) plus the chunks' `date_composed`, `date_range`, `date_confidence` and `out_of_period`. The update covers the `works` row, the chunks' date fields, and the filter columns `chunk_vectors` copies from them (`genre`, `author_ids`, `date_range`, `out_of_period`). The column was added after the first production load (hash format 3). While `index_meta.hash_format` is below 3, an unchanged work without a `body_sha` gets it computed from its files and stored in place, so the first run of the new loader reloads nothing (it reads every normalized file once). A work that changed *and* has no `body_sha` yet is reloaded as before, so run the new loader once before merging metadata-only data changes. `scripts.status --db --vectors data/embeddings` lists works to load, works to update in place and body hashes to fill in separately.

The first full load sends about 4 GB of vectors over the tunnel and then builds the HNSW index on the droplet; see `infra/README.md` → "Search index".

## Schema changes

`schema.sql` only creates what is missing, so changing an existing table needs more than an edit. Bump `SCHEMA_VERSION` in both `schema.sql` and `scripts/build_index.py`. Then either write the migration here, or rebuild: drop the tables and run `build_index` again. The loader refuses to run against a database with a different version.
