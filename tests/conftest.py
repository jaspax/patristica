"""Shared fixtures."""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest


@pytest.fixture
def pg_url() -> Iterator[str]:
    """A connection string for an empty schema of a Postgres with pgvector.

    Set ``PATRISTICA_TEST_DATABASE_URL`` to use one (CI runs a pgvector
    service); the test is skipped otherwise. Each test gets its own schema,
    dropped afterwards.
    """
    url = os.environ.get("PATRISTICA_TEST_DATABASE_URL")
    if not url:
        pytest.skip("PATRISTICA_TEST_DATABASE_URL is not set (a Postgres with pgvector)")
    psycopg = pytest.importorskip("psycopg")
    from psycopg.conninfo import make_conninfo

    schema = f"test_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(url, autocommit=True) as conn:
        # db/schema.sql's extensions, made once in public: created by a test's
        # schema.sql they would land in its own schema (first on its search_path),
        # invisible to tests running beside it (pytest -n) and dropped with it.
        # CREATE EXTENSION IF NOT EXISTS isn't safe concurrently: hold a lock.
        conn.execute("SELECT pg_advisory_lock(3141592)")
        try:
            for ext in ("vector", "pg_trgm"):
                conn.execute(f"CREATE EXTENSION IF NOT EXISTS {ext} WITH SCHEMA public")
        finally:
            conn.execute("SELECT pg_advisory_unlock(3141592)")
        conn.execute(f"CREATE SCHEMA {schema}")
    try:
        yield make_conninfo(url, options=f"-c search_path={schema},public")
    finally:
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(f"DROP SCHEMA {schema} CASCADE")
