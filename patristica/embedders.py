"""
Embedding API clients shared by the pipeline (``scripts.embed``), the search
API and the eval harness (``scripts.embed_eval``).

- ``ApiEmbedder`` batches texts and POSTs them with retry/backoff. Rate-limit
  and server errors are retried; other refusals raise ``ApiError``.
- ``VoyageEmbedder`` is the production model, Voyage ``voyage-4-large``
  (decided in #84; ``docs/embedding-eval.md``). It counts the tokens Voyage
  bills in ``tokens_used``.
- ``shorten`` cuts vectors to their first *dims* components and renormalizes
  them (Matryoshka shortening; the DB stores 512 of the 1024 dims, #50).

API keys are read from the environment or the repo-root ``.env``
(``env_key``). Needs numpy (the ``embed`` extra).
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger(__name__)

RETRIES = 8
# Rate limits clear on their own, so 429s get far more patience (~75 minutes).
RATE_LIMIT_RETRIES = 40


class ApiError(RuntimeError):
    """An embedding API refused a request after retries (bad key, quota exhausted, ...)."""


def cl100k() -> Any:
    import tiktoken

    return tiktoken.get_encoding("cl100k_base")


def env_key(name: str, env_file: Path = Path(".env")) -> str:
    """The value of *name* from the environment, else from *env_file*."""
    if os.environ.get(name):
        return os.environ[name]
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            k, sep, v = line.partition("=")
            if sep and k.strip() == name and not k.lstrip().startswith("#"):
                return v.strip().strip("'\"")
    raise KeyError(f"{name} is not set (environment or {env_file})")


class ApiEmbedder:
    """Base class: batches texts and POSTs them with retry/backoff.

    Batches are capped by count (``batch_size``) and by estimated tokens
    (``max_batch_tokens``, counted with cl100k_base). ``rpm`` / ``tpm`` pace
    requests to stay inside a plan's rate limits; ``max_input_tokens``
    truncates single inputs locally for APIs that reject long ones.
    ``embed_batch`` sends one request as is, for callers that batch
    themselves; it is safe to call from several threads.
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
        self._lock = threading.Lock()
        self.tokens_used = 0  # billed tokens, for APIs that report them

    def _count(self, tokens: int) -> None:
        with self._lock:
            self.tokens_used += tokens

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
        enc = cl100k()
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

    def embed_batch(self, texts: list[str], kind: str = "document") -> np.ndarray:
        """Embed *texts* in a single request (no splitting, truncation or pacing)."""
        import numpy as np

        return np.asarray(self._embed(texts, kind), dtype=np.float32)

    def embed_documents(self, texts: list[str]) -> np.ndarray:
        return self._run(texts, "document")

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._run(texts, "query")


class VoyageEmbedder(ApiEmbedder):
    # Paid tier. Voyage caps a request at 120k of its own tokens and counts rare
    # scripts at up to ~2x cl100k, hence 30k estimated. (Without a payment
    # method the limits are 3 requests and 10k tokens a minute; #85.)
    batch_size = 1000  # API maximum per request
    max_batch_tokens = 30_000

    def __init__(self, model: str = "voyage-4-large", dims: int | None = None) -> None:
        super().__init__()
        self.model, self.name, self.dims = model, f"voyage/{model}", dims
        self._key = env_key("VOYAGE_API_KEY")

    def _embed(self, texts: list[str], kind: str) -> list[list[float]]:
        body: dict[str, Any] = {"model": self.model, "input": texts, "input_type": kind}
        if self.dims is not None:
            body["output_dimension"] = self.dims
        j = self._post("https://api.voyageai.com/v1/embeddings",
                       {"Authorization": f"Bearer {self._key}"}, body)
        self._count(j.get("usage", {}).get("total_tokens", 0))
        return [d["embedding"] for d in sorted(j["data"], key=lambda d: d["index"])]


def shorten(vecs: np.ndarray, dims: int) -> np.ndarray:
    """The first *dims* components of each row of *vecs*, renormalized (float32).

    For Voyage voyage-4-large this matches requesting ``output_dimension``
    (cosine 1.0 on a spot check in #3), so one stored 1024-dim vector serves
    every smaller size.
    """
    import numpy as np

    v = np.asarray(vecs, dtype=np.float32)
    if v.ndim != 2 or v.shape[1] < dims:
        raise ValueError(f"cannot shorten vectors of shape {v.shape} to {dims} dims")
    v = v[:, :dims]
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.where(norms == 0, 1, norms)
