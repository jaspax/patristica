"""Tests for patristica.descriptions (#795)."""

from __future__ import annotations

from pathlib import Path

import pytest

from patristica import descriptions
from patristica.descriptions import Description, DescriptionError


def test_round_trip_sorted_and_idempotent(tmp_path: Path):
    path = tmp_path / "works.jsonl"
    descriptions.save(path, [Description("b/y", "Two."), Description("a/x", "One.", model="m")])
    assert [line[:12] for line in path.read_text().splitlines()] == ['{"id": "a/x"', '{"id": "b/y"']
    loaded = descriptions.load(path)
    assert loaded["a/x"] == Description("a/x", "One.", model="m")
    before = path.stat().st_mtime_ns
    descriptions.save(path, loaded.values())
    assert path.stat().st_mtime_ns == before


def test_rejects_bad_entries(tmp_path: Path):
    with pytest.raises(DescriptionError):
        descriptions.save(tmp_path / "x.jsonl", [Description("a", "  ")])
    with pytest.raises(DescriptionError):
        Description("a", "t", wikipedia="https://de.wikipedia.org/wiki/X").check()
    path = tmp_path / "dup.jsonl"
    path.write_text('{"id": "a", "text": "t"}\n{"id": "a", "text": "u"}\n')
    with pytest.raises(DescriptionError, match="duplicate"):
        descriptions.load(path)


def test_committed_files_are_valid():
    """The tracked descriptions load, and name only known authors and works."""
    import json

    from patristica.authors import author_index

    root = Path(__file__).resolve().parent.parent
    authors = descriptions.load_authors(root / descriptions.DEFAULT_DIR)
    works = descriptions.load_works(root / descriptions.DEFAULT_DIR)
    assert set(authors) <= set(author_index().authors)
    manifest = root / "data/normalized/_works.jsonl"
    ids = {json.loads(line)["work"]["work_id"] for line in manifest.open(encoding="utf-8")}
    assert set(works) <= ids
