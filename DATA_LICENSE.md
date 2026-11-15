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
- **CC BY-SA 3.0** (Unported): stays CC BY-SA 3.0. One Coptic Scriptorium
  work, the Canons of Apa Johannes (#382).
- **CC BY-NC 4.0, CC BY-NC-SA 4.0 and CC BY-NC-SA 3.0**: non-commercial use
  only. CC BY-NC-SA 3.0 (Unported) is one PTA edition (#366) and the Referenzkorpus
  Altdeutsch (#567), whose corpus header reads "Open Source Projekt, CC-BY-NC-SA 3.0.";
  each `rea` work's `edition` credits ReA 1.2 (Humboldt-Universität zu Berlin et al.)
  and the printed edition it follows.
- **Custom terms** (`academic-noncommercial`): the source's own terms apply.
- **`used-with-permission`**: the rights holder gave Patristica permission to
  include the text, on the terms recorded under "Used with permission" below
  (so far: non-commercial use, with attribution). The permission is Patristica's
  only and is not a licence for others: anyone else who wants to reuse the text,
  including from Patristica's data, needs the rights holder's own permission.
- **`unknown`**: not cleared for redistribution. These are being verified (#32)
  and must be excluded from public distribution until then.

The corpus breaks down as follows (late October 2026, by chunks):

| Licence | Share | Sources |
|---|---:|---|
| CC BY-SA 4.0 | 51% | Patrologia Latina (OGL), CSEL, First Thousand Years of Greek, most of the Patristic Text Archive, Perseus, PTA Septuagint, Ge'ez Bible, Coptic Scriptorium's Mercurius, the Old Georgian texts on Georgian Wikisource |
| Public domain | 42% | OGPG (Migne), NPNF/ANF and McClure and Feltoe's Etheria (CCEL), CANTUS, KJV, ASV, WEB, Clementine Vulgate, Zohrab Armenian Bible, Sahidic NT, older liturgical editions, the Christian Arabic texts on tertullian.org with their English translations (dedicated to the public domain by Roger Pearse), Wither's Nemesius (1636; EEBO-TCP keyboarding dedicated CC0), English translations from the Internet Sacred Text Archive (Charles 1917, Terry 1899), the Library of the Fathers' *Morals on the Book of Job* (1844–50), A. J. Mason's Pseudo-Macarius (English Wikisource) |
| CC BY 4.0 | 5% | Digital Syriac Corpus, Open Scriptures Hebrew Bible, most of Coptic Scriptorium, parts of PTA, CCMH |
| CC BY-NC 4.0 | 1.5% | CURSUS, PTA Peshitta |
| CC BY-NC-SA 4.0 | 0.5% | Septuagint (Rahlfs, eliranwong; with a CCAT user declaration), four Coptic Scriptorium saints' Lives (Aphou, Longinus and Lucius, Paul of Tamma, Phib), TOROT Old Church Slavonic (Psalterium Sinaiticum, Kiev Missal, Euchologium, Chrabr), the Old Irish *Félire Óengusso* (Gloss Corpus, P. Moran), the Old Georgian texts of TITUS (#514; see "Licences stated in correspondence") |
| Academic, non-commercial | 0.3% | SBL Greek New Testament, Wulfila Gothic Bible, English translations from the Internet Medieval Sourcebook (Hill 1913, Brehaut 1912 and 1916: public-domain translations, but the Sourcebook and Badke's PDF claim copyright in "the specific electronic form" with non-commercial permission only, so they follow those terms; #696) |
| CC BY-NC-SA 3.0 | <0.1% | PTA's Anonymus of Cyzicus, *Historia ecclesiastica* (`pta/pta0036/pta001/pta-grc1`), the Referenzkorpus Altdeutsch (Old High German and Old Saxon, #567) |
| Used with permission | <0.1% | Hudra and Taksa d'Raze (hudra.day, Hendo Academy; 2 works), CELT's Old Irish texts (University College Cork; 48 works) |
| CC BY-SA 3.0 | <0.1% | Coptic Scriptorium's Canons of Apa Johannes |

Each work's licence is read from the source's own per-file statement where
it has one: PTA's `<licence @target>` URL (#366) and the `license` in each
Coptic Scriptorium document's metadata header, the most restrictive over a
work's documents (#382).

**Public domain in the United States only.** Patristica is hosted in the United
States, and `public_domain` means public domain there. One source is not yet
public domain everywhere: A. C. Moule's English translations of the Jingjiao
texts in *Christians in China before the Year 1550* (London: SPCK, 1930;
`moule-1930`, #654) were published in 1930 and so entered the US public domain
on 1 January 2026, but Moule died in 1957, so the book is in copyright in the
United Kingdom (and other life-plus-70 countries) until the end of 2027. The
owner decided on 2026-11-12 to publish it from the US. Anyone reusing these
works outside the United States should check their own country's term.

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

#### CELT Old Irish texts (`celt`)

- **Texts:** the Old and early Middle Irish religious texts of CELT, the Corpus
  of Electronic Texts (University College Cork, https://celt.ucc.ie/), listed
  by CELT id in the request (#541): the Félire Óengusso, Bethu Brigte, Betha
  Adamnáin, Saltair na Rann, the rules, the tracts, the Vision of Laisrén, Baile
  Bricín, the Irish Bede and the religious poems, with CELT's English
  translations of Bethu Brigte and the Vision of Laisrén. CELT's pages say
  "Available with prior consent of the CELT programme for purposes of academic
  research and teaching only".
- **Granted by:** the CELT programme, on 2026-11-12, in reply to Patristica's
  request of November 2026 (#542). The request described Patristica as a free,
  non-commercial library and asked to show the listed texts in its reader and
  make them searchable across the original languages and English, with credit
  to CELT and to each printed edition and a link to the CELT page. The reply:
  *"Permission is granted for the texts that you have listed, in the manner you
  outlined, for your non-commercial Patristica project."* The project owner
  keeps the correspondence.
- **Covers:** including the listed texts in Patristica's library, reader and
  search, with our machine translations and embeddings of them.
- **Conditions:** non-commercial use; attribution to CELT (University College
  Cork) and the printed edition, with a link to the text's CELT page. Each
  work's edition line reads "CELT {id} (University College Cork), from {printed
  edition}, used with permission" and its source link is the CELT page. As the
  request undertook, the texts are not offered as a downloadable dataset, and
  any text is removed at CELT's request.
- **Not transferable:** like the Hudra's, this permission is Patristica's only,
  not a licence: anyone reusing Patristica's data needs CELT's own consent for
  these texts.

### Licences stated in correspondence

#### TITUS Old Georgian texts (`titus-*`)

- **Texts:** the Old Georgian texts of TITUS, *Thesaurus Indogermanischer
  Text- und Sprachmaterialien*, ed. Jost Gippert, University of Frankfurt
  (https://titus.uni-frankfurt.de/): Bible recensions and lectionaries,
  hagiography, the Shatberdi codex, liturgies, chronicles and translations of
  Greek Fathers (#514, #515, #516, #517).
- **Stated by:** the editor of TITUS, on 2026-11-03, in reply to Patristica's
  request. TITUS's pages say "No parts of this document may be republished in
  any form without prior permission by the copyright holder"; the reply:
  *"In principle, the TITUS texts can be used for non-commercial purposes on a
  CC-BY-NC-SA basis, even though this is not stated explicitly (the CC types
  did not yet exist when we started in the 1980s)."* The project owner keeps
  the correspondence.
- **Licence:** CC BY-NC-SA (`cc-by-nc-sa-4.0`; the reply names no version, so
  we use the current one). Unlike the Hudra's, this is a licence for anyone,
  not a permission for Patristica only.
- **Attribution:** the editor asked that the printed editions' authors and
  publishers be named as TITUS names them, and TITUS cited as above. Each work's edition line reads "TITUS (Thesaurus
  Indogermanischer Text- und Sprachmaterialien, ed. …, University of
  Frankfurt), after {printed edition}" and links to the TITUS page.
- The printed editions published in Georgia in Soviet times are, in the
  editor's words, free, and many are online as PDFs at the National
  Parliamentary Library of Georgia. He also pointed to TITUS's new site
  (titus2.uni-frankfurt.de, Georgian not yet moved) and the Georgian National
  Corpus (gnc.gov.ge), which includes the material with some gaps.

### Non-commercial material

The non-commercial texts mean that **Patristica as a whole may only be used and
served non-commercially**: no ads, paid tiers or API fees. If that ever changes,
remove or replace those texts first. That includes the Hudra and CELT texts, which are
used with permission for non-commercial use (`used-with-permission`), and the TITUS Old Georgian texts (CC BY-NC-SA). For the Septuagint, `pta-lxx` is a
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
