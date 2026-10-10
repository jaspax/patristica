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
| Embeddings | `text-embedding-3-large` (OpenAI) or `multilingual-e5-large` | Multilingual support required |
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
  embedding vector(1536),    -- or 3072 for large model
  translation_group_id       -- links original + translations of same passage
)
translation_groups (id)      -- joins parallel chunks across languages
```

### 2.3 Indexing Pipeline

1. Load normalized JSON from Phase 1
2. Insert author/work metadata into PostgreSQL
3. For each chunk: call embedding API → store chunk + embedding
4. Build HNSW index on `text_chunks.embedding` via pgvector
5. Build Postgres `tsvector` full-text index for keyword fallback

**Script:** `scripts/build_index.py` — idempotent, resumable (skip already-embedded chunks)

### 2.4 Search API (internal)

Python function (later exposed via FastAPI):
```python
def search(query: str, top_k: int = 20, filters: dict = None) -> list[TextChunk]
```
- Embed query with same model
- pgvector cosine similarity search
- Optional filters: language, author, date range, tradition
- Return ranked chunks with work/author metadata

---

## Phase 3: Web Application

### 3.1 Technology Stack

| Component | Choice |
|---|---|
| Backend API | FastAPI (Python) |
| Frontend | Next.js 14+ (React, TypeScript) |
| Auth | Optional at launch; add later for saved searches/notes |
| Deployment | Docker Compose (dev), cloud VM + managed Postgres (prod) |
| AI features | Claude API (Anthropic) |

### 3.2 Core Features

**Search:**
- Text input → semantic vector search → ranked results
- Filter panel: date range, tradition (Eastern/Western/Syrian/etc.), language, author
- Hybrid mode: toggle between semantic and keyword search
- Results show: canonical reference, author, work, date, snippet

**Citation Format:**
The primary reference shown to users must be the work title and author, not the collection or source database. The collection/edition is secondary provenance. Target format:
> *Apology*, by Tertullian — found in ANF Vol. 3 (`patristic/ccel-anf/anf03/…`)

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
- Separate `scripts/` container for ingestion jobs
- Environment-based config for API keys (OpenAI/Anthropic)

---

## Immediate Next Steps (Session 1 Deliverables)

1. Create `CLAUDE.md` with project overview and tech decisions
2. Scaffold directory structure: `data/`, `scripts/`, `api/`, `web/`
3. Write `pyproject.toml` for the Python backend/scripts
4. Build first ingestion script targeting one well-structured source (CCEL NPNF TEI XML)
5. Define and migrate initial PostgreSQL schema

---

## Open Questions (to resolve before implementation)

- **Embedding model choice**: multilingual model needed for Greek/Latin/Hebrew/Syriac — evaluate `multilingual-e5-large` vs. OpenAI `text-embedding-3-large`
- **Hosting budget**: pgvector at scale (millions of vectors) requires significant RAM — confirm target infrastructure
- **Copyrighted texts**: Identify specific modern translations (RSV, ESV, etc.) where licensing may be obtainable
- **Transliteration**: Do we offer Hebrew/Greek in romanized form for accessibility?
