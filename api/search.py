"""Search over the search database (#141, #143; IMPLEMENTATION_PLAN.md §2.4).

``parse_query`` splits a query into quoted phrases and free text. A query
with a phrase runs **keyword** search (``api.keyword``, #86): every phrase
must occur as whole words, and the free text, if any, ranks the matches by
meaning. A query without one runs **vector** search. The two are routed, not
fused (#3). Keyword results carry the match offsets for highlighting.

For vector search, ``Searcher.search`` embeds the query with Voyage ``voyage-4-large``
(``input_type="query"``), cuts it to the stored 512 dims with ``shorten``,
and ranks ``chunk_vectors`` of the same model by cosine distance through the
model's HNSW index. A chunk with a translation vector scores the better of its
two vectors and appears once. The versions of one passage (``api.passages``,
#180) fold into one result, led by the best-scoring one, with the others in
``versions``. Each page scans only as many candidates as the results up to
it need (``pool_size``, #251), folded before paging. Pages follow a cursor
(``Cursor``): the next page is the leads after the last one shown, by
distance and chunk id. Filters are columns of ``chunk_vectors``
(``db/schema.sql``) and apply before folding, and the HNSW scan is
iterative, so narrow filters still fill a page.

Each result of either mode comes with the unit before and after it, and an
English version of all three when it is not in English (``api.context``).
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from api.context import add_context
from api.keyword import Hit, phrase_search
from api.passages import passage_group
from patristica.embedders import ApiError, VoyageEmbedder, shorten
from patristica.keyword import match_spans, phrase_pattern
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
MAX_DEPTH = 200  # results shown before the last page a query can reach
MAX_CURSOR_CHARS = 1000
# Each page scans just enough candidate rows for the results up to it (and one
# more, to tell whether there is a next page), with two rows per chunk at most
# (text and translation vectors). A cold scan costs a random read per HNSW
# page it visits, so a fixed pool sized for the deepest page made every first
# page ~10x slower (#249).
#
# The pool is folded by passage group before paging (#180), so several rows
# can make one result: a Scripture verse is in ~9 versions on average
# (330,708 verses in 37,060 groups). FOLD_ROWS more rows per result keep a
# page full for a query that finds mostly Scripture in a few languages. When
# a full pool still folds into too few results for the page, the page is run
# again with twice the pool, up to MAX_POOL (the old fixed pool); the second
# run reads index pages the first one just cached. A query that matches
# every version of every verse can still run out of results before
# MAX_DEPTH, which only shortens the last pages, never repeats a result.
#
# A query's pages are cut from the first page's pool until one runs short, so
# the cursor needs the pool sizes and the last lead shown from each (Cursor).
# A page skips every passage group the pages before showed, so no result
# repeats: an index scan returns its rows in the same order whatever its
# LIMIT, so a smaller pool is the prefix of a bigger one. A passage a bigger
# pool finds ahead of results already shown is shown on the next page.
FOLD_ROWS = 4


def pool_size(shown: int, limit: int) -> int:
    """Candidate rows for *limit* results after *shown* (the first page's pool)."""
    return FOLD_ROWS * 2 * (shown + limit + 1)


MAX_POOL = pool_size(MAX_DEPTH, MAX_LIMIT)
MAX_LEVELS = 10  # pool sizes in a cursor: pools double, from 16 rows at least


TEXT_CHARS = 2000  # longer chunk texts are cut in results (a few Scripture chapters)
EF_SEARCH = 100
TRANSLATION_LANGUAGE = "eng"
ANONYMOUS = "anonymous"  # author filter value for works with no author_ids

# Any of these opens or closes a quoted phrase: "…", “…”, „…“, «…».
_QUOTES = frozenset('"“”„«»')
_SPACE = re.compile(r"\s+")
# Keyword results whose first match lies past TEXT_CHARS show a window that
# starts this many characters before it.
MATCH_CONTEXT = 200


class SearchUnavailable(RuntimeError):
    """The query could not be embedded (no key, Voyage down or slow, or the index is missing)."""


class QueryError(ValueError):
    """A query with nothing to search for."""


@dataclass(frozen=True)
class ParsedQuery:
    phrases: tuple[str, ...]  # quoted, each normalized and non-empty
    text: str  # everything outside the quotes, normalized

    @property
    def mode(self) -> Literal["keyword", "vector"]:
        return "keyword" if self.phrases else "vector"


def normalize_query(q: str) -> str:
    """Whitespace collapsed and trimmed: the text that is embedded and cached."""
    return _SPACE.sub(" ", q).strip()


def parse_query(q: str) -> ParsedQuery:
    """Split *q* into quoted phrases and the free text around them (#143).

    Each quote mark in ``_QUOTES`` opens or closes a phrase. A quote left
    open runs to the end of the query, empty quotes are ignored, and the
    free text is what is left, quote marks removed.
    """
    phrases: list[str] = []
    free: list[str] = []
    part: list[str] = []
    inside = False
    for ch in q:
        if ch in _QUOTES:
            (phrases if inside else free).append("".join(part))
            part, inside = [], not inside
        else:
            part.append(ch)
    (phrases if inside else free).append("".join(part))
    return ParsedQuery(tuple(p for p in map(normalize_query, phrases) if p),
                       normalize_query(" ".join(free)))


#: One pool a vector query's pages were cut from: its size, and the last lead
#: shown from it (distance, chunk id).
Level = tuple[int, float, str]


@dataclass(frozen=True)
class Cursor:
    """Where a page starts: the next page token of the response before it (#251).

    *shown* counts the results on the pages before. A keyword page starts
    after *shown* results, since keyword search orders every match exactly.

    A vector page uses the pool of the last of *levels*. Each level is a pool
    the pages before were cut from, with the last lead shown from it; the
    pages before showed exactly the passage groups with a member up to a
    level's lead in that level's pool. Pools grow (doubling) only when a page
    runs short, so a cursor has a few levels at most.
    """

    shown: int = 0
    levels: tuple[Level, ...] = ()

    def encode(self) -> str:
        fields = [self.shown, *(list(level) for level in self.levels)]
        raw = json.dumps(fields, separators=(",", ":"), ensure_ascii=False).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    @classmethod
    def decode(cls, token: str) -> Cursor:
        """The cursor in *token*; a QueryError if it isn't one."""
        try:
            shown, *levels = json.loads(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
            pools = [level[0] for level in levels]
            ok = (type(shown) is int and 0 <= shown <= MAX_DEPTH and len(levels) <= MAX_LEVELS
                  and all(type(pool) is int and 0 < pool <= MAX_POOL
                          and type(distance) in (int, float) and isinstance(chunk_id, str)
                          for pool, distance, chunk_id in levels)
                  and pools == sorted(set(pools)))
        except (binascii.Error, ValueError, TypeError):
            ok = False
        if not ok:
            raise QueryError("The cursor is not valid: start the search again.")
        return cls(shown, tuple((pool, float(d), cid) for pool, d, cid in levels))


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
            # A chunk without a date (nor its work) matches through its work's
            # authors' activity range (#151), which lives in works only: the
            # derived date never rewrites chunks or chunk_vectors rows.
            conds.append("(date_range && int4range(%(date_from)s, %(date_to)s, '[]') "
                         "OR (date_range IS NULL AND work_id IN (SELECT work_id FROM works "
                         "WHERE author_date_range && int4range(%(date_from)s, %(date_to)s, "
                         "'[]'))))")
            params["date_from"], params["date_to"] = self.date_from, self.date_to
        if not self.include_out_of_period:
            conds.append("NOT out_of_period")
        return " AND ".join(conds) or "TRUE", params


class QueryEmbedder:
    """Embeds queries with Voyage, failing fast, with an LRU cache of the vectors.

    Every miss is a paid Voyage call, so repeated queries (and paging through
    results) are served from the cache. Concurrent misses for the same text
    share one call: the first request makes it, and the others wait for its
    vector or its error. Other queries are not held up.
    """

    def __init__(self, make_client: Callable[[], Any] | None = None, cache_size: int = 10_000,
                 timeout: float = 5.0) -> None:
        self._make_client = make_client or (
            lambda: VoyageEmbedder(MODEL, timeout=timeout, retries=1))
        self._client: Any = None
        self._cache: OrderedDict[str, np.ndarray] = OrderedDict()
        self._inflight: dict[str, Future[np.ndarray]] = {}
        self._size = cache_size
        # Longer than the leader can take (one Voyage attempt), as a backstop.
        self._wait = 2 * timeout + 5
        self._lock = threading.Lock()
        self._client_lock = threading.Lock()

    def embed(self, text: str) -> tuple[np.ndarray, bool]:
        """(unit vector of DIMS dims, whether no Voyage call was made for this request)."""
        with self._lock:
            if text in self._cache:
                self._cache.move_to_end(text)
                return self._cache[text], True
            pending = self._inflight.get(text)
            if pending is None:
                future: Future[np.ndarray] = Future()
                self._inflight[text] = future
        if pending is not None:
            try:
                return pending.result(timeout=self._wait), True
            except TimeoutError as exc:
                raise SearchUnavailable("the embedding service did not answer in time") from exc
        try:
            vec = self._fetch(text)
        except BaseException as exc:
            future.set_exception(exc)
            raise
        else:
            with self._lock:
                self._cache[text] = vec
                while len(self._cache) > self._size:
                    self._cache.popitem(last=False)
            future.set_result(vec)
            return vec, False
        finally:
            with self._lock:
                del self._inflight[text]

    def _fetch(self, text: str) -> np.ndarray:
        try:
            with self._client_lock:
                if self._client is None:
                    self._client = self._make_client()
            raw = self._client.embed_batch([text], "query")
        except KeyError as exc:  # env_key: VOYAGE_API_KEY not set
            raise SearchUnavailable("search is not configured on this server") from exc
        except ApiError as exc:
            log.warning("query embedding failed: %s", exc)
            raise SearchUnavailable("the embedding service did not answer in time") from exc
        return shorten(raw, DIMS)[0]


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


# The candidate scan: the first %(pool)s rows of the HNSW scan (or the
# planner's exact plan for narrow filters).
_SCAN = """
    SELECT chunk_id, kind, embedding <=> %(q)s::halfvec AS distance
    FROM chunk_vectors
    WHERE model_id = {model_id} AND {where}
    ORDER BY embedding <=> %(q)s::halfvec
    LIMIT {limit}
"""

# hits: the candidate pool; best: each chunk's better vector; folded: each
# chunk's passage group and its place in it (n = 1 leads: the best score,
# then the chunk id); seen: the groups the pages before showed ({seen}, one
# part per cursor level); page: the next leads of the other groups;
# versions: the other members of the page's groups found in the pool.
_SEARCH_SQL = """
WITH hits AS MATERIALIZED ({hits}),{levels} best AS (
    SELECT DISTINCT ON (chunk_id) chunk_id, kind, distance
    FROM hits ORDER BY chunk_id, distance, kind
), folded AS (
    SELECT b.chunk_id, b.kind, b.distance, {group} AS grp,
           row_number() OVER (PARTITION BY {group} ORDER BY b.distance, b.chunk_id) AS n
    FROM best b JOIN chunks c ON c.chunk_id = b.chunk_id
), seen AS ({seen}
), page AS (
    SELECT chunk_id, kind, distance, grp FROM folded
    WHERE n = 1 AND grp NOT IN (SELECT grp FROM seen)
    ORDER BY distance, chunk_id LIMIT %(limit)s
), versions AS (
    SELECT grp, json_agg(json_build_array(chunk_id, distance) ORDER BY distance, chunk_id)
           AS versions
    FROM folded WHERE n > 1 AND grp IN (SELECT grp FROM page) GROUP BY grp
)
SELECT b.distance, b.kind, c.chunk_id, c.work_id, c.canonical_ref, c.language,
       left(c.text, %(text_chars)s), length(c.text) > %(text_chars)s,
       c.date_composed, lower(c.date_range), upper(c.date_range) - 1, c.out_of_period,
       t.text, t.model,
       w.title, w.author_ids, w.source_id, w.edition, w.license, w.provenance_url,
       w.genre, w.tradition, w.date_composed, lower(w.date_range), upper(w.date_range) - 1,
       coalesce((SELECT array_agg(a.name ORDER BY i.n) FROM unnest(w.author_ids)
                 WITH ORDINALITY AS i(id, n) JOIN authors a ON a.author_id = i.id), '{{}}'),
       coalesce(v.versions, '[]'), (SELECT count(*) FROM hits)
FROM page b
JOIN chunks c ON c.chunk_id = b.chunk_id
JOIN works w ON w.work_id = c.work_id
LEFT JOIN chunk_translations t ON t.chunk_id = c.chunk_id AND t.language = %(tr_lang)s
LEFT JOIN versions v ON v.grp = b.grp
ORDER BY b.distance, c.chunk_id
"""

# The groups shown from one cursor level: those with a member up to its last
# lead in its pool (a scan, or hits when the page uses the same pool).
_SEEN_SQL = """
    SELECT {group} AS grp
    FROM (SELECT chunk_id, min(distance) AS distance FROM {pool} GROUP BY chunk_id) b
    JOIN chunks c ON c.chunk_id = b.chunk_id
    WHERE (b.distance, b.chunk_id) <= (%(distance{i})s::float8, %(chunk{i})s::text)"""

# The fields a result shows for each of its other versions.
_VERSIONS_SQL = """
SELECT c.chunk_id, c.work_id, c.canonical_ref, c.language, w.source_id, w.edition
FROM chunks c JOIN works w ON w.work_id = c.work_id
WHERE c.chunk_id = ANY(%(ids)s::text[])
"""


# The display fields of the keyword results, in page order (full text: it is
# windowed around the first match in Python).
_HYDRATE_SQL = """
SELECT NULL, NULL, c.chunk_id, c.work_id, c.canonical_ref, c.language, c.text, false,
       c.date_composed, lower(c.date_range), upper(c.date_range) - 1, c.out_of_period,
       t.text, t.model,
       w.title, w.author_ids, w.source_id, w.edition, w.license, w.provenance_url,
       w.genre, w.tradition, w.date_composed, lower(w.date_range), upper(w.date_range) - 1,
       coalesce((SELECT array_agg(a.name ORDER BY i.n) FROM unnest(w.author_ids)
                 WITH ORDINALITY AS i(id, n) JOIN authors a ON a.author_id = i.id), '{}')
FROM unnest(%(ids)s::text[]) WITH ORDINALITY AS p(chunk_id, n)
JOIN chunks c ON c.chunk_id = p.chunk_id
JOIN works w ON w.work_id = c.work_id
LEFT JOIN chunk_translations t ON t.chunk_id = c.chunk_id AND t.language = %(tr_lang)s
ORDER BY p.n
"""


def utf16_offset(text: str, index: int) -> int:
    """*index* (code points) in *text* as a JavaScript string index (UTF-16 code units)."""
    return len(text[:index].encode("utf-16-le")) // 2


def keyword_window(text: str, phrases: tuple[str, ...]) -> tuple[str, int, bool, list[list[int]]]:
    """(text shown, its start in *text*, cut at the end?, match spans in it).

    Text longer than TEXT_CHARS is cut, starting MATCH_CONTEXT characters
    before the first match when the match would be cut off. Start and spans
    are UTF-16 code units, for the web app.
    """
    spans = match_spans(text, list(phrases))
    start = 0
    if len(text) > TEXT_CHARS and spans and spans[0][1] > TEXT_CHARS:
        # Context before the match, but never a window shorter than TEXT_CHARS.
        start = max(0, min(spans[0][0] - MATCH_CONTEXT, len(text) - TEXT_CHARS))
    shown = text[start:start + TEXT_CHARS]
    inside = [(max(a - start, 0), min(b - start, len(shown))) for a, b in spans
              if a < start + len(shown) and b > start]
    return (shown, utf16_offset(text, start), start + len(shown) < len(text),
            [[utf16_offset(shown, a), utf16_offset(shown, b)] for a, b in inside])


def _range(lo: int | None, hi: int | None) -> list[int] | None:
    return None if lo is None else [lo, hi]


def _score(distance: float | None) -> float | None:
    return None if distance is None else round(1 - float(distance), 4)


def _versions(conn: Any, hits: list[list[Hit]]) -> list[list[dict[str, Any]]]:
    """The ``versions`` of each result, from its other members' (chunk_id, distance)."""
    ids = [cid for members in hits for cid, _ in members]
    if not ids:
        return [[] for _ in hits]
    rows = {r[0]: r for r in conn.execute(_VERSIONS_SQL, {"ids": ids}).fetchall()}
    return [[{"chunk_id": cid, "work_id": rows[cid][1], "canonical_ref": rows[cid][2],
              "language": rows[cid][3], "source_label": source_label(rows[cid][4]),
              "edition": rows[cid][5], "score": _score(distance)}
             for cid, distance in members] for members in hits]


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
        "score": _score(distance),
        "matched": "translation" if kind == 1 else "text",
        "text_start": 0,
        "matches": [],
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
        # The other versions of the passage that the search found (#180).
        "versions": [],
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

    def search(self, q: str, filters: Filters, limit: int = 20, cursor: str | None = None
               ) -> dict[str, Any]:
        """One page of results; *cursor* is the ``next_cursor`` of the page before."""
        parsed = parse_query(q)
        start = Cursor.decode(cursor) if cursor else Cursor()
        if parsed.phrases:
            if start.levels:
                raise QueryError("The cursor is not for this query: start the search again.")
            return self._keyword(q, parsed, filters, limit, start)
        if not parsed.text:
            raise QueryError("The query has nothing to search for.")
        if start.shown and not start.levels:
            raise QueryError("The cursor is not for this query: start the search again.")
        return self._vector(q, parsed, filters, limit, start)

    def _response(self, q: str, parsed: ParsedQuery, limit: int, next_cursor: Cursor | None,
                  total: int | None, results: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "query": normalize_query(q),
            "mode": parsed.mode,
            "phrases": list(parsed.phrases),
            "text": parsed.text,
            "model": MODEL_NAME,
            "limit": limit,
            "total": total,
            # None after the last page, and once MAX_DEPTH results are shown.
            "next_cursor": (None if next_cursor is None or next_cursor.shown > MAX_DEPTH
                            else next_cursor.encode()),
            "results": results,
        }

    def _keyword(self, q: str, parsed: ParsedQuery, filters: Filters, limit: int,
                 start: Cursor) -> dict[str, Any]:
        for phrase in parsed.phrases:  # reject a bad phrase before paying for an embedding
            phrase_pattern(phrase)
        started = time.monotonic()
        vec, cached = self.embedder.embed(parsed.text) if parsed.text else (None, True)
        embedded = time.monotonic()
        where, params = filters.sql()
        with self.pool.connection() as conn:
            rank = None if vec is None else (_vec_literal(vec), self.model_id(conn))
            page, total = phrase_search(conn, list(parsed.phrases), where, params,
                                        limit + 1, start.shown, rank)
            distances = {cid: distance for cid, distance, _ in page[:limit]}
            rows = conn.execute(_HYDRATE_SQL, {"ids": list(distances),
                                               "tr_lang": TRANSLATION_LANGUAGE}).fetchall()
            versions = dict(zip(distances, _versions(conn, [m for _, _, m in page[:limit]])))
        done = time.monotonic()
        log.info("search: keyword, %d phrases, %s, embed %.0f ms (%s), db %.0f ms, %d rows",
                 len(parsed.phrases), "ranked" if rank else "unranked",
                 1000 * (embedded - started), "cached" if cached else "voyage",
                 1000 * (done - embedded), len(rows))
        results = []
        for row in rows:
            shown, text_start, truncated, matches = keyword_window(row[6], parsed.phrases)
            result = _result((distances[row[2]], None, *row[2:6], shown, truncated, *row[8:]))
            result.update(matched="phrase", text_start=text_start, matches=matches,
                          versions=versions[row[2]])
            results.append(result)
        self._add_context(results)
        more = Cursor(start.shown + limit) if len(page) > limit else None
        return self._response(q, parsed, limit, more, total, results)

    def _vector(self, q: str, parsed: ParsedQuery, filters: Filters, limit: int,
                start: Cursor) -> dict[str, Any]:
        started = time.monotonic()
        vec, cached = self.embedder.embed(parsed.text)
        embedded = time.monotonic()
        where, params = filters.sql()
        levels = list(start.levels)
        pool = levels[-1][0] if levels else pool_size(0, limit)
        for i, (_, distance, chunk_id) in enumerate(levels):
            params[f"distance{i}"], params[f"chunk{i}"] = distance, chunk_id
        params.update(q=_vec_literal(vec), limit=limit + 1, text_chars=TEXT_CHARS,
                      tr_lang=TRANSLATION_LANGUAGE)
        with self.pool.connection() as conn, conn.transaction():
            model_id = self.model_id(conn)
            # JIT compilation costs more than this short query; on the full
            # index the cost estimates can exceed jit_above_cost.
            conn.execute("SELECT set_config('hnsw.ef_search', %s, true), "
                         "set_config('hnsw.iterative_scan', 'relaxed_order', true), "
                         "set_config('jit', 'off', true)",
                         (str(self.ef_search),))
            while True:
                rows = conn.execute(self._search_sql(model_id, where, pool, levels),
                                    {**params, "pool": pool}).fetchall()
                # The pool filled up but folded into too few results: the index has more.
                if len(rows) > limit or not rows or rows[0][-1] < pool or pool >= MAX_POOL:
                    break
                pool = min(2 * pool, MAX_POOL)
            versions = _versions(conn, [[(cid, d) for cid, d in r[-2]] for r in rows[:limit]])
        done = time.monotonic()
        log.info("search: vector, %d chars, embed %.0f ms (%s), db %.0f ms, pool %d, %d rows",
                 len(parsed.text), 1000 * (embedded - started),
                 "cached" if cached else "voyage", 1000 * (done - embedded), pool, len(rows))
        results = []
        for row, members in zip(rows[:limit], versions):
            result = _result(row[:-2])
            result["versions"] = members
            results.append(result)
        self._add_context(results)
        more = None
        if len(rows) > limit:
            lead = rows[limit - 1]
            if levels and levels[-1][0] == pool:
                levels.pop()  # the same pool: its new last lead covers the old one
            more = Cursor(start.shown + limit, (*levels, (pool, float(lead[0]), lead[2])))
        return self._response(q, parsed, limit, more, None, results)

    @staticmethod
    def _search_sql(model_id: int, where: str, pool: int, levels: list[Level]) -> str:
        """_SEARCH_SQL over a pool of *pool* rows, after the pages of cursor *levels*."""
        def scan(limit: str) -> str:
            # Inlined, not a parameter: a generic plan of a prepared statement
            # can't prove model_id = n, so it would never use the partial index.
            return _SCAN.format(model_id=model_id, where=where, limit=limit)

        group = passage_group("c")
        scans, seen = [], []
        for i, (level_pool, _, _) in enumerate(levels):
            name = "hits"
            if level_pool != pool:
                name = f"level{i}"
                scans.append(f" {name} AS MATERIALIZED ({scan(str(level_pool))}),")
            seen.append(_SEEN_SQL.format(group=group, pool=name, i=i))
        return _SEARCH_SQL.format(
            hits=scan("%(pool)s"), levels="".join(scans), group=group,
            seen="\n    UNION".join(seen) or "\n    SELECT NULL::text AS grp WHERE false")

    def _add_context(self, results: list[dict[str, Any]]) -> None:
        """The units around each result, and English versions (``api.context``)."""
        started = time.monotonic()
        with self.pool.connection() as conn:
            add_context(conn, results, TEXT_CHARS)
        log.info("search: context for %d results, %.0f ms", len(results),
                 1000 * (time.monotonic() - started))
