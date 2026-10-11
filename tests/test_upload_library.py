"""Tests for scripts.upload_library (no network access)."""

from __future__ import annotations

import gzip
import os
from pathlib import Path

import pytest

from scripts.upload_library import (
    compress,
    load_env_files,
    md5_hex,
    plan_sync,
    public_index,
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


def test_compress_is_deterministic_and_round_trips():
    data = b'{"chunks": [["1", "\xce\xb1"]]}'
    assert compress(data) == compress(data)
    assert gzip.decompress(compress(data)) == data
    assert md5_hex(compress(data)) == md5_hex(compress(data))


def test_plan_sync():
    local = {"index.json": "a", "works/x.json": "b", "works/new.json": "c"}
    remote = {"index.json": "a", "works/x.json": "OLD", "works/gone.json": "d"}
    upload, delete = plan_sync(local, remote)
    assert upload == ["works/new.json", "works/x.json"]
    assert delete == ["works/gone.json"]


def test_load_env_files_does_not_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = tmp_path / ".env"
    env.write_text("# comment\nR2_TEST_A='from-file'\nR2_TEST_B=file\n\n", encoding="utf-8")
    monkeypatch.setenv("R2_TEST_B", "from-env")
    monkeypatch.delenv("R2_TEST_A", raising=False)
    load_env_files((env, tmp_path / "missing.env"))
    assert os.environ["R2_TEST_A"] == "from-file"
    assert os.environ["R2_TEST_B"] == "from-env"
    monkeypatch.delenv("R2_TEST_A")
