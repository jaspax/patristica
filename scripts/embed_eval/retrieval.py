"""
Retrievers scored by the eval.

Every retriever answers ``search(queries, k, allowed)`` with, per query, the
corpus positions of its top *k* hits. *allowed* optionally restricts each
query to a subset of positions (the language filter a user would set).

- ``BM25`` — lexical baseline over ``textfold.fold`` tokens: the text index
  that quoted and near-verbatim search will use in production.
- ``Dense`` — cosine similarity over embeddings from any ``Embedder`` (wrap
  it in ``embedders.CachedEmbedder`` to keep vectors across runs).
- ``RRF`` — reciprocal rank fusion of several retrievers (hybrid search).

Dense retrieval needs the ``eval`` extra (``uv sync --extra eval``).
"""

from __future__ import annotations

import heapq
import logging
import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

from patristica.textfold import fold

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger(__name__)

Allowed = Sequence[frozenset[int] | None] | None


class Retriever(Protocol):
    name: str

    def search(self, queries: list[str], k: int, allowed: Allowed = None) -> list[list[int]]: ...


class Embedder(Protocol):
    """An embedding model. Implementations add any query/passage prefixes themselves."""

    name: str

    def embed_documents(self, texts: list[str]) -> np.ndarray: ...

    def embed_queries(self, texts: list[str]) -> np.ndarray: ...


class BM25:
    name = "bm25"

    def __init__(self, docs: list[str], k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self.postings: dict[str, list[tuple[int, int]]] = defaultdict(list)
        self.lengths: list[int] = []
        for i, doc in enumerate(docs):
            tokens = fold(doc).split()
            self.lengths.append(len(tokens))
            for term, tf in Counter(tokens).items():
                self.postings[term].append((i, tf))
        n = len(docs)
        self.avgdl = (sum(self.lengths) / n) if n else 0.0
        self.idf = {
            t: math.log(1 + (n - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.postings.items()
        }

    def scores(self, query: str) -> dict[int, float]:
        acc: dict[int, float] = defaultdict(float)
        for term in set(fold(query).split()):
            idf = self.idf.get(term)
            if idf is None:
                continue
            for doc, tf in self.postings[term]:
                norm = self.k1 * (1 - self.b + self.b * self.lengths[doc] / self.avgdl)
                acc[doc] += idf * tf * (self.k1 + 1) / (tf + norm)
        return acc

    def search(self, queries: list[str], k: int, allowed: Allowed = None) -> list[list[int]]:
        out = []
        for qi, q in enumerate(queries):
            mask = allowed[qi] if allowed is not None else None
            items = self.scores(q).items()
            if mask is not None:
                items = [(d, s) for d, s in items if d in mask]
            top = heapq.nlargest(k, items, key=lambda x: (x[1], -x[0]))
            out.append([d for d, _ in top])
        return out


class Dense:
    def __init__(self, embedder: Embedder, texts: list[str]) -> None:
        import numpy as np

        self.name = f"dense:{embedder.name}"
        self.embedder = embedder
        log.info("%s: embedding %d documents", self.name, len(texts))
        self.docs = _normalize(np.asarray(embedder.embed_documents(texts), dtype=np.float32))

    def search(self, queries: list[str], k: int, allowed: Allowed = None) -> list[list[int]]:
        import numpy as np

        q = _normalize(np.asarray(self.embedder.embed_queries(queries), dtype=np.float32))
        sims = q @ self.docs.T
        out = []
        for qi in range(len(queries)):
            row = sims[qi]
            mask = allowed[qi] if allowed is not None else None
            if mask is not None:
                idx = np.fromiter(sorted(mask), dtype=np.int64, count=len(mask))
                if not len(idx):
                    out.append([])
                    continue
                sub = row[idx]
                top = idx[np.argsort(-sub, kind="stable")[:k]]
            else:
                top = np.argsort(-row, kind="stable")[:k]
            out.append([int(i) for i in top])
        return out


def _normalize(m: np.ndarray) -> np.ndarray:
    import numpy as np

    norms = np.linalg.norm(m, axis=1, keepdims=True)
    return m / np.where(norms == 0, 1, norms)


class RRF:
    """Weighted reciprocal rank fusion: score(d) = Σ w_r / (c + rank_r(d)) over retrievers r."""

    def __init__(
        self,
        retrievers: list[Retriever],
        weights: list[float] | None = None,
        c: int = 60,
        depth: int = 100,
    ) -> None:
        self.retrievers, self.c, self.depth = retrievers, c, depth
        self.weights = weights or [1.0] * len(retrievers)
        if len(self.weights) != len(retrievers):
            raise ValueError("one weight per retriever")
        self.name = "hybrid:" + "+".join(
            r.name if w == 1.0 else f"{r.name}@{w:g}" for r, w in zip(retrievers, self.weights)
        )

    def search(self, queries: list[str], k: int, allowed: Allowed = None) -> list[list[int]]:
        depth = max(k, self.depth)
        runs = [r.search(queries, depth, allowed) for r in self.retrievers]
        out = []
        for qi in range(len(queries)):
            score: dict[int, float] = defaultdict(float)
            for run, w in zip(runs, self.weights):
                for rank, d in enumerate(run[qi], start=1):
                    score[d] += w / (self.c + rank)
            out.append([d for d, _ in sorted(score.items(), key=lambda x: (-x[1], x[0]))[:k]])
        return out
