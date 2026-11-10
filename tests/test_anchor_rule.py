"""Which works are anchored, and on what (#638, ``patristica.anchor_rule``)."""

from __future__ import annotations

from patristica.anchor_rule import anchors, preferred_edition

TLG = ["TLG:tlg2040.tlg004"]


def work(wid: str, language: str, translation_of: str | None = None,
         external_ids: list[str] | None = None) -> dict:
    rec = {"work_id": wid, "source_id": wid.split("/")[0], "language": language}
    if translation_of:
        rec["translation_of"] = translation_of
    if external_ids:
        rec["external_ids"] = external_ids
    return rec


def corpus(*recs: dict) -> dict[str, dict]:
    return {r["work_id"]: r for r in recs}


def test_a_translation_is_anchored_on_its_translation_of() -> None:
    works = corpus(work("perseus/basil", "grc", external_ids=TLG),
                   work("npnf-works/basil", "eng", "perseus/basil"))
    assert anchors(works, {}) == {"npnf-works/basil": "perseus/basil"}


def test_a_translation_of_migne_moves_to_the_critical_text() -> None:
    works = corpus(work("ogpg/basil", "grc", external_ids=TLG),
                   work("perseus/basil", "grc", external_ids=TLG),
                   work("npnf-works/basil", "eng", "ogpg/basil"))
    got = anchors(works, {})
    assert got["npnf-works/basil"] == "perseus/basil"
    assert got["ogpg/basil"] == "perseus/basil"  # the OCR'd edition follows the critical one
    assert "perseus/basil" not in got


def test_a_translation_of_migne_without_a_critical_text_stays_on_migne() -> None:
    works = corpus(work("ogpg/x", "grc"), work("npnf-works/x", "eng", "ogpg/x"))
    assert anchors(works, {}) == {"npnf-works/x": "ogpg/x"}


def test_a_decision_on_record_is_kept() -> None:
    """A translation cut on Migne before #638 keeps that anchor (another edition
    of the same text), and an edition anchored on a member of its group makes
    that member the preferred edition, whatever the tie-break says."""
    works = corpus(work("ogpg/basil", "grc", external_ids=TLG),
                   work("perseus/basil", "grc", external_ids=TLG),
                   work("first1k/basil", "grc", external_ids=TLG),
                   work("npnf-works/basil", "eng", "ogpg/basil"))
    recorded = {"npnf-works/basil": "ogpg/basil", "perseus/basil": "first1k/basil"}
    got = anchors(works, recorded)
    assert got["npnf-works/basil"] == "ogpg/basil"
    assert got["perseus/basil"] == "first1k/basil"
    assert got["ogpg/basil"] == "first1k/basil"
    assert "first1k/basil" not in got


def test_preferred_edition_tie_break() -> None:
    works = corpus(work("ogpg/a", "grc"), work("pta/a", "grc"), work("first1k/a", "grc"))
    eds = list(works)
    assert preferred_edition(eds, works, {}, {}) == "pta/a"  # critical, then the work id
    assert preferred_edition(eds, works, {}, {"first1k/a": 2}) == "first1k/a"  # most links
    assert preferred_edition(["ogpg/a", "ogpg/b"], {**works, "ogpg/b": work("ogpg/b", "grc")},
                             {}, {}) == "ogpg/b"  # both OCR'd: the work id


def test_works_that_are_not_anchored() -> None:
    works = corpus(work("perseus/a", "grc"),
                   work("eng/a", "eng", "perseus/a"),
                   work("eng/b", "eng", "eng/a"),  # translation_of in its own language
                   work("eng/c", "eng", "missing/x"),  # anchor not in the corpus
                   work("csel/lonely", "lat"))  # one edition
    assert anchors(works, {}) == {"eng/a": "perseus/a"}
