# Patristica — Claude Code Instructions

## Project Overview

Patristica is a searchable database of Scriptural and Patristic writings from the first thousand years of Christianity, interpreted broadly: authors born before c. 1025, or — when the author is unknown — texts composed by 1050 (`patristica/period.py`), with a web frontend. The collection is deliberately not framed by the 1054 East–West schism, so that non-Chalcedonian traditions fit naturally. The project proceeds in three phases: data collection, database construction, and web app. See `IMPLEMENTATION_PLAN.md` for the high-level overview and `DATA_COLLECTION_PLAN.md` for the detailed Phase 1 plan.

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
├── LICENSE                    # MIT (code)
├── DATA_LICENSE.md            # texts keep their source licences; our own metadata is CC0
├── IMPLEMENTATION_PLAN.md     # high-level 3-phase plan
├── DATA_COLLECTION_PLAN.md    # detailed Phase 1 plan (design reference; work items live in GH issues)
├── .github/workflows/ci.yml   # CI: Python unit tests + web app checks on every PR (manual run on master)
├── .github/workflows/publish-library.yml  # on master: export_library + upload_library → Spaces (no-op if unchanged)
├── .github/workflows/deploy.yml           # on master: infra/deploy.sh --keep-env → web + api on the droplet
├── patristica/
│   ├── models.py              # Pydantic data models (Work, Chunk)
│   ├── sources.py             # readable label for every source_id (SOURCE_LABELS)
│   ├── authors.py             # author index: resolve_author(), dates (data/authors.csv, data/author_strings.csv; #82)
│   ├── genres.py              # curated per-work genres (data/genre_overrides.csv, #103)
│   ├── versions.py            # work-level version groups (translation_of + books + CTS + data/version_links.csv, #178)
│   ├── alignment.py           # passage alignment inside a version group: n:m groups from the vectors (#179)
│   ├── alignment_store.py     # alignment store (data/alignments/): one file per version group, no numpy
│   ├── versify.py             # split long prose chunks into verse-sized derived verses (#2)
│   ├── textfold.py            # fold(): normalize diacritics/spelling for keyword matching; fold_spans() maps back
│   ├── keyword.py             # keyword index for quoted search: index_text(), phrase_pattern(), FOLD_VERSION (#86)
│   ├── translations.py        # translation store (data/translations/)
│   ├── embedders.py           # embedding API clients (Voyage) + shorten(); shared by pipeline, API, eval
│   └── embeddings.py          # vector store (data/embeddings/): per-work .npz, model recorded per row
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
│   ├── translate.py           # rare-language chunks → English (GPT-6.1 Sol) → data/translations/
│   ├── embed.py               # normalized + translations → Voyage vectors → data/embeddings/ (#136)
│   ├── catalog.py             # print ingestion status table with last-run timestamps
│   ├── migrate_layout.py      # #102 genre-first → source-first migration (raw / eval / tracked)
│   ├── build_index.py         # normalized + translations + embeddings → Postgres/pgvector search DB (#137; db/README.md)
│   ├── version_groups.py      # report version groups per language pair (#178)
│   ├── align.py               # version groups + vectors → passage alignments → data/alignments/ (#179)
│   ├── align_eval.py          # aligner evaluation: Scripture vs versification, ±1 neighbours, samples
│   ├── export_library.py      # normalized → static library (index, authors.json, per-work JSON) for the web browser
│   ├── upload_library.py      # sync data/library → DO Spaces (deploy extra; skips unpublishable licences)
│   ├── embed_eval/            # embedding/retrieval eval harness (#3): build, run, report, translate
│   ├── bootstrap_infra.py     # one-time: Spaces key + tofu state bucket (infra/)
│   └── hooks/pre-push         # git hook: rejects pushes to master, runs unit tests (enable: git config core.hooksPath scripts/hooks)
├── db/                        # search DB schema (schema.sql, applied by scripts.build_index) and README
├── api/                       # FastAPI backend: /healthz, /search (search.py: parsing, routing, vector path #141/#143; keyword.py: phrase search #86); Dockerfile builds from the repo root
├── infra/                     # hosting as code (#117): tofu/ (DigitalOcean), compose/ (db + api + web + caddy), deploy.sh, db-tunnel.sh; see infra/README.md
├── web/                       # Next.js frontend (App Router, TypeScript); see "Web app"; Dockerfile for the droplet
│   ├── src/app/               # routes, root layout, fonts.ts (Noto fonts for every corpus script)
│   ├── src/app/works/[...id]/ # reader route (work ids contain slashes)
│   ├── src/app/authors/       # author list; authors/[id]/ is the author page (#145)
│   ├── src/app/page.tsx       # passage search, the landing page (#142)
│   ├── src/app/works/page.tsx # library index (work list)
│   ├── src/components/        # UI: SiteHeader/Footer, LibraryBrowser (index), FilterFields (shared facets), SearchPage,
│                              # WorkReader + WorkText (reader), AuthorList + AuthorPage
│   └── src/lib/               # library.ts (export types/loaders), filter.ts (search/sort/URL state, author facet),
│                              # authors.ts (author pages), render.ts (chunks → sections/units), search.ts (search API client, URL state),
│                              # useHashTarget.ts (jump to #ref), lang.ts, format.ts, config.ts
└── data/
    ├── raw/                   # downloaded source files (large; gitignored)
    │   ├── _zips/             # cached GitHub/eBible ZIP archives
    │   ├── _csvs/             # cached scrollmapper CSV files
    │   └── {source_id}/       # per-book JSON files (e.g. oshb/Gen.json)
    ├── normalized/            # normalized Chunk JSON, {source_id}/… mirroring raw/ (one file per work)
    ├── chunks/                # chunked records ready for embedding
    ├── translations/          # machine translations, {source_id}/… mirroring normalized/ (one file per work; tracked)
    ├── embeddings/            # corpus vectors, {source_id}/….npz mirroring normalized/ (gitignored; scripts.embed)
    ├── alignments/            # passage alignments, one file per version group (tracked; scripts.align, #179)
    └── library/               # static library for the web browser (gitignored; scripts.export_library)
```

## Data Models

See `patristica/models.py`. Key types:

- **`Work`**: metadata for a single work (author, title, language, date, license, genre, tradition)
  - `source_id` is the bare collection slug (`oshb`, `first1k`, `oglt-pl`), never a genre; it is also the work's directory under `data/raw/` and `data/normalized/`.
  - `work_id` is `{source_id}/{local id}` (`oshb/gen`, `ogpg/vol-045/ad-graecos`); a chunk's `chunk_id` is `{work_id}#{canonical_ref}`.
  - Genre lives only in `Work.genre`; a source may mix genres (`gez`, `anf-works`). Select works by genre from `_works.jsonl`, never by path or id prefix.
  - `author` is the source's own spelling (`Augustinus`, `Augustine of Hippo`), kept for provenance. `author_ids` holds canonical author ids (`augustine-of-hippo`) from the author index (`patristica/authors.py`, #82); `scripts.normalize` fills it, and anonymous works get `[]`. Select works by author through `author_ids`, never by the `author` string. Author ids are URLs in the web app, so never rename one.
  - `external_ids` holds the catalogue identifiers a source records for the work, as `KIND:value` (`TLG:tlg4090.tlg096`, `CPG:5200`, `BHG:…`, `Pinakes-Oeuvre:…`); PTA fills it from its `__cts__.xml` catalogue. When a source records such ids, have its ingestor store them: the version-group crosswalk uses them. `_works.jsonl` omits the field when it is empty, and `build_index` leaves it out of a work's content hash.

### Author index (#82)
`patristica/data/authors.csv` has one row per person: `author_id` (a stable slug), English `name`, `aliases` (every source spelling plus Latin/Greek forms, `|`-separated), `birth`/`death`/`floruit` (`354` established, `c. 347` approximate, `350?` uncertain, `340/345` a range), `tradition`, `external_ids` (TLG/stoa/PTA), `pseudo_of` (for `pseudo-*` authors, the real author) and a `note`. Keep it sorted by id. `patristica/data/author_strings.csv` maps source strings that are not a simple alias, with a required reason: anonymous works, work titles and councils in the author field, modern editors named as author, ambiguous bare names (`Gelasius`) and multi-person strings. `resolve_author()` matches on `fold()`-ed text and splits `;`-separated lists; an unknown name raises `UnknownAuthorError`. A pseudonymous author has no dates of its own. The author's birth year feeds the period rule (`period_birth_year`); see "Date Handling".
### Version groups (#178)
A work's *version group* is every work that is the same text in another language or edition. Groups are derived, never stored (`patristica/versions.py`): connected components over `translation_of`, Scripture books (a Scripture source's work id is `{source}/{osis book, lower case}`, so `kjv/gen`, `oshb/gen` and `lxx-rahlfs/gen` are one group, whatever each witness's genre), CTS work ids (`first1k`/`perseus` `{tlg…}/{tlg…}`, `pta` `{pta…}/{pta…}`), the **identifier crosswalk** (works sharing a TLG, CPG or BHG id from `Work.external_ids`, or the TLG id in a First1K/Perseus work id, are one work; ranges and ids carried by two different works of one source are collections and are set aside), and the curated `patristica/data/version_links.csv` (`work_id,other_work_id,relation,reason`; relation `translation_of`, `same_work` or `different_edition`). Add a curated link only when both works are the same work, checked against the text, and never link a container (a Migne Work holding several works, a catena) to one of its works: the groups would merge. `export_library` writes the group id per work (`version_group`, null for a work with no other version); ids are deterministic but change when links change, so don't use them in URLs. `uv run python -m scripts.version_groups` prints counts per language pair.

### Passage alignment (#179)
Inside a version group, `scripts.align` aligns the passages of the versions: an *alignment group* is one contiguous span of units per version (or none) that renders the same passage, n:m since derived verses are cut per language. Every member is aligned with a pivot (the longest version, English preferred) by a monotonic dynamic program over the stored vectors (`patristica/alignment.py`: 1:1 up to 4:1 beads, cosine above each unit's baseline, skips free so missing passages stay unaligned, later passes for moved blocks). Scripture books use their versification-mapped refs as a soft prior, so content overrules refs only where they clearly disagree. Each span has a confidence; spans under 0.5 are flagged and not used. Results are tracked in `data/alignments/`, one file per version group (`patristica/alignment_store.py`; see the README there): per member one token per unit, never text. A group is re-aligned only when its inputs hash changes (units, vectors, refs, parameters), so the run is idempotent and makes no API calls; it needs `--embeddings-dir` pointing at the vectors. Measure changes to the method with `scripts.align_eval` (Scripture with refs hidden vs versification, the ±1-neighbour count of #186, hand-check samples) before re-running the corpus. `build_index` syncs the confident spans into `passage_groups` in place (never through a work's hash, so no vectors are re-sent), search folds by them (`api/passages.py`), and `export_library` writes `alignments/{group}.json` for the reader. After re-normalizing a work, run `scripts.align` again: its spans count chunks, and a member whose chunk ids changed is left out (a test fails until then).

- **`Chunk`**: one text unit (verse, paragraph, stanza) with `canonical_ref`, `language`, `text`, optional `translation_group_id`

### Language codes (ISO 639-3)
`grc` Greek · `lat` Latin · `hbo` Hebrew · `syc` Syriac · `cop` Coptic · `gez` Ge'ez · `hye` Armenian · `got` Gothic · `eng` English

### Genre values
`scripture` · `patristic` · `liturgical` · `council` · `apocrypha`

Ingestors set a default genre; `patristica/data/genre_overrides.csv` (`work_id,genre,reason`) overrides it per work, and `scripts.normalize` applies it (#103). Genre is decided per work, not per book: a work is `scripture` if it is canonical in the tradition it belongs to (its language and edition), so the same book can be `scripture` in one witness and `apocrypha` in another (Ge'ez `gez/1en` vs Greek `first1k/tlg1463/…` Enoch). A work with any liturgical use is `liturgical`, and other apocryphal gospels, acts, apocalypses, testaments and Old Testament pseudepigrapha are `apocrypha`. Works about apocrypha, hagiography and martyr acts stay `patristic`. After editing the file, re-run `scripts.normalize`, with `--force` if a work moves into or out of `scripture` or `liturgical` (their chunks normalize differently). A test fails if `_works.jsonl` disagrees with the file.

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
SOURCE_ID = "oshb"   # required module-level constant: the bare collection slug

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
uv run python -m scripts.ingest.all --source oshb

# One source directly:
uv run python -m scripts.ingest.oshb

# Force re-download:
uv run python -m scripts.ingest.all --source kjv --force
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

`all.py` uses the convention: replace `-` in the source_id with `_`.
- `"lxx-rahlfs"` → `scripts.ingest.lxx_rahlfs`
- `"coptic-nt"` → `scripts.ingest.coptic_nt`

Keep module filenames consistent with this convention.

## Pipeline Scripts

```bash
uv run python -m scripts.normalize        # raw → Chunk objects (+ derived verses); also maintains data/normalized/_works.jsonl
uv run python -m scripts.chunk            # add 50-token context overlap
uv run python -m scripts.link_translations # assign translation_group_id (works with genre scripture)
uv run python -m scripts.validate         # QC report (stub until M7)
uv run python -m scripts.translate --dry-run  # rare-language chunks → data/translations/ (paid API; drop --dry-run to run)
uv run --extra embed python -m scripts.embed --dry-run  # vectors → data/embeddings/ (paid Voyage API; drop --dry-run to run)
uv run --extra embed python -m scripts.align --dry-run --embeddings-dir data/embeddings  # passage alignments → data/alignments/ (no API calls)
uv run --extra index python -m scripts.build_index --dry-run  # load the search DB (DATABASE_URL; droplet: infra/db-tunnel.sh …)
uv run python -m scripts.catalog          # status table with last-run timestamps
uv run python -m scripts.export_library   # normalized → data/library/ (index.json, authors.json, slim per-work JSON)
uv run --extra deploy python -m scripts.upload_library  # data/library → Spaces (incremental; --dry-run)
```

`_works.jsonl` is the only work manifest: `validate`, `export_library` and `scripts.lookup` all read it. There is no `_index.json`.

### Embedding eval (`scripts/embed_eval/`, #3)

```bash
uv sync --extra eval [--extra eval-local]       # eval-local: CPU torch + sentence-transformers
uv run python -m scripts.embed_eval.build       # data/chunks → data/eval/{corpus,queries}.jsonl
uv run python -m scripts.embed_eval.run --retriever bm25 --retriever dense:openai/text-embedding-3-large
uv run python -m scripts.embed_eval.report      # one table per query mode
uv run python -m scripts.embed_eval.translate quality   # translation-quality eval (Claude + OpenAI)
```

API keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, ...) are read from the environment or the repo-root `.env` (gitignored). `data/eval/` is gitignored scratch; embeddings are cached per text in `data/eval/embeddings/*.sqlite`. Authored queries (tracked) are in `data/eval_authored/`. Findings and decisions: `docs/embedding-eval.md` (full results matrix) and `IMPLEMENTATION_PLAN.md` §2.5. Machine translations are tracked in `data/translations/`, one file per work at its normalized path (`patristica/translations.py`; see the README there), and produced by `scripts.translate`.

### Corpus embeddings (`scripts/embed.py`, #136)

`scripts.embed` embeds every unit of at least 10 characters with Voyage `voyage-4-large` (its `text` only, no context overlap), plus the English translation of every Syriac, Coptic, Armenian and Ge'ez unit as a second vector (`KIND_TRANSLATION`). Vectors are stored at 1024 dims in float16 in `data/embeddings/`, one `.npz` per work at its normalized path (`patristica/embeddings.py`). The DB keeps 512 (`patristica.embedders.shorten`, #50). The model is recorded per row (a run table in each shard), never in the path, so vectors from a future model are labelled. A row is reused while the hash of the text it embeds and its model/dims/input type are unchanged; works with an `EXCLUDED_LICENSES` licence are skipped, as in `scripts.translate`. Production code imports the API clients from `patristica.embedders`, never from `scripts.embed_eval`.

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

The collection period is defined once, in `patristica/period.py` (`AUTHOR_BORN_BEFORE = 1025`, `COMPOSED_BY = 1050`); use `work_in_period()` / `is_out_of_period()` — never hard-code years. A whole work is excluded only on positive evidence (date range starting after `COMPOSED_BY`, or an author known to be born after `AUTHOR_BORN_BEFORE`). `scripts.normalize` takes author birth years from the author index: when every author of a work has one, it decides `out_of_period` instead of the composition date (a work by several authors is judged by the youngest), so a late work by an author born before 1025 is not flagged. Every chunk carries `date_composed`, `date_range`, `date_confidence`, and `out_of_period`. For hybrid texts (Typikon, Beth Gazo, CANTUS, mixed Migne volumes), keep the work and flag at the chunk level. When composition date is unknown, default to `date_confidence: "uncertain"` and `out_of_period: False` (include).

Per-book date estimates for all 66 Protestant books plus the Deuterocanon are in `_scripture_meta.BOOK_DATES`. Use these as the default; override only when a source warrants a specific translation date (e.g. Clementine Vulgate: 405 CE).

## Web app

The frontend lives in `web/` and is a Next.js 16 app (App Router, TypeScript, CSS modules, no Tailwind). It is the shell of the Phase 3 app (`IMPLEMENTATION_PLAN.md` §3).

- **Node**: version 22, pinned in `web/.nvmrc`, installed with nvm. Shells need nvm loaded (`source ~/.nvm/nvm.sh`) before `node`/`npm` work.
- **Commands** (run in `web/`): `npm ci`, `npm run dev`, `npm run lint`, `npm run typecheck` (runs `next typegen` first, since `LayoutProps`/`PageProps` are generated types), `npm test` (Vitest), `npm run build`. CI runs all of them in the `web` job.
- **Next.js 16 differs from older versions.** Read the bundled docs in `web/node_modules/next/dist/docs/` before using a Next API (see `web/AGENTS.md`).
- **Languages and fonts**: render corpus text with `lang` and `dir` from `languageInfo()` in `src/lib/lang.ts`. `globals.css` picks the script font with `:lang()` rules, and `src/app/fonts.ts` loads the fonts. Only the body font is preloaded.
- **Config**: `NEXT_PUBLIC_LIBRARY_URL` is the base URL of the static library export (`scripts/export_library.py`). It defaults to `/library`. `NEXT_PUBLIC_API_URL` is the search API's base URL, `/api` by default (same origin, through Caddy). For `npm run dev`, set `API_PROXY_URL=http://localhost:8000` to send `/api/*` to a local API (a dev-only rewrite in `next.config.ts`; the Docker build leaves it unset).
- New UI code comes with Vitest tests next to the code (`*.test.ts[x]`).

### Deployment

- **Production:** https://patristica.app (`www.patristica.app` redirects to it), served from the DigitalOcean droplet (#132). Until its DNS records and first deploy are done, the old Vercel deployment https://patristica-beta.vercel.app/ (team `patristica1`) is what's live; it is deleted once the droplet serves the site.
- **Library data:** https://patristica-library.nyc3.cdn.digitaloceanspaces.com (DigitalOcean Spaces bucket `patristica-library` behind its CDN, #131; e.g. `https://patristica-library.nyc3.cdn.digitaloceanspaces.com/index.json`).

The app runs on the droplet as the `web` service of the compose stack (`infra/compose`), built from `web/Dockerfile` (Node 22, `output: "standalone"`), behind Caddy. Runbook: `infra/README.md` → "Web app".

- **Code is deployed automatically.** On every push to `master` that touches `web/`, `api/`, `patristica/`, `pyproject.toml`/`uv.lock`, `infra/compose/` or `infra/deploy.sh`, `.github/workflows/deploy.yml` runs `infra/deploy.sh --keep-env`, using the repo secrets `DEPLOY_HOST`, `DEPLOY_SSH_KEY` and `DEPLOY_KNOWN_HOSTS`. It rebuilds the images on the droplet and leaves the host `.env` alone, so a change that adds a host `.env` setting needs one manual `infra/deploy.sh` run. There are no preview deploys.
- `NEXT_PUBLIC_LIBRARY_URL` is the Spaces CDN URL (`infra/tofu.sh output -raw library_url`, `LIBRARY_URL` in the host `.env`). `NEXT_PUBLIC_*` values are inlined at build time, so they are Docker build arguments; changing one means rebuilding the image.
- **`/api/*` on `patristica.app` is the FastAPI app**, with the prefix stripped by Caddy: `/api/search` reaches FastAPI as `/search`. Declare FastAPI routes without `/api`, call them from the web app same-origin at `/api/…`, and never add Next.js routes under `/api`. `api.patristica.app` serves the same routes without the prefix.

- **Data is published automatically.** On every push to `master` that touches `data/normalized/**`, the export/upload code or what the export derives from (authors, version links), `.github/workflows/publish-library.yml` runs `scripts.export_library` and then `scripts.upload_library`, using the repo secrets `LIBRARY_ACCESS_KEY_ID` and `LIBRARY_SECRET_ACCESS_KEY` (a Spaces key that can only touch the library bucket; tofu outputs `library_access_key` / `library_secret_key`). The bucket name and region are plain values in the workflow. Unchanged data uploads nothing. Re-run it manually from the Actions tab (`workflow_dispatch`).
- To publish by hand, run the same two scripts locally. Local credentials (`LIBRARY_*`) go in `web/.env` (gitignored). Never print or commit them.
- The export is deterministic: `index.json` has a content hash (`version`), not a timestamp. A from-scratch export is byte-identical to an incremental one, which is what makes CI runs no-ops. Keep it that way: no timestamps or other run-dependent values in exported files.
- Objects are stored gzipped with `Content-Encoding: gzip`. Changes are detected through `_manifest.json` in the bucket, which maps each key to the SHA-256 of its *uncompressed* content and is written last. Don't compare gzip bytes or ETags: gzip output differs between Python and zlib versions (even the header's OS byte, #46), so CI and local runs would keep re-uploading everything. A no-op run takes a few seconds.
- The bucket, its CORS rule (GET/HEAD from any origin), the CDN and the upload key are OpenTofu resources in `infra/tofu` (runbook: `infra/README.md` → "Library"). The bucket listing is private: `upload_library` makes the work files and `index.json` public-read and keeps `_manifest.json` private. The CDN caches files for `library_cdn_ttl` (10 minutes), so a publish can take that long to show.
- `EXCLUDED_LICENSES` in `upload_library.py` keeps unpublishable works (`unknown`) out of the public copy.

### Database host (#117)

- **API:** https://api.patristica.app (`/healthz`), and https://patristica.app/api/ for the web app. The domain `patristica.app` is registered at Cloudflare and its DNS is managed by hand there. `api`, the apex and `www` are A records to the reserved IP `159.89.246.34`, set to DNS only: proxying would break Caddy's certificates.
- Postgres 16 + pgvector, the FastAPI `api`, the Next.js `web` and Caddy (TLS) run under Docker Compose on one DigitalOcean droplet. OpenTofu provisions it from `infra/tofu`, and `infra/deploy.sh` deploys it. The runbook is in `infra/README.md`.
- All hosting is on DigitalOcean: the library on Spaces (#131), the app and API on the droplet (#132).
- The only secrets added by hand are `DIGITALOCEAN_TOKEN` in `infra/.env` (gitignored) and the three `DEPLOY_*` repo secrets for the Deploy workflow. `scripts.bootstrap_infra` adds the Spaces key for tofu state, and the backups key comes from tofu outputs. The droplet's Postgres password is generated on the droplet and stays there. The SSH deploy key is `~/.ssh/patristica_deploy`, with the master copy in the password manager. Never print or commit any of these.
- Postgres has no public port. Reach it over SSH (`infra/README.md`).
- Run the stack locally: `cd infra/compose && cp .env.local.example .env && docker compose up -d --build`, then open http://localhost:18080 (API at http://api.localhost:18080 and http://localhost:18080/api/).

### Library browser

`/` is passage search (`/?q=…`, through `/api/search`, #142), and the landing page. `/works` is the work index, `/works/{work_id}` is the reader, and `/authors/{author_id}` is an author page (`/authors` lists them). All load the static library export in the browser. `/search` permanently redirects to `/`, keeping its query. Don't add a page at `/library`, which is the default `NEXT_PUBLIC_LIBRARY_URL` (the export, symlinked into `public/`). To run it locally:

```bash
uv run python -m scripts.export_library   # repo root: data/normalized → data/library
cd web && npm run link-data               # symlink public/library → ../../data/library (once)
npm run dev
```

- Index state (query, facets, date range, sort) lives in the URL query, so links can be shared. So does search state (`src/lib/search.ts`, the same parameter names), and every search is a history entry. Author, language and genre take several values (`MULTI_KEYS`, `MultiSelect`), written as repeated parameters (`?language=grc&language=lat`); comma-separated values are read too, as the API does.
- Search results link to `/works/{work_id}#{canonical_ref}`. Every chunk's ref is an element id in the reader, including derived verses and heading chunks. Because the text loads after navigation, `useHashTarget` scrolls to the target once it is rendered, re-scrolls while `content-visibility` settles the layout, and marks it with `data-target`.
- Work ids are reader URLs and bucket keys. When a source is renamed, add its old id prefix to `RENAMED_ID_PREFIXES` in `src/lib/redirects.ts` so old links get a permanent redirect; `upload_library` deletes the old keys from the bucket on the next publish.
- Authors come from `authors.json` (#82), never the free-text `Work.author`: the index's author facet (`?author={author_id}`, `?author=anonymous` for works with `author_ids: []`) and author sort use ids and display names, and the text filter also matches aliases. Author ids are URLs too: when one is renamed or merged, add it to `RENAMED_AUTHOR_IDS` in `src/lib/redirects.ts`.
- `src/lib/render.ts` turns refs into structure. The last ref segment is the unit number and the rest is the section path. A chunk whose ref is the parent of the next ref is a section heading. A zero-numbered first unit is a heading in liturgy and scripture. Short all-caps lines in liturgical texts are rubrics.
- Huge works (up to ~9.4k chunks) rely on `content-visibility: auto` instead of virtualization. Content-visibility clips anything painted outside the box, so keep margin content (paragraph numbers) inside the element's padding.

## Development Workflow

These rules are mandatory for all changes, including ones made by Claude.

### Work tracking: GitHub issues

- All work items live in **GitHub issues** on `jaspax/patristica` (`gh issue list`). Do **not** add checklists or TODO lists to the plan docs or other text files; open an issue instead (`gh issue create`), and link to it from the doc if the doc needs to mention it (`#12`).
- Label issues by area: `phase-1: data`, `phase-2: database`, `phase-3: web`, `data-quality`, `ocr`, `infra` (plus GitHub's `bug` / `enhancement` / `documentation`).
- Also label language-specific issues by language: `lang: greek`, `lang: latin`, `lang: hebrew`, `lang: syriac`, `lang: coptic`, `lang: geez`, `lang: armenian`, `lang: arabic`, `lang: slavonic`, `lang: gothic` (filter with `gh issue list --label "lang: geez"`). Give a multi-language issue every relevant language label, and leave general issues (pipeline, web, cross-language linking) without one. There is no `lang: english`: English is the general translation language, so tag the original language instead. `lang: arabic` and `lang: slavonic` exist before the corpus has any such text, so planned work can be filtered. Add a new `lang:` label when a new language enters the corpus.
- If you discover a bug, gap or follow-up while working on something else, file an issue rather than widening the current change.
- The milestone checklists in `DATA_COLLECTION_PLAN.md` §10 are a frozen historical record of Phase 1; don't add new items there.

### Branches and pull requests

- **Never commit directly to `master`.** Start each piece of work on a feature branch off an up-to-date `master` (e.g. `git switch -c 12-ruff-cleanup`).
- Every change lands on `master` through a **pull request**.
- **Every PR must link the issue it resolves**, with a closing keyword in the PR description (`Closes #12`, `Fixes #12`). If no issue exists yet, create one first. A PR that only partially addresses an issue says `Part of #12` instead.
- **CI must pass** before a PR is merged. Don't merge over a red build; fix it or, if the failure is unrelated, file an issue and fix that first.
- Keep PRs focused on one issue.

### Tests, hooks and CI

- Unit tests: `uv run pytest`. Tests that need downloaded source data under `data/raw/` must skip themselves when it is absent (CI has no source data), so the suite passes on a clean checkout. Database tests use `PATRISTICA_TEST_DATABASE_URL` (a Postgres with pgvector; CI runs one as a service) through the `pg_url` fixture, each in its own schema, and skip without it.
- The **pre-push hook** (`scripts/hooks/pre-push`) rejects any push to `master` and runs the unit tests, aborting the push on failure. (GitHub branch protection is unavailable on this private repo without GitHub Pro, so this hook is the guard.) Enable it once per clone: `git config core.hooksPath scripts/hooks`. Use `git push --no-verify` only in an emergency.
- **CI** (`.github/workflows/ci.yml`) runs on every PR, not on pushes to `master`: PR runs already cover everything that merges. If `master` has moved since a PR's last CI run, re-run its checks before merging (GitHub shows "This branch is out-of-date"). To check `master` itself, run the workflow manually (Actions → CI → Run workflow). It has three jobs: Python unit tests, the web app job (lint, typecheck, Vitest, build), and infra (tofu, compose and Caddyfile validation, the web Docker image, shellcheck). Add heavier suites (pipeline/integration tests, data validation, lint) as separate jobs in that workflow.
- New code should come with unit tests.

## Working with the Plan Docs

- `IMPLEMENTATION_PLAN.md` and `DATA_COLLECTION_PLAN.md` are **design and reference documents**: architecture, source catalog, conventions, known gaps. They are not task trackers (see "Work tracking" above).
- When starting work on an issue, read the plan sections it references before writing any code.
- If a source turns out to be unavailable, licensed differently than noted, or structurally different from what the plan describes, update the plan doc to reflect reality (in the same PR as the related change).

## Licensing

Code is MIT (`LICENSE`). Texts are **not** relicensed: each keeps its source licence (`Work.license`), and our changes to a text go out under that same licence. Our own metadata is CC0. See `DATA_LICENSE.md`.

- Every new ingestor must set `Work.license` accurately from the source's actual terms. Use `unknown` only while the terms are being checked; works marked `unknown` must not be published.
- Don't add anything that imposes extra terms on CC BY or public-domain text, or that puts CC BY-SA text under a different licence.
- Non-commercial texts (CC BY-NC, CC BY-NC-SA, `academic-noncommercial`) mean the public site must stay non-commercial. `web/src/lib/sources.ts` (`NON_COMMERCIAL`) flags them on the `/sources` page.

## Known Issues / Gotchas

- **SBLGNT** uses a Logos/Faithlife custom XML format (not OSIS). The `parse_osis` utility will not work; use the custom parser in `sblgnt.py`.
- **LXX Rahlfs** (eliranwong repo) requires a CCAT user declaration for redistribution. License is CC-BY-NC-SA. The word CSV has 3 columns (`idx\tidx\tword`); the verse index has the same start index in both columns — end index is inferred from the next verse's start.
- **Wulfila** books are identified by `xml:id="B1"–"B18"` (German headings), not OSIS codes. The mapping is in `_BOOK_ID_TO_OSIS` in `wulfila.py`. Books B19–B21 (Skeireins, legal documents, calendar) are non-canonical and skipped.
- **eBible USFM** files contain Strong's number annotations (`\w word|strong="H1234"\w*`) and footnote blocks (`\f...\f*`). Always pre-process with `_ebible_usfm._preprocess_usfm()` before calling `parse_usfm`.
- **Source-first layout (#102)**: before #102, source ids, data paths and many work ids started with a genre (`scripture/oshb`, `data/raw/patristic/first1k/`, `councils/nicaea1`, `oglt_pl/…`). A local checkout made before then migrates once with `uv run python -m scripts.migrate_layout raw` (moves `data/raw/{genre}/{source}` to `data/raw/{source_id}` and rewrites the ids in the raw work records; `--dry-run` first) and `… migrate_layout eval` (ids in the local `data/eval/` scratch). A branch that adds tracked data in the old layout runs `… migrate_layout tracked`. Old reader URLs redirect (`web/src/lib/redirects.ts`), so never name a source `scripture`, `patristic`, `liturgical`, `councils` or `oglt_pl`.
- **New sources need a label**: add every new `source_id` to `SOURCE_LABELS` in `patristica/sources.py`. Users see that label, not the id. `tests/test_export_library.py` fails if a source in `_works.jsonl` has no label.
- **New sources need their author spellings**: `scripts.normalize` raises `UnknownAuthorError` on an author string the author index doesn't know. Add the spelling as an alias of an existing person in `patristica/data/authors.csv`, or add a new person row (with dates), or, for an anonymous, collective or multi-person string, add it to `author_strings.csv` with a reason. `tests/test_authors.py` fails if `_works.jsonl` has an unresolved author or stale `author_ids`, and `scripts.validate` reports them.
- **CCEL carve-outs**: a dedicated ingestor that extracts a section of a CCEL volume (ANF/NPNF) must register that div's `@id` in `_ccel_common.EXCLUDED_DIVS`, otherwise `ccel_anf`/`ccel_npnf*` keep ingesting it too and the text is in the corpus twice. `download_volume` reads the cached XML without network access unless `force=True`.
- **Scripture versification**: `canonical_ref` is always in the source's *native* numbering; `link_translations.py` groups verses via `patristica/versification.py`, which maps refs onto org (BHS / Nestle-Aland) numbering. A new scripture source must be added to `SOURCE_SCHEMES` there (org / eng / lxx / vul) or linking raises `VersificationError` — check its per-chapter verse counts against the schemes' `maxVerses` to pick one. A book or chapter that follows another scheme goes in `BOOK_SCHEME_OVERRIDES` / `CHAPTER_SCHEME_OVERRIDES`. `scripts.build_index` applies group changes in place (no vectors reloaded, #186).
- **OGPG works** come from `scripts/ingest/data/ogpg_index.csv` (Migne column ranges per work, #67). Never rename a row's `slug` (it is in reader URLs); when you split a new volume, add it to `SPLIT_OGPG_VOLUMES` in `web/src/lib/redirects.ts` (a test checks). Edits apply on a plain `python -m scripts.ingest.ogpg` run from the cached `_extract/` files.
- **Derived verses (#2)**: `normalize` splits every chunk longer than about a verse, except in Scripture and other works ingested as `verses`, into derived verses `{ref}.s1`, `{ref}.s2`, … (`patristica/versify.py`), breaking at sentence ends where it can. The target size is the mean Scripture verse in the chunk's language (`VERSE_TOKENS`). Derived refs are reader URLs and translation keys, so the split must stay repeatable: don't change `VERSE_TOKENS`, the break costs or the punctuation tables casually, since that renumbers derived verses across the corpus and invalidates their translations. The reader joins a paragraph's derived verses back together and marks them in a style distinct from source numbering (`render.ts`, `isDerivedRef`).
- **`beta2unicode`** does not exist on PyPI. Betacode conversion for any CCAT source (Tier 2) will need a per-ingestor solution.
