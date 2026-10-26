"""Corpus-wide checks on ``Work.translation_of`` in the tracked manifest (#11, #153)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica import translation_links as tl
from patristica.versification import SOURCE_SCHEMES
from patristica.versions import curated_links

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


def _translation_of() -> dict[str, str | None]:
    return {wid: w.get("translation_of") for wid, w in _works().items()}


def test_some_works_are_linked() -> None:
    assert len(_links()) >= 900


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


def test_no_cycles() -> None:
    """Links may chain (Coptic → Greek → Hebrew), but never come back."""
    translation_of = _translation_of()
    for wid in translation_of:
        tl.translation_chain(wid, translation_of)  # raises on a cycle


def test_chains_are_short() -> None:
    """The longest history in the corpus is version → LXX → Hebrew."""
    translation_of = _translation_of()
    longest = max(len(tl.translation_chain(w, translation_of)) for w in translation_of)
    assert longest <= 3


def test_only_curated_links_chain() -> None:
    """An ingestor's link (the English translations of #150) goes straight to
    the original: only curated links may name a translation."""
    works = _works()
    chained = sorted(
        (wid, target) for wid, target in _links()
        if works[target].get("translation_of") and tl.curated_translation_of(wid) is None
    )
    assert not chained, f"an ingestor's translation_of points at a translation: {chained}"


def test_manifest_carries_the_curated_links() -> None:
    stale = sorted(
        (wid, w.get("translation_of"), tl.curated_translation_of(wid))
        for wid, w in _works().items()
        if tl.curated_translation_of(wid) is not None
        and w.get("translation_of") != tl.curated_translation_of(wid)
    )
    assert not stale, f"re-run scripts.normalize: {stale[:10]}"


# ---------------------------------------------------------------------------
# The Scripture table
# ---------------------------------------------------------------------------


def test_table_covers_exactly_the_scripture_sources() -> None:
    assert tl.scripture_sources() == frozenset(SOURCE_SCHEMES)


def test_every_scripture_work_has_a_rule() -> None:
    missing = sorted(w for w in _works() if w.split("/")[0] in SOURCE_SCHEMES
                     and tl.scripture_rule(w) is None)
    assert not missing, f"no rule in scripture_translation_of.csv for {missing}"


def test_every_rule_is_used() -> None:
    used = {(r.source_id, r.books) for w in _works() if (r := tl.scripture_rule(w))}
    unused = sorted(set(tl.load_scripture_rules()) - used)
    assert not unused, f"rules that match no work: {unused}"


def test_curated_links_never_name_a_scripture_work() -> None:
    """Scripture-source works get their link from the Scripture table only."""
    rows = [link for link in curated_links() if link.relation == "translation_of"
            and link.work_id.split("/")[0] in SOURCE_SCHEMES]
    assert not rows


@pytest.mark.parametrize(("work_id", "expected"), [
    ("oshb/gen", None),
    ("sblgnt/matt", None),
    ("pta-lxx/gen", "oshb/gen"),
    ("pta-lxx/matt", None),           # another edition of the Greek NT
    ("pta-lxx/wis", None),            # composed in Greek
    ("pta-lxx/danthdt", "oshb/dan"),
    ("pta-lxx/ezraneh", None),        # both books in one work
    ("lxx-rahlfs/ps", "oshb/ps"),
    ("clementine/gen", "oshb/gen"),
    ("clementine/ps", "pta-lxx/ps"),  # the Gallican Psalter
    ("clementine/sir", "pta-lxx/sir"),
    ("clementine/tob", None),         # from Aramaic, not in the corpus
    ("clementine/john", "sblgnt/john"),
    ("pta-peshitta/gen", "oshb/gen"),
    ("pta-peshitta/wis", "pta-lxx/wis"),
    ("pta-peshitta/3esr", "pta-lxx/1esr"),
    ("pta-peshitta/sir", None),       # from Hebrew, not in the corpus
    ("coptic-nt/gen", "pta-lxx/gen"),
    ("coptic-nt/dan", "pta-lxx/danthdt"),
    ("coptic-nt/rom", "sblgnt/rom"),
    ("armenian/1esd", "pta-lxx/1esr"),
    ("armenian/neh", None),
    ("gez/gen", "pta-lxx/gen"),
    ("gez/1en", "first1k/tlg1463/tlg001/1st1K-grc1"),
    ("gez/1meq", None),
    ("wulfila/mark", "sblgnt/mark"),
    ("kjv/gen", "oshb/gen"),
    ("web/rev", "sblgnt/rev"),
])
def test_scripture_rules(work_id: str, expected: str | None) -> None:
    assert _works()[work_id].get("translation_of") == expected


@pytest.mark.parametrize(("work_id", "root"), [
    ("coptic-nt/gen", "oshb/gen"),     # Coptic → LXX → Hebrew
    ("armenian/ps", "oshb/ps"),
    ("clementine/ps", "oshb/ps"),
    ("coptic-nt/sir", "pta-lxx/sir"),
    ("gez/1en", "first1k/tlg1463/tlg001/1st1K-grc1"),
    ("armenian/rom", "sblgnt/rom"),
])
def test_chains_end_at_the_original(work_id: str, root: str) -> None:
    assert tl.translation_chain(work_id, _translation_of())[-1] == root
