# OCR error detection with character n-grams: proof of concept

Before paying for a full proofreading pass, we tested two hypotheses about
cheap detection of OCR damage at the chunk level:

1. **H1.** A per-language *unigram* character frequency model is enough to flag
   chunks that contain erroneous characters.
2. **H2.** A *bigram* model catches what slips through the unigram, including
   errors made entirely of characters from the target alphabet.

Code is in `scripts/ocr_poc/` (not part of the pipeline). Run it from the repo
root with `python -m scripts.ocr_poc.<module>`. `score_sample` scores the
labelled sample, `synth` runs single-error injection, and `flagrate` gives
the flag rate for each source.

## Verdict

- **H1: confirmed, with conditions.** The unigram catches every injected
  out-of-alphabet error, and nearly all real chunks that contain junk
  characters. Clean text is flagged about 2% of the time. Two things are
  needed for this:
  - **The unigram must know the alphabet, not just frequencies.** Clean Greek
    editions contain Latin letters and digits in their apparatus. A
    frequency-only unigram therefore rates OCR's `ot` (for οἱ) or `6` (for ὁ)
    as "rare" rather than "impossible", and misses 13 of the 75 Greek junk
    chunks. A script-aware unigram misses 2.
  - **The reference corpus must match the target's editorial conventions.**
    The Vulgate/Perseus reference has no Bible citations, Roman numerals,
    footnote markers or French spacing before `:`. Against Migne Latin it
    flags 22% of clean chunks. Masking those patterns brings this to 10%.

  Even so, the unigram sees only **half of the damaged Greek chunks**
  (71/148): the other half contain no odd characters at all.
- **H2: partly confirmed. Mostly disconfirmed for the error classes that
  matter most.** At chunk level the bigram looks good: it flags 66% of the
  Greek damaged chunks the unigram missed and 50% of the Latin ones, at about
  2% false positives. Damaged chunks, though, usually carry several errors.
  **Per single error**, the bigram catches only:
  - 38% of Greek letter confusions, and 3–30% of Latin ones;
  - almost none of the Greek accent and breathing errors (0–14%). The
    exception is the smooth breathing read as a grave, `ὲν` (86%);
  - 0% of real-word errors (`bis` for `his`) and case errors (`tempUs`);
  - 3–38% of word splits and joins.

  A **trigram** is consistently better: roughly double on Latin letter
  confusions, at the same false-positive rate.
- **What's left needs word-level knowledge**: a dropped or misplaced accent
  (`ταχος`, `γάρ` before a non-enclitic, `ὅντες`), breathing swaps
  (`αὑτοῦ`), a word that is valid but wrong, and word division. A word list
  built from about 30M characters of clean Greek is too sparse for Greek
  morphology to notice one bad word in a chunk, with or without accents. It
  would take a morphological analyser (Morpheus/Diorisis), a word-level LM or
  an LLM pass.
- **Practical consequence**: in the labelled sample, **117 of 120 OGPG chunks
  and 94 of 120 Migne PL chunks have at least one real error**, and so do
  17–20 of 20 in Mozarabic, Gallican and the Typikon. For those sources,
  flagging hardly shrinks a proofreading job: nearly every chunk needs one.
  The detector is useful for:
  - triaging sources and works;
  - ranking chunks by severity;
  - finding the damaged minority in mixed sources (First1K: about a third
    flagged; 9 of 30 sampled chunks were damaged);
  - keeping clean editions out of the proofreading queue.

## Method

**Models** (`models.py`). Text is NFC-normalized. Apostrophe and koronis
variants and Migne's `ϐ` are unified, since they are encoding variants, not
OCR errors (`corpus.norm`).
- *Unigram*: score = surprisal of the rarest character.
- *Bigram/trigram*: casefolded, padded with word boundaries, interpolated
  (Witten–Bell) down to the unigram. Score = the largest conditional
  surprisal in the chunk. Mean surprisal (perplexity) does clearly worse,
  because OCR damage is local.
- *v2*: typographic spacing normalized, apparatus masked (`prep`), and a
  script-aware unigram.
- *Lexicon*: OOV share against a word list, either folded or keeping
  accents.

**Reference (training) text**: SBLGNT, LXX, PTA, PTA-LXX and Perseus for
Greek; Clementine Vulgate, Perseus, PTA and Cursus for Latin. Labelled chunks
are excluded. 5% is held out, and **every threshold is set so that 2% of
held-out clean chunks are flagged**. The labelled sample never sets a
threshold.

**Labelled sample** (`sample.jsonl`, `labels.txt`). 390 random chunks of at
least 20 characters, drawn per source:
- Greek: OGPG 120, First1K 30, Typikon 20, PTA 15, Perseus 15;
- Latin: PL 120, Mozarabic 20, Gallican 20, Clementine 10, Perseus 10,
  Cursus 10.

They were labelled by hand before any scoring. Tags:
- **X**: characters that are impossible in clean text of the language;
- **L**: wrong letters within the alphabet;
- **A**: Greek accent or breathing errors;
- **S**: split, joined or hyphenated words;
- **F**: foreign-language contamination.

"In-alphabet only" means L/A/S without X/F. Editorial matter (M) and glyph
variants (V) count as clean.

## Results: labelled sample

Counts are flagged/total.

**Greek**: 52 clean; 148 damaged, of which 75 have junk characters and 73
are in-alphabet only (43 with wrong letters, 29 with accent errors only).

| scorer | clean flagged | junk chunks | in-alphabet only | of which letters | of which accent-only | unigram misses caught | precision | AUC |
|---|---|---|---|---|---|---|---|---|
| unigram | 2/52 | 62/75 | 9/73 | 6/43 | 2/29 | — | .97 | .83 |
| bigram | 3/52 | 73/75 | 48/73 | 31/43 | 16/29 | 51/77 | .98 | .91 |
| trigram | 3/52 | 73/75 | 48/73 | 31/43 | 16/29 | 51/77 | .98 | .94 |
| unigram ∪ bigram | 3/52 | 74/75 | 48/73 | 31/43 | 16/29 | 51/77 | .98 | |
| v2 script unigram | 3/52 | 73/75 | 11/73 | 6/43 | 4/29 | 14/77 | .97 | .81 |
| v2 script unigram ∪ bigram | 3/52 | 75/75 | 47/73 | 31/43 | 15/29 | 51/77 | .98 | |
| … ∪ accent lexicon | 7/52 | 75/75 | 54/73 | 34/43 | 19/29 | 58/77 | .95 | |
| unigram, self-trained on all Greek | 1/52 | 13/75 | 2/73 | | | 1/77 | .94 | .75 |
| bigram, self-trained on all Greek | 2/52 | 31/75 | 3/73 | | | 6/77 | .94 | .77 |

**Latin**: 59 clean; 131 damaged, of which 63 have junk characters and 68
are in-alphabet only (48 with wrong letters, 20 with split/hyphenation
only).

| scorer | clean flagged | junk chunks | in-alphabet only | of which letters | of which splits only | unigram misses caught | precision | AUC |
|---|---|---|---|---|---|---|---|---|
| unigram | 13/59 | 62/63 | 45/68 | 25/48 | 20/20 | — | .89 | .82 |
| bigram | 18/59 | 63/63 | 55/68 | 35/48 | 20/20 | 12/24 | .87 | .86 |
| trigram | 19/59 | 63/63 | 51/68 | 34/48 | 17/20 | 13/24 | .86 | .88 |
| v2 script unigram | 6/59 | 62/63 | 40/68 | 20/48 | 20/20 | 1/24 | .94 | .85 |
| v2 bigram | 9/59 | 62/63 | 50/68 | 30/48 | 20/20 | 8/24 | .93 | .91 |
| v2 trigram | 10/59 | 63/63 | 48/68 | 31/48 | 17/20 | 10/24 | .92 | .92 |
| v2 script unigram ∪ bigram | 9/59 | 63/63 | 50/68 | 30/48 | 20/20 | 9/24 | .93 | |
| unigram, self-trained on all Latin | 1/59 | 10/63 | 0/68 | | | 0/24 | .91 | .53 |

The Latin unigram's strong score on in-alphabet errors is mostly incidental.
Hyphenation splits (`assumptio- nem`) use `-`, which is rare in the reference.
Wrong-letter errors are caught when they share a chunk with one.

**Training on the whole corpus (OCR included) fails.** The OCR noise becomes
part of the model, and junk-character recall drops from 62/75 to 13/75.
Bootstrapping, i.e. retraining on the target chunks that pass round 1, did
not help either. Round 1 rejects exactly the chunks that would teach the
model the target's legitimate conventions.

*Caveats.*
- The v2 masking was designed after looking at the v1 false positives on
  this same sample, so the v2 rows are optimistic. Confirming them needs a
  fresh labelled sample.
- There was one annotator, and the labels were blind to scores but not to
  the source.
- Several "clean" chunks the detectors still flag are editorial apparatus:
  `(Psal. XLIII, 25, 24)`, `x 6, 7, 10, 12–14 …`, CANTUS metadata.

## Results: one injected error per chunk

1,500 held-out clean reference chunks per language, each corrupted with
exactly one error, using v2 models and thresholds. Only chunks whose clean
copy is not flagged are counted, so the false-positive rate (about 2%) is
the floor.

| Greek error | unigram | bigram | trigram | accent lexicon |
|---|---|---|---|---|
| Latin look-alike (ο→o, ι→i, ν→v …) | 100% | 97% | 96% | 3% |
| digit/junk (ὁ→6, ο→0 …) | 100% | 100% | 100% | 3% |
| letter confusion (ο→σ, ν↔υ, β→δ, ὸ→δ, ε→ς …) | 0% | 38% | 60% | 3% |
| drop initial breathing (εἰς→είς) | 0% | 9% | 14% | 2% |
| smooth breathing read as grave (ἐν→ὲν) | 6% | 86% | 79% | 3% |
| swap breathing (αὐτοῦ→αὑτοῦ) | 1% | 8% | 9% | 2% |
| acute↔grave (γὰρ→γάρ) | 5% | 14% | 28% | 0% |
| drop accent (λοιπὸν→λοιπον) | 0% | 0% | 0% | 2% |
| split word | 0% | 10% | 9% | 5% |
| hyphen split | 100% | 100% | 95% | 5% |
| join words | 0% | 38% | 46% | 4% |

| Latin error | unigram | bigram | trigram |
|---|---|---|---|
| digit/junk (i→1, l→\|, e→©, s→$) | 100% | 100% | 100% |
| c↔e | 0% | 30% | 56% |
| n↔u | 0% | 22% | 46% |
| rn↔m, cl↔d, li↔h | 0% | 3% | 39% |
| h↔b, i↔l, t↔l, f↔s (long s) | 0% | 17% | 50% |
| æ→x, a↔o | 0% | 4% | 10% |
| case (tempus→tempUs) | 0% | 0% | 0% |
| split word | 0% | 3% | 19% |
| hyphen split | 100% | 99% | 76% |
| join words | 0% | 12% | 20% |

Case errors are invisible because the n-gram models casefold. A simple rule
(an uppercase letter inside a lowercase word) would catch them.

## Results: flag rate by source

v2 detector, 10% sample of each source's chunks of at least 20 characters.
The reference sources' rates are partly in-sample (their chunks trained the
models).

| source | lang | unigram | unigram ∪ bigram | unigram ∪ trigram |
|---|---|---|---|---|
| sblgnt | grc | 0.6% | 2.0% | 0.9% |
| lxx-rahlfs | grc | 0.2% | 0.4% | 0.2% |
| pta | grc | 2.3% | 4.3% | 3.1% |
| perseus | grc | 2.1% | 3.0% | 2.5% |
| first1k | grc | 27.1% | 33.0% | 34.7% |
| ogpg | grc | 54.8% | 77.7% | 81.9% |
| typikon | grc | 96.9% | 98.6% | 99.0% |
| clementine | lat | 0.9% | 1.9% | 1.4% |
| perseus | lat | 4.4% | 6.8% | 5.7% |
| cursus | lat | 0.4% | 0.7% | 0.7% |
| oglt-pl | lat | 61.1% | 70.1% | 75.2% |
| mozarabic | lat | 78.0% | 85.9% | 87.8% |
| gallican | lat | 86.4% | 90.4% | 92.4% |
| cantus | lat | 63.7% | 96.0% | 96.0% |

CANTUS is not OCR. Its chunks start with ingest metadata
(`[Fer. 3 Maj. Hebd.] [L] [A] [5] [CANTUS:002263] [mode:8] …`), which the
models rightly find un-Latin.

## Recommendations

1. For a cheap first-pass flag, use a **script-aware unigram plus a
   character trigram** (rather than a bigram), trained on clean editions
   only, with thresholds calibrated on held-out clean text. Mask the
   legitimate apparatus of the target edition first.
2. Treat the score as a **severity ranking**, not a gate, for OGPG, PL, the
   IA liturgical OCR and the Typikon. Nearly all of their chunks are damaged.
3. Greek accent/breathing errors and real-word errors need word-level
   checking: a morphological analyser, a word LM or an LLM proofreader. An
   LLM pass over ranked chunks is probably the cost-effective next
   experiment.
