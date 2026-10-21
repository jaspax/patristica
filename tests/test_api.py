"""Tests for the API health check (api/app.py, #117). The database is mocked."""

import pytest

pytest.importorskip("fastapi")
psycopg = pytest.importorskip("psycopg")

from fastapi.testclient import TestClient  # noqa: E402

from api import app as api_app  # noqa: E402

client = TestClient(api_app.app)


@pytest.fixture
def database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db:5432/patristica")


def test_healthz_ok(database_url: None, mocker) -> None:
    mocker.patch.object(api_app, "check_database", return_value={"db": "ok", "vector": "0.8.7"})
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok", "db": "ok", "vector": "0.8.7"}


def test_healthz_missing_vector_extension(database_url: None, mocker) -> None:
    mocker.patch.object(api_app, "check_database", return_value={"db": "ok", "vector": None})
    resp = client.get("/healthz")
    assert resp.status_code == 503
    assert resp.json()["vector"] is None


def test_healthz_database_unreachable(database_url: None, mocker) -> None:
    mocker.patch.object(
        api_app, "check_database", side_effect=psycopg.OperationalError("connection refused")
    )
    resp = client.get("/healthz")
    assert resp.status_code == 503
    assert resp.json() == {"status": "error", "db": "unreachable"}


def test_healthz_without_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    resp = client.get("/healthz")
    assert resp.status_code == 503


def test_check_database_reports_vector_version(mocker) -> None:
    conn = mocker.MagicMock()
    conn.__enter__.return_value = conn
    conn.execute.return_value.fetchone.return_value = ("0.8.7",)
    connect = mocker.patch.object(api_app.psycopg, "connect", return_value=conn)
    assert api_app.check_database("postgresql://x") == {"db": "ok", "vector": "0.8.7"}
    connect.assert_called_once_with("postgresql://x", connect_timeout=3)
