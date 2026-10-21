"""Staleness of normalized data (#130): fingerprints in scripts.normalize.

The first tests check the committed ``data/normalized`` against the code and
curated data on this branch; they are what makes CI fail when normalize's code,
``genre_overrides.csv`` or the author index change without a re-normalize.
The rest exercise the skip / raw-guard logic on a small corpus.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica import genres
from scripts import normalize as nz
from scripts import status

NORMALIZED = Path(__file__).resolve().parents[1] / "data" / "normalized"
RERUN = "re-run `uv run python -m scripts.normalize` and commit data/normalized"


# ---------------------------------------------------------------------------
# The committed data
# ---------------------------------------------------------------------------


def test_committed_data_was_normalized_with_this_code() -> None:
    assert status.normalize_code_current(NORMALIZED), (
        f"normalize's code changed since data/normalized was produced: {RERUN}"
    )


def test_every_work_has_a_current_fingerprint() -> None:
    missing = status.unfingerprinted_works(NORMALIZED)
    assert not missing, f"works without a fingerprint, or the reverse ({RERUN}): {missing[:10]}"
    stale = status.curation_stale_works(NORMALIZED)
    assert not stale, (
        f"genre_overrides.csv or the author index changed for these works ({RERUN}): {stale[:10]}"
    )


def test_manifest_lists_exactly_the_normalized_files() -> None:
    unlisted, absent = status.manifest_mismatch(NORMALIZED)
    assert not unlisted, f"normalized files missing from _works.jsonl ({RERUN}): {unlisted[:10]}"
    assert not absent, f"_works.jsonl lists normalized files that don't exist: {absent[:10]}"


def test_fingerprints_stay_out_of_the_works_manifest() -> None:
    """build_index hashes whole _works.jsonl lines: a new key would reload the DB."""
    line = (NORMALIZED / nz.WORKS_MANIFEST).read_text(encoding="utf-8").splitlines()[0]
    assert set(json.loads(line)) == {"path", "work"}


# ---------------------------------------------------------------------------
# Skip and guard logic
# ---------------------------------------------------------------------------


@pytest.fixture
def overrides(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    table: dict[str, str] = {}
    monkeypatch.setattr(genres, "_overrides", lambda: table)
    return table


@pytest.fixture
def code(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The step's code hash, changeable by the test: ``code[0] = ...``."""
    current = ["code-1"]
    monkeypatch.setattr(nz, "normalize_code_hash", lambda: current[0])
    return current


@pytest.fixture
def built(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Paths of the works normalized (rebuilt), in order."""
    calls: list[str] = []
    original = nz._normalize_record

    def record(raw_record: dict, raw_path: Path, output_dir: Path) -> int:
        calls.append(nz._output_rel(raw_path).as_posix())
        return original(raw_record, raw_path, output_dir)

    monkeypatch.setattr(nz, "_normalize_record", record)
    return calls


def write_raw(raw: Path, rel: str, text: str = "Text", genre: str = "patristic") -> None:
    source_id, name = rel.split("/")[0], Path(rel).stem
    path = raw / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "work": {"work_id": f"{source_id}/{name}", "source_id": source_id, "title": "T",
                 "genre": genre, "language": "eng", "license": "public_domain"},
        "paragraphs": [{"ref": "T.1", "text": text}],
    }), encoding="utf-8")


@pytest.fixture
def corpus(tmp_path: Path, overrides: dict[str, str]) -> tuple[Path, Path]:
    raw, norm = tmp_path / "raw", tmp_path / "normalized"
    write_raw(raw, "a/one.json")
    write_raw(raw, "a/two.json")
    write_raw(raw, "b/three.json")
    return raw, norm


def chunk_text(norm: Path, rel: str) -> str:
    return json.loads((norm / rel).read_text(encoding="utf-8"))[0]["text"]


def manifest_text(norm: Path) -> str:
    return (norm / nz.WORKS_MANIFEST).read_text(encoding="utf-8")


ALL = ["a/one.json", "a/two.json", "b/three.json"]


def test_first_run_records_fingerprints(corpus, code, built) -> None:
    raw, norm = corpus
    nz.normalize_all(raw, norm)
    assert built == ALL
    assert nz.read_step_fingerprints(norm) == {"normalize": {"code": "code-1"}}
    fps = nz.read_work_fingerprints(norm)
    assert sorted(fps) == ALL
    assert all(set(fp) == {"raw", "curated"} for fp in fps.values())
    assert all(set(json.loads(line)) == {"path", "work"}
               for line in manifest_text(norm).splitlines())


def test_unchanged_inputs_are_skipped(corpus, code, built) -> None:
    raw, norm = corpus
    nz.normalize_all(raw, norm)
    built.clear()
    before = manifest_text(norm), (norm / nz.FINGERPRINTS_FILE).read_text()
    nz.normalize_all(raw, norm)
    assert built == []
    assert (manifest_text(norm), (norm / nz.FINGERPRINTS_FILE).read_text()) == before
    nz.normalize_all(raw, norm, force=True)
    assert built == ALL


def test_code_change_rebuilds_every_work(corpus, code, built) -> None:
    raw, norm = corpus
    nz.normalize_all(raw, norm)
    built.clear()
    code[0] = "code-2"
    nz.normalize_all(raw, norm)
    assert built == ALL
    assert nz.read_step_fingerprints(norm)["normalize"]["code"] == "code-2"


def test_changed_raw_is_refused_until_accepted(corpus, code, built) -> None:
    raw, norm = corpus
    nz.normalize_all(raw, norm)
    built.clear()
    before = manifest_text(norm), nz.read_work_fingerprints(norm)
    write_raw(raw, "a/two.json", text="Older text")

    with pytest.raises(nz.RawChangedError, match="a/two.json"):
        nz.normalize_all(raw, norm)
    assert built == []
    assert chunk_text(norm, "a/two.json") == "Text"
    assert (manifest_text(norm), nz.read_work_fingerprints(norm)) == before

    with pytest.raises(nz.RawChangedError):  # --force doesn't bypass the guard
        nz.normalize_all(raw, norm, force=True)
    assert chunk_text(norm, "a/two.json") == "Text"

    built.clear()
    nz.normalize_all(raw, norm, accept_raw_change=True)
    assert built == ["a/two.json"]
    assert chunk_text(norm, "a/two.json") == "Older text"
    nz.normalize_all(raw, norm)  # now recorded: no refusal


def test_refused_work_keeps_its_manifest_entry(corpus, code) -> None:
    raw, norm = corpus
    nz.normalize_all(raw, norm)
    path = raw / "a/two.json"
    record = json.loads(path.read_text())
    record["work"]["title"] = "Old title"
    path.write_text(json.dumps(record))
    with pytest.raises(nz.RawChangedError):
        nz.normalize_all(raw, norm)
    assert nz.read_works_manifest(norm)["a/two.json"]["title"] == "T"


def test_refused_work_blocks_new_code_hash(corpus, code) -> None:
    raw, norm = corpus
    nz.normalize_all(raw, norm)
    write_raw(raw, "a/two.json", text="Older text")
    code[0] = "code-2"
    with pytest.raises(nz.RawChangedError):
        nz.normalize_all(raw, norm)
    assert nz.read_step_fingerprints(norm)["normalize"]["code"] == "code-1"


def test_new_source_normalizes_only_its_works(corpus, code, built) -> None:
    raw, norm = corpus
    nz.normalize_all(raw, norm)
    built.clear()
    write_raw(raw, "newsrc/alpha.json")
    write_raw(raw, "newsrc/beta.json")
    nz.normalize_all(raw, norm)
    assert built == ["newsrc/alpha.json", "newsrc/beta.json"]
    assert sorted(nz.read_work_fingerprints(norm)) == ALL + [
        "newsrc/alpha.json", "newsrc/beta.json"]
    assert nz.read_step_fingerprints(norm)["normalize"]["code"] == "code-1"


def test_missing_raw_keeps_entries_and_blocks_new_code_hash(corpus, code, built) -> None:
    raw, norm = corpus
    nz.normalize_all(raw, norm)
    before = nz.read_works_manifest(norm), nz.read_work_fingerprints(norm)
    (raw / "b/three.json").unlink()  # another machine: no raw for source b
    (raw / "b").rmdir()

    nz.normalize_all(raw, norm)
    assert (nz.read_works_manifest(norm), nz.read_work_fingerprints(norm)) == before

    code[0] = "code-2"
    built.clear()
    nz.normalize_all(raw, norm)
    assert built == ["a/one.json", "a/two.json"]
    assert nz.read_work_fingerprints(norm)["b/three.json"] == before[1]["b/three.json"]
    assert nz.read_step_fingerprints(norm)["normalize"]["code"] == "code-1"


def test_curation_change_rebuilds_only_that_work(corpus, code, built, overrides) -> None:
    raw, norm = corpus
    nz.normalize_all(raw, norm)
    built.clear()
    overrides["a/two"] = "apocrypha"
    nz.normalize_all(raw, norm)
    assert built == ["a/two.json"]
    assert nz.read_works_manifest(norm)["a/two.json"]["genre"] == "apocrypha"


def test_curated_hash_sees_a_removed_override(overrides) -> None:
    """Checked from the manifest's (curated) record, so removing an override
    must still change it."""
    work = {"work_id": "a/two", "genre": "patristic", "author": None}
    overrides["a/two"] = "apocrypha"
    with_override = nz.curated_hash({**work, "genre": "apocrypha"})
    del overrides["a/two"]
    assert nz.curated_hash({**work, "genre": "apocrypha"}) != with_override


def test_main_exits_nonzero_on_refusal(corpus, code, monkeypatch) -> None:
    raw, norm = corpus
    nz.normalize_all(raw, norm)
    write_raw(raw, "a/one.json", text="Changed")
    monkeypatch.setattr("sys.argv", ["normalize", "--raw-dir", str(raw), "--output-dir", str(norm)])
    with pytest.raises(SystemExit) as exc:
        nz.main()
    assert exc.value.code == 1
