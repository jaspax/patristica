# Patristica — Claude Code Instructions

## Project Overview

Patristica is a searchable database of Scriptural and Patristic writings up to the Great Schism (1054 CE), with a web frontend. The project proceeds in three phases: data collection, database construction, and web app. See `IMPLEMENTATION_PLAN.md` for the high-level overview and `DATA_COLLECTION_PLAN.md` for the detailed Phase 1 plan.

## Tech Stack

- **Language**: Python 3.11+
- **Data models**: Pydantic v2
- **HTTP**: `httpx` (async-capable) preferred over `requests`
- **XML parsing**: `lxml` for TEI/OSIS/USFM; `beautifulsoup4` for HTML scraping
- **Token counting**: `tiktoken` (cl100k_base encoding)
- **Package management**: `pyproject.toml` with `uv` for environment management
- **Database** (Phase 2): PostgreSQL 16 + pgvector
- **Backend API** (Phase 3): FastAPI
- **Frontend** (Phase 3): Next.js 14+ / React / TypeScript
- **AI features** (Phase 3): Claude API (Anthropic)

## Repository Structure

```
patristica/
├── CLAUDE.md                  # this file
├── IMPLEMENTATION_PLAN.md     # high-level 3-phase plan
├── DATA_COLLECTION_PLAN.md    # detailed Phase 1 plan (living document — check off milestones)
├── patristica/
│   └── models.py              # Pydantic data models (Work, Chunk)
├── scripts/
│   ├── ingest/
│   │   ├── _common.py         # shared utilities: download, parse_tei, parse_osis, etc.
│   │   ├── all.py             # run all ingestors
│   │   └── {source_id}.py     # one module per source
│   ├── normalize.py           # raw → normalized Chunk JSON
│   ├── chunk.py               # normalized → chunked records
│   ├── link_translations.py   # assign translation_group_id across parallel chunks
│   ├── validate.py            # QC checks; outputs data/validation_report.json
│   └── catalog.py             # print ingestion status table
└── data/
    ├── raw/                   # downloaded source files (large; gitignored)
    ├── normalized/            # normalized Work/Chunk JSON (one file per work)
    └── chunks/                # chunked records ready for embedding
```

## Data Models

See `patristica/models.py`. Key types:

- **`Work`**: metadata for a single work (author, title, language, date, license, genre, tradition)
- **`Chunk`**: one text unit (verse, paragraph, stanza) with `canonical_ref`, `language`, `text`, optional `translation_group_id`

### Language codes (ISO 639-3)
`grc` Greek · `lat` Latin · `hbo` Hebrew · `syc` Syriac · `cop` Coptic · `gez` Ge'ez · `hye` Armenian · `got` Gothic · `eng` English

### Genre values
`scripture` · `patristic` · `liturgical` · `council`

### Canonical reference format
Dot-separated: `Gen.1.1`, `Aug.Conf.1.1.1`, `ByzLit.Chrysostom.Anaphora.3`, `Nicaea1.Canon.7`

## Ingestion Modules

Every module in `scripts/ingest/` must implement:

```python
def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """
    Download/parse source. Write one JSON file per work to output_dir/raw/{source_id}/.
    Skip already-downloaded files unless force=True (idempotent).
    Returns list of Work metadata records.
    """
```

Use `_common.py` utilities for HTTP downloads, TEI/OSIS parsing, and HTML cleaning. Do not duplicate parsing logic across modules.

## Coding Conventions

- All functions that do I/O should be idempotent (re-running produces the same result, skips already-done work)
- Log progress with `tqdm` for long loops; use Python `logging` (not `print`) for status messages
- Type-annotate all function signatures
- Raise specific exceptions with informative messages; do not silently swallow errors
- Store source URLs and edition metadata in every `Work` record — provenance matters
- Text must always be stored as Unicode (UTF-8). Convert betacode, transliterations, etc. at ingest time

## Date Handling

Every chunk carries `date_composed`, `date_range`, `date_confidence`, and `post_schism` fields. For hybrid texts (Typikon, Beth Gazo, CANTUS), filter or flag at the chunk level — do not exclude entire works. When composition date is unknown, default to `date_confidence: "uncertain"` and `post_schism: False` (include unless positive evidence of post-1054 composition).

## Working with the Plan Docs

- `DATA_COLLECTION_PLAN.md` is a **living document**. Check off milestone items as they are completed.
- When starting a new session, read the relevant milestone section before writing any code.
- If a source turns out to be unavailable, licensed differently than noted, or structurally different from what the plan describes, update the plan doc to reflect reality.
