"""Tests for scripts.status (#130) and validate's --if-changed / --summary."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica import genres
from scripts import normalize as nz
from scripts import status, validate


@pytest.fixture
def overrides(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    table: dict[str, str] = {}
    monkeypatch.setattr(genres, "_overrides", lambda: table)
    return table


def write_raw(raw: Path, rel: str, text: str = "Text") -> None:
    source_id, name = rel.split("/")[0], Path(rel).stem
    path = raw / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "work": {"work_id": f"{source_id}/{name}", "source_id": source_id, "title": "T",
                 "genre": "patristic", "language": "eng", "license": "public_domain"},
        "paragraphs": [{"ref": "T.1", "text": text}],
    }), encoding="utf-8")


@pytest.fixture
def corpus(tmp_path: Path, overrides: dict[str, str], monkeypatch) -> dict[str, Path]:
    monkeypatch.setattr(nz, "normalize_code_hash", lambda: "code-1")
    raw, norm = tmp_path / "raw", tmp_path / "normalized"
    write_raw(raw, "a/one.json")
    write_raw(raw, "a/two.json")
    nz.normalize_all(raw, norm)
    return {"raw": raw, "norm": norm, "trans": tmp_path / "translations",
            "align": tmp_path / "alignments"}


def levels(rows: list[status.Row]) -> dict[tuple[str, str], str]:
    return {(r.step, r.check): r.level for r in rows}


def collect(c: dict[str, Path], monkeypatch, **kw) -> list[status.Row]:
    monkeypatch.setattr(status, "align_code_current", lambda align_dir: True)
    return status.collect(c["norm"], trans=c["trans"], align_dir=c["align"], **kw)


def test_fresh_corpus_is_all_ok(corpus, monkeypatch) -> None:
    rows = collect(corpus, monkeypatch, raw=corpus["raw"])
    assert set(levels(rows).values()) == {"ok"}
    assert ("normalize", "local raw") in levels(rows)


def test_curation_change_fails_normalize(corpus, overrides, monkeypatch) -> None:
    overrides["a/two"] = "apocrypha"
    rows = collect(corpus, monkeypatch)
    assert levels(rows)[("normalize", "works")] == "fail"
    assert "a/two.json" in next(r.detail for r in rows if r.check == "works")


def test_code_change_fails_normalize(corpus, monkeypatch) -> None:
    monkeypatch.setattr(nz, "normalize_code_hash", lambda: "code-2")
    assert levels(collect(corpus, monkeypatch))[("normalize", "code")] == "fail"


def test_local_raw_changes_warn_and_metadata_files_dont_count(corpus, monkeypatch) -> None:
    write_raw(corpus["raw"], "a/two.json", text="Older")
    write_raw(corpus["raw"], "b/new.json")
    (corpus["raw"] / "a" / "catalog.json").write_text('{"works": []}')
    changed, new = status.raw_changes(corpus["norm"], corpus["raw"])
    assert (changed, new) == (["a/two.json"], ["b/new.json"])
    assert levels(collect(corpus, monkeypatch, raw=corpus["raw"]))[
        ("normalize", "local raw")] == "warn"


def test_check_exits_nonzero_only_on_failures(corpus, overrides, monkeypatch, capsys) -> None:
    monkeypatch.setattr(status, "align_code_current", lambda align_dir: True)
    monkeypatch.setattr("sys.argv", [
        "status", "--normalized-dir", str(corpus["norm"]), "--translations-dir",
        str(corpus["trans"]), "--alignments-dir", str(corpus["align"]), "--check"])
    status.main()  # all ok: no exit
    overrides["a/one"] = "apocrypha"
    with pytest.raises(SystemExit) as exc:
        status.main()
    assert exc.value.code == 1
    assert "❌" in capsys.readouterr().out


def test_render_is_a_markdown_table() -> None:
    table = status.render([status.Row("normalize", "code", "ok", "current")])
    assert table.splitlines() == ["| step | check | | detail |", "|---|---|---|---|",
                                  "| normalize | code | ✅ | current |"]


# ---------------------------------------------------------------------------
# validate --if-changed / --summary
# ---------------------------------------------------------------------------


def test_validate_runs_only_when_its_inputs_change() -> None:
    assert validate.inputs_changed(["web/src/app/page.tsx", "README.md"]) == []
    assert validate.inputs_changed(["data/normalized/kjv/Gen.json"]) == [
        "data/normalized/kjv/Gen.json"]
    assert validate.inputs_changed(["patristica/data/authors.csv"]) == [
        "patristica/data/authors.csv"]
    assert "patristica/section_numbers.py" in validate.input_files()  # its code
    assert validate.inputs_changed(["scripts/validate.py"]) == ["scripts/validate.py"]
    assert validate.inputs_changed(["data/normalized/_fingerprint.json",
                                    "data/normalized/_fingerprints.jsonl"]) == []
    # the nightly MT curation tables (#425): validate doesn't read them
    assert validate.inputs_changed(["patristica/data/mt_exceptions.csv",
                                    "patristica/data/mt_blocked.csv"]) == []
    assert not any("machine_translation" in p for p in validate.input_files())


def test_validate_summary_lists_failures_first(tmp_path: Path) -> None:
    report = {
        "summary": {"total_works": 2, "total_chunks": 10, "errors": 1, "warnings": 3},
        "checks": {"a": {"short": {"status": "warn", "violation_count": 3},
                         "fine": {"status": "pass", "violation_count": 0}},
                   "b": {"broken": {"status": "fail", "violation_count": 1}}},
    }
    out = tmp_path / "summary.md"
    validate.write_summary(report, out)
    lines = out.read_text().splitlines()
    assert "**1 errors**, 3 warnings." in lines[2]
    assert lines[6:8] == ["| broken | fail | 1 |", "| short | warn | 3 |"]


def test_missing_normalized_file_skips_dependent_checks(corpus, monkeypatch) -> None:
    """The table is still written when a manifested file is missing (#204 review)."""
    (corpus["norm"] / "a" / "two.json").unlink()
    rows = collect(corpus, monkeypatch)
    by = {(r.step, r.check): r for r in rows}
    assert by[("normalize", "manifest")].level == "fail"
    assert "a/two.json" in by[("normalize", "manifest")].detail
    for key in (("align", "groups"), ("align", "units"), ("translate", "pending")):
        assert by[key].level == "fail" and by[key].detail.startswith("skipped")
    assert ("embed", "pending") not in by  # --vectors wasn't asked for
    assert "❌" in status.render(rows)


def test_a_check_that_raises_becomes_a_failing_row(corpus, monkeypatch) -> None:
    def broken(norm, trans):
        raise RuntimeError("store unreadable")

    monkeypatch.setattr(status, "pending_translations", broken)
    rows = collect(corpus, monkeypatch)
    row = next(r for r in rows if r.step == "translate")
    assert row.level == "fail" and "RuntimeError: store unreadable" in row.detail
    assert levels(rows)[("normalize", "code")] == "ok"  # the other checks still ran


def test_brief_lists_only_what_needs_attention() -> None:
    rows = [status.Row("normalize", "code", "ok", "current"),
            status.Row("ingest", "code", "warn", "1 source changed"),
            status.Row("align", "groups", "fail", "2 stale")]
    assert status.render_brief(rows).splitlines() == [
        "warning: ingest code: 1 source changed", "FAIL: align groups: 2 stale",
        "1 of 3 checks current"]
    assert status.render_brief(rows[:1]) == "all 1 checks current"
