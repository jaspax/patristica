"""Tests for the source-first data layout (#102) and scripts.migrate_layout."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

from patristica.sources import SOURCE_LABELS
from scripts import migrate_layout as ml
from scripts.ingest.all import _source_id_to_module, discover_ingestors

REPO = Path(__file__).resolve().parents[1]
WORKS_MANIFEST = REPO / "data" / "normalized" / "_works.jsonl"


# ---------------------------------------------------------------------------
# The layout itself
# ---------------------------------------------------------------------------


def _manifest() -> list[dict]:
    return [json.loads(line) for line in WORKS_MANIFEST.read_text(encoding="utf-8").splitlines()]


def test_work_ids_and_paths_start_with_source_id() -> None:
    for rec in _manifest():
        work, source = rec["work"], rec["work"]["source_id"]
        assert "/" not in source, source
        assert work["work_id"].startswith(f"{source}/"), work["work_id"]
        assert rec["path"].startswith(f"{source}/"), rec["path"]


def test_translation_of_uses_current_work_ids() -> None:
    for rec in _manifest():
        target = rec["work"].get("translation_of")
        if target:
            assert ml.new_work_id(target) == target, target


def test_no_source_id_shadows_a_legacy_prefix() -> None:
    # Old reader URLs /works/{genre}/… redirect by prefix (web/src/lib/redirects.ts).
    legacy = {*ml.GENRE_PREFIXES, "oglt_pl"}
    assert not legacy & set(SOURCE_LABELS)


@pytest.mark.parametrize("module", discover_ingestors())
def test_ingestor_source_id_is_a_bare_slug(module: str) -> None:
    source_id = importlib.import_module(module).SOURCE_ID
    assert "/" not in source_id
    assert _source_id_to_module(source_id) == module
    assert source_id in ml.SOURCE_IDS.values() or source_id in ml.NEW_SOURCES


def test_mapping_covers_every_labelled_source() -> None:
    assert set(SOURCE_LABELS) <= set(ml.SOURCE_IDS.values()) | ml.NEW_SOURCES
    assert not ml.NEW_SOURCES & set(ml.SOURCE_IDS.values())


# ---------------------------------------------------------------------------
# Id mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "old,new",
    [
        ("scripture/kjv/gen", "kjv/gen"),
        ("liturgical/cursus/Bat", "cursus/Bat"),
        ("liturgical/coptic-scriptorium/AP", "coptic-scriptorium/AP"),
        ("patristic/coptic-scriptorium/AP", "coptic-scriptorium/AP"),
        ("councils/nicaea1", "ecumenical/nicaea1"),
        ("oglt_pl/augustinus/pl32_5_s", "oglt-pl/augustinus/pl32_5_s"),
        ("first1k/tlg2042/tlg001/1st1K-grc1", "first1k/tlg2042/tlg001/1st1K-grc1"),
        ("ogpg/vol-045/ad-graecos", "ogpg/vol-045/ad-graecos"),
        ("anf-works/ignatius-to-the-ephesians", "anf-works/ignatius-to-the-ephesians"),
    ],
)
def test_new_work_id(old: str, new: str) -> None:
    assert ml.new_work_id(old) == new
    assert ml.new_work_id(new) == new  # idempotent


def test_new_chunk_id_keeps_the_ref() -> None:
    assert ml.new_chunk_id("scripture/kjv/gen#Gen.1.1") == "kjv/gen#Gen.1.1"
    assert ml.new_chunk_id("councils/nicaea1#Nicaea1.Canon.7") == "ecumenical/nicaea1#Nicaea1.Canon.7"


@pytest.mark.parametrize(
    "old,new",
    [
        ("scripture/kjv/Gen.json", "kjv/Gen.json"),
        ("patristic/oglt_pl/data/x.json", "oglt-pl/data/x.json"),
        ("councils/ecumenical/nicaea1.json", "ecumenical/nicaea1.json"),
        ("kjv/Gen.json", "kjv/Gen.json"),
    ],
)
def test_new_path(old: str, new: str) -> None:
    assert ml.new_path(old) == new


def test_new_source_id() -> None:
    assert ml.new_source_id("patristic/oglt-pl") == "oglt-pl"
    assert ml.new_source_id("councils/ecumenical") == "ecumenical"
    assert ml.new_source_id("kjv") == "kjv"


def test_migrate_query() -> None:
    row = {"query_id": "paraphrase:scripture/kjv/gen#Gen.1.1", "origin": "scripture",
           "target_chunk_id": "scripture/kjv/gen#Gen.1.1"}
    assert ml.migrate_query(row) == {"query_id": "paraphrase:kjv/gen#Gen.1.1", "origin": "scripture",
                                     "target_chunk_id": "kjv/gen#Gen.1.1"}


# ---------------------------------------------------------------------------
# raw: a scratch tree in the old layout
# ---------------------------------------------------------------------------


def _raw_work(work_id: str, source_id: str, translation_of: str | None = None) -> str:
    work = {"work_id": work_id, "source_id": source_id, "title": "T", "genre": "scripture",
            "language": "eng", "translation_of": translation_of}
    # Ingestors write with indent=2; keep a non-ASCII text to check it is untouched.
    return json.dumps({"work": work, "verses": [{"ref": "Gen.1.1", "text": "Ἐν ἀρχῇ"}]},
                      ensure_ascii=False, indent=2)


@pytest.fixture()
def old_raw(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    files = {
        "scripture/kjv/Gen.json": _raw_work("scripture/kjv/gen", "scripture/kjv"),
        "patristic/oglt_pl/data/a/x.json": _raw_work("oglt_pl/a/x", "patristic/oglt-pl"),
        "patristic/npnf-works/npnf101/conf.json": _raw_work(
            "npnf-works/conf", "patristic/npnf-works", translation_of="oglt_pl/augustinus/c"),
        "councils/ecumenical/nicaea1.json": _raw_work("councils/nicaea1", "councils/ecumenical"),
        "liturgical/coptic-scriptorium/AP.json": _raw_work(
            "liturgical/coptic-scriptorium/AP", "liturgical/coptic-scriptorium"),
        "patristic/ogpg/_volumes.json": "{}",
        "patristic/ccel-anf/anf01.xml": "<x/>",
    }
    for rel, text in files.items():
        (raw / rel).parent.mkdir(parents=True, exist_ok=True)
        (raw / rel).write_text(text, encoding="utf-8")
    (raw / "_zips").mkdir()
    (raw / "_zips" / "kjv.zip").write_bytes(b"zip")
    return raw


def _snapshot(root: Path) -> dict[str, bytes]:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_raw_dry_run_changes_nothing(old_raw: Path) -> None:
    before = _snapshot(old_raw)
    moved, rewritten = ml.migrate_raw(old_raw, dry_run=True)
    assert (moved, rewritten) == (7, 5)
    assert _snapshot(old_raw) == before


def test_raw_migration(old_raw: Path) -> None:
    ml.migrate_raw(old_raw)
    assert sorted(p.name for p in old_raw.iterdir()) == [
        "_zips", "ccel-anf", "coptic-scriptorium", "ecumenical", "kjv", "npnf-works", "oglt-pl",
        "ogpg",
    ]
    kjv = json.loads((old_raw / "kjv/Gen.json").read_text(encoding="utf-8"))
    assert (kjv["work"]["work_id"], kjv["work"]["source_id"]) == ("kjv/gen", "kjv")
    assert kjv["verses"] == [{"ref": "Gen.1.1", "text": "Ἐν ἀρχῇ"}]
    pl = json.loads((old_raw / "oglt-pl/data/a/x.json").read_text(encoding="utf-8"))
    assert (pl["work"]["work_id"], pl["work"]["source_id"]) == ("oglt-pl/a/x", "oglt-pl")
    conf = json.loads((old_raw / "npnf-works/npnf101/conf.json").read_text(encoding="utf-8"))
    assert conf["work"]["translation_of"] == "oglt-pl/augustinus/c"
    council = json.loads((old_raw / "ecumenical/nicaea1.json").read_text(encoding="utf-8"))
    assert council["work"]["work_id"] == "ecumenical/nicaea1"
    cop = json.loads((old_raw / "coptic-scriptorium/AP.json").read_text(encoding="utf-8"))
    assert cop["work"]["work_id"] == "coptic-scriptorium/AP"
    assert (old_raw / "ogpg/_volumes.json").read_text() == "{}"
    assert (old_raw / "_zips/kjv.zip").read_bytes() == b"zip"

    # Only the id values changed: the formatting is the ingestor's.
    expected = _raw_work("kjv/gen", "kjv")
    assert (old_raw / "kjv/Gen.json").read_text(encoding="utf-8") == expected


def test_raw_migration_is_idempotent(old_raw: Path) -> None:
    ml.migrate_raw(old_raw)
    after = _snapshot(old_raw)
    assert ml.migrate_raw(old_raw) == (0, 0)
    assert _snapshot(old_raw) == after


def test_raw_conflict_leaves_old_dir(old_raw: Path, caplog: pytest.LogCaptureFixture) -> None:
    (old_raw / "kjv").mkdir()
    ml.migrate_raw(old_raw)
    assert (old_raw / "scripture/kjv/Gen.json").exists()
    assert "Both" in caplog.text


# ---------------------------------------------------------------------------
# tracked: a scratch data/ dir
# ---------------------------------------------------------------------------


def _chunk(work_id: str, ref: str) -> dict:
    return {"chunk_id": f"{work_id}#{ref}", "work_id": work_id, "canonical_ref": ref,
            "language": "eng", "text": "t"}


def test_tracked_migration(tmp_path: Path) -> None:
    data = tmp_path / "data"
    norm = data / "normalized"
    for rel, wid in (("scripture/kjv/Gen.json", "scripture/kjv/gen"),
                     ("patristic/first1k/a.json", "first1k/a")):
        (norm / rel).parent.mkdir(parents=True, exist_ok=True)
        (norm / rel).write_text(json.dumps([_chunk(wid, "A.1")], ensure_ascii=False, indent=2))
    manifest = [
        {"path": "scripture/kjv/Gen.json",
         "work": {"work_id": "scripture/kjv/gen", "source_id": "scripture/kjv",
                  "translation_of": None}},
        {"path": "patristic/first1k/a.json",
         "work": {"work_id": "first1k/a", "source_id": "patristic/first1k",
                  "translation_of": "oglt_pl/x"}},
    ]
    (norm / "_works.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in manifest))
    (data / "eval_authored").mkdir()
    (data / "eval_authored" / "q.jsonl").write_text(json.dumps(
        {"query_id": "exact:scripture/kjv/gen#A.1", "target_chunk_id": "scripture/kjv/gen#A.1"},
        ensure_ascii=False) + "\n")

    counts = ml.migrate_tracked(data, use_git=False)
    assert counts == {"dirs": 2, "normalized": 1, "manifest": 1, "eval_authored": 1,
                      "translations": 0}
    assert sorted(p.name for p in norm.iterdir()) == ["_works.jsonl", "first1k", "kjv"]
    chunks = json.loads((norm / "kjv/Gen.json").read_text())
    assert chunks[0]["chunk_id"] == "kjv/gen#A.1"
    rows = [json.loads(line) for line in (norm / "_works.jsonl").read_text().splitlines()]
    assert [r["path"] for r in rows] == ["first1k/a.json", "kjv/Gen.json"]  # re-sorted
    assert rows[0]["work"]["translation_of"] == "oglt-pl/x"
    assert rows[1]["work"]["source_id"] == "kjv"
    q = json.loads((data / "eval_authored/q.jsonl").read_text())
    assert q["query_id"] == "exact:kjv/gen#A.1"

    assert ml.migrate_tracked(data, use_git=False) == dict.fromkeys(counts, 0)


def test_tracked_refuses_unexpected_formatting(tmp_path: Path) -> None:
    norm = tmp_path / "data" / "normalized" / "kjv"
    norm.mkdir(parents=True)
    (norm / "Gen.json").write_text(json.dumps([_chunk("scripture/kjv/gen", "A.1")]))  # no indent
    with pytest.raises(ml.MigrationError):
        ml.migrate_tracked(tmp_path / "data", use_git=False)


# ---------------------------------------------------------------------------
# eval: local data/eval scratch
# ---------------------------------------------------------------------------


def test_eval_migration(tmp_path: Path) -> None:
    rows = [
        {"chunk_id": "scripture/kjv/gen#Gen.1.1", "work_id": "scripture/kjv/gen",
         "text": 'He said "scripture/kjv" twice: \\"scripture/x\\"', "origin": "scripture"},
        {"query_id": "exact:councils/nicaea1#N.1", "relevant_ids": ["oglt_pl/a/b#1", "pta/x#1"]},
    ]
    path = tmp_path / "review" / "q.jsonl"
    path.parent.mkdir()
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    assert ml.migrate_eval(tmp_path, dry_run=True) == 1
    assert ml.migrate_eval(tmp_path) == 1
    new = [json.loads(line) for line in path.read_text().splitlines()]
    assert new[0] == {**rows[0], "chunk_id": "kjv/gen#Gen.1.1", "work_id": "kjv/gen"}
    assert new[1] == {"query_id": "exact:ecumenical/nicaea1#N.1",
                      "relevant_ids": ["oglt-pl/a/b#1", "pta/x#1"]}
    assert ml.migrate_eval(tmp_path) == 0
