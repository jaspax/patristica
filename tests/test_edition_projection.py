"""Derived verses of an edition projected from another edition's cuts (#200)."""

from __future__ import annotations

import random

from patristica import anchoring
from patristica import edition_projection as ep


def _words(n: int, seed: int = 0) -> list[str]:
    rng = random.Random(seed)
    return [f"w{rng.randrange(10_000)}" for _ in range(n)]


def _paras(texts_per_para: list[list[str]], prefix: str = "P") -> list[anchoring.Paragraph]:
    chunks = []
    for k, units in enumerate(texts_per_para):
        for s, u in enumerate(units, start=1):
            ref = f"{prefix}.{k}.s{s}" if len(units) > 1 else f"{prefix}.{k}"
            chunks.append({"canonical_ref": ref, "text": u})
    return anchoring.paragraphs(chunks)


def _cut(words: list[str], sizes: list[int]) -> list[str]:
    out, k = [], 0
    for s in sizes:
        out.append(" ".join(words[k:k + s]))
        k += s
    return out


def _units(paras: list[anchoring.Paragraph], proj: ep.Projection) -> list[str]:
    out: list[str] = []
    for p, st in zip(paras, proj.starts):
        out += list(p.units) if st is None else anchoring.cut_at(" ".join(p.units), st)
    return out


def test_cuts_follow_the_reference() -> None:
    ws = _words(60)
    ref = _paras([_cut(ws, [20, 25, 15])])
    ed = _paras([_cut(ws, [30, 30])])  # cut elsewhere
    proj = ep.project(ref, ed)
    assert proj.starts == [(0, 20, 45)]
    assert _units(ed, proj) == _cut(ws, [20, 25, 15])


def test_reference_paragraph_breaks_cut_the_edition() -> None:
    ws = _words(60)
    ref = _paras([_cut(ws[:30], [30]), _cut(ws[30:], [30])])
    ed = _paras([_cut(ws, [60])])
    assert ep.project(ref, ed).starts == [(0, 30)]


def test_damaged_start_word_is_skipped_over() -> None:
    ws = _words(40)
    damaged = list(ws)
    damaged[20] = "ocrjunk"
    ref = _paras([_cut(ws, [20, 20])])
    ed = _paras([_cut(damaged, [40])])
    assert ep.project(ref, ed).starts == [(0, 20)]


def test_edition_only_text_keeps_its_provisional_cut() -> None:
    ws = _words(40)
    notes = _words(40, seed=7)
    ref = _paras([_cut(ws, [20, 20])])
    ed = _paras([_cut(ws, [40]), _cut(notes, [20, 20])])  # an apparatus the reference lacks
    proj = ep.project(ref, ed)
    assert proj.starts == [(0, 20), None]
    assert proj.stats["provisional_paragraphs"] == 1


def test_unrelated_texts_project_nothing() -> None:
    ref = _paras([_cut(_words(50, seed=1), [25, 25])])
    ed = _paras([_cut(_words(50, seed=2), [50])])
    proj = ep.project(ref, ed)
    assert proj.starts == [None]
    assert proj.stats["starts_projected"] == 0


def test_method_hash_changes_with_the_parameters() -> None:
    assert ep.method_hash() == ep.method_hash(ep.Params())
    assert ep.method_hash() != ep.method_hash(ep.Params(min_cover=0.6))


def test_a_leading_section_number_is_not_left_alone() -> None:
    """Migne prints "2." before the text the critical edition starts its unit
    with: the number joins the unit instead of becoming a unit of its own."""
    ws = _words(40)
    ref = _paras([_cut(ws, [20, 20])])
    ed = _paras([_cut(["2.", *ws], [41])])
    assert ep.project(ref, ed).starts == [(0, 21)]
    ed_units = _units(ed, ep.project(ref, ed))
    assert ed_units[0].startswith("2. ")


def test_an_unmatched_start_word_is_placed_after_its_predecessor() -> None:
    """The reference's first word of a unit is spelled differently and the
    edition has a stray OCR token after it: the cut goes right after the
    previous word's counterpart, not onto the stray token."""
    ws = _words(40)
    ref_words = list(ws)
    ed_words = ws[:20] + ["Saepe", "I"] + ws[21:]
    ref_words[20] = "Saepe-x"
    ref = _paras([_cut(ref_words, [20, 20])])
    ed = _paras([_cut(ed_words, [41])])
    assert ep.project(ref, ed).starts == [(0, 20)]


def test_no_scraps_joins_short_pieces() -> None:
    assert ep._no_scraps(["2.", "alphabetically"], [1], 8) == (0,)
    assert ep._no_scraps(["alphabetically", "3."], [1], 8) == (0,)
    assert ep._no_scraps(["alphabetically", "longerwordhere"], [1], 8) == (0, 1)


def test_an_unmatched_start_after_the_last_match_projects_nothing() -> None:
    """The reference's last unit starts with a word the edition lacks, right
    after the edition's last matched word: there is nothing left to cut."""
    ws = _words(30)
    ref = _paras([_cut(ws + ["extraword"], [30, 1])])
    ed = _paras([_cut(ws, [30])])
    assert ep.project(ref, ed).starts == [(0,)]
