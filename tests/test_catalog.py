"""Tests for scripts.catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.catalog import build_catalog, count_files, print_table


class TestCountFiles:
    def test_empty_directory(self, tmp_path):
        assert count_files(tmp_path / "nonexistent") == {}

    def test_counts_json_files(self, tmp_path):
        src = tmp_path / "pta"
        src.mkdir()
        (src / "work1.json").write_text("{}")
        (src / "work2.json").write_text("{}")
        result = count_files(tmp_path)
        assert result == {"pta": 2}

    def test_ignores_non_json(self, tmp_path):
        src = tmp_path / "pta"
        src.mkdir()
        (src / "work1.json").write_text("{}")
        (src / "readme.txt").write_text("hello")
        result = count_files(tmp_path)
        assert result == {"pta": 1}

    def test_multiple_sources(self, tmp_path):
        for name in ("pta", "ccel-anf", "oshb"):
            d = tmp_path / name
            d.mkdir()
            for i in range(3):
                (d / f"w{i}.json").write_text("{}")
        result = count_files(tmp_path)
        assert result == {"ccel-anf": 3, "oshb": 3, "pta": 3}

    def test_custom_suffix(self, tmp_path):
        src = tmp_path / "pta"
        src.mkdir()
        (src / "file.xml").write_text("<x/>")
        assert count_files(tmp_path, suffix=".xml") == {"pta": 1}
        assert count_files(tmp_path, suffix=".json") == {}

    def test_counts_nested_json(self, tmp_path):
        src = tmp_path / "ccel-anf"
        sub = src / "vol1"
        sub.mkdir(parents=True)
        (sub / "work.json").write_text("{}")
        result = count_files(tmp_path)
        assert result == {"ccel-anf": 1}


class TestBuildCatalog:
    def test_empty_data_dir(self, tmp_path):
        rows = build_catalog(tmp_path)
        assert rows == []

    def test_raw_only(self, tmp_path):
        raw = tmp_path / "raw" / "oshb"
        raw.mkdir(parents=True)
        (raw / "gen.json").write_text("{}")
        rows = build_catalog(tmp_path)
        assert len(rows) == 1
        assert rows[0]["source_id"] == "oshb"
        assert rows[0]["raw"] == 1
        assert rows[0]["normalized"] == 0
        assert rows[0]["status"] == "raw"

    def test_normalized_status(self, tmp_path):
        norm = tmp_path / "normalized" / "oshb"
        norm.mkdir(parents=True)
        (norm / "gen.json").write_text("{}")
        rows = build_catalog(tmp_path)
        assert rows[0]["status"] == "normalized"

    def test_union_of_sources(self, tmp_path):
        (tmp_path / "raw" / "oshb").mkdir(parents=True)
        (tmp_path / "raw" / "oshb" / "f.json").write_text("{}")
        (tmp_path / "normalized" / "pta").mkdir(parents=True)
        (tmp_path / "normalized" / "pta" / "f.json").write_text("{}")
        rows = build_catalog(tmp_path)
        ids = {r["source_id"] for r in rows}
        assert ids == {"oshb", "pta"}


class TestPrintTable:
    def test_empty(self, capsys):
        print_table([])
        out = capsys.readouterr().out
        assert "No ingested data found." in out

    def test_renders_rows(self, capsys):
        rows = [{"source_id": "oshb", "raw": 5, "normalized": 3, "status": "normalized"}]
        print_table(rows)
        out = capsys.readouterr().out
        assert "oshb" in out
        assert "5" in out
        assert "3" in out
        assert "normalized" in out

    def test_totals_row(self, capsys):
        rows = [
            {"source_id": "oshb", "raw": 4, "normalized": 2, "status": "normalized"},
            {"source_id": "pta", "raw": 6, "normalized": 0, "status": "raw"},
        ]
        print_table(rows)
        out = capsys.readouterr().out
        assert "TOTAL" in out
        assert "10" in out  # total raw
        assert "2" in out   # total normalized
