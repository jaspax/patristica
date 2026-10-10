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
│   │   ├── _common.py         # shared utilities: download_file, parse_tei, parse_osis, parse_usfm, clean_html, slugify_ref
│   │   ├── _scripture_meta.py # book metadata: OSIS abbreviations, dates, title map, FULL_NAME_TO_ABBREV
│   │   ├── _scrollmapper.py   # shared CSV ingestor for scrollmapper/bible_databases translations
│   │   ├── _ebible_usfm.py    # shared USFM ingestor for eBible.org zip archives (handles Strong's + footnotes)
│   │   ├── _ingestor_main.py  # shared CLI entry-point helper for individual ingestors
│   │   ├── all.py             # run all ingestors, or a single one via --source
│   │   └── {source_id}.py     # one module per source (e.g. oshb.py, kjv.py)
│   ├── normalize.py           # raw → normalized Chunk JSON
│   ├── chunk.py               # normalized → chunked records (adds context overlap)
│   ├── link_translations.py   # assign translation_group_id across parallel chunks
│   ├── validate.py            # QC checks; outputs data/validation_report.json
│   └── catalog.py             # print ingestion status table with last-run timestamps
└── data/
    ├── raw/                   # downloaded source files (large; gitignored)
    │   ├── _zips/             # cached GitHub/eBible ZIP archives
    │   ├── _csvs/             # cached scrollmapper CSV files
    │   └── {source_id}/       # per-book JSON files (e.g. scripture/oshb/Gen.json)
    ├── normalized/            # normalized Chunk JSON (one file per work)
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

## Raw Ingest Output Format

Every ingestor writes per-book JSON files to `data/raw/{source_id}/`. Each file contains:

```json
{
  "work": { ...Work model fields... },
  "verses": [
    { "ref": "Gen.1.1", "text": "..." },
    ...
  ]
}
```

For prose/patristic sources (M3+), use `"paragraphs"` instead of `"verses"` with the same `{"ref": ..., "text": ...}` structure. `normalize.py` reads this format and produces `Chunk` objects.

## Ingestion Modules

Every module in `scripts/ingest/` must implement:

```python
SOURCE_ID = "scripture/oshb"   # required module-level constant

def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """
    Download/parse source. Write one JSON file per work to output_dir/{source_id}/.
    Skip already-written files unless force=True (idempotent).
    Returns list of Work metadata records.
    """
```

And end with:

```python
if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
```

This makes each module runnable directly: `python -m scripts.ingest.oshb [--force]`.

### Running ingestors

```bash
# All sources:
uv run python -m scripts.ingest.all

# One source by ID:
uv run python -m scripts.ingest.all --source scripture/oshb

# One source directly:
uv run python -m scripts.ingest.oshb

# Force re-download:
uv run python -m scripts.ingest.all --source scripture/kjv --force
```

### Shared ingest helpers

Use the appropriate helper rather than duplicating logic:

| Helper | Use for |
|--------|---------|
| `_common.download_file` | Any HTTP download (ETag-cached, idempotent) |
| `_common.parse_tei` | TEI P5 XML → (metadata, paragraphs) |
| `_common.parse_osis` | OSIS XML → (metadata, [(ref, text)]) |
| `_common.parse_usfm` | USFM files → (metadata, [(ref, text)]) |
| `_common.clean_html` | Strip HTML markup → plain text |
| `_common.slugify_ref` | Normalize dot-separated canonical refs |
| `_scripture_meta` | Book OSIS abbreviations, dates, title maps, `FULL_NAME_TO_ABBREV` |
| `_scrollmapper.ingest_scrollmapper` | Translations available in scrollmapper/bible_databases CSV format |
| `_ebible_usfm.ingest_ebible_usfm` | Translations available as eBible.org USFM zips (strips Strong's / footnotes) |

### Source ID → module name mapping

`all.py` uses the convention: take the last path component of the source_id and replace `-` with `_`.
- `"scripture/lxx-rahlfs"` → `scripts.ingest.lxx_rahlfs`
- `"scripture/coptic-nt"` → `scripts.ingest.coptic_nt`

Keep module filenames consistent with this convention.

## Pipeline Scripts

```bash
uv run python -m scripts.normalize        # raw verses → Chunk objects
uv run python -m scripts.chunk            # add 50-token context overlap
uv run python -m scripts.link_translations # assign translation_group_id
uv run python -m scripts.validate         # QC report (stub until M7)
uv run python -m scripts.catalog          # status table with last-run timestamps
```

All accept `--help`. `normalize.py` currently processes `genre: scripture` only; prose genres are stubbed for M3+.

## Coding Conventions

- All functions that do I/O should be idempotent (re-running produces the same result, skips already-done work)
- Log progress with `tqdm` for long loops; use Python `logging` (not `print`) for status messages
- Type-annotate all function signatures
- Raise specific exceptions with informative messages; do not silently swallow errors
- Store source URLs and edition metadata in every `Work` record — provenance matters
- Text must always be stored as Unicode (UTF-8). Convert betacode, transliterations, etc. at ingest time
- ZIP archives from GitHub/eBible are cached under `data/raw/_zips/`; CSVs under `data/raw/_csvs/`. Do not re-download if the file exists (unless `force=True`)

## Date Handling

Every chunk carries `date_composed`, `date_range`, `date_confidence`, and `post_schism` fields. For hybrid texts (Typikon, Beth Gazo, CANTUS), filter or flag at the chunk level — do not exclude entire works. When composition date is unknown, default to `date_confidence: "uncertain"` and `post_schism: False` (include unless positive evidence of post-1054 composition).

Per-book date estimates for all 66 Protestant books plus the Deuterocanon are in `_scripture_meta.BOOK_DATES`. Use these as the default; override only when a source warrants a specific translation date (e.g. Clementine Vulgate: 405 CE).

## Working with the Plan Docs

- `DATA_COLLECTION_PLAN.md` is a **living document**. Check off milestone items as they are completed.
- When starting a new session, read the relevant milestone section before writing any code.
- If a source turns out to be unavailable, licensed differently than noted, or structurally different from what the plan describes, update the plan doc to reflect reality.

## Known Issues / Gotchas

- **SBLGNT** uses a Logos/Faithlife custom XML format (not OSIS). The `parse_osis` utility will not work; use the custom parser in `sblgnt.py`.
- **LXX Rahlfs** (eliranwong repo) requires a CCAT user declaration for redistribution. License is CC-BY-NC-SA. The word CSV has 3 columns (`idx\tidx\tword`); the verse index has the same start index in both columns — end index is inferred from the next verse's start.
- **Wulfila** books are identified by `xml:id="B1"–"B18"` (German headings), not OSIS codes. The mapping is in `_BOOK_ID_TO_OSIS` in `wulfila.py`. Books B19–B21 (Skeireins, legal documents, calendar) are non-canonical and skipped.
- **eBible USFM** files contain Strong's number annotations (`\w word|strong="H1234"\w*`) and footnote blocks (`\f...\f*`). Always pre-process with `_ebible_usfm._preprocess_usfm()` before calling `parse_usfm`.
- **CCEL carve-outs**: a dedicated ingestor that extracts a section of a CCEL volume (ANF/NPNF) must register that div's `@id` in `_ccel_common.EXCLUDED_DIVS`, otherwise `ccel_anf`/`ccel_npnf*` keep ingesting it too and the text is in the corpus twice. `download_volume` reads the cached XML without network access unless `force=True`.
- **Scripture versification**: `canonical_ref` is always in the source's *native* numbering; `link_translations.py` groups verses via `patristica/versification.py`, which maps refs onto org (BHS / Nestle-Aland) numbering. A new scripture source must be added to `SOURCE_SCHEMES` there (org / eng / lxx / vul) or linking raises `VersificationError` — check its per-chapter verse counts against the schemes' `maxVerses` to pick one.
- **`beta2unicode`** does not exist on PyPI. Betacode conversion for any CCAT source (Tier 2) will need a per-ingestor solution.
