# Patristica: High-Level Implementation Plan

## Context

This project aims to build a comprehensive, searchable online database of Scriptural and Patristic writings from the first thousand years of Christianity (broadly: authors born before c. 1025, or anonymous texts composed by 1050; see `patristica/period.py`). The goal is to serve scholars and researchers by enabling semantic topic-based discovery across a vast corpus of texts, presenting original languages alongside translations, and offering AI-assisted translation and synthesis. The project proceeds in three phases: data collection, database construction, and web app development.

---

## Phase 1: Data Collection

### 1.1 Source Inventory & Prioritization

Catalog all target sources by category:

**Scripture (original languages + canonical translations):**
- Hebrew Bible: Leningrad Codex / Westminster Leningrad Codex (open license)
- Greek OT: Septuagint (Swete/Brenton, public domain; NETS for reference)
- Greek NT: SBL Greek NT (open license), Tischendorf (public domain)
- Latin Vulgate: Stuttgart Vulgate (public domain edition via Clementine)
- English: KJV, ASV, WEB, YLT (all public domain)
- Syriac Peshitta: CAL (Comprehensive Aramaic Lexicon) corpus where available

**Church Fathers (Ante-Nicene, Nicene, Post-Nicene):**
- ANF (Ante-Nicene Fathers, 10 vols) — public domain via CCEL/Project Gutenberg
- NPNF Series 1 & 2 (28 vols) — public domain via CCEL
- Tertullian.org corpus (HTML)
- Documenta Catholica Omnia (Latin originals, some with translations)
- Perseus Digital Library (Greek/Latin originals with some translations)
- CCEL (Christian Classics Ethereal Library) — TEI XML exports where available

**Councils & Creeds:**
- Ecumenical council acts (Nicaea, Constantinople, Ephesus, Chalcedon, etc.)
- Apostolic Canons and Didache

### 1.2 Data Acquisition Pipeline

For each source, build an ingestion script that:
1. Fetches raw content (HTTP scrape, API, or file download)
2. Parses into a normalized internal format (see §1.3)
3. Extracts and validates metadata
4. Deduplicates against already-ingested content

Use Python with `requests`, `lxml`, `BeautifulSoup4`, and `tei-reader` (or custom TEI parser).

### 1.3 Normalized Data Model (pre-database)

Every text unit stored as a JSON record with:

```json
{
  "source_id": "ccel/npnf1-01",
  "work_id": "augustine/confessions",
  "author": "Augustine of Hippo",
  "author_ids": ["augustine-of-hippo"],  // canonical ids (patristica/data/authors.csv, #82)
  "title": "Confessions",
  "date_range": [397, 400],
  "language": "la",          // ISO 639 code
  "canonical_ref": "Conf.1.1",
  "text": "...",
  "translation_links": [     // refs to parallel translation records
    { "language": "en", "source": "npnf1-01", "record_id": "..." }
  ],
  "license": "public_domain",
  "provenance_url": "https://..."
}
```

### 1.4 Chunking Strategy

Texts must be split into semantically meaningful chunks for vector embedding:
- Scripture: by verse (smallest unit), with paragraph-level chunks for context
- Patristic prose: by paragraph or section heading
- Aim for ~300–600 token chunks with 50-token overlap
- Preserve canonical reference (book/chapter/verse or book/section/paragraph) in each chunk

### 1.5 Output

Raw ingested data stored as structured JSON files on disk (one file per work), organized as:
```
data/raw/{category}/{author_slug}/{work_slug}.json
```

---

## Phase 2: Database Construction

### 2.1 Technology Stack

| Component | Choice | Rationale |
|---|---|---|
| Relational DB | PostgreSQL 16+ | Mature, JSONB support, full-text search |
| Vector store | pgvector extension | Keeps everything in one DB, simplifies ops |
| Embeddings | **Decided (2026-10-13):** Voyage `voyage-4-large`. Syriac, Coptic, Armenian and Ge'ez chunks also get an English translation by GPT-6.1 Sol, embedded as a second vector | `docs/embedding-eval.md`: paraphrase/topical recall 0.99/0.99, every language ≥ 0.90; best at every vector size. 512-dim `halfvec` (decided 2026-10-15, #50) |
| ORM/migration | SQLAlchemy + Alembic | Python ecosystem |
| Search layer | Custom (via pgvector + Postgres FTS) | Avoid unnecessary infra |

### 2.2 Schema

**Core tables:**

```sql
authors (id, name, aliases, birth, death, floruit, tradition, external_ids, pseudo_of)
                             -- from patristica/data/authors.csv (#82)
works (id, author_ids, title, date_range, genre, language, license)
                             -- author_ids: text[] + GIN index, [] for anonymous works
text_chunks (
  id, work_id, canonical_ref, language,
  text, chunk_index,
  embedding halfvec(512),    -- Voyage voyage-4-large, shortened (#50)
  translation_group_id       -- links original + translations of same passage
)
translation_groups (id)      -- joins parallel chunks across languages
```

### 2.3 Indexing Pipeline

1. Load normalized JSON from Phase 1
2. Insert author/work metadata into PostgreSQL
3. Translate Syriac, Coptic, Armenian and Ge'ez chunks into English with GPT-6.1 Sol (`scripts.translate`, #93). Translations are stored in `data/translations/`, one file per work, mirroring `data/normalized/`, with model, prompt version and date recorded per run.
4. Embed every unit of at least 10 characters with Voyage `voyage-4-large`, plus a second vector for the English translation of each rare-language unit (`scripts.embed`, #136). Vectors are stored at 1024 dims (float16) in `data/embeddings/`, one file per work mirroring `data/normalized/`, with the model, dims, input type and date recorded per run. The store is resumable: a vector is reused while the text it embeds and its model are unchanged. The dry run on 2026-10-17 counted 4.02M vectors (3.96M distinct texts, ~333M cl100k tokens).
5. Load works, chunks, translations and vectors (cut to 512 dims) into PostgreSQL (`scripts.build_index`, #137); every vector row names its model
6. Build HNSW index on the vectors via pgvector
7. Build the keyword index over normalized text (`patristica.textfold.fold`) for quoted search (#86)

**Script:** `scripts/build_index.py` — idempotent, resumable: a work is reloaded only when a hash of its inputs changes (#137). The schema as built is `db/schema.sql` (see `db/README.md`). It differs from the sketch in §2.2: vectors are in their own table, `chunk_vectors (chunk_id, kind, model_id, embedding halfvec(512), …filter columns)`, with one row per kind (text or English translation) and one partial HNSW index per model, and translations are in `chunk_translations`.

### 2.5 Open Issues (from the Phase 1 handoff — resolve before building the index)

Inputs and the data contract are described in `DATA_COLLECTION_PLAN.md` → "Phase 2 Handoff".

1. **Chunk size normalization** ([#2](https://github.com/jaspax/patristica/issues/2)). *Resolved 2026-10-15.* Phase 1 chunks were source units (verse, paragraph, div, sometimes a whole work), measured with `cl100k_base`: 302 over 8,191 tokens (whole PTA manuscripts up to ~144k), ~68k over 512, ~39k over 2,000.

   **Decision: search units are about one Scripture verse long.** `normalize` splits every non-scripture chunk longer than that into *derived verses* (`patristica/versify.py`).
   - **Size is set per language.** The target is the mean Scripture verse length in that language, because tokens per verse differ about 7× between scripts: English 31, Latin 37, Gothic 44, Greek 130, Syriac 155, Hebrew 177, Armenian 194, Ge'ez 201, Coptic 221 `cl100k_base` tokens (measured over every scripture source). Words per verse vary much less (12–25).
   - **Breaks are grammatical.** In order of preference: sentence end, clause punctuation (`;` `:` `·`, Ge'ez `፤`, Syriac `܆`…), comma, between words. Each language has its own punctuation table (the Greek `;` is a question mark; the Armenian `:` is a full stop). A dynamic program picks the breaks that keep units close to the target. Units are at most 3 verses long, except for a single unbroken word.
   - **Refs.** The derived verses of the chunk at `ref` are `ref.s1`, `ref.s2`, … . Chunks already about a verse long keep their ref. Scripture, and any work ingested as verses (apocrypha from Bible editions, #103), is never split. The split depends only on the text, the language and frozen constants, so it is repeatable; changing those constants renumbers derived verses.
   - **Reader.** A source paragraph's derived verses are shown together as that paragraph, with its source number in the margin and small italic derived-verse numbers inline, unlike the source's own numbering (`web/src/lib/render.ts`).
   - **Result.** 970k chunks became 3.90M units: 3.27M derived verses and 0.63M unchanged chunks. Median unit size is 0.9–1.1 verses in every language, and p99 is under 2.5. Only Scripture still has units over 8,191 tokens: the Ge'ez 4 Baruch chapters that were ingested as single verses (#120).
   - **Translations.** Rare-language chunks that were split are translated again at the new granularity (`scripts.translate`; ~10.4k units, ~$15).
   - **Not done here:** ~11k chunks under 10 characters (headings, numbers, OCR fragments) stay in the text. The embedding step should skip them rather than merge them into neighbouring units, which would change source refs.
2. **Embedding model coverage of rare scripts** ([#3](https://github.com/jaspax/patristica/issues/3)). *Evaluated 2026-10-12* with the harness in `scripts/embed_eval/`. Full results are on #3. Findings:
   - **Quotes go to the keyword index.** Keyword search over normalized text finds an exact or near-verbatim quote at rank 1 in 0.94 of cases (0.98–1.00 for Scripture in every language). Every embedder scores below 0.5. So quoted queries (`"..."`) use the keyword index (#86).
   - **No equal-weight hybrid.** Fusing keyword and vector rankings made both quote and paraphrase search worse, so queries are routed rather than fused.
   - **Greek, Latin and Hebrew** are well served from English by OpenAI `text-embedding-3-large`: paraphrase R@3 0.95–1.0, topical R@100 0.85–1.0.
   - **No embedder reaches Coptic or Syriac from English.** OpenAI doesn't reach Armenian or Ge'ez; BGE-M3 reaches them only partly.
   - **Rare languages are therefore indexed through English translations** (#84). GPT-6.1 Sol and Opus 5.5 translate them about equally well under independent judging (fidelity ≈ 4.4–4.5 of 5, no hallucinations), with Sol at about a third of the cost. Haiku 5.5 invents content in about a quarter of passages.
   - **Translations confirmed (#84).** With Sol translations, every embedder reaches the rare languages from English: paraphrase R@3 0.94–0.99, topical R@100 0.77–0.99, Coptic and Syriac included. Best is Voyage `voyage-4-large` + translations (0.99 / 0.99); OpenAI + translations is close (0.98 / 0.94). Without translations, only Gemini `gemini-embedding-2` comes near (0.84 / 0.86). The full {language × embedder} matrix and method are in `docs/embedding-eval.md`. Production translation pipeline: #93.

### 2.4 Search API (internal)

Python function (later exposed via FastAPI):
```python
def search(query: str, top_k: int = 20, filters: dict = None) -> list[TextChunk]
```
- Quoted query (`"..."`): phrase match against the normalized keyword index (#86)
- Otherwise: embed query with same model; pgvector cosine similarity search, where a translated chunk scores the better of its original and English vectors
- Optional filters: language, author, date range, tradition
- Return ranked chunks with work/author metadata

*Status (#141):* `GET /search` in `api/search.py` implements the vector path over `chunk_vectors`. Filters are language, genre, source, work, author id (`anonymous` for `author_ids = []`), a date range (overlap with the chunk's range, so undated chunks drop out) and `out_of_period` (excluded unless asked). The HNSW scan is iterative (`relaxed_order`) and narrow filters may use the btree indexes instead. Query vectors are cached in memory (LRU), clients are rate-limited per IP, and a slow or failing Voyage call answers 503. Quoted queries are recognised (`parse_query`) but fall back to vector search until the keyword index exists (#86, #143).

---

## Phase 3: Web Application

### 3.1 Technology Stack

| Component | Choice |
|---|---|
| Backend API | FastAPI (Python) |
| Frontend | Next.js 16 (React, TypeScript), in `web/` |
| Auth | Optional at launch; add later for saved searches/notes |
| Deployment | Docker Compose: dev, and prod on one DigitalOcean droplet (Postgres + API, `infra/`, #117). All hosting consolidates on DigitalOcean: library data on Spaces (#131), Next.js on the droplet (#132) |
| AI features | Claude API (Anthropic) |

### 3.2 Core Features

**Search:**
- Text input → semantic vector search → ranked results
- Filter panel: date range, tradition (Eastern/Western/Syrian/etc.), language, author
- Keyword mode via search operators: quoted text is a phrase search over the normalized keyword index, not a semantic one (#86)
- Results show: canonical reference, author, work, date, snippet

**Citation Format:**
The primary reference shown to users must be the work title and author, not the collection or source database. The collection/edition is secondary provenance. Target format:
> *Apology*, by Tertullian — found in ANF Vol. 3 (`ccel-anf/anf03/…`)

This means `Work.title` and `Work.author` must be the individual work's identity, and `Work.edition` carries the anthology/volume label. The `source_id` and `work_id` are internal identifiers only, never shown directly to users. Wherever a canonical reference is displayed (search results, text view, AI synthesis citations), use `{author}, *{title}* {canonical_ref}` as the human-readable label, falling back to `*{title}* {canonical_ref}` when author is absent.

**Text View:**
- Side-by-side or tabbed display: original language | known translation | AI translation
- AI translation generated on demand via Claude API (cached after first generation)
- Contextual navigation: prev/next passage, jump to full work

**AI Synthesis:**
- "Synthesize" button on search results page
- Sends top N results to Claude with prompt: "Summarize what the Fathers teach on [topic]"
- Output clearly labeled as AI-generated, with citations to source texts

**Browse:**
- By author, tradition, time period, work
- Scripture browser with cross-links to Patristic commentary

*Status:* a first library browser exists (`web/`, #16). It has a work index with client-side search, facets, date range and sorting, and a reader that renders normalized chunks as text. It reads the static export from `scripts/export_library.py` (`index.json` plus one JSON file per work), not an API. When the FastAPI backend exists, replace those fetches in `web/src/lib/library.ts` with `/api/works/*`. The rendering rules (section headings from the ref hierarchy, rubrics, out-of-period marking) live in `web/src/lib/render.ts`.

*Search (#142):* `/search` sends the query and the library index's facets (author, language, genre, collection, dates) to `/api/search`. Results are listed by score, citation first (`{author}, *{title}* {ref}`), then the text in its own script, an English machine translation for the rare languages, and language, date, collection/edition, licence and source. Each result opens the reader at the passage, highlighted.

### 3.3 API Routes (FastAPI)

```
GET  /api/search?q=...&filters=...     → ranked TextChunk[]
GET  /api/works/{work_id}              → Work metadata
GET  /api/chunks/{chunk_id}            → Full chunk with translations
POST /api/translate                    → AI translation for a chunk
POST /api/synthesize                   → AI synthesis of a result set
GET  /api/authors                      → Author list/browse
```

### 3.4 Deployment

- Docker Compose: `web` (Next.js), `api` (FastAPI), `db` (PostgreSQL + pgvector)
- Production (#50, #117, #132): `web`, `api` and `db` run on one DigitalOcean droplet (NYC, 8 GB; 16 GB if the index doesn't stay cached) behind Caddy, provisioned with OpenTofu, with a nightly `pg_dump` to DigitalOcean Spaces. The runbook is `infra/README.md`.
- *Decided 2026-10-15:* consolidate on DigitalOcean rather than spreading over three providers. The static library moves from R2 to Spaces (#131, done), and `web` moves from Vercel to the droplet (#132, done). The cost is a single point of failure, no preview deploys and no edge CDN for the app shell (the library data is on the Spaces CDN).
- Hostnames: the app is on the apex `patristica.app` (`www` redirects to it) and the API on `api.patristica.app`. Caddy also routes `/api/*` on the apex to the API with the prefix stripped, so the browser calls it same-origin and needs no CORS: the routes in §3.3 are `/api/…` as the web app sees them and are declared without `/api` in FastAPI.
- Deploys: merging to `master` runs `infra/deploy.sh --keep-env` from GitHub Actions (`.github/workflows/deploy.yml`), which rebuilds the images on the droplet. `NEXT_PUBLIC_*` settings are Docker build arguments.
- Separate `scripts/` container for ingestion jobs
- Environment-based config for API keys (OpenAI/Anthropic)

*Current (library browser, #17):* production is https://patristica.app, the `web` service on the droplet (`web/Dockerfile`, `output: "standalone"`). The static library export is in the DigitalOcean Spaces bucket `patristica-library` (provisioned in `infra/tofu`), uploaded with `scripts/upload_library.py`, and the app's `NEXT_PUBLIC_LIBRARY_URL` points at its CDN endpoint (https://patristica-library.nyc3.cdn.digitaloceanspaces.com). The earlier Vercel deployment (https://patristica-beta.vercel.app/) is retired once the droplet serves the site.

### 3.5 Licensing & Attribution Requirements

Every text carries its licence in `Work.license` (and provenance in `Work.provenance_url` / `Work.edition`). The public site must honour these:
- **Attribution:** display source edition, licence and provenance with every passage shown (search results, reader view, AI-generated syntheses that quote text). Most of the corpus is CC BY or CC BY-SA (PTA, First1KGreek, Perseus, OGL, Beta Masaheft, SBLGNT, Coptic Scriptorium); the versification mappings (`patristica/data/versification/`) are CC BY-SA too.
- **ShareAlike:** any redistributed derivative of CC BY-SA material (downloads, exports, an API serving text) must stay under CC BY-SA.
- **Non-commercial texts:** LXX Rahlfs (`lxx-rahlfs`, CC BY-NC-SA, with a CCAT user declaration) and the PTA Peshitta OT (CC BY-NC) may not be used commercially. If the site ever monetises (ads, paid tiers, API fees), filter these out or replace them (`pta-lxx` is a CC BY-SA Rahlfs alternative).
- **Licence page:** a page listing every source, its licence and required credit line, generated from the works manifest (`data/normalized/_works.jsonl`). *Status:* implemented as `/sources` in `web/`, generated from the library index (#31).
- **Project licensing (decided, #31):** code is MIT. Texts pass through their source licences, and our changes to a text take that text's licence. Our own metadata is CC0. See `DATA_LICENSE.md`. Unverified licences are tracked in #32.

---

## Immediate Next Steps (Session 1 Deliverables)

1. Create `CLAUDE.md` with project overview and tech decisions
2. Scaffold directory structure: `data/`, `scripts/`, `api/`, `web/`
3. Write `pyproject.toml` for the Python backend/scripts
4. Build first ingestion script targeting one well-structured source (CCEL NPNF TEI XML)
5. Define and migrate initial PostgreSQL schema

---

## Open Questions (to resolve before implementation)

- **Embedding model choice**: *decided 2026-10-13* (#3, #84; `docs/embedding-eval.md`): Voyage `voyage-4-large`, with GPT-6.1 Sol English translations as a second vector for the rare languages (#93). Vectors are 512-dim `halfvec` (#50); the full 1024-dim output is kept in object storage (DigitalOcean Spaces, #131).
- **Database hosting**: *decided 2026-10-14* (#50). Postgres 16 + pgvector and the FastAPI service run together under Docker Compose on one self-managed DigitalOcean Basic droplet in NYC (8 GB RAM, 4 vCPU, ~$48/mo), close to Vercel's `iad1` functions. Reasons:
  - **Size.** Splitting into verse-sized units (#2) gives ~3.9M units plus ~0.14M English translation vectors for the rare languages, so about 4.0M vectors. That made 1024 dims too big for 8 GB (≈ 8 GB of vectors alone), so vectors are 512-dim `halfvec`: ≈ 4.1 GB of vectors and an HNSW index of roughly 5–5.5 GB. The eval scored 512 dims at paraphrase/topical recall 0.99 / 0.97, against 0.99 / 0.99 at 1024, with the same worst language cell (`docs/embedding-eval.md`). Voyage vectors can be shortened, so the full 1024-dim vectors are stored in object storage and the size can change without re-embedding.
  - **8 GB is tight.** The index needs most of the droplet's memory to stay cached. Start on 8 GB, measure query latency, and resize to the 16 GB droplet (~$96/mo, an in-place resize on DigitalOcean) if the index doesn't stay in memory.
  - **The database is derived data.** Text and translations are in git, and the Voyage vectors are kept as a file in object storage, so a lost database is rebuilt without re-embedding. Managed hosts mostly sell backups, failover and point-in-time recovery, which don't matter until the app stores user data. Backup is a nightly `pg_dump` to DigitalOcean Spaces (#117).
  - **Alternatives (Oct 2026 prices).** Supabase Pro + Large (8 GB) ~$125/mo; Neon is cheap with scale-to-zero, but the HNSW index has to reload after every pause, so the first queries are slow (~$77/mo for 4 GB always on); RDS / DO Managed Postgres $100–245/mo. Hetzner's US regions are no cheaper after its June 2026 price increase.
  - **Revisit** when Phase 3 adds accounts or saved searches. Moving to managed Postgres (Supabase Large) is a dump and restore.
- **Copyrighted texts**: Identify specific modern translations (RSV, ESV, etc.) where licensing may be obtainable
- **Transliteration**: Do we offer Hebrew/Greek in romanized form for accessibility?
