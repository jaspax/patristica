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
