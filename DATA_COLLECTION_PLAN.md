# Patristica: Data Collection — Detailed Implementation Plan

## Overview

This document covers Phase 1 of the implementation plan: acquiring, normalizing, and preparing all source texts for database ingestion. Sources are organized by category, with each source assigned a priority tier based on data quality, licensing clarity, and ingestion complexity.

---

## 1. Project Structure

```
patristica/
├── data/
│   ├── raw/            # Downloaded/scraped source files (gitignored if large)
│   ├── normalized/     # Normalized JSON records, one file per work
│   └── chunks/         # Chunked records ready for embedding
├── scripts/
│   ├── ingest/         # One module per source (e.g. ingest_ccel.py)
│   ├── normalize.py    # Normalize raw → normalized JSON
│   ├── chunk.py        # Chunk normalized → chunk JSON
│   ├── validate.py     # QC checks on normalized/chunk data
│   └── catalog.py      # Print ingestion status across all sources
├── patristica/
│   └── models.py       # Pydantic data models
├── pyproject.toml
└── ...
```

---

## 2. Canonical Data Models

Defined in `patristica/models.py` using Pydantic.

### Work record (one per work)
```python
class Work(BaseModel):
    work_id: str                  # slug: "augustine/confessions"
    source_id: str                # "ccel/npnf1-01"
    author: str | None
    title: str
    date_composed: int | None     # best single estimate (CE), negative = BCE
    date_range: tuple[int, int] | None
    genre: str                    # "scripture", "patristic", "liturgical", "council"
    language: str                 # ISO 639-3 code: "grc", "lat", "hbo", "syc", "cop", "gez", ...
    tradition: str | None         # "greek", "latin", "syriac", "ethiopic", "coptic", "armenian"
    license: str                  # "public_domain", "cc-by-4.0", "cc-by-nc-sa-4.0", etc.
    provenance_url: str | None
    translation_of: str | None    # work_id of the original-language work, if translation
```

### Chunk record (one per text unit)
```python
class Chunk(BaseModel):
    chunk_id: str                 # "{work_id}#{canonical_ref}"
    work_id: str
    canonical_ref: str            # e.g. "Gen.1.1", "Conf.1.1", "Typikon.Pascha.3"
    language: str
    text: str
    translation_group_id: str | None  # links parallel chunks across languages
    chunk_index: int              # sequential position within work
    context_before: str | None    # ~50-token overlap from prior chunk
    context_after: str | None     # ~50-token overlap from next chunk
```

---

## 3. Source Catalog

### Tier 1 — Bulk download, structured format, clear license
These should be ingested first. Data is available as GitHub repos or structured archives.

#### 3.1 Scripture

| ID | Text | Language | Source | Format | License |
|----|------|----------|--------|--------|---------|
| `scripture/oshb` | Open Scriptures Hebrew Bible | Hebrew (`hbo`) | github.com/openscriptures/morphhb | OSIS XML | CC-BY 4.0 |
| `scripture/sblgnt` | SBL Greek NT | Greek (`grc`) | github.com/LogosBible/SBLGNT + github.com/morphgnt/sblgnt | OSIS XML + morph TSV | CC-BY 4.0 |
| `scripture/nestle1904` | Nestle 1904 GNT | Greek (`grc`) | github.com/biblicalhumanities/Nestle1904 | USFM/XML | Public domain |
| `scripture/clementine` | Clementine Vulgate | Latin (`lat`) | dev.find.bible/bibles/LATCLV + Internet Archive | HTML/text | Public domain |
| `scripture/lxx-rahlfs` | Septuagint (Rahlfs 1935) | Greek (`grc`) | github.com/eliranwong/LXX-Rahlfs-1935 | USFM | CC-BY-NC-SA 4.0 |
| `scripture/kjv` | King James Version | English (`eng`) | github.com/aruljohn/Bible-kjv or similar | JSON/XML | Public domain |
| `scripture/asv` | American Standard Version | English (`eng`) | multiple GitHub mirrors | JSON/XML | Public domain |
| `scripture/web` | World English Bible | English (`eng`) | ebible.org/Scriptures/ | USFM | Public domain |
| `scripture/coptic-nt` | Sahidic Coptic NT (Horner) | Coptic (`cop`) | sahidica.org + Coptic Scriptorium GitHub | HTML/CoNLL-U | Free non-commercial / CC-BY |
| `scripture/wulfila` | Gothic Bible (Wulfila) | Gothic (`got`) | wulfila.be/gothic/download | TEI XML | Academic non-commercial |

#### 3.2 Patristic Texts

| ID | Collection | Language | Source | Format | License |
|----|-----------|----------|--------|--------|---------|
| `patristic/pta` | Patristic Text Archive | Greek (`grc`) | github.com/PatristicTextArchive | TEI P5 XML | CC-BY / CC-BY-SA |
| `patristic/oglt-pl` | Open Patrologia Latina (OGLT) | Latin (`lat`) | github.com/OpenGreekAndLatin | TEI XML | Open Educational |
| `patristic/first1k` | First1KGreek | Greek (`grc`) | github.com/OpenGreekAndLatin/First1KGreek | TEI XML | Open Educational |
| `patristic/perseus` | Perseus Greek/Latin | Greek (`grc`), Latin (`lat`) | github.com/PerseusDL/canonical-greekLit + canonical-latinLit | TEI XML | CC |
| `patristic/ccel-anf` | Ante-Nicene Fathers (10 vols) | English (`eng`) | ccel.org / Project Gutenberg | ThML/HTML | Public domain |
| `patristic/ccel-npnf1` | Nicene & Post-Nicene Fathers Series 1 (14 vols) | English (`eng`) | ccel.org / Project Gutenberg | ThML/HTML | Public domain |
| `patristic/ccel-npnf2` | Nicene & Post-Nicene Fathers Series 2 (14 vols) | English (`eng`) | ccel.org / Project Gutenberg | ThML/HTML | Public domain |

#### 3.3 Liturgical Texts

| ID | Text | Language | Source | Format | License |
|----|------|----------|--------|--------|---------|
| `liturgical/cantus` | CANTUS Latin Chant Database | Latin (`lat`) | cantusdatabase.org (API) | JSON (API) | Free |
| `liturgical/cursus` | CURSUS Medieval Liturgical Texts | Latin (`lat`) | zenodo.org/records/5090613 | TEI P4 XML | Academic |
| `liturgical/coptic-scriptorium` | Coptic Scriptorium liturgical corpus | Coptic (`cop`) | github.com/CopticScriptorium/corpora | CoNLL-U / TEI | CC-BY |

---

### Tier 2 — Downloadable but less structured; require significant parsing

| ID | Text | Language | Source | Format | Notes |
|----|------|----------|--------|--------|-------|
| `scripture/peshitta` | Peshitta NT (SEDRA) | Syriac (`syc`) | sedra.bethmardutho.org + github.com/peshitta/sedrajs | DB/JS | Non-commercial; JS conversion needed |
| `scripture/gez` | Ethiopic Bible (Ge'ez) | Ge'ez (`gez`) | Internet Archive (multiple editions) | PDF/text | Public domain; OCR quality varies |
| `scripture/armenian` | Classical Armenian Bible (Zohrab 1805) | Armenian (`hye`) | Internet Archive | PDF/text | Public domain; OCR needed |
| `scripture/vetus-latina` | Vetus Latina fragments | Latin (`lat`) | itseeweb.cal.bham.ac.uk | HTML | Check licensing; fragmentary |
| `patristic/ogpg` | Open Patrologia Graeca (OCR) | Greek (`grc`) | github.com/OGL-PatrologiaGraecaDev | .txt/.hocr | Public domain; OCR noise |
| `patristic/dco` | Documenta Catholica Omnia | Latin (`lat`) | documentacatholicaomnia.eu | PDF/DOC | Unclear license; Latin originals |
| `liturgical/gallican` | Gallican Liturgy (Neale/Forbes 1855) | Latin (`lat`) | Internet Archive | PDF | Public domain; OCR needed |
| `liturgical/mozarabic` | Mozarabic Rite (Ferotin editions) | Latin (`lat`) | Internet Archive | PDF | Public domain; OCR needed |
| `liturgical/gez-anaphoras` | Ethiopian Anaphoras (14 anaphoras) | Ge'ez (`gez`) | ethiopianorthodox.org + Internet Archive | PDF | Public domain |
| `liturgical/syriac-james` | Liturgy of St. James (Syriac) | Syriac (`syc`) | Internet Archive | PDF | Public domain |
| `liturgical/armenian-liturgy` | Armenian Divine Liturgy | Armenian (`hye`) | Internet Archive | PDF | Public domain |
| `councils/ecumenical` | Seven Ecumenical Councils | English/Greek (`eng`/`grc`) | CCEL / Internet Archive | HTML/PDF | Public domain |

---

### Tier 3 — Requires scraping or special API access

| ID | Text | Language | Source | Notes |
|----|------|----------|--------|-------|
| `liturgical/hudra` | East Syriac Hudra texts | Syriac (`syc`) | hudra.day | Free; may require scraping |
| `liturgical/goarch-chrysostom` | Liturgy of St. John Chrysostom (Greek) | Greek (`grc`) | goarch.org | HTML scrape |
| `liturgical/goarch-basil` | Liturgy of St. Basil (Greek) | Greek (`grc`) | goarch.org | HTML scrape |
| `liturgical/typikon` | Greek Typikon (selected pre-1054 sections) | Greek (`grc`) | equip-orthodox.com + manual curation | PDF; date filtering required |
| `patristic/tertullian` | Tertullian.org corpus | English (`eng`) | tertullian.org | HTML scrape |

---

### Tier 4 — Subscription/restricted (deferred or seek access)

| Text | Source | Notes |
|------|--------|-------|
| Thesaurus Linguae Graecae (full) | tlg.uci.edu | Institutional subscription required |
| Patrologia Orientalis (full) | Brepols | Subscription; covers Eastern fathers in Syriac, Coptic, Armenian, Ge'ez |
| Coptic OT (full) | coptot.manuscriptroom.com | May require arrangement |

---

## 4. Ingestion Pipeline Architecture

Each source has a dedicated ingestion module in `scripts/ingest/`. All modules implement a common interface:

```python
def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """
    Download/parse source, write one JSON file per work to output_dir/raw/{source_id}/.
    Returns list of Work metadata records.
    Skip already-downloaded files unless force=True.
    """
```

Common utilities in `scripts/ingest/_common.py`:
- `download_file(url, dest, etag_cache=True)` — idempotent HTTP download with ETag caching
- `parse_tei(path)` — shared TEI XML parser returning `(metadata, list[str paragraphs])`
- `parse_osis(path)` — OSIS XML parser (for OSHB, SBLGNT)
- `parse_usfm(path)` — USFM parser (for Nestle1904, LXX)
- `clean_html(html)` — strip markup, normalize whitespace
- `slugify_ref(ref)` — normalize canonical references

### Execution order (suggested)

```
Tier 1 GitHub sources  →  Tier 1 CCEL/web  →  Tier 2 archive sources  →  Tier 3 scraped
```

Run all ingestion:
```bash
python -m scripts.catalog         # show status before
python -m scripts.ingest.all      # run all Tier 1 ingestors
python -m scripts.validate        # check output
```

---

## 5. Normalization

`scripts/normalize.py` converts raw ingest output → normalized `Chunk` JSON records.

### Chunking rules by genre

| Genre | Primary unit | Target tokens | Overlap |
|-------|-------------|---------------|---------|
| Scripture | Verse | 1 verse (varies) | None (verse = atomic) |
| Scripture (context) | Paragraph/pericope | 300–500 | 1 verse |
| Patristic prose | Paragraph / `<div>` section | 400–600 | 50 tokens |
| Liturgical prose | Prayer / collect / strophe | 200–400 | 1 sentence |
| Liturgical poetry/hymnody | Stanza | 1 stanza | None |
| Council acts | Paragraph / canon | 300–500 | 50 tokens |

### Canonical reference format

All chunks carry a `canonical_ref` in dot-separated form:
- Scripture: `Gen.1.1`, `Matt.5.3`
- Patristic: `{author_abbrev}.{work_abbrev}.{book}.{section}.{paragraph}` — e.g. `Aug.Conf.1.1.1`
- Liturgical: `{rite}.{service}.{element}` — e.g. `ByzLit.Chrysostom.Anaphora.3`
- Councils: `Nicaea1.Canon.7`

### Translation linking

After all chunks are normalized, `scripts/link_translations.py` creates `translation_group_id` values by aligning chunks with the same canonical reference across languages. For Scripture this is deterministic (verse IDs). For Patristics it requires a section-level alignment heuristic or manual mapping table.

---

## 6. Date Filtering for Hybrid Texts

Some sources (especially liturgical) contain material from a wide date range. Handle as follows:

- **Typikon**: Use section-level composition dates from academic sources. Include only sections plausibly pre-1054. Annotate each chunk with `date_composed` and `date_range`; post-1054 content flagged `excluded=True` in the raw record but retained in data files.
- **Beth Gazo / Hudra**: Include sections attributable to pre-1054 hymnographers (Ephrem the Syrian d.373, Narsai d.502, etc.). Flag uncertain-date sections with `date_confidence: "uncertain"`.
- **Sarum Use**: Post-dates the cutoff; include only demonstrably pre-schism liturgical elements.
- **CANTUS chants**: Filter by `century` metadata field where available; include chants attributed to Gregory I (d.604) and earlier, flag later attributions.

All chunks carry:
```python
date_composed: int | None      # best estimate (CE)
date_range: tuple[int,int] | None
date_confidence: str           # "established" | "approximate" | "uncertain"
post_schism: bool              # True if composition date > 1054 CE
```

---

## 7. Language & Encoding

All text stored as Unicode (UTF-8). Source-specific conversions required:

| Source encoding | Conversion needed |
|----------------|-------------------|
| Beta code (CCAT LXX) | `beta2unicode` Python library |
| SEDRA transliteration | Syriac Unicode mapping table |
| Ge'ez Internet Archive PDFs | OCR with Tesseract `gez` model + manual QC |
| Armenian Internet Archive PDFs | OCR with Tesseract `hye` model + manual QC |

---

## 8. Quality Control

`scripts/validate.py` checks:
- No empty `text` fields
- All `language` values are valid ISO 639-3 codes
- All `canonical_ref` values parse against their expected schema
- No duplicate `chunk_id` values
- `date_composed` plausible for claimed `genre`/`tradition`
- Translation groups have ≥2 members

Output: validation report as `data/validation_report.json`.

---

## 9. Dependency Manifest

`pyproject.toml` dependencies for ingestion:

```toml
[project]
name = "patristica-ingest"
requires-python = ">=3.11"
dependencies = [
    "requests",
    "httpx",
    "lxml",
    "beautifulsoup4",
    "pydantic>=2",
    "tqdm",
    "python-slugify",
    "tiktoken",           # token counting for chunking
    "usfm-grammar",       # USFM parsing
    "beta2unicode",       # Greek betacode conversion
]
```

---

## 10. Milestone Checklist

### Milestone 1: Infrastructure (session 1)
- [x] Scaffold directory structure
- [x] `pyproject.toml` + dev environment
- [x] Pydantic models (`patristica/models.py`)
- [x] Common ingestion utilities (`scripts/ingest/_common.py`)
- [x] Catalog/status script

### Milestone 2: Scripture — Tier 1 (sessions 2–3)
- [x] OSHB (Hebrew Bible) ingestion + OSIS parser  (`scripts/ingest/oshb.py`)
- [x] SBLGNT + MorphGNT ingestion  (`scripts/ingest/sblgnt.py`; text only, no morph)
- [x] Clementine Vulgate ingestion  (`scripts/ingest/clementine.py`; eBible USFM)
- [x] LXX Rahlfs ingestion  (`scripts/ingest/lxx_rahlfs.py`; CC-BY-NC-SA, CCAT decl. req'd)
- [x] KJV / ASV / WEB ingestion  (`scripts/ingest/kjv.py`, `asv.py`, `web.py`)
- [x] Sahidic Coptic NT  (`scripts/ingest/coptic_nt.py`; scrollmapper CopSahBible2)
- [x] Gothic Wulfila  (`scripts/ingest/wulfila.py`; Wulfila Project TEI)
- [x] Chunking + translation linking for all Scripture  (`normalize.py`, `chunk.py`, `link_translations.py`)

### Milestone 3: Patristic Texts — Tier 1 (sessions 4–6)
- [ ] Patristic Text Archive (PTA) TEI ingestion
- [ ] First1KGreek + OGLT Patrologia Latina
- [ ] Perseus canonical Greek/Latin
- [ ] CCEL ANF/NPNF HTML ingestion (scrape or ThML parse)
- [ ] Author/work metadata table population

### Milestone 4: Liturgical Texts — Tier 1 (sessions 7–8)
- [ ] CANTUS Database API ingestion
- [ ] CURSUS TEI liturgical texts
- [ ] Coptic Scriptorium liturgical content
- [ ] goarch.org Greek liturgies (Chrysostom, Basil)

### Milestone 5: Tier 2 Sources (sessions 9–12)
- [ ] SEDRA Peshitta
- [ ] Ge'ez Bible (OCR pipeline)
- [ ] Classical Armenian Bible (OCR pipeline)
- [ ] Open Patrologia Graeca (OCR noise handling)
- [ ] Gallican + Mozarabic liturgies
- [ ] Ethiopian Anaphoras
- [ ] Syriac Liturgy of St. James
- [ ] Ecumenical Council texts

### Milestone 6: Tier 3 Sources (sessions 13–14)
- [ ] Hudra.day Syriac liturgical scrape
- [ ] Tertullian.org corpus scrape
- [ ] Typikon date-filtered ingestion

### Milestone 7: QC & Handoff (session 15)
- [ ] Full validation pass
- [ ] Translation linkage for all Scripture
- [ ] Chunk count report by language/genre/tradition
- [ ] Hand normalized JSON to Phase 2 (database construction)

---

## 11. Known Gaps & Risks

| Gap | Mitigation |
|-----|-----------|
| No clean Ge'ez digital text; PDFs only | OCR with Ge'ez Tesseract model; flag low-confidence passages |
| SEDRA Peshitta is JS-native; no Python parser | Use Node.js subprocess or port the sedrajs data layer to Python |
| Typikon date filtering requires scholarly judgment | Compile a date annotation table from academic literature; default to inclusion when uncertain |
| TLG/Patrologia Orientalis behind paywall | Defer; note gaps in validation report; seek institutional access |
| Migne PG OCR quality highly variable | Use Open PG GitHub (already OCR'd); supplement with PTA where critical editions exist |
| Gallican/Mozarabic liturgy sources are 19th-century editions (may contain editorial additions) | Document edition metadata; flag as `edition_date: 1855` etc. |
