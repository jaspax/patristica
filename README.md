# Patristica

A searchable online database of Scriptural and Patristic writings from the early church, covering the period up to the Great Schism (1054 AD).

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

All sources are public domain unless otherwise noted.

## Project Phases

1. **Data Collection** — ingestion and normalization of source texts from CCEL, Perseus, Project Gutenberg, and other repositories
2. **Database Construction** — PostgreSQL + pgvector for structured storage and semantic indexing
3. **Web Application** — FastAPI backend and Next.js frontend with search, text view, and AI features

See [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for full technical detail.

## Tech Stack

- Python (ingestion scripts, FastAPI backend)
- PostgreSQL + pgvector (database and vector search)
- Next.js / React (frontend)
- Claude API (AI translation and synthesis)
