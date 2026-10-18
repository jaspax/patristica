"""Vector search over the search database (#141; IMPLEMENTATION_PLAN.md §2.4).

``Searcher.search`` embeds the query with Voyage ``voyage-4-large``
(``input_type="query"``), cuts it to the stored 512 dims with ``shorten``,
and ranks ``chunk_vectors`` of the same model by cosine distance through the
model's HNSW index. A chunk with a translation vector scores the better of its
two vectors and appears once. Filters are columns of ``chunk_vectors``
(``db/schema.sql``), and the HNSW scan is iterative, so narrow filters still
fill a page.

Quoted queries are meant for the keyword index (#86, #143). ``parse_query``
recognises them; until that index exists they fall back to vector search on
the unquoted text, and the response says so.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from patristica.embedders import ApiError, VoyageEmbedder, shorten
from patristica.sources import source_label

if TYPE_CHECKING:
    import numpy as np
    from psycopg_pool import ConnectionPool

log = logging.getLogger(__name__)

MODEL = "voyage-4-large"
MODEL_NAME = f"voyage/{MODEL}"  # embedding_models.name
DIMS = 512
DOCUMENT_INPUT = "document"  # the input type of the stored vectors
MAX_QUERY_CHARS = 500
MAX_LIMIT = 50
MAX_OFFSET = 500
TEXT_CHARS = 2000  # longer chunk texts are cut in results (a few Scripture chapters)
EF_SEARCH = 100
TRANSLATION_LANGUAGE = "eng"
ANONYMOUS = "anonymous"  # author filter value for works with no author_ids

_QUOTED = re.compile(r'^\s*["“”](.+?)["“”]\s*$', re.DOTALL)
_SPACE = re.compile(r"\s+")


class SearchUnavailable(RuntimeError):
    """The query could not be embedded (no key, Voyage down or slow, or the index is missing)."""


@dataclass(frozen=True)
class ParsedQuery:
    mode: Literal["vector", "phrase"]
    text: str


def normalize_query(q: str) -> str:
    """Whitespace collapsed and trimmed: the text that is embedded and cached."""
    return _SPACE.sub(" ", q).strip()


def parse_query(q: str) -> ParsedQuery:
    """A query in double quotes is a phrase search (#86); anything else is semantic."""
    text = normalize_query(q)
    m = _QUOTED.match(text)
    if m and m.group(1).strip():
        return ParsedQuery("phrase", normalize_query(m.group(1)))
    return ParsedQuery("vector", text)


@dataclass
class Filters:
    language: list[str] = field(default_factory=list)
    genre: list[str] = field(default_factory=list)
    source: list[str] = field(default_factory=list)
    work: list[str] = field(default_factory=list)
    author: list[str] = field(default_factory=list)  # author ids, or ANONYMOUS
    date_from: int | None = None
    date_to: int | None = None
    include_out_of_period: bool = False

    def sql(self) -> tuple[str, dict[str, Any]]:
        """WHERE conditions on ``chunk_vectors`` (``AND``-joined) and their parameters."""
        conds, params = [], {}
        for name in ("language", "genre", "source", "work"):
            values = getattr(self, name)
            if values:
                column = {"source": "source_id", "work": "work_id"}.get(name, name)
                conds.append(f"{column} = ANY(%({name})s)")
                params[name] = values
        if self.author:
            ids = [a for a in self.author if a != ANONYMOUS]
            parts = ["author_ids && %(author)s::text[]"] if ids else []
            if ANONYMOUS in self.author:
                parts.append("author_ids = '{}'")
            conds.append("(" + " OR ".join(parts) + ")")
            if ids:
                params["author"] = ids
        if self.date_from is not None or self.date_to is not None:
            # Undated chunks can't match a date filter.
            conds.append("date_range && int4range(%(date_from)s, %(date_to)s, '[]')")
            params["date_from"], params["date_to"] = self.date_from, self.date_to
        if not self.include_out_of_period:
            conds.append("NOT out_of_period")
        return " AND ".join(conds) or "TRUE", params


class QueryEmbedder:
    """Embeds queries with Voyage, failing fast, with an LRU cache of the vectors.

    Every miss is a paid Voyage call, so repeated queries (and paging through
    results) are served from the cache.
    """

    def __init__(self, make_client: Callable[[], Any] | None = None, cache_size: int = 10_000,
                 timeout: float = 5.0) -> None:
        self._make_client = make_client or (
            lambda: VoyageEmbedder(MODEL, timeout=timeout, retries=1))
        self._client: Any = None
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._size = cache_size
        self._lock = threading.Lock()

    def embed(self, text: str) -> tuple[np.ndarray, bool]:
        """(unit vector of DIMS dims, whether it came from the cache)."""
        with self._lock:
            if text in self._cache:
                self._cache.move_to_end(text)
                return self._cache[text], True
        try:
            if self._client is None:
                self._client = self._make_client()
            raw = self._client.embed_batch([text], "query")
        except KeyError as exc:  # env_key: VOYAGE_API_KEY not set
            raise SearchUnavailable("search is not configured on this server") from exc
        except ApiError as exc:
            log.warning("query embedding failed: %s", exc)
            raise SearchUnavailable("the embedding service did not answer in time") from exc
        vec = shorten(raw, DIMS)[0]
        with self._lock:
            self._cache[text] = vec
            while len(self._cache) > self._size:
                self._cache.popitem(last=False)
        return vec, False


class RateLimiter:
    """A token bucket per client: *rate* requests a minute, bursts up to *burst*."""

    def __init__(self, rate: float = 30, burst: int = 10,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.rate, self.burst, self._clock = rate / 60, burst, clock
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> float:
        """0 if *key* may go ahead (and counts it), else the seconds until it may."""
        now = self._clock()
        with self._lock:
            tokens, then = self._buckets.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - then) * self.rate)
            if tokens < 1:
                self._buckets[key] = (tokens, now)
                return (1 - tokens) / self.rate
            self._buckets[key] = (tokens - 1, now)
            if len(self._buckets) > 10_000:  # forget clients whose bucket is full again
                full = now - self.burst / self.rate
                self._buckets = {k: v for k, v in self._buckets.items() if v[1] > full}
            return 0.0


def citation(authors: list[str], title: str, ref: str) -> str:
    """``{author}, *{title}* {ref}`` (IMPLEMENTATION_PLAN.md §3.2), without the author if none."""
    head = f"*{title}* {ref}"
    return f"{' and '.join(authors)}, {head}" if authors else head


def _vec_literal(vec: np.ndarray) -> str:
    return "[" + ",".join(f"{float(x):.6g}" for x in vec) + "]"


_SEARCH_SQL = """
WITH hits AS MATERIALIZED (
    SELECT chunk_id, kind, embedding <=> %(q)s::halfvec AS distance
    FROM chunk_vectors
    WHERE model_id = {model_id} AND {where}
    ORDER BY embedding <=> %(q)s::halfvec
    LIMIT %(fetch)s
), best AS (
    SELECT DISTINCT ON (chunk_id) chunk_id, kind, distance
    FROM hits ORDER BY chunk_id, distance
)
SELECT b.distance, b.kind, c.chunk_id, c.work_id, c.canonical_ref, c.language,
       left(c.text, %(text_chars)s), length(c.text) > %(text_chars)s,
       c.date_composed, lower(c.date_range), upper(c.date_range) - 1, c.out_of_period,
       t.text, t.model,
       w.title, w.author_ids, w.source_id, w.edition, w.license, w.provenance_url,
       w.genre, w.tradition, w.date_composed, lower(w.date_range), upper(w.date_range) - 1,
       coalesce((SELECT array_agg(a.name ORDER BY i.n) FROM unnest(w.author_ids)
                 WITH ORDINALITY AS i(id, n) JOIN authors a ON a.author_id = i.id), '{{}}')
FROM best b
JOIN chunks c ON c.chunk_id = b.chunk_id
JOIN works w ON w.work_id = c.work_id
LEFT JOIN chunk_translations t ON t.chunk_id = c.chunk_id AND t.language = %(tr_lang)s
ORDER BY b.distance, c.chunk_id
OFFSET %(offset)s LIMIT %(limit)s
"""


def _range(lo: int | None, hi: int | None) -> list[int] | None:
    return None if lo is None else [lo, hi]


def _result(row: tuple) -> dict[str, Any]:
    (distance, kind, chunk_id, work_id, ref, language, text, truncated, c_date, c_lo, c_hi,
     out_of_period, tr_text, tr_model, title, author_ids, source_id, edition, license_,
     provenance_url, genre, tradition, w_date, w_lo, w_hi, author_names) = row
    names = list(author_names)
    return {
        "chunk_id": chunk_id,
        "work_id": work_id,
        "canonical_ref": ref,
        "language": language,
        "text": text,
        "text_truncated": truncated,
        "translation": None if tr_text is None else {
            "language": TRANSLATION_LANGUAGE, "text": tr_text, "model": tr_model,
            "machine": True},
        "score": round(1 - float(distance), 4),
        "matched": "translation" if kind == 1 else "text",
        "date_composed": c_date,
        "date_range": _range(c_lo, c_hi),
        "out_of_period": out_of_period,
        "citation": citation(names, title, ref),
        "work": {
            "title": title,
            "authors": [{"id": i, "name": n} for i, n in zip(author_ids, names)],
            "genre": genre,
            "tradition": tradition,
            "date_composed": w_date,
            "date_range": _range(w_lo, w_hi),
            "edition": edition,
            "source_label": source_label(source_id),
            "license": license_,
            "provenance_url": provenance_url,
        },
    }


class Searcher:
    def __init__(self, pool: ConnectionPool, embedder: QueryEmbedder,
                 ef_search: int = EF_SEARCH) -> None:
        self.pool, self.embedder, self.ef_search = pool, embedder, ef_search
        self._model_id: int | None = None

    def model_id(self, conn: Any) -> int:
        if self._model_id is None:
            row = conn.execute(
                "SELECT model_id FROM embedding_models WHERE name = %s AND dims = %s "
                "AND input_type = %s", (MODEL_NAME, DIMS, DOCUMENT_INPUT)).fetchone()
            if row is None:
                raise SearchUnavailable(f"the search index has no {MODEL_NAME} vectors")
            self._model_id = int(row[0])
        return self._model_id

    def search(self, q: str, filters: Filters, limit: int = 20, offset: int = 0
               ) -> dict[str, Any]:
        parsed = parse_query(q)
        # Phrase search needs the keyword index (#86); until then, search semantically.
        started = time.monotonic()
        vec, cached = self.embedder.embed(parsed.text)
        embedded = time.monotonic()
        where, params = filters.sql()
        params.update(q=_vec_literal(vec), fetch=2 * (offset + limit + 1), offset=offset,
                      limit=limit + 1, text_chars=TEXT_CHARS, tr_lang=TRANSLATION_LANGUAGE)
        with self.pool.connection() as conn, conn.transaction():
            # Inlined, not a parameter: a generic plan of a prepared statement
            # can't prove model_id = n, so it would never use the partial index.
            sql = _SEARCH_SQL.format(model_id=self.model_id(conn), where=where)
            conn.execute("SELECT set_config('hnsw.ef_search', %s, true), "
                         "set_config('hnsw.iterative_scan', 'relaxed_order', true)",
                         (str(self.ef_search),))
            rows = conn.execute(sql, params).fetchall()
        done = time.monotonic()
        log.info("search: %d chars, %s, embed %.0f ms (%s), db %.0f ms, %d rows",
                 len(parsed.text), parsed.mode, 1000 * (embedded - started),
                 "cached" if cached else "voyage", 1000 * (done - embedded), len(rows))
        more = len(rows) > limit
        return {
            "query": parsed.text,
            "mode": "vector",
            "requested_mode": parsed.mode,
            "model": MODEL_NAME,
            "offset": offset,
            "limit": limit,
            "next_offset": offset + limit if more and offset + limit <= MAX_OFFSET else None,
            "results": [_result(r) for r in rows[:limit]],
        }
