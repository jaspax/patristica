# Data licensing

Patristica's **code** is under the MIT License (`LICENSE`). The **texts** are not:
each text keeps the licence of the source it came from. This file explains how
the pieces fit together. It is a summary, not legal advice; the upstream licence
is always the authority.

## Texts: the source licence passes through

Every work in the corpus records its licence in `Work.license`, with provenance
in `Work.provenance_url` and `Work.edition` (see `patristica/models.py` and
`data/normalized/_works.jsonl`). The licence applies to that work everywhere we
distribute it: the files under `data/`, the static library export
(`scripts/export_library.py`), the web app and any future API.

Changes we make to a text are distributed under **that text's licence**. This
covers OCR and markup cleanup, chunking, canonical references, dating and
period flags. In particular:

- **Public domain**: stays public domain.
- **CC BY 4.0**: stays CC BY 4.0. Attribution is required, and we add no further
  restrictions.
- **CC BY-SA 4.0**: stays CC BY-SA 4.0. Modified versions must keep the same
  licence (ShareAlike).
- **CC BY-NC 4.0 and CC BY-NC-SA 4.0**: non-commercial use only.
- **Custom terms** (`academic-noncommercial`): the source's own terms apply.
- **`used-with-permission`**: the rights holder gave Patristica permission to
  include the text. The permission is ours, not a licence for others: anyone
  else who wants to reuse the text must ask the rights holder. Each grant is
  recorded under "Used with permission" below.
- **`unknown`**: not cleared for redistribution. These are being verified (#32)
  and must be excluded from public distribution until then.

The corpus breaks down as follows (October 2026, by chunks):

| Licence | Share | Sources |
|---|---:|---|
| Public domain | 46% | NPNF/ANF (CCEL), KJV, ASV, WEB, Clementine Vulgate, Zohrab Armenian Bible, Sahidic NT, OGPG (Migne), CANTUS, older liturgical editions |
| CC BY-SA 4.0 | 38% | Patristic Text Archive, First Thousand Years of Greek, Perseus, Patrologia Latina (OGL), Ge'ez Bible, PTA Septuagint |
| CC BY 4.0 | 7% | Open Scriptures Hebrew Bible, Coptic Scriptorium, parts of PTA |
| CC BY-NC 4.0 | 6% | PTA Peshitta, CURSUS |
| CC BY-NC-SA 4.0 | 2% | Septuagint (Rahlfs, eliranwong; with a CCAT user declaration) |
| Academic, non-commercial | 1% | SBL Greek New Testament, Wulfila Gothic Bible |
| Used with permission | <0.1% | Hudra and Taksa d'Raze (hudra.day, Hendo Academy; 2 works) |

The web app's **Sources & licences** page (`/sources`) lists every collection
with its licences, edition and source link. It is generated from the library
index, so it stays current as the corpus changes.

### Used with permission

| Collection | Granted by | Date | Covers | Conditions |
|---|---|---|---|---|
| `hudra`: *The Hudra of the Assyrian Church of the East*, Vol. I (Darmo, Thrissur 1960) and *Taksa d'Raze*, Editio Typica (2003) | Hendo Academy, for its transcriptions on [hudra.day](https://hudra.day) | 2026-10-25 | Including the transcriptions in Patristica: the library, the reader and search (with machine translations and embeddings made from them) | None recorded yet (to be confirmed) |

hudra.day's own terms grant personal viewing only (#32); this permission is
what lets Patristica include the texts. Each work credits the transcription
to hudra.day (Hendo Academy) in its edition line, and links to its page there.

### Non-commercial material

The non-commercial texts mean that **Patristica as a whole may only be used and
served non-commercially**: no ads, paid tiers or API fees. If that ever changes,
remove or replace those texts first. For the Septuagint, `pta-lxx` is a
CC BY-SA alternative to Rahlfs.

If you reuse the data, filter on `Work.license` to keep only what your use permits.

## Our own data: CC0

Material we created ourselves, separate from any text, is dedicated to the
public domain under [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/).
This covers catalogue metadata (titles, authors, dates and attributions we
assigned), collection labels (`patristica/sources.py`), the structure of the
library export, and our own attribution tables such as
`scripts/ingest/data/oglt_pl_index.csv`.

## Bundled third-party and derived data

- `patristica/data/versification/` contains versification mappings under
  CC BY-SA 4.0. See `ATTRIBUTION.md` in that directory.
- `scripts/ingest/data/greek_wordforms.tsv.gz` is a word-form list derived
  from CC BY-SA texts (First1KGreek, PTA, Perseus, PTA Septuagint) and the SBLGNT.
  It is distributed under CC BY-SA 4.0, and Rahlfs is excluded.

## Attribution

When you show or redistribute a text, credit it the way the reader does: the
title and author, the collection and edition, the licence, and a link to the
source (`Work.provenance_url`).
