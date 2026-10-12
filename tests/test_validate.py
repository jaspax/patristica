"""Tests for scripts.validate: genre comes from Work.genre, not the path prefix."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.validate import (
    UNKNOWN_GENRE,
    ValidationInputError,
    _check_canonical_refs,
    _check_scripture_coverage,
    _check_works_manifest,
    _chunk_count_report,
    _load_work_records,
)


def _chunk(work_id: str, ref: str, index: int = 0, language: str = "eng") -> dict:
    return {
        "chunk_id": f"{work_id}#{ref}",
        "work_id": work_id,
        "canonical_ref": ref,
        "language": language,
        "text": "some text here",
        "chunk_index": index,
    }


def _work(work_id: str, source_id: str, genre: str | None) -> dict:
    return {"work_id": work_id, "source_id": source_id, "genre": genre, "title": work_id}


def _write_manifest(tmp_path: Path, entries: list[tuple[str, dict]]) -> Path:
    norm = tmp_path / "normalized"
    norm.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"path": path, "work": work}) for path, work in entries]
    (norm / "_works.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return tmp_path


@pytest.fixture()
def records(tmp_path: Path) -> dict[str, dict]:
    """Works whose path prefix deliberately disagrees with their genre."""
    data_dir = _write_manifest(tmp_path, [
        # A patristic work filed under a 'liturgical/' path prefix.
        ("liturgical/src-a/hom.json", _work("src-a/hom", "liturgical/src-a", "patristic")),
        # A council text filed under a 'patristic/' path prefix.
        ("patristic/src-b/canons.json", _work("src-b/canons", "patristic/src-b", "council")),
        # Scripture under an unrelated prefix.
        ("other/bib/Gen.json", _work("other/bib/gen", "other/bib", "scripture")),
        # A 'scripture/' path whose work is not scripture.
        ("scripture/notes/x.json", _work("scripture/notes/x", "scripture/notes", "patristic")),
    ])
    return _load_work_records(data_dir)


class TestLoadWorkRecords:
    def test_keyed_by_work_id(self, records: dict[str, dict]):
        assert records["src-a/hom"]["genre"] == "patristic"
        assert len(records) == 4

    def test_missing_manifest_raises(self, tmp_path: Path):
        with pytest.raises(ValidationInputError, match="_works.jsonl"):
            _load_work_records(tmp_path)

    def test_malformed_line_raises(self, tmp_path: Path):
        norm = tmp_path / "normalized"
        norm.mkdir()
        (norm / "_works.jsonl").write_text('{"path": "a.json"}\n', encoding="utf-8")
        with pytest.raises(ValidationInputError, match=":1:"):
            _load_work_records(tmp_path)

    def test_blank_lines_ignored(self, tmp_path: Path):
        norm = tmp_path / "normalized"
        norm.mkdir()
        line = json.dumps({"path": "a/b/c.json", "work": _work("b/c", "a/b", "council")})
        (norm / "_works.jsonl").write_text(f"\n{line}\n\n", encoding="utf-8")
        assert list(_load_work_records(tmp_path)) == ["b/c"]


class TestChunkCountReport:
    def test_counts_by_work_genre_not_path(self, records: dict[str, dict]):
        chunks = [
            _chunk("src-a/hom", "Hom.1", 0, "cop"),
            _chunk("src-a/hom", "Hom.2", 1, "cop"),
            _chunk("src-b/canons", "Can.1"),
            _chunk("other/bib/gen", "Gen.1.1", 0, "hbo"),
            _chunk("scripture/notes/x", "X.1"),
        ]
        report = _chunk_count_report(chunks, records)
        assert report["by_genre"] == {"patristic": 3, "council": 1, "scripture": 1}
        assert "liturgical" not in report["by_genre"]
        assert report["by_language"] == {"cop": 2, "eng": 2, "hbo": 1}

    def test_unknown_work_counted_as_unknown(self, records: dict[str, dict]):
        report = _chunk_count_report([_chunk("nowhere/w", "W.1")], records)
        assert report["by_genre"] == {UNKNOWN_GENRE: 1}


class TestWorksManifestCheck:
    def test_missing_work_is_an_error(self, records: dict[str, dict]):
        result = _check_works_manifest(
            [_chunk("nowhere/w", "W.1"), _chunk("nowhere/w", "W.2", 1), _chunk("src-a/hom", "H.1")],
            records,
        )
        missing = result["work_missing_from_manifest"]
        assert missing["status"] == "fail"
        assert missing["examples"] == ["nowhere/w"]
        assert result["work_missing_genre"]["status"] == "pass"

    def test_missing_genre_is_an_error(self):
        result = _check_works_manifest([], {"a/b": _work("a/b", "a", None)})
        assert result["work_missing_genre"]["examples"] == ["a/b"]


class TestScriptureByGenre:
    def test_scripture_ref_check_uses_genre(self, records: dict[str, dict]):
        chunks = [
            # Scripture work under a non-'scripture/' prefix: strict ref check applies.
            _chunk("other/bib/gen", "NotABook.1.1"),
            # Non-scripture work under 'scripture/': prose rules apply.
            _chunk("scripture/notes/x", "X.1"),
        ]
        result = _check_canonical_refs(chunks, records)
        assert result["scripture_ref_malformed"]["examples"] == [
            "other/bib/gen#NotABook.1.1 ('NotABook.1.1')"
        ]
        assert result["prose_ref_malformed"]["status"] == "pass"

    def test_coverage_uses_genre(self, records: dict[str, dict]):
        coverage = _check_scripture_coverage(
            records, [_chunk("other/bib/gen", "Gen.1.1"), _chunk("scripture/notes/x", "X.1.1")]
        )
        assert list(coverage["coverage_by_source"]) == ["other/bib"]
        assert coverage["sources_with_zero_chunks"] == []
