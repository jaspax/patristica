"""Patristica API (Phase 3, IMPLEMENTATION_PLAN.md §3.3).

- ``GET /healthz``: Caddy (TLS) → this app → Postgres with pgvector (#117).
- ``GET /search``: vector search over the search database (#141; ``api.search``).

Routes have no ``/api`` prefix: on ``patristica.app`` Caddy strips it.
Settings come from the environment: ``DATABASE_URL``, ``VOYAGE_API_KEY``,
and optionally ``SEARCH_RATE_PER_MINUTE`` / ``SEARCH_BURST`` (per client IP)
and ``SEARCH_EF_SEARCH``.
"""

import logging
import math
import os
from functools import cache
from typing import Annotated, Any

import psycopg
from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse

from api.keyword import PhraseTooBroad
from api.search import (
    MAX_LIMIT,
    MAX_OFFSET,
    MAX_QUERY_CHARS,
    Filters,
    QueryEmbedder,
    QueryError,
    RateLimiter,
    Searcher,
    SearchUnavailable,
)
from patristica.keyword import PhraseError

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

app = FastAPI(title="Patristica API")


def check_database(database_url: str) -> dict[str, Any]:
    """Connect, run a trivial query and report the pgvector version (None if missing)."""
    with psycopg.connect(database_url, connect_timeout=3) as conn:
        conn.execute("SELECT 1")
        row = conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
    return {"db": "ok", "vector": row[0] if row else None}


@app.get("/healthz")
def healthz() -> JSONResponse:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        return JSONResponse({"status": "error", "db": "DATABASE_URL is not set"}, status_code=503)
    try:
        result = check_database(database_url)
    except psycopg.Error as exc:
        log.warning("health check: database unreachable: %s", exc)
        return JSONResponse({"status": "error", "db": "unreachable"}, status_code=503)
    if result["vector"] is None:
        return JSONResponse({"status": "error", **result}, status_code=503)
    return JSONResponse({"status": "ok", **result})


@cache
def get_searcher() -> Searcher:
    """The process-wide searcher: a small connection pool and the query embedder."""
    from psycopg_pool import ConnectionPool

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SearchUnavailable("DATABASE_URL is not set")
    pool = ConnectionPool(database_url, min_size=1, max_size=8, open=True,
                          kwargs={"connect_timeout": 3})
    return Searcher(pool, QueryEmbedder(),
                    ef_search=int(os.environ.get("SEARCH_EF_SEARCH", "100")))


@cache
def get_rate_limiter() -> RateLimiter:
    return RateLimiter(rate=float(os.environ.get("SEARCH_RATE_PER_MINUTE", "30")),
                       burst=int(os.environ.get("SEARCH_BURST", "10")))


def _list(values: list[str]) -> list[str]:
    """Repeated parameters, also accepting comma-separated values (?language=grc,lat)."""
    return [v for value in values for v in (p.strip() for p in value.split(",")) if v]


@app.exception_handler(SearchUnavailable)
def search_unavailable(request: Request, exc: SearchUnavailable) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=503)


@app.exception_handler(PhraseError)
@app.exception_handler(PhraseTooBroad)
@app.exception_handler(QueryError)
def unsearchable_query(request: Request, exc: Exception) -> JSONResponse:
    """A query that can't be run as written: the message says what to change."""
    return JSONResponse({"error": str(exc)}, status_code=422)


@app.exception_handler(psycopg.Error)
def database_error(request: Request, exc: psycopg.Error) -> JSONResponse:
    log.warning("%s: database error: %s", request.url.path, exc)
    return JSONResponse({"error": "the search database is unavailable"}, status_code=503)


@app.get("/search")
def search(
    request: Request,
    searcher: Annotated[Searcher, Depends(get_searcher)],
    limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
    q: Annotated[str, Query(min_length=1, max_length=MAX_QUERY_CHARS)],
    language: Annotated[list[str], Query()] = [],
    genre: Annotated[list[str], Query()] = [],
    source: Annotated[list[str], Query()] = [],
    work: Annotated[list[str], Query()] = [],
    author: Annotated[list[str], Query(description="author id, or 'anonymous'")] = [],
    date_from: Annotated[int | None, Query(ge=-3000, le=3000)] = None,
    date_to: Annotated[int | None, Query(ge=-3000, le=3000)] = None,
    out_of_period: Annotated[bool, Query(description="include chunks dated after the period")
                             ] = False,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = 20,
    offset: Annotated[int, Query(ge=0, le=MAX_OFFSET)] = 0,
) -> JSONResponse:
    if not q.strip():
        return JSONResponse({"error": "empty query"}, status_code=422)
    if date_from is not None and date_to is not None and date_from > date_to:
        return JSONResponse({"error": "date_from is after date_to"}, status_code=422)
    wait = limiter.check(request.client.host if request.client else "unknown")
    if wait:
        return JSONResponse({"error": "too many searches; try again shortly"}, status_code=429,
                            headers={"Retry-After": str(math.ceil(wait))})
    filters = Filters(language=_list(language), genre=_list(genre), source=_list(source),
                      work=_list(work), author=_list(author), date_from=date_from,
                      date_to=date_to, include_out_of_period=out_of_period)
    return JSONResponse(searcher.search(q, filters, limit=limit, offset=offset))
