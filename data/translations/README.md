# Machine translations

English translations of Syriac, Coptic, Armenian and Ge'ez chunks, used to
index those languages for search (#84, #93). Format and helpers:
`patristica/translations.py`.

## Layout

This directory mirrors `data/normalized/`. The translations of the work at
`data/normalized/{path}` are in `data/translations/{path}`, where `path` is the
work's `path` in `_works.jsonl`. Only works with translated chunks have a
file. The model is part of each file's metadata, not of the path.

## File format

Each file is one JSON object, pretty-printed like the normalized files:

| field | meaning |
|---|---|
| `work_id`, `source_path` | the work translated, and its path under `data/normalized/` |
| `source_language`, `target_language` | ISO 639-3 codes (`target_language` is `eng`) |
| `provenance` | the translation runs used in this file, keyed `{model}/{prompt_version}/{date}`. Each has `model`, `prompt_version` (the prompt in `scripts/translate.py`), `date` and `script` |
| `translations` | one row per translated chunk, in normalized chunk order |

Each row in `translations`:

| field | meaning |
|---|---|
| `chunk_id` | the chunk translated |
| `source_sha256` | first 16 hex digits of the SHA-256 of the exact source text. A row is used only while the chunk's text still matches. |
| `provenance` | key into the file's `provenance` table |
| `group_size` | how many consecutive chunks of the work were translated in one request |
| `text` | English translation |

There is one translation per chunk. Re-translating a chunk replaces its row.
When a file is written, rows for chunks that changed or no longer exist are
dropped, and so are provenance entries no row uses.

## Producing it

`python -m scripts.translate` (run `--dry-run` first to see the chunk count and
estimated cost). It skips chunks with a fresh translation and reuses
translations of identical text, so reruns only pay for new or changed text.
Works with an `unknown` licence (Hudra) are kept out of the search index and
are skipped unless you pass `--include-unpublishable`.

## Licensing

A machine translation with no human authorship is probably not copyrightable
on its own; the US Copyright Office takes that position. Our policy is still
to treat each translation as bound by its source edition's licence
(`Work.license` in `_works.jsonl`; see `DATA_LICENSE.md`), because the edition
we translated from may carry terms (share-alike, non-commercial) whether or
not the translation is copyrightable. The licence is not copied into these
files: `_works.jsonl` records it once. If translations are ever shown to users
rather than only indexed, label them as AI translations.
