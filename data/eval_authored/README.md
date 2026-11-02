# Authored eval queries

Paraphrase and topical queries for the embedding eval (#3), loaded by
`scripts.embed_eval.run` (all `*.jsonl` here). Each line names a
`target_chunk_id`. `scripts.embed_eval.build` always keeps these targets in
the eval corpus.

- `drafted.jsonl`: drafted by Claude on 2026-10-12, **not yet reviewed**.
  There are 213 targets: 20 per language/origin group (some Latin, Greek and
  Coptic targets were skipped because they were headings or unreadable
  fragments), each with one English paraphrase and one English topical query.
  Each paraphrase was written from the original-language text, not from an
  English translation in the corpus. `confidence` (high / medium) records how
  sure the drafter was of the reading, which matters most for Coptic and for
  OCR-damaged Greek.

Fields: `query_id`, `mode` (`paraphrase` | `topical`), `text`, `query_lang`,
`target_lang`, `origin` (`scripture` | `unique`), `target_chunk_id`,
`confidence`.

Ge'ez queries (35 targets: 20 Scripture, 15 Ge'ez-only) were added the same
day, after the eval set was extended with `build --extend gez`.

**Review (#87, 2026-10-12).** GPT-6.1 Sol reviewed every target's queries
against the original (`scripts.embed_eval.review`). It rated paraphrase
accuracy, ignoring partial coverage, and topical relevance and specificity.
A bigram-overlap check flagged Scripture paraphrases that echo an English
Bible. Each query now carries:
- `review`: `pass` (345), `corrected` (131) or `flagged` (20, overlap only);
- `reviewed_by`;
- for corrected queries, the original draft in `drafted_text`.

Rerunning the eval with all, passing-only and corrected queries left every
conclusion unchanged: no language cell moved by 0.20 or more.

**Church Slavonic (#336).** `chu.jsonl`: drafted by Claude on 2026-10-29
from the Slavonic text (CCMH transliterations), **not yet reviewed**: 40
targets, 20 Gospel verses (Marianus, Zographensis, Assemanianus, Savvina) and
20 Slavonic-only passages (18 Codex Suprasliensis texts, the Vitae of
Constantine and Methodius), each with one English paraphrase and one English
topical query. The targets are the first of each origin in the one-language
eval set `scripts.embed_eval.langset chu` (seed 0), skipping none.

Extended the same day for the second round (#336): 120 more targets, so
`chu.jsonl` now has 160 targets and 320 queries:
- **Scripture (80):** the four Gospel codices, plus the Psalterium Sinaiticum (TOROT) and the Psalter of Demetrius;
- **Slavonic-only (80):** Suprasliensis, the Vitae, Chrabr, the Euchologium and the Kiev Missal.

The new targets are the first of each origin in `langset chu` built with
those sources (#334, #337). Formulaic doxologies and two obscure fragments
were skipped. 39 targets are `medium` confidence, mostly fragmentary
Suprasliensis sentences.

**Review of `chu.jsonl` (#87 method, GPT-6.1 Sol, one pass, 2026-10-29).**
- 198 pass, 118 corrected (the draft kept in `drafted_text`), 4 flagged for overlap with an English Bible.
- Scripture paraphrases scored 4.91 accuracy on average, Slavonic-only 4.50.
- Rerunning retrieval on all, passing-only and corrected queries moved no cell by more than 0.06.

**Arabic (#483).** `arb.jsonl`: drafted by Claude on 2026-10-30 from the
Arabic text, never from the English versions in the corpus: 100 targets,
each with one English paraphrase and one English topical query. The targets
are every target of the one-language set `scripts.embed_eval.langset arb`
(seed 0), skipping none. There is no Arabic Scripture, so all of them are
`unique`:
- 54 from the six tertullian.org texts (`pearse-arabic`);
- 37 from the History of the Patriarchs (`openiti`, uncorrected OCR);
- 9 from al-Kindi's *Apology* (`openiti`).

31 targets are `medium` confidence, mostly OCR-damaged History of the
Patriarchs fragments.

**Review of `arb.jsonl` (#87 method, GPT-6.1 Sol, one pass, 2026-10-30).**
- 166 pass and 34 corrected (11 paraphrases, 23 topical queries; the draft kept in `drafted_text`).
- Paraphrase accuracy averaged 4.66 and topical relevance 4.62. Sol read 86 originals well and 14 partly.
- Rerunning retrieval on all, passing-only and corrected queries moved no cell by more than 0.05.

**Old Georgian (#529).** `oge.jsonl`: drafted by Claude on 2026-10-31 from
the Georgian text, never from an English version: 100 targets, each with one
English paraphrase and one English topical query. The targets are every
target of the one-language set `scripts.embed_eval.langset oge --scripture-per-lang 50
--unique-per-lang 50` (seed 0), skipping none, built on master plus the
unmerged TITUS hagiography (#521) and codices (#526):
- **Scripture (50):** 33 Oshki/Jerusalem OT verses, 9 Gospel verses (Khanmeti, Adishi, pre-Athonite, Athonite), 5 from Acts and the Epistles, 3 Psalms;
- **Georgian-only (50):** 18 from the TITUS translations (Basil's homilies, Climacus and their scholia), 17 hagiography, 6 Shatberdi codex, 5 chronicles (Kartlis Tskhovreba), 3 liturgy of St James, 1 Wikisource (*Conversion of Kartli*).

The lectionaries are left out of the unique pool (`EXCLUDED_UNIQUE_WORKS`):
they are Scripture pericopes. 20 targets are `medium` confidence, mostly
abbreviated or allusive prose.

**Review of `oge.jsonl` (#87 method, GPT-6.1 Sol, one pass, 2026-10-31).**
- 149 pass, 49 corrected (12 paraphrases, 37 topical queries, mostly as too narrow; the draft kept in `drafted_text`) and 2 flagged for overlap with an English Bible.
- Paraphrase accuracy averaged 4.66 and topical relevance 4.76. Sol read 90 originals well and 10 partly.

**Old Irish (#552).** `sga.jsonl`: drafted by Claude on 2026-11-01 from
the Irish text, never from an English version (the Würzburg glosses' Stokes
& Strachan English, CELT's Bethu Brigte and Laisrén translations): 80
targets, each with one English paraphrase and one English topical query.
There is no Old Irish Scripture, so every target is Irish-only. The targets
are every target of the one-language set `scripts.embed_eval.langset sga
--scripture-per-lang 0 --unique-per-lang 80 --min-target-chars 80` (seed 0),
skipping none, 20 from each pool of `UNIQUE_POOLS["sga"]`:
- **Würzburg glosses (20):** one or two per Pauline epistle. Most glosses are a few words, so targets need 80 characters (the shorter ones stay in the set as neighbours and distractors);
- **Félire Óengusso (20):** 10 from CELT's (Stokes) text and 10 from Gloss Corpus's diplomatic text, never the same day twice. The two editions are grouped by ref (`langset.WITNESS_GROUPS`), so either answers a query on the other;
- **CELT prose (20):** Apgitir Chrábaid, Baile Bricín, the Lives of Adamnán and Brigit, the sayings of Flann Fína, Cáin Eimíne Báin, Fursa's prayer, the tracts on sins, the Irish Bede, Molaisse, the Rule of Colum Cille, the Vision of Laisrén, the prophecy of Adamnán;
- **CELT verse (20):** one quatrain from each of 20 poems (Saltair na Rann among them).

The CELT texts are unpublished (`license: unknown`); only these English
queries are committed. 42 targets are `medium` confidence: verse and
glosses whose reading is uncertain.

**Review of `sga.jsonl` (#87 method, GPT-6.1 Sol, one pass, 2026-11-01).**
- 115 pass and 45 corrected (29 paraphrases, mostly a misread clause; 16 topical queries, 9 of them as too narrow; the draft kept in `drafted_text`).
- Paraphrase accuracy averaged 4.20 and topical relevance 4.61. Sol read 34 originals well and 46 partly: Old Irish verse and the diplomatic Félire are hard for it too.

**Old Saxon (#585).** `osx.jsonl`: drafted by Claude on 2026-11-02 from the
Old Saxon text (ReA 1.2, #567), never from an English version: 57 targets,
each with one English paraphrase and one English topical query. There is no
Old Saxon Scripture, so every target is `unique`. The targets are the
one-language set `scripts.embed_eval.langset osx --scripture-per-lang 0
--unique-per-lang 60` (seed 0), 20 from each pool of `UNIQUE_POOLS["osx"]`,
with three skipped:
- **Heliand (20):** one long line each, from 17 fitts (the census, the shepherds, the Magi, the baptism, the temptation, the Sermon on the Mount, Cana, the sower, the tares, Peter's confession, the rich man and Lazarus, Martha, the Last Judgement, the Last Supper, the arrest);
- **Genesis (19):** Cain and Abel, Enoch and the Antichrist, Abraham and Sodom. `AsGen.2.642` was skipped: it is the line after the target `AsGen.2.641`, in the same sentence;
- **Minor texts (18):** the Bede homily, the confession, the two baptismal vows and the Gernrode Psalm commentary. Skipped: the creed (`GB.1`), which is the same text as the target `KT.1.s4`, and `KT.1.s5`, which is mostly a Latin rubric.

A *Heliand* or *Genesis* unit is one verse line (44 characters on average,
#586), so the drafts described the sentence around the line. 5 targets are
`medium` confidence, 4 of them OCR-damaged Gernrode fragments.

**Review of `osx.jsonl` (#87 method, Claude Opus 5.5 via `--reviewer
local-opus`, one pass, 2026-11-02).** The owner allowed no paid API for this
eval, so the reviewer is the drafter's own model family, not an independent
vendor.
- 43 pass and 71 corrected (37 paraphrases, 34 topical queries; the draft kept in `drafted_text`). Almost every correction cuts a *Heliand* or *Genesis* query down to its one line: the reviewer counts words taken from the neighbouring lines as additions. 23 topical queries were rated too narrow, mostly because they named the Gospel scene.
- Paraphrase accuracy averaged 3.28 (Heliand 2.50, Genesis 2.68, minor texts 4.78), and topical relevance 3.86. Opus read 44 originals well and 13 partly.
- Rerunning retrieval moved native Voyage's paraphrase R@3 from 0.19 (drafts) to 0.33 (corrected) and 0.40 (the 20 passing). The decision is the same with every variant.
**Old English (#582).** `ang.jsonl`: drafted by Claude on 2026-11-02 from
the Old English text, never from Thorpe's English (`aelfric-ch-eng`): 80
targets, each with one English paraphrase and one English topical query.
There is no Old English Scripture in the corpus, so every target is
`unique`. The targets are every target of the one-language set
`scripts.embed_eval.langset ang --scripture-per-lang 0 --unique-per-lang 80
--min-target-chars 80` (seed 0), skipping none, 20 from each pool of
`UNIQUE_POOLS["ang"]`:
- **Religious narrative verse (20):** Genesis, Exodus, Daniel, Christ and Satan, Judith, Andreas, Elene, the Fates of the Apostles, the Dream of the Rood;
- **Exeter Book religious poems (20):** Christ I–III, Guthlac, the Phoenix, Juliana, Azarias, the Panther, the Whale, the Partridge, the Descent into Hell, Judgment Day I, Alms-Giving, Soul and Body II, Homiletic Fragment II;
- **Wisdom and elegy (20):** the Wanderer, the Seafarer, the Order of the World, Maxims I and II, the Fortunes and Gifts of Men, Precepts, Vainglory, the Riming Poem, Resignation, the Rune Poem, Solomon and Saturn, the Meters of Boethius;
- **Ælfric's Catholic Homilies I (20).**

Thorpe's English is a version of every homily, but the one-language set
holds no English (as for the Würzburg glosses), so a query can't be answered
by the English. 22 targets are `medium` confidence: verse whose syntax or
referent is uncertain out of context.

**Review of `ang.jsonl` (#87 method, local-opus, one pass, 2026-11-02).**
The owner allowed no paid API for this eval, so the reviewer was Claude Opus
5.5 on the Claude subscription (`review --reviewer local-opus`): the
drafter's own model, so less independent than Sol's reviews above.
- 143 pass and 17 corrected (5 paraphrases, misread clauses; 12 topical queries, 11 of them as too narrow; the draft kept in `drafted_text`).
- Paraphrase accuracy averaged 4.55 and topical relevance 4.72. Opus read 78 originals well and 2 partly.
- Rerunning retrieval on all, passing-only and corrected queries moved no cell by more than 0.04.


**Old High German (#584).** `goh.jsonl`: drafted by Claude on 2026-11-02
from the OHG text, never from an English or Latin version: 80 targets, each
with one English paraphrase and one English topical query. There is no OHG
Scripture in the corpus, so every target is `unique`. The targets are every
target of the one-language set `scripts.embed_eval.langset goh
--scripture-per-lang 0 --unique-per-lang 80` (seed 0), skipping none, 20 from
each pool of `UNIQUE_POOLS["goh"]`:
- **Otfrid's *Evangelienbuch* (20):** one long line each (the unit ReA gives), so most are a clause or two;
- **Notker's Psalter (20):** Notker weaves the Latin psalm text and some Latin terms into his German, so 18 of the 20 targets contain some Latin;
- **Tatian (20):** the OHG Gospel harmony;
- **minor texts (20):** one unit from each of 20 of the other works (the confessions, creeds and Lord's Prayer commentaries, *Muspilli*, the *Ludwigslied*, the *Georgslied*, the *Petruslied*, the Murbach Hymns, the Benedictine Rule, the Monsee fragments, Notker's *Cantica*, …).

35 targets are `medium` confidence, mostly Otfrid lines read without their context.

**Review of `goh.jsonl` (#87 method, Claude Opus 5.5 on `local-opus`, one pass, 2026-11-02).**
The owner allowed no paid API but Voyage for this eval, so the reviewer is
Opus on the Claude subscription (`review --reviewer local-opus`) instead of
GPT-6.1 Sol. It is the drafter's model family, so this review is not
independent.
- 134 pass and 26 corrected (7 paraphrases, mostly a misread word such as *gilári* "lodging", *gebînot* "tormented", *ríetun* "took counsel"; 19 topical queries, 18 of them as too narrow; the draft kept in `drafted_text`).
- Paraphrase accuracy averaged 4.65 and topical relevance 4.61. Opus read 75 originals well and 5 partly.
- Rerunning retrieval on all, passing-only and corrected queries moved no cell by more than 0.02.
