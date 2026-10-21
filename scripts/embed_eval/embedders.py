"""
Embedding models the eval can score (``--retriever dense:NAME``).

``EMBEDDERS`` maps a name to a zero-argument factory returning an
``Embedder`` (see ``retrieval.Embedder``). Factories import their backend
lazily, so a missing optional dependency only matters for the model actually
requested.

- API models read their key from the environment or the repo-root ``.env``
  (``OPENAI_API_KEY``, ``VOYAGE_API_KEY``, ``COHERE_API_KEY``,
  ``GEMINI_API_KEY``). They retry rate-limit and server errors with backoff
  and raise ``ApiError`` when a quota is exhausted. The base class and
  ``VoyageEmbedder`` live in ``patristica.embedders``.
- Local models run on CPU through sentence-transformers (``uv sync --extra
  eval-local``). Inputs are truncated to ``LOCAL_MAX_TOKENS`` to keep CPU time
  bounded; eval chunks are at most 2,000 characters.

Wrap any embedder in ``CachedEmbedder`` to store vectors in SQLite as they
are computed, so an interrupted or quota-limited run resumes where it stopped.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tqdm import tqdm

from patristica.embedders import (  # noqa: F401  (re-exported for the eval)
    ApiEmbedder,
    ApiError,
    VoyageEmbedder,
    env_key,
    shorten,
)
from scripts.embed_eval.retrieval import Embedder

if TYPE_CHECKING:
    import numpy as np

LOCAL_MAX_TOKENS = 512
INSTRUCTION = "Given a search query, retrieve relevant passages from early Christian texts"
_env_key = env_key


# --- API embedders (the base class and Voyage live in patristica.embedders) -----

class OpenAIEmbedder(ApiEmbedder):
    max_input_tokens = 8191  # exact: the model uses cl100k_base
    max_batch_tokens = 250_000  # per-request limit is 300k

    def __init__(self, model: str = "text-embedding-3-large") -> None:
        super().__init__()
        self.model, self.name = model, f"openai/{model}"
        self._key = _env_key("OPENAI_API_KEY")

    def _embed(self, texts: list[str], kind: str) -> list[list[float]]:
        j = self._post("https://api.openai.com/v1/embeddings",
                       {"Authorization": f"Bearer {self._key}"},
                       {"model": self.model, "input": texts})
        return [d["embedding"] for d in sorted(j["data"], key=lambda d: d["index"])]


class CohereEmbedder(ApiEmbedder):
    # 96 texts is the API maximum. Production key; trial keys allow only 100k
    # tokens a minute and 1,000 calls a month (#85).
    batch_size = 96
    max_batch_tokens = 40_000

    def __init__(self, model: str = "embed-v4.0") -> None:
        super().__init__()
        self.model, self.name = model, f"cohere/{model}"
        self._key = _env_key("COHERE_API_KEY")

    def _embed(self, texts: list[str], kind: str) -> list[list[float]]:
        j = self._post("https://api.cohere.com/v2/embed",
                       {"Authorization": f"Bearer {self._key}"},
                       {"model": self.model, "texts": texts, "truncate": "END",
                        "input_type": f"search_{kind}", "embedding_types": ["float"]})
        return j["embeddings"]["float"]


class GeminiEmbedder(ApiEmbedder):
    # 100 texts is the batchEmbedContents maximum. Paid tier; the free tier
    # counts every text as a request (100 a minute, 1,000 a day; #85).
    batch_size = 100
    max_batch_tokens = 40_000

    def __init__(self, model: str = "gemini-embedding-2") -> None:
        super().__init__()
        self.model, self.name = model, f"gemini/{model}"
        self._key = _env_key("GEMINI_API_KEY")

    def _embed(self, texts: list[str], kind: str) -> list[list[float]]:
        task = "RETRIEVAL_DOCUMENT" if kind == "document" else "RETRIEVAL_QUERY"
        reqs = [{"model": f"models/{self.model}", "content": {"parts": [{"text": t}]},
                 "taskType": task} for t in texts]
        j = self._post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}"
            ":batchEmbedContents",
            {"x-goog-api-key": self._key}, {"requests": reqs})
        return [e["values"] for e in j["embeddings"]]


# --- local embedders ----------------------------------------------------------

class LocalEmbedder:
    """A sentence-transformers model on CPU, with optional query/document prompts."""

    batch_size = 16

    def __init__(
        self,
        model_id: str,
        *,
        query_prompt: str | None = None,
        query_prompt_name: str | None = None,
        document_prompt: str | None = None,
        trust_remote_code: bool = False,
    ) -> None:
        import torch
        from sentence_transformers import SentenceTransformer

        torch.set_num_threads(os.cpu_count() or 4)
        self.name = model_id
        self.model = SentenceTransformer(model_id, device="cpu",
                                         trust_remote_code=trust_remote_code)
        self.model.max_seq_length = min(self.model.max_seq_length or LOCAL_MAX_TOKENS,
                                        LOCAL_MAX_TOKENS)
        self.query_prompt, self.query_prompt_name = query_prompt, query_prompt_name
        self.document_prompt = document_prompt

    def _encode(self, texts: list[str], **kw: Any) -> np.ndarray:
        return self.model.encode(texts, batch_size=self.batch_size, convert_to_numpy=True,
                                 normalize_embeddings=True, **kw)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts, prompt=self.document_prompt)

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        if self.query_prompt_name:
            return self._encode(texts, prompt_name=self.query_prompt_name)
        return self._encode(texts, prompt=self.query_prompt)


# --- shortened vectors -----------------------------------------------------------

class Truncated:
    """Keep the first *dims* components and renormalize (Matryoshka shortening).

    For OpenAI text-embedding-3 this is documented as equivalent to requesting
    ``dimensions``; for Voyage voyage-4-large it matches ``output_dimension``
    (cosine 1.0 on a spot check). Wrap the cached embedder, so one cache
    serves every size.
    """

    def __init__(self, inner: Embedder, dims: int) -> None:
        self.inner, self.dims = inner, dims
        self.name = f"{inner.name}@{dims}"

    def _cut(self, vecs: np.ndarray) -> np.ndarray:
        return shorten(vecs, self.dims)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._cut(self.inner.embed_documents(texts))

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._cut(self.inner.embed_queries(texts))


# --- cache --------------------------------------------------------------------

class CachedEmbedder:
    """Store every vector in SQLite (keyed by kind + text hash) as soon as it is computed."""

    def __init__(self, inner: Embedder, path: Path, batch_size: int | None = None) -> None:
        self.inner, self.name = inner, inner.name
        # Large cache batches let sentence-transformers sort by length (less padding).
        self.batch_size = batch_size or max(getattr(inner, "batch_size", 64) * 4, 256)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute("CREATE TABLE IF NOT EXISTS emb "
                        "(kind TEXT, h TEXT, vec BLOB, PRIMARY KEY (kind, h))")

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def _get(self, texts: list[str], kind: str) -> np.ndarray:
        import numpy as np

        hashes = [self._hash(t) for t in texts]
        found: dict[str, np.ndarray] = {}
        for i in range(0, len(hashes), 500):
            part = hashes[i:i + 500]
            rows = self.db.execute(
                f"SELECT h, vec FROM emb WHERE kind = ? AND h IN ({','.join('?' * len(part))})",
                [kind, *part])
            found.update((h, np.frombuffer(v, dtype=np.float32)) for h, v in rows)
        missing = sorted({h: t for h, t in zip(hashes, texts) if h not in found}.items())
        if missing:
            fn = self.inner.embed_documents if kind == "document" else self.inner.embed_queries
            bar = tqdm(total=len(missing), desc=f"{self.name} {kind}s", unit="text")
            for i in range(0, len(missing), self.batch_size):
                batch = missing[i:i + self.batch_size]
                vecs = np.asarray(fn([t for _, t in batch]), dtype=np.float32)
                self.db.executemany("INSERT OR REPLACE INTO emb VALUES (?, ?, ?)",
                                    [(kind, h, v.tobytes()) for (h, _), v in zip(batch, vecs)])
                self.db.commit()
                found.update((h, v) for (h, _), v in zip(batch, vecs))
                bar.update(len(batch))
            bar.close()
        return np.stack([found[h] for h in hashes])

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._get(texts, "document")

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._get(texts, "query")


# --- registry -------------------------------------------------------------------

EMBEDDERS: dict[str, Callable[[], Embedder]] = {
    "openai/text-embedding-3-large": lambda: OpenAIEmbedder("text-embedding-3-large"),
    "voyage/voyage-4-large": lambda: VoyageEmbedder("voyage-4-large"),
    "cohere/embed-v4.0": lambda: CohereEmbedder("embed-v4.0"),
    "gemini/gemini-embedding-2": lambda: GeminiEmbedder("gemini-embedding-2"),
    "BAAI/bge-m3": lambda: LocalEmbedder("BAAI/bge-m3"),
    "intfloat/multilingual-e5-large-instruct": lambda: LocalEmbedder(
        "intfloat/multilingual-e5-large-instruct",
        query_prompt=f"Instruct: {INSTRUCTION}\nQuery: "),
    "Qwen/Qwen3-Embedding-0.6B": lambda: LocalEmbedder(
        "Qwen/Qwen3-Embedding-0.6B", query_prompt=f"Instruct: {INSTRUCTION}\nQuery:"),
    "bowphs/SPhilBerta": lambda: LocalEmbedder("bowphs/SPhilBerta"),
}


def get_embedder(name: str) -> Embedder:
    try:
        factory = EMBEDDERS[name]
    except KeyError:
        known = ", ".join(sorted(EMBEDDERS))
        raise KeyError(f"Unknown embedder {name!r} (available: {known})") from None
    return factory()
