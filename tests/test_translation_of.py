"""Corpus-wide checks on ``Work.translation_of`` in the tracked manifest (#11)."""

from __future__ import annotations

import json
from pathlib import Path

WORKS_MANIFEST = Path(__file__).resolve().parents[1] / "data" / "normalized" / "_works.jsonl"


def _works() -> dict[str, dict]:
    works: dict[str, dict] = {}
    for line in WORKS_MANIFEST.read_text(encoding="utf-8").splitlines():
        work = json.loads(line)["work"]
        works[work["work_id"]] = work
    return works


def _links() -> list[tuple[str, str]]:
    return [
        (wid, w["translation_of"]) for wid, w in _works().items() if w.get("translation_of")
    ]


def test_some_works_are_linked() -> None:
    assert len(_links()) >= 300


def test_every_target_exists() -> None:
    works = _works()
    dangling = sorted((wid, target) for wid, target in _links() if target not in works)
    assert not dangling, f"translation_of names works not in _works.jsonl: {dangling}"


def test_no_self_links() -> None:
    assert not [wid for wid, target in _links() if wid == target]


def test_target_is_not_english() -> None:
    works = _works()
    english = sorted(
        (wid, target) for wid, target in _links()
        if target in works and works[target]["language"] == "eng"
    )
    assert not english, f"translation_of points at an English work: {english}"


def test_target_is_not_itself_a_translation() -> None:
    """Links go straight to the original, so version groups are stars, not chains."""
    works = _works()
    chained = sorted(
        (wid, target) for wid, target in _links()
        if target in works and works[target].get("translation_of")
    )
    assert not chained, f"translation_of points at another translation: {chained}"
