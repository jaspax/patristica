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

### exact (R@1)

| retriever | grc S | grc U | lat S | lat U | hbo S | hye S | hye U | gez S | gez U | cop S | cop U | syc S | syc U | mean |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BM25 (keyword) | 1.00 | 0.83 | 1.00 | 0.89 | 1.00 | 1.00 | 0.71 | 1.00 | 0.99 | 1.00 | 0.98 | 1.00 | 0.78 | **0.94** |
| OpenAI text-embedding-3-large | 0.72 | 0.25 | 0.83 | 0.56 | 0.90 | 0.56 | 0.00 | 0.68 | 0.49 | 0.39 | 0.45 | 0.61 | 0.01 | **0.50** |
| OpenAI text-embedding-3-large + Sol translations | 0.72 | 0.25 | 0.83 | 0.56 | 0.90 | 0.56 | 0.00 | 0.68 | 0.49 | 0.39 | 0.45 | 0.61 | 0.01 | **0.50** |
| Voyage voyage-4-large | 0.74 | 0.46 | 0.91 | 0.61 | 0.95 | 0.86 | 0.25 | 0.85 | 0.75 | 0.93 | 0.86 | 0.95 | 0.22 | **0.72** |
| Voyage voyage-4-large + Sol translations | 0.74 | 0.46 | 0.91 | 0.61 | 0.95 | 0.86 | 0.25 | 0.85 | 0.75 | 0.93 | 0.86 | 0.95 | 0.22 | **0.72** |
| Cohere embed-v4.0 | 0.85 | 0.43 | 0.93 | 0.64 | 0.94 | 0.89 | 0.07 | 0.50 | 0.49 | 0.27 | 0.32 | 0.67 | 0.00 | **0.54** |
| Cohere embed-v4.0 + Sol translations | 0.85 | 0.43 | 0.93 | 0.64 | 0.94 | 0.89 | 0.07 | 0.50 | 0.49 | 0.27 | 0.32 | 0.67 | 0.00 | **0.54** |
| Gemini gemini-embedding-2 | 0.70 | 0.24 | 0.89 | 0.56 | 0.93 | 0.35 | 0.01 | 0.43 | 0.39 | 0.55 | 0.55 | 0.80 | 0.00 | **0.49** |
| Gemini gemini-embedding-2 + Sol translations | 0.70 | 0.24 | 0.89 | 0.56 | 0.93 | 0.35 | 0.01 | 0.43 | 0.39 | 0.55 | 0.55 | 0.80 | 0.00 | **0.49** |
| BGE-M3 (local) | 0.72 | 0.26 | 0.83 | 0.50 | 0.69 | 0.74 | 0.08 | 0.67 | 0.59 | 0.00 | 0.06 | 0.24 | 0.00 | **0.41** |
| BGE-M3 (local) + Sol translations | 0.72 | 0.26 | 0.83 | 0.50 | 0.69 | 0.74 | 0.08 | 0.67 | 0.59 | 0.00 | 0.06 | 0.24 | 0.00 | **0.41** |
| *n* | 100 | 100 | 99 | 98 | 96 | 100 | 100 | 100 | 100 | 98 | 99 | 100 | 69 | |

### near (R@1)

| retriever | grc S | grc U | lat S | lat U | hbo S | hye S | hye U | gez S | gez U | cop S | cop U | syc S | syc U | mean |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BM25 (keyword) | 1.00 | 0.83 | 1.00 | 0.89 | 1.00 | 1.00 | 0.71 | 1.00 | 0.99 | 1.00 | 0.98 | 1.00 | 0.78 | **0.94** |
| OpenAI text-embedding-3-large | 0.60 | 0.13 | 0.81 | 0.52 | 0.81 | 0.50 | 0.00 | 0.64 | 0.46 | 0.38 | 0.24 | 0.52 | 0.00 | **0.43** |
| OpenAI text-embedding-3-large + Sol translations | 0.60 | 0.13 | 0.81 | 0.52 | 0.81 | 0.50 | 0.00 | 0.64 | 0.46 | 0.38 | 0.24 | 0.52 | 0.00 | **0.43** |
| Voyage voyage-4-large | 0.67 | 0.39 | 0.92 | 0.61 | 0.94 | 0.85 | 0.28 | 0.82 | 0.75 | 0.93 | 0.85 | 0.93 | 0.09 | **0.69** |
| Voyage voyage-4-large + Sol translations | 0.67 | 0.39 | 0.92 | 0.61 | 0.94 | 0.85 | 0.28 | 0.82 | 0.75 | 0.93 | 0.85 | 0.93 | 0.09 | **0.69** |
| Cohere embed-v4.0 | 0.73 | 0.36 | 0.93 | 0.64 | 0.69 | 0.87 | 0.05 | 0.48 | 0.45 | 0.24 | 0.18 | 0.60 | 0.00 | **0.48** |
| Cohere embed-v4.0 + Sol translations | 0.73 | 0.36 | 0.93 | 0.64 | 0.69 | 0.87 | 0.05 | 0.48 | 0.45 | 0.24 | 0.18 | 0.60 | 0.00 | **0.48** |
| Gemini gemini-embedding-2 | 0.39 | 0.02 | 0.88 | 0.48 | 0.79 | 0.13 | 0.00 | 0.14 | 0.19 | 0.53 | 0.44 | 0.66 | 0.00 | **0.36** |
| Gemini gemini-embedding-2 + Sol translations | 0.39 | 0.02 | 0.88 | 0.48 | 0.79 | 0.13 | 0.00 | 0.14 | 0.19 | 0.53 | 0.44 | 0.66 | 0.00 | **0.36** |
| BGE-M3 (local) | 0.52 | 0.15 | 0.79 | 0.50 | 0.44 | 0.71 | 0.05 | 0.70 | 0.61 | 0.00 | 0.00 | 0.16 | 0.00 | **0.36** |
| BGE-M3 (local) + Sol translations | 0.52 | 0.15 | 0.79 | 0.50 | 0.44 | 0.71 | 0.05 | 0.69 | 0.61 | 0.00 | 0.00 | 0.16 | 0.00 | **0.36** |
| *n* | 100 | 100 | 99 | 98 | 96 | 100 | 100 | 100 | 100 | 98 | 99 | 100 | 69 | |

### paraphrase (R@3)

| retriever | grc S | grc U | lat S | lat U | hbo S | hye S | hye U | gez S | gez U | cop S | cop U | syc S | syc U | mean |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BM25 (keyword) | 0.00 | 0.00 | 0.10 | 0.17 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | **0.02** |
| OpenAI text-embedding-3-large | 1.00 | 0.89 | 1.00 | 1.00 | 1.00 | 0.05 | 0.05 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | **0.38** |
| OpenAI text-embedding-3-large + Sol translations | 1.00 | 0.89 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.90 | **0.98** |
| Voyage voyage-4-large | 1.00 | 1.00 | 1.00 | 1.00 | 0.90 | 0.70 | 0.85 | 0.15 | 0.07 | 0.00 | 0.00 | 0.45 | 0.00 | **0.55** |
| Voyage voyage-4-large + Sol translations | 1.00 | 1.00 | 1.00 | 1.00 | 0.90 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | **0.99** |
| Cohere embed-v4.0 | 1.00 | 0.74 | 1.00 | 1.00 | 0.50 | 0.20 | 0.25 | 0.05 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | **0.36** |
| Cohere embed-v4.0 + Sol translations | 1.00 | 0.74 | 1.00 | 1.00 | 0.50 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | **0.94** |
| Gemini gemini-embedding-2 | 1.00 | 0.84 | 1.00 | 1.00 | 1.00 | 0.90 | 0.95 | 1.00 | 0.93 | 0.50 | 0.50 | 1.00 | 0.35 | **0.84** |
| Gemini gemini-embedding-2 + Sol translations | 1.00 | 0.84 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.55 | **0.95** |
| BGE-M3 (local) | 0.85 | 0.89 | 1.00 | 0.94 | 0.55 | 0.80 | 0.90 | 0.40 | 0.53 | 0.00 | 0.06 | 0.00 | 0.00 | **0.53** |
| BGE-M3 (local) + Sol translations | 0.85 | 0.89 | 1.00 | 0.94 | 0.55 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.95 | **0.94** |
| *n* | 20 | 19 | 20 | 18 | 20 | 20 | 20 | 20 | 15 | 20 | 16 | 20 | 20 | |

### topical (R@100)

| retriever | grc S | grc U | lat S | lat U | hbo S | hye S | hye U | gez S | gez U | cop S | cop U | syc S | syc U | mean |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BM25 (keyword) | 0.00 | 0.00 | 0.20 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | **0.02** |
| OpenAI text-embedding-3-large | 0.90 | 0.89 | 0.90 | 0.94 | 0.85 | 0.15 | 0.05 | 0.10 | 0.00 | 0.00 | 0.00 | 0.10 | 0.10 | **0.38** |
| OpenAI text-embedding-3-large + Sol translations | 0.90 | 0.89 | 0.90 | 0.94 | 0.85 | 1.00 | 1.00 | 1.00 | 1.00 | 0.95 | 0.94 | 0.90 | 1.00 | **0.94** |
| Voyage voyage-4-large | 1.00 | 1.00 | 1.00 | 1.00 | 0.95 | 0.80 | 0.90 | 0.30 | 0.40 | 0.05 | 0.19 | 0.50 | 0.45 | **0.66** |
| Voyage voyage-4-large + Sol translations | 1.00 | 1.00 | 1.00 | 1.00 | 0.95 | 1.00 | 1.00 | 1.00 | 1.00 | 0.95 | 0.94 | 1.00 | 1.00 | **0.99** |
| Cohere embed-v4.0 | 0.30 | 0.74 | 0.70 | 1.00 | 0.40 | 0.25 | 0.40 | 0.10 | 0.00 | 0.00 | 0.06 | 0.05 | 0.15 | **0.32** |
| Cohere embed-v4.0 + Sol translations | 0.30 | 0.74 | 0.70 | 1.00 | 0.40 | 1.00 | 1.00 | 0.85 | 1.00 | 0.90 | 1.00 | 0.90 | 1.00 | **0.83** |
| Gemini gemini-embedding-2 | 1.00 | 0.89 | 1.00 | 0.94 | 0.95 | 0.95 | 0.85 | 0.95 | 1.00 | 0.70 | 0.44 | 0.90 | 0.65 | **0.86** |
| Gemini gemini-embedding-2 + Sol translations | 1.00 | 0.89 | 1.00 | 0.94 | 0.95 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 | 0.94 | 0.95 | 0.85 | **0.96** |
| BGE-M3 (local) | 0.45 | 0.74 | 0.80 | 0.89 | 0.50 | 0.40 | 0.55 | 0.40 | 0.47 | 0.00 | 0.12 | 0.00 | 0.00 | **0.41** |
| BGE-M3 (local) + Sol translations | 0.45 | 0.74 | 0.80 | 0.89 | 0.50 | 0.55 | 1.00 | 0.90 | 1.00 | 0.75 | 0.81 | 0.65 | 0.95 | **0.77** |
| *n* | 20 | 19 | 20 | 18 | 20 | 20 | 20 | 20 | 15 | 20 | 16 | 20 | 20 | |

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
