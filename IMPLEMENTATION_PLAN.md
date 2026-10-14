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
| Embeddings | **Decided (2026-10-13):** Voyage `voyage-4-large`. Syriac, Coptic, Armenian and Ge'ez chunks also get an English translation by GPT-6.1 Sol, embedded as a second vector | `docs/embedding-eval.md`: paraphrase/topical recall 0.99/0.99, every language ≥ 0.90; best at every vector size. 1024-dim `halfvec` (decided 2026-10-14, #50) |
| ORM/migration | SQLAlchemy + Alembic | Python ecosystem |
| Search layer | Custom (via pgvector + Postgres FTS) | Avoid unnecessary infra |

### 2.2 Schema

**Core tables:**

```sql
authors (id, name, birth_date, death_date, tradition, bio)
works (id, author_id, title, date_range, genre, language, license)
text_chunks (
  id, work_id, canonical_ref, language,
  text, chunk_index,
  embedding halfvec(1024),   -- Voyage voyage-4-large (#50)
  translation_group_id       -- links original + translations of same passage
)
translation_groups (id)      -- joins parallel chunks across languages
```

### 2.3 Indexing Pipeline

1. Load normalized JSON from Phase 1
2. Insert author/work metadata into PostgreSQL
3. Translate Syriac, Coptic, Armenian and Ge'ez chunks into English with GPT-6.1 Sol (`scripts.translate`, #93). Translations are stored in `data/translations/`, one file per work, mirroring `data/normalized/`, with model, prompt version and date recorded per run.
4. For each chunk: call embedding API → store chunk + embedding (plus a second embedding for the translation, where there is one)
5. Build HNSW index on `text_chunks.embedding` via pgvector
6. Build the keyword index over normalized text (`patristica.textfold.fold`) for quoted search (#86)

**Script:** `scripts/build_index.py` — idempotent, resumable (skip already-embedded chunks)

### 2.5 Open Issues (from the Phase 1 handoff — resolve before building the index)

Inputs and the data contract are described in `DATA_COLLECTION_PLAN.md` → "Phase 2 Handoff".

1. **Chunk size normalization** ([#2](https://github.com/jaspax/patristica/issues/2)). Phase 1 chunks are source units (verse, paragraph, div), and their sizes vary wildly. Measured with `cl100k_base`:
   - 302 chunks exceed 8,191 tokens, the OpenAI embedding input limit. The worst are whole PTA manuscripts (`pta0022`) at up to ~144k tokens each; others come from OGLT PL (112), First1KGreek (48) and the Mozarabic/Gallican OCR (38).
   - ~68k chunks exceed 512 tokens (the `multilingual-e5-large` limit); ~39k exceed 2,000 tokens.
   - ~11k chunks are under 10 characters (headings, verse numbers, OCR fragments).

   Add a size-normalization step before embedding, ideally in `scripts/chunk.py` so `data/chunks/` is embedding-ready: split oversized chunks on sentence/clause boundaries into sub-chunks with stable derived refs (e.g. `{canonical_ref}.s{n}`) that keep `work_id`, dates and `translation_group_id`; merge or drop trivially short chunks. The target size depends on the embedding model (item 2), so decide them together.
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

---

## Phase 3: Web Application

### 3.1 Technology Stack

| Component | Choice |
|---|---|
| Backend API | FastAPI (Python) |
| Frontend | Next.js 16 (React, TypeScript), in `web/` |
| Auth | Optional at launch; add later for saved searches/notes |
| Deployment | Docker Compose: dev, and prod on one DigitalOcean VM (Postgres + API); Next.js on Vercel (#50) |
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
- Production (#50): `web` stays on Vercel; `api` and `db` run on one DigitalOcean droplet (NYC, 8 GB), with a nightly `pg_dump` to R2
- Separate `scripts/` container for ingestion jobs
- Environment-based config for API keys (OpenAI/Anthropic)

*Current (library browser, #17):* production is https://patristica-beta.vercel.app/. The Next.js app is on Vercel (Hobby plan, production branch `master`, root directory `web`). The static library export is in a Cloudflare R2 bucket, uploaded with `scripts/upload_library.py`. Vercel's `NEXT_PUBLIC_LIBRARY_URL` points at the bucket's public URL (https://pub-7022ba788905451f9b1a0db66d769964.r2.dev). The R2 public URL and Vercel production URL are reachable by anyone who has them; Vercel Hobby can only restrict preview deployments.

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

- **Embedding model choice**: *decided 2026-10-13* (#3, #84; `docs/embedding-eval.md`): Voyage `voyage-4-large`, with GPT-6.1 Sol English translations as a second vector for the rare languages (#93). Vectors are 1024-dim `halfvec` (#50).
- **Database hosting**: *decided 2026-10-14* (#50). Postgres 16 + pgvector and the FastAPI service run together under Docker Compose on one self-managed DigitalOcean Basic droplet in NYC (8 GB RAM, 4 vCPU, ~$48/mo), close to Vercel's `iad1` functions. Reasons:
  - **Size.** ~1.1M vectors × 1024 dims as `halfvec` take ≈ 2.3 GB, and the HNSW index ≈ 2.5–3 GB, which fits in 8 GB alongside the API. If the index stops fitting in memory, the next step is the 16 GB droplet (~$96/mo).
  - **The database is derived data.** Text and translations are in git, and the Voyage vectors are kept as a file in R2, so a lost database is rebuilt without re-embedding. Managed hosts mostly sell backups, failover and point-in-time recovery, which don't matter until the app stores user data. Backup is a nightly `pg_dump` to R2.
  - **Alternatives (Oct 2026 prices).** Supabase Pro + Large (8 GB) ~$125/mo; Neon is cheap with scale-to-zero, but the HNSW index has to reload after every pause, so the first queries are slow (~$77/mo for 4 GB always on); RDS / DO Managed Postgres $100–245/mo. Hetzner's US regions are no cheaper after its June 2026 price increase.
  - **Revisit** when Phase 3 adds accounts or saved searches. Moving to managed Postgres (Supabase Large) is a dump and restore.
- **Copyrighted texts**: Identify specific modern translations (RSV, ESV, etc.) where licensing may be obtainable
- **Transliteration**: Do we offer Hebrew/Greek in romanized form for accessibility?
