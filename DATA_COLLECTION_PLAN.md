# Patristica: Data Collection — Detailed Implementation Plan

## Overview

This document covers Phase 1 of the implementation plan: acquiring, normalizing, and preparing all source texts for database ingestion. Sources are organized by category, with each source assigned a priority tier based on data quality, licensing clarity, and ingestion complexity.

---

## 1. Project Structure

```
patristica/
├── data/
│   ├── raw/            # Downloaded/scraped source files, raw/{source_id}/… (git-lfs since #244)
│   ├── normalized/     # Normalized JSON records, normalized/{source_id}/…, one file per work
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
    work_id: str                  # "{source_id}/{local id}": "oshb/gen", "npnf-works/augustine-confessions"
    source_id: str                # bare collection slug: "oshb", "first1k" (no genre, #102)
    author: str | None            # the source's own spelling (provenance)
    author_ids: list[str]         # canonical ids from patristica/data/authors.csv (#82); [] if anonymous
    title: str
    date_composed: int | None     # best single estimate (CE), negative = BCE
    date_range: tuple[int, int] | None
    genre: str                    # "scripture", "patristic", "liturgical", "council", "apocrypha" (#103), "hagiography" (#558)
    language: str                 # ISO 639-3 code: "grc", "lat", "hbo", "syc", "cop", "gez", ...
    tradition: str | None         # "greek", "latin", "syriac", "ethiopic", "coptic", "armenian"
    license: str                  # "public_domain", "cc-by-4.0", "cc-by-nc-sa-4.0", etc.
    provenance_url: str | None
    translation_of: str | None    # work_id of the work this one was translated from (may chain; #11, #153)
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

The ID column is the `source_id`: the bare collection slug, which is also the source's directory under `data/raw/` and `data/normalized/`. Before #102 it carried a genre prefix (`scripture/oshb`); genre is now only a property of each work (`Work.genre`), and a source may mix genres.

### Tier 1 — Bulk download, structured format, clear license
These should be ingested first. Data is available as GitHub repos or structured archives.

#### 3.1 Scripture

| ID | Text | Language | Source | Format | License | Notes |
|----|------|----------|--------|--------|---------|-------|
| `oshb` | Open Scriptures Hebrew Bible | Hebrew (`hbo`) | github.com/openscriptures/morphhb | OSIS XML (word-level) | CC-BY 4.0 | ZIP: morphhb-master.zip; words inside `<w>` with lemma/morph; text reconstructed by joining `<w>` children |
| `sblgnt` | SBL Greek NT | Greek (`grc`) | github.com/LogosBible/SBLGNT | Custom Logos XML (NOT OSIS) | Non-commercial | ZIP: SBLGNT-master.zip; uses `<verse-number id="Book Ch:V">` + `<w>` + `<suffix>`; custom parser required |
| `nestle1904` | Nestle 1904 GNT | Greek (`grc`) | github.com/biblicalhumanities/Nestle1904 | USFM/XML | Public domain | Not yet ingested (M2 deferred) |
| `clementine` | Clementine Vulgate | Latin (`lat`) | ebible.org/Scriptures/ (`latVUC_usfm.zip`) | USFM | Public domain | 73 books incl. Deuterocanon; footnotes stripped via `_ebible_usfm` helper |
| `lxx-rahlfs` | Septuagint (Rahlfs 1935) | Greek (`grc`) | github.com/eliranwong/LXX-Rahlfs-1935 | Word-list CSV + verse-index CSV | CC-BY-NC-SA 4.0 | CCAT user declaration required; word list 3-col (`idx\tidx\tword`); verse index start-only; 33 books produced |
| `kjv` | King James Version | English (`eng`) | github.com/aruljohn/Bible-kjv | JSON per book (no spaces in filename: `1Samuel.json`) | Public domain | 66 books |
| `asv` | American Standard Version | English (`eng`) | github.com/scrollmapper/bible_databases (`ASV.csv`) | CSV (`Book,Chapter,Verse,Text`) | Public domain | 48 books (scrollmapper ASV lacks some books — see gap below) |
| `web` | World English Bible | English (`eng`) | ebible.org/Scriptures/ (`engwebp_usfm.zip`) | USFM | Public domain | `WEB.csv` does not exist in scrollmapper; use eBible USFM; Strong's annotations stripped |
| `brenton-eng` | Brenton's English Septuagint (1844; Apocrypha 1851) | English (`eng`) | ebible.org/Scriptures/ (`eng-Brenton_usfm.zip`) | USFM | Public domain | 52 books (#355): the LXX Old Testament with Ezra–Nehemiah as one book (`ezraneh`; eBible's `NEH` repeats it and is skipped), Theodotion's Daniel, Susanna and Bel, the Vaticanus Judges and the short Tobit (`translation_of` in `scripture_translation_of.csv`); no Psalms of Solomon or Odes. Lettered verses kept (`1Kgs.2.35a`); footnotes and cross-references kept at the end of their verse as `note` spans. LXX versification, the KJV-based Apocrypha (Tob, Jdt, Wis, Bar, EpJer, 1Esd) English; Prov 24–31 and Sir 30–36 are in the Greek manuscripts' order (#683) |
| `kjv-apocrypha-eng` | King James Version, 2 Esdras 3–14 (4 Ezra) | English (`eng`) | ebible.org/Scriptures/ (`eng-kjv_usfm.zip`) | USFM | Public domain | One work, `4esr` (#355): 4 Ezra from the Latin, in the group of the Syriac and Ge'ez 4 Ezra; chapters 1–2 and 15–16 (5 and 6 Ezra) left out; lacks 7:36–105, so its 7:36–70 are 7:106–140 of the Syriac |
| `coptic-nt` | Sahidic Coptic NT | Coptic (`cop`) | github.com/scrollmapper/bible_databases (`CopSahBible2.csv`) | CSV | Public domain | 50 files (includes some OT books from this CSV) |
| `wulfila` | Gothic Bible (Wulfila) | Gothic (`got`) | wulfila.be/gothic/text/gotica.xml | TEI P5 XML | Academic non-commercial | 18 books; identified by `xml:id="B1"–"B18"` with German headings; words in `<app><rdg><w>` |

#### 3.2 Patristic Texts

| ID | Collection | Language | Source | Format | License |
|----|-----------|----------|--------|--------|---------|
| `pta` | Patristic Text Archive | Greek (`grc`) | github.com/PatristicTextArchive | TEI P5 XML | per file from `<licence @target>` (#366): mostly CC-BY-SA 4.0, some CC-BY 4.0, one CC-BY-NC-SA 3.0 |
| `pta-eng` | Patristic Text Archive's own English translations (`<div type="translation">` files of the PTA clone, #345), linked to the PTA edition they render; enrolled for anchored derived verses. Other translations (Latin, German, Romanian) are skipped (#367) | English (`eng`) | github.com/PatristicTextArchive | TEI P5 XML | CC-BY / CC-BY-SA |
| `gutenberg-eng` | English translations from Project Gutenberg's HTML editions (#349, wave 3 of #341), cached at `data/raw/_cache/gutenberg-{N}/`, Gutenberg's header, footer and licence left out: Procopius, *Wars* I–VI.15 (Dewing, Loeb 1914–19, #16764/#16765/#20298) and *Secret History* (anonymous, Athenian Society 1896, #12916), linked to the Perseus Greek; *Barlaam and Ioasaph* (Woodward & Mattingly, Loeb 1914, #749), linked to the Perseus text (the Loeb Greek); John of Damascus, *On Holy Images* and three Dormition sermons (Allies 1898, #49917) and Prudentius, *Cathemerinon* (Pope 1905, verse, #14959), unlinked, since their originals are inside Migne containers. Hodgkin's condensed *Variae* (#18590) is an abstract, not a translation, and is left out | English (`eng`) | gutenberg.org | HTML | Public domain |
| `oglt-pl` | Open Patrologia Latina (OGLT) | Latin (`lat`) | github.com/OpenGreekAndLatin | TEI XML | Open Educational |
| `csel` | Corpus Scriptorum Ecclesiasticorum Latinorum (OGL csel-dev, #77): 270 works from the pre-1930 CSEL volumes (Augustine, Cyprian, Lactantius, Arnobius, Sulpicius Severus, Cassian, Ambrose, Hilary, …), one file per work. Kept beside OGLT PL as a separate witness; the stoa ids are Perseus's, so the two group by CTS id. Peter the Deacon's *De locis sanctis* (1137) is left out | Latin (`lat`) | github.com/OpenGreekAndLatin/csel-dev (`data/` only) | TEI EpiDoc (CTS) | CC-BY-SA 4.0 |
| `wikisource-canons` | Holy canons in Greek (Greek Wikisource, #22): the Apostolic Canons, the canons of Nicaea I, Constantinople I, Ephesus, Chalcedon, Trullo and Nicaea II, and of Ancyra, Neocaesarea, Gangra, Antioch, Laodicea, Sardica and Carthage. The text is Rhalles–Potles's (1852–59) by way of the nektar site; each page is pinned to its last revision before the September 2012 edits, which added the *Pedalion*'s prolegomena and commentary and changed some words of the canons. Not on Wikisource: Constantinople 394, Carthage under Cyprian, the Fathers' canons | Greek (`grc`) | el.wikisource.org (MediaWiki API, by revision id) | wikitext | CC-BY-SA 4.0 |
| `wikisource-apocrypha` | Greek apocrypha on Greek Wikisource (#78): the Apocalypse of Esdras (Tischendorf 1866), the Apocalypse of Sedrach (James 1893), the Testaments of the Twelve Patriarchs (Charles 1908); each page pinned to a revision; only pages that name their source | Greek (`grc`) | el.wikisource.org | wikitext | CC-BY-SA 4.0 |
| `ocp` | Online Critical Pseudepigrapha (#78): the Greek Apocalypse of Moses (Tischendorf 1866), pinned to a commit. Its other files are raw OCR, copied from Wikisource, or from editions in copyright, so they are left out | Greek (`grc`) | github.com/OnlineCriticalPseudepigrapha | OCP XML | CC-BY 4.0 |
| `dsc` | Digital Syriac Corpus (#79, #322): the whole corpus except the Peshitta NT (in `pta-peshitta`) and authors after the period (Dionysius bar Salibi, Bar Hebraeus, Timothy II). #79's 8 works are the `WORKS` table in `dsc.py` (Aphrahat, Addai, Syriac Eusebius HE, Mara, Hypomnemata, Ephrem's Nisibene and Nativity hymns, Bardaisan); the rest, 52 works grouped by DSC series (Narsai, Isaac of Nineveh, Jacob of Serugh, Philoxenus, Ishoʿyahb III, the Odes of Solomon, the Book of Steps, Nestorius, Titus of Bostra, the Syriac Clementines, the apocryphal Acts, chronicles, …), are rows of `scripts/ingest/data/dsc_works.csv`. Modern editions (Beck, Drijvers, …) are taken under DSC's CC BY (decision on #79). English translations, notes and apparatus inside the TEI are left out | Syriac (`syc`) | github.com/srophe/syriac-corpus (`data/tei` only) | TEI P5 | CC-BY 4.0 |
| `first1k` | First1KGreek | Greek (`grc`) | github.com/OpenGreekAndLatin/First1KGreek | TEI XML | Open Educational |
| `perseus` | Perseus Greek/Latin | Greek (`grc`), Latin (`lat`) | github.com/PerseusDL/canonical-greekLit + canonical-latinLit | TEI XML | CC |
| `ccel-anf` | Ante-Nicene Fathers (10 vols) | English (`eng`) | ccel.org / Project Gutenberg | ThML/HTML | Public domain |
| `ccel-npnf1` | Nicene & Post-Nicene Fathers Series 1 (14 vols) | English (`eng`) | ccel.org / Project Gutenberg | ThML/HTML | Public domain |
| `ccel-npnf2` | Nicene & Post-Nicene Fathers Series 2 (14 vols) | English (`eng`) | ccel.org / Project Gutenberg | ThML/HTML | Public domain |
| `coptic-scriptorium` | Coptic Scriptorium: Shenoute, Besa, homilies, saints' lives, monastic texts, apocrypha (ingested as genre `patristic`; the apocrypha become `apocrypha` and the Lament of the Virgin `liturgical` via `patristica/data/genre_overrides.csv`, #103; `liturgical/coptic-scriptorium` until #52 and `patristic/coptic-scriptorium` until #102; old reader URLs redirect) | Coptic (`cop`) | github.com/CopticScriptorium/corpora | CoNLL-U / TEI | per work from its documents' TT `license` headers, the most restrictive (#382): mostly CC-BY 4.0; CC-BY-NC-SA 4.0 for the Lives of Aphou, Longinus and Lucius, Paul of Tamma and Phib; CC-BY-SA 3.0 for the Canons of Apa Johannes; CC-BY-SA 4.0 for Mercurius (its header links BY-SA but reads "CC-BY") |

#### 3.3 Liturgical Texts

| ID | Text | Language | Source | Format | License |
|----|------|----------|--------|--------|---------|
| `cantus` | CANTUS Latin Chant Database | Latin (`lat`) | cantusdatabase.org (API) | JSON (API) | Free |
| `cursus` | CURSUS Medieval Liturgical Texts | Latin (`lat`) | zenodo.org/records/5090613 | TEI P4 XML | Academic |

#### 3.4 Church Slavonic (planned, #29)

The canonical Old Church Slavonic texts and their contemporaries, from the survey on #29 (2026-10-29). Language `chu`, tradition `slavonic`, stored in Cyrillic: Glagolitic witnesses are stored in Cyrillic transliteration (owner's decision on #29). The language plumbing is #330; the decision record is on #29. Source ids are provisional until each ingest PR.

| Source | Works | Format | License | Issue |
|--------|-------|--------|---------|-------|
| CCMH (Corpus Cyrillo-Methodianum Helsingiense, now at Kielipankki: kielipankki.fi/download/ccmh-src/www/) | Codex Marianus, Zographensis (+ Zogr-B), Assemanianus, Savvina kniga (Gospels and aprakos, translated 860s, MSS 10th–11th c.); Codex Suprasliensis (48 lives and homilies, Greek originals, translated late 9th–10th c.); Vita Constantini, Vita Methodii (late 9th c., later copies) | 7-bit ASCII transliteration `.txt` (some `.xml`); lines numbered by Gospel/chapter/verse or folio/line | CC-BY 4.0 | #332, #333 |
| ↳ ingested (#332) | `ccmh-marianus`, `ccmh-zographensis` (Matt 16:19–24:20 from the Zogr-B leaves, read into the same work), `ccmh-assemanianus`, `ccmh-savvina`: one work per Gospel book (`{source}/{osis book}`), org versification, `translation_of` `sblgnt`. The lectionaries are stored by Gospel verse, each verse once (its first reading, or a later one where the first is cut short, #370; the other readings are dropped). The chapter lists (kephalaia, chapter 0) are units `{book}.0.{n}` marked as titles (#369). `ccmh`: `ccmh/vita-constantini`, `ccmh/vita-methodii` (patristic, anonymous, refs `{chapter}.{verse}` of Tomšič's edition, title `0`) | `scripts/ingest/_ccmh.py` (one table per text) | CC-BY 4.0 | #332 |
| TOROT (Syntacticus release 20230428, github.com/syntacticus/syntacticus-treebank-data) | Source `torot` (#334): Psalterium Sinaiticum (`torot/ps`, Ps 2–151 with verse-0 superscriptions, versification `lxx`, from `pta-lxx`), Kiev Missal (`torot/kievmis`, rubrics as section headings), Euchologium Sinaiticum (`torot/euch`, the 8 prayers TOROT has), Chrabr *On the Letters* (`torot/chrabr`); Suprasliensis text divisions (#333). Lacunae (dots), restored letters (brackets) and the Psalter's dittographies and 1850 reader's note are editorial spans. The Ostromir colophon (`ostromir-col`, 1056–57, `orv`) is out of period. | PROIEL XML, Cyrillic, tokenized (text = presentation-before + form + presentation-after) | CC-BY-NC-SA 4.0 | #334, #333 |
| `pta` (already cloned) | Severian of Gabala, *In theophaniam*, Slavonic (`pta-chu1`, 16th-c. Minei) | TEI P5 | as PTA | #335 |
| `demetrius-psalter`: Miklas, MacRobert, Sobolev et al., *Psalterium Demetrii Sinaitici* (Glagolitica Sinaitica II, Wien 2021; e-book.fwf.ac.at/o:1578) | Psalter of Demetrius (Sinai slav. NF 3, written 1058–1066; recension I of the 9th–10th-c. translation), one Scripture work in Rahlfs numbering. Left out: Demetrius' own prayers and subscriptions (composed c. 1060, out of period) and the *Folia medicinalia* (medical recipes) | Born-digital PDF, Cyrillic transliteration; extracted with pdfplumber from character positions (no OCR) | CC BY 4.0 | #337 |

**Codex Suprasliensis** (`ccmh-supr`, #333): 48 works, one per text, in CCMH's text (CC BY 4.0). CCMH has no text boundaries; the ingestor takes them from the first token of each TOROT division (its `foreign-ids` give part, folio and line; Syntacticus commit `525cee4`), matched against CCMH's words, so only positions come from the NC-SA source. Every work's words are checked against its TOROT division (overlap 0.94–0.997). TOROT has no line ids for fols. 28–50 (found by text) and lacks the heading of Paul the Simple (85v28–30, set in `scripts/ingest/data/supr_texts.csv`); its two Pionius divisions are one text. Lost leaves (Birnbaum's foliation map) are `lacuna` marks, CCMH's marginalia (after tab runs: Retko's note on 104r, two marginal corrections, two marginal titles) are `note` marks. Greek originals: most are inside Migne containers (Chrysostom spuria, Basil's homilies, the *Scala* with Daniel's Life of Climacus, the *Historia Lausiaca*), so only Conon (PTA, BHG 2077) is linked; PTA's Severian homilies on the sinful woman, the betrayal and Thomas (CPG 4199, 4205, 4198) were checked and are other texts. BHG/CPG ids are recorded only where a text is a whole Greek work.

Out of period: the Uspenskij sbornik (Boris and Gleb, Life of Feodosij), the Primary Chronicle and the other Old East Slavic (`orv`) TOROT texts. Not usable: TITUS (copyright notices), Gorazd and the Russian National Corpus (dictionary / no redistribution). Not found yet (Clozianus, the full Euchologium, Ostromir, the Hexaemeron, the Didactic Gospel, Clement of Ohrid, Hilarion, the Izbornik of 1073): #331.

#### 3.5 Christian Arabic (planned, #83)

From the survey on #83 (2026-10-30). Language `arb` (BCP 47 `ar`), no `arabic` tradition: Arabic is a language several communities wrote in, so each work takes its community's tradition (Melkite `greek`, Syriac Orthodox and East Syriac `syriac`, Copto-Arabic `coptic`). The language plumbing is #478; the decision record is on #83. There is no Arabic in any source already cloned, and little in-period Christian Arabic exists as digital text with a usable licence; most of it is in public-domain printed editions that need OCR. Source ids are provisional until each ingest PR.

| Source | Works | Format | License | Issue |
|--------|-------|--------|---------|-------|
| tertullian.org (Roger Pearse; Arabic transcriptions with Sam Noble's and Youhanna Youssef's English): `pearse-arabic`, `pearse-arabic-eng` | Yaḥyā ibn ʿAdī, three treatises (Sbath 15–17); Abū al-Faraj ibn al-Ṭayyib, *On knowledge and miracles* (Sbath 19); Severus ibn al-Muqaffaʿ, *Book of the Councils* (Cairo fragment, ff. 268v–270v); Abū al-Majdalus, *Commentary on the Nicene Creed* (date uncertain: Pearse places him in the 10th century, nothing places him after 1050) | HTML, unvocalized Arabic after the English; the page's notes kept as note spans, Sbath's page numbers dropped | Public domain (Arabic and English) | #479 |
| OpenITI (corpus release) | *Apology of al-Kindī* (Hāshimī letter and Kindī's reply; clean transcription); *History of the Patriarchs of Alexandria* parts 1–4 to Joseph I (Evetts, PO 1, 5, 10; Kraken OCR, hybrid, dated per part from its Coptic sources to the Arabic redaction). The OCR files interleave the PO translation pages; only the Arabic lines are kept | OpenITI mARkdown text | CC BY-NC-SA 4.0 | #480 (ingested; Yaḥyā of Antioch's *Tārīkh* left out, #485) |
| Evetts's English *History of the Patriarchs* (PO 1, 5, 10; archive.org OCR text) | English translation of the HoP parts above, `translation_of` the Arabic | OCR text | Public domain | #481 |
| Public-domain printed editions (OCR, waits for the owner) | Eutychius, *Annales* (Cheikho 1906–09); Agapius, *Kitāb al-ʿUnwān* (Vasiliev, PO 5/7/8); Theodore Abū Qurrah (Bacha 1904–05; Arendzen 1897); Sinai Ar. 154 and 151 (Gibson, *Studia Sinaitica*); Cheikho, *Seize traités*; the Arabic Diatessaron (Ciasca 1888); the Arabic apocrypha of #80; the Copto-Arabic Synaxarium (#7) | Page images | Public domain | #482 |

**OpenITI** (`openiti`, #480, part of the Christian Arabic series #83): Arabic texts from the Open Islamicate Texts Initiative (github.com/OpenITI, one repository per 25-year AH bucket, files pinned to a commit), CC BY-NC-SA 4.0 (OpenITI's release licence). The mARkdown parser is `scripts/ingest/_openiti.py`. The *Apology of al-Kindī* (`openiti/apology-of-al-kindi`; the Syriac Studies text, which follows Tien's London 1880 edition, with the website's headings and scripture references marked editorial) and Evetts's parts 1–4 of the *History of the Patriarchs of Alexandria* (`openiti/history-of-the-patriarchs-1` … `-4`, section `{n}` = the life of the n-th patriarch, `{n}.{k}` its k-th printed page; starts curated in `scripts/ingest/data/openiti_hop_patriarchs.csv`). The History is uncorrected Kraken OCR of the Patrologia Orientalis, whose pages also carry the apparatus and the translation (turned into digit noise by the Arabic model): only each page's Arabic lines are kept, and footnote numbers are stripped, OCR letter errors kept (≈6% of tokens). Yaḥyā of Antioch's *Tārīkh* (Kraken OCR of PO 18.5) is still ≈12% errors after the same cleanup and is left out: #485.

Excluded: modern critical editions (CSCO after 1950, later PO volumes, Samir's editions, Badawi's Orosius, Tadmuri's Yaḥyā of Antioch: in copyright); OpenITI's Greek medicine and logic in translation (Ḥunayn, Qusṭā ibn Lūqā, …: not Christian writings); PAVONe and the Arabic Diatessaron Project (no licence or no public data). Retrieval quality and the translation-vector decision: #483.

#### 3.6 Old Georgian (planned, #222)

From the survey on #222 (2026-10-31). Language `oge` (BCP 47 `oge`; `kat` is modern Georgian), tradition `georgian`. The language plumbing is #511 (web: #512); the decision record is on #222. Almost no in-period Old Georgian is digitized under a licence that lets us publish it: the one large, clean corpus is TITUS, which needs permission. Source ids are provisional until each ingest PR.

| Source | Works | Format | License | Issue |
|--------|-------|--------|---------|-------|
| ka.wikisource | Iakob Tsurtaveli, *Martyrdom of Shushanik* (edition to check); the Shatberdi *Conversion of Kartli* (after Takaishvili 1890/91) | Wikitext, Mkhedruli with archaic letters, modern punctuation | CC BY-SA (base editions to check) | #513 |
| TITUS (titus.uni-frankfurt.de, Gippert / ARMAZI) | Nearly the whole inventory: Khanmeti fragments, the Adishi, pre-Athonite and Athonite Gospels, Acts, Paul, Catholic epistles, Apocalypse, the Oshki OT, Psalter, lectionaries; the hagiographic collections (Shushanik, Eustathius, Abo, Gregory of Khandzta, Serapion, John and Euthymius, George the Athonite, Peter the Iberian, Nino); the Shatberdi codex; the Mravaltavi; the Liturgy of St James; Kartlis Tskhovreba I; Euthymius's and George's translations | HTML, UTF-8 Mkhedruli with archaic letters; Scripture verse-numbered, prose by the edition's page and line | CC BY-NC-SA: not stated on the site (each page forbids republication without permission), but its editor stated it in reply to Patristica on 2026-11-03 (`DATA_LICENSE.md`) | #514 |
| Public-domain printed editions (OCR, deferred) | Marr, Hippolytus on the Song of Songs (1901) and *Antiokh Stratig* (1909); Kipshidze's chrestomathy (1918); Blake's Mark (PO 20, 1929); Sabinin, *Sakartvelos samotkhe* (1882); Takaishvili 1891 | Page images | Public domain | — |

**TITUS Bible and lectionaries (#515), CC BY-NC-SA** (ingested as `unknown` and published once TITUS's editor stated the licence, #514; it is set in one place, `TITUS_LICENSE` in `scripts/ingest/_titus.py`, the shared fetch/parse helper for every TITUS ingestor). One source per witness or recension, since a Scripture work id is `{source}/{book}`: `titus-khanmeti-gospels` (palimpsest A-89/A-844, Kajaia 1984; the Mkhedruli transcription), `titus-adishi` (Adishi Gospels, 897), `titus-preathonite-gospels`, `titus-athonite-gospels` (George the Athonite), `titus-acts-sinai` (Garitte 1955), `titus-acts-ab` (Abuladze 1950), `titus-paul-ab` and `titus-paul-cd` (Dzotsenidze and Danelia 1974), `titus-catholic-a1`, `-b`, `-g`, `-d` (Lortkipanidze 1956), `titus-apocalypse` (Euthymius the Athonite, Imnaishvili 1961), `titus-oshki` (Oshki Bible 978 and Jerusalem manuscripts), `titus-psalter-a` (Psalms and Odes, Shanidze 1960); and two `liturgical` works, `titus-khanmeti-lectionary` (Graz/Paris, units under the Bible ref of each lection) and `titus-paris-lectionary` (Tarchnischvili's Jerusalem lectionary with TITUS's inserted pericopes, units `{day}.{entry}`). Dated by the translation or revision, not the manuscript. Variant lines (`Verse: 1V`) and the manuscripts' book titles are left out; TITUS's brackets become editorial spans. Not ingested: the Vienna khanmeti palimpsest (private use only), the Mtskheta, Bakar and Gelati Bibles (out of period), the synopsis `ntkpl` (a view of the Gospel sets), and the Graz Psalter, Exodus–Deuteronomy recension AK, Song of Songs redaction G, the Petritsi Ecclesiastes and the NT apocrypha, which are left for later issues.

English parallels in the public domain: Wardrop's *Life of St Nino* (Studia Biblica V.1, 1900; Sabinin's late recension) and Conybeare's *Sack of Jerusalem* by Antiochus Strategos (EHR 1910). Skipped: GNC and the UD Old Georgian treebanks (built from TITUS), the MyBible "OGB" (Church Bible, out of period or of unknown licence), NPLG and Ilia University scans (copyright or none stated); eBible has no Georgian. In copyright: Lang (1956–66), Thomson (1996). Retrieval quality and the translation-vector decision wait for enough Georgian text (TITUS).


#### 3.7 Old Irish (#225)

From the survey on #225 (2026-11-01). Language `sga` (BCP 47 `sga`) for every Irish text in period, early Middle Irish included; tradition `latin`. The plumbing is #538 (web: #544); the decision record is on #225. There is no Old Irish Bible: the in-period religious literature is glosses, hymns, martyrologies, lives, rules and biblical verse. Source ids are provisional until each ingest PR.

| Source | Works | Format | License | Issue |
|--------|-------|--------|---------|-------|
| `wb-glosses` + `wb-glosses-eng`: Würzburg glosses (A. Doyle's digital text of *Thesaurus Palaeohibernicus* I 499–712, Zenodo 5508250) | 3,648 glosses on the 14 Pauline epistles, with folio, gloss number, hand, biblical ref and Latin lemma; Stokes and Strachan's English translation of each. Ingested as one Irish and one English work per epistle (`wb-glosses/rom`, `wb-glosses-eng/rom`, …), 3,511 glosses each; the 137 glosses with no Irish (wholly Latin) are left out | JSON | CC BY 4.0 (the 1901 translations are public domain) | #539 |
| `glosscorpus`: Gloss Corpus (P. Moran, Galway; github.com/padraicmoran/glosscorpus, pinned commit), `felire/basetext.xml` | Félire Óengusso (`glosscorpus/felire`, liturgical, c. 797–833): the 365 calendar quatrains in Rawlinson B 505 (diplomatic, abbreviations expanded, no prologue or epilogue), refs `Fel.{Mon}.{day}` with an editorial month heading at `Fel.{Mon}`; supplied letters marked `supplement`, one gap `lacuna`. The other base texts (Isidore, Priscian, the Vulgate of *Thesaurus Palaeohibernicus*) are Latin and not ingested | TEI | CC BY-NC-SA 4.0 | #540 |
| `celt`: CELT (celt.ucc.ie, UCC) | 46 Irish works in period (#541): Stokes's Félire Óengusso (prologue, calendar, epilogue), Saltair na Rann, Bethu Brigte, the Irish Life of Adamnán, Cáin Eimíne Báin, Molaisse and his sister, Tiugraind Beccáin, Airbertach mac Coise's poems on the Psalms and on Adam, the Rules of Mo Chutu and of Colum Cille, Apgitir Chrábaid, On the deadly sins, On secret sins, Bríathra Flainn Fína, the Vision of Laisrén, Baile Bricín, Dofil aimser laithe mbratha, Pátraic cecinit, the Old Irish Bede extract, and 25 religious poems from Murphy's *Early Irish Lyrics* and Meyer's small editions; plus the English translations CELT has of Bethu Brigte and the Vision of Laisrén | HTML (the TEI masters are not downloadable) | Restricted ("available with prior consent of the CELT programme"): consent granted to Patristica, non-commercial, 2026-11-12 (`used-with-permission`, #542; recorded in `DATA_LICENSE.md`) | #541 |
| *Thesaurus Palaeohibernicus* I–II (Stokes and Strachan 1901–03, archive.org OCR; deferred) | Milan glosses on the Psalm commentary, Turin glosses on Mark, the Cambrai Homily, the hymns and poems, the Stowe Missal tract, the minor glosses | Page images, damaged OCR | Public domain | #543 |

**CELT (#541), `license: used-with-permission`** (CELT's consent for Patristica, non-commercial, with attribution, granted 2026-11-12, #542; `CELT_LICENSE` in `scripts/ingest/_celt.py`, grant in `DATA_LICENSE.md`). One source, `celt`, one work per CELT text (`scripts/ingest/celt.py`, table `TEXTS`/`LYRICS` with each text's dating basis); the pages are cached in `data/raw/_cache/celt/`. Refs follow the edition: stanzas for poems (`Fel.Jan.1`, `Fel.Prol.1`, `Fel.Epil.1`, matching the Gloss Corpus Félire), Stokes's quatrain line numbers for Saltair na Rann (`SnR.{poem}.{line}`), section or ¶ numbers for prose (`BBrig.12`, `BBrig.Slicht.3`). CELT's `[gap: …]`, bracketed restorations, marginal references and deletions are editorial spans; page and folio markers, line numbers and footnote calls are dropped (the notes are separate pages, not fetched); editors' introductions and the Félire's Middle Irish prose prefaces are left out. Kept when in period by CELT's date or the standard scholarship (Saltair na Rann 988, Mac Eoin; Tiugraind Beccáin 7th c., Kelly; Apgitir Chrábaid c. 600–800, Ó Néill; the Irish Life of Adamnán 956×964, Herbert and Ó Riain). Borderline (owner, 2026-11-01): Molaisse (800–1000) and the Rule of Mo Chutu (usually taken as late Old Irish; CELT 900–1200; the Rule, not the late Life) kept, marked `uncertain`; five lyrics Murphy dates 10th–11th c. (*Rop tú mo baile*, *Tórramat do nóebaingil*, *A Maire mín*, *Mé Éba*, *Ropo mían*) left out, their composition probably after 1050 (`OWNER_EXCLUDED` in `celt.py`). Left out: texts CELT dates only to "900–1200" without earlier evidence, the Leabhar Breac lives, passions and homilies, the Lismore and Plummer lives, Mo Ling, Colmán mac Lúacháin, the Fifteen Tokens, Tidings of Doomsday and of the Resurrection, Aisling Tundail, the Irish Litanies (900–1500, mixed; could be split per litany later), later Early Modern texts, and the secular lyrics. The Latin (`L…`) files are out of scope.

Skipped: CorPH/ChronHib and the Milan Glosses Database (no public download or licence), the St Gall Priscian glosses (grammar, not Christian literature), POMIC (a few parsed texts, no licence).
#### 3.8 Old English, Old High German and Old Saxon (#223, #224)

From the survey on #223/#224 (2026-11-02). Three languages: `ang` (Old English), `goh` (Old High German) and `osx` (Old Saxon), BCP 47 the same, tradition `latin`. The plumbing is #563 (web: #564); the decision records go on #223 (Old English) and #224 (OHG and Old Saxon). Gothic is already in the corpus; Old Frisian and Old Norse have no Christian texts in period. Old Low Franconian (the Wachtendonck Psalms) is in ReA after all, among the minor Old Saxon texts, but is not ingested: it is neither `goh` nor `osx`. Clearly secular texts are left out (heroic and historical poetry such as *Beowulf*, *Maldon* and the *Hildebrandslied*, riddles, pagan charms, Notker's school texts), and each source PR lists what it leaves out; Notker's Boethius and the *Meters of Boethius* are kept, since Boethius is in the corpus. Source ids are provisional until each ingest PR.

| Source | Works | Format | License | Issue |
|--------|-------|--------|---------|-------|
| `aspr`: ASPR digital text, Oxford Text Archive 3009 (Hidley/Toronto DOE, corr. Macrae-Gibson; `3009.xml` from the llds.phon.ox.ac.uk bitstream, cached in `data/raw/_cache/aspr/`) | 69 religious, homiletic and wisdom poems of Krapp and Dobbie's *Anglo-Saxon Poetic Records* I–VI (`scripts/ingest/aspr.py`, tables `POEMS` / `DROPPED` / `DEFERRED`), one work per poem: the Junius MS (*Genesis A/B*, *Exodus*, *Daniel*, *Christ and Satan*), the Vercelli poems (*Andreas*, *Fates*, *Dream of the Rood*, *Elene*, …), the Exeter Book (*Christ I–III* split at ASPR's lines 440 and 867, *Guthlac*, *Phoenix*, *Juliana*, *Wanderer*, *Seafarer*, the gnomic poems, …), *Judith*, the *Meters of Boethius* (one work, a section per meter) and the minor poems (Cædmon's Hymn, Bede's Death Song, the Creed, Lord's Prayers, Glorias, …). Units are sentence groups with ASPR line refs (`Dream.1`, `Christ.440`, `MBo.10.1`): numbered lines are the TEI's `<l>` with a caesura. Emendations (`<unclear>`) are `supplement`, gaps and `/` damage `lacuna`, Latin cue lines `rubric`; runes become Unicode futhorc. Left out: heroic and historical poems, the secular elegies, riddles, charms, *Durham* (1104–1109). The metrical Paris Psalter (Ps 51–150) and the Benedictine Office psalm fragments wait for verse numbers (#569) | TEI XML | CC BY-SA 3.0 (the file's header; the legacy item 1936 is BY-NC-SA) | #565 |
| `aelfric-ch` + `aelfric-ch-eng`: Project Gutenberg #38334, Thorpe, *The Homilies of the Anglo-Saxon Church* I (1844) | Ælfric, *Catholic Homilies* I: 42 `aelfric-ch` works (the 40 homilies `ch1-01` … `ch1-40` and the preface `ch1-praefatio` in Old English, the Latin preface `ch1-praefatio-lat`) and 41 `aelfric-ch-eng` works, Thorpe's facing English (`translation_of` the Old English work), 725 and 722 units. The facing pages pair element for element, so both sides share their refs (`AECHomI.{homily}.{paragraph}`, §5); the English is enrolled for anchored derived verses. Latin pericopes and quotations stay in the text; Thorpe's endnotes and his own preface are not carried. The HTML keeps þ ð æ ǽ and the accents; the .txt is ASCII | HTML | Public domain | #566 |
| `rea`: Referenzkorpus Altdeutsch (DDD-AD) 1.2, LAUDATIO repository; relANNIS export downloaded from `laudatio-repository.org/download/format/1/53/1.2` and cached as `data/raw/_zips/rea-relannis-1.2.zip` | 59 works (#567): OHG Tatian (Sievers chapter.verse) with its Latin column, Otfrid (book.chapter.line, with the Latin letter to Liutbert as its own work), the Isidor and the Monsee fragments (Matthew, *De vocatione gentium*, Isidor, Augustine's Sermo 76, a homily), the Murbach Hymns with the Latin hymns, the St. Gall 916 Benedictine Rule (interlinear, its unglossed words as lacunae) with its Latin, Notker's Psalter, *Cantica* and Boethius, the *Heliand* (fitt.line) and Old Saxon *Genesis*, and 38 religious minor texts (Muspilli, Ludwigslied, Georgslied, confessions, creeds, baptismal vows, prayers, the Exhortatio, the Weissenburg Catechism, the Gernrode Psalm commentary, …). Left out (`DROPPED` in the ingestor): secular texts, charms, Notker's school texts and Psalter glosses, the Physiologus (c. 1070), the 12th-century confessions and sermons, and four texts dated only by 11th-century manuscripts. Text from the `edition` layer (the Isidor from `text`); lacunae and supplied letters are editorial spans | relANNIS | CC BY-NC-SA 3.0 | #567 |
| HeliPaD (Walkden, Zenodo 4395039) | *Heliand*, MS C (Sievers 1878) | Penn treebank | CC BY 4.0 | fallback only, if ReA's *Heliand* is unusable |
| archive.org scans of PD editions (deferred) | Nearly all Old English prose: the West Saxon Gospels, *Pastoral Care*, the Old English Bede, Orosius, the *Blickling Homilies*, Wulfstan, Ælfric's *Lives* and *Catholic Homilies* II, the *Martyrology*, Gregory's *Dialogues*, the *Soliloquies*, the Benedictine Rule, the Lindisfarne and Rushworth glosses | Page images | Public domain | #568 |

Not used: the YCOE and the Dictionary of Old English Corpus (no redistribution), ISWOC's Old English (excerpts only), TITUS (no republication without permission), and the "Wessex" Gospels of textusreceptus.thekingsbible.com (no licence).

Latin originals already in the corpus, for `translation_of` and anchoring: Boethius, *De consolatione* (`csel/stoa0058/stoa001/opp-lat3`) for Notker's Boethius; Isidore, *De fide catholica* (`oglt-pl/isidorus-hispalensis/pl83_10_sa`) for the OHG Isidor; and, for the deferred Alfredian prose, Gregory's *Regula pastoralis* (PL 77), Augustine's *Soliloquia* (PL 32) and Orosius (CSEL).

#### 3.9 Literary Chinese (#228)

From the survey on #228 (2026-11-12). Language `lzh` (BCP 47 `lzh`), tradition `syriac` (the Church of the East's Tang mission, Jingjiao 景教); traditional characters stored as each source gives them. The plumbing is #648 (web: #649).

| Source | Works | Format | License | Issue |
|--------|-------|--------|---------|-------|
| `cbeta`: CBETA's Taishō, TEI P5 (github.com/cbeta-org/xml-p5, pinned commit; cached in `data/raw/_cache/cbeta/`) | Taishō 54: T2142 序聽迷詩所經, T2143 split into the hymn 景教三威蒙度讚 and 尊經, T2144 the Xi'an stele (Jingjing, 781). T2141A/B (Manichaean) are out of scope | TEI XML | CC BY-NC-SA 4.0 (cbeta.org/copyright, checked 2026-11-12; the file header: non-commercial use with the header intact) | #651 |

**CBETA (#651), `license: cc-by-nc-sa-4.0`.** One work per text (`scripts/ingest/cbeta.py`, table `TEXTS` by Taishō number, so more texts can be added). Refs are the Taishō line a unit starts on, `T{no}.p{page}{register}{line}` (`T2143.p1288b05`), with CBETA's `<p>` as the prose unit and one `<l>` (a couplet, its halves joined by an ideographic space) as the hymn's unit; the hymn is ingested as `verses`. CBETA's rare characters (`<g>`) are resolved through the header's `charDecl` (Unicode, else CBETA's normalized form); the one with no Unicode form (CB07751 in T2142) is kept as CBETA's composition and marked `note`. Inline notes are the manuscripts' small print and kept; the apparatus (the Taishō's witness notes, CBETA's corrections) is dropped, the corrected reading kept. Titles are `title`, the stele's byline `heading`, `□` `lacuna`; the stele's 1859 colophon by Han Taihua is left out.

---

### Tier 2 — Downloadable but less structured; require significant parsing

| ID | Text | Language | Source | Format | Notes |
|----|------|----------|--------|--------|-------|
| `peshitta` | Peshitta NT (SEDRA) | Syriac (`syc`) | sedra.bethmardutho.org + github.com/peshitta/sedrajs | DB/JS | **Superseded by `pta-peshitta` (clean TEI, 85 books)** |
| `gez` | Ethiopic Bible (Ge'ez) | Ge'ez (`gez`) | github.com/LPettay/ethiopian-bible (Beta Masaheft data) | JSON chapter files | CC-BY-SA 4.0 |
| `armenian` | Classical Armenian Bible (Zohrab 1895) | Armenian (`hye`) | arak29.org/bible/book/ (1895 Constantinople edition) | HTML per chapter | Public domain |
| `vetus-latina` | Vetus Latina fragments | Latin (`lat`) | itseeweb.cal.bham.ac.uk | HTML | Check licensing; fragmentary |
| `ogpg` | Open Patrologia Graeca (OCR) | Greek (`grc`) | github.com/OGL-PatrologiaGraecaDev | .txt/.hocr | Public domain; OCR noise |
| `dco` | Documenta Catholica Omnia | Latin (`lat`) | documentacatholicaomnia.eu | PDF/DOC | Unclear license; Latin originals |
| `gallican` | Gallican Liturgy (Neale/Forbes 1855–67: Missale Richenovense, Gothicum, Gallicanum Vetus, Vesontionense = Bobbio Missal, one work each, #245; Muratori's Missale Gallicanum Vetus) | Latin (`lat`) | Internet Archive | OCR text | Public domain; OCR needed |
| `mozarabic` | Mozarabic Rite (Ferotin editions) | Latin (`lat`) | Internet Archive | PDF | Public domain; OCR needed |
| `gez-anaphoras` | Ethiopian Anaphoras (14 anaphoras) | Ge'ez (`gez`) | ethiopianorthodox.org + Internet Archive | PDF | Public domain |
| `syriac-james` | Liturgy of St. James (Syriac) | Syriac (`syc`) | Internet Archive | PDF | Public domain |
| `armenian-liturgy` | Armenian Divine Liturgy | Armenian (`hye`) | Internet Archive | PDF | Public domain |
| `ecumenical` | Seven Ecumenical Councils | English/Greek (`eng`/`grc`) | CCEL / Internet Archive | HTML/PDF | Public domain |

---

### Tier 3 — Requires scraping or special API access

| ID | Text | Language | Source | Notes |
|----|------|----------|--------|-------|
| `hudra` | East Syriac Hudra texts | Syriac (`syc`) | hudra.day | Read through hudra.day's Firestore REST API, not scraped; no cache, so it can't be ingested offline (#215). Transcriptions used with permission of hudra.day / Hendo Academy (2026-10-24; non-commercial, with attribution; licence `used-with-permission`, #262); hudra.day's own terms allow viewing only (#32). |
| `goarch-chrysostom` | Liturgy of St. John Chrysostom (Greek) | Greek (`grc`) | goarch.org | HTML scrape |
| `goarch-basil` | Liturgy of St. Basil (Greek) | Greek (`grc`) | goarch.org | HTML scrape |
| `typikon` | Greek Typikon (selected first-millennium sections) | Greek (`grc`) | Violakis 1900 ed. via archive.org/details/typikontstou00orth | OCR plain text; date filtering required via flag_liturgical.py second pass |
| `tertullian-eng` | English translations from Roger Pearse's *Additional Fathers*: 60 works, each `translation_of` its Greek, Latin or Syriac original (Library of the Fathers, SPCK, Bohn, Hakluyt, Wright's *Apocryphal Acts*, Pearse's public-domain commissions; #347) | English (`eng`) | tertullian.org | HTML scrape (`scripts/ingest/tertullian_eng.py`, shared parser `_tertullian_org.py`), pages cached in `data/raw/_cache/tertullian-org/` |

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
uv run python -m scripts.ingest.all --source oshb [--force]

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
| Apocrypha | Paragraph / `<div>` section (as patristic prose) | 400–600 | 50 tokens |
| Liturgical prose | Prayer / collect / strophe | 200–400 | 1 sentence |
| Liturgical poetry/hymnody | Stanza | 1 stanza | None |
| Council acts | Paragraph / canon | 300–500 | 50 tokens |

### Canonical reference format

All chunks carry a `canonical_ref` in dot-separated form:
- Scripture: `Gen.1.1`, `Matt.5.3`
- Patristic: `{author_abbrev}.{work_abbrev}.{book}.{section}.{paragraph}` — e.g. `Aug.Conf.1.1.1`
- Liturgical: `{rite}.{service}.{element}` — e.g. `ByzLit.Chrysostom.Anaphora.3`
- Councils: `Nicaea1.Canon.7`
- Manuscripts cited by folio: `{siglum}.{folio}{r|v}`, one unit per page — e.g. `Supr.119r` (Codex Suprasliensis in the codex's continuous foliation, 1r–285v, as the obdurodon edition cites it; CCMH numbers the three parts 1–3 separately). A page shared by two texts is a unit in each ([#333](https://github.com/jaspax/patristica/issues/333)).
- Glosses by folio and gloss number, as the *Thesaurus Palaeohibernicus* cites them (Würzburg glosses, [#539](https://github.com/jaspax/patristica/issues/539)): `Wb.{folio}.{gloss}` — e.g. `Wb.1a.8` for Wb. 1a 8, `Wb.2a.8a` for an inserted gloss, `Wb.1b.10-11` for two numbers printed as one gloss. The Irish work and its English translation share the refs.
- Ælfric's *Catholic Homilies* I by homily and paragraph of Thorpe's edition ([#566](https://github.com/jaspax/patristica/issues/566)): `AECHomI.{homily}.{paragraph}` (the Dictionary of Old English short title ÆCHom I), the paragraph being the k-th element (heading, pericope or paragraph) of the homily's facing-page text, e.g. `AECHomI.8.3`; `AECHomI.Praef.{k}` for the Old English preface and `AECHomI.PraefLat.{k}` for the Latin one. The Old English work and Thorpe's English share the refs.
- Project Gutenberg English translations (`gutenberg-eng`, [#349](https://github.com/jaspax/patristica/issues/349)): the book's own divisions and the k-th paragraph (or stanza) in them, behind a prefix per work: `ProcWars.{book}.{chapter}.{k}`, `ProcAnec.{chapter}.{k}` (`ProcAnec.Intro.{k}`), `BarlIoas.{chapter}.{k}` (`BarlIoas.Praef.{k}`), `JDImag.{oration}.{k}`, `JDDorm{n}.1.{k}`, `PrudCath.{hymn}.{stanza}` (`Praef`, `Epil`); a translator's introduction is `{prefix}.TrPref.{k}`.
- TITUS prose by printed page and line (Old Georgian hagiography, [#516](https://github.com/jaspax/patristica/issues/516)): `{text}.{chapter}.{paragraph}`, the editors' chapter (Roman numerals as Arabic, `0` before the first) and the paragraph within it, a paragraph being a run of lines from one indented line to the next: e.g. `Shush.3.2`. A set that numbers its own paragraphs uses them: `AsIoZedA.39-a`.
- Referenzkorpus Altdeutsch (`rea`, #567): the editions' numbering behind a prefix per work. Verse-numbered texts are ingested as verses: `Tat.{chapter}.{verse}` (Sievers; the prologue is chapter 0) and `MH.{hymn}.{strophe}`. The poems are ingested as paragraphs, their long lines grouped into units at the edition's number of the unit's first line (#586; normalize cuts long units into derived verses; citing a single line is #593): the *Heliand* (`Hel.{fitt}.{line}`, Behaghel's continuous lines), the *Genesis* (`AsGen.{fragment}.{line}`), *Muspilli*, the *Wessobrunn Prayer*, the *Augsburg Prayer* and the *Carmen ad Deum* by the ASPR rule (a unit runs to the next line that ends a sentence); Otfrid by couplet (`Otfr.{book}.{chapter}.{odd line}`, `Otfr.L`/`S`/`H.{odd line}` for the dedications, whose acrostics run by these strophes; `Otfr.{book}.0.{n}` for each book's Latin capitula, one unit each); the *Ludwigslied*, *Georgslied*, *Petruslied*, *Christus und die Samariterin* and *Psalm 138* by strophe (at least a couplet, run on to the next line that ends a sentence; a refrain or a printed strophe number closes or opens one), `{siglum}.{first line}`. Prose is ingested as paragraphs: `Isid.{chapter}.{section}`, `NPs.{psalm}.{page}` and `NCant.{canticle}.{page}` (Tax's pages), `NBo.{book}.{section}`, `RB.{chapter}` (the Benedictine Rule, both columns; the prologue `RB.0`), `Mons.{fragment}` (Hench), the Latin Tatian `Tat.{chapter}`, and `{siglum}.1` (or `{siglum}.{section}`) for each minor prose text. A bare section ref (`Otfr.1.2`) is the chapter's title.

### Duplicated section numbers

Many editions print the paragraph number at the start of the paragraph (`3 Αὐτοκράτορι…` in First1KGreek, `1. Great art Thou…` in NPNF, `α. Πᾶσαι…` in PTA, `[3] …` in ANF), and the ref already carries it. `normalize.py` strips such a prefix from non-scripture chunks, only when its value equals the ref's last segment (`patristica/section_numbers.py`, [#30](https://github.com/jaspax/patristica/issues/30)). It handles Arabic digits (bare, `3.`, `3)`, `[3]`, `(3)`, also glued to the word as in `3Καὶ…` or `2.δι’…`), superscript digits (`⁴καὶ…` in First1KGreek's 1 Enoch, including OCR-mixed runs like `¹7`; [#121](https://github.com/jaspax/patristica/issues/121)), Greek numerals with a keraia or dot (Greek text only), and Roman numerals followed by `.` or `)`. A glued number needs a following word of two or more letters that is not an ordinal suffix or a short abbreviation (`1st`, `3a.`, `4.col.a.` stay). Raw files keep the number. A bare number followed by a numbered book (`1 Cor.`, `1 Timothy`) or by `bis` or a Roman calendar word (`8 kal.`) is content and stays. `ogpg` is skipped: its refs end in a paragraph's position on its Migne page, a number the OCR text never prints, so a match there is coincidence. Not handled: printed numbers that differ from the ref, such as continuous paragraph numbering against chapter.section refs. They can't be told apart from content. `validate.py` warns (`text_starts_with_section_number`) about any chunk that still starts with its ref's number. Superscript digits anywhere else are left in the text, including a leading one that differs from the ref (OCR-damaged verse numbers such as 1 Enoch's `⁰` at 1.2): in this corpus they are footnote markers (Coptic Scriptorium's `⁽²⁾`), Migne OCR noise or mojibake, never inner verse numbers. `validate.py` lists them (`text_has_superscript_digits`).

### Editorial material

Material that an editor or the source added to a text (titles, headings, supplements, lacuna markers, catalogue metadata, notes) is marked, not stripped ([#236](https://github.com/jaspax/patristica/issues/236), `patristica/editorial.py`, CLAUDE.md "Editorial material"): it stays in the text for readers, and spans `[start, end, kind]` on the unit keep it out of translation and embedding. Pure noise (OCR damage, layout placeholders, footnote markers whose notes the source lacks) is still dropped at ingest. Per source:

| Source | Material | Status |
|---|---|---|
| `coptic-scriptorium` | lacunae `[....]`, `[…]`, `[]` in the normalized layer | marked `lacuna` at ingest (#236). Bracketed letters (`[ⲉ]`) stay unmarked; the diplomatic `orig` is a whole alternative rendering, not editorial material |
| `cantus` | `[feast] [service] … [CANTUS:id] [mode:n]` prefix | to mark `metadata` in normalize (no offline re-ingest): [#163](https://github.com/jaspax/patristica/issues/163) |
| `first1k` | `<gap>` lacunae; `<head>`s in divs whose paragraphs share the div's ref | [#71](https://github.com/jaspax/patristica/issues/71), [#259](https://github.com/jaspax/patristica/issues/259) |
| `gez` | the edition's `[…]` / `(…)` brackets | to mark (`supplement` where the brackets enclose an editor's addition: brackets marked, content embedded): [#297](https://github.com/jaspax/patristica/issues/297) |
| `coptic-nt` | CopSahBible2 `<…>` supplements | to mark `supplement` (content embedded, brackets not): [#298](https://github.com/jaspax/patristica/issues/298) |
| `oshb` | the ketiv, as a note beside the qere | [#299](https://github.com/jaspax/patristica/issues/299) |
| `wb-glosses`, `wb-glosses-eng` | each gloss's lemma, prefixed as `Rom. 1:8 meo]`; the editors' comments `[in marg.]`; restored `(…)` and supplied `[…]` letters | marked at ingest: lemma and comments `note`, restored and supplied letters `supplement` ([#539](https://github.com/jaspax/patristica/issues/539)) |
| `aelfric-ch`, `aelfric-ch-eng` | the rubrics and Thorpe's headings (`h3`), the inner headings (`EUANGELIUM.`), Thorpe's supplied words `[on]` | marked at ingest: `title`, `heading`, `supplement`; page numbers dropped, Thorpe's endnotes not carried ([#566](https://github.com/jaspax/patristica/issues/566)) |
| `tertullian-eng` | footnotes (on the page, or on a notes page), headings (`h1`–`h6`, short centred or bold lines, contents entries), translators' introductions in small type, editors' remarks on a line of their own, Archer's bracketed notes (Jerome on Daniel) | marked at ingest: footnotes in place of their markers as `note`, the rest whole-unit `heading` / `note`; page and column numbers, navigation and licence lines dropped; translators' prefaces and margin summaries not carried ([#347](https://github.com/jaspax/patristica/issues/347)) |
| `gutenberg-eng` | the translators' introductions and prefaces; the Secret History's chapter arguments; titles and headings; footnotes and their markers; the Loeb's marginal dates | marked at ingest: introductions as whole `note` units (`{prefix}.TrPref.{k}`), arguments `heading`, titles `title`/`heading`, footnotes appended to the paragraph citing them and marginal dates `[408 A.D.]` as `note` spans; page numbers dropped ([#349](https://github.com/jaspax/patristica/issues/349)) |
| `cbeta` | titles (`<cb:jhead>`, `<head>`), the stele's byline, `□`, the composition of a character with no Unicode form | marked at ingest: `title`, `heading`, `lacuna`, `note`; the apparatus is dropped ([#651](https://github.com/jaspax/patristica/issues/651)) |
| `brenton-eng` | Brenton's footnotes (alternative and literal renderings) and cross-references | marked at ingest: `note`, moved to the end of their verse ([#355](https://github.com/jaspax/patristica/issues/355)) |
| `asv` | Psalm titles `Ps.N.0`, Hab 3:19's closing note | text, not editorial: kept as verse 0 ([#300](https://github.com/jaspax/patristica/issues/300)) |

### Patrologia Graeca: columns, refs and works

The OGL PG repos are plain page OCR with no work boundaries ([#67](https://github.com/jaspax/patristica/issues/67)). `scripts/ingest/ogpg.py` extracts each volume once (cached in `data/raw/ogpg/_extract/`, with the column numbers found on every page of the primary scan) and then cuts it into works:

- **Columns.** `_ogpg_columns.py` maps each scan page to the two Migne columns it prints, from the numbers in the running heads. Within a run of pages, `column = k × page + offset` (`k` = 2, or 1 in the Chrysostom volumes, where the Latin is on the facing page). A Viterbi pass picks a piecewise-constant offset path (switching costs more the further the offset jumps, so misread digits such as 1305 → 1505 don't pull it away), only the best-supported increasing chain of runs is kept (numbers in front matter, such as a Vita's years, are dropped), and long gaps are interpolated when their columns advance at 1 or 2 per page. Pages are read in numeric order (some scans have over 999 pages). After a stretch of pages with no head numbers (blank OCR), the offset may fall by up to the stretch's length at no extra cost, since those pages may print fewer columns than they number, never more. **Repeated pages ([#96](https://github.com/jaspax/patristica/issues/96)).** About 90 primary scans contain runs of leaves twice (PG 2, 18, 93, 94, 119 and many more; ~4,400 pages, 7% of the extracted text): `_ogpg_repeats.py` finds a page whose text matches an earlier page and starts or ends like it (a passage Migne prints twice, such as a quotation in a note or parallel chronicles, sits elsewhere on its page and is kept), `split_volume` drops its paragraphs, and the column mapping leaves it out and numbers the scan as if it were not there. A page inside a repeated run whose first copy has no text (its OCR failed) is the only copy and takes that page's place. **Other scans ([#90](https://github.com/jaspax/patristica/issues/90)).** The primary scan (most dictionary-valid Greek) may stop early, lose pages or carry another volume's leaves. At extraction, every scan is placed on columns the same way; columns no primary page covers are filled from the other scans (most Greek first) when the page's text isn't already in the primary nearby and its scan's column mapping is confirmed by head numbers within two pages (`fills` in the extraction, merged by column in `split_volume`). A run of primary pages whose text most other scans lack at those columns, while their text for those columns is nowhere in the primary nearby, is misbound (PG 46 carries PG 44 leaves at cols. 105–135, PG 44 PG 46 leaves): it is dropped and filled the same way. Text that no scan has OCR'd (the end of PG 31, PG 37's later Carmina, the second half of PG 60–62) needs new OCR ([#94](https://github.com/jaspax/patristica/issues/94)).
- **Refs.** `ogpg.{vol}.c{first column:04d}.{n}`: the first column of the paragraph's page and the paragraph's number on that page (`ogpg.vol-045.c0009.1`). A page with no column uses the scan page, `p{page:04d}`. Refs are the same whether or not a volume is split.
- **Works.** `scripts/ingest/data/ogpg_index.csv` (one row per work, or several rows with the same slug and metadata for a work printed in pieces, such as Cyril of Alexandria's Ep. 17 in PG 77: volume, slug, Migne column range, author, title, CPG, dates, `basis`, `duplicate_of`, note; documented in `_ogpg_index.py`) is the curated attribution table. Rows come from each volume's printed *Elenchus* (table of contents, read from the OCR of several scans) and were checked against the work titles (Greek capitals headings) that the OCR finds at those columns. On a page shared by two works the split falls at the first heading. Work ids are `ogpg/{vol}/{slug}`; text outside every row (front matter, prefaces, notes, misbound leaves) goes to `ogpg/{vol}/other`, so nothing is dropped silently. Volumes without rows stay one work, `ogpg/vol-NNN`. A row dated after the collection period is dropped: later commentaries (Elias of Crete and Nicetas of Heraclea in PG 36, George Pachymeres's paraphrase of Dionysius in PG 3–4, which alternates with the text chapter by chapter), later canonists (PG 119), and the 17th–19th-century prefaces, dissertations and notes printed as separate sections (Massuet, Huet, Le Nourry, Allatius, Petavius, Le Quien, Bentley and others). When an author was born before 1025 but wrote after 1050 (PG 119–120), the row's dates are left blank so that the work takes the volume's dates and is not flagged. Only Greek is extracted, so works that survive only in Latin translation (Rufinus's De principiis in PG 11, Jerome's versions of Origen's homilies in PG 13, Hesychius on Leviticus in PG 93) have little or no text: the De principiis work is the Greek fragments printed beside the Latin. The old reader URL of a split volume redirects to the library index filtered to its works (`SPLIT_OGPG_VOLUMES` in `web/src/lib/redirects.ts`; a test keeps it in sync with the CSV).
- **Duplicates.** Where the same text is also in First1KGreek, PTA or Perseus, both are kept: the Migne OCR is a different (and noisier) witness, and its refs are Migne columns, which scholars cite. The row's `duplicate_of` names the cleaner edition, and the OCR work's `edition` says so.
- **Coverage.** All 125 volume repos (PG 1–120, with the parts of PG 16, 86 and 87) have rows, 942 in all: 744 works with text, plus an `other` file for the volumes with text outside every row. Where a volume has no usable *Elenchus*, or a work has no heading in the scan, rows use the standard PG columns (`basis` = `curated`, with a note). Many primary scans lack pages or whole ranges of columns (for example PG 8 has no Paedagogus, PG 31 stops at col. 1401, PG 119 has no pages for cols. c. 414–824), so 71 rows find no text; filling them from other scans is #90. Coarse rows that could be split further, such as Basil's homilies (PG 31) and Chrysostom's sermones panegyrici and spuria (PG 49–50), are left for a follow-up.

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
| CCMH ASCII transliteration (Church Slavonic, #29) | `scripts/ingest/_ccmh.py`: one `Table` per text, from its `.html` page (`a`→а, `&`→ъ, `$`→ь, `@`→ѣ, `E`/`O`→ѧ/ѫ, Glagolitic `u`→оу but Cyrillic `u`→ѹ, `*` capital, `!word` titlo over the second letter, `!` inside a word a superscript letter + pokrytie, `'` paerok → ꙿ, `::`→⁘, `:.`→⁖, `:-`→⁛; Savvina writes jat as `"e`). Edition signs become editorial spans (#236): `[…]` and Zogr-B `<…>` supplements, `=…=` (later hand) supplement, `{…}` (dittography) note, `?` and `-` lacuna, the scribes' lection marks (кⷰ҇ "end", заⷱ҇ "beginning") metadata; CCMH's `%` check marks are dropped. Checked against TOROT's Cyrillic of the same files: base letters agree on 94.4% of 3,613 Marianus verses and 93.0% of 761 Zographensis verses (the rest are TOROT's corrections and expansions); marks agree except titlo placement (TOROT: first letter) and the Zographensis dasia and breves TOROT drops |
| Glagolitic (any Slavonic source) | `scripts/ingest/_slavonic.py` `glagolitic_to_cyrillic()` (U+2C00–2C5F, combining U+1E000–1E02F; yer + i → ꙑ). TOROT's Suprasliensis has ~1,300 Glagolitic letters for Cyrillic ones (ⱕ for ѧ) |
| TOROT PROIEL XML (Church Slavonic) | Join tokens as presentation-before + form + presentation-after. In Marianus about a fifth of the stops have no space after them (`г҃лѧ.азъ`); put one back, since derived verses only break between words |
| Arabic (any source, #83) | Stored as the source gives it, unvocalized where it is (every selected source is), in the base Arabic block; presentation forms are not converted at ingest (`fold()` maps them for search). Keyword folding (`patristica/textfold.py`, #478): harakat and tatweel dropped, أ/إ/آ/ٱ → ا, ى → ي (Christian and Egyptian printing writes الذى), OCR's Persian ی/ک → ي/ك; ة and ه kept apart (كتابة ≠ كتابه). Garshuni (Arabic in Syriac script) is decided when a source has it |
| Old Georgian (any source, #222) | Stored in Mkhedruli with the archaic letters ჱ ჲ ჳ ჴ ჵ, as TITUS and Wikisource give it; no conversion at ingest. Keyword folding (`patristica/textfold.py`, #511): Asomtavruli, Nuskhuri and Mtavruli → Mkhedruli letter for letter (Khutsuri ოჳ → უ), and old spelling → modern for matching: ჱ → ე, ჴ → ხ, ჳ → ვ before a vowel and ვი elsewhere, ჲ → ი before a vowel and dropped elsewhere (merging case forms such as დედაჲ/დედა, as modern spelling does), უ → ვ between a consonant and ა/ე/ო (ქუეყანა → ქვეყანა; not word-initially, after a vowel or before ი); ჵ kept. Known merge: შუა "middle" / შვა "begat". An editor's restoration in brackets is a `supplement` span (#236), kept in the text |
| Old Irish (any source, #225) | Stored as the edition prints it: Latin letters with length marks, the dotted letters ḟ ṡ ṁ ṅ, æ/ǽ and the scribal signs ⁊ (ocus), ↄ (con), ɫ (nó). Keyword folding needs no new rule: length marks and dots drop and æ → e. Lenition written with h (fh) and with the dot (ḟ) are not folded together; no source mixes them yet. Latin words inside an Irish gloss stay in the gloss's text |
| Old English, Old High German, Old Saxon (any source, #563) | Stored as the edition prints it: Latin letters with æ ǽ ð þ (ƿ ȝ where a text has them), the *Heliand*'s ð đ ƀ, and the editions' length marks, circumflexes and accents; OHG and Old Saxon `uu` for w is kept. No conversion at ingest. ReA stores one token per row with punctuation as its own token, so an ingestor joins the tokens and puts the punctuation back on the word before it. Keyword folding (`patristica/textfold.py`, #563): marks drop, æ → e as in Latin, ð/đ → þ (Thorpe writes þæt/ðæt, the *Heliand* quað/quađ), ƀ → b (haƀda/habda), ƿ → w, ȝ/ᵹ/ʒ → g. Not folded: `th` onto þ (English *the*/*this* would match Old English *þe*/*þis*) and `uu` onto w (Latin *uua*/*uus* and OHG *uuas* would match English *wa*/*was*). The Tironian ⁊ (and) is punctuation to `fold()`, as in Old Irish |
| Literary Chinese (any source, #228, #648) | Stored in the characters each source has, traditional, with no conversion at ingest: zh.wikisource's diplomatic transcriptions keep the forms of the stone and the manuscripts (㬌 for 景, 夲 for 本, 礼 无 衆 䫟 躭 蹔), the Taishō (CBETA) its own, with its gaiji by their Unicode code point. Never converted between simplified and traditional. Keyword folding (`patristica/textfold.py` `_CJK_VARIANTS`): the variant characters (異體字) the editions write differently fold to the traditional standard form (眾 啟 跡 where two traditional forms compete), from a table built by comparing zh.wikisource with CBETA T2142–T2144 and CBETA's gaiji normalizations; characters that are words of their own (閒, 疋, 豊) are not folded. NFKD maps compatibility ideographs onto unified ones. Chinese has no spaces: derived verses, same-language alignment and edition projection treat each ideograph as a word (`patristica/versify.py`, `patristica/text_alignment.py`), and keyword search matches a phrase as a character sequence across punctuation (`patristica/keyword.py`) |
| OpenITI mARkdown (Arabic, #480) | `scripts/ingest/_openiti.py`: header and `#META#` lines, `# ` paragraphs and `~~` continuations joined, `### |`/`### ||` headings, `PageV01P012` page tags (closing their page) and `ms001` milestones dropped. Uncorrected Kraken OCR of bilingual editions: per page, the Arabic body runs from the first text line (≥ 70% Arabic-word tokens, at most one free number) to the apparatus (`1.` and a non-text line) or three noise lines; afterwards only clean lines (≥ 4 Arabic words, no number) are kept, since Kraken doesn't always keep reading order. Glued footnote numbers, free numbers, Latin debris and `*` are stripped; letters are never corrected |
| Born-digital PDF edition (Psalter of Demetrius, #337) | pdfplumber characters with positions: lines from baselines; margins, folio and line numbers and the apparatus dropped by position; the font's Private Use Area letters (и, ч, ѥ, ѧ, the titlo, …) mapped; line-end hyphens joined; half-verses (`13a`, `13b`) joined into verses; a few verses completed in the margin corrected by hand |

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
| `data/normalized/_works.jsonl` | yes | One line per normalized file: `{"path": …, "work": {…}}` with the full `Work` record (title, author, author_ids, dates, genre, language, tradition, license, provenance_url, edition, translation_of). Work metadata in plain git (`data/raw` is in git-lfs since #244); maintained by `scripts.normalize`. `scripts.validate` and `patristica/lookup.py` read it (lookup builds its ref-prefix index in memory from it; the old tracked `_index.json` was removed in #75) |
| `data/chunks/…` | no | Embedding-ready chunks: normalized chunks plus `context_before`/`context_after` (~50 tokens) and `translation_group_id` (Scripture only, versification-mapped). Regenerate with `uv run python -m scripts.chunk && uv run python -m scripts.link_translations` (~4 min) |

**For the Phase 2 loader**
- Load works from `_works.jsonl`, chunks from `data/chunks/` (regenerate first). Every pipeline step is idempotent and incremental.
- `authors` table: `Work.author` is a free-text string in each source's own convention (Latin forms for OGLT PL, English for CCEL; OGPG volumes may list several authors separated by `; `). Since #82, `Work.author_ids` holds canonical author ids from the author index, `patristica/data/authors.csv` (one row per person: slug, display name, aliases, birth/death/floruit with certainty, tradition, TLG/stoa/PTA ids, `pseudo_of`), plus `patristica/data/author_strings.csv` for anonymous, collective and multi-person strings. Load the `authors` table from the CSV (or the library's `authors.json`) and `works.author_ids` from `_works.jsonl`. Anonymous works have `author_ids: []`.
- `translation_of` (Work level) names the work a version was translated from. Ingestors set it for 310 English translations (CCEL ANF/NPNF and their carve-outs), straight to their Greek/Latin originals in First1KGreek, PTA, Perseus, OGLT PL or OGPG (#11). Since #153 it covers the ancient versions too, curated rather than set by ingestors (`patristica/translation_links.py`, applied by `scripts.normalize`): every Scripture work from `patristica/data/scripture_translation_of.csv` (per source and book; English Bibles included), and other works from the `translation_of` rows of `version_links.csv`. Links may chain (Coptic Genesis → LXX Genesis → Hebrew Genesis), and each names one designated edition of its source text (Hebrew → `oshb`, Greek Old Testament → `pta-lxx`, Greek New Testament → `sblgnt`; see `IMPLEMENTATION_PLAN.md` §2.4, "Translation history"). The field stays one work id: a secondary source (the Greek additions in Vulgate Esther) is recorded in the table's note; `translation_group_id` (chunk level) links parallel Scripture verses only. Work-level **version groups** (#178, `patristica/versions.py`) join every work with its other languages and editions: derived from `translation_of`, Scripture books across sources, shared CTS work ids (First1K/Perseus/CSEL, PTA), shared catalogue ids (`Work.external_ids`: PTA records TLG, CPG, BHG, Pinakes and other ids per work; First1K and Perseus carry the TLG id in the work id) and the curated `patristica/data/version_links.csv`; the library export carries each work's `version_group`.
- `out_of_period` is per chunk (rule in `patristica/period.py`): works composed entirely after the period are excluded; hybrid/straddling works (Typikon, CANTUS, OGPG PG 3/4/97/119/120, a few OGLT PL files) are kept with date-derived flags — filter at query time. When every author of a work has a known birth year in the author index, that year decides instead (`scripts.normalize`, #82): a late work by an author born before 1025 (e.g. Peter Damian, b. 1007) is not flagged.
- Licences vary per work (`Work.license`): most are public domain or CC-BY(-SA); LXX Rahlfs (eliranwong) and the PTA Peshitta OT are non-commercial.

**Open issues for the Phase 2 implementation** (chunk size normalization before embedding, [#2](https://github.com/jaspax/patristica/issues/2); embedding-model coverage of Coptic/Syriac/Armenian/Ge'ez/Gothic, [#3](https://github.com/jaspax/patristica/issues/3)) are described in `IMPLEMENTATION_PLAN.md` §2.5; licensing obligations for the public site in §3.5.

**Known caveats carried into Phase 2**: All OGPG text remains noisier than PTA/First1K for the same authors (see "Custom OCR pipeline" decision criteria); 879 works without author (mostly liturgical, council, anonymous apocrypha — honest anonymity); 211 OGLT PL works undated; one deliberate `period_flag_mismatch` warning (Ethiopic Synaxarion, hybrid liturgical); remaining text-quality warnings are listed in `data/validation_report.json`.

---

## 11. Known Gaps & Risks

| Gap | Mitigation |
|-----|-----------|
| No clean Ge'ez digital text; PDFs only | OCR with Ge'ez Tesseract model; flag low-confidence passages |
| SEDRA Peshitta is JS-native; no Python parser | Use Node.js subprocess or port the sedrajs data layer to Python |
| Typikon/Hudra out-of-period saint filtering requires scholarly judgment | Ingest all content; apply `out_of_period` flags in a second pass via `scripts/flag_liturgical.py` using `data/out_of_period_feasts.csv` (see §6 for full design). Default is inclusion when uncertain. |
| TLG and modern *Patrologia Orientalis* volumes behind paywall | Defer; seek institutional access. Note: PO volumes from 1904 to c.1930 (roughly PO 1–22) are public domain and scanned on archive.org, but need OCR (bilingual pages, Oriental scripts) — see §12 "Broader Non-Chalcedonian coverage" |
| Migne PG OCR quality highly variable | Use Open PG GitHub (already OCR'd); supplement with PTA where critical editions exist |
| OGLT PL attribution | The 502 anonymous split files are resolved via `scripts/ingest/data/oglt_pl_index.csv`. Remaining: header-attributed works carry volume-level (often wrong) author/title — M8 item; a few kept works are hybrids (PL8_4 Donation of Constantine + Armenian Letter of Concord; PL66_7 with an Alberic of Monte Cassino sermon; PL66_1 Rule with Martène commentary) that cannot be split per chunk. A split file holding several whole works can be cut into works by *part rows* (`{stem}/{part}` with `keep_refs`, #306): the Dionysiana (`PL67_11_CO`) is one part per council plus the African Code |
| CCEL/OGPG `Work.title` is set to collection/volume name, not individual work title | OGPG: split volumes (see "Patrologia Graeca: columns, refs and works") have work titles; the rest keep "Works in PG Vol. N". Currently `Work.title = "ANTE-NICENE FATHERS"` or `"Patrologia Graeca Vol. 1"` for most works in these collections. Tracked in [#10](https://github.com/jaspax/patristica/issues/10): replace with the actual work title; move collection identity to `Work.edition`. Until fixed, the lookup tool and any Phase 3 UI will surface collection names instead of work titles as the primary label. |
| Gallican/Mozarabic liturgy sources are 19th-century editions (may contain editorial additions) | Document edition metadata; flag as `edition_date: 1855` etc. |
| `WEB.csv` does not exist in scrollmapper/bible_databases | Use eBible.org USFM (`engwebp_usfm.zip`) — already implemented |
| SBLGNT is NOT OSIS XML — uses Logos custom format | Custom parser implemented in `sblgnt.py`; `parse_osis` will not work for it |
| LXX Rahlfs (eliranwong repo) has CCAT user-declaration requirement | Non-commercial only; word CSV is 3-column, verse index is start-only — see `lxx_rahlfs.py` |
| ASV from scrollmapper is only 48/66 books | Resolved: `data/raw/asv/` now has all 66 books |
| `beta2unicode` package does not exist on PyPI | Betacode conversion for any CCAT-sourced text (Tier 2) needs a custom solution at ingest time |
| Some CCEL ANF/NPNF translations have no `translation_of` | 310 English works are linked (#11; tables `_ORIGINALS` in `anf_works.py`/`npnf_works.py`, plus `translation_of` in the `ecumenical.py` and `syriac_documents.py` tables). The rest have no original in the corpus (Latin: #77; apocrypha and martyr acts: #78; Syriac/Armenian: #79; Arabic: #80; councils: #22; Greek liturgies: #42), or only one inside a multi-author or missing OGPG range (#81, #94, #149); reasons for the near misses are in each table's `_UNLINKED`. |
| First1KGreek/Perseus TEI headers have no composition dates; both repos are mostly classical pagan literature | The −50 CE / late-date filters never fired (every work was `uncertain`), so ~1,700 classical works (Plutarch, Galen, Cicero, …), works after the period (Anna Comnena, Zonaras) and French/German translations tagged `grc` were ingested. Fixed by an author-ID allowlist in `scripts/ingest/_cts_scope.py` (Christian/Jewish first-millennium literature, plus Procopius) and strict edition-suffix language matching; ingestors prune previously written out-of-scope files. NT (`tlg0031`) and LXX (`tlg0527`) excluded as covered by scripture ingestors. Pagan authors writing about Christians (Julian, etc.) are a possible future expansion. |
| arak29.org (Armenian) restarts verse numbering mid-chapter and has label typos | Mapped onto LXX versification via `_RESTART_RULES` in `armenian.py` (Ps 9 / 113 continue numbering, Ps 151 split out of the Ps 150 page, Prov 24:22a–e, Armenian-only Song 8:15–20); Exod 39 label typo fixed via `_LABEL_TYPOS`; Sirach's scrambled partial verses get letter suffixes (`Sir.16.13b`). Ref dedup across First1K/Perseus/PTA/OGLT PL now uses the shared `_common.dedupe_refs`. |
| Perseus Latin repo contains `.tracking.json` files from the CTS system | Repos stored under `data/raw/_repos/` (not `data/raw/perseus/`) to prevent catalog and normalize.py from treating them as source files. Do not move repos back into the source directory. |
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

