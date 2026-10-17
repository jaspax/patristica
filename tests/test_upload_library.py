"""Tests for scripts.upload_library (no network access)."""

from __future__ import annotations

import gzip
import os
from pathlib import Path

import pytest

from scripts.upload_library import (
    MANIFEST_KEY,
    REQUIRED_ENV,
    UploadError,
    _client,
    compress,
    load_env_files,
    plan_sync,
    public_index,
    spaces_endpoint,
)


def test_public_index_drops_uncleared_licences():
    index = {
        "version": "x",
        "sources": {"a/x": "X", "b/y": "Y"},
        "works": [
            {"id": "1", "source_id": "a/x", "license": "cc-by-4.0"},
            {"id": "2", "source_id": "b/y", "license": "unknown"},
        ],
    }
    pub = public_index(index)
    assert [w["id"] for w in pub["works"]] == ["1"]
    assert pub["sources"] == {"a/x": "X"}
    assert pub["version"] == "x"
    assert len(index["works"]) == 2  # input untouched


def test_compress_round_trips():
    data = b'{"chunks": [["1", "\xce\xb1"]]}'
    assert gzip.decompress(compress(data)) == data


def test_plan_sync_compares_content_hashes():
    local = {"index.json": "a", "works/x.json": "b", "works/new.json": "c"}
    manifest = {"index.json": "a", "works/x.json": "OLD", "works/gone.json": "d"}
    present = {"index.json", "works/x.json", "works/gone.json", MANIFEST_KEY}
    upload, delete = plan_sync(local, manifest, present)
    assert upload == ["works/new.json", "works/x.json"]
    assert delete == ["works/gone.json"]  # never the manifest itself


def test_plan_sync_reuploads_missing_objects_and_handles_no_manifest():
    local = {"index.json": "a", "works/x.json": "b"}
    # Manifest says x was uploaded, but the object is gone.
    assert plan_sync(local, local, {"index.json"}) == (["works/x.json"], [])
    # First run: no manifest, so everything uploads.
    assert plan_sync(local, {}, {"index.json", "works/x.json"})[0] == ["index.json", "works/x.json"]


def test_unchanged_is_a_no_op():
    local = {"index.json": "a", "works/x.json": "b"}
    assert plan_sync(local, dict(local), {"index.json", "works/x.json", MANIFEST_KEY}) == ([], [])


def test_load_env_files_does_not_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nUPLOAD_TEST_A='from-file'\nUPLOAD_TEST_B=file\n\n", encoding="utf-8")
    monkeypatch.setenv("UPLOAD_TEST_B", "from-env")
    monkeypatch.delenv("UPLOAD_TEST_A", raising=False)
    load_env_files((env, tmp_path / "missing.env"))
    assert os.environ["UPLOAD_TEST_A"] == "from-file"
    assert os.environ["UPLOAD_TEST_B"] == "from-env"
    monkeypatch.delenv("UPLOAD_TEST_A")


def test_spaces_endpoint():
    assert spaces_endpoint("nyc3") == "https://nyc3.digitaloceanspaces.com"


def test_client_names_missing_settings(monkeypatch: pytest.MonkeyPatch):
    for key in REQUIRED_ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("LIBRARY_BUCKET", "b")
    with pytest.raises(UploadError, match="LIBRARY_ACCESS_KEY_ID, LIBRARY_SECRET_ACCESS_KEY"):
        _client()
