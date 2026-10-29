# Machine translations

Patristica gives an English **machine translation (MT)** to works the library has no English version of (#422). There are about 2,150 such works, some 284M characters, nearly all Latin and Greek. They are translated gradually, on the Claude subscription, by a nightly agent (#425). This page covers what qualifies, what an MT is in the data, and how it moves through the pipeline. Choosing a translator and watching usage is `docs/translation-backends.md`.

## What gets translated

`patristica/machine_translation.py` decides, and `python -m scripts.machine_translate candidates` lists the candidates with their sizes. A work is a candidate when:

- **Its version group has no English.** Neither a published translation nor an MT, among all versions of the work (`patristica/versions.py`). A published English version always wins: an MT whose group later gains one is *redundant*, and `scripts.export_library` leaves it out of the library.
- **It is the original.** It has no `translation_of`, or its original isn't in the corpus (an Armenian version of a lost Greek work). An ancient version of an original we have isn't translated, unless it diverges from the original in ways that matter to readers and researchers. Such a version is listed in `patristica/data/mt_exceptions.csv` (`work_id,reason`), and is then translated even if its group has English, until English made from it exists.
- **It is the best edition.** Where a group has two originals in one language, only one is translated: critical and digital editions (PTA, First1K, Perseus, CSEL, …) before Migne's OCR (`EDITION_PREFERENCE`).
- **It is publishable and isn't Scripture.** Every Scripture book has English versions, and a Scripture source would need a versification scheme.

Which candidates go first is the nightly agent's judgement: well-known, influential works and works important in their tradition first, works whose English is already widely available later (#425).

## What an MT is

An MT is a work of the derived source **`mt-eng`**. Its raw file is `data/raw/mt-eng/{the original's normalized path}`, written by `scripts.machine_translate translate WORK_ID`. Unlike the rest of `data/raw`, it is **plain git, not git-lfs** (`.gitattributes`), so a PR shows the translation itself.

- **`work`**: the original's metadata, in English.
  - `work_id` is `mt-eng/{original id}` and `translation_of` is the original.
  - The author, title, dates, genre, tradition and licence are the original's. Our changes to a text go out under its licence (`DATA_LICENSE.md`).
  - The `edition` begins "Machine translation ({model}, Patristica, {date}) of:".
  - There are no `external_ids`: `translation_of` already joins the version group.
- **`paragraphs`**: one per paragraph of the original, with the original's ref.
  - The original's derived verses are joined back into their paragraph.
  - A work its ingestor delivered as verses keeps them as **`verses`**.
  - Each unit records `source_sha`, the hash of the source text it was translated from.
  - A unit that was editorial as a whole in the original (an added title or heading, #236) is translated and marked editorial again, so readers see it and it is never embedded.
- **`machine_translation`**: provenance. Normalize ignores this key.
  - It records the model that answered, the prompt version, the date, the original's id and path, and the number of requests.

Whether a work is MT is decided by its `source_id` (`patristica.sources.MACHINE_TRANSLATION_SOURCES`), never by a `Work` field: adding a field to `patristica/models.py` would change every ingest stamp (#130). `mt-eng` has no ingestor, so `scripts.status` expects no ingest stamp for it.

## How it is translated

`scripts.machine_translate` sends **paragraphs, not chunks**:

- One request holds a chapter, several short sections, or the whole work: consecutive paragraphs of a section (the ref without its last segment), up to `DOC_MAX_CHARS` (about 20k characters) of source.
- A longer section is split at paragraph boundaries, and each part gets the paragraphs before it as context.
- The prompt (`DOCUMENT_SYSTEM`, `PROMPT_VERSION`) asks for a faithful, complete, fluent translation for readers, one item per numbered paragraph.
- Each response must have every paragraph, none empty, at a plausible length (`RATIO_BAND`). A request that fails is retried once.

A work is all or nothing. Finished requests are kept in `logs/mt-partial/` (gitignored), so a work that stops resumes where it left off, and the raw file is written only when every request is done.

The default translator is `local-opus`, Claude Opus through `claude -p` on the subscription. Its 5-hour and 7-day usage is logged but never enforced. `--model opus` and `--model sol` use the APIs and cost money.

**Staleness.** When an original's text changes, `scripts.machine_translate stale` lists the MT works whose paragraphs no longer match, and `translate WORK_ID --update` re-translates only the requests with a changed paragraph. A change that only moves derived verses doesn't make an MT stale, since its units are paragraphs.

## Through the pipeline

An MT PR adds only the raw file, so it needs no issue (CLAUDE.md, "Branches and pull requests"). The next `scripts.pipeline` run takes it like any new work:

1. **normalize** builds it as a new work of `mt-eng`.
2. **anchor** cuts its derived verses where the original's are (`mt-eng` is in `patristica/data/anchored_sources.csv`, #304). It embeds the MT's segments with Voyage, a few cents a work, and writes their vectors to `data/embeddings`. The original needs current vectors (or, for a rare language, its translation vectors).
3. **embed** keeps its vectors current. They exist for alignment, never for search.
4. **align** aligns it with its original. Their derived verses are cut alike, so the passages pair 1:1 for parallel reading.
5. **build_index** loads its work and chunks but **no vectors**, so vector search never returns it. **Keyword search** skips it too (`api/keyword.py`). Under a hit on its original, the search context may show it as the English after every published version, as `machine: true`, with its `work_id` and `canonical_ref` (`api/context.py`).
6. **export_library** writes `machine_translation: true` on its `index.json` row, and the reader labels it with a disclaimer (#424).

`tests/test_machine_translation.py` checks that every tracked MT names its original in the corpus.

## Disclaimer

The reader shows every MT with a short notice: the English was machine-translated from the original by an AI model, has not been reviewed, and may contain errors, so readers should consult the original for close study (#424).
