"""Tests for scripts.validate: genre comes from Work.genre, not the path prefix."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import validate
from scripts.validate import (
    UNKNOWN_GENRE,
    ValidationInputError,
    _check_authors,
    _check_canonical_refs,
    _check_cross_references,
    _check_date_plausibility,
    _check_id_uniqueness,
    _check_scripture_coverage,
    _check_works_manifest,
    _chunk_count_report,
    _load_chunks,
    _load_work_records,
    _load_works,
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
    """Works whose genre can't be told from their path or source (#102)."""
    data_dir = _write_manifest(tmp_path, [
        ("src-a/hom.json", _work("src-a/hom", "src-a", "patristic")),
        ("src-b/canons.json", _work("src-b/canons", "src-b", "council")),
        ("bib/Gen.json", _work("bib/gen", "bib", "scripture")),
        # A non-scripture work from a Bible source (cf. gez/clem, #74).
        ("bib/notes.json", _work("bib/notes", "bib", "patristic")),
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
            _chunk("bib/gen", "Gen.1.1", 0, "hbo"),
            _chunk("bib/notes", "X.1"),
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
            # Scripture work: strict ref check applies.
            _chunk("bib/gen", "NotABook.1.1"),
            # Non-scripture work from the same source: prose rules apply.
            _chunk("bib/notes", "X.1"),
        ]
        result = _check_canonical_refs(chunks, records)
        assert result["scripture_ref_malformed"]["examples"] == [
            "bib/gen#NotABook.1.1 ('NotABook.1.1')"
        ]
        assert result["prose_ref_malformed"]["status"] == "pass"

    def test_derived_verse_of_a_scripture_ref_is_well_formed(self, records: dict[str, dict]):
        """A split many-verse unit (#129) is a verse ref plus ``.sN``."""
        chunks = [_chunk("bib/gen", "Gen.2.35.s1"), _chunk("bib/gen", "Gen.2.s1", 1)]
        result = _check_canonical_refs(chunks, records)
        assert result["scripture_ref_malformed"]["examples"] == ["bib/gen#Gen.2.s1 ('Gen.2.s1')"]

    def test_coverage_uses_genre(self, records: dict[str, dict]):
        coverage = _check_scripture_coverage(
            records, [_chunk("bib/gen", "Gen.1.1"), _chunk("bib/notes", "X.1.1")]
        )
        assert list(coverage["coverage_by_source"]) == ["bib"]
        assert coverage["sources_with_zero_chunks"] == []


class TestWorksFromManifest:
    """Work list, orphan and duplicate-ID checks read ``_works.jsonl`` (#75)."""

    def test_load_works_keeps_one_record_per_line(self, tmp_path: Path):
        data_dir = _write_manifest(tmp_path, [
            ("a/src/w.json", _work("src/w", "a/src", "patristic")),
            ("b/src/w.json", _work("src/w", "b/src", "patristic")),
            ("a/src/v.json", _work("src/v", "a/src", "patristic")),
        ])
        works = _load_works(data_dir)
        assert [w["work_id"] for w in works] == ["src/w", "src/w", "src/v"]
        assert set(_load_work_records(data_dir)) == {"src/w", "src/v"}

    def test_missing_manifest_raises(self, tmp_path: Path):
        with pytest.raises(ValidationInputError, match="_works.jsonl"):
            _load_works(tmp_path)

    def test_duplicate_work_id_across_paths_is_an_error(self, tmp_path: Path):
        data_dir = _write_manifest(tmp_path, [
            ("a/src/w.json", _work("src/w", "a/src", "patristic")),
            ("b/src/w.json", _work("src/w", "b/src", "patristic")),
        ])
        result = _check_id_uniqueness(_load_works(data_dir), [])
        assert result["duplicate_work_ids"]["status"] == "fail"
        assert result["duplicate_work_ids"]["examples"] == ["src/w ×2"]

    def test_orphan_chunk_is_an_error(self, records: dict[str, dict]):
        works = list(records.values())
        chunks = [_chunk("src-a/hom", "Hom.1"), _chunk("nowhere/w", "W.1")]
        result = _check_cross_references(works, chunks, records)
        assert result["orphan_chunks"]["status"] == "fail"
        assert result["orphan_chunks"]["examples"] == ["nowhere/w#W.1"]

    def test_translation_of_checked_against_manifest(self, records: dict[str, dict]):
        works = [
            {**_work("x/eng", "x", "patristic"), "translation_of": "src-a/hom"},
            {**_work("x/bad", "x", "patristic"), "translation_of": "missing/w"},
        ]
        result = _check_cross_references(works, [], records)
        assert result["bad_translation_of"]["examples"] == ["x/bad → missing/w"]

    def test_load_chunks_skips_underscore_files(self, tmp_path: Path):
        norm = tmp_path / "normalized" / "src"
        norm.mkdir(parents=True)
        (norm / "w.json").write_text(json.dumps([_chunk("src/w", "W.1")]), encoding="utf-8")
        (tmp_path / "normalized" / "_stale.json").write_text("{}", encoding="utf-8")
        chunks, errors = _load_chunks(tmp_path)
        assert [c["chunk_id"] for c in chunks] == ["src/w#W.1"]
        assert errors == []


class TestMain:
    def _run(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[int, dict]:
        out = tmp_path / "report.json"
        monkeypatch.setattr(
            "sys.argv", ["validate", "--data-dir", str(tmp_path), "--output", str(out)]
        )
        with pytest.raises(SystemExit) as exc:
            validate.main()
        report = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
        return exc.value.code, report

    def _write_work(self, tmp_path: Path, rel: str, chunks: list[dict]) -> None:
        path = tmp_path / "normalized" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(chunks), encoding="utf-8")

    def test_runs_from_manifest_alone(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        _write_manifest(tmp_path, [
            ("src/w.json", _work("src/w", "src", "patristic")),
        ])
        self._write_work(tmp_path, "src/w.json", [
            _chunk("src/w", "W.1", 0), _chunk("src/w", "W.2", 1),
        ])
        code, report = self._run(tmp_path, monkeypatch)
        assert not (tmp_path / "normalized" / "_index.json").exists()
        assert code == 0
        assert report["summary"]["total_works"] == 1
        assert report["checks"]["cross_references"]["orphan_chunks"]["status"] == "pass"
        assert report["checks"]["id_uniqueness"]["duplicate_work_ids"]["status"] == "pass"

    def test_reports_orphans_and_duplicates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        _write_manifest(tmp_path, [
            ("a/w.json", _work("src/w", "a", "patristic")),
            ("b/w.json", _work("src/w", "b", "patristic")),
        ])
        self._write_work(tmp_path, "a/w.json", [_chunk("src/w", "W.1")])
        self._write_work(tmp_path, "b/o.json", [_chunk("src/orphan", "O.1")])
        code, report = self._run(tmp_path, monkeypatch)
        assert code == 1
        xref = report["checks"]["cross_references"]
        assert xref["orphan_chunks"]["examples"] == ["src/orphan#O.1"]
        assert report["checks"]["id_uniqueness"]["duplicate_work_ids"]["examples"] == ["src/w ×2"]

    def test_missing_manifest_exits(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        code, report = self._run(tmp_path, monkeypatch)
        assert code == 2
        assert report == {}


class TestAuthors:
    def test_unresolved_and_stale(self):
        works = [
            {"work_id": "a/1", "author": "Augustinus", "author_ids": ["augustine-of-hippo"]},
            {"work_id": "a/2", "author": None, "author_ids": []},
            {"work_id": "a/3", "author": "Nobody Whatsoever", "author_ids": []},
            {"work_id": "a/4", "author": "Hieronymus"},
        ]
        result = _check_authors(works)
        assert result["unresolved_authors"]["status"] == "fail"
        assert result["unresolved_authors"]["examples"] == [
            "'Nobody Whatsoever' (1 works, e.g. a/3)"
        ]
        assert result["stale_author_ids"]["examples"] == ["a/4: None != ['jerome']"]

    def test_period_flag_follows_author_birth_year(self):
        records = {
            "a/damian": {"work_id": "a/damian", "author_ids": ["peter-damian"]},
            "a/anon": {"work_id": "a/anon", "author_ids": []},
        }
        chunks = [
            # Born 1007: in period although dated after COMPOSED_BY.
            {**_chunk("a/damian", "D.1"), "date_composed": 1056, "out_of_period": False},
            {**_chunk("a/damian", "D.2"), "date_composed": 1056, "out_of_period": True},
            {**_chunk("a/anon", "A.1"), "date_composed": 1056, "out_of_period": False},
        ]
        result = _check_date_plausibility(chunks, records)
        assert result["period_flag_mismatch"]["examples"] == [
            "a/damian#D.2 (out_of_period=True, author born 1007)",
            "a/anon#A.1 (out_of_period=False, date_composed=1056)",
        ]
