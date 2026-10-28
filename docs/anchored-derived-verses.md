# Anchored derived verses through vectors (design, #304)

**Status: implemented** (#304, #292), with the owner's decisions of
2026-10-28 (§13) and the deviations listed below. No source is enrolled yet:
Slavonic (#29) enrols `torot` in its own data PR. The code is
`patristica/anchoring.py` (enrolment, applying cut files, `RefineParams`),
`patristica/anchor_store.py` (cut files), `patristica/anchor_refine.py` (the
refinement of §4), `scripts/anchor.py` (the step) and `scripts/anchor_eval.py`
(the evaluation of §8). The prototype this document was written from
(`prototypes/anchored_verses/`) was removed; the implementation reproduces its
cuts exactly on synthetic data. It replaced the length-only projection of draft
PR #303 (#292), which was not merged.

### As implemented: decisions and deviations

- **Decisions (§13):** a separate `scripts.anchor` step with tracked cut
  files (1); data PRs of enrolled sources run `scripts.anchor --pay`, and an
  agent does so only after asking the owner, every time (2;
  `docs/adding-a-language.md` §8); published cuts are **frozen** (3b);
  **3 exploring rounds** plus the exact-only round (4, `RefineParams.max_rounds`);
  the higher share of comma cuts is accepted (5); #200's migration stays
  separate (7).
- **Staleness (§6).** A cut file records its inputs itself (`method`: a hash of
  `ANCHOR_VERSION` and `RefineParams`; `anchor`; `anchor_cuts`; `words`; and,
  for information, `model` and `stats`), so there is no
  `data/anchors/_fingerprint.json`. `scripts.anchor` cuts a work whose cut file
  is *missing* or whose *words* changed. A changed anchor, original cuts or
  method makes the file **frozen**: `scripts.status` warns, nothing is re-cut
  until `scripts.anchor --recut WORK` (or `--recut all`). So the redirect map
  of §6 isn't needed yet. `tests/test_anchor_fingerprint.py` (no vectors) fails
  on a missing cut file, changed words, a normalized output not cut as its file
  says, an enrolled work normalize hasn't built since enrolment, and an orphan
  cut file; not on frozen ones. A model change is a warning.
- **normalize's record** is a separate `anchor` key in `_fingerprints.jsonl`
  (`{"cuts": hash of the cut file or null}`; `null` for an enrolled work with a
  standard versification, which is never anchored), not part of the `curated`
  hash. The effect is the one §3 describes.
- **The step re-normalizes from `data/raw`** (`scripts.normalize`'s
  `normalize_all(..., only=…)`), instead of rebuilding the output from
  `data/normalized` (§3): the whitespace at the provisional cuts and the
  editorial spans (#236) can't be recovered from the normalized units. So
  `scripts.anchor` needs the raw data of the works it cuts (a data PR has it).
  It still reads only `data/normalized` and `data/embeddings` to compute.
- **Provisional units without vectors are embedded too.** A new source has no
  vectors for its provisional cut, which the band, the calibration and the
  exact-only fallback use, so the first embed sends them along with the
  segments. That adds up to about 1× the text (less the provisional units equal
  to a segment) to the costs of §7, which assumed stored vectors. Still cents.
- **Final units** whose exact text the refinement never embedded (a new unit
  spanning a provisional cut where the raw text had other whitespace) are
  embedded after the re-normalize, so every final unit's text vector is in
  `data/embeddings`.
- **Editorial material (#236) is never embedded:** segments, candidate pieces
  and units are embedded as their source text (spans left out, as
  `scripts.embed` does), while cut positions stay word positions of the full
  text.
- **Eligibility:** works with an unpublishable licence (`corpus.EXCLUDED_LICENSES`),
  or whose original has one, aren't anchored (they are never embedded). Vectors
  of another model, size or input type count as missing, for the original
  (the work is refused) and for rows of the translation (replaced).
- **Cost estimate and cap** (`--dry-run`, `scripts.pipeline`): per work, the
  first embed exactly, plus 2× the translation's text tokens for the rounds
  and final units. `scripts.anchor` enforces each work's sum as its budget, so
  the estimate is a real upper bound (in cl100k tokens, like `scripts.embed`'s)
  and the pipeline can debit it. A work whose original is cut earlier in the
  same run is estimated too.
- **A work is all or nothing:** if anything fails after its cut file is saved
  (re-normalize, final embed, writing vectors), the previous cut file and
  output are restored, so a plain re-run resumes it (from the scratch store).
  The pipeline's anchor step also fails, before anything is published, when a
  cut file is stale in a way the step can't fix (`scripts.anchor --check`).
- **Runtime.** The DP is vectorized over the run lengths of a segment
  boundary: one round on the Tractates (40,502 segments, 15,217 Latin units)
  takes about 40 s, against about 2.6 min in the prototype. A whole run there
  is a few minutes.
- **The evaluation** is `scripts/anchor_eval.py` (not `scripts.anchor --eval`):
  the prototype's pairs, metrics and hand-check samples, without #303's
  projection, which was dropped.

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
- **Cost** is cents: 1.4–2.6× one embed of the translation's text, and the
  final units' vectors come out of it, so the ordinary embed shrinks
  accordingly (§7). For a Slavonic source of TOROT's size it is about
  $0.07–0.25.
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

Implementation: `patristica/anchor_refine.py` (the prototype's `refine.py`).

### 4.1 Segments: the candidate cut points
- Each source paragraph of the translation is cut into segments at every
  sentence end and clause end (`versify._strength`: the same per-language
  punctuation tables), and at today's (provisional) cuts.
- Inside a run longer than the language's verse size, the paragraph is also
  cut at commas. Inside a run longer than twice that size, it is cut between
  words, as `split_text` does.
- A derived verse of the result is always a run of whole segments inside one
  source paragraph. Boundaries therefore stay at sentence and clause breaks:
  in the evaluation, 0% of refined cuts fell between words, and 10–22% fell
  at commas (§8).
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
- New pieces per round in the evaluation fall by about half each round
  (Tractates 5,572 → 2,149 → 1,195 → 724; §8).
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

Stale works re-run in `scripts.anchor`. Whether a work that is already published re-runs automatically or is only reported is decision 3 in §13. Segments whose text is unchanged hit
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

**Measured** in the evaluation (§8), in cl100k tokens of the translation:

| translation | text | segments (1st embed) | rounds 1–5 | total | × text |
|---|---|---|---|---|---|
| Tractates, NPNF (eng), 40,502 segments | 496k | 401k | 198k + 77k + 45k + 29k + 1k | 751k | **1.5×** |
| Basil letters, NPNF (eng), 16,065 segments | 209k | 158k | ≈ 137k over 2 runs | ≈ 295k | **1.4×** |
| Severian pta031 (hye), 929 segments | 76k | 65k | ≈ 132k over 2 runs | ≈ 197k | **2.6×** |

Notes:
- The segments cost less than the text. 17–20% of segments equal a
  provisional unit, whose vector is already stored.
- Each round costs less than the one before: about 40%, then 50–60%.
- The free Armenian version explores more.
- Voyage billed Armenian at about 0.55× its cl100k count, and English at about
  1×.
- **The final units' vectors are part of this total.** The later
  `scripts.embed` sends nothing for their text vectors, so the anchor step
  adds 0.4–1.6× an ordinary embed of the translation, not 1.4–2.6×.

**Slavonic (TOROT, #29).**
- TOROT's Old Church Slavonic is on the order of 250k words in all. Most of
  it is Scripture (Marianus, Zographensis, the Psalter), which is never
  split and so never anchored.
- The anchored part is the Suprasliensis homilies and lives, the Clozianus
  and similar: of the order of 60–100k words, about 0.4–0.8M cl100k tokens in
  Cyrillic (4× that if stored as Glagolitic, `docs/adding-a-language.md` §2).
- At 1.5–2.5× that, the anchor step costs **about $0.07–0.25**, and it
  replaces the text part of the ordinary embed.
- If Slavonic needs translation vectors (`TRANSLATED_LANGUAGES`), the real
  saving is translation: Sol at ~$0.0014 per unit, paid once on the final
  cut instead of on a provisional one and again after a re-cut.

**Runtime.** The prototype is pure Python plus numpy:
- 13 minutes for the Tractates' 40k segments × 5 rounds;
- 5 minutes for Basil;
- 20 seconds for a Severian homily.

That is fine for a source PR. For #200's corpus-wide migration, the DP's
inner loop should be vectorized over the segment-run length, or the step
parallelized per work.

**#200's migration** of the existing ~1.28M derived verses (§10): see there.

## 8. Evaluation

The prototype's `evaluate.py` (now `scripts/anchor_eval.py`, without #303)
evaluated #303's measurement pairs.
For each translation it compares three cuts:
- **today**: independent per-language cuts;
- **#303**: its Gale–Church projection, run from a scratch copy of its branch;
- **refined**: §4, with 4 exploring rounds plus the exact-only round.

Every cut is aligned with the original by `align_pair` (#179, default
parameters, text vectors on both sides, so native Armenian vectors too).
Run it with:

```
uv run --extra embed python -m scripts.anchor_eval --pay --sample 20
```

(The numbers below were measured with the prototype, 4 exploring rounds, and
#303's projection from a scratch copy of its branch.)

### Automatic measures

| pair | units: today / #303 / refined | original units in a confident 1:1 row: today / #303 / refined | refined units that differ from today's | refined cuts at sentence / clause / comma / word |
|---|---|---|---|---|
| Basil, Perseus grc → NPNF eng | 6,613 / 6,803 / 6,964 | 74.8% / 80.6% / **94.0%** | 2,629 (38%) | 69 / 9 / 22 / 0% (today 77 / 9 / 14 / 0.1%) |
| Tractates, PL 35 lat → NPNF eng | 14,818 / 14,658 / 14,975 | 81.8% / 88.9% / **97.7%** | 5,709 (38%) | 70 / 19 / 11 / 0% (today 73 / 19 / 8 / 0%) |
| Severian pta014, grc → hye | 282 / (as today) / 258 | 60.9% / – / **78.3%** | 148 | 44 / 46 / 10 / 0% (today 56 / 40 / 4 / 0%) |
| Severian pta031, grc → hye | 347 / (as today) / 312 | 65.7% / – / **92.1%** | 184 | 40 / 48 / 12 / 0% (today 50 / 40 / 10 / 0%) |

**These measures favour the refinement.** It optimizes the aligner's own
objective on the aligner's own vectors, so "1:1 in the alignment" is partly
circular. "Today" here is a fresh pairwise alignment, so its numbers differ
from #303's, which used the stored group alignments: three members for Basil,
translation vectors for Armenian.

The hand check is the real measure.

### Hand check (#303's protocol)

20 random original units per pair (seed 1). For each, the row that each cut
gives it: is it **exactly 1:1 and right**? I judged by reading:
- the Latin and Greek against the English;
- for Armenian, the Greek against the English machine translations of
  today's units that the row overlaps (`data/translations`). That makes the
  Armenian judgements coarser.

Units with no counterpart in the translation (NPNF's omissions, PL's
editorial notes and headings) count as wrong for every cut.

| pair | today | #303 | refined | no counterpart |
|---|---|---|---|---|
| Basil | 12 / 20 | 9 / 20 | **17 / 20** | 2 |
| Tractates | 11 / 20 | 12 / 20 | **14 / 20** | 3 |
| Severian pta031 | 7 / 20 | 7 / 20 (not anchored: free) | **15 / 20** | 0; 2 more unclear for both, counted wrong |

What the errors look like:
- **Refined, right where today is wrong.** It splits today's 2:1 and 1:2 rows
  (Basil 965, 3868; Tractates 1033, 9325, 10675; Severian 60, 117). It drops
  a trailing or leading clause that belongs to the neighbour (Basil 1100,
  3109, 3193; Severian 14, 48, 68, 107, 241). And it pulls in a clause today
  left in the neighbour (Severian 130, 136).
- **Refined, wrong.**
  - Basil 2089: it cut the relative clause off a sentence that the original
    unit ends inside.
  - Tractates 1537, 1931, 13144: the original unit starts or ends in
    mid-sentence at a citation ("I, 53).") or a question, and the
    translation's sentence order differs. These were wrong today too.
  - Severian 199: it took one sentence too many from the previous unit.
- **#303 made today worse on Basil** (9 vs 12; it was ≥ 7 in #303's own
  check). It merges rows where its margin wasn't sure (Basil 232, 1719) and
  cuts one clause short (4058).

### Convergence

New pieces per round fall by about half each round (Tractates 5,572 → 2,149 →
1,195 → 724). After 4 exploring rounds, the exact-only round left only
4–30 units unembedded: units that took in a skipped segment. None of the
runs reached the strict fixed point within 4 rounds. That doesn't matter
for the result, because the exact-only round scores the final cut on real
vectors; it does cost the extra rounds. A cap of 3 rounds would lose little:
round 4 found 0.2–0.5% new pieces.

### Caveats
- The hand check is one reader's judgement on 20 units per pair, and the
  Armenian is judged through machine translations.
- **Severian and Basil were resumed** from the scratch cache of an earlier
  run that was stopped by a bug in the final round (fixed). Those two
  therefore had up to 8 exploring rounds in effect. The Tractates run had 4.
- **Basil: 651 of 1,487 English paragraphs were touched by no bead** and kept
  today's cut. Most are short (salutations, letter headings), but some are
  letters whose Greek the monotone DP skipped: NPNF reorders the late letters,
  as #303 found. A per-letter window (the structural anchors of #302: letter
  numbers in both refs) would recover them.
- **Comma cuts rise** (Basil 14% → 22%), because original units end at
  commas. That is the price of following the original. Word cuts stay at 0%.

## 9. Free translations and same-language editions

**Free translations** (#303's gate gave up on Severian's Armenian, which keeps
53–57% of the original's sentence ends):
- The vector DP has no gate. It pairs what it can and leaves additions and
  omissions to the skips.
- On both Severian homilies it raised the aligner's count of confident 1:1
  rows from 61–66% to 78–92%, with Armenian's native vectors. In the hand
  check on pta031 it went from 7 to 15 of 20 (§8).
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
  same-language editions (#199), so the translations to refine come to
  roughly 25–40M tokens.
- At the measured 1.4–2.6×, that is **about $4–10 of Voyage**. The final
  vectors come out of it, so it replaces most of #200's "re-embedding"
  line (~$11–12) instead of adding to it.
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
| `scripts/anchor_eval.py` | **reuse** its pairs, `_translation` and the alignment-based reference. Merge it with the prototype's `evaluate.py` as `scripts.anchor --eval` (done as `scripts/anchor_eval.py`, without #303's projection) |
| CLAUDE.md "Derived verses" standard, the `adding-a-language.md` item | **reuse**, reworded for the anchor step |

## 12. Implementation plan (follow-up PRs)

Steps 1–4 were done in one PR (see "As implemented" at the top); step 5 is #29's.

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

## 13. Recommendation and decisions for the owner

**Recommendation: build this, not #303's projection.**
- It beats today's cuts on all three hand-checked pairs: Basil 12 → 17,
  Tractates 11 → 14, Severian 7 → 15 of 20.
- #303 managed 9 and 12, and it can't touch free versions.
- It costs cents per source.
- Through the cut file, normalize stays free and deterministic.

**Don't merge #303 as it stands.** Take from it, in the first implementation
PR (§11):
- the enrolment table and its loader;
- `Anchor`, `cuts_hash` and `anchor_order`;
- `versify_chunks(units_of=…)`;
- `anchor_eval`'s pairs and reference code, merged into the new eval.

Then close #303.

**Decisions for the owner:**
1. **A separate `scripts.anchor` step plus tracked cut files** (this design),
   rather than vectors inside normalize. Normalize stays vector-free, and a
   cut is reproducible without the API.
2. **An exception to "a PR never sends embed requests"** for
   `scripts.anchor --pay` and the embed of its originals, so master never
   holds provisional cuts of enrolled works (the #308 precedent). Without
   it, the owner's pipeline run anchors after merge, and refs change between
   the PR and the publish.
3. **What happens after publication when an original changes:**
   - (a) re-cut automatically, with a redirect map (§6 as written); or
   - (b) freeze published cuts, and only report the staleness until someone
     runs `scripts.anchor --recut WORK`.

   I lean to (b) for the first sources: refs are reader URLs, and the
   originals of new languages (Greek) change rarely.
4. **Rounds:** 3 exploring rounds plus the exact-only round (round 4 found
   ≤ 0.5% new pieces), or 4 as measured.
5. **More comma cuts** (up to ~22% of cuts, from 14%): accept, as the price of
   following the original. A larger comma `break_cost` trades 1:1 rows for
   cleaner breaks.
6. **Same-language editions** wait for #199 (string alignment, the same DP with
   a different scorer).
7. **#200:** pilot the migration on these same groups with this machinery
   (their vectors exist) before deciding on the corpus-wide run.

