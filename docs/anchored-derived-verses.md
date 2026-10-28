# Anchored derived verses through vectors (design, #304)

**Status: design.** Nothing here is implemented in the pipeline yet. The
prototype in `prototypes/anchored_verses/` is experimental and evaluation-only:
it writes nothing under `data/normalized` or `data/embeddings`. Part of #304;
it replaces the length-only projection of draft PR #303 (#292), which stays
offline.

## 1. The problem in one paragraph

Derived verses (#2, `patristica/versify.py`) are cut in each work on its own,
at a per-language size. The versions of one work are therefore cut at
different places, and parallel reading (#181) shows rows that begin and end at
different words. A translation should instead be cut so that each of its
derived verses renders one derived verse of its original (the work it was
translated from, `Work.translation_of`). #303 tried to do that from lengths
alone (Gale–Church) at normalize time. It was right where it was sure, but it
was sure of only 44–56% of the boundaries, and it could not handle free
translations at all (#200 measurement). The passage aligner (#179) already
pairs units through their Voyage vectors and knows content, not only length.
This design uses the same vectors to place the boundaries.

## 2. Summary of the design

- **A new paid step, `scripts.anchor`**, runs between `normalize` and
  `translate`. For each *enrolled* work (enrolment as in #303: a per-source
  table) that has an original in the corpus, it embeds the translation's
  sentence/clause *segments* (Voyage, text only), finds the cut that pairs
  each original unit with a run of whole segments (§4), embeds the
  resulting units, and repeats until the chosen units all have their own
  vectors.
- **The result is a tracked cut file**, `data/anchors/{normalized path}.json`:
  per source paragraph, the word positions where its derived verses start.
  No text, no vectors. `normalize` applies a current cut file when it builds
  the work, so normalize stays free, deterministic and vector-free, and
  anyone can rebuild the anchored output from tracked data alone.
- **Vectors.** Segment and candidate vectors live in a gitignored, regenerable
  scratch store (`data/anchor_vectors/`). The final units' vectors are
  production vectors (same model, dims, input type, text) and are written into
  `data/embeddings` as ordinary `KIND_TEXT` rows, so `scripts.embed` has
  nothing left to send for them.
- **Translation happens once**, after the cut is final: `translate` runs after
  `anchor`, so the rare languages never pay for translating a provisional cut.
- **Cost** is a fraction of a normal embed of the same text: the measured
  total over the four evaluation works was about 1.6× the cost of embedding the
  translation once (§7). For a Slavonic source of TOROT's size it is well
  under a dollar.
- **A data PR runs `scripts.anchor --pay`** for its new sources, as #308 ran
  `scripts.embed`, and commits the cut files with the normalized output. A
  test fails when an enrolled work's cut file is missing or stale, so master
  never holds a provisional cut of an enrolled work.

## 3. Pipeline order

```
normalize → anchor → validate → translate → embed → align → build_index → export_library → upload_library
```

### normalize
- Unchanged for every work that is not enrolled (byte for byte: enrolment is
  opt-in and empty at first, as in #303).
- For an enrolled work it splits each source paragraph as follows:
  - if the work has a cut file whose paragraph hash matches that paragraph's
    words, at the recorded positions;
  - otherwise as today (`split_text`, the *provisional* cut).
- The cut file's hash joins the work's curation fingerprint
  (`_fingerprints.jsonl`, like `translation_of`, #153). A new or changed cut
  file therefore rebuilds exactly that work, with no `--force`.
- normalize never reads vectors, never calls an API, and doesn't need the
  original to be normalized first. That is simpler than #303, which had to
  build anchors before the works anchored on them (its deferred build order).

### anchor (new, paid: Voyage only)
- Reads `data/normalized` (the translation's source paragraphs are rebuilt
  from its derived verses, as `scripts.anchor_eval` in #303 did) and the
  original's unit vectors from `data/embeddings`. It needs no raw data.
- For every enrolled work whose cut file is missing or stale (§6) it runs the
  refinement (§4) and writes the cut file. It then rebuilds that work's
  normalized output through the same code path normalize uses
  (`patristica.anchoring.apply_cuts`), so a later normalize writes the same
  bytes.
- It also writes the final units' text vectors into the work's
  `data/embeddings` shard.
- Works are processed originals first (#303's `anchor_order`: an English
  translation of a Slavonic translation of a Greek work waits for the
  Slavonic cut). An original must have current vectors: the step refuses a
  work whose original lacks them, as `scripts.align` refuses a group, and
  says to run `scripts.embed --work {original}` first.
- `--dry-run` prints, per work, the segments and an upper bound for the
  refinement rounds and its cost. Without `--pay` it sends nothing.

### scripts.pipeline
- `anchor` joins `STEPS` after `normalize` and joins `PAID`. Like
  `translate` and `embed`, it sends requests only with `--pay`, stops the run
  before itself (exit 0, with the estimate) otherwise, and counts against
  `--max-cost`.
- With nothing stale it is a no-op that needs no key.
- `validate` follows `anchor`, so it checks the final cut.

### In a data PR (the #308 precedent)
A PR that adds an enrolled source runs, after normalize:
1. `scripts.embed --work {originals}`, if the originals have no vectors yet
   (usually they do);
2. `scripts.anchor --pay`;
3. `scripts.normalize`, a no-op check that the output is current.

It commits `data/anchors/`, `data/normalized/` and the fingerprints. The
cost goes in the PR description, as #308 did. Translation, the remaining
embeds (translation vectors), align and publish happen in the owner's next
`scripts.pipeline --pay`, unchanged. `docs/adding-a-language.md` §8 says "a
PR never sends translate or embed requests". It should get an exception
for `scripts.anchor` and the embed of its originals: cheap, Voyage only, and
the one way to commit final refs. Without that exception, the PR commits
provisional cuts and the owner's pipeline run re-cuts them. That works too,
but the refs would change between the PR and the publish.

## 4. The refinement algorithm

Prototype: `prototypes/anchored_verses/refine.py`.

### 4.1 Segments: the candidate cut points
- Each source paragraph of the translation is cut into segments at every
  sentence end and clause end (`versify._strength`: the same per-language
  punctuation tables), and at today's (provisional) cuts.
- Inside a run longer than the language's verse size, the paragraph is also
  cut at commas. Inside a run longer than twice that size, it is cut between
  words, as `split_text` does.
- A derived verse of the result is always a run of whole segments inside one
  source paragraph. Boundaries therefore stay at sentence and clause breaks:
  in the evaluation, 0% of refined cuts fell between words, and the comma
  share was 5–12% (§8).
- Derived verses never cross source paragraphs. This is the rule of #2 and
  #292, unchanged.

### 4.2 Vectors
- Every segment is embedded once, text only.
- The *vector cache* maps the hash of an exact text (`translations.text_sha`)
  to its vector. It is seeded for free with the provisional cut's stored
  vectors. A provisional unit is a run of segments, so the cache can score it
  exactly.
- The original's units already have vectors in `data/embeddings`. For a
  Syriac/Coptic/Armenian/Ge'ez *original* the design uses its text vectors,
  not its translation vectors: the two vector kinds aren't mixed on one side.
- **Rare-language translations use their native text vectors.** Their
  translation vectors don't exist yet: they come after the cut. The
  evaluation (Armenian) shows that native vectors are good enough to place
  the boundaries (§8). A language whose native vectors are too weak to
  align at all (measured per language, `docs/adding-a-language.md` §3)
  shouldn't be enrolled.

### 4.3 Anchored segmentation: one dynamic program
A monotonic DP over (original units consumed *k*, segments consumed *j*), in
the style of the passage aligner:

- **Bead.** 1–3 original units take a run of 1–24 segments, at most 12 verses
  of the language. The run may cross a translation paragraph break, which
  scores it as one passage, but the output cuts it there.
- **Gain**, exactly the aligner's (#179):
  `√a · (cos − baseline − margin) − merge_penalty · (a − 1)`.
  - `cos` is the cosine of the summed original vectors with the piece's
    vector.
  - The baseline is the mean of the original units' mean similarity to the
    translation and the piece's similarity to the original's mean vector.
    This corrects for text that is close to everything.
  - Small extra costs:
    - ending on a weak break: clause 0.01, comma 0.03, word 0.08;
    - crossing a paragraph: 0.02.
- **The piece's vector.**
  - If the piece's exact text is in the cache, its own vector.
  - Otherwise the sum of its segments' vectors, mapped onto the exact scale
    by a linear *calibration*. The calibration is fitted per work on the
    provisional cut's confident 1:1 beads: exact margin against summed
    margin (fitted slope 0.69–0.75, intercept 0.10–0.18). A summed piece
    also pays a hysteresis of 0.02, so an embedded piece is kept unless the
    estimate is clearly better.
- **Skips.**
  - Skipping an original unit is free: the translation leaves it out (NPNF
    translates a selection of Basil's letters).
  - Skipping a segment costs 0.03: it is an addition, and it joins the unit
    before it (else after it) in its paragraph.
  - A paragraph that no bead touches keeps its provisional cut.
- **Band.** The DP runs in a band of ±6 original units around the
  provisional cut's alignment (`align_pair` on the stored vectors, its
  confident monotone chain), interpolated where that is unaligned. A row is
  widened where the translation skips a block, so the band never cuts off
  the path. This is what keeps a 40k-segment work tractable.

### 4.4 Rounds and convergence (the owner's loop)
The loop the owner sketched:

> provisional cut → embed → align against the original → move boundaries
> where a unit straddles two original units, or two units map to one →
> re-embed only changed units → repeat

maps onto the DP like this:

| step of the loop | here |
|---|---|
| provisional cut, embed | today's cut and its stored vectors (free), plus one embed of the segments |
| align, move boundaries | one run of the DP: it moves every boundary, not only those of non-1:1 beads, and it places the new boundaries from the segments' vectors |
| re-embed only changed units | embed the chosen pieces that aren't in the cache |
| repeat | run the DP again: those pieces now score by their own vectors |

- **Convergence.** Stop when a round chooses only pieces that are already
  in the cache (a fixed point: every chosen piece was scored by its own
  vector). Otherwise stop after `max_rounds` = 4 exploring rounds.
- **The final round is exact-only.** It runs the DP once more, allowing only
  pieces that have their own vector (the provisional units are always among
  them, so it can't fail). The final cut is therefore scored entirely on real
  vectors, and every final unit already has its production vector.
- New pieces per round in the evaluation:
  - Severian: 25 → 16 → 12 → 5.
  - Basil and the Tractates: see §8.
- The cache only grows and the hysteresis favours embedded pieces, so the
  rounds can't oscillate for long. Each round costs less than the one before.

### 4.5 What it does not do
- **It doesn't re-cut the original.** The original keeps its own derived
  verses, cut as today. Re-cutting existing originals is #200's migration.
- **It doesn't reorder.** A translation that moves a block is aligned
  monotonically, like the aligner's first pass. The moved block keeps its
  provisional cut (it is skipped), and `scripts.align` pairs it later.
- **Same-language editions are out of scope.** That is #199: string
  alignment beats vectors there. See §9.

## 5. Data layout

| what | where | tracked | size |
|---|---|---|---|
| enrolment | `patristica/data/anchored_sources.csv` (`source_id,reason`, #303's file and loader) | yes | a row per source |
| cut files | `data/anchors/{normalized path}.json`, one per anchored work | yes (plain git, small) | ~30 bytes per unit |
| fingerprint | `data/anchors/_fingerprint.json`: method version, params and, per work, its inputs (§6) | yes | small |
| segment and candidate vectors | `data/anchor_vectors/{normalized path}.npz` (`sha`, `vec` float16 1024) | no (gitignored, regenerable; in #156's archive with the embeddings) | ~2 KB per segment |
| final unit vectors | `data/embeddings/{path}.npz`, ordinary `KIND_TEXT` rows with the production run record | no (as today) | as today |

A cut file looks like this:

```json
{"work_id": "torot/supr-…", "anchor": "first1k/tlg2062/…",
 "method": 1, "anchor_cuts": "sha16", "inputs": "sha16",
 "paragraphs": {"Supr.12": {"words": "sha16", "starts": [0, 41, 77, 130]}, …},
 "stats": {"rounds": 3, "beads": 812, "one_one": 0.83, "vectors": "sha16"}}
```

- `starts` are word indices (`versify._atoms`), so whitespace differences
  between the raw text and the rebuilt paragraph don't matter.
- `words` is a hash of the paragraph's words. A paragraph whose text changed
  falls back to the provisional cut until `scripts.anchor` runs again. The
  test below catches that state.

## 6. Determinism and staleness (#130)

**Reproducing a cut needs no vectors.** The cut file is tracked, and
normalize applies it, so any checkout rebuilds byte-identical output.
Vectors are needed only to *compute* a cut. Computing is deterministic given
the vector cache: the DP uses float64 sums in a fixed order, and ties go to
the earlier position. The API itself isn't bit-reproducible, so two machines
that embed from scratch may differ on close calls. That is why the cut, not
the vectors, is the record.

**Inputs of a cut** (`inputs` in the fingerprint):
- the translation's paragraph words;
- the original's id and `anchor_cuts`: #303's `cuts_hash` of the original's
  refs and texts;
- the method version and parameters;
- the model of the vectors used.

A work is **stale** when:
- its paragraph words changed (a re-ingest or editorial fix);
- its original's cuts changed;
- its enrolment or `translation_of` changed;
- `ANCHOR_VERSION` was bumped.

Stale works re-run in `scripts.anchor`. Segments whose text is unchanged hit
the scratch cache (free when it is present, cheap when it is not).

**Not stale: a change to the anchor code's hash.** Derived refs are reader
URLs and translation keys, so a published cut is frozen like
`VERSE_TOKENS`. A code change that should re-cut bumps `ANCHOR_VERSION`
deliberately, as `LOADER_VERSION` works for build_index. A **model change**
(new vectors for the original) is reported by `scripts.status` but doesn't
re-cut either.

**Checks.**
- `tests/test_anchor_fingerprint.py` needs no vectors (like
  `test_align_fingerprint.py`). It fails when an enrolled work with an
  original in the corpus has no cut file, a stale one, or a normalized
  output that doesn't match its cut file.
- `scripts.status` gets an "anchor" row.

**When an original changes after publication,** its translations are re-cut
and their refs move. That is unavoidable (#303 and #200 say the same). The
refs that disappear go into a redirect map (old ref → the new unit that
contains its first word), the mechanism #200 needs anyway.

## 7. Cost

Voyage `voyage-4-large`, $0.12 per million tokens.

**Measured** (the evaluation, §8), per translation:
- segments: about 1.0× the translation's tokens, less the segments that equal
  a provisional unit (17–20% of segments);
- exploring rounds: 0.3–0.6× in all;
- the final units' vectors are among those, so the later `scripts.embed`
  saves 1×.

Net: about **0.6× to 1× an ordinary embed of the same text, on top of it**.

| corpus | translation tokens | anchor step | of which per round after the first |
|---|---|---|---|
| Basil, NPNF (English) | 0.21 M | see §8 | |
| Tractates, NPNF (English) | 0.50 M | see §8 | |
| Severian ×2 (Armenian) | 0.27 M (cl100k) | see §8 | |

**Slavonic (TOROT, #29).**
- TOROT's Old Church Slavonic is on the order of 250k words in all. Most of
  it is Scripture (Marianus, Zographensis, the Psalter), which is never
  split and so never anchored.
- The anchored part is the Suprasliensis homilies and lives, the Clozianus
  and similar: of the order of 60–100k words, about 0.4–0.8M cl100k tokens in
  Cyrillic (4× that if stored as Glagolitic, `docs/adding-a-language.md` §2).
- The anchor step for them costs about **$0.05–0.20**, on top of the
  ordinary embed of $0.05–0.10.
- If Slavonic needs translation vectors (`TRANSLATED_LANGUAGES`), the
  saving is the real one: Sol translation at ~$0.0014 per unit, paid once on
  the final cut instead of twice.

**#200's migration** of the existing ~1.28M derived verses (§10) would cost
about $10–15 of Voyage, in the range #200 estimated for re-embedding alone.
Most of that is the Greek editions, which #199's string alignment would
handle instead.

## 8. Evaluation

See the PR description for the table and the hand check (filled in from
`prototypes/anchored_verses/evaluate.py`).

## 9. Free translations and same-language editions

**Free translations** (#303's gate gave up on Severian's Armenian, which keeps
53–57% of the original's sentence ends):
- The vector DP has no gate. It pairs what it can and leaves additions and
  omissions to the skips.
- On both Severian homilies it raised the aligner's count of confident 1:1
  rows (§8) with Armenian's native vectors.
- A free version still gets fewer 1:1 rows than a close one, because its
  passages genuinely don't correspond unit for unit. The DP then merges
  (2–3 originals into one unit) instead of forcing a cut.
- No threshold is needed. `stats.one_one` in the cut file records how well
  it went.

**Same-language editions (#199):**
- Vectors can tell which passage a unit renders, but not where inside a
  near-identical sentence two editions differ by a word.
- For an edition of the original in its own language, the same DP should
  score with a folded-text alignment instead (#199: character or word
  alignment of `textfold.fold` output). Its boundaries then coincide wherever
  the texts agree.
- The design keeps the hook from #303 (`same_language_units`): enrolled works
  whose `translation_of` is in their own language aren't anchored until #199
  lands.
- Two translations of one original (two English versions of Basil) are each
  anchored on the original, not on each other. Their rows coincide through
  the original.

## 10. #200: migrating existing works

The machinery is the same; only the inputs differ:
- **The provisional cut is today's published cut**, with vectors for every
  unit already in `data/embeddings`. The DP can always fall back to today's
  units for free.
- Segments have to be embedded once: English 12M, Latin 12M and Greek 75M
  cl100k tokens over all derived verses. Most of the Greek is originals or
  same-language editions (#199), so the vector part is roughly 25–40M
  tokens, about $3–5 for segments plus rounds.
- What #200 lists stays: the redirect map, the re-translation of 643
  Armenian/Coptic units, and a reload with `build_index --rebuild-index`.
- **Migration should run per version group, original first.** A group whose
  refined cut doesn't beat today's by a set margin (the measured share of
  confident 1:1 rows) keeps today's cut. That bounds churn to where it
  helps.

## 11. What to take from #303

| #303 piece | verdict |
|---|---|
| enrolment table `anchored_sources.csv` + loader | **reuse** as is |
| anchor = `translation_of`; `Anchor`, `cuts_hash`, `anchor_order` (cycles raise) | **reuse**, moved into `scripts.anchor` |
| anchor record in `_fingerprints.jsonl` | **replace** by the cut file's hash in the curation fingerprint, and the inputs in `data/anchors/_fingerprint.json` |
| deferred build order inside normalize | **drop**: normalize no longer needs the original |
| `split_text(target=…)` / `versify_chunks(units_of=…)` | **reuse** `units_of` (apply a cut, keeping #236's marks); `target` isn't needed |
| Gale–Church `project`, `align_lengths`, margins, the 70% gate | **drop** from the pipeline. Its paragraph-level DP could serve as a vector-free band for an original with no vectors, but the step refuses that case instead |
| `scripts/anchor_eval.py` | **reuse** its pairs, `_translation` and the alignment-based reference. Merge it with `prototypes/anchored_verses/evaluate.py` as `scripts.anchor --eval` |
| CLAUDE.md "Derived verses" standard, the `adding-a-language.md` item | **reuse**, reworded for the anchor step |

## 12. Implementation plan (follow-up PRs)

1. `patristica/anchoring.py`:
   - from #303: enrolment, anchors, `cuts_hash`, `anchor_order`;
   - `apply_cuts`;
   - the cut-file store (`patristica/anchor_store.py`, no numpy, like
     `alignment_store`);
   - normalize applies cut files, plus the fingerprint;
   - tests.
   Nothing is enrolled, and a full normalize writes 0 chunks.
2. `scripts/anchor.py`: the refinement (from the prototype), the scratch
   vector store, writing final vectors into `data/embeddings`, `--dry-run`,
   `--pay`, `--eval`; `tests/test_anchor_fingerprint.py`; the `scripts.status`
   row.
3. `scripts.pipeline`: the `anchor` step (paid), its estimate and preflight.
4. Docs:
   - CLAUDE.md "Derived verses" and "Pipeline Scripts";
   - `docs/adding-a-language.md` §5 and §8 (the in-PR anchor exception).
5. Slavonic (#29) enrols `torot` in its own data PR and runs
   `scripts.anchor --pay` there.
