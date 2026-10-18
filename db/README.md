# Search database

`schema.sql` is the schema of the Postgres + pgvector database behind search (#137, IMPLEMENTATION_PLAN.md §2.2). `scripts.build_index` applies it on every run and loads the corpus into it:

| Table | Rows | From |
|---|---|---|
| `authors` | one per person | `patristica/data/authors.csv` (#82), replaced on every run |
| `works` | one per publishable work | `data/normalized/_works.jsonl`; `content_sha` drives incremental reloads |
| `chunks` | every unit, including those too short to embed | `data/normalized/`; Scripture gets `translation_group_id` |
| `chunk_translations` | fresh machine translations | `data/translations/` (#93) |
| `embedding_models` | one per vector space (model, dims, input type) | the runs recorded in `data/embeddings/` |
| `chunk_vectors` | one per (chunk, kind, model), `halfvec(512)` | `data/embeddings/` (#136), cut to 512 dims and renormalized |

- `chunk_vectors.kind` is 0 for the chunk's own text and 1 for its English translation (Syriac, Coptic, Armenian, Ge'ez). A search scores a chunk by the better of the two.
- `chunk_vectors` repeats the filter columns of its chunk and work (`work_id`, `source_id`, `language`, `genre`, `author_ids`, `date_range`, `out_of_period`), so a filtered vector search reads a single table.
- Each model has a partial HNSW index, `chunk_vectors_hnsw_m{model_id}` (`halfvec_cosine_ops`, `m = 16`, `ef_construction = 64`, `WHERE model_id = …`). A query must use the same `model_id` condition to use it. `build_index` creates the index after a bulk load.
- Year ranges are `int4range` with inclusive input (`[350,373]`), which Postgres shows as `[350,374)`.

## Loading

```bash
# Locally (DATABASE_URL in the environment or .env):
uv run --extra index python -m scripts.build_index --dry-run
uv run --extra index python -m scripts.build_index

# The droplet, through an SSH tunnel to the db container:
infra/db-tunnel.sh uv run --extra index python -m scripts.build_index
```

Only works whose inputs changed are reloaded. The first full load sends about 4 GB of vectors over the tunnel and then builds the HNSW index on the droplet; see `infra/README.md` → "Search index".

## Schema changes

`schema.sql` only creates what is missing, so changing an existing table needs more than an edit. Bump `SCHEMA_VERSION` in both `schema.sql` and `scripts/build_index.py`. Then either write the migration here, or rebuild: drop the tables and run `build_index` again. The loader refuses to run against a database with a different version.
