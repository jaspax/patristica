"""Tests for patristica.lookup: the index is built from ``_works.jsonl`` (#75)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica import lookup as lk


def _work(work_id: str, source_id: str, title: str, **extra: object) -> dict:
    return {
        "work_id": work_id, "source_id": source_id, "title": title,
        "author": extra.get("author"), "translation_of": extra.get("translation_of"),
        "language": extra.get("language", "eng"), "genre": "scripture",
    }


def _chunks(work_id: str, refs: list[str], language: str = "eng", text: str = "t") -> list[dict]:
    return [
        {"chunk_id": f"{work_id}#{r}", "work_id": work_id, "canonical_ref": r,
         "language": language, "text": text, "chunk_index": i}
        for i, r in enumerate(refs)
    ]


def _corpus(tmp_path: Path, works: list[tuple[str, dict, list[dict]]]) -> Path:
    norm = tmp_path / "normalized"
    norm.mkdir(parents=True, exist_ok=True)
    lines = []
    for rel, work, chunks in works:
        path = norm / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
        lines.append(json.dumps({"path": rel, "work": work}, sort_keys=True))
    (norm / "_works.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def data_dir(tmp_path: Path) -> Path:
    return _corpus(tmp_path, [
        ("kjv/Gen.json", _work("kjv/gen", "kjv", "Genesis"),
         _chunks("kjv/gen", ["Gen.1.1", "Gen.1.2", "Gen.2.1"])),
        ("oshb/Gen.json",
         _work("oshb/gen", "oshb", "Bereshit", language="hbo"),
         _chunks("oshb/gen", ["Gen.1.1"], language="hbo")),
        ("x/hom.json",
         _work("x/hom", "x", "Homily", author="John", translation_of="x/orig"),
         _chunks("x/hom", ["Hom.1"])),
    ])


class TestBuildIndex:
    def test_entries_from_manifest_and_first_chunk(self, data_dir: Path):
        entries = lk.build_index(data_dir)["entries"]
        assert sorted(entries) == ["Gen", "Hom"]
        hom = entries["Hom"][0]
        assert hom == {
            "work_id": "x/hom", "path": "x/hom.json", "canonical_prefix": "Hom",
            "language": "eng", "title": "Homily", "author": "John",
            "source_id": "x", "translation_of": "x/orig",
        }
        assert [e["language"] for e in entries["Gen"]] == ["eng", "hbo"]

    def test_writes_nothing(self, data_dir: Path):
        before = sorted(p.name for p in (data_dir / "normalized").iterdir())
        lk.build_index(data_dir)
        assert sorted(p.name for p in (data_dir / "normalized").iterdir()) == before
        assert not (data_dir / "normalized" / "_index.json").exists()

    def test_deterministic(self, data_dir: Path):
        assert lk.build_index(data_dir) == lk.build_index(data_dir)
        assert "built_at" not in lk.build_index(data_dir)

    def test_reflects_manifest_changes(self, data_dir: Path):
        """No cache: a work dropped from the manifest disappears immediately."""
        manifest = data_dir / "normalized" / "_works.jsonl"
        lines = manifest.read_text(encoding="utf-8").splitlines()
        manifest.write_text("\n".join(lines[:1]) + "\n", encoding="utf-8")
        assert sorted(lk.build_index(data_dir)["entries"]) == ["Gen"]

    def test_missing_manifest_raises(self, tmp_path: Path):
        with pytest.raises(lk.LookupIndexError, match="_works.jsonl"):
            lk.build_index(tmp_path)

    def test_malformed_manifest_raises(self, tmp_path: Path):
        norm = tmp_path / "normalized"
        norm.mkdir()
        (norm / "_works.jsonl").write_text('{"path": "a.json"}\n', encoding="utf-8")
        with pytest.raises(lk.LookupIndexError, match=":1:"):
            lk.build_index(tmp_path)

    def test_missing_or_empty_file_skipped(self, tmp_path: Path):
        data_dir = _corpus(tmp_path, [
            ("a/b/empty.json", _work("b/empty", "a/b", "Empty"), []),
        ])
        manifest = data_dir / "normalized" / "_works.jsonl"
        gone = json.dumps({"path": "a/b/gone.json", "work": _work("b/gone", "a/b", "Gone")})
        manifest.write_text(manifest.read_text(encoding="utf-8") + gone + "\n", encoding="utf-8")
        assert lk.build_index(data_dir)["entries"] == {}


class TestFirstChunk:
    def test_reads_past_block_size(self, tmp_path: Path):
        big = "α" * (3 * lk._PEEK_BYTES)
        path = tmp_path / "w.json"
        path.write_text(json.dumps(_chunks("w", ["W.1", "W.2"], text=big), ensure_ascii=False,
                                   indent=2), encoding="utf-8")
        first = lk._first_chunk(path)
        assert first is not None
        assert first["canonical_ref"] == "W.1"
        assert first["text"] == big

    def test_empty_list(self, tmp_path: Path):
        path = tmp_path / "w.json"
        path.write_text("[\n]\n", encoding="utf-8")
        assert lk._first_chunk(path) is None

    def test_not_a_list(self, tmp_path: Path):
        path = tmp_path / "w.json"
        path.write_text('{"a": 1}', encoding="utf-8")
        with pytest.raises(ValueError):
            lk._first_chunk(path)

    def test_truncated(self, tmp_path: Path):
        path = tmp_path / "w.json"
        path.write_text('[{"canonical_ref": "W.1"', encoding="utf-8")
        with pytest.raises(ValueError):
            lk._first_chunk(path)


class TestQueries:
    def test_lookup_filters_chunks(self, data_dir: Path):
        results = lk.lookup("Gen.1", data_dir, lang="eng")
        assert len(results) == 1
        assert [c["canonical_ref"] for c in results[0].chunks] == ["Gen.1.1", "Gen.1.2"]

    def test_list_works(self, data_dir: Path):
        works = lk.list_works(data_dir, lang="hbo")
        assert [w["work_id"] for w in works] == ["oshb/gen"]

    def test_list_translations(self, data_dir: Path):
        assert {e["source_id"] for e in lk.list_translations("Gen.1.1", data_dir)} == {
            "kjv", "oshb",
        }
