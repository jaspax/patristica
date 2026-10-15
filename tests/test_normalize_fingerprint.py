"""Staleness of normalized data (#130): fingerprints in scripts.normalize.

The first tests check the committed ``data/normalized`` against the code on
this branch; they are what makes CI fail when normalize's code or the genre
overrides change without a re-normalize.  The rest exercise the skip / raw
guard logic on a small corpus.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica import genres
from scripts import normalize as nz

NORMALIZED = Path(__file__).resolve().parents[1] / "data" / "normalized"
RERUN = "re-run `uv run python -m scripts.normalize` and commit data/normalized"


# ---------------------------------------------------------------------------
# The committed data
# ---------------------------------------------------------------------------


def test_committed_data_was_normalized_with_this_code() -> None:
    recorded = nz.read_step_fingerprints(NORMALIZED).get(nz.STEP, {}).get("code")
    assert recorded == nz.normalize_code_hash(), (
        f"normalize's code changed since data/normalized was produced: {RERUN}"
    )


def test_every_work_has_a_current_fingerprint() -> None:
    manifest = nz.read_works_manifest(NORMALIZED)
    missing = sorted(p for p, e in manifest.items() if "fingerprint" not in e)
    assert not missing, f"works without a fingerprint ({RERUN}): {missing[:10]}"
    stale = sorted(
        p for p, e in manifest.items()
        if e["fingerprint"]["override"]
        != nz.work_fingerprint(b"", e["work"]["work_id"])["override"]
    )
    assert not stale, f"genre_overrides.csv changed for these works ({RERUN}): {stale[:10]}"


def test_manifest_lists_exactly_the_normalized_files() -> None:
    files = {
        p.relative_to(NORMALIZED).as_posix() for p in NORMALIZED.rglob("*.json")
        if not p.name.startswith("_")
    }
    listed = set(nz.read_works_manifest(NORMALIZED))
    assert files - listed == set(), f"normalized files missing from _works.jsonl ({RERUN})"
    assert listed - files == set(), "_works.jsonl lists normalized files that don't exist"


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
    """Paths of the works normalized (rebuilt) in each run."""
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


ALL = ["a/one.json", "a/two.json", "b/three.json"]


def test_first_run_records_fingerprints(corpus, code, built) -> None:
    raw, norm = corpus
    nz.normalize_all(raw, norm)
    assert built == ALL
    assert nz.read_step_fingerprints(norm) == {"normalize": {"code": "code-1"}}
    manifest = nz.read_works_manifest(norm)
    assert sorted(manifest) == ALL
    assert all(set(e["fingerprint"]) == {"raw", "override"} for e in manifest.values())


def test_unchanged_inputs_are_skipped(corpus, code, built) -> None:
    raw, norm = corpus
    nz.normalize_all(raw, norm)
    built.clear()
    before = (norm / "_works.jsonl").read_text(encoding="utf-8")
    nz.normalize_all(raw, norm)
    assert built == []
    assert (norm / "_works.jsonl").read_text(encoding="utf-8") == before
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
    manifest_before = (norm / "_works.jsonl").read_text(encoding="utf-8")
    write_raw(raw, "a/two.json", text="Older text")

    with pytest.raises(nz.RawChangedError, match="a/two.json"):
        nz.normalize_all(raw, norm)
    assert built == []
    assert chunk_text(norm, "a/two.json") == "Text"
    assert (norm / "_works.jsonl").read_text(encoding="utf-8") == manifest_before

    with pytest.raises(nz.RawChangedError):  # --force doesn't bypass the guard
        nz.normalize_all(raw, norm, force=True)
    assert chunk_text(norm, "a/two.json") == "Text"

    built.clear()
    nz.normalize_all(raw, norm, accept_raw_change=True)
    assert built == ["a/two.json"]
    assert chunk_text(norm, "a/two.json") == "Older text"
    nz.normalize_all(raw, norm)  # now recorded: no refusal


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
    assert sorted(nz.read_works_manifest(norm)) == ALL + ["newsrc/alpha.json", "newsrc/beta.json"]
    assert nz.read_step_fingerprints(norm)["normalize"]["code"] == "code-1"


def test_missing_raw_keeps_entries_and_blocks_new_code_hash(corpus, code, built) -> None:
    raw, norm = corpus
    nz.normalize_all(raw, norm)
    before = nz.read_works_manifest(norm)
    for path in (raw / "b").iterdir():  # another machine: no raw for source b
        path.unlink()
    (raw / "b").rmdir()

    nz.normalize_all(raw, norm)
    assert nz.read_works_manifest(norm) == before

    code[0] = "code-2"
    built.clear()
    nz.normalize_all(raw, norm)
    assert built == ["a/one.json", "a/two.json"]
    assert nz.read_works_manifest(norm)["b/three.json"] == before["b/three.json"]
    assert nz.read_step_fingerprints(norm)["normalize"]["code"] == "code-1"


def test_override_change_rebuilds_only_that_work(corpus, code, built, overrides) -> None:
    raw, norm = corpus
    nz.normalize_all(raw, norm)
    built.clear()
    overrides["a/two"] = "apocrypha"
    nz.normalize_all(raw, norm)
    assert built == ["a/two.json"]
    assert nz.read_works_manifest(norm)["a/two.json"]["work"]["genre"] == "apocrypha"


def test_main_exits_nonzero_on_refusal(corpus, code, monkeypatch) -> None:
    raw, norm = corpus
    nz.normalize_all(raw, norm)
    write_raw(raw, "a/one.json", text="Changed")
    monkeypatch.setattr("sys.argv", ["normalize", "--raw-dir", str(raw), "--output-dir", str(norm)])
    with pytest.raises(SystemExit) as exc:
        nz.main()
    assert exc.value.code == 1
