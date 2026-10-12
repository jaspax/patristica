"""
Embedding models the eval can score (``--retriever dense:NAME``).

``EMBEDDERS`` maps a name to a zero-argument factory returning an
``Embedder`` (see ``retrieval.Embedder``). Factories import their backend
lazily, so a missing optional dependency only matters for the model actually
requested.

- API models read their key from the environment or the repo-root ``.env``
  (``OPENAI_API_KEY``, ``VOYAGE_API_KEY``, ``COHERE_API_KEY``,
  ``GEMINI_API_KEY``). They retry rate-limit and server errors with backoff
  and raise ``ApiError`` when a quota is exhausted.
- Local models run on CPU through sentence-transformers (``uv sync --extra
  eval-local``). Inputs are truncated to ``LOCAL_MAX_TOKENS`` to keep CPU time
  bounded; eval chunks are at most 2,000 characters.

Wrap any embedder in ``CachedEmbedder`` to store vectors in SQLite as they
are computed, so an interrupted or quota-limited run resumes where it stopped.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from tqdm import tqdm

from scripts.embed_eval.retrieval import Embedder

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger(__name__)

LOCAL_MAX_TOKENS = 512
RETRIES = 8
INSTRUCTION = "Given a search query, retrieve relevant passages from early Christian texts"


class ApiError(RuntimeError):
    """An embedding API refused a request after retries (bad key, quota exhausted, ...)."""


def _env_key(name: str, env_file: Path = Path(".env")) -> str:
    if os.environ.get(name):
        return os.environ[name]
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() == name and not k.lstrip().startswith("#"):
                return v.strip().strip("'\"")
    raise KeyError(f"{name} is not set (environment or {env_file})")


# --- API embedders ------------------------------------------------------------

class ApiEmbedder:
    """Base class: batches texts and POSTs them with retry/backoff."""

    name: str
    batch_size: int = 64

    def __init__(self) -> None:
        import httpx

        self._client = httpx.Client(timeout=120)

    def _post(self, url: str, headers: dict[str, str], body: dict[str, Any]) -> dict:
        import httpx

        delay = 2.0
        for attempt in range(1, RETRIES + 1):
            try:
                r = self._client.post(url, headers=headers, json=body)
            except httpx.TransportError as e:
                status, detail = None, f"{type(e).__name__}"
            else:
                if r.status_code == 200:
                    return r.json()
                status, detail = r.status_code, r.text[:300]
                if status not in (408, 429) and status < 500:
                    raise ApiError(f"{self.name}: HTTP {status}: {detail}")
                retry_after = r.headers.get("retry-after")
                if retry_after and retry_after.replace(".", "", 1).isdigit():
                    delay = max(delay, float(retry_after))
            if attempt == RETRIES:
                raise ApiError(f"{self.name}: gave up after {RETRIES} tries: {status} {detail}")
            log.warning("%s: %s, retrying in %.0fs", self.name, status or detail, delay)
            time.sleep(delay)
            delay = min(delay * 2, 120)
        raise AssertionError("unreachable")

    def _embed(self, texts: list[str], kind: str) -> list[list[float]]:
        raise NotImplementedError

    def _run(self, texts: list[str], kind: str) -> np.ndarray:
        import numpy as np

        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            out.extend(self._embed(texts[i:i + self.batch_size], kind))
        return np.asarray(out, dtype=np.float32)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._run(texts, "document")

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._run(texts, "query")


class OpenAIEmbedder(ApiEmbedder):
    def __init__(self, model: str = "text-embedding-3-large") -> None:
        super().__init__()
        self.model, self.name = model, f"openai/{model}"
        self._key = _env_key("OPENAI_API_KEY")

    def _embed(self, texts: list[str], kind: str) -> list[list[float]]:
        j = self._post("https://api.openai.com/v1/embeddings",
                       {"Authorization": f"Bearer {self._key}"},
                       {"model": self.model, "input": texts})
        return [d["embedding"] for d in sorted(j["data"], key=lambda d: d["index"])]


class VoyageEmbedder(ApiEmbedder):
    def __init__(self, model: str = "voyage-4-large") -> None:
        super().__init__()
        self.model, self.name = model, f"voyage/{model}"
        self._key = _env_key("VOYAGE_API_KEY")

    def _embed(self, texts: list[str], kind: str) -> list[list[float]]:
        j = self._post("https://api.voyageai.com/v1/embeddings",
                       {"Authorization": f"Bearer {self._key}"},
                       {"model": self.model, "input": texts, "input_type": kind})
        return [d["embedding"] for d in sorted(j["data"], key=lambda d: d["index"])]


class CohereEmbedder(ApiEmbedder):
    batch_size = 96  # API maximum; trial keys allow 1,000 calls a month

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
    batch_size = 100  # batchEmbedContents maximum

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
        from sentence_transformers import SentenceTransformer

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


# --- cache --------------------------------------------------------------------

class CachedEmbedder:
    """Store every vector in SQLite (keyed by kind + text hash) as soon as it is computed."""

    def __init__(self, inner: Embedder, path: Path, batch_size: int | None = None) -> None:
        self.inner, self.name = inner, inner.name
        self.batch_size = batch_size or getattr(inner, "batch_size", 64) * 4
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
