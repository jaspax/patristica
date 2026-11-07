# Adding a language

The checklist for bringing a new language into the corpus (#293). Work through it before the first ingest of a language and again in the PR that adds it. Every step names the file or symbol to change and why.

**Keep this file language-neutral (#475).** It holds only what applies to every language. A language's own choices, measurements and notes go on its umbrella issue (the "Add … texts" issue with its `lang:` label): candidate codes and scripts while it is planned, and the **decision record** (template at the end) as a comment once it is added. Don't add a language's details here, not even as an example; if one teaches something general, write the general rule here and leave the details on the issue. Planned languages: `gh issue list --label "phase-1: data" --search '"none in the corpus" in:title'`.

**Cost legend.** Each step is marked:

- **free**: no data changes, and nothing goes stale.
- **rebuild**: a CPU-only re-run of a step (normalize, align, build_index), usually over every work. It costs minutes, not money, but the result must be committed.
- **paid**: API calls, made only by `scripts.pipeline --pay` (#248).
- **frozen**: once data exists, changing the value renumbers or invalidates stored data.

## 1. Identity

- [ ] **Pick the ISO 639-3 code** and record why in the decision record. Prefer the code for the historical stage over the modern language, keep it distinct from `eng` (the translation language), and note the BCP 47 tag, which may differ. The code is stored in every chunk and is a URL filter value (`?language=`), so it is **frozen** once data exists.
- [ ] **`Language` in `patristica/models.py`.** Add the code. **Free:** controlled vocabularies are left out of every code hash (`fingerprint.VOCABULARIES`, #262), so no ingest stamp or normalize/align hash changes.
- [ ] **`Tradition` in `patristica/models.py`**, if the language needs its own value rather than an existing tradition or the writer's confession. **Free**, for the same reason. The author index accepts it automatically (`AUTHOR_TRADITIONS` in `patristica/authors.py`). Add its display name to `TRADITIONS` in `web/src/lib/format.ts`.
- [ ] **`VALID_LANGUAGES` and `SCRIPT_RANGES` in `scripts/validate.py`.** `VALID_LANGUAGES` duplicates `Language`, so validate flags the new code until it is added (#294). Add the script's Unicode block(s) to `SCRIPT_RANGES` so validate catches chunks in the wrong script or mojibake. Changing validate makes the CI `pipeline` job run it.
- [ ] **`tests/test_models.py`**: add the code to the loop that checks every language is accepted.
- [ ] **Existing multi-language ingestors** may already skip texts in the language. `scripts/ingest/pta.py` `_LANG_MAP` (and `_LANG_TRADITION`) drops unmapped `xml:lang` values at DEBUG level. Check the cached clone for them first. Mapping a new tag changes that ingestor's code hash, so it needs a `--force` re-ingest (#130).
- [ ] **GitHub label.** Create the `lang:` label if it doesn't exist yet. When the language lands, drop "not yet in the corpus" from its description (`gh label edit "lang: {name}" --description "{Language} ({code})"`).

## 2. Script, fonts and keyword folding

- [ ] **Decide the stored script** and record it. Store what the source has, in Unicode. Convert at ingest only when there is a reason: the language is written in several scripts and readers of one can't read the other, or sources disagree on script or transliteration. Measure the cl100k tokens of the same verse in each candidate script: a script that costs several times more raises `VERSE_TOKENS` and the embed cost. A shared conversion goes in a helper under `scripts/ingest/`, used by every ingestor of the language, and `validate` should count the other script as wrong (`SCRIPT_RANGES`).
- [ ] **`web/src/lib/lang.ts`.** Add the code to `LanguageCode` and an entry to `LANGUAGES`: the BCP 47 `lang`, the display `name`, and `dir` (`rtl` for a right-to-left script). `lang.test.ts` covers RTL; extend it.
- [ ] **`web/src/app/fonts.ts`.** Add a font, usually a Noto font through `next/font/google` with `preload: false`, and add it to `fontVariables`. Check its coverage against every code point the sources use (extended blocks, combining marks, punctuation), not just the base block. Latin-script languages use the body font; check that their extra letters render.
  - **Combining marks:** a browser draws a letter and its marks from one font file. Google serves some fonts in `unicode-range` slices, and a cluster whose base and marks fall in different slices renders as tofu. Render the sources' real clusters, not single code points; if the slices split them, self-host the whole font with a fallback, as the Slavonic fonts do (`web/scripts/slavonic-fonts.py`, #371).
- [ ] **`web/src/app/globals.css`.** Add a `:lang()` rule under "Script fonts by language", using the BCP 47 `lang` value from `lang.ts`, not the ISO 639-3 code.
- [ ] **Reader smoke test** (`npm run dev` with a local export; see CLAUDE.md "Library browser"). Open one work in light and dark themes and check:
  - combining marks render;
  - RTL layout and paragraph numbers work (Hebrew and Syriac already do);
  - the parallel reader shows the language next to its original.
- [ ] **`patristica/textfold.py`.** `fold()` is language-independent: it applies NFKD, drops Mn/Me/Cf marks, casefolds and evens out Latin spelling, and it has per-script rules for scripts already in the corpus. Check what it does to the sources' text (`fold()` on sample words) and record what is and isn't folded. Compare editions and witnesses of the language to find the letters they write differently for one sound, and add rules only where they really differ: an over-eager fold makes different words match. Check the effect on the existing corpus (chunks of other languages may contain the script). Then:
  - add cases to `tests/test_textfold.py`;
  - keep `fold_spans()` consistent;
  - bump `FOLD_VERSION` in `patristica/keyword.py`.

  This is a **rebuild**. `textfold` is in the normalize closure (via `patristica.authors`), so every work is re-normalized. The `FOLD_VERSION` bump makes `build_index` fold every chunk again locally (a few minutes for the corpus) and rewrite `text_folded` only where it changed (#607): no vectors, and quoted search keeps the old folding until a work is done. Batch fold changes for a language into one PR.

## 3. Search quality: measure, then decide

Voyage `voyage-4-large` reaches Greek, Latin and Hebrew natively. Syriac, Coptic, Armenian and Ge'ez needed English translation vectors (#3, #84; `docs/embedding-eval.md`). Measure every new language the same way; don't assume. Note the expected result on the language's issue, then measure anyway.

- [ ] **Build the eval data** from normalized data (it needs the language's first source ingested):
  - `scripts.chunk` and `scripts.link_translations`;
  - then `uv run python -m scripts.embed_eval.build --extend {code}`. It appends targets without disturbing the existing set (`select.extend`). Add the code to `TARGET_LANGS` in `scripts/embed_eval/select.py`, and list language-unique works in `UNIQUE_WORKS` if the metadata rule picks the wrong ones.
- [ ] **Author queries** in `data/eval_authored/`: an English paraphrase and an English topical query for about 20 targets per origin (Scripture, unique).
  - Draft each from the original text, not from an English translation in the corpus.
  - Have them reviewed with `scripts.embed_eval.review` (#87).
  - Record the date and reviewer in `data/eval_authored/README.md`.
- [ ] **Run the eval:** `scripts.embed_eval.run --retriever bm25 --retriever dense:voyage/voyage-4-large`, then `scripts.embed_eval.report`. Compare the paraphrase R@3 and topical R@100 cells with Greek and Latin. **Paid**: a few dollars of Voyage calls, cached in `data/eval/embeddings/`.
- [ ] **Decide on translation vectors.** If native retrieval is near the Greek/Latin level (#84's bar: paraphrase R@3 ≈ 0.95, topical R@100 ≈ 0.9), don't add them. Otherwise:
  - Run the translation quality eval with `scripts.embed_eval.translate quality --langs {code}` (#84's method: blind judging by two vendors, fidelity on a 1–5 scale, hallucination count, $/passage). Spot-check some translations yourself.
  - Rerun retrieval with `dense:voyage/voyage-4-large+tr:gpt-6.1-sol` to confirm the gain.
  - Enrolling the language for the quality eval needs an entry in `LANGUAGE_NAMES`, which a test ties to production (#295).
  - **Without paid APIs** (#582): `review --reviewer local-opus`, `translate quality --translators local-opus --judges local-opus` and `scripts.translate --model local-opus` run on the Claude subscription. The review is then by the drafter's own model, and fidelity is self-judged only; say so in the record.
- [ ] **Record it.** Add the language's columns to the matrices in `docs/embedding-eval.md`, and the numbers and the decision to the decision record.
- [ ] **If translation vectors are needed**, enroll the language:
  - add it to `TRANSLATED_LANGUAGES` in `patristica/translations.py`;
  - add the prompt name to `LANGUAGE_NAMES` in `scripts/embed_eval/translate.py` (the language's English name; `tests/test_embed.py` checks the two sets match).

  Then `scripts.translate` translates the language's units and `scripts.embed` adds a `KIND_TRANSLATION` vector for each.

  Costs:
  - **Paid:** about $0.0014 per unit for Sol bulk translation (`COST_PER_CHUNK` in `scripts/translate.py`), plus the translation's embedding. In an interactive session, translate with `--model local-opus` instead, on the Claude subscription's usage (`docs/translation-backends.md`).
  - **No corpus-wide rebuild:** `TRANSLATED_LANGUAGES` is left out of the aligner's code hash (#336). Each group's inputs hash records the vectors its members are aligned on, so only the groups whose members gain translation vectors are re-aligned, in the pipeline's align step after embed (no API calls).
  - Translate before embed: `scripts.status` lists the pending translations and their cost.

  Enrolling later re-translates nothing, but it adds a vector per unit. Decide before the paid run if you can.

## 4. Sources and metadata

- [ ] **Licence.** Set `Work.license` in the ingestor from the source's actual terms.
  - Use `unknown` only while the terms are being checked. `EXCLUDED_LICENSES` in `patristica/corpus.py` keeps such works out of translate, embed, search and the public library (`scripts/upload_library.py` re-exports it).
  - A new licence id goes in `License` (**free**), in `LICENSES` in `web/src/lib/format.ts`, and, if it is non-commercial, in `NON_COMMERCIAL` in `web/src/lib/sources.ts`.
  - Record permissions and unusual terms in `DATA_LICENSE.md`.
- [ ] **Period.** Apply `work_in_period()` / `is_out_of_period()` from `patristica/period.py`, never hard-coded years. Date by composition, not manuscript. Hybrid collections keep the work and flag chunks.
- [ ] **Source label.** Add every new `source_id` to `SOURCE_LABELS` in `patristica/sources.py` (`tests/test_export_library.py`). The `/sources` page then lists it with its licence.
- [ ] **Authors.** Add every author spelling to `patristica/data/authors.csv` as an alias of an existing person, or as a new person row with dates, sorted by id. Anonymous, collective or multi-person strings go in `patristica/data/author_strings.csv` with a reason. Otherwise `scripts.normalize` raises `UnknownAuthorError`. Add transliterated and English forms as aliases, since the library's text filter matches aliases.
- [ ] **Genre.** Set the ingestor's default genre and add per-work exceptions to `patristica/data/genre_overrides.csv` (see CLAUDE.md "Genre values").
- [ ] **Catalogue ids.** If the source records TLG, CPG or BHG ids (or the language's own CPG-like clavis), store them in `Work.external_ids`. The version-group crosswalk links on them.
- [ ] **Ingestor hygiene:**
  - Implement the `ingest()` contract.
  - Download through `_common.download_file` or cached clones, so the source can be regenerated offline (#215).
  - Log dropped works at ERROR, so a failed forced run isn't stamped (#130).
  - Raw and normalized work files are git-lfs objects (#244). After an ingest that adds or updates a clone under `data/raw/_repos/`, run `uv run python -m scripts.data pack`.

## 5. Structure

- [ ] **Canonical refs.** Use dot-separated refs in the source's native numbering. Add a section to `DATA_COLLECTION_PLAN.md` §5 if the scheme is new.
- [ ] **Scripture versification.** Add each Scripture source to `SOURCE_SCHEMES` in `patristica/versification.py` (`org`, `eng`, `lxx` or `vul`). Pick the scheme by comparing per-chapter verse counts with the schemes' `maxVerses`. Put books or chapters that follow another scheme in `BOOK_SCHEME_OVERRIDES` / `CHAPTER_SCHEME_OVERRIDES`. Without an entry, linking raises `VersificationError`.
  - The registries are left out of the aligner's hash, so only that source's version groups go stale.
  - Add a row per source to `patristica/data/scripture_translation_of.csv` (`tests/test_translation_of.py` requires one for every source in `SOURCE_SCHEMES`).
- [ ] **`VERSE_TOKENS` in `patristica/versify.py`** (**frozen**). It needs a value for the language, or normalize raises `ValueError` on the first long chunk. The value is the mean cl100k tokens per Scripture verse in that language. Measure it on the language's first Scripture source, in the script you store. With no Scripture, use the mean over a verse-numbered text and record how in the decision record. After it is set, a change renumbers every derived verse of the language and invalidates their translations.
  - Adding the key is a **rebuild**: `versify` is in the normalize hash, so every work is re-normalized, unchanged, and `data/normalized/_fingerprint.json` must be committed.
- [ ] **Punctuation in `patristica/versify.py`** (**frozen**, like `VERSE_TOKENS`). Add the language to `_SENTENCE_MARKS`, `_CLAUSE_MARKS` and `_COMMA_MARKS` when the defaults (`.!?`, `;:··—…`, `,،`) are wrong. Count the marks the sources actually use and what they do (a `;` may be a question mark, a raised dot a clause or sentence end, a multi-dot sign a section end). Check the result on a long text: the mean derived verse should be about one verse and end at a stop. Also check word separators in `_ATOM_RE` (as for Ge'ez `፡`); a stop with no space after it doesn't break, so ingestors keep a space after punctuation.
- [ ] **Derived verses anchored on the original (#292, #304).** New sources whose works translate an original already in the corpus are enrolled: a row in `patristica/data/anchored_sources.csv` (`source_id,language,reason`), in the PR that adds the source; for a new language in an existing source, a row with that `language`, so the source's published works keep their derived verses. Their derived verses follow the original's boundaries within each source paragraph (`scripts.anchor`, from Voyage vectors; `docs/anchored-derived-verses.md`), and `VERSE_TOKENS` is only the fallback. This is the go-forward standard, so their works never need re-splitting (or re-translating) when #200 migrates the rest.
  - Set `translation_of` first (section 6): it is the anchor. A work whose original isn't in the corpus, or is in its own language (another edition, #199), is cut by size.
  - Anchoring uses the language's native text vectors, so check in section 3 that they align at all. A language whose vectors are too weak to align shouldn't be enrolled.
  - After normalize, run `scripts.anchor` in the PR (section 8): `tests/test_anchor_fingerprint.py` fails while an enrolled work has no current cut file.
- [ ] **Editorial material is marked, not stripped (#236).** Mark titles, supplements, headings, apparatus and chant metadata as editorial spans with #236's mechanism, so the reader shows them and embed, translate and alignment leave them out. Don't add a new per-source stripping rule.

## 6. Cross-language links

- [ ] **`translation_of`.**
  - Scripture: `scripture_translation_of.csv`.
  - Other works: a `translation_of` row in `patristica/data/version_links.csv`, checked against the text, never to a container.
  - English translations: set in the ingestor (#150, #153).
- [ ] **`ORIGINAL_LANGUAGE_ORDER` in `web/src/lib/versions.ts`.** Insert the code after the languages its works were translated from. The reader uses this order only when no `translation_of` in a group names the original.
- [ ] **Version groups and alignment.** Check them with `uv run python -m scripts.version_groups`, which prints counts per language pair. `scripts.align` aligns new members once they have vectors. Check a sample in the parallel reader, and measure with `scripts.align_eval` if the language behaves differently.

- [ ] **Machine translation (#422).** Add the language's prompt name to `DOCUMENT_LANGUAGES` and a length band (English characters per source character, measured on a translated text) to `RATIO_BAND` in `scripts/machine_translate.py`. Without them, translating one of its works raises `KeyError`, and its works with no English version are candidates for the nightly run. **Free**: no data changes. `tests/test_machine_translation.py` checks that every language has both.

## 7. Web app and docs

- [ ] **Landing page.** Add the language's "Word" of John 1:1 to `WORDS` in `web/src/components/Landing.tsx`.
- [ ] **Site description.** Add the language to the description in `web/src/app/layout.tsx`.
- [ ] **Docs.**
  - CLAUDE.md "Language codes (ISO 639-3)";
  - README.md "Scope";
  - `DATA_COLLECTION_PLAN.md` §3 (source catalog rows) and §7 (encoding conversions);
  - a "Not yet in the corpus" mention, if any, removed.
- [ ] **`/sources` page.** It lists each source with its label and licence. Check that the new rows and any non-commercial mark are right.

## 8. Pipeline and cost

- [ ] **Estimate before paying:**
  - Embedding: Voyage `voyage-4-large` at $0.12 per million tokens (`PRICE_PER_MTOK` in `scripts/embed.py`). Rare scripts count up to about 2× cl100k. Every unit of at least `MIN_CHARS` characters gets a vector. For scale, the whole corpus (4.02M vectors) cost about $34 (#136).
  - Translation: units × $0.0014, plus the translation vectors, if the language is enrolled.
- [ ] **Reload size.** `build_index` loads only new works: their chunks and vectors. It updates metadata-only changes in place. A `FOLD_VERSION` bump refolds every work locally but rewrites only the chunks it changes; a `LOADER_VERSION` bump reloads everything (avoid). `scripts.status --db --vectors` on the pipeline machine lists the works a run would load, update or delete.
- [ ] **Paid steps run only in `scripts.pipeline --pay`** on master, after merge, by the owner. A PR never sends translate or embed requests, with one exception:
- [ ] **Anchored derived verses are cut in the PR** (#304), so master never holds provisional cuts of enrolled works and refs don't change between the PR and the publish. After normalize:
  1. `uv run --extra embed python -m scripts.anchor --dry-run`: the works to cut and the cost (an upper bound; usually cents per source);
  2. if an original lacks vectors (the step refuses it), `scripts.embed --work {original}` (paid);
  3. **ask the owner**, with the dry run's numbers, and wait for a yes. An agent never sends these requests without that permission, asked each time, **unless the dry runs of steps 1–2 total under $1.00** (#604): then it goes on without asking, with `--max-cost` capping anchor at what is left of the $1.00;
  4. `uv run --extra embed python -m scripts.anchor --pay`, then `uv run python -m scripts.normalize` (a no-op check);
  5. commit `data/anchors/`, `data/normalized/` and the changed `data/embeddings` shards, and put the cost in the PR description.

  Translation and the remaining embeds still happen in the owner's `scripts.pipeline --pay` after merge.

## Worked example: first ingest (skeleton)

The first source of a new language. `{code}` is the ISO 639-3 code, `{bcp47}` its BCP 47 tag, `{source}` the source id, `{n}` the issue.

```bash
# 0. Issue labelled "lang: {name}" and "phase-1: data"; branch off fresh master.
git switch -c {n}-{source}-ingest

# 1. Identity and display (sections 1-2): Language "{code}", Tradition if new,
#    validate.py, test_models.py, lang.ts (+test), fonts.ts, globals.css :lang({bcp47}),
#    format.ts TRADITIONS, versions.ts ORIGINAL_LANGUAGE_ORDER.

# 2. Ingestor: scripts/ingest/{source}.py with SOURCE_ID = "{source}", ingest(), licence,
#    author ids, translation_of where known, editorial spans marked (#236).
uv run python -m scripts.ingest.{source}        # first run into an empty dir stamps it
#    sources.py SOURCE_LABELS, authors.csv / author_strings.csv, genre_overrides.csv,
#    versification.py SOURCE_SCHEMES + scripture_translation_of.csv for Scripture books.

# 3. Structure: VERSE_TOKENS["{code}"] (measure first) and punctuation marks; enroll
#    translations of corpus originals in anchored splitting (anchored_sources.csv, #304).
uv run python -m scripts.normalize               # rebuilds all works once (versify hash)
uv run python -m scripts.validate
uv run python -m scripts.status --raw

# 4. Measure (section 3) on the new data; record the numbers on the language's issue.
uv run python -m scripts.chunk && uv run python -m scripts.link_translations
uv run python -m scripts.embed_eval.build --extend {code}
uv run python -m scripts.embed_eval.run --retriever bm25 --retriever dense:voyage/voyage-4-large
uv run python -m scripts.embed_eval.report
#    If translation vectors are needed: TRANSLATED_LANGUAGES + LANGUAGE_NAMES, then
#    scripts.align over the corpus (no API calls) to refresh its fingerprint.

# 4b. Anchored derived verses (section 8, #304): estimate, ASK THE OWNER (unless
#     the Voyage total is under $1.00, #604), then cut.
uv run --extra embed python -m scripts.anchor --dry-run
uv run --extra embed python -m scripts.anchor --pay   # only after the owner said yes, or under $1.00 (--max-cost)
uv run python -m scripts.normalize                    # a no-op check

# 5. Dry run: what is stale and what --pay would cost. Agents skip the steps whose
#    preflight reaches production (the DB tunnel, the upload key).
uv run --extra pipeline python -m scripts.pipeline --dry-run --skip build_index --skip upload_library

# 6. Reader check (both themes), web checks, PR. After merge the owner runs:
#    uv run --extra pipeline python -m scripts.pipeline --pay
```

Measurement (step 4) may be its own PR after the ingest PR. Enrolling in `TRANSLATED_LANGUAGES` must land before the language's first `--pay` run if the decision is yes, so its units are embedded once with both vectors.

## PR checklist

Copy into the PR description and tick:

- [ ] Links the language issue (`Closes #…` / `Part of #…`); the issue has its `lang:` label.
- [ ] `uv run pytest` passes, in particular:
  - `test_models`;
  - `test_normalize_fingerprint` (normalize re-run and committed);
  - `test_authors`;
  - `test_export_library` (labels);
  - `test_translation_of`;
  - `test_align_fingerprint`;
  - `test_textfold` and `test_versify` if changed.
- [ ] Web: `npm run lint`, `npm run typecheck`, `npm test` and `npm run build` in `web/`.
- [ ] `scripts.validate` has no errors (the pre-push hook runs it when its inputs change).
- [ ] `scripts.status` is clean apart from the pending paid steps.
- [ ] `scripts.pipeline --dry-run` output is summarized in the PR (agents add `--skip build_index --skip upload_library`, so nothing connects to production): the stale steps, the translate and embed estimates, and the new works and units (the reload size).
- [ ] No paid requests were sent, apart from `scripts.anchor --pay` (and the embed of its originals) with the owner's permission (or under $1.00 in all, #604), its cost stated. An "After merge" section lists what `scripts.pipeline --pay` will do and cost (as in #262).
- [ ] `tests/test_anchor_fingerprint.py` passes: every enrolled work has a current cut file in `data/anchors/`.
- [ ] Reader checked in light and dark themes (and RTL if relevant), with a screenshot of one work and of a parallel view.
- [ ] Decision record posted or updated on the language's issue (not in this file), and `docs/embedding-eval.md` if measured.
- [ ] Docs updated (section 7) and the `lang:` label description updated.

## Decision records

One per language, posted as a comment on the language's umbrella issue when the language is added (and edited as later PRs change it), never added to this file. Keep it short: the code and why, the script stored, folding rules, `VERSE_TOKENS` and how it was measured, eval numbers (paraphrase R@3, topical R@100, native vs translated), the translation decision and model, cost of the first paid run, and links to issues and PRs. Per-source details (conversion tables, versification, editorial spans) go in the source's own ingest issue and PR.

Records so far: Church Slavonic, #29; Arabic, #83; Old Georgian, #222; Old Irish, #225.

### Template

```markdown
### {Language} (`{code}`), {date}
- **Code:** … (why; BCP 47 tag …)
- **Script stored:** … (conversions at ingest, and why)
- **Folding:** rules added to `textfold.py`, or none (why)
- **`VERSE_TOKENS`:** N, measured on … (frozen)
- **Punctuation:** marks added to `versify.py`, or none (frozen)
- **Fonts:** font chosen, coverage checked
- **Embedding eval (#3 method):** paraphrase R@3 S/U …, topical R@100 S/U … (Greek/Latin for reference …)
- **Translation vectors:** yes/no, because …; model …, fidelity …, $/unit …
- **First paid run:** N units, $… embed, $… translate
- **Issues/PRs:** #…
```
