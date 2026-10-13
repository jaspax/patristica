# Machine translations

English translations of Syriac, Coptic, Armenian and Ge'ez chunks, used to
index those languages for search (#84, #93). There is one JSONL file per
model, e.g. `gpt-6.1-sol.jsonl`, sorted by `chunk_id`. Each row:

| field | meaning |
|---|---|
| `chunk_id`, `language` | the chunk translated |
| `source_sha256` | first 16 hex digits of SHA-256 of the exact source text; a row is reused only while the chunk's text still matches |
| `translation` | English text |
| `model`, `prompt_version`, `date` | provenance (`prompt_version` names the prompt in `scripts/embed_eval/translate.py`) |
| `group_size` | how many consecutive chunks of the same work were translated in one request |

Written by `python -m scripts.embed_eval.translate bulk --model sol`. That
command skips chunks that already have a fresh translation, so reruns and the
production pipeline (#93) only pay for new or changed text.

**Licensing:** a translation is a derivative of its source text and carries that
text's licence (`Work.license`; see `DATA_LICENSE.md`). If these are ever
shown to users rather than only indexed, label them as AI translations.
