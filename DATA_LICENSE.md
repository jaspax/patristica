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
  include the text, on the terms recorded under "Used with permission" below
  (so far: non-commercial use, with attribution). The permission is Patristica's
  only and is not a licence for others: anyone else who wants to reuse the text,
  including from Patristica's data, needs the rights holder's own permission.
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

#### Hudra (`hudra`)

- **Texts:** the transcriptions on [hudra.day](https://hudra.day) of *The Hudra
  of the Assyrian Church of the East*, Vol. I (Thoma Darmo ed., Thrissur 1960)
  and the *Taksa d'Raze*, Editio Typica (2003).
- **Granted by:** the maintainer of hudra.day (Hendo Academy), on 2026-10-24, in
  reply to Patristica's request of 2026-10-12. The request described Patristica
  as a non-commercial library, free to use, and asked to include the Syriac
  texts on hudra.day. The reply: *"Yes, I would be happy if you can include
  them - please feel free to use anything you find on the site."* The project
  owner keeps the correspondence.
- **Covers:** including the texts in Patristica's library, reader and search,
  with our machine translations and embeddings of them.
- **Conditions:** non-commercial use, and attribution to hudra.day (Hendo
  Academy). Each work's edition line reads "transcription on hudra.day (Hendo
  Academy), used with permission" and links to the book's page on hudra.day; the
  reader and the `/sources` page show both.
- **Not transferable:** this is not a CC BY-NC licence. It was given to
  Patristica only, so anyone reusing Patristica's data needs their own
  permission from hudra.day for these texts.

hudra.day's own terms grant personal viewing only (#32); this permission is
what lets Patristica include the texts.

### Non-commercial material

The non-commercial texts mean that **Patristica as a whole may only be used and
served non-commercially**: no ads, paid tiers or API fees. If that ever changes,
remove or replace those texts first. That includes the Hudra texts, which are
used with permission for non-commercial use (`used-with-permission`). For the Septuagint, `pta-lxx` is a
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
