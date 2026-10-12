"""
Embedding-model evaluation harness (issue #3).

The eval answers one question: which retrieval setup makes every supported
original language searchable, whatever the query language? It runs on a
sampled sub-corpus, not the full index, so a model can be scored in minutes.

Pipeline::

    python -m scripts.embed_eval.build   # data/chunks → data/eval/{corpus,queries}.jsonl
    python -m scripts.embed_eval.run --retriever bm25 [--retriever dense:NAME ...]

Modules:

- ``select``   — choose target passages and assemble the sampled corpus
- ``queries``  — generate exact-quote and near-verbatim queries and their relevance sets
- ``retrieval``— retriever interface: BM25 (folded text), dense (any embedder), RRF hybrid
- ``metrics``  — recall@k / MRR, broken down by mode, target language and origin

Query modes (see #3): ``exact`` (partial quote in the original language,
target expected at rank 1), ``near`` (the same quote with orthography changed,
rank 1–3), ``paraphrase`` (loose English rendering, top 3) and ``topical``
(target anywhere in the top K). Only ``exact`` and ``near`` are generated
automatically; the other two are authored query sets added later.
"""
