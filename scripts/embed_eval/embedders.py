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
import re
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
# Rate limits clear on their own, so 429s get far more patience (~75 minutes).
RATE_LIMIT_RETRIES = 40
INSTRUCTION = "Given a search query, retrieve relevant passages from early Christian texts"


class ApiError(RuntimeError):
    """An embedding API refused a request after retries (bad key, quota exhausted, ...)."""


def _encoding() -> Any:
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


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
    """Base class: batches texts and POSTs them with retry/backoff.

    Batches are capped by count (``batch_size``) and by estimated tokens
    (``max_batch_tokens``, counted with cl100k_base). ``rpm`` / ``tpm`` pace
    requests to stay inside a plan's rate limits; ``max_input_tokens``
    truncates single inputs locally for APIs that reject long ones.
    """

    name: str
    batch_size: int = 64
    max_batch_tokens: int | None = None
    max_input_tokens: int | None = None
    rpm: float | None = None
    tpm: float | None = None

    def __init__(self) -> None:
        import httpx

        self._client = httpx.Client(timeout=120)

    def _post(self, url: str, headers: dict[str, str], body: dict[str, Any]) -> dict:
        import httpx

        delay = 2.0
        attempt = 0
        while True:
            attempt += 1
            try:
                r = self._client.post(url, headers=headers, json=body)
            except httpx.TransportError as e:
                status, detail = None, f"{type(e).__name__}"
            else:
                if r.status_code == 200:
                    return r.json()
                status, detail = r.status_code, r.text[:1000]
                if status not in (408, 429) and status < 500:
                    raise ApiError(f"{self.name}: HTTP {status}: {detail}")
                retry_after = r.headers.get("retry-after")
                if retry_after and retry_after.replace(".", "", 1).isdigit():
                    delay = max(delay, float(retry_after))
            limit = RATE_LIMIT_RETRIES if status == 429 else RETRIES
            if attempt >= limit:
                raise ApiError(f"{self.name}: gave up after {attempt} tries: {status} {detail}")
            quota = re.search(r"Quota exceeded for metric: [^\n]*|rate limit[^\"]*", detail)
            log.warning("%s: %s %s, retrying in %.0fs", self.name, status or detail,
                        quota.group(0) if quota else "", delay)
            time.sleep(delay)
            delay = min(delay * 2, 120)

    def _embed(self, texts: list[str], kind: str) -> list[list[float]]:
        raise NotImplementedError

    def _batches(self, texts: list[str]) -> list[tuple[list[str], int]]:
        """Split *texts* into (batch, estimated tokens), truncating long inputs."""
        enc = _encoding()
        batches: list[tuple[list[str], int]] = []
        cur: list[str] = []
        cur_tokens = 0
        for text in texts:
            tokens = enc.encode(text)
            if self.max_input_tokens and len(tokens) > self.max_input_tokens:
                tokens = tokens[:self.max_input_tokens]
                text = enc.decode(tokens)
            n = len(tokens)
            full = len(cur) >= self.batch_size or (
                self.max_batch_tokens is not None and cur_tokens + n > self.max_batch_tokens)
            if cur and full:
                batches.append((cur, cur_tokens))
                cur, cur_tokens = [], 0
            cur.append(text)
            cur_tokens += n
        if cur:
            batches.append((cur, cur_tokens))
        return batches

    def _run(self, texts: list[str], kind: str) -> np.ndarray:
        import numpy as np

        out: list[list[float]] = []
        for batch, tokens in self._batches(texts):
            started = time.monotonic()
            out.extend(self._embed(batch, kind))
            wait = max(60 / self.rpm if self.rpm else 0, tokens * 60 / self.tpm if self.tpm else 0)
            time.sleep(max(0.0, wait - (time.monotonic() - started)))
        return np.asarray(out, dtype=np.float32)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._run(texts, "document")

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._run(texts, "query")


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


class VoyageEmbedder(ApiEmbedder):
    # Without a payment method Voyage allows 3 requests and 10k tokens a minute.
    # Voyage counts rare scripts at up to ~2x cl100k, hence the wide margin.
    max_batch_tokens = 4000
    rpm = 3
    tpm = 4000

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
    # 96 texts is the API maximum. Trial keys allow 100k tokens a minute and
    # 1,000 calls a month, so batches are large and paced well under the limit.
    batch_size = 96
    max_batch_tokens = 15_000
    tpm = 40_000

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
    # 100 texts is the batchEmbedContents maximum. The free tier counts every
    # text as a request (100 a minute), so send at most one batch a minute.
    batch_size = 100
    max_batch_tokens = 12_000
    rpm = 0.9
    tpm = 12_000

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
