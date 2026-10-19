-- Search database schema (#137; IMPLEMENTATION_PLAN.md §2.2).
--
-- Idempotent: scripts.build_index applies this file on every run, so it only
-- creates what is missing. A change that alters an existing table bumps
-- SCHEMA_VERSION here and in scripts/build_index.py, and adds the migration
-- (or a note to rebuild from scratch) to db/README.md.
--
-- The HNSW indexes are not here: there is one partial index per embedding
-- model (chunk_vectors_hnsw_m{model_id}), and build_index creates it after a
-- bulk load, which is much faster than inserting into a live index.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE TABLE IF NOT EXISTS schema_version (
    version integer NOT NULL
);
INSERT INTO schema_version (version)
SELECT 1 WHERE NOT EXISTS (SELECT FROM schema_version);

-- The author index (patristica/data/authors.csv, #82). Replaced on every load.
CREATE TABLE IF NOT EXISTS authors (
    author_id   text PRIMARY KEY,
    name        text NOT NULL,
    aliases     text[] NOT NULL DEFAULT '{}',
    birth       jsonb,          -- {"low", "high", "confidence"} (Author.to_json)
    death       jsonb,
    floruit     jsonb,
    tradition   text,
    pseudo_of   text
);

-- One row per work in data/normalized/_works.jsonl, except EXCLUDED_LICENSES.
CREATE TABLE IF NOT EXISTS works (
    work_id         text PRIMARY KEY,
    source_id       text NOT NULL,
    title           text NOT NULL,
    author          text,                       -- the source's spelling (provenance)
    author_ids      text[] NOT NULL DEFAULT '{}',
    date_composed   integer,
    date_range      int4range,                  -- inclusive years, '[lo,hi]'
    date_confidence text NOT NULL,
    genre           text NOT NULL,
    language        text NOT NULL,
    tradition       text,
    license         text NOT NULL,
    provenance_url  text,
    edition         text,
    translation_of  text,
    path            text NOT NULL,              -- under data/normalized/
    content_sha     text NOT NULL               -- of everything loaded for the work
);
CREATE INDEX IF NOT EXISTS works_author_ids ON works USING gin (author_ids);

-- Every unit of every work, including the ones too short to embed.
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id             text PRIMARY KEY,
    work_id              text NOT NULL REFERENCES works ON DELETE CASCADE,
    canonical_ref        text NOT NULL,
    chunk_index          integer NOT NULL,
    language             text NOT NULL,
    text                 text NOT NULL,
    date_composed        integer,
    date_range           int4range,
    date_confidence      text NOT NULL,
    out_of_period        boolean NOT NULL,
    translation_group_id text,                  -- Scripture only (link_translations)
    text_folded          text                   -- keyword index (#86): ' ' || fold(text) || ' '
);
-- Added after the first production load; build_index folds rows where it is NULL.
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS text_folded text;
CREATE INDEX IF NOT EXISTS chunks_work ON chunks (work_id, chunk_index);
-- Finds the works still to fold without scanning the table (empty once all are).
CREATE INDEX IF NOT EXISTS chunks_unfolded ON chunks (work_id) WHERE text_folded IS NULL;
-- The trigram index on text_folded (chunks_text_folded_trgm) is created by
-- build_index after the folding, like the HNSW indexes.
CREATE INDEX IF NOT EXISTS chunks_translation_group ON chunks (translation_group_id)
    WHERE translation_group_id IS NOT NULL;

-- Passage alignment groups (data/alignments/, #179): the chunks of the
-- versions of a work that render one passage share a group_id
-- ('{version group}@{n}'). Search folds versions by it (api/passages.py).
-- Synced in place by build_index, never through a work's content hash, so a
-- new alignment reloads no work and no vector. Only spans at
-- alignment_store.MIN_CONFIDENCE or more are here.
CREATE TABLE IF NOT EXISTS passage_groups (
    chunk_id    text PRIMARY KEY REFERENCES chunks ON DELETE CASCADE,
    group_id    text NOT NULL,
    confidence  smallint NOT NULL               -- tenths (0-9)
);
CREATE INDEX IF NOT EXISTS passage_groups_group ON passage_groups (group_id);

-- Settings the stored data was built with, e.g. fold_version
-- (patristica.keyword.FOLD_VERSION): when it changes, every chunk is refolded.
CREATE TABLE IF NOT EXISTS index_meta (
    key     text PRIMARY KEY,
    value   text NOT NULL
);

-- Machine translations (data/translations/, #93), only those made from the
-- chunk's current text.
CREATE TABLE IF NOT EXISTS chunk_translations (
    chunk_id        text NOT NULL REFERENCES chunks ON DELETE CASCADE,
    language        text NOT NULL,
    text            text NOT NULL,
    model           text NOT NULL,
    prompt_version  text NOT NULL,
    date            date NOT NULL,
    PRIMARY KEY (chunk_id, language)
);

-- A vector space: the model, the stored dims and the input type. Vectors are
-- only comparable within one model_id, and a query must be embedded the same
-- way (with input_type "query").
CREATE TABLE IF NOT EXISTS embedding_models (
    model_id    smallint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    name        text NOT NULL,                  -- e.g. 'voyage/voyage-4-large'
    dims        integer NOT NULL,
    input_type  text NOT NULL,
    UNIQUE (name, dims, input_type)
);

-- One vector per (chunk, kind, model). kind 0 embeds the chunk's text, kind 1
-- its English translation (Syriac, Coptic, Armenian, Ge'ez; #84). The columns
-- after the embedding are copied from the chunk and its work, so a filtered
-- search reads this table only.
CREATE TABLE IF NOT EXISTS chunk_vectors (
    chunk_id        text NOT NULL REFERENCES chunks ON DELETE CASCADE,
    kind            smallint NOT NULL,
    model_id        smallint NOT NULL REFERENCES embedding_models,
    embedding       halfvec(512) NOT NULL,
    work_id         text NOT NULL,
    source_id       text NOT NULL,
    language        text NOT NULL,              -- the chunk's, also for kind 1
    genre           text NOT NULL,
    author_ids      text[] NOT NULL,
    date_range      int4range,                  -- the chunk's, else the work's
    out_of_period   boolean NOT NULL,
    PRIMARY KEY (chunk_id, kind, model_id)
);
-- For narrow filters the planner can pick these and compute exact distances
-- over the few matching rows instead of walking the HNSW graph.
CREATE INDEX IF NOT EXISTS chunk_vectors_work ON chunk_vectors (work_id);
CREATE INDEX IF NOT EXISTS chunk_vectors_source ON chunk_vectors (source_id);
CREATE INDEX IF NOT EXISTS chunk_vectors_language ON chunk_vectors (language);
CREATE INDEX IF NOT EXISTS chunk_vectors_author_ids ON chunk_vectors USING gin (author_ids);
