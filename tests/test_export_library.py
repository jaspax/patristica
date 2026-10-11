"""Tests for scripts.export_library and patristica.sources."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from patristica.sources import SOURCE_LABELS, source_label
from scripts.export_library import (
    ExportError,
    common_ref_prefix,
    export_library,
    strip_prefix,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _chunk(work_id: str, ref: str, text: str, index: int, out_of_period: bool = False) -> dict:
    return {
        "chunk_id": f"{work_id}#{ref}",
        "work_id": work_id,
        "canonical_ref": ref,
        "language": "eng",
        "text": text,
        "chunk_index": index,
        "out_of_period": out_of_period,
    }


def _work(work_id: str, source_id: str, genre: str = "scripture", **extra) -> dict:
    return {
        "work_id": work_id,
        "source_id": source_id,
        "title": work_id.rsplit("/", 1)[-1].title(),
        "genre": genre,
        "language": "eng",
        **extra,
    }


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    """A tiny normalized corpus: two scripture books and one patristic work."""
    norm = tmp_path / "normalized"
    works = [
        ("scripture/kjv/Gen.json", _work("scripture/kjv/gen", "scripture/kjv", date_composed=-500),
         [_chunk("scripture/kjv/gen", "Gen.1.1", "In the beginning", 0),
          _chunk("scripture/kjv/gen", "Gen.1.2", "And the earth", 1)]),
        ("scripture/kjv/Exod.json", _work("scripture/kjv/exod", "scripture/kjv"),
         [_chunk("scripture/kjv/exod", "Exod.1.1", "Now these are", 0)]),
        ("patristic/pta/x.json",
         _work("pta/x", "patristic/pta", genre="patristic", author="Anon", license="cc-by-sa-4.0"),
         # Out of order on disk; the second is out of period.
         [_chunk("pta/x", "pta1.pta2.2", "second", 1, out_of_period=True),
          _chunk("pta/x", "pta1.pta2.1", "first", 0)]),
    ]
    lines = []
    for rel, work, chunks in works:
        p = norm / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(chunks), encoding="utf-8")
        lines.append(json.dumps({"path": rel, "work": work}))
    (norm / "_works.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return norm


class TestRefPrefix:
    def test_scripture(self):
        assert common_ref_prefix(["Gen.1.1", "Gen.1.2", "Gen.2.1"]) == "Gen"

    def test_shared_chapter(self):
        assert common_ref_prefix(["Gen.1.1", "Gen.1.2"]) == "Gen.1"

    def test_keeps_one_segment(self):
        # A ref equal to the shared prefix must keep a suffix.
        assert common_ref_prefix(["PL73.0.UNKNOWN", "PL73.0.UNKNOWN.1"]) == "PL73.0"
        assert common_ref_prefix(["Synax.1.1"]) == "Synax.1"

    def test_no_common_prefix(self):
        assert common_ref_prefix(["A.1", "B.1"]) == ""
        assert common_ref_prefix([]) == ""

    def test_strip_prefix(self):
        assert strip_prefix("Gen.1.1", "Gen") == "1.1"
        assert strip_prefix("Gen.1.1", "") == "Gen.1.1"


class TestExport:
    def test_index(self, corpus: Path, tmp_path: Path):
        out = tmp_path / "library"
        counts = export_library(corpus, out)
        assert counts == {"works": 3, "written": 3, "removed": 0}

        index = json.loads((out / "index.json").read_text(encoding="utf-8"))
        assert index["sources"] == {
            "scripture/kjv": "King James Version",
            "patristic/pta": "Patristic Text Archive",
        }
        rows = {r["id"]: r for r in index["works"]}
        assert rows["scripture/kjv/gen"]["chunks"] == 2
        assert rows["scripture/kjv/gen"]["date"] == -500
        assert rows["scripture/kjv/gen"]["file"] == "works/scripture/kjv/Gen.json"
        assert rows["pta/x"]["author"] == "Anon"
        assert rows["pta/x"]["license"] == "cc-by-sa-4.0"
        for row in index["works"]:
            assert (out / row["file"]).exists()

    def test_work_file(self, corpus: Path, tmp_path: Path):
        out = tmp_path / "library"
        export_library(corpus, out)
        gen = json.loads((out / "works/scripture/kjv/Gen.json").read_text(encoding="utf-8"))
        assert gen == {
            "work_id": "scripture/kjv/gen",
            "ref_prefix": "Gen.1",
            "chunks": [["1", "In the beginning"], ["2", "And the earth"]],
        }
        pta = json.loads((out / "works/patristic/pta/x.json").read_text(encoding="utf-8"))
        # Sorted by chunk_index; out-of-period flag as third element.
        assert pta["chunks"] == [["1", "first"], ["2", "second", 1]]

    def test_idempotent(self, corpus: Path, tmp_path: Path):
        out = tmp_path / "library"
        export_library(corpus, out)
        first = json.loads((out / "index.json").read_text(encoding="utf-8"))
        counts = export_library(corpus, out)
        assert counts["written"] == 0
        second = json.loads((out / "index.json").read_text(encoding="utf-8"))
        assert first["works"] == second["works"]

    def test_rebuilds_changed_source(self, corpus: Path, tmp_path: Path):
        out = tmp_path / "library"
        export_library(corpus, out)
        src = corpus / "scripture/kjv/Exod.json"
        src.write_text(json.dumps([
            _chunk("scripture/kjv/exod", "Exod.1.1", "Now these are", 0),
            _chunk("scripture/kjv/exod", "Exod.1.2", "Reuben", 1),
        ]), encoding="utf-8")
        future = src.stat().st_mtime + 10
        os.utime(src, (future, future))
        counts = export_library(corpus, out)
        assert counts["written"] == 1
        rows = {r["id"]: r for r in json.loads((out / "index.json").read_text())["works"]}
        assert rows["scripture/kjv/exod"]["chunks"] == 2

    def test_force(self, corpus: Path, tmp_path: Path):
        out = tmp_path / "library"
        export_library(corpus, out)
        assert export_library(corpus, out, force=True)["written"] == 3

    def test_removes_stale(self, corpus: Path, tmp_path: Path):
        out = tmp_path / "library"
        stale = out / "works/old/gone.json"
        stale.parent.mkdir(parents=True)
        stale.write_text("{}")
        assert export_library(corpus, out)["removed"] == 1
        assert not stale.exists()

    def test_missing_manifest(self, tmp_path: Path):
        with pytest.raises(ExportError, match="manifest"):
            export_library(tmp_path, tmp_path / "library")

    def test_missing_work_file(self, corpus: Path, tmp_path: Path):
        (corpus / "scripture/kjv/Exod.json").unlink()
        with pytest.raises(ExportError, match="missing"):
            export_library(corpus, tmp_path / "library")


class TestSourceLabels:
    def test_fallback(self):
        assert source_label("scripture/kjv") == "King James Version"
        assert source_label("nope/unknown") == "nope/unknown"

    def test_every_corpus_source_has_label(self):
        manifest = REPO_ROOT / "data/normalized/_works.jsonl"
        if not manifest.exists():
            pytest.skip("normalized corpus not present")
        with manifest.open(encoding="utf-8") as f:
            sources = {json.loads(line)["work"]["source_id"] for line in f if line.strip()}
        missing = sorted(sources - SOURCE_LABELS.keys())
        assert not missing, f"Add these to patristica.sources.SOURCE_LABELS: {missing}"
