# Patristica

A searchable online database of Scriptural and Patristic writings from the early church, covering the first thousand years of Christianity (broadly: authors born before c. 1025, or anonymous texts composed by 1050), across Greek, Latin, Syriac, Coptic, Armenian, Ge'ez and other traditions.

## Goal

Patristica aims to make the writings of the Church Fathers and the Scriptures they interpreted accessible to scholars and researchers through modern search technology. Rather than relying solely on keyword matching, the database uses semantic vector search to let users discover texts by topic and theme across the entire corpus.

## Features (planned)

- **Semantic search** — find relevant passages by topic, not just exact words
- **Multilingual texts** — original languages (Greek, Latin, Hebrew, Syriac) alongside established public-domain translations
- **AI translation** — on-demand translation of any passage via Claude
- **AI synthesis** — summarize what the Fathers say on a given topic, with citations
- **Browse by author, tradition, date, or work**

## Scope

The corpus covers:

- **Scripture**: Hebrew Bible, Septuagint, Greek New Testament, Latin Vulgate, Syriac Peshitta, and major English translations
- **Church Fathers**: Ante-Nicene, Nicene, and Post-Nicene Fathers (ANF/NPNF), with Greek and Latin originals where available
- **Councils & Creeds**: Acts of the seven Ecumenical Councils, the Apostolic Canons, and major credal documents

Original-language texts are in Greek, Latin, Hebrew, Syriac, Coptic, Ge'ez, Armenian, Gothic and Old Church Slavonic (#29: the Gospel codices, the Psalterium Sinaiticum, Codex Suprasliensis and other canonical OCS texts, stored in Cyrillic), and Christian Arabic (#83: Melkite, Syriac Orthodox, East Syriac and Coptic writers to the early eleventh century), Old Georgian (#222: hagiography, chronicles and the Georgian Bible to the early eleventh century, stored in Mkhedruli) and Old Irish (#225: the Würzburg glosses on Paul, the Félire Óengusso and other early Irish religious texts). Old English (#223: the religious poetry of the *Anglo-Saxon Poetic Records* and Ælfric's *Catholic Homilies* I), Old High German and Old Saxon (#224: the Referenzkorpus Altdeutsch, with the OHG Tatian, Otfrid, Notker and Isidor and the *Heliand*) are being added, and so is Literary Chinese (#228: the Tang-era Church of the East texts, the Xi'an stele, the hymn and sūtras of Dunhuang).

All sources are public domain unless otherwise noted.

Adding a new language (Old Nubian, Sogdian, …) follows the checklist in [docs/adding-a-language.md](docs/adding-a-language.md).

## Project Phases

1. **Data Collection** — ingestion and normalization of source texts from CCEL, Perseus, Project Gutenberg, and other repositories
2. **Database Construction** — PostgreSQL + pgvector for structured storage and semantic indexing
3. **Web Application** — FastAPI backend and Next.js frontend with search, text view, and AI features

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for full technical detail.

---

## Development Setup

Requires Python 3.11+ and [`uv`](https://github.com/astral-sh/uv).

```bash
uv venv
uv pip install -e ".[dev]"
```

Run the test suite:

```bash
uv run pytest
```

Enable the git hooks (rejects pushes to `master`; runs the unit tests before every push):

```bash
git config core.hooksPath scripts/hooks
```

### Web app

The frontend in `web/` is a Next.js (App Router, TypeScript) app. It needs Node.js 22; the version is pinned in `web/.nvmrc`, so with [nvm](https://github.com/nvm-sh/nvm):

```bash
cd web
nvm install        # once; then `nvm use` in new shells
npm ci
npm run dev        # http://localhost:3000
```

Checks (all run in CI):

```bash
npm run lint
npm run typecheck
npm test
npm run build
```

#### Library browser

The app's library browser (work index with search and sort, plus a reader) reads a static export of the corpus. Build it and link it into the app once:

```bash
uv run python -m scripts.export_library   # in the repo root
cd web && npm run link-data && npm run dev
```

Then open http://localhost:3000. Re-run the export after the normalized data changes; the link stays.

#### Deployment

**Live site:** https://patristica-beta.vercel.app/

The deployed app runs on Vercel (root directory `web`) and reads the library from a DigitalOcean Spaces bucket through its CDN. The data pipeline publishes it as its last step (`uv run --extra pipeline python -m scripts.pipeline`, #248); merging a data change publishes nothing. To publish by hand:

```bash
uv run python -m scripts.upload_library   # boto3 is in the default dev group; add --dry-run to preview
```

The script reads `LIBRARY_ACCESS_KEY_ID`, `LIBRARY_SECRET_ACCESS_KEY`, `LIBRARY_BUCKET` and optionally `LIBRARY_REGION` (default `nyc3`) from the environment, `.env` or `web/.env`. It uploads only changed files (gzip-compressed), deletes files that are no longer in the export, and leaves out works whose licence isn't cleared (`unknown`). In Vercel, set `NEXT_PUBLIC_LIBRARY_URL` to the CDN URL. The bucket, CDN and key are set up with OpenTofu (`infra/README.md` → "Library").

### Contributing

- Work is tracked in [GitHub issues](https://github.com/jaspax/patristica/issues), not in checklists in the docs.
- Don't commit directly to `master`. Do each change on a feature branch and merge it with a pull request.
- Every PR must link the issue it resolves (`Closes #123` in the description). PRs that only commit a pipeline run's data use the short template `.github/PULL_REQUEST_TEMPLATE/pipeline.md` instead.
- Do each branch in its own git worktree (under `.claude/worktrees/`), so parallel work streams don't collide; pipeline and data runs stay in the main checkout, which has the git-lfs data.
- CI (GitHub Actions, `.github/workflows/ci-*.yml`, one workflow per area, run on the PRs that touch it) must pass before merging.

See [CLAUDE.md](CLAUDE.md) → "Development Workflow" for the details.

---

## Data Ingestion (Phase 1)

### Check ingestion status

Shows how many raw and normalized files exist per source, and when each was last run:

```bash
uv run python -m scripts.catalog
```

### Run all ingestors

Downloads and parses every Tier 1 source into `data/raw/`:

```bash
uv run python -m scripts.ingest.all
```

### Run a single source

Pass `--source` with the source ID (see the catalog for IDs):

```bash
uv run python -m scripts.ingest.all --source oshb
uv run python -m scripts.ingest.all --source kjv
uv run python -m scripts.ingest.all --source lxx-rahlfs
```

Each ingestor module can also be run directly:

```bash
uv run python -m scripts.ingest.oshb
uv run python -m scripts.ingest.sblgnt
uv run python -m scripts.ingest.kjv
```

All ingestors are **idempotent** — re-running skips already-downloaded files. Use `--force` to re-download and re-parse:

```bash
uv run python -m scripts.ingest.all --source wulfila --force
```

### Normalize, chunk, and link translations

After ingestion, run the pipeline to produce embedding-ready chunks:

```bash
# 1. Convert raw verse JSON → Chunk objects
uv run python -m scripts.normalize

# 2. Add context overlap (50-token context_before / context_after)
uv run python -m scripts.chunk

# 3. Assign translation_group_id across parallel verse chunks
uv run python -m scripts.link_translations
```

All three scripts accept `--help` for options, and support `--force` to overwrite existing output.

### Export the static library

The web library browser reads a static export of the normalized corpus:

```bash
uv run python -m scripts.export_library   # → data/library/index.json + data/library/works/…
```

It writes one index of all works (author, title, language, date, collection, …) and a slim JSON file per work. Re-runs only rebuild works whose normalized file changed; `--force` rebuilds everything.

### Raw data format

Each ingestor writes one JSON file per book to `data/raw/{source_id}/`:

```json
{
  "work": { "work_id": "oshb/gen", "language": "hbo", ... },
  "verses": [
    { "ref": "Gen.1.1", "text": "בְּרֵאשִׁית בָּרָא אֱלֹהִים..." },
    ...
  ]
}
```

Normalized output (`data/normalized/`) is a JSON array of `Chunk` objects. Final chunked output (`data/chunks/`) adds `context_before` and `context_after` and `translation_group_id`.

---

## Tech Stack

- Python (ingestion scripts, FastAPI backend)
- PostgreSQL + pgvector (database and vector search)
- Next.js / React (frontend)
- Claude API (AI translation and synthesis)

---

## License

- **Code** (Python package, scripts, `web/`): [MIT](LICENSE).
- **Texts**: each text keeps the licence of its source edition (public domain, CC BY, CC BY-SA, CC BY-NC(-SA), or the source's own terms), recorded per work in `Work.license`. Our changes to a text are shared under that text's licence. Some texts are non-commercial, so Patristica as a whole is non-commercial.
- **Our own metadata**: CC0.

See [DATA_LICENSE.md](DATA_LICENSE.md) for details, and the web app's *Sources & licences* page (`/sources`) for the per-collection list.
