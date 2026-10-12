"""
Score retrievers on the eval corpus and queries built by ``scripts.embed_eval.build``.

Each retriever is run twice per query: over the whole corpus (``all``) and
restricted to the target language (``lang``), as a user filtering by
language would. Writes per-query ranks and summaries to
``data/eval/results/{retriever}.json`` and prints one table per scope.

Retriever specs: ``bm25``, ``dense:NAME`` (see ``embedders.EMBEDDERS``), and
``hybrid:A+B`` for reciprocal rank fusion of any of those.

Usage::

    python -m scripts.embed_eval.run --retriever bm25 --retriever hybrid:bm25+dense:NAME
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from scripts.embed_eval.embedders import CachedEmbedder, get_embedder
from scripts.embed_eval.metrics import breakdown, first_rank, markdown_table
from scripts.embed_eval.queries import DEFAULT_AUTHORED, Query, load_authored
from scripts.embed_eval.retrieval import BM25, RRF, Dense, Retriever

log = logging.getLogger(__name__)

DEFAULT_DIR = Path("data/eval")
TOP_K = 100
SCOPES = ("all", "lang")


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def make_retriever(spec: str, corpus: list[dict], cache_dir: Path | None) -> Retriever:
    if spec.startswith("hybrid:"):
        parts = spec.removeprefix("hybrid:").split("+")
        if len(parts) < 2:
            raise ValueError(f"hybrid needs at least two retrievers: {spec!r}")
        return RRF([make_retriever(p, corpus, cache_dir) for p in parts])
    texts = [c["text"] for c in corpus]
    if spec == "bm25":
        return BM25(texts)
    if spec.startswith("dense:"):
        embedder = get_embedder(spec.removeprefix("dense:"))
        if cache_dir is not None:
            safe = embedder.name.replace("/", "__")
            embedder = CachedEmbedder(embedder, cache_dir / f"{safe}.sqlite")
        return Dense(embedder, texts)
    raise ValueError(f"Unknown retriever spec {spec!r}")


def evaluate(retriever: Retriever, corpus: list[dict], queries: list[Query]) -> dict:
    ids = [c["chunk_id"] for c in corpus]
    by_lang: dict[str, set[int]] = {}
    for i, c in enumerate(corpus):
        by_lang.setdefault(c["language"], set()).add(i)
    frozen = {lang: frozenset(s) for lang, s in by_lang.items()}
    texts = [q.text for q in queries]

    per_query: dict[str, dict[str, int | None]] = {q.query_id: {} for q in queries}
    summaries = {}
    for scope in SCOPES:
        allowed = None
        if scope == "lang":
            allowed = [frozen.get(q.target_lang, frozenset()) for q in queries]
        runs = retriever.search(texts, TOP_K, allowed)
        rows = []
        for q, hits in zip(queries, runs, strict=True):
            rank = first_rank([ids[h] for h in hits], q.relevant_ids)
            per_query[q.query_id][scope] = rank
            rows.append(((q.mode, q.target_lang, q.origin), rank))
        summaries[scope] = breakdown(rows)
    return {"retriever": retriever.name, "per_query": per_query, "summaries": summaries}


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--eval-dir", type=Path, default=DEFAULT_DIR)
    p.add_argument("--retriever", action="append", required=True, help="repeatable")
    p.add_argument("--mode", action="append", help="only these query modes (repeatable)")
    p.add_argument("--authored", type=Path, default=DEFAULT_AUTHORED,
                   help="directory of authored query files (*.jsonl)")
    p.add_argument("--no-cache", action="store_true", help="don't cache embeddings")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    corpus = load_jsonl(args.eval_dir / "corpus.jsonl")
    queries = [Query.from_json(d) for d in load_jsonl(args.eval_dir / "queries.jsonl")]
    queries += load_authored(sorted(args.authored.glob("*.jsonl")), corpus)
    if args.mode:
        queries = [q for q in queries if q.mode in args.mode]
    cache_dir = None if args.no_cache else args.eval_dir / "embeddings"
    out_dir = args.eval_dir / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    failed = []
    for spec in args.retriever:
        try:
            retriever = make_retriever(spec, corpus, cache_dir)
            result = evaluate(retriever, corpus, queries)
        except Exception:
            # One model's quota or outage must not stop an overnight batch.
            log.exception("%s failed; continuing with the next retriever", spec)
            failed.append(spec)
            continue
        path = out_dir / (retriever.name.replace("/", "__").replace(":", "_") + ".json")
        serial = {
            **result,
            "summaries": {
                scope: [{"mode": k[0], "lang": k[1], "origin": k[2], **v} for k, v in s.items()]
                for scope, s in result["summaries"].items()
            },
        }
        path.write_text(json.dumps(serial, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        for scope in SCOPES:
            print(f"\n## {retriever.name} — scope: {scope}\n")
            print(markdown_table(result["summaries"][scope], ("mode", "lang", "origin")))
        log.info("Wrote %s", path)
    if failed:
        log.error("Failed retrievers: %s", ", ".join(failed))
        raise SystemExit(1)


if __name__ == "__main__":
    main()
