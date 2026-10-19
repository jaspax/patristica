"""Tests for scripts.export_library and patristica.sources."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from patristica.authors import author_index
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


def _add_works(corpus: Path, works: list[tuple[str, dict, list[dict]]]) -> None:
    """Add ``(path, work, chunks)`` entries to a normalized corpus."""
    with (corpus / "_works.jsonl").open("a", encoding="utf-8") as f:
        for rel, work, chunks in works:
            (corpus / rel).parent.mkdir(parents=True, exist_ok=True)
            (corpus / rel).write_text(json.dumps(chunks), encoding="utf-8")
            f.write(json.dumps({"path": rel, "work": work}) + "\n")


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    """A tiny normalized corpus: two scripture books and one patristic work."""
    norm = tmp_path / "normalized"
    works = [
        ("kjv/Gen.json", _work("kjv/gen", "kjv", date_composed=-500),
         [_chunk("kjv/gen", "Gen.1.1", "In the beginning", 0),
          _chunk("kjv/gen", "Gen.1.2", "And the earth", 1)]),
        ("kjv/Exod.json", _work("kjv/exod", "kjv"),
         [_chunk("kjv/exod", "Exod.1.1", "Now these are", 0)]),
        ("pta/x.json",
         _work("pta/x", "pta", genre="patristic", author="Augustinus",
               author_ids=["augustine-of-hippo"], license="cc-by-sa-4.0"),
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
            "kjv": "King James Version",
            "pta": "Patristic Text Archive",
        }
        rows = {r["id"]: r for r in index["works"]}
        assert rows["kjv/gen"]["chunks"] == 2
        assert rows["kjv/gen"]["date"] == -500
        assert rows["kjv/gen"]["file"] == "works/kjv/Gen.json"
        assert rows["pta/x"]["author"] == "Augustinus"
        assert rows["pta/x"]["author_ids"] == ["augustine-of-hippo"]
        assert rows["kjv/gen"]["author_ids"] == []
        assert rows["pta/x"]["license"] == "cc-by-sa-4.0"
        for row in index["works"]:
            assert (out / row["file"]).exists()

    def test_version_group(self, corpus: Path, tmp_path: Path):
        """Rows carry their version group (#178); a work with no other version has null."""
        _add_works(corpus, [
            ("web/Gen.json", _work("web/gen", "web"),
             [_chunk("web/gen", "Gen.1.1", "In the beginning", 0)]),
            ("npnf-works/y.json", _work("npnf-works/y", "npnf-works", genre="patristic",
                                        translation_of="pta/x"),
             [_chunk("npnf-works/y", "1.1", "first", 0)]),
        ])
        out = tmp_path / "library"
        export_library(corpus, out)
        rows = {r["id"]: r for r in json.loads((out / "index.json").read_text())["works"]}
        assert rows["kjv/gen"]["version_group"] == rows["web/gen"]["version_group"] == "book:gen"
        assert rows["npnf-works/y"]["version_group"] == rows["pta/x"]["version_group"] == "pta/x"
        assert rows["kjv/exod"]["version_group"] is None

    def test_authors_file(self, corpus: Path, tmp_path: Path):
        out = tmp_path / "library"
        export_library(corpus, out)
        authors = json.loads((out / "authors.json").read_text(encoding="utf-8"))["authors"]
        ids = [a["id"] for a in authors]
        assert ids == sorted(ids)
        assert len(ids) == len(author_index().authors)
        aug = next(a for a in authors if a["id"] == "augustine-of-hippo")
        assert aug["name"] == "Augustine of Hippo"
        assert "Augustinus" in aug["aliases"]
        assert aug["birth"] == {"low": 354, "high": 354, "confidence": "established"}
        assert aug["pseudo_of"] is None
        pseudo = next(a for a in authors if a["id"] == "pseudo-augustine")
        assert pseudo["pseudo_of"] == "augustine-of-hippo"

    def test_unknown_author_id(self, corpus: Path, tmp_path: Path):
        manifest = corpus / "_works.jsonl"
        manifest.write_text(
            manifest.read_text(encoding="utf-8").replace("augustine-of-hippo", "nobody"),
            encoding="utf-8",
        )
        with pytest.raises(ExportError, match="nobody"):
            export_library(corpus, tmp_path / "library")

    def test_work_file(self, corpus: Path, tmp_path: Path):
        out = tmp_path / "library"
        export_library(corpus, out)
        gen = json.loads((out / "works/kjv/Gen.json").read_text(encoding="utf-8"))
        # A Scripture book carries org_refs (#144), empty when its refs are in org numbering.
        assert gen == {
            "work_id": "kjv/gen",
            "ref_prefix": "Gen.1",
            "org_refs": {},
            "chunks": [["1", "In the beginning"], ["2", "And the earth"]],
        }
        pta = json.loads((out / "works/pta/x.json").read_text(encoding="utf-8"))
        # Sorted by chunk_index; out-of-period flag as third element.
        assert pta["chunks"] == [["1", "first"], ["2", "second", 1]]
        # Only Scripture books are versified.
        assert "org_refs" not in pta

    def test_org_refs(self, corpus: Path, tmp_path: Path):
        """org_refs maps the native refs that differ from org (BHS) numbering (#144)."""
        _add_works(corpus, [
            ("clementine/Ps.json", _work("clementine/ps", "clementine"),
             [_chunk("clementine/ps", "Ps.9.21", "Constitue", 0),
              _chunk("clementine/ps", "Ps.9.22", "Ut quid Domine", 1),
              _chunk("clementine/ps", "Ps.22.1", "Dominus regit me", 2)]),
            ("kjv/Ps.json", _work("kjv/ps", "kjv"),
             [_chunk("kjv/ps", "Ps.3.1", "Lord, how are they increased", 0),
              _chunk("kjv/ps", "Ps.23.1", "The Lord is my shepherd", 1)]),
        ])
        out = tmp_path / "library"
        export_library(corpus, out)
        vul = json.loads((out / "works/clementine/Ps.json").read_text(encoding="utf-8"))
        assert vul["ref_prefix"] == "Ps"
        # Vulgate 9.22 is Hebrew 10.1 and Vulgate 22 is Hebrew 23; 9.21 is unchanged.
        assert vul["org_refs"] == {"9.22": "Ps.10.1", "22.1": "Ps.23.1"}
        kjv = json.loads((out / "works/kjv/Ps.json").read_text(encoding="utf-8"))
        # The Hebrew counts the psalm's title as verse 1.
        assert kjv["org_refs"] == {"3.1": "Ps.3.2"}

    def test_org_refs_follow_versification(
        self, corpus: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """An up-to-date Scripture book is rewritten when only the versification changes."""
        out = tmp_path / "library"
        export_library(corpus, out)
        assert export_library(corpus, out)["written"] == 0
        monkeypatch.setattr(
            "scripts.export_library.to_org_ref",
            lambda source, ref: "Gen.9.9" if ref == "Gen.1.1" else ref,
        )
        assert export_library(corpus, out)["written"] == 1
        gen = json.loads((out / "works/kjv/Gen.json").read_text(encoding="utf-8"))
        assert gen["org_refs"] == {"1": "Gen.9.9"}

    def test_idempotent(self, corpus: Path, tmp_path: Path):
        out = tmp_path / "library"
        export_library(corpus, out)
        first = (out / "index.json").read_bytes()
        counts = export_library(corpus, out)
        assert counts["written"] == 0
        # Byte-identical, so the upload sees no change.
        assert (out / "index.json").read_bytes() == first
        assert len(json.loads(first)["version"]) == 16

    def test_version_tracks_text_changes(self, corpus: Path, tmp_path: Path):
        out = tmp_path / "library"
        export_library(corpus, out)
        before = json.loads((out / "index.json").read_text())["version"]
        # Same chunk count, different text: the index rows are unchanged.
        src = corpus / "kjv/Exod.json"
        src.write_text(json.dumps([_chunk("kjv/exod", "Exod.1.1", "Changed", 0)]))
        future = src.stat().st_mtime + 10
        os.utime(src, (future, future))
        export_library(corpus, out)
        assert json.loads((out / "index.json").read_text())["version"] != before

    def test_rebuilds_changed_source(self, corpus: Path, tmp_path: Path):
        out = tmp_path / "library"
        export_library(corpus, out)
        src = corpus / "kjv/Exod.json"
        src.write_text(json.dumps([
            _chunk("kjv/exod", "Exod.1.1", "Now these are", 0),
            _chunk("kjv/exod", "Exod.1.2", "Reuben", 1),
        ]), encoding="utf-8")
        future = src.stat().st_mtime + 10
        os.utime(src, (future, future))
        counts = export_library(corpus, out)
        assert counts["written"] == 1
        rows = {r["id"]: r for r in json.loads((out / "index.json").read_text())["works"]}
        assert rows["kjv/exod"]["chunks"] == 2

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
        (corpus / "kjv/Exod.json").unlink()
        with pytest.raises(ExportError, match="missing"):
            export_library(corpus, tmp_path / "library")


class TestSourceLabels:
    def test_fallback(self):
        assert source_label("kjv") == "King James Version"
        assert source_label("nope/unknown") == "nope/unknown"

    def test_every_corpus_source_has_label(self):
        manifest = REPO_ROOT / "data/normalized/_works.jsonl"
        if not manifest.exists():
            pytest.skip("normalized corpus not present")
        with manifest.open(encoding="utf-8") as f:
            sources = {json.loads(line)["work"]["source_id"] for line in f if line.strip()}
        missing = sorted(sources - SOURCE_LABELS.keys())
        assert not missing, f"Add these to patristica.sources.SOURCE_LABELS: {missing}"
