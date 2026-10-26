"""Re-chunking at printed verse numbers (#122)."""

from __future__ import annotations

import pytest

from scripts.ingest._printed_verses import rechunk, split_verses
from scripts.ingest.didache import rechunk_chapters


def test_split_verses_takes_only_numbers_that_continue_the_run() -> None:
    lead, verses = split_verses("1. One, p. 379. 2. Two 7. not 3, three—4. four")
    assert lead == ""
    assert verses == [(1, "One, p. 379."), (2, "Two 7. not"), (3, "three—"), (4, "four")]


def test_split_verses_allows_a_gap_up_to_max_gap() -> None:
    assert split_verses("1. a 3. b", max_gap=1)[1] == [(1, "a 3. b")]
    assert split_verses("1. a 3. b", max_gap=2)[1] == [(1, "a"), (3, "b")]


def test_split_verses_keeps_unnumbered_text() -> None:
    assert split_verses("No numbers here.") == ("No numbers here.", [])
    assert split_verses("Lead in. 4. Four", last=3) == ("Lead in.", [(4, "Four")])


def test_rechunk_runs_on_across_paragraphs() -> None:
    paras = [
        {"ref": "A.1", "text": "Title"},
        {"ref": "A.1.2", "text": "1. one 3. three"},
        {"ref": "A.1.3", "text": "more of three 4. four"},
        {"ref": "A.2.1", "text": "1. Fragment one"},
    ]
    out = rechunk(paras, lambda r: "A.1" if r.startswith("A.1.") else None,
                  restart=False, max_gap=2)
    assert out == [
        {"ref": "A.1", "text": "Title"},
        {"ref": "A.1.1", "text": "one"},
        {"ref": "A.1.3", "text": "three more of three"},
        {"ref": "A.1.4", "text": "four"},
        {"ref": "A.2.1", "text": "1. Fragment one"},
    ]


def test_rechunk_refuses_unnumbered_text_it_cannot_place() -> None:
    with pytest.raises(ValueError, match="before the first printed verse"):
        rechunk([{"ref": "C.1", "text": "no number 1. one"}], lambda r: r, restart=True)


def test_didache_chapters_become_verses_and_the_elucidation_stays() -> None:
    paras = [
        {"ref": "Did.1", "text": "1. There are two ways. 2. The way of life."},
        {"ref": "Did.16", "text": "1. Watch. 2. Gather."},
        {"ref": "Did.17", "text": "(Thus baptize ye, p. 379.)"},
        {"ref": "Did.17.1", "text": "1. Not a verse."},
    ]
    assert [p["ref"] for p in rechunk_chapters(paras)] == [
        "Did.1.1", "Did.1.2", "Did.16.1", "Did.16.2", "Did.17", "Did.17.1",
    ]
