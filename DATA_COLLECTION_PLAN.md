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

| ID | Text | Language | Source | Format | License | Notes |
|----|------|----------|--------|--------|---------|-------|
| `scripture/oshb` | Open Scriptures Hebrew Bible | Hebrew (`hbo`) | github.com/openscriptures/morphhb | OSIS XML (word-level) | CC-BY 4.0 | ZIP: morphhb-master.zip; words inside `<w>` with lemma/morph; text reconstructed by joining `<w>` children |
| `scripture/sblgnt` | SBL Greek NT | Greek (`grc`) | github.com/LogosBible/SBLGNT | Custom Logos XML (NOT OSIS) | Non-commercial | ZIP: SBLGNT-master.zip; uses `<verse-number id="Book Ch:V">` + `<w>` + `<suffix>`; custom parser required |
| `scripture/nestle1904` | Nestle 1904 GNT | Greek (`grc`) | github.com/biblicalhumanities/Nestle1904 | USFM/XML | Public domain | Not yet ingested (M2 deferred) |
| `scripture/clementine` | Clementine Vulgate | Latin (`lat`) | ebible.org/Scriptures/ (`latVUC_usfm.zip`) | USFM | Public domain | 73 books incl. Deuterocanon; footnotes stripped via `_ebible_usfm` helper |
| `scripture/lxx-rahlfs` | Septuagint (Rahlfs 1935) | Greek (`grc`) | github.com/eliranwong/LXX-Rahlfs-1935 | Word-list CSV + verse-index CSV | CC-BY-NC-SA 4.0 | CCAT user declaration required; word list 3-col (`idx\tidx\tword`); verse index start-only; 33 books produced |
| `scripture/kjv` | King James Version | English (`eng`) | github.com/aruljohn/Bible-kjv | JSON per book (no spaces in filename: `1Samuel.json`) | Public domain | 66 books |
| `scripture/asv` | American Standard Version | English (`eng`) | github.com/scrollmapper/bible_databases (`ASV.csv`) | CSV (`Book,Chapter,Verse,Text`) | Public domain | 48 books (scrollmapper ASV lacks some books — see gap below) |
| `scripture/web` | World English Bible | English (`eng`) | ebible.org/Scriptures/ (`engwebp_usfm.zip`) | USFM | Public domain | `WEB.csv` does not exist in scrollmapper; use eBible USFM; Strong's annotations stripped |
| `scripture/coptic-nt` | Sahidic Coptic NT | Coptic (`cop`) | github.com/scrollmapper/bible_databases (`CopSahBible2.csv`) | CSV | Public domain | 50 files (includes some OT books from this CSV) |
| `scripture/wulfila` | Gothic Bible (Wulfila) | Gothic (`got`) | wulfila.be/gothic/text/gotica.xml | TEI P5 XML | Academic non-commercial | 18 books; identified by `xml:id="B1"–"B18"` with German headings; words in `<app><rdg><w>` |

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
| `scripture/peshitta` | Peshitta NT (SEDRA) | Syriac (`syc`) | sedra.bethmardutho.org + github.com/peshitta/sedrajs | DB/JS | **Superseded by `scripture/pta-peshitta` (clean TEI, 85 books)** |
| `scripture/gez` | Ethiopic Bible (Ge'ez) | Ge'ez (`gez`) | github.com/LPettay/ethiopian-bible (Beta Masaheft data) | JSON chapter files | CC-BY-SA 4.0 |
| `scripture/armenian` | Classical Armenian Bible (Zohrab 1895) | Armenian (`hye`) | arak29.org/bible/book/ (1895 Constantinople edition) | HTML per chapter | Public domain |
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
- `parse_osis(path)` — OSIS XML parser (for OSHB and other OSIS sources)
- `parse_usfm(path)` — USFM parser (for eBible and similar sources)
- `clean_html(html)` — strip markup, normalize whitespace
- `slugify_ref(ref)` — normalize canonical references

Higher-level shared helpers (use instead of duplicating logic):
- `_scripture_meta.py` — `OT_BOOKS`, `NT_BOOKS`, `BOOK_TITLE`, `BOOK_DATES`, `FULL_NAME_TO_ABBREV`, `book_work_id()` — shared across all scripture ingestors
- `_scrollmapper.py` / `ingest_scrollmapper()` — downloads and parses any translation from `github.com/scrollmapper/bible_databases` CSV format
- `_ebible_usfm.py` / `ingest_ebible_usfm()` — downloads and parses any eBible.org USFM zip (pre-processes Strong's numbers and footnotes); also exports `USFM_TO_OSIS` code map
- `_ingestor_main.py` / `ingestor_main()` — standard CLI entry point; call from every ingestor's `if __name__ == "__main__"` block

Each ingestor must also define a `SOURCE_ID` constant at module level (used by the entry point).

### Running ingestors

```bash
# All sources:
uv run python -m scripts.ingest.all

# Single source by ID:
uv run python -m scripts.ingest.all --source scripture/oshb [--force]

# Single source module directly:
uv run python -m scripts.ingest.oshb [--force]

# Check what ran and when:
uv run python -m scripts.catalog
```

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

- **Typikon** and **Hudra**: Ingest all content in the primary pass; apply `post_schism` flags in a dedicated second pass (see below). The ingestors should preserve feast-section headings as structured metadata (not just inline text) so the second pass can operate at section granularity without re-parsing.
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

### Post-schism saint filtering — second pass design

The Typikon and Hudra both organize content around feast days, some of which commemorate saints canonized after 1054 CE (Greek tradition) or after the Church of the East's principal canonization period. The hymnography composed for these feasts (troparia, kontakia, canons) is post-schism even though it appears in the same book as genuinely ancient material. This cannot be reliably resolved at ingestion time without a pre-compiled saint-date lookup table.

**Approach:** Ingest everything in the primary pass with `post_schism=False` as the default. Run `scripts/flag_liturgical.py` as a separate step after primary ingestion is complete.

**Implementation notes for `scripts/flag_liturgical.py`:**
- Maintain `data/post_schism_feasts.csv` with columns `tradition`, `feast_name` (normalized), `saint_name`, `canonization_year`, `notes`. This file is the authoritative source and should be reviewed manually before each pipeline run.
- The ingestors must expose the feast section heading in each chunk's `canonical_ref` or in a sidecar metadata field so the flagging script can do a direct lookup without re-parsing the source XML/text.
- Apply `post_schism=True` to all chunks whose containing feast section matches an entry in the lookup table. Propagate the flag to the entire section (heading + all following hymnographic chunks) rather than individual chunks.
- For feast sections **not** in the lookup table, leave `post_schism=False` and `date_confidence="uncertain"`. The default-include policy means marginally post-schism or disputed feasts are included until positive evidence of post-1054 canonization is established.
- **Reference sources for building the lookup table:**
  - Greek: *Synaxarion of Constantinople* (Hieromonk Makarios of Simonos Petra, Ormylia 1998–2005) gives feast-by-feast origin dates for the Byzantine calendar.
  - East Syriac: *The Martyrology and Hagiology of the Church of the East* (Fiey, CSCO 1963) and the Hudra critical editions by Sauget and Jammo.
- The flagging script is idempotent: re-running it with an updated `post_schism_feasts.csv` corrects previously set flags.

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
- [x] LXX with Deuterocanon — full Rahlfs 1935 (80 OT + 5 variant editions + 27 NT books) via PTA pta9999  (`scripts/ingest/pta_lxx.py`; CC-BY-SA 4.0 OT / CC-BY 4.0 NT; supersedes the 33-book `lxx-rahlfs` gap; includes Judith, Tobit, 1–4 Maccabees, Wisdom, Sirach, Baruch, Ep. Jer., 1 Esdras, Odes, Psalms of Solomon, Theodotion + OG variants for Daniel/Susanna/Bel)

### Milestone 3: Patristic Texts — Tier 1 (sessions 4–6)
- [x] Patristic Text Archive (PTA) TEI ingestion  (`scripts/ingest/pta.py`; git clone; 163 works incl. 9 Armenian-language; CC-BY/CC-BY-SA)
- [x] Syriac Peshitta — 85 books via PTA pta9999  (`scripts/ingest/pta_peshitta.py`; CC-BY NT / CC-BY-NC OT; supersedes M5 SEDRA plan)
- [x] Author/work metadata table population  (`scripts/ingest/_patristic_meta.py`)
- [x] Normalize patristic prose  (`normalize.py` now handles `genre: "patristic"` with `"paragraphs"`)
- [x] First1KGreek + OGLT Patrologia Latina  (`scripts/ingest/first1k.py` 1104 works grc, date≥−50 CE; `scripts/ingest/oglt_pl.py` 1453 works lat; CC-BY-SA 4.0)
- [x] Perseus canonical Greek/Latin  (`scripts/ingest/perseus.py`; git clone canonical-greekLit + canonical-latinLit; repos stored under `data/raw/_repos/` to avoid catalog pollution; dedup against First1KGreek by CTS work ID; same −50 CE / post-schism date filters; `XMLParser(no_network=True)` required — Latin files reference remote Perseus DTDs; 892 works: 658 grc + 234 lat; CC-BY-SA 4.0)
- [x] CCEL ANF/NPNF ThML ingestion  (`scripts/ingest/ccel_anf.py` 10 vols, `ccel_npnf1.py` 14 vols, `ccel_npnf2.py` 14 vols; shared `_ccel_common.py`; downloads from `https://ccel.org/ccel/s/schaff/{volume_id}.xml`; ETag-cached; ANF uses `<h1>` for headings, NPNF uses `<p>`; output filename is positional `{div1_counter:03d}.json` for stability; author matched via 3-pass fuzzy strategy against `_patristic_meta.AUTHORS`; 343 works total; public domain eng; `translation_of=None` — linking pass deferred to M7)

### Milestone 4: Liturgical Texts — Tier 1 (sessions 7–8)
- [x] CANTUS Database API ingestion — 22 manuscripts (860–1200 CE), 63,062 chants; `liturgical/cantus`
- [x] CURSUS TEI liturgical texts — 12 English Benedictine manuscripts, 32,180 chunks; `liturgical/cursus`
- [x] Coptic Scriptorium corpus — 49 works (Shenoute, AP, Besa, Pachomius, pseudo-attributed homilies, hagiographies, liturgical texts); 14,595 chunks; `liturgical/coptic-scriptorium` (`scripts/ingest/coptic_scriptorium.py`; CC-BY 4.0; Coptic `cop`; shallow clone to `data/raw/_repos/coptic-scriptorium/`; handles both TEI P5 and custom `<meta>` annotation formats)
- [x] goarch.org Greek liturgies (Chrysostom, Basil) — **source changed to dcs.goarch.org** (DCS serves plain static HTML, publicly accessible). `fetch_dcs_html` + `parse_dcs_liturgy` in `_goarch_common.py` handle the bilingual `table#biTable` layout. 403/1 works each; Chrysostom 403 chunks, Basil 417 chunks; `liturgical/goarch-chrysostom`, `liturgical/goarch-basil`

### Milestone 5: Tier 2 Sources (sessions 9–12)
- [x] Ecumenical Council texts — 17 works (7 ecumenical + Trullo + 5 provincial + 4 Sardica/Carthage), 4213 chunks; `councils/ecumenical` (`scripts/ingest/ecumenical.py`; Schaff/Percival NPNF2-14; public domain; genre `council`; `normalize_council_work()` added to `normalize.py`)
- [x] Open Patrologia Graeca (OCR noise handling) — 176 works, 139,196 chunks from 196 repos (PG Vol. 1–161; 3 repos are empty: Vol.-58-59, Vol.-61-62, Vol.-65-66); `patristic/ogpg` (`scripts/ingest/ogpg.py`); glob-based sparse git clone (no API calls needed; avoids 60 req/hour unauthenticated rate limit); Greek/Latin column separation by line-level Greek char ratio (≥35%); page-boundary paragraph flush; function-word quality filter (≥2 Greek function words per paragraph); public domain
- [x] Ge'ez Bible — 36 books, 18,296 chunks; `scripture/gez` (`scripts/ingest/gez.py`; shallow clone `LPettay/ethiopian-bible`; CC-BY-SA 4.0 Beta Masaheft data; includes 1 Enoch, Jubilees, Meqabyan 1–3, Kebra Nagast, Synaxarion; no OCR needed)
- [x] Classical Armenian Bible (Zohrab 1895 text) — 75 books, 35,309 chunks; `scripture/armenian` (`scripts/ingest/armenian.py`; HTML scrape of arak29.org; public domain; full Bible incl. Deuterocanon + 1 Esdras; LXX book numbering; no OCR needed)
- [x] Gallican liturgies — 2 works (Missale Gothicum 219 chunks, Missale Gallicanum Vetus 391 chunks); `liturgical/gallican` (`scripts/ingest/gallican.py`; IA OCR; public domain; Bobbio + Stowe omitted — only facsimile editions available on IA)
- [x] Mozarabic rite — 2 works (Liber Mozarabicus Sacramentorum 612 chunks, Liber Ordinum 486 chunks); `liturgical/mozarabic` (`scripts/ingest/mozarabic.py`; Ferotin 1904/1912 via IA; public domain)
- [x] Ethiopian Anaphoras — 13 works, ~1166 chunks; `liturgical/gez-anaphoras` (`scripts/ingest/gez_anaphoras.py`; "Anaphoras of the Ethiopic Liturgy" 1928 IA English translation; public domain; Basil not in OCR)
- [x] Syriac Liturgy of St. James — 468 chunks; `liturgical/syriac-james` (`scripts/ingest/syriac_james.py`; CCEL ANF Vol. 7 English translation; public domain)
- [x] Liturgy of the Holy Apostles Adai and Mari — 233 chunks; `liturgical/adai-mari` (`scripts/ingest/adai_mari.py`; CCEL ANF Vol. 7 English translation; ANF07 cache shared with `syriac_james`; public domain; oldest complete surviving anaphora, c.2nd–4th c., foundational to East Syriac and pre-Portuguese Thomas Christian tradition)
- [x] Divine Liturgy of St. Mark — 375 chunks; `liturgical/mark-liturgy` (`scripts/ingest/mark_liturgy.py`; CCEL ANF Vol. 7 English translation; ANF07 cache shared; public domain; ancient Alexandrian eucharistic rite, ancestor of Coptic Liturgy of St. Cyril; c.3rd–5th c.)
- [x] Didache (Teaching of the Twelve Apostles) — 24 chunks; `patristic/didache` (`scripts/ingest/didache.py`; CCEL ANF Vol. 7; public domain; supersedes anonymous `anf07/008.json` with correct metadata; c.50–120 CE; genre `patristic`, tradition `greek`)
- [x] Apostolic Constitutions (all 8 books) — 401 chunks; `patristic/apostolic-constitutions` (`scripts/ingest/apostolic_constitutions.py`; CCEL ANF Vol. 7; public domain; supersedes anonymous `anf07/009.json`; book-level refs ApostConst.I–VIII; Book VIII contains the Clementine Liturgy, the most complete early Greek anaphora; c.375–400 CE)

### Milestone 6: Tier 3 Sources (sessions 13–14)
- [ ] Typikon date-filtered ingestion (see §6 for post-schism saint filtering design)
- [ ] Hudra.day Syriac liturgical scrape (see §6 for post-schism saint filtering design)
- [ ] Anaphora of Serapion of Thmuis (c.350 CE) — Wordsworth 1899 English translation; Internet Archive; public domain; Egyptian bishop, colleague of Athanasius; important for early Egyptian eucharistic theology
- [ ] Armenian Divine Liturgy / Badarak — English translation from Internet Archive public domain edition; `liturgical/armenian-liturgy`; lang `eng`, tradition `armenian`
- [ ] Tertullian.org corpus scrape
- [ ] https://www.newadvent.org/fathers/ document scrape (only where original-language sources have not been found)

### Milestone 7: QC & Handoff (session 15)
- [ ] Full validation pass
- [ ] Translation linkage for all Scripture
- [ ] **CCEL translation linkage**: populate `translation_of` on all CCEL ANF/NPNF1/NPNF2 works by matching author abbreviation + work structure against First1KGreek/PTA/Perseus originals (currently all `null`)
- [ ] Chunk count report by language/genre/tradition
- [ ] **Resolve OGLT PL anonymous works**: apply Migne PL column-to-work mapping to populate `author`/`title` for the ~502 `oglt_pl/unknown/*` files (see Known Gaps). All citations shown to users must have an author and title.
- [ ] **OPG Greek dictionary filter**: score each `patristic/ogpg` paragraph by the fraction of Greek tokens that appear in a standard Greek lexicon (Perseus Morpheus wordlist or TLG headword list). Drop or flag paragraphs below a tuned threshold (~40% real words). This catches garbled OCR that slips past the current function-word filter — especially the mixed Latin/Greek column-boundary artifacts and combined-diacritic noise strings. Implement as a post-processing pass over the normalized chunks, not a change to the ingestor.
- [ ] **OPG cross-scan voting** *(follow-on to dictionary filter)*: each PG volume has 5–9 independent scans in the OGL repos (hvd, coo, mdp, njp, etc.); we currently use one. For paragraphs that score below the dictionary threshold in the primary scan, fetch the same page range from a secondary scan and substitute if it scores higher. Requires aligning page numbers across scans.
- [ ] **ANF08/009 Syriac documents — dedicated ingestors**: the "Memoirs of Edessa" blob (`patristic/ccel-anf/anf08/009.json`, 1485 paragraphs) contains several distinct works currently ingested as one anonymous blob. Create dedicated ingestors for each, all from the already-cached `anf08.xml`, following the same pattern as `didache.py` and `apostolic_constitutions.py`:
  - **Teaching of Addai (Doctrina Addai)** — §CCELANF089.6; foundational Syriac text on the Christianization of Edessa; c.3rd–5th c.; `patristic/teaching-of-addai`; author=None, tradition=`syriac`
  - **Bardesan, Book of the Laws of Divers Countries** — §CCELANF089.16; Bardesan of Edessa (154–222 CE), earliest major Syriac theologian/philosopher; `patristic/bardesan`; author="Bardesan of Edessa", tradition=`syriac`
  - **Teaching of the Apostles** (Syriac) — §CCELANF089.7; Syriac church-order document related to the Didache tradition; early; `patristic/teaching-of-apostles-syriac`; author=None, tradition=`syriac`
  - **Jacob of Serugh, Hymns on Edessa** — §CCELANF089.4 + §CCELANF089.14; Jacob of Serugh (d.521), pre-schism East Syriac poet; genre `patristic`; author="Jacob of Serugh", tradition=`syriac`
  - **Acts of Sharbil** — §CCELANF089.9; Edessene martyrdom account, c.3rd c.; `patristic/acts-of-sharbil`; tradition=`syriac`
  - **Martyrdom of Habib the Deacon** — §CCELANF089.11; early Syrian martyrdom; `patristic/martyrdom-of-habib`; tradition=`syriac`
  - **Moses of Khoren, History of Armenia** — §CCELANF089.13; Moses of Khoren (c.5th c.), foundational Armenian historian; `patristic/moses-of-khoren`; author="Moses of Khoren", tradition=`armenian`
- [ ] **ANF full QA pass — identify remaining extractable works**: audit all 10 ANF volumes (`anf01`–`anf10`) for div1/div2 sections currently ingested as anonymous blobs in `patristic/ccel-anf/` that could be extracted into dedicated ingestors with proper author, title, and date metadata. Priority: any work with a known author, a distinct canonical identity, or liturgical/conciliar genre that is misclassified as generic patristic. Cross-reference against First1KGreek, PTA, and Perseus to avoid duplicating works already present in original-language form.
- [ ] Hand normalized JSON to Phase 2 (database construction)

---

## 11. Known Gaps & Risks

| Gap | Mitigation |
|-----|-----------|
| No clean Ge'ez digital text; PDFs only | OCR with Ge'ez Tesseract model; flag low-confidence passages |
| SEDRA Peshitta is JS-native; no Python parser | Use Node.js subprocess or port the sedrajs data layer to Python |
| Typikon/Hudra post-schism saint filtering requires scholarly judgment | Ingest all content; apply `post_schism` flags in a second pass via `scripts/flag_liturgical.py` using `data/post_schism_feasts.csv` (see §6 for full design). Default is inclusion when uncertain. |
| TLG/Patrologia Orientalis behind paywall | Defer; note gaps in validation report; seek institutional access |
| Migne PG OCR quality highly variable | Use Open PG GitHub (already OCR'd); supplement with PTA where critical editions exist |
| OGLT PL: 502/1459 split-dir files have no author or title metadata | The OGLT project left those volumes' metadata unpopulated. **Phase 2/3 TODO**: cross-reference Migne PL column numbers against a reference index (e.g. Corpus Thomisticum, Clavis Patrum Latinorum, or a community-maintained PL column map) to supply `author` and `title` for all `oglt_pl/unknown/*` works. Required before citations can be shown to users. |
| Gallican/Mozarabic liturgy sources are 19th-century editions (may contain editorial additions) | Document edition metadata; flag as `edition_date: 1855` etc. |
| `WEB.csv` does not exist in scrollmapper/bible_databases | Use eBible.org USFM (`engwebp_usfm.zip`) — already implemented |
| SBLGNT is NOT OSIS XML — uses Logos custom format | Custom parser implemented in `sblgnt.py`; `parse_osis` will not work for it |
| LXX Rahlfs (eliranwong repo) has CCAT user-declaration requirement | Non-commercial only; word CSV is 3-column, verse index is start-only — see `lxx_rahlfs.py` |
| ASV from scrollmapper is only 48/66 books | Some NT books appear to be missing from the scrollmapper ASV CSV; investigate before M7 QC |
| `beta2unicode` package does not exist on PyPI | Betacode conversion for any CCAT-sourced text (Tier 2) needs a custom solution at ingest time |
| CCEL ANF/NPNF `translation_of` is null for all 343 works | English translations not yet linked to Greek/Latin originals. M7 TODO: match by author abbreviation + canonical ref structure against First1KGreek/PTA/Perseus. |
| Perseus Latin repo contains `.tracking.json` files from the CTS system | Repos stored under `data/raw/_repos/` (not `data/raw/patristic/`) to prevent catalog and normalize.py from treating them as source files. Do not move repos back into `patristic/`. |
| Clementine Vulgate eBible ID is `latVUC` not `latclv` | Corrected; `latVUC_usfm.zip` is the working URL |
| Wulfila books B19–B21 (Skeireins, legal docs, calendar) skipped | Non-canonical; if needed, add mappings to `_BOOK_ID_TO_OSIS` in `wulfila.py` |
| www.goarch.org returns 403 for automated requests | Resolved: ingestors retargeted to `dcs.goarch.org` (GOA Digital Chant Stand) which serves static HTML without bot-blocking. |
| Coptic Scriptorium uses two XML formats | Standard TEI P5 for most corpora; custom `<meta>` root with `<norm_group>` word elements for some (besa-letters, shenoute-eagerness, life-aphou, etc.). Both handled by `coptic_scriptorium.py`. |

---

## 12. Future: Custom OCR Pipeline (Post-Phase 1, if needed)

If the M7 dictionary filter + cross-scan voting strategy does not bring OPG quality to an acceptable level for search, a custom OCR pipeline is the next escalation. Gate this decision on measured search quality after Phase 3 is running.

**What it would address:** The root cause of most OPG noise is that the OGL project ran Tesseract on full-page images without separating the Greek and Latin columns first. Better character recognition alone is not sufficient — the column layout problem must be solved first.

**Approach:**
1. **Source images**: The OGL repo identifiers (`hvd.32044054121090`, `coo.31924054872803`, etc.) are Internet Archive item IDs. Full-resolution TIFFs are freely downloadable via the IA S3 API (~200–400 GB per volume; selective download of individual volumes is feasible).
2. **Column segmentation**: Detect the vertical divider between Greek and Latin columns using a layout analysis model (LayoutParser, PaddleOCR layout, or a simple projection-profile heuristic on the binarized image). Crop to the Greek column before passing to OCR. This step alone would eliminate the interleaved-column artifacts that are the largest noise source.
3. **OCR engine**: Kraken or Calamari (both designed for historical printed text) with a model fine-tuned on polytonic Greek. The OGL project's custom Tesseract 3 model (`migne*.pyrnn.gz`) could serve as training data ground-truth for bootstrapping a Kraken model. Alternatively, check whether the OCR-D or EFES projects have published Migne-specific Kraken models.
4. **Scale**: ~600 pages/volume × 161 volumes ≈ 97,000 page images. At ~2–5 s/page on a single GPU, this is a few hours of compute once the pipeline is built; the data prep (IA download + segmentation) is the larger investment.

**Decision criteria**: Pursue this path if post-M7 search evaluation shows that OPG result quality is materially worse than PTA/First1KGreek results for the same authors (e.g., Origen, Chrysostom, Athanasius), and the dictionary filter has not closed that gap.
