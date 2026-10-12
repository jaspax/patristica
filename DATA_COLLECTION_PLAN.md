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
| `liturgical/coptic-scriptorium` | Coptic Scriptorium: Shenoute, Besa, homilies, saints' lives, monastic texts, apocrypha (genre `patristic`; no liturgies, despite the historical id prefix) | Coptic (`cop`) | github.com/CopticScriptorium/corpora | CoNLL-U / TEI | CC-BY |

#### 3.3 Liturgical Texts

| ID | Text | Language | Source | Format | License |
|----|------|----------|--------|--------|---------|
| `liturgical/cantus` | CANTUS Latin Chant Database | Latin (`lat`) | cantusdatabase.org (API) | JSON (API) | Free |
| `liturgical/cursus` | CURSUS Medieval Liturgical Texts | Latin (`lat`) | zenodo.org/records/5090613 | TEI P4 XML | Academic |

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
| `liturgical/typikon` | Greek Typikon (selected first-millennium sections) | Greek (`grc`) | Violakis 1900 ed. via archive.org/details/typikontstou00orth | OCR plain text; date filtering required via flag_liturgical.py second pass |
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

### Duplicated section numbers

Many editions print the paragraph number at the start of the paragraph (`3 Αὐτοκράτορι…` in First1KGreek, `1. Great art Thou…` in NPNF, `α. Πᾶσαι…` in PTA, `[3] …` in ANF), and the ref already carries it. `normalize.py` strips such a prefix from non-scripture chunks, only when its value equals the ref's last segment (`patristica/section_numbers.py`, [#30](https://github.com/jaspax/patristica/issues/30)). It handles Arabic digits (bare, `3.`, `3)`, `[3]`, `(3)`), Greek numerals with a keraia or dot (Greek text only), and Roman numerals followed by `.` or `)`. Raw files keep the number. A bare number followed by a numbered book (`1 Cor.`, `1 Timothy`) or by `bis` or a Roman calendar word (`8 kal.`) is content and stays. `patristic/ogpg` is skipped because its refs are serial counters, so a match there is coincidence. Not handled: printed numbers that differ from the ref, such as continuous paragraph numbering against chapter.section refs. They can't be told apart from content. `validate.py` warns (`text_starts_with_section_number`) about any chunk that still starts with its ref's number.

### Translation linking

After all chunks are normalized, `scripts/link_translations.py` creates `translation_group_id` values by aligning chunks with the same canonical reference across languages. For Scripture this is deterministic (verse IDs). For Patristics it requires a section-level alignment heuristic or manual mapping table.

---

## 6. Date Filtering for Hybrid Texts

Some sources (especially liturgical) contain material from a wide date range. Handle as follows:

- **Typikon** and **Hudra**: Ingest all content in the primary pass; apply `out_of_period` flags in a dedicated second pass (see below). The ingestors should preserve feast-section headings as structured metadata (not just inline text) so the second pass can operate at section granularity without re-parsing.
- **Beth Gazo / Hudra**: Include sections attributable to first-millennium hymnographers (Ephrem the Syrian d.373, Narsai d.502, etc.). Flag uncertain-date sections with `date_confidence: "uncertain"`.
- **Sarum Use**: Post-dates the period; include only demonstrably first-millennium liturgical elements.
- **CANTUS chants**: Filter by `century` metadata field where available; include chants attributed to Gregory I (d.604) and earlier, flag later attributions.

All chunks carry:
```python
date_composed: int | None      # best estimate (CE)
date_range: tuple[int,int] | None
date_confidence: str           # "established" | "approximate" | "uncertain"
out_of_period: bool            # True if dated after the collection period (patristica/period.py)
```

### Out-of-period saint filtering — second pass design

The Typikon and Hudra both organize content around feast days, some of which commemorate saints who lived after the collection period. The hymnography composed for these feasts (troparia, kontakia, canons) is out of period even though it appears in the same book as genuinely ancient material. This cannot be reliably resolved at ingestion time without a pre-compiled saint-date lookup table.

**Approach:** Ingest everything in the primary pass with `out_of_period=False` as the default. Run `scripts/flag_liturgical.py` as a separate step after primary ingestion is complete.

**Implementation notes for `scripts/flag_liturgical.py`:**
- Maintain `data/out_of_period_feasts.csv` with columns `tradition`, `feast_name` (normalized), `saint_name`, `saint_floruit`, `notes`. This file is the authoritative source and should be reviewed manually before each pipeline run.
- The ingestors must expose the feast section heading in each chunk's `canonical_ref` or in a sidecar metadata field so the flagging script can do a direct lookup without re-parsing the source XML/text.
- Apply `out_of_period=True` to all chunks whose containing feast section matches an entry in the lookup table. Propagate the flag to the entire section (heading + all following hymnographic chunks) rather than individual chunks.
- For feast sections **not** in the lookup table, leave `out_of_period=False` and `date_confidence="uncertain"`. The default-include policy means marginal or disputed feasts are included until there is positive evidence that the commemorated saint and the hymnography post-date the period.
- **Reference sources for building the lookup table:**
  - Greek: *Synaxarion of Constantinople* (Hieromonk Makarios of Simonos Petra, Ormylia 1998–2005) gives feast-by-feast origin dates for the Byzantine calendar.
  - East Syriac: *The Martyrology and Hagiology of the Church of the East* (Fiey, CSCO 1963) and the Hudra critical editions by Sauget and Jammo.
- The flagging script is idempotent: re-running it with an updated `out_of_period_feasts.csv` corrects previously set flags.

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

> **Frozen (Phase 1 complete, 2026-10-10).** This checklist is the historical record of Phase 1. New and outstanding work is tracked in [GitHub issues](https://github.com/jaspax/patristica/issues); do not add items here.

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
- [x] First1KGreek + OGLT Patrologia Latina  (`scripts/ingest/first1k.py` 220 works grc after scope filter — see below; `scripts/ingest/oglt_pl.py` 1453 works lat; CC-BY-SA 4.0)
- [x] Perseus canonical Greek/Latin  (`scripts/ingest/perseus.py`; git clone canonical-greekLit + canonical-latinLit; repos stored under `data/raw/_repos/` to avoid catalog pollution; dedup against First1KGreek by CTS work ID; same author-allowlist scope filter as First1KGreek; `XMLParser(no_network=True)` required — Latin files reference remote Perseus DTDs; 50 works: 11 grc + 39 lat; CC-BY-SA 4.0)
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
- [x] Typikon date-filtered ingestion (see §6 for out-of-period saint filtering design) — `scripts/ingest/typikon.py`; Violakis 1900 OCR from Internet Archive; 3806 paragraphs in 14 sections (General + 12 months + Mov); flag_liturgical.py second pass deferred
- [x] Hudra.day Syriac liturgical scrape — `scripts/ingest/hudra.py`; Firestore REST API with web API key (publicly readable `books` + `pages` top-level collections; no playwright needed at runtime, only used for discovery); 2 works: Hudra ACE 1960 (18/126 pages transcribed, refs `EastSyrLit.Hudra.*`, syc, digitization in progress) + Taksa d'Raze 2003 (51/55 pages, refs `EastSyrLit.Taksa.*`, syc); date_range (600, 1000) and (200, 700) respectively; license `unknown` (community transcription of copyrighted print editions)
- [x] Anaphora of Serapion of Thmuis (c.350 CE) — 426 paragraphs; `liturgical/serapion` (`scripts/ingest/serapion.py`); Wordsworth 1899 English translation from IA (`bishopsarapionsp06sera`); public domain; Egyptian bishop, colleague of Athanasius; 30 prayers incl. eucharistic anaphora, baptismal, ordination, blessing of oils, pro-anaphoral prayers; lang `eng`, tradition `coptic`
- [x] Armenian Divine Liturgy / Badarak — 641 paragraphs; `liturgical/armenian-liturgy` (`scripts/ingest/armenian_liturgy.py`); Issaverdens 1873 English translation from IA (`ArmenianRitual0104`); public domain; Part I (Divine Liturgy) only; lang `eng`, tradition `armenian`; date_range (350, 500)

### Milestone 7: QC & Handoff (session 15)
- [x] Full validation pass — `scripts/validate.py` implemented with 10 check groups; report at `data/validation_report.json` (first run: 4,961 works · 1,588,182 chunks; current, after the First1K/Perseus scope fix on 2026-09-28: 3,233 works · 1,109,902 chunks · 0 errors)
  - [x] Schema integrity: all normalized files parse cleanly as JSON lists
  - [x] Text quality: no empty text; flags HTML artifacts, encoding failures, low-alpha chunks
  - [x] Language/script consistency: valid ISO 639-3 codes; verifies Unicode block coverage
  - [x] Canonical reference integrity: format check per genre; within-work dedup; sequential chunk_index
  - [x] ID uniqueness: no duplicate work_ids or chunk_ids globally
  - [x] Date plausibility: range check, out_of_period consistency
  - [x] Cross-reference integrity: orphan chunks, bad translation_of targets, singleton translation groups
  - [x] Metadata completeness: author presence, collection-name titles
  - [x] Scripture coverage: books present/missing per translation source
  - [x] Chunk count report by language/genre: 1,109,902 total — lat 395k, grc 330k, eng 230k, syc 39k, cop 36k, hye 36k, hbo 23k, gez 18k, got 4k; by genre patristic 657k, scripture 329k, liturgical 120k, councils 4k
  - [x] ~~Remaining errors~~ — all resolved: `text_has_html_tags` downgraded to a warning (2,247 remaining, mostly CANTUS/OCR; was 25,741); duplicate refs/chunk IDs fixed via shared `_common.dedupe_refs` + Armenian versification rules
  - **Open warnings** (informational; tracked as items below where actionable):
    - 1,599 works without `author` (expected for liturgical/council; OGLT PL and CCEL addressed below)
    - 177 works with collection-name titles (CCEL ANF/NPNF + OGPG) — addressed by title/author audit below
    - 2,247 chunks with HTML-like tags — mostly CANTUS rubric fields and OCR artifacts
- [x] **scrollmapper book-name mapping** — the CSVs use roman numerals ("I Samuel", "III John") and "Revelation of John"; new `_scripture_meta.book_abbrev()` accepts roman prefixes, plus missing LXX-extra names/titles/dates (incl. new `PrAzar`). Unknown names now warn once. ASV 48 → 66 books; Coptic 48 → 68
- [x] **Kebra Nagast** — excluded in `gez.py` (`_EXCLUDED_BOOKS`; composed c.1200–1325). Root cause of the bad flag fixed too: `normalize_scripture_work` hardcoded the date flag (now `out_of_period`) to False; it now derives it from dates. The Ethiopic Synaxarion (1 chunk, 14th-c. recension, liturgical) is kept as a hybrid text and is the one remaining `period_flag_mismatch` warning
- [x] **`data/chunks/` first run + Scripture translation linkage** — 3,233 files · 1,109,902 chunks · 1.5 GB (gitignored; ~3.5 min, 177 MB RSS). `chunk.py` now rebuilds outputs older than their normalized source and prunes orphans; `link_translations.py` links `scripture/` only, resets singletons to `None`, and rewrites only changed files (~9 s). 317,884 / 329,211 scripture chunks grouped. Second run of both is a no-op.
- [x] **Versification-aware Scripture linking** — `patristica/versification.py` maps each source's native ref onto "org" versification (BHS / Nestle-Aland) using the Copenhagen Alliance / Paratext standard mappings (vendored in `patristica/data/versification/`, CC BY-SA 4.0); `translation_group_id` is the mapped ref, `canonical_ref` stays native. Scheme per source (`SOURCE_SCHEMES`) sniffed from per-chapter verse counts; per-book exceptions (`BOOK_SCHEME_OVERRIDES`) chosen by correlating verse lengths with the OSHB/SBLGNT verse each ref maps to. Psalms length-correlation vs the Hebrew went from 0.15–0.48 to 0.75–0.82 for every LXX/Vulgate/English-numbered source; overall correlation improved or held for every source. Also fixed along the way: Armenian Daniel/Esther chapters were numbered by fetch position (Daniel off by one chapter throughout), and Armenian Esther 13:8–18 (`13_1:N` labels) had been silently dropped. 321,444 / 329,222 scripture chunks grouped
- [x] **Resolve OGLT PL anonymous works** — all 502 split files lacking TEI author/title attributed via `scripts/ingest/data/oglt_pl_index.csv` (stem → author, title, floruit dates, basis). Built by text-matching split files against the repo's own CTS catalog (`data/*/__cts__.xml`, CC-BY-SA 4.0; 469/502 matched), the other 33 from in-text headings, then hand-curated (Latin author names, floruit dates, pseudepigrapha, misattributions). 420 kept (48 honestly "Anonymus"/"Varii"); 82 excluded by the collection-period filter: 73 early-modern editorial apparatus and 9 later works/forgeries (Pseudo-Dexter, Pseudo-Maximus, Pseudo-Liutprand, Letbert's psalm commentary, Goscelin). 0 `oglt_pl/unknown/*` works remain
- [x] **ANF08/009 Syriac documents** → `scripts/ingest/syriac_documents.py` (`patristic/syriac-documents`), table-driven carve of ANF08 div1 `ix` (Pratten after Cureton) into 17 works / 1,361 paragraphs: Eusebius HE 1.13 (Syriac Abgar story), Doctrina Addai, Teaching of the Apostles, Teaching of Simon Cephas, Acts of Sharbil, Martyrdom of Barsamya, Martyrdom of Habib, Metaphrastes' Shamuna/Guria/Habib, Moses of Khoren extract, Bardaisan *Laws of Countries*, Letter of Mara bar Serapion, "Ambrose" Memorial (= Syriac Ps.-Justin *Oratio ad Graecos*), Abgar/Addai extracts, Jacob of Serugh ×4. Editorial div2s excluded
- [x] **ANF full QA pass** — the generic author heuristic had left nearly all of ANF03–09 anonymous and lumped several authors into some div1s. New table-driven `scripts/ingest/anf_works.py` (`patristic/anf-works`) carves out 200 works (≈19.9k paragraphs) with author, date, tradition and genre: per-treatise Tertullian/Cyprian, 32 NT apocrypha, pseudepigrapha split from genuine authors, 3 council-genre texts (7th Council of Carthage, Synod of Antioch 268, Nicene Creed). Two pieces from after the period (Balsamon/Zonaras commentary on Peter of Alexandria's canons; Vignier's forged Theonas letter) are skipped. Title pages, indexes, ANF10 (page images only) and the ANF09 Gospel-of-Peter synoptic table excluded as non-text. ccel-anf drops from 94 to 69 works, mostly editorial matter
- [x] **CCEL de-duplication** — dedicated ingestors (Didache, Apostolic Constitutions, ANF07 liturgies, ecumenical councils, and now `syriac_documents`/`anf_works`) used to "supersede" sections that `ccel_anf`/`ccel_npnf2` kept ingesting too, so those texts were in the corpus twice. `_ccel_common.EXCLUDED_DIVS` now registers every carved-out or non-text div; `ingest_ccel_series` writes only changed files and prunes outputs no longer produced; `normalize.py` rebuilds stale outputs and prunes orphans (only inside sources whose raw dir exists)
- [x] **Decision: ANF editorial notices** — excluded (user decision 2026-10-10). All 19th-c. editorial apparatus in ANF and NPNF (prefaces, introductory notices/essays, prolegomena, elucidations, translators' notes, excursuses; ANF 134 divs ≈2,140 paragraphs, NPNF ≈210 divs) plus title pages, contents and indexes are registered as `non-text` in `EXCLUDED_DIVS`; authorial prefaces kept
- [x] **CCEL translation linkage** — `Work.translation_of` set on 167 CCEL works (anf-works 89/232, npnf-works 78/233; syriac-documents 0/17 — no originals in corpus). Targets: 59 First1KGreek, 65 OGLT PL, 33 Perseus, 9 PTA. Hand-reviewed `_ORIGINALS` tables in `anf_works.py`/`npnf_works.py`; partial correspondences point to the best single original; ~20 ambiguous cases left null with reasons in `_UNLINKED`. A test checks every target exists and none points to OGPG volume blobs
- [x] **Title/author extraction audit** — no work is titled by its collection any more (`collection_name_as_title` 177 → 0); collection identity lives only in `Work.edition`:
  - CCEL (ANF, NPNF1, NPNF2): generic per-div1 ingestors now emit nothing; all text is carved by table-driven `anf_works.py` (232 works) and `npnf_works.py` (233), sharing `_ccel_works.py`, plus `syriac_documents.py` (17). Pseudepigrapha split from genuine authors, misfiled documents re-attributed, each treatise/oration its own work, council-genre texts tagged. A test checks the generic parsers leave nothing behind
  - OGPG: `_ogpg_volumes.py` maps PG 1–161 to authors/date ranges (Wikipedia/Cavallera; ~40 volumes confirmed by text overlap with First1K/PTA); titles "Works in PG Vol. N (Author, …)". Splitting individual works within a volume remains open
  - OGLT PL: every kept work has an index-backed author and work-specific title (see below)
- [x] **OPG Greek dictionary filter** — 168k accent-insensitive Greek word forms built from our own clean First1K/PTA/Perseus/SBLGNT/PTA-LXX text (`_greek_lexicon.py`, cached `scripts/ingest/data/greek_wordforms.tsv.gz`; Rahlfs excluded for licence). Score = attested words ÷ all words; threshold 0.65 (hand-labelled samples: below it ~80% is garbage/apparatus; 0.40 would remove < 1%). Applied in `ogpg.py` at the raw stage with pipeline-versioned outputs. Also fixed: 24 volumes held 2–3 interleaved copies of their text, and 10 mislabeled/duplicate repos (4 were PL scans) are excluded
- [x] **OPG cross-scan voting** — all scans per volume fetched (+1.2 GB). Best-scoring scan becomes primary (changed for 138 volumes); failing paragraphs replaced by another scan's passing paragraph matched by position/trigrams/length (2,533 of 8,912 rescued). PG 50 text ×7.4, PG 16.1/16.2 ×2.2–2.5. Volumes composed entirely after the period (PG 121+, 41 volumes) excluded like every other source; 5 straddling volumes (PG 3, 4, 97, 119, 120) kept and flagged by date. Not done: Lace hOCR output
- [x] **OGLT PL header-attributed works** — `oglt_pl_index.csv` now has a row for all 1,453 split files (TEI headers carried volume-level metadata: 897/951 shared an author/title pair, ~300 had the wrong author). 1,167 kept works, each with a work-specific title, checked author and no duplicate (author, title) pairs. Excluded 133 editorial-apparatus files and 28 works from after the period (Martin V, Samuel of Ani, Gilbert of Poitiers, Hugh of St Victor, late-medieval Pseudo-Augustine, …). Open: 5 hybrid files mix ancient and later material (PL8_4, PL66_7, PL72_14, PL79_1, PL85_2); 211 kept works undated
- [x] **PL28–29 Divina Bibliotheca** — biblical text (42 files) dropped via `basis=scripture` (duplicates the Clementine Vulgate); 22 of Jerome's prefaces/prologues kept as patristic works via `keep_refs`
- [x] Hand normalized JSON to Phase 2 — see **Phase 2 Handoff** below


### Phase 2 Handoff (2026-10-10)

Final Phase 1 state: **3,072 works · 971,656 chunks · 39 sources · validation PASS (0 errors)**. Chunks by language: lat 340k, grc 276k, eng 195k, cop 41k, syc 39k, hye 36k, hbo 23k, gez 18k, got 4k. By genre: patristic 507k, scripture 341k, liturgical 120k, council 4k.

**Data contract**

| Path | Tracked | Contents |
|---|---|---|
| `data/normalized/{genre}/{source}/…/*.json` | yes | One file per work: a JSON list of `Chunk` records (`patristica/models.py`) — `chunk_id` (globally unique), `work_id`, `canonical_ref` (source-native numbering), `language`, `text`, `chunk_index` (0-based, sequential), dates, `out_of_period`. Context and translation groups are *not* filled here |
| `data/normalized/_works.jsonl` | yes | One line per normalized file: `{"path": …, "work": {…}}` with the full `Work` record (title, author, dates, genre, language, tradition, license, provenance_url, edition, translation_of). The only tracked copy of work metadata (`data/raw` is gitignored); maintained by `scripts.normalize` |
| `data/normalized/_index.json` | yes | Lookup index for `patristica/lookup.py` (ref prefix → works) |
| `data/chunks/…` | no | Embedding-ready chunks: normalized chunks plus `context_before`/`context_after` (~50 tokens) and `translation_group_id` (Scripture only, versification-mapped). Regenerate with `uv run python -m scripts.chunk && uv run python -m scripts.link_translations` (~4 min) |

**For the Phase 2 loader**
- Load works from `_works.jsonl`, chunks from `data/chunks/` (regenerate first). Every pipeline step is idempotent and incremental.
- `authors` table: `Work.author` is a free-text string (Latin forms for OGLT PL, English for CCEL; OGPG volumes may list several authors separated by `; `, with "et al."). Author normalization/deduplication across sources is a Phase 2 task; `scripts/ingest/_patristic_meta.AUTHORS` has dates/traditions for the major Fathers.
- `translation_of` (Work level) links 167 CCEL English translations to their originals; `translation_group_id` (chunk level) links parallel Scripture verses only.
- `out_of_period` is per chunk (rule in `patristica/period.py`): works composed entirely after the period are excluded; hybrid/straddling works (Typikon, CANTUS, OGPG PG 3/4/97/119/120, a few OGLT PL files) are kept with date-derived flags — filter at query time.
- Licences vary per work (`Work.license`): most are public domain or CC-BY(-SA); LXX Rahlfs (eliranwong) and the PTA Peshitta OT are non-commercial.

**Open issues for the Phase 2 implementation** (chunk size normalization before embedding, [#2](https://github.com/jaspax/patristica/issues/2); embedding-model coverage of Coptic/Syriac/Armenian/Ge'ez/Gothic, [#3](https://github.com/jaspax/patristica/issues/3)) are described in `IMPLEMENTATION_PLAN.md` §2.5; licensing obligations for the public site in §3.5.

**Known caveats carried into Phase 2**: OGPG volumes are not split into individual works and remain noisier than PTA/First1K for the same authors (see "Custom OCR pipeline" decision criteria); 879 works without author (mostly liturgical, council, anonymous apocrypha — honest anonymity); 211 OGLT PL works undated; one deliberate `period_flag_mismatch` warning (Ethiopic Synaxarion, hybrid liturgical); remaining text-quality warnings are listed in `data/validation_report.json`.

---

## 11. Known Gaps & Risks

| Gap | Mitigation |
|-----|-----------|
| No clean Ge'ez digital text; PDFs only | OCR with Ge'ez Tesseract model; flag low-confidence passages |
| SEDRA Peshitta is JS-native; no Python parser | Use Node.js subprocess or port the sedrajs data layer to Python |
| Typikon/Hudra out-of-period saint filtering requires scholarly judgment | Ingest all content; apply `out_of_period` flags in a second pass via `scripts/flag_liturgical.py` using `data/out_of_period_feasts.csv` (see §6 for full design). Default is inclusion when uncertain. |
| TLG and modern *Patrologia Orientalis* volumes behind paywall | Defer; seek institutional access. Note: PO volumes from 1904 to c.1930 (roughly PO 1–22) are public domain and scanned on archive.org, but need OCR (bilingual pages, Oriental scripts) — see §12 "Broader Non-Chalcedonian coverage" |
| Migne PG OCR quality highly variable | Use Open PG GitHub (already OCR'd); supplement with PTA where critical editions exist |
| OGLT PL attribution | The 502 anonymous split files are resolved via `scripts/ingest/data/oglt_pl_index.csv`. Remaining: header-attributed works carry volume-level (often wrong) author/title — M8 item; a few kept works are hybrids (PL8_4 Donation of Constantine + Armenian Letter of Concord; PL66_7 with an Alberic of Monte Cassino sermon; PL66_1 Rule with Martène commentary) that cannot be split per chunk |
| CCEL/OGPG `Work.title` is set to collection/volume name, not individual work title | Currently `Work.title = "ANTE-NICENE FATHERS"` or `"Patrologia Graeca Vol. 1"` for most works in these collections. Tracked in [#10](https://github.com/jaspax/patristica/issues/10): replace with the actual work title; move collection identity to `Work.edition`. Until fixed, the lookup tool and any Phase 3 UI will surface collection names instead of work titles as the primary label. |
| Gallican/Mozarabic liturgy sources are 19th-century editions (may contain editorial additions) | Document edition metadata; flag as `edition_date: 1855` etc. |
| `WEB.csv` does not exist in scrollmapper/bible_databases | Use eBible.org USFM (`engwebp_usfm.zip`) — already implemented |
| SBLGNT is NOT OSIS XML — uses Logos custom format | Custom parser implemented in `sblgnt.py`; `parse_osis` will not work for it |
| LXX Rahlfs (eliranwong repo) has CCAT user-declaration requirement | Non-commercial only; word CSV is 3-column, verse index is start-only — see `lxx_rahlfs.py` |
| ASV from scrollmapper is only 48/66 books | Resolved: `data/raw/scripture/asv/` now has all 66 books |
| `beta2unicode` package does not exist on PyPI | Betacode conversion for any CCAT-sourced text (Tier 2) needs a custom solution at ingest time |
| CCEL ANF/NPNF `translation_of` is null for all 343 works | English translations not yet linked to Greek/Latin originals. Tracked in [#11](https://github.com/jaspax/patristica/issues/11): match by author abbreviation + canonical ref structure against First1KGreek/PTA/Perseus. |
| First1KGreek/Perseus TEI headers have no composition dates; both repos are mostly classical pagan literature | The −50 CE / late-date filters never fired (every work was `uncertain`), so ~1,700 classical works (Plutarch, Galen, Cicero, …), works after the period (Anna Comnena, Zonaras) and French/German translations tagged `grc` were ingested. Fixed by an author-ID allowlist in `scripts/ingest/_cts_scope.py` (Christian/Jewish first-millennium literature, plus Procopius) and strict edition-suffix language matching; ingestors prune previously written out-of-scope files. NT (`tlg0031`) and LXX (`tlg0527`) excluded as covered by scripture ingestors. Pagan authors writing about Christians (Julian, etc.) are a possible future expansion. |
| arak29.org (Armenian) restarts verse numbering mid-chapter and has label typos | Mapped onto LXX versification via `_RESTART_RULES` in `armenian.py` (Ps 9 / 113 continue numbering, Ps 151 split out of the Ps 150 page, Prov 24:22a–e, Armenian-only Song 8:15–20); Exod 39 label typo fixed via `_LABEL_TYPOS`; Sirach's scrambled partial verses get letter suffixes (`Sir.16.13b`). Ref dedup across First1K/Perseus/PTA/OGLT PL now uses the shared `_common.dedupe_refs`. |
| Perseus Latin repo contains `.tracking.json` files from the CTS system | Repos stored under `data/raw/_repos/` (not `data/raw/patristic/`) to prevent catalog and normalize.py from treating them as source files. Do not move repos back into `patristic/`. |
| Clementine Vulgate eBible ID is `latVUC` not `latclv` | Corrected; `latVUC_usfm.zip` is the working URL |
| Wulfila books B19–B21 (Skeireins, legal docs, calendar) skipped | Non-canonical; if needed, add mappings to `_BOOK_ID_TO_OSIS` in `wulfila.py` |
| www.goarch.org returns 403 for automated requests | Resolved: ingestors retargeted to `dcs.goarch.org` (GOA Digital Chant Stand) which serves static HTML without bot-blocking. |
| Coptic Scriptorium uses two XML formats | Standard TEI P5 for most corpora; custom `<meta>` root with `<norm_group>` word elements for some (besa-letters, shenoute-eagerness, life-aphou, etc.). Both handled by `coptic_scriptorium.py`. |

---

## 12. Future Possibilities

### Broader Non-Chalcedonian coverage

Requires a research project. Some of this stuff has poor online visibility.
Consider doing OCR (see below) over Google Books where necessary.

- **Patrologia Orientalis (public-domain volumes)** — [#4](https://github.com/jaspax/patristica/issues/4). The modern volumes are subscription-only (Tier 4), but PO 1–22 (1904 to c.1930) are public domain on archive.org; needs OCR of bilingual pages. Covers the Coptic and Armenian synaxaria below, Severus of Antioch, John of Ephesus, the History of the Patriarchs of Alexandria, Ephrem and Jacob of Serugh.

### Additional Scrapes

- Tertullian per-work ingestors / tertullian.org scrape — [#8](https://github.com/jaspax/patristica/issues/8) (deferred from M6)
- newadvent.org Fathers scrape, only where no other source exists — [#9](https://github.com/jaspax/patristica/issues/9) (deferred from M6)

### Custom OCR Pipeline (Post-Phase 1, if needed)

If the M7 dictionary filter + cross-scan voting strategy does not bring OPG quality to an acceptable level for search, a custom OCR pipeline is the next escalation. Gate this decision on measured search quality after Phase 3 is running.

**What it would address:** The root cause of most OPG noise is that the OGL project ran Tesseract on full-page images without separating the Greek and Latin columns first. Better character recognition alone is not sufficient — the column layout problem must be solved first.

**Approach:**
1. **Source images**: The OGL repo identifiers (`hvd.32044054121090`, `coo.31924054872803`, etc.) are Internet Archive item IDs. Full-resolution TIFFs are freely downloadable via the IA S3 API (~200–400 GB per volume; selective download of individual volumes is feasible).
2. **Column segmentation**: Detect the vertical divider between Greek and Latin columns using a layout analysis model (LayoutParser, PaddleOCR layout, or a simple projection-profile heuristic on the binarized image). Crop to the Greek column before passing to OCR. This step alone would eliminate the interleaved-column artifacts that are the largest noise source.
3. **OCR engine**: Kraken or Calamari (both designed for historical printed text) with a model fine-tuned on polytonic Greek. The OGL project's custom Tesseract 3 model (`migne*.pyrnn.gz`) could serve as training data ground-truth for bootstrapping a Kraken model. Alternatively, check whether the OCR-D or EFES projects have published Migne-specific Kraken models.
4. **Scale**: ~600 pages/volume × 161 volumes ≈ 97,000 page images. At ~2–5 s/page on a single GPU, this is a few hours of compute once the pipeline is built; the data prep (IA download + segmentation) is the larger investment.

**Decision criteria**: Pursue this path if post-M7 search evaluation shows that OPG result quality is materially worse than PTA/First1KGreek results for the same authors (e.g., Origen, Chrysostom, Athanasius), and the dictionary filter has not closed that gap.

### Oriental Synaxaria
- **Ethiopic Synaxarion**: split by commemoration and apply the period rule per commemoration — [#5](https://github.com/jaspax/patristica/issues/5)
- **Armenian Synaxarion (Yaysmawurk')** — [#6](https://github.com/jaspax/patristica/issues/6)
- **Coptic Synaxarium (Arabic, Alexandrian recension)** — [#7](https://github.com/jaspax/patristica/issues/7)

