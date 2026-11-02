"""Curated genres (#103): the ``apocrypha`` genre and ``patristica/data/genre_overrides.csv``."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica import genres
from patristica.genres import (
    GENRES,
    OVERRIDES_PATH,
    GenreOverrideError,
    apply_genre_override,
    load_genre_overrides,
)
from scripts.normalize import normalize_all, normalize_file, write_works_manifest

WORKS_MANIFEST = Path(__file__).resolve().parents[1] / "data" / "normalized" / "_works.jsonl"


def _manifest() -> dict[str, dict]:
    works = {}
    for line in WORKS_MANIFEST.read_text(encoding="utf-8").splitlines():
        if line.strip():
            work = json.loads(line)["work"]
            works[work["work_id"]] = work
    return works


# ---------------------------------------------------------------------------
# The overrides file
# ---------------------------------------------------------------------------

def test_apocrypha_is_a_genre() -> None:
    assert "apocrypha" in GENRES


def test_hagiography_is_a_genre() -> None:
    assert "hagiography" in GENRES


def test_overrides_file_is_valid() -> None:
    overrides = load_genre_overrides()
    assert overrides
    assert set(overrides.values()) <= set(GENRES)


def test_every_override_names_a_known_work() -> None:
    unknown = set(load_genre_overrides()) - set(_manifest())
    assert not unknown, f"genre_overrides.csv lists work_ids not in _works.jsonl: {sorted(unknown)}"


def test_manifest_carries_the_curated_genres() -> None:
    """_works.jsonl was regenerated after the overrides file last changed."""
    works = _manifest()
    stale = {
        wid: (works[wid]["genre"], genre)
        for wid, genre in load_genre_overrides().items()
        if works[wid]["genre"] != genre
    }
    assert not stale, f"re-run scripts.normalize: {stale}"


@pytest.mark.parametrize(
    ("work_id", "genre"),
    [
        ("anf-works/protevangelium-of-james", "apocrypha"),
        ("ogpg/vol-002/clementina-homiliae", "apocrypha"),
        ("coptic-scriptorium/lament_mary", "liturgical"),
        ("anf-works/shepherd-of-hermas", "patristic"),
        ("gez/1en", "scripture"),
        # #558: post-apostolic saints are hagiography, apostles apocrypha.
        ("anf-works/martyrdom-of-polycarp", "hagiography"),
        ("npnf-works/athanasius-life-of-antony", "hagiography"),
        ("mt-eng/dsc/life-of-rabbula", "hagiography"),
        ("dsc/doctrina-addai", "apocrypha"),
        ("anf-works/acts-of-paul-and-thecla", "apocrypha"),
        ("npnf-works/chrysostom-homilies-on-ignatius-and-babylas", "patristic"),
    ],
)
def test_examples(work_id: str, genre: str) -> None:
    assert _manifest()[work_id]["genre"] == genre


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ("a/b,heretical,because\n", "unknown genre"),
        ("a/b,apocrypha,\n", "no reason"),
        ("a/b,apocrypha,x\na/b,patristic,y\n", "listed twice"),
        (",apocrypha,x\n", "empty work_id"),
    ],
)
def test_malformed_overrides_are_rejected(tmp_path: Path, rows: str, message: str) -> None:
    path = tmp_path / "overrides.csv"
    path.write_text("work_id,genre,reason\n" + rows, encoding="utf-8")
    with pytest.raises(GenreOverrideError, match=message):
        load_genre_overrides(path)


# ---------------------------------------------------------------------------
# Normalize
# ---------------------------------------------------------------------------

@pytest.fixture
def overrides(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    table: dict[str, str] = {}
    monkeypatch.setattr(genres, "_overrides", lambda: table)
    return table


def _work(work_id: str, genre: str, **extra) -> dict:
    return {
        "work_id": work_id, "source_id": work_id.split("/")[0], "title": "T",
        "genre": genre, "language": "grc", **extra,
    }


def _write_raw(raw: Path, rel: str, work: dict, key: str, units: list[tuple[str, str]]) -> Path:
    path = raw / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"work": work, key: [{"ref": r, "text": t} for r, t in units]}
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return path


def _chunks(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def test_apply_genre_override(overrides: dict[str, str]) -> None:
    overrides["src/a"] = "apocrypha"
    work = _work("src/a", "patristic")
    assert apply_genre_override(work)["genre"] == "apocrypha"
    assert work["genre"] == "patristic"  # not mutated
    other = _work("src/b", "patristic")
    assert apply_genre_override(other) is other


def test_normalize_handles_apocrypha(tmp_path: Path, overrides: dict[str, str]) -> None:
    raw, norm = tmp_path / "raw", tmp_path / "normalized"
    work = _work("src/acts", "apocrypha", date_composed=1200, date_range=[1150, 1250])
    units = [("Acts.1", "1. Text"), ("Acts.2", "More")]
    path = _write_raw(raw, "src/acts.json", work, "paragraphs", units)
    assert normalize_file(path, norm) == 2
    chunks = _chunks(norm / "src" / "acts.json")
    assert [c["text"] for c in chunks] == ["Text", "More"]  # prose: section number stripped
    assert all(c["out_of_period"] for c in chunks)  # dated like patristic prose


def test_normalize_handles_hagiography(tmp_path: Path, overrides: dict[str, str]) -> None:
    raw, norm = tmp_path / "raw", tmp_path / "normalized"
    overrides["src/vita"] = "hagiography"  # ingested as patristic, curated (#558)
    work = _work("src/vita", "patristic", date_composed=400, date_range=[380, 420])
    units = [("Vita.1", "1. Text"), ("Vita.2", "More")]
    path = _write_raw(raw, "src/vita.json", work, "paragraphs", units)
    assert normalize_file(path, norm) == 2
    chunks = _chunks(norm / "src" / "vita.json")
    assert [c["text"] for c in chunks] == ["Text", "More"]  # prose like patristic
    assert not any(c["out_of_period"] for c in chunks)
    write_works_manifest(norm)
    line = (norm / "_works.jsonl").read_text(encoding="utf-8").strip()
    assert json.loads(line)["work"]["genre"] == "hagiography"


def test_normalize_applies_override_across_unit_keys(
    tmp_path: Path, overrides: dict[str, str]
) -> None:
    """A curated genre may differ from the one the ingestor picked its key for."""
    raw, norm = tmp_path / "raw", tmp_path / "normalized"
    overrides["src/book"] = "apocrypha"  # ingested as scripture: "verses"
    overrides["src/clem"] = "scripture"  # ingested as patristic: "paragraphs"
    _write_raw(raw, "src/book.json", _work("src/book", "scripture"), "verses", [("Bk.1.1", "a")])
    clem = _work("src/clem", "patristic")
    _write_raw(raw, "src/clem.json", clem, "paragraphs", [("Clem.1.1", "b")])

    normalize_all(raw, norm)

    assert [c["text"] for c in _chunks(norm / "src" / "book.json")] == ["a"]
    assert [c["text"] for c in _chunks(norm / "src" / "clem.json")] == ["b"]
    manifest = {
        json.loads(line)["work"]["work_id"]: json.loads(line)["work"]["genre"]
        for line in (norm / "_works.jsonl").read_text(encoding="utf-8").splitlines()
    }
    assert manifest == {"src/book": "apocrypha", "src/clem": "scripture"}


def test_manifest_applies_override_without_raw_data(
    tmp_path: Path, overrides: dict[str, str]
) -> None:
    """On a checkout without data/raw, the previous manifest entry gets the curated genre."""
    norm = tmp_path / "normalized"
    (norm / "src").mkdir(parents=True)
    (norm / "src" / "a.json").write_text("[]", encoding="utf-8")
    entry = {"path": "src/a.json", "work": _work("src/a", "patristic")}
    (norm / "_works.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")
    overrides["src/a"] = "apocrypha"

    write_works_manifest(norm)

    line = (norm / "_works.jsonl").read_text(encoding="utf-8").strip()
    assert json.loads(line)["work"]["genre"] == "apocrypha"


def test_manifest_drops_empty_external_ids(tmp_path: Path) -> None:
    """Only works with catalogue ids carry ``external_ids`` in the manifest (#178)."""
    norm, raw = tmp_path / "normalized", tmp_path / "elsewhere" / "raw"
    for rel, ids in (("src/a.json", []), ("src/b.json", ["CPG:5200"])):
        (norm / "src").mkdir(parents=True, exist_ok=True)
        (norm / rel).write_text("[]", encoding="utf-8")
        (raw / "src").mkdir(parents=True, exist_ok=True)
        work = _work(f"src/{rel[4]}", "patristic", external_ids=ids)
        (raw / rel).write_text(json.dumps({"work": work}), encoding="utf-8")

    write_works_manifest(norm, raw)

    works = {json.loads(line)["path"]: json.loads(line)["work"]
             for line in (norm / "_works.jsonl").read_text(encoding="utf-8").splitlines()}
    assert "external_ids" not in works["src/a.json"]
    assert works["src/b.json"]["external_ids"] == ["CPG:5200"]


def test_overrides_path_is_packaged() -> None:
    assert OVERRIDES_PATH.is_file()
