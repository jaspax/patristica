# Embedding eval: results

Evidence for the Phase 2 search design (#3, #84). Run 2026-10-12/13 on the eval set built from master data at that date. The harness is in `scripts/embed_eval/`, and its commands are in `CLAUDE.md`.

## Setup

**Eval corpus:** 26,557 chunks sampled from the corpus, in 9 languages. It contains:
- every chunk of the selected Scripture verse groups, in all languages;
- language-unique targets, each with its ±2 neighbouring chunks;
- about 2,000 random distractors per language.

**Targets:** each of the 7 target languages has about 100 Scripture verses and about 100 chunks from works that exist only in that language. The exceptions are Hebrew (no unique works) and Syriac-unique (69, all from the Hudra). Gothic is parallel-only.

**Queries:**
- **exact:** a 5–9-word span of the target, in the original language. Generated automatically.
- **near-verbatim:** the same span unaccented and unpointed, with Latin spelling variants. Generated automatically.
- **paraphrase:** a loose English rendering of the target.
- **topical:** an English topic that the target answers.

The paraphrase and topical queries were drafted by Claude from the original text, then reviewed and partly corrected by GPT-6.1 Sol (#87): 496 queries, about 20 targets per language and origin.

**Scoring:** every number is filtered to the target's language. Each query type has its own pass threshold:
- exact and near-verbatim: the target is at rank 1 (R@1);
- paraphrase: the target is in the top 3 (R@3);
- topical: the target is in the top 100 (R@100).

Columns are language plus **S** (Scripture) or **U** (unique). Small cells (n = 15–20 for paraphrase and topical) move by 0.05 per query.

**"+ Sol translations":** every Syriac, Coptic, Armenian and Ge'ez chunk in the eval corpus also has an English vector, made from its GPT-6.1 Sol translation (11,239 chunks; `data/translations/`). A chunk scores the better of its two vectors.

## Decision (2026-10-13)

- **Translator:** GPT-6.1 Sol.
- **Embedder:** Voyage `voyage-4-large`. Every Syriac, Coptic, Armenian and Ge'ez chunk gets a second vector made from its Sol translation, and a chunk scores the better of its two vectors.
- **Quoted queries** go to the normalized keyword index (#86).
- **Vector size** (1024 or 512 dims) is settled with hosting (#50).
- **Production pipeline:** #93.

## Conclusions

1. **Quotes go to the keyword index (#86).** BM25 over normalized text (`patristica.textfold`) gets 0.94 on exact and near-verbatim quotes. The best embedder gets 0.72 (Voyage). Translations don't change quote search at all: none of the 2,518 quote queries changed rank.
2. **Translations make every rare language reachable from English.**
   - **Paraphrase R@3** rises from 0.38–0.84 to **0.94–0.99** across embedders.
   - **Topical R@100** rises from 0.32–0.86 to **0.77–0.99**.
   - **Coptic and Syriac,** previously unreachable, reach 0.90–1.00.
   - **Queries written by a different model from the translator** (Claude's drafts against Sol's translations) score as high as Sol-written ones, so the gain isn't the translator matching its own phrasing.
3. **Best combination: Voyage `voyage-4-large` + Sol translations.** It scores 0.99 paraphrase and 0.99 topical, and is the strongest embedder on quotes (0.72), with 1024-dim vectors. OpenAI + translations is close (0.98 / 0.94, 3072 dims).
4. **Without translations, only Gemini `gemini-embedding-2` comes close** (0.84 / 0.86). It is still weak on Coptic (0.50) and the Syriac Hudra (0.35 paraphrase).
5. **No equal-weight hybrid.** Fusing BM25 and vector rankings by RRF made both quote and paraphrase search worse (see #3), so queries are routed, not fused.

## Matrix: {language × embedder}

The `arb U` column comes from Arabic's own one-language set (#483, "Arabic" below), the `oge S` / `oge U` columns from Old Georgian's (#529, "Old Georgian" below), the `sga U` column from Old Irish's (#552, "Old Irish" below) the `osx U` column from Old Saxon's (#585, "Old Saxon" below), the `ang U` column from Old English's (#582, "Old English" below) and the `goh U` column from Old High German's (#584, "Old High German" below); ¹ with local-opus translations, not Sol's. They were measured later with BM25 and Voyage only, and are not in the mean. `–` means not measured.

### exact (R@1)

| retriever | grc S | grc U | lat S | lat U | hbo S | hye S | hye U | gez S | gez U | cop S | cop U | syc S | syc U | arb U | oge S | oge U | sga U | osx U | ang U | goh U | mean |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BM25 (keyword) | 1.00 | 0.83 | 1.00 | 0.89 | 1.00 | 1.00 | 0.71 | 1.00 | 0.99 | 1.00 | 0.98 | 1.00 | 0.78 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.96 | **0.94** |
| OpenAI text-embedding-3-large | 0.72 | 0.25 | 0.83 | 0.56 | 0.90 | 0.56 | 0.00 | 0.68 | 0.49 | 0.39 | 0.45 | 0.61 | 0.01 | – | – | – | – | – | – | – | **0.50** |
| OpenAI text-embedding-3-large + Sol translations | 0.72 | 0.25 | 0.83 | 0.56 | 0.90 | 0.56 | 0.00 | 0.68 | 0.49 | 0.39 | 0.45 | 0.61 | 0.01 | – | – | – | – | – | – | – | **0.50** |
| Voyage voyage-4-large | 0.74 | 0.46 | 0.91 | 0.61 | 0.95 | 0.86 | 0.25 | 0.85 | 0.75 | 0.93 | 0.86 | 0.95 | 0.22 | 0.79 | 0.80 | 0.92 | 0.93 | 0.93 | 0.78 | 0.80 | **0.72** |
| Voyage voyage-4-large + Sol translations | 0.74 | 0.46 | 0.91 | 0.61 | 0.95 | 0.86 | 0.25 | 0.85 | 0.75 | 0.93 | 0.86 | 0.95 | 0.22 | 0.77 | 0.80 | 0.92 | 0.93 | 0.93¹ | 0.78 | 0.80¹ | **0.72** |
| Cohere embed-v4.0 | 0.85 | 0.43 | 0.93 | 0.64 | 0.94 | 0.89 | 0.07 | 0.50 | 0.49 | 0.27 | 0.32 | 0.67 | 0.00 | – | – | – | – | – | – | – | **0.54** |
| Cohere embed-v4.0 + Sol translations | 0.85 | 0.43 | 0.93 | 0.64 | 0.94 | 0.89 | 0.07 | 0.50 | 0.49 | 0.27 | 0.32 | 0.67 | 0.00 | – | – | – | – | – | – | – | **0.54** |
| Gemini gemini-embedding-2 | 0.70 | 0.24 | 0.89 | 0.56 | 0.93 | 0.35 | 0.01 | 0.43 | 0.39 | 0.55 | 0.55 | 0.80 | 0.00 | – | – | – | – | – | – | – | **0.49** |
| Gemini gemini-embedding-2 + Sol translations | 0.70 | 0.24 | 0.89 | 0.56 | 0.93 | 0.35 | 0.01 | 0.43 | 0.39 | 0.55 | 0.55 | 0.80 | 0.00 | – | – | – | – | – | – | – | **0.49** |
| BGE-M3 (local) | 0.72 | 0.26 | 0.83 | 0.50 | 0.69 | 0.74 | 0.08 | 0.67 | 0.59 | 0.00 | 0.06 | 0.24 | 0.00 | – | – | – | – | – | – | – | **0.41** |
| BGE-M3 (local) + Sol translations | 0.72 | 0.26 | 0.83 | 0.50 | 0.69 | 0.74 | 0.08 | 0.67 | 0.59 | 0.00 | 0.06 | 0.24 | 0.00 | – | – | – | – | – | – | – | **0.41** |
| *n* | 100 | 100 | 99 | 98 | 96 | 100 | 100 | 100 | 100 | 98 | 99 | 100 | 69 | 100 | 50 | 50 | 80 | 58 | 80 | 80 | |

### near (R@1)

| retriever | grc S | grc U | lat S | lat U | hbo S | hye S | hye U | gez S | gez U | cop S | cop U | syc S | syc U | arb U | oge S | oge U | sga U | osx U | ang U | goh U | mean |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BM25 (keyword) | 1.00 | 0.83 | 1.00 | 0.89 | 1.00 | 1.00 | 0.71 | 1.00 | 0.99 | 1.00 | 0.98 | 1.00 | 0.78 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.96 | **0.94** |
| OpenAI text-embedding-3-large | 0.60 | 0.13 | 0.81 | 0.52 | 0.81 | 0.50 | 0.00 | 0.64 | 0.46 | 0.38 | 0.24 | 0.52 | 0.00 | – | – | – | – | – | – | – | **0.43** |
| OpenAI text-embedding-3-large + Sol translations | 0.60 | 0.13 | 0.81 | 0.52 | 0.81 | 0.50 | 0.00 | 0.64 | 0.46 | 0.38 | 0.24 | 0.52 | 0.00 | – | – | – | – | – | – | – | **0.43** |
| Voyage voyage-4-large | 0.67 | 0.39 | 0.92 | 0.61 | 0.94 | 0.85 | 0.28 | 0.82 | 0.75 | 0.93 | 0.85 | 0.93 | 0.09 | 0.79 | 0.78 | 0.92 | 0.88 | 0.93 | 0.75 | 0.81 | **0.69** |
| Voyage voyage-4-large + Sol translations | 0.67 | 0.39 | 0.92 | 0.61 | 0.94 | 0.85 | 0.28 | 0.82 | 0.75 | 0.93 | 0.85 | 0.93 | 0.09 | 0.77 | 0.78 | 0.92 | 0.88 | 0.93¹ | 0.75 | 0.81¹ | **0.69** |
| Cohere embed-v4.0 | 0.73 | 0.36 | 0.93 | 0.64 | 0.69 | 0.87 | 0.05 | 0.48 | 0.45 | 0.24 | 0.18 | 0.60 | 0.00 | – | – | – | – | – | – | – | **0.48** |
| Cohere embed-v4.0 + Sol translations | 0.73 | 0.36 | 0.93 | 0.64 | 0.69 | 0.87 | 0.05 | 0.48 | 0.45 | 0.24 | 0.18 | 0.60 | 0.00 | – | – | – | – | – | – | – | **0.48** |
| Gemini gemini-embedding-2 | 0.39 | 0.02 | 0.88 | 0.48 | 0.79 | 0.13 | 0.00 | 0.14 | 0.19 | 0.53 | 0.44 | 0.66 | 0.00 | – | – | – | – | – | – | – | **0.36** |
| Gemini gemini-embedding-2 + Sol translations | 0.39 | 0.02 | 0.88 | 0.48 | 0.79 | 0.13 | 0.00 | 0.14 | 0.19 | 0.53 | 0.44 | 0.66 | 0.00 | – | – | – | – | – | – | – | **0.36** |
| BGE-M3 (local) | 0.52 | 0.15 | 0.79 | 0.50 | 0.44 | 0.71 | 0.05 | 0.70 | 0.61 | 0.00 | 0.00 | 0.16 | 0.00 | – | – | – | – | – | – | – | **0.36** |
| BGE-M3 (local) + Sol translations | 0.52 | 0.15 | 0.79 | 0.50 | 0.44 | 0.71 | 0.05 | 0.69 | 0.61 | 0.00 | 0.00 | 0.16 | 0.00 | – | – | – | – | – | – | – | **0.36** |
| *n* | 100 | 100 | 99 | 98 | 96 | 100 | 100 | 100 | 100 | 98 | 99 | 100 | 69 | 100 | 50 | 50 | 80 | 58 | 80 | 80 | |

### paraphrase (R@3)

| retriever | grc S | grc U | lat S | lat U | hbo S | hye S | hye U | gez S | gez U | cop S | cop U | syc S | syc U | arb U | oge S | oge U | sga U | osx U | ang U | goh U | mean |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BM25 (keyword) | 0.00 | 0.00 | 0.10 | 0.17 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.11 | 0.07 | 0.12 | 0.01 | **0.02** |
| OpenAI text-embedding-3-large | 1.00 | 0.89 | 1.00 | 1.00 | 1.00 | 0.05 | 0.05 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | – | – | – | – | – | – | – | **0.38** |
| OpenAI text-embedding-3-large + Sol translations | 1.00 | 0.89 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.90 | – | – | – | – | – | – | – | **0.98** |
| Voyage voyage-4-large | 1.00 | 1.00 | 1.00 | 1.00 | 0.90 | 0.70 | 0.85 | 0.15 | 0.07 | 0.00 | 0.00 | 0.45 | 0.00 | 0.97 | 0.82 | 0.80 | 0.47 | 0.33 | 0.71 | 0.36 | **0.55** |
| Voyage voyage-4-large + Sol translations | 1.00 | 1.00 | 1.00 | 1.00 | 0.90 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.98¹ | 1.00¹ | 1.00¹ | **0.99** |
| Cohere embed-v4.0 | 1.00 | 0.74 | 1.00 | 1.00 | 0.50 | 0.20 | 0.25 | 0.05 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | – | – | – | – | – | – | – | **0.36** |
| Cohere embed-v4.0 + Sol translations | 1.00 | 0.74 | 1.00 | 1.00 | 0.50 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | – | – | – | – | – | – | – | **0.94** |
| Gemini gemini-embedding-2 | 1.00 | 0.84 | 1.00 | 1.00 | 1.00 | 0.90 | 0.95 | 1.00 | 0.93 | 0.50 | 0.50 | 1.00 | 0.35 | – | – | – | – | – | – | – | **0.84** |
| Gemini gemini-embedding-2 + Sol translations | 1.00 | 0.84 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.55 | – | – | – | – | – | – | – | **0.95** |
| BGE-M3 (local) | 0.85 | 0.89 | 1.00 | 0.94 | 0.55 | 0.80 | 0.90 | 0.40 | 0.53 | 0.00 | 0.06 | 0.00 | 0.00 | – | – | – | – | – | – | – | **0.53** |
| BGE-M3 (local) + Sol translations | 0.85 | 0.89 | 1.00 | 0.94 | 0.55 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.95 | – | – | – | – | – | – | – | **0.94** |
| *n* | 20 | 19 | 20 | 18 | 20 | 20 | 20 | 20 | 15 | 20 | 16 | 20 | 20 | 100 | 50 | 50 | 80 | 57 | 80 | 80 | |

### topical (R@100)

| retriever | grc S | grc U | lat S | lat U | hbo S | hye S | hye U | gez S | gez U | cop S | cop U | syc S | syc U | arb U | oge S | oge U | sga U | osx U | ang U | goh U | mean |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BM25 (keyword) | 0.00 | 0.00 | 0.20 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.09 | 0.11 | 0.03 | 0.06 | **0.02** |
| OpenAI text-embedding-3-large | 0.90 | 0.89 | 0.90 | 0.94 | 0.85 | 0.15 | 0.05 | 0.10 | 0.00 | 0.00 | 0.00 | 0.10 | 0.10 | – | – | – | – | – | – | – | **0.38** |
| OpenAI text-embedding-3-large + Sol translations | 0.90 | 0.89 | 0.90 | 0.94 | 0.85 | 1.00 | 1.00 | 1.00 | 1.00 | 0.95 | 0.94 | 0.90 | 1.00 | – | – | – | – | – | – | – | **0.94** |
| Voyage voyage-4-large | 1.00 | 1.00 | 1.00 | 1.00 | 0.95 | 0.80 | 0.90 | 0.30 | 0.40 | 0.05 | 0.19 | 0.50 | 0.45 | 0.97 | 0.80 | 0.86 | 0.38 | 0.39 | 0.70 | 0.44 | **0.66** |
| Voyage voyage-4-large + Sol translations | 1.00 | 1.00 | 1.00 | 1.00 | 0.95 | 1.00 | 1.00 | 1.00 | 1.00 | 0.95 | 0.94 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.95 | 0.93¹ | 0.93¹ | 0.94¹ | **0.99** |
| Cohere embed-v4.0 | 0.30 | 0.74 | 0.70 | 1.00 | 0.40 | 0.25 | 0.40 | 0.10 | 0.00 | 0.00 | 0.06 | 0.05 | 0.15 | – | – | – | – | – | – | – | **0.32** |
| Cohere embed-v4.0 + Sol translations | 0.30 | 0.74 | 0.70 | 1.00 | 0.40 | 1.00 | 1.00 | 0.85 | 1.00 | 0.90 | 1.00 | 0.90 | 1.00 | – | – | – | – | – | – | – | **0.83** |
| Gemini gemini-embedding-2 | 1.00 | 0.89 | 1.00 | 0.94 | 0.95 | 0.95 | 0.85 | 0.95 | 1.00 | 0.70 | 0.44 | 0.90 | 0.65 | – | – | – | – | – | – | – | **0.86** |
| Gemini gemini-embedding-2 + Sol translations | 1.00 | 0.89 | 1.00 | 0.94 | 0.95 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.94 | 0.95 | 0.85 | – | – | – | – | – | – | – | **0.96** |
| BGE-M3 (local) | 0.45 | 0.74 | 0.80 | 0.89 | 0.50 | 0.40 | 0.55 | 0.40 | 0.47 | 0.00 | 0.12 | 0.00 | 0.00 | – | – | – | – | – | – | – | **0.41** |
| BGE-M3 (local) + Sol translations | 0.45 | 0.74 | 0.80 | 0.89 | 0.50 | 0.55 | 1.00 | 0.90 | 1.00 | 0.75 | 0.81 | 0.65 | 0.95 | – | – | – | – | – | – | – | **0.77** |
| *n* | 20 | 19 | 20 | 18 | 20 | 20 | 20 | 20 | 15 | 20 | 16 | 20 | 20 | 100 | 50 | 50 | 80 | 57 | 80 | 80 | |

## Cost and vector size: OpenAI vs Voyage

**Token counts.** Measured on a per-language sample, Voyage counts rare scripts at 0.55–0.70× OpenAI's tokens (Armenian and Ge'ez lowest) and English and Latin about equally.

**Embedding the full corpus once** (about 972k chunks plus 133k translations) costs about the same either way:
- **OpenAI:** about 339M tokens, ≈ $44 standard or $22 batch.
- **Voyage:** about 288M tokens, ≈ $11 standard after the 200M free tokens, or $23 batch.

**Shortened vectors.** Both models support Matryoshka shortening: keep the first N dimensions and renormalize. OpenAI documents this as equivalent to its `dimensions` option. For Voyage, truncated vectors matched `output_dimension` exactly (cosine 1.0). The table scores shortened vectors from the cached full-size ones (`dense:NAME@N`). Means are across language groups; "worst cell" is the lowest language/origin score on paraphrase or topical.

| With Sol translations | Dims | Paraphrase R@3 | Topical R@100 | Worst cell | Exact R@1 | Vectors, full corpus (halfvec) |
|---|---:|---:|---:|---:|---:|---:|
| OpenAI text-embedding-3-large | 3072 | 0.98 | 0.94 | 0.85 | 0.50 | ≈ 6.8 GB |
| OpenAI text-embedding-3-large | 1536 | 0.98 | 0.94 | 0.85 | 0.50 | ≈ 3.4 GB |
| OpenAI text-embedding-3-large | 1024 | 0.98 | 0.93 | 0.80 | 0.49 | ≈ 2.3 GB |
| Voyage voyage-4-large | 1024 | 0.99 | 0.99 | 0.90 | 0.72 | ≈ 2.3 GB |
| Voyage voyage-4-large | 512 | 0.99 | 0.97 | 0.90 | 0.70 | ≈ 1.1 GB |
| Voyage voyage-4-large | 256 | 0.99 | 0.97 | 0.90 | 0.66 | ≈ 0.6 GB |

At full size, OpenAI's 3072-dim vectors would need a 16 GB database tier against 8 GB for 1024 dims, roughly $100 a month more on the managed hosts in #50. Shortening removes that gap. At any given size, Voyage scores at least as well as OpenAI, and it is clearly ahead on quotes.

## Translation quality (151 rare-language targets)

Four models translated each target. Opus 5.5 and GPT-6.1 Sol judged every translation blind; the judges agreed exactly 74% of the time and within one point 99% of the time. Fidelity is on a 1–5 scale.

| Translator | Fidelity, other vendor's judge | Self-judged | Hallucinated (of 151) | $/passage |
|---|---:|---:|---:|---:|
| GPT-6.1 Sol | 4.44 (Opus) | 4.66 | 0 | 0.0066 |
| Opus 5.5 | 4.48 (Sol) | 4.77 | 0 | 0.0197 |
| Sonnet 5.5 | 4.07–4.11 | – | 1–3 | 0.0119 |
| Haiku 5.5 | 2.91–2.97 | – | 36–39 | 0.0009 |

Bulk translation groups up to 25 consecutive chunks of one work per request, which costs about $0.0014 per chunk.

## Church Slavonic (`chu`, #336)

Measured on 2026-10-29, Voyage `voyage-4-large` only, on the CCMH Gospel codices (Marianus, Zographensis, Assemanianus, Savvina kniga), Codex Suprasliensis and the Vitae of Constantine and Methodius. These are built from the branches of #332 and #333 before they merged. The harness is `scripts.embed_eval.spelling` and `scripts.embed_eval.langset`. The old eval set's cache and chunk ids are gone (#102), and every number above is filtered to the target's language, so `chu` gets its own one-language set, `data/eval/chu`, built the same way. It has 2,706 chunks: 100 Scripture and 100 Slavonic-only targets, their ±2 neighbours, every witness of the target verses, and 1,908 distractors.

**Decision (a), owner, 2026-10-29: `chu` is embedded in its stored spelling.** `fold()` stays a keyword-search feature, and `source_text` isn't normalized for `chu`. **Decision (b), owner, 2026-10-29: `chu` gets Sol translation vectors** (`TRANSLATED_LANGUAGES`), on the second round below. The translation-quality bake-off was skipped: Sol's translations bring retrieval to about 1.00, and a spot-check of 22 of them against the Slavonic found no hallucinations or omissions.

### Spelling sensitivity

The minimal pairs are 50 Marianus verses, each rewritten in one spelling class at a time. The table gives the cosine of each variant to its original. "Nearest" is the share of variants whose nearest verse among all 3,614 Marianus verses is their original.

| Spelling class | n | Mean cosine | Min | Nearest |
|---|---:|---:|---:|---:|
| final yers dropped (богъ → бог) | 47 | 0.982 | 0.906 | 1.00 |
| ь → ъ | 39 | 0.983 | 0.895 | 1.00 |
| every yer dropped (кръстъ → крст) | 50 | 0.967 | 0.889 | 1.00 |
| ѣ → ꙗ by position (ѣко → ꙗко) | 19 | 0.989 | 0.980 | 1.00 |
| ѣ → е/я by position | 50 | 0.973 | 0.943 | 1.00 |
| і, ꙇ → и | 50 | 0.975 | 0.940 | 1.00 |
| оу → ѹ | 50 | 0.974 | 0.827 | 1.00 |
| оу, ѹ → у | 50 | 0.967 | 0.804 | 1.00 |
| ꙗ → я, ѥ → е, ѩ → ѧ, ѭ → ѫ | 25 | 0.990 | 0.977 | 1.00 |
| titla spelled out (гл҃а → глагола) | 46 | 0.957 | 0.885 | 1.00 |
| titla, breathings and accents dropped | 50 | 0.977 | 0.914 | 1.00 |
| all at once: modern Russian orthography | 50 | 0.862 | 0.682 | 0.96 |
| `fold()` | 50 | 0.886 | 0.727 | 0.94 |
| *the next verse* | 50 | 0.564 | 0.395 | 0.00 |
| *the same verse in Zographensis* | 49 | 0.895 | 0.727 | 0.92 |
| *the same verse in Assemanianus* | 37 | 0.879 | 0.696 | 0.95 |
| *Greek (SBLGNT) unaccented vs accented* | 50 | 0.950 | 0.799 | – |
| *Greek, the next verse* | 50 | 0.651 | 0.364 | – |

A single spelling class costs no more than Greek accents do. All of them stacked (modern spelling, `fold()`) move a verse about as far as another witness's copy of it, and it still finds its original 94–96% of the time.

**Cross-witness retrieval** finds each verse of one codex among all verses of another (12 ordered pairs, 1,440–3,430 verses each):
- **as stored:** R@1 0.90–0.97, R@5 0.96–1.00;
- **both sides `fold()`-ed:** R@1 0.91–0.98, R@5 0.97–1.00.

Folding gains at most 0.02, and Savvina kniga is the weakest witness either way.

### Native retrieval, first round (n = 20 per paraphrase/topical cell)

| Query | Metric | `chu` S | `chu` U | `chu` folded S | `chu` folded U |
|---|---|---:|---:|---:|---:|
| English paraphrase | R@3 | 0.90 | 0.75 | 1.00 | 0.90 |
| English topical | R@100 | 1.00 | 0.85 | 1.00 | 0.85 |
| exact span | R@1 | 0.67 | 0.96 | 0.62 | 0.93 |
| near-verbatim span | R@1 | 0.58 | 0.95 | 0.61 | 0.92 |
| span in modern Russian spelling | R@1 | 0.38 | 0.93 | 0.47 | 0.88 |

- **Comparison:** Greek and Latin score 1.00 on both English cells. Armenian without translations scored 0.70/0.85 paraphrase and 0.80/0.90 topical. #84's bar is about 0.95/0.9.
- **Keyword search:** BM25 over folded text scores 0.97/0.99 on exact spans and 0.66/0.95 on modern-spelled spans.
- **Scripture R@1 is pessimistic:** a span counts only in witnesses that contain it letter for letter, so another codex's copy of the verse at rank 1 is scored as a miss.
- **Cost:** about $0.15 of Voyage, 1.27M tokens.

### Native vs Sol translations, second round (n = 80 per cell)

**The set:** `data/eval/chu2` has 2,737 Slavonic chunks.
- **Scripture:** the Gospel codices, the Psalterium Sinaiticum (#334) and the Psalter of Demetrius (#337).
- **Slavonic-only:** Suprasliensis, the Vitae, Chrabr, the Euchologium and the Kiev Missal.

**The queries:** Claude drafted 160 targets × 2 English queries from the Slavonic. GPT-6.1 Sol reviewed them once (#87 method): 198 pass, 118 were corrected and 4 were flagged for overlap with an English Bible. Every Slavonic chunk of the set also got a Sol translation (bulk prompt, 142 requests), stored in an eval store rather than `data/translations`.

| Queries | Retriever | Paraphrase R@3 S / U | Topical R@100 S / U |
|---|---|---|---|
| all (80/80) | native | 0.85 / 0.84 | 0.91 / 0.84 |
| all (80/80) | + Sol translations | 1.00 / 1.00 | 1.00 / 0.96 |
| passing (74/62, 42/20) | native | 0.85 / 0.82 | 0.88 / 0.90 |
| passing (74/62, 42/20) | + Sol translations | 1.00 / 1.00 | 1.00 / 1.00 |
| corrected (76/80) | native | 0.84 / 0.81 | 0.89 / 0.81 |
| corrected (76/80) | + Sol translations | 1.00 / 1.00 | 0.99 / 0.99 |

- **Native, by text** (all queries): Gospels 0.92 paraphrase / 0.94 topical, Psalters 0.71 / 0.86, Suprasliensis 0.82 / 0.83.
- **With translations:** every group reaches 1.00, except Suprasliensis topical at 0.97.
- **Cost:** review $1.00, Sol translation $2.25, Voyage about $0.02.

## Arabic (`arb`, #483)

Measured on 2026-10-30, Voyage `voyage-4-large` only, with the method of the Slavonic second round (`scripts.embed_eval.langset`), on the branches of #479, #480 and #481 before they merged.

**The set:** `data/eval/arb` has 2,273 Arabic chunks from all 11 Arabic works: 100 targets, their ±2 neighbours and 1,889 distractors. Units that `scripts.embed` doesn't embed are left out (shorter than 10 characters of source text, such as wholly editorial headings).
- **There is no Arabic Scripture** in the corpus, so the Scripture cells are empty. Every target is "unique" (`UNIQUE_WORKS["arb"]` lists all 11 works). The one-language set holds no English, so a work's English version (tertullian.org, Evetts) is not in the search space.
- **By text:** 54 targets from the six tertullian.org texts (Yahya ibn Adi, Ibn al-Tayyib, al-Majdal, Severus's *Book of the Councils*), 37 from the four parts of the History of the Patriarchs (OpenITI, uncorrected OCR), and 9 from al-Kindi's *Apology*, the only Arabic work with no English version.

**The queries** (`data/eval_authored/arb.jsonl`): Claude drafted 100 targets × 2 English queries from the Arabic. 31 targets are `medium` confidence, mostly OCR-damaged History of the Patriarchs fragments. GPT-6.1 Sol reviewed them once (#87 method):
- 166 queries pass and 34 were corrected (11 paraphrases, 23 topical queries, mostly as too narrow);
- paraphrase accuracy averaged 4.66 and topical relevance 4.62;
- Sol read 86 originals "well" and 14 "partly", all of them History of the Patriarchs OCR.

Every Arabic chunk of the set also got a Sol translation (bulk prompt, 104 requests), stored in an eval store rather than `data/translations`.

| Queries | Retriever | Paraphrase R@3 | Topical R@100 | Topical R@1 |
|---|---|---:|---:|---:|
| all (100/100) | native | 0.97 | 0.97 | 0.45 |
| all (100/100) | + Sol translations | 1.00 | 1.00 | 0.61 |
| passing (89/77) | native | 0.97 | 0.96 | 0.47 |
| passing (89/77) | + Sol translations | 1.00 | 1.00 | 0.62 |
| corrected (100/100) | native | 0.97 | 0.97 | 0.50 |
| corrected (100/100) | + Sol translations | 1.00 | 1.00 | 0.61 |

- **Native, by text** (all queries, paraphrase R@3 / topical R@100):
  - tertullian.org: 0.94 / 0.98;
  - History of the Patriarchs: 1.00 / 0.97;
  - al-Kindi: 1.00 / 0.89 (n = 9).
- **The misses are near misses.** The three paraphrases outside the top 3 rank 4th or 5th, behind neighbouring paragraphs of the same short treatise, and only three topical queries miss the top 100.
- **Quotes:** BM25 1.00 on exact and near-verbatim spans. Voyage gets 0.79 at R@1, above Greek (0.74 / 0.46); quotes go to the keyword index anyway.
- **Translations add little.** They lift the top ranks (topical R@1 0.45 → 0.61) but not the bar cells, which native already passes.

**Spelling and OCR sensitivity** (minimal pairs, scratch script, n = the targets a class changes): each of the 100 targets is rewritten in one spelling class. The table gives the cosine to the original, and "Nearest" is the share whose nearest unit among all 2,273 is still the original.

| Spelling class | n | Mean cosine | Min | Nearest |
|---|---:|---:|---:|---:|
| ى ↔ ي at word end | 91 | 0.989 | 0.944 | 1.00 |
| hamza seats dropped (أ إ آ → ا, ؤ ئ → و ي) | 56 | 0.984 | 0.924 | 1.00 |
| ة → ه at word end | 60 | 0.976 | 0.919 | 1.00 |
| harakat dropped | 32 | 0.984 | 0.953 | 1.00 |
| tatweel in every word of 4+ letters | 100 | 0.941 | 0.882 | 1.00 |
| OCR noise: every 6th dotted letter loses its dots | 99 | 0.936 | 0.776 | 1.00 |
| `fold()` | 92 | 0.975 | 0.858 | 1.00 |
| *the next unit* | 98 | 0.475 | 0.201 | – |

Voyage treats Arabic spelling variants and dot-level OCR noise as the same text, so there is no case for embedding a folded form.

**Recommendation (pending the owner's decision): no translation vectors for `arb`.** Native retrieval passes #84's bar (0.97 ≥ 0.95 paraphrase R@3, 0.97 ≥ 0.9 topical R@100), as the issue expected. Arabic is embedded in its stored spelling.

- **Cost:** review $0.61, Sol translation $2.09, Voyage about $0.05.

## Old Georgian (`oge`, #529)

Measured on 2026-10-31, BM25 and Voyage `voyage-4-large` only, with the method of the Arabic eval (`scripts.embed_eval.langset`), on master (the TITUS Bible and lectionaries #527, Wikisource #520) plus the branches of #521 (TITUS hagiography) and #526 (TITUS codices) before they merged. The TITUS texts are unpublished (`license: unknown`, #514); they were sent to Voyage and OpenAI for this internal evaluation only.

**The set:** `data/eval/oge` has 2,317 Old Georgian chunks: 50 Scripture and 50 Georgian-only targets (`--scripture-per-lang 50 --unique-per-lang 50`), every Georgian witness of the target verses, the unique targets' ±2 neighbours and 1,995 distractors, plus the WEB/KJV/ASV verses as references for the review (outside the scores).
- **Scripture (50):** 33 Oshki/Jerusalem OT verses, 9 Gospel verses (Khanmeti, Adishi, pre-Athonite, Athonite), 5 from the Epistles, 3 Psalms.
- **Georgian-only (50):** 18 from the TITUS translations (Basil's homilies, Climacus and his scholia), 17 hagiography, 6 Shatberdi codex, 5 chronicles (Kartlis Tskhovreba), 3 liturgy of St James, 1 Wikisource. The two lectionaries are left out of the unique pool (`EXCLUDED_UNIQUE_WORKS`): they are Scripture pericopes. Georgian translations of Greek works count as Georgian-only here, since their originals aren't in the one-language set.

**The queries** (`data/eval_authored/oge.jsonl`): Claude drafted 100 targets × 2 English queries from the Georgian. 20 targets are `medium` confidence. GPT-6.1 Sol reviewed them once (#87 method):
- 149 pass, 49 were corrected (12 paraphrases, 37 topical queries, mostly as too narrow) and 2 were flagged for overlap with an English Bible;
- paraphrase accuracy averaged 4.66 and topical relevance 4.76;
- Sol read 90 originals "well" and 10 "partly".

Every Georgian chunk of the set also got a Sol translation (bulk prompt, 225 requests), stored in an eval store rather than `data/translations`. A spot-check of 12 of them against the Georgian found no hallucinations or omissions; Sol marks a word it can't read with `[?]`.

| Queries | Retriever | Paraphrase R@3 S / U | Topical R@100 S / U | Topical R@1 S / U |
|---|---|---|---|---|
| all (50/50) | native | 0.82 / 0.80 | 0.80 / 0.86 | 0.30 / 0.36 |
| all (50/50) | + Sol translations | 1.00 / 1.00 | 1.00 / 1.00 | 0.70 / 0.64 |
| passing (45/41, 30/33) | native | 0.82 / 0.80 | 0.83 / 0.85 | 0.30 / 0.39 |
| passing (45/41, 30/33) | + Sol translations | 1.00 / 1.00 | 1.00 / 1.00 | 0.80 / 0.73 |
| corrected (48/50, 50/50) | native | 0.83 / 0.80 | 0.80 / 0.76 | 0.30 / 0.28 |
| corrected (48/50, 50/50) | + Sol translations | 1.00 / 1.00 | 0.98 / 1.00 | 0.58 / 0.56 |

- **Native, by text** (all queries, paraphrase R@3 / topical R@100):
  - Oshki OT 0.85 / 0.79 (n = 33), Gospels 0.78 / 0.67 (n = 9);
  - TITUS translations (Basil, Climacus) 0.67 / 0.83 (n = 18), hagiography 0.82 / 0.82 (n = 17);
  - chronicles and liturgy 1.00 / 1.00 (n = 5, 3).
- **With translations** every group reaches 1.00 on both.
- **The misses are not near misses.** Of the 19 native paraphrase misses, 8 rank 4th–8th and 11 rank 11th or lower (3 outside the top 100); the 17 topical misses are all outside the top 100.
- **Quotes:** BM25 1.00 on exact and near-verbatim spans. Voyage gets 0.80 / 0.92 at R@1 (Scripture is pessimistic: another redaction's copy of the verse at rank 1 is scored as a miss when it doesn't contain the span letter for letter).

**Spelling sensitivity** (minimal pairs, scratch script): each of the 100 targets is rewritten in one spelling class (the `fold()` rules of #525, one at a time). The table gives the cosine to the original, and "Nearest" is the share whose nearest unit among the 2,317 is still the original (or, for Scripture, a witness of the same verse).

| Spelling class | n | Mean cosine | Min | Nearest |
|---|---:|---:|---:|---:|
| ჱ → ე | 14 | 0.987 | 0.948 | 1.00 |
| ჴ → ხ | 21 | 0.977 | 0.954 | 1.00 |
| ჳ → ვ / ვი | 38 | 0.966 | 0.848 | 1.00 |
| ჲ → ი / dropped | 61 | 0.981 | 0.889 | 1.00 |
| consonantal უ → ვ | 59 | 0.977 | 0.880 | 1.00 |
| all of them: modern spelling | 89 | 0.951 | 0.660 | 1.00 |
| `fold()` | 100 | 0.921 | 0.660 | 1.00 |
| the same text in Nuskhuri script | 100 | 0.194 | 0.030 | 0.02 |
| *a neighbouring unit* | 84 | 0.462 | 0.301 | – |
| *the same verse in another witness* | 14 | 0.887 | 0.568 | – |

- **Modern spelling costs little.** Each archaic letter class costs less than another redaction of the same verse does, and an exact span typed in modern spelling (`fold()`) still finds its target at R@1 0.78 / 0.88 (as stored: 0.80 / 0.92). Keyword search folds both sides anyway.
- **Script matters.** Voyage doesn't know Nuskhuri as Georgian: the same text in Nuskhuri is farther from its Mkhedruli original than a neighbouring unit is. Every source stores Mkhedruli, so this matters only for a future source in Khutsuri (convert it at ingest).

**Decision, owner, 2026-10-31: `oge` gets translation vectors** (`TRANSLATED_LANGUAGES`): Sol in the pipeline, the first batch (the publishable Wikisource units) translated on local-opus. The recommendation: Native retrieval misses #84's bar (paraphrase R@3 0.82 / 0.80 against ≈ 0.95, topical R@100 0.80 / 0.86 against ≈ 0.9), about where Church Slavonic was (0.85 / 0.84, 0.91 / 0.84), and Sol translations bring every cell to 1.00. Georgian is embedded in its stored spelling.

- **Cost:** review $0.70, Sol translation $2.47, Voyage about $0.08 (0.64M cl100k tokens at list price).

## Old Irish (`sga`, #552)

Measured on 2026-11-01, BM25 and Voyage `voyage-4-large` only, with the method of the Old Georgian eval (`scripts.embed_eval.langset`), on master: the Würzburg glosses (#539), the Gloss Corpus Félire (#540) and the CELT texts (#541). The CELT texts are unpublished (`license: unknown`, #542); they were sent to Voyage and OpenAI for this internal evaluation only.

**The set:** `data/eval/sga` has 2,270 Old Irish chunks: 80 targets (`--scripture-per-lang 0 --unique-per-lang 80 --min-target-chars 80`, seed 0), the targets' ±2 neighbours, the other Félire edition's quatrain for each Félire target, and 1,903 distractors.
- **There is no Old Irish Scripture**, so every target is Irish-only. The Würzburg glosses, Bethu Brigte and the Vision of Laisrén have English versions in the corpus, but the one-language set holds no English, so they count as Irish-only here.
- **Four pools of 20** (`select.UNIQUE_POOLS["sga"]`): targets are drawn round-robin over the pools, then over each pool's works, so the many small CELT poems don't crowd out the rest.
  - **Würzburg glosses:** one or two per epistle.
  - **Félire Óengusso:** 10 from CELT's text (Stokes) and 10 from Gloss Corpus's diplomatic text, never the same day twice. The two editions are grouped by ref like Scripture witnesses (`langset.WITNESS_GROUPS`), so either answers a query on the other.
  - **CELT prose:** 14 works (the Lives of Adamnán and Brigit, Apgitir Chrábaid, Baile Bricín, the Vision of Laisrén, the rules, the tracts on sins, the Irish Bede and others).
  - **CELT verse:** one quatrain from each of 20 poems (Saltair na Rann among them).
- **Length:** most glosses are a few words (median 25–42 characters per epistle). Targets need at least 80 characters, so they are whole sentences; the shorter units stay in the set as neighbours and distractors.

**The queries** (`data/eval_authored/sga.jsonl`): Claude drafted 80 targets × 2 English queries from the Irish, never from the English versions. 42 targets are `medium` confidence. GPT-6.1 Sol reviewed them once (#87 method):
- 115 queries pass and 45 were corrected (29 paraphrases, mostly a misread clause; 16 topical queries, 9 as too narrow);
- paraphrase accuracy averaged 4.20 and topical relevance 4.61;
- Sol read 34 originals "well" and 46 "partly" (17 of the 20 Félire quatrains).

Every Irish chunk of the set also got a Sol translation (bulk prompt, 130 requests), stored in an eval store rather than `data/translations`.

| Queries | Retriever | Paraphrase R@3 | Topical R@100 | Topical R@1 |
|---|---|---:|---:|---:|
| all (80/80) | BM25 | 0.11 | 0.09 | 0.01 |
| all (80/80) | native | 0.47 | 0.38 | 0.06 |
| all (80/80) | + Sol translations | 1.00 | 0.95 | 0.55 |
| passing (51/64) | native | 0.41 | 0.39 | 0.08 |
| passing (51/64) | + Sol translations | 1.00 | 0.94 | 0.52 |
| corrected (80/80) | native | 0.51 | 0.38 | 0.09 |
| corrected (80/80) | + Sol translations | 1.00 | 0.94 | 0.51 |

No cell moves by 0.20 or more between the query variants (`review compare`).

By text (all queries, n = 20 each, paraphrase R@3 / topical R@100):

| Text | Native | + Sol translations |
|---|---|---|
| Würzburg glosses | 0.40 / 0.55 | 1.00 / 0.95 |
| Félire Óengusso | 0.90 / 0.50 | 1.00 / 0.95 |
| CELT prose | 0.20 / 0.15 | 1.00 / 1.00 |
| CELT verse | 0.40 / 0.30 | 1.00 / 0.90 |

- **Native Voyage barely reads Old Irish.** Of the 42 native paraphrase misses, 7 rank 4th–10th, 10 rank 11th–100th and 25 fall outside the top 100; all 50 topical misses are outside the top 100. The Félire's paraphrases score 0.90 only because they name its saints: its topical queries score 0.50.
- **Quotes:** BM25 1.00 on exact and near-verbatim spans. Voyage gets 0.93 / 0.88 at R@1.
- **With translations** paraphrase R@3 is 1.00 in every group. Topical R@1 stays low on the Félire (0.25), whose quatrains are near-identical lists of saints.

**Translation quality** (`translate quality --langs sga`, 40 targets, 10 per pool; fidelity 1–5; judges agreed exactly 62% of the time and within one point 99%; Opus said it read 8 originals well and 32 partly, Sol 17 and 23):

| Translator | Fidelity, other vendor's judge | Self-judged | Hallucinated (of 40) | $/passage |
|---|---:|---:|---:|---:|
| Opus 5.5 | 4.35 (Sol) | 4.55 | 0 | 0.0128 |
| GPT-6.1 Sol | 3.98 (Opus) | 4.22 | 0 | 0.0070 |
| Sonnet 5.5 | 3.40 | – | 0–1 | 0.0069 |
| Haiku 5.5 | 2.20–2.30 | – | 5–6 | 0.0004 |

- **Sol is weaker on Old Irish than on the other languages** (4.44 by Opus over the 151 targets above). It is weakest on CELT prose (3.80 by either judge) and the Félire (4.00 by Opus), and best on the glosses (4.20 / 4.70). Opus scores 4.20–4.70 in every group.
- **Spot check:** Claude compared 11 of Sol's translations with the Irish (glosses, Félire, prose and verse) and found no hallucinations or omissions. Two slips: *uissi* ("worthy") rendered "obedient" (Félire, 19 June), and the object of *rod-toig* ("roofed it") as "you" (*M'airiuclán*). Sol marks a word it can't read with `[?]` (*stoir*). Where Claude's draft had misread a gloss (*nianse* "it is not difficult", Wb 12d41), Sol read it right.

**Decision, owner, 2026-11-01: `sga` gets translation vectors** (`TRANSLATED_LANGUAGES`): Sol in the pipeline, the first batch (the publishable Würzburg glosses and Gloss Corpus Félire) translated on local-opus. The recommendation: native retrieval is far below #84's bar (paraphrase R@3 0.47 against ≈ 0.95, topical R@100 0.38 against ≈ 0.9), well below Old Georgian (0.80 / 0.86) and Church Slavonic, and Sol translations bring it to 1.00 / 0.95. Since Opus translates Old Irish better than Sol (4.35 against 3.98, cross-judged), the first batch was made on local-opus, as the Georgian one was. Old Irish is embedded in its stored spelling.

- **Cost:** review $1.14, translation-quality eval $3.21, Sol translation $3.95, Voyage about $0.06 (≤ 0.34M cl100k tokens at list price).

## Old Saxon (`osx`, #585)

Measured on 2026-11-02, BM25 and Voyage `voyage-4-large` only, with the Old Irish method (`scripts.embed_eval.langset`), on master with ReA 1.2 (#567): 8 works and 6,397 units, 94% of them the *Heliand*. The owner allowed no paid API but Voyage for this eval, so everything Claude did ran on `local-opus` (the Claude subscription), and the Sol steps were adapted or skipped (below).

**The set:** `data/eval/osx` has 2,162 Old Saxon chunks: 60 targets (`--scripture-per-lang 0 --unique-per-lang 60`, seed 0), their ±2 neighbours and 1,925 distractors. There is no Old Saxon Scripture, so every target is `unique`, drawn from three pools of 20 (`select.UNIQUE_POOLS["osx"]`): the *Heliand*, the *Genesis*, and the minor texts (the Bede homily, the confession, the two baptismal vows, the Gernrode Psalm commentary and the creed). Three targets were left without queries: a *Genesis* line next to another target, the creed (the same text as a Cologne baptismal vow target) and a Latin rubric. That leaves n = 20 / 19 / 18.
- **A *Heliand* or *Genesis* unit is one verse line**, 44 characters on average (#586): *Sîmon Petrus: sprak sân angegin*. A line is often a fragment of a sentence, and its ±2 neighbours, which are in the set as hard negatives, belong to the same sentence.

**The queries** (`data/eval_authored/osx.jsonl`): Claude drafted 57 targets × 2 English queries from the Old Saxon. Opus reviewed them once (`review --reviewer local-opus`; the drafter's own model family, not an independent vendor). It corrected 71 of the 114, mostly by cutting a *Heliand* or *Genesis* query down to its one line. The committed file holds the corrected queries, and the matrices above use them.

| Queries | Retriever | Paraphrase R@3 | Topical R@100 | Topical R@1 |
|---|---|---:|---:|---:|
| drafts (57/57) | BM25 | 0.05 | 0.11 | 0.02 |
| drafts (57/57) | native | 0.19 | 0.26 | 0.09 |
| drafts (57/57) | + local-opus translations | 0.72 | 0.81 | 0.30 |
| passing (20/23) | native | 0.40 | 0.35 | 0.17 |
| passing (20/23) | + local-opus translations | 1.00 | 0.91 | 0.52 |
| corrected (57/57) | BM25 | 0.07 | 0.11 | 0.04 |
| corrected (57/57) | native | 0.33 | 0.39 | 0.11 |
| corrected (57/57) | + local-opus translations | 0.98 | 0.93 | 0.54 |

Native paraphrase R@3 moves by 0.21 between the variants (`review compare`), so the drafts and the corrections disagree. The two variants still lead to the same decision: every native cell is far below the bar.

By pool (corrected queries, paraphrase R@3 / topical R@100):

| Pool | n | Native | + local-opus translations |
|---|---:|---|---|
| *Heliand* | 20 | 0.25 / 0.35 | 0.95 / 0.85 |
| *Genesis* | 19 | 0.32 / 0.37 | 1.00 / 0.95 |
| Minor texts | 18 | 0.44 / 0.44 | 1.00 / 1.00 |

- **Native Voyage barely reads Old Saxon.** That holds even when any line within ±2 of the target counts as a hit (paraphrase R@3 0.37, topical R@100 0.53).
- **The drafts score lower with translations (0.72 / 0.81)** because they describe the sentence or the scene, so a neighbouring line often wins. With a hit within ±2 lines counted, the corrected queries reach 1.00 / 1.00.
- **Quotes:** BM25 is 1.00 on exact and near-verbatim spans. Voyage gets 0.93 / 0.93 at R@1, with or without translations.
- **Gospel competition:** the *Heliand* and *Genesis* retell Scripture, so a second set (`osx-gospels`, scratch) added 31,207 verses: Genesis, the Psalms and the four Gospels in WEB, KJV, the Clementine Vulgate, SBLGNT and the LXX. A Scripture hit counts as a miss: it is not in the target's relevance set. Unfiltered, native retrieval falls further, from 0.33 / 0.39 to 0.16 / 0.16, as the English and Latin verses take the top ranks. With translations it holds at 0.93 / 0.86. Filtered to Old Saxon, as a reader who picks the language would search, the scores are those above. The queries keep to the poem's own framing (lines and wording), not the Gospel verse, so that a paraphrase of the line, not of the Gospel, is what is measured.

**Translation quality** (`translate quality --langs osx --translators local-opus --judges local-opus`, all 57 targets). Two-vendor blind judging needs Sol, so it was skipped, and Sonnet and Haiku (paid API) weren't run. Opus judged its own translations, so this is a self-judgement and reads high (compare Old Irish: Opus 4.55 self-judged, 4.35 by Sol):
- fidelity **4.58** (*Heliand* 4.75, *Genesis* 4.63, minor texts 4.33);
- 0 hallucinations; 18 mistranslations, 9 additions and 7 omissions flagged across the 57;
- the judge read 45 originals well, 10 partly and 2 poorly (the Gernrode fragments).

**Spot check:** Claude compared 15 translations with the Old Saxon. They were faithful, with no hallucinations, apart from slips caused by one-line units: *Lâte man sia forð hinan* rendered "let them be sent forth from here" (the verb *uuahsan*, "grow", is on the next line), and *giungarduom* ("service") rendered "discipleship" with a `[?]`. Opus marks gaps with `[?]` and bracketed glosses ([Phocas?] for the Bede homily's emperor).

**Decision, owner, 2026-11-02: `osx` gets translation vectors** (`TRANSLATED_LANGUAGES`). The first batch is the 62 units of the minor texts, translated on local-opus. The *Heliand* and *Genesis* (6,335 units) wait for #586, since regrouping their lines would change their refs. The recommendation: native retrieval is far below #84's bar (paraphrase R@3 0.33 against ≈ 0.95, topical R@100 0.39 against ≈ 0.9): at Old Irish's level when it was enrolled (0.47 / 0.38) and far below Old Georgian (0.82 / 0.80). With local-opus translations the scores are 0.98 / 0.93. Enrolling means translating all **6,397** units (`scripts.translate --dry-run`: 262 requests, $8.96 with Sol, or free on local-opus) and embedding a second vector for each.

- **Cost:** Voyage about $0.30 (about 1.65M cl100k tokens, most of it the Scripture of `osx-gospels`). Review, translation-quality eval and the translation of the set's 2,162 chunks ran on local-opus at no API cost: 262 requests, which took the 5-hour window from 30% to 69%, together with the sibling evals.

## Old English (`ang`, #582)

Measured on 2026-11-02, BM25 and Voyage `voyage-4-large` only, with the method of the Old Irish eval (`scripts.embed_eval.langset`), on master: the Anglo-Saxon Poetic Records (#572) and Ælfric's *Catholic Homilies* I (#580). The owner allowed no paid API but Voyage for this eval, so the review, the translations and the quality judging ran on Claude Opus 5.5 through local `claude -p` (`local-opus`, the Claude subscription): `review --reviewer local-opus`, `translate quality --translators local-opus --judges local-opus`, `scripts.translate --model local-opus`.

**The set:** `data/eval/ang` has 2,297 Old English chunks: 80 targets (`--scripture-per-lang 0 --unique-per-lang 80 --min-target-chars 80`, seed 0), the targets' ±2 neighbours and 1,918 distractors.
- **There is no Old English Scripture** in the corpus, so every target is Old English-only.
- **Thorpe's English:** `aelfric-ch-eng` is a version of every homily, but the one-language set holds no English, so a query is never answered by Thorpe instead of Ælfric. In production the two are one version group, and search folds them by the passage alignment.
- **Four pools of 20** (`select.UNIQUE_POOLS["ang"]`): religious narrative verse (Junius, Vercelli, *Judith*), the Exeter Book's religious poems, wisdom and elegy (*Wanderer*, *Seafarer*, *Maxims*, *Order of the World*, the *Meters of Boethius* …), and Ælfric. The minor poems are distractors only.

**The queries** (`data/eval_authored/ang.jsonl`): Claude drafted 80 targets × 2 English queries from the Old English, never from Thorpe. 22 targets are `medium` confidence. local-opus reviewed them once (#87 method; the drafter's own model, so less independent than Sol's reviews):
- 143 queries pass and 17 were corrected (5 paraphrases, misread clauses; 12 topical queries, 11 as too narrow);
- paraphrase accuracy averaged 4.55 and topical relevance 4.72;
- Opus read 78 originals "well" and 2 "partly".

Every Old English chunk of the set also got a local-opus translation (bulk prompt, 159 requests), stored in an eval store rather than `data/translations`.

| Queries | Retriever | Paraphrase R@3 | Topical R@100 |
|---|---|---:|---:|
| all (80/80) | BM25 | 0.12 | 0.03 |
| all (80/80) | native | 0.71 | 0.70 |
| all (80/80) | + local-opus translations | 1.00 | 0.93 |
| passing (75/68) | native | 0.73 | 0.71 |
| passing (75/68) | + local-opus translations | 1.00 | 0.94 |
| corrected (80/80) | native | 0.72 | 0.74 |
| corrected (80/80) | + local-opus translations | 1.00 | 0.95 |

No cell moves by 0.20 or more between the query variants (`review compare`). Topical R@1 is 0.20 native and 0.45 with translations.

By pool (all queries, n = 20 each, paraphrase R@3 / topical R@100):

| Pool | BM25 | Native | + local-opus translations |
|---|---|---|---|
| Religious narrative verse | 0.10 / 0.00 | 0.70 / 0.60 | 1.00 / 0.90 |
| Exeter Book religious poems | 0.05 / 0.00 | 0.70 / 0.65 | 1.00 / 0.85 |
| Wisdom and elegy | 0.15 / 0.05 | 0.50 / 0.60 | 1.00 / 0.95 |
| Ælfric's *Catholic Homilies* | 0.20 / 0.05 | 0.95 / 0.95 | 1.00 / 1.00 |

- **Native Voyage reads Ælfric's prose but not the poetry.** Late West Saxon prose, with its Latin names and near-English function words, passes the bar natively; the verse (poetic compounds, kennings, free word order) scores 0.50–0.70. Of the 23 native paraphrase misses, 12 rank 4th–10th, 7 rank 11th–100th and 4 fall outside the top 100; all 24 topical misses are outside the top 100.
- **Quotes:** BM25 1.00 on exact and near-verbatim spans; Voyage 0.78 / 0.75 at R@1.
- **With translations** paraphrase R@3 is 1.00 in every pool, and topical R@100 0.85–1.00.

**Translation quality** (`translate quality --langs ang --translators local-opus --judges local-opus`, 40 targets, 10 per pool): Opus 5.5 fidelity **4.67** self-judged (Ælfric 4.90, narrative 4.80, Exeter 4.50, wisdom 4.50), 0 hallucinations; the judge listed 14 mistranslations, 5 omissions and 3 additions over the 40, and read 37 originals well and 3 partly. **Skipped:** the second vendor's judge (Sol) and the Sol, Sonnet and Haiku translators, which need paid APIs, so there is no cross-vendor fidelity score; self-judging ran 0.20–0.30 above cross-judging for Opus in the earlier evals.
- **Spot check:** Claude compared 14 translations with the Old English (8 quality-eval targets, 6 bulk units of every pool): faithful, with no hallucinations or omissions. *Order of the World* 43 (*stiþe stefnbyrd*) is marked `[?]`, as it should be. 96 of the 2,297 bulk translations (4%) carry `[?]`.

**Decision, owner, 2026-11-02: `ang` gets translation vectors** (`TRANSLATED_LANGUAGES`), the first batch on local-opus. Native retrieval misses the bar (paraphrase R@3 0.71 against ≈ 0.95, topical R@100 0.70 against ≈ 0.9), below Old Georgian (0.82 / 0.80) though well above Old Irish (0.47 / 0.38), and translations bring it to 1.00 / 0.93. The gap is in the verse: 5,075 of the 9,234 Old English units. `TRANSLATED_LANGUAGES` is per language, so Ælfric would get translation vectors too; they don't hurt it (1.00 / 1.00).

- **Corpus to translate:** 9,132 units in 488 requests (`scripts.translate --langs ang --dry-run`; Sol estimate $12.78), done on local-opus; the eval set's 2,297 translations were reused.
- **Cost:** Voyage about $0.05 (≈ 0.22M cl100k tokens: the set, its translations and the queries). No other API was paid; the local-opus work (80 reviews, 80 quality calls, 159 bulk requests) moved the 5-hour window by about 45 points (shared with two sibling evals) and the 7-day window by 4.

## Old High German (`goh`, #584)

Measured on 2026-11-02, BM25 and Voyage `voyage-4-large` only, with the method of the Old Irish eval (`scripts.embed_eval.langset`), on master with the Referenzkorpus Altdeutsch (#576). The owner allowed no paid API but Voyage, so the query review, the translations and the translation-quality check all ran on Opus 5.5 through `local-opus` (the Claude subscription), not on Sol.

**The set:** `data/eval/goh` has 2,357 OHG chunks: 80 targets (`--scripture-per-lang 0 --unique-per-lang 80`, seed 0), the targets' ±2 neighbours and 1,969 distractors.
- **There is no OHG Scripture**, so every target is OHG-only. Tatian, Isidor, the Benedictine Rule, the Murbach Hymns and Notker's Boethius translate Latin works that are in the corpus (`rea/tatian-lat`, PL 83, …), but the one-language set holds no Latin, so a query can't be answered by the Latin instead. In production that would be a near-success (the version groups and the alignment lead to the OHG), so leaving the Latin out measures the harder case: reaching the OHG itself.
- **Four pools of 20** (`select.UNIQUE_POOLS["goh"]`): Otfrid's *Evangelienbuch*, Notker's Psalter, Tatian, and the minor texts (one unit from each of 20 other works: confessions, creeds, Lord's Prayer commentaries, *Muspilli*, the *Ludwigslied*, the Murbach Hymns, the Benedictine Rule, Notker's *Cantica*, …).
- **Otfrid's units are single long lines** (47 characters on average), so its targets are a clause or two, often meaningless without the chapter around them.
- **Notker writes Latin into his German:** 18 of the 20 Psalter targets contain the Latin psalm text or Latin terms, which Voyage reads well. That pool is reported separately.

**The queries** (`data/eval_authored/goh.jsonl`): Claude drafted 80 targets × 2 English queries from the OHG. 35 targets are `medium` confidence, mostly Otfrid lines. Opus 5.5 on `local-opus` reviewed them once (`review --reviewer local-opus`; the drafter's model family, so not an independent review): 134 pass and 26 were corrected (7 paraphrases, 19 topical queries, 18 of them as too narrow); paraphrase accuracy averaged 4.65 and topical relevance 4.61.

Every OHG chunk of the set also got an Opus translation (`scripts.translate --model local-opus`, bulk prompt, 139 requests), stored in an eval store rather than `data/translations`.

| Queries | Retriever | Paraphrase R@3 | Topical R@100 | Topical R@1 |
|---|---|---:|---:|---:|
| all (80/80) | BM25 | 0.01 | 0.06 | 0.01 |
| all (80/80) | native | 0.36 | 0.44 | 0.15 |
| all (80/80) | + Opus translations | 1.00 | 0.94 | 0.62 |
| passing (73/61) | native | 0.37 | 0.46 | 0.16 |
| passing (73/61) | + Opus translations | 1.00 | 0.98 | 0.67 |
| corrected (80/80) | native | 0.36 | 0.44 | 0.14 |
| corrected (80/80) | + Opus translations | 1.00 | 0.97 | 0.62 |

No cell moves by 0.20 or more between the query variants (`review compare`).

By text (all queries, n = 20 each, paraphrase R@3 / topical R@100):

| Text | Native | + Opus translations |
|---|---|---|
| Otfrid | 0.00 / 0.10 | 1.00 / 0.75 |
| Notker's Psalter | 0.80 / 0.80 | 1.00 / 1.00 |
| Tatian | 0.35 / 0.50 | 1.00 / 1.00 |
| minor texts | 0.30 / 0.35 | 1.00 / 1.00 |

- **Native Voyage reads OHG poorly**, below Old Irish (0.47 / 0.38) on paraphrases. Of the 51 native paraphrase misses, 35 fall outside the top 100.
- **What it does find, it finds through Latin and names.** Notker's Psalter scores 0.80 because of its Latin: both of its targets with no Latin miss outright. Elsewhere the hits are mostly units with Latin (the interlinear prayer fragment, Notker's *Cantica*) or with names (Pilate and Barabbas, Peter, Louis). Without the Psalter, the three other pools average 0.22 / 0.32.
- **Otfrid is unreachable natively** (0.00 / 0.10). Even with translations its topical R@100 is 0.75: a single line rarely carries a topic.
- **Unit length and neighbours** (as for Old Saxon, #586): the mean target is 44 characters in Otfrid (one line per unit; the *Muspilli*, *Ludwigslied*, *Georgslied* and *Petruslied* among the minor targets are lines too), 111 in Notker's Psalter (derived verses of its paragraphs), 199 in Tatian and 121 in the minor texts. Counting a hit on the target's ±2 neighbours as well lifts native Voyage from 0.36 / 0.44 to 0.44 / 0.65 overall, but Otfrid's paraphrases stay at 0.00 (topical 0.10 → 0.25): the lines are short, and Voyage doesn't read them either way. With translations, ±2 lifts Otfrid's topical R@100 from 0.75 to 0.95 (#588).
- **Quotes:** BM25 0.96 at R@1 on exact and near-verbatim spans, Voyage 0.80 / 0.81.
- **With translations**, paraphrase R@3 is 1.00 in every pool. The queries, the review and the translations all come from Claude models, so shared phrasing may flatter these numbers somewhat; the Irish run, with Sol translations, also reached 1.00.

**Translation quality** (`translate quality --langs goh --translators local-opus local-haiku --judges local-opus`): 80 targets (all of them); both translators use the per-passage prompt, and Opus judged both blind, under shuffled labels. There was no second vendor, so Opus judged its own work: treat its own score as an upper bound. Haiku is there as a contrast, to show that the judge separates good from bad translations.

| Translator | Fidelity (Opus judge) | Otfrid | Notker's Psalter | Tatian | minor | Hallucinated (of 80) |
|---|---:|---:|---:|---:|---:|---:|
| Opus 5.5 (`local-opus`) | 4.83 (self) | 4.85 | 4.80 | 4.85 | 4.80 | 0 |
| Haiku 5.5 (`local-haiku`) | 3.20 | 2.45 | 3.40 | 4.15 | 2.80 | 1 |

The judge said it read 74 originals well and 6 partly. Haiku does well only on Tatian, where it can lean on the Gospel text. Skipped: the cross-vendor judging (#84 used Sol and the API Opus) and the Sol and API translators, because they are paid APIs.

- **Spot check:** Claude compared 14 random Opus translations from the set with the OHG (Notker's Psalter, *Cantica* and Boethius, Tatian, Otfrid, the Murbach Hymns, the Monsee fragments) and found no hallucinations or omissions. Opus marks a word it can't read with `[?]`: 167 of the 2,357 units (7 %). The share is highest in the fragmentary Monsee texts and the interlinear glosses (Murbach Hymns 9 of 20, *Carmen ad Deum* 4 of 5); Notker's Psalter has 59 of 812, Otfrid 30 of 807 and Tatian 1 of 233.

**Decision, owner, 2026-11-02 (with Old English and Old Saxon): `goh` gets translation vectors** (`TRANSLATED_LANGUAGES`): Sol in the pipeline, the first batch on `local-opus`, and Otfrid and the verse poems only after their lines are regrouped (#586). The recommendation: native retrieval is far below #84's bar (paraphrase R@3 0.36 against ≈ 0.95, topical R@100 0.44 against ≈ 0.9), and the Latin in Notker's works carries most of what it finds. Opus translations bring it to 1.00 / 0.94. The corpus has 21,434 OHG units: 1,025 bulk requests, about $30 on Sol, or about a quarter of the 7-day subscription window on `local-opus` at this eval's rate (the 139 requests, with the 80 review requests alongside, moved the 7-day window from 39 % to 43 % and the 5-hour window from 30 % to 75 %), so it would be spread over several 5-hour windows.

- **Cost:** Voyage about $0.04 (the set, its translations and the queries, ≤ 0.25M cl100k tokens at list price); everything else on the subscription, at no API cost.

## Not evaluated

- **Qwen3-Embedding and multilingual-e5-large-instruct:** too slow on this machine's CPU (#85). Local Ollama is the likely route for Qwen3.
- **SPhilBerta:** dropped. It covers only Greek, Latin and English and was weakest everywhere in the first round.

## Cost of the evaluation

| Item | Cost |
|---|---:|
| Translation-quality eval (#3) | $15.14 |
| Query review, two passes (#87) | $3.92 |
| Sol translation of the eval corpus (#84) | $15.58 |
| Embeddings | a few dollars, mostly OpenAI and Gemini 3072-dim |
