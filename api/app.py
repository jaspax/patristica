"""Patristica API (Phase 3, IMPLEMENTATION_PLAN.md §3.3).

For now only a health check, so the hosting stack (#117) can be verified end
to end: Caddy (TLS) → this app → Postgres with pgvector.
"""

import logging
import os
from typing import Any

import psycopg
from fastapi import FastAPI
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)

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
