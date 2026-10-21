"""Tests for the passage aligner (#179): patristica.alignment and its store."""

from __future__ import annotations

import json

import pytest

np = pytest.importorskip("numpy")

from patristica import alignment as al  # noqa: E402
from patristica import alignment_store as store  # noqa: E402

DIMS = 64


def passages(n: int, seed: int = 0) -> np.ndarray:
    """*n* random unit vectors: the 'meaning' of n passages."""
    rng = np.random.default_rng(seed)
    v = rng.normal(size=(n, DIMS)).astype(np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def render(meanings: list[np.ndarray], noise: float, seed: int) -> np.ndarray:
    """Unit vectors for units with the given meanings, plus noise."""
    rng = np.random.default_rng(seed)
    v = np.stack(meanings) + noise / np.sqrt(DIMS) * rng.normal(
        size=(len(meanings), DIMS)).astype(np.float32)
    return (v / np.linalg.norm(v, axis=1, keepdims=True)).astype(np.float32)


def halves(p: np.ndarray, seed: int) -> list[np.ndarray]:
    """Two units that together render passage *p*."""
    rng = np.random.default_rng(seed)
    r = rng.normal(size=DIMS).astype(np.float32)
    r -= (r @ p) * p
    r /= np.linalg.norm(r)
    return [p + 0.6 * r, p - 0.6 * r]


def pairs_of(beads: list[al.Bead]) -> set[tuple[int, int]]:
    return {(i, j) for b in beads for i in range(b.i0, b.i1) for j in range(b.j0, b.j1)}


def test_one_to_one_recovers_identity() -> None:
    p = passages(40)
    a = al.Version("a", render(list(p), 0.3, 1))
    b = al.Version("b", render(list(p), 0.3, 2))
    beads = al.align_pair(a, b)
    assert [(x.i0, x.i1, x.j0, x.j1) for x in beads] == [(i, i + 1, i, i + 1) for i in range(40)]
    assert all(x.conf > 0.9 for x in beads)


def test_splits_merges_and_gaps() -> None:
    p = passages(30)
    # B splits passage 5 in two, drops passage 12 and adds a passage of its own after 20.
    a_units = list(p)
    b_units: list[np.ndarray] = []
    expect: set[tuple[int, int]] = set()
    for k, v in enumerate(p):
        if k == 12:
            continue
        if k == 5:
            for h in halves(v, 3):
                expect.add((k, len(b_units)))
                b_units.append(h)
            continue
        expect.add((k, len(b_units)))
        b_units.append(v)
        if k == 20:
            b_units.append(passages(1, seed=99)[0])
    beads = al.align_pair(al.Version("a", render(a_units, 0.2, 1)),
                          al.Version("b", render(b_units, 0.2, 2)))
    assert pairs_of(beads) == expect
    assert any((x.i1 - x.i0, x.j1 - x.j0) == (1, 2) for x in beads)


def test_partial_version_aligns_with_the_middle() -> None:
    p = passages(200)
    short = al.Version("short", render(list(p[120:140]), 0.2, 1))
    long = al.Version("long", render(list(p), 0.2, 2))
    beads = al.align_pair(short, long, al.Params(full_cells=1000))  # force the anchor band
    assert pairs_of(beads) == {(i, 120 + i) for i in range(20)}


def test_moved_block_is_found_by_a_later_pass() -> None:
    p = passages(60)
    order = list(range(0, 20)) + list(range(40, 50)) + list(range(20, 40)) + list(range(50, 60))
    a = al.Version("a", render(list(p), 0.2, 1))
    b = al.Version("b", render([p[k] for k in order], 0.2, 2))
    one = al.align_pair(a, b, al.Params(passes=1))
    three = al.align_pair(a, b)
    expect = {(k, order.index(k)) for k in range(60)}
    assert pairs_of(one) < expect
    assert pairs_of(three) == expect


def test_prior_decides_where_content_cannot() -> None:
    p = passages(10)
    same = p[3]
    units = [same if k in (3, 4) else v for k, v in enumerate(p)]  # 3 and 4 look alike
    keys = np.arange(10, dtype=np.int64)
    a = al.Version("a", render(units, 0.0, 1), keys)
    b = al.Version("b", render(units, 0.0, 2), keys)
    beads = al.align_pair(a, b, al.Params(prior=0.1))
    assert {(3, 3), (4, 4)} <= pairs_of(beads)


def test_content_overrules_a_wrong_prior() -> None:
    p = passages(30)
    a = al.Version("a", render(list(p), 0.2, 1), np.arange(30, dtype=np.int64))
    # B's refs are shifted by one from 10 on: its unit k has key k + 1.
    keys = np.array([k if k < 10 else k + 1 for k in range(30)], dtype=np.int64)
    b = al.Version("b", render(list(p), 0.2, 2), keys)
    beads = al.align_pair(a, b, al.Params(prior=0.1))
    assert pairs_of(beads) == {(k, k) for k in range(30)}


def test_units_without_vectors_are_left_out() -> None:
    p = passages(10)
    va = render(list(p), 0.2, 1)
    va[4] = 0
    beads = al.align_pair(al.Version("a", va), al.Version("b", render(list(p), 0.2, 2)))
    assert all(i != 4 for i, _ in pairs_of(beads))
    assert {(k, k) for k in range(10) if k != 4} <= pairs_of(beads)


def test_band_covers_the_path_and_is_monotonic() -> None:
    lo, hi = al.band_from_anchors(100, 80, [(10, 8), (50, 40), (90, 70)], 5)
    assert lo[0] == 0 and hi[-1] == 80
    assert (np.diff(lo) >= 0).all() and (np.diff(hi) >= 0).all()
    assert (lo[1:] <= hi[:-1]).all()  # every row reaches the next
    for p, q in [(10, 8), (50, 40), (90, 70)]:
        assert lo[p + 1] <= q + 1 <= hi[p + 1]


def test_anchor_chain_is_the_longest_increasing_chain() -> None:
    pairs = [(0, 0), (1, 5), (2, 1), (3, 2), (4, 3), (5, 4), (6, 0)]
    assert al.anchor_chain(pairs) == [(0, 0), (2, 1), (3, 2), (4, 3), (5, 4)]
    assert al.anchor_chain([]) == []


def test_merge_joins_pivot_units_covered_by_one_bead() -> None:
    b = al.Bead
    pairs = {
        "x": (4, [b(0, 1, 0, 1, 1, 1, 0.9), b(1, 2, 1, 3, 1, 1, 0.8), b(3, 4, 3, 4, 1, 1, 0.3)]),
        "y": (3, [b(0, 1, 0, 1, 1, 1, 0.9), b(1, 2, 1, 2, 1, 1, 0.9), b(2, 3, 2, 3, 1, 1, 0.9)]),
    }
    m = al.merge("p", 5, pairs)
    assert m.n_groups == 3
    assert list(m.group_of["p"]) == [0, 1, 1, 2, -1]
    assert list(m.group_of["x"]) == [0, 1, -1, 2]
    assert list(m.group_of["y"]) == [0, 1, 1]  # y's units 1 and 2 share pivot group 1
    assert m.conf["x"] == {0: 0.9, 1: 0.8, 2: 0.3}
    assert m.conf["p"] == {0: 0.9, 1: 0.9, 2: 0.3}


def test_merge_does_not_fill_gaps_between_beads() -> None:
    """Units no bead assigns stay out of the group; a non-contiguous span is left out."""
    b = al.Bead
    pairs = {
        # y joins pivot units 0-1 into one group.
        "y": (1, [b(0, 1, 0, 2, 1, 1, 0.9)]),
        # x maps its units 0 and 2 onto pivot units 0 and 1; unit 1 matches nothing.
        "x": (3, [b(0, 1, 0, 1, 1, 1, 0.9), b(2, 3, 1, 2, 1, 1, 0.9)]),
    }
    m = al.merge("p", 2, pairs)
    assert m.n_groups == 1
    assert list(m.group_of["x"]) == [-1, -1, -1]  # not the bounding span [0, 3)
    assert 0 not in m.conf["x"]
    assert list(m.group_of["y"]) == [0]


def test_merge_keeps_an_inner_group_inside_a_reordered_span() -> None:
    """A reordered bead must not swallow the group whose units lie between its beads."""
    b = al.Bead
    pairs = {
        "y": (2, [b(0, 1, 0, 2, 1, 1, 0.9), b(1, 2, 2, 3, 1, 1, 0.9)]),
        # x: units 0 and 2 render pivot 0-1 (group 0); unit 1 renders pivot 2 (group 1).
        "x": (3, [b(0, 1, 0, 1, 1, 1, 0.9), b(1, 2, 2, 3, 1, 1, 0.9),
                  b(2, 3, 1, 2, 1, 1, 0.9)]),
    }
    m = al.merge("p", 3, pairs)
    assert list(m.group_of["p"]) == [0, 0, 1]
    assert list(m.group_of["x"]) == [-1, 1, -1]
    assert m.conf["x"] == {1: 0.9}


def test_choose_pivot_prefers_the_longest_then_english() -> None:
    assert al.choose_pivot({"a": ("lat", 1000), "b": ("eng", 500)}) == "a"
    assert al.choose_pivot({"a": ("lat", 1000), "b": ("eng", 950), "c": ("eng", 960)}) == "c"
    assert al.choose_pivot({"z": ("syc", 10), "y": ("syc", 10)}) == "y"


# ------------------------------------------------------------------------ store


@pytest.mark.parametrize("group_of", [
    [], [-1, -1], [0, 1, 2, 3], [0, 0, 1, -1, 3, 3, 4], [2, 3, 0, 1, -1, 5], [7]])
def test_spans_round_trip(group_of: list[int]) -> None:
    assert store.decode_spans(store.encode_spans(group_of)) == group_of


def test_spans_are_one_byte_per_verse() -> None:
    assert store.encode_spans(list(range(5))) == "+++++"
    assert store.encode_spans([0, 0, -1, 3, 1]) == "+=.+3-2"


@pytest.mark.parametrize("bad", ["x", "=", "-1", "+2-5"])
def test_bad_spans_raise(bad: str) -> None:
    with pytest.raises(store.AlignmentFormatError):
        store.decode_spans(bad)


def sample_alignment() -> store.Alignment:
    a = store.Alignment("book:gen", "kjv/gen", 3, "abc", {"aligner": 1, "date": "2026-10-19"})
    a.members["kjv/gen"] = store.Member("kjv/gen", 3, "k", [0, 1, 2], {0: 9, 1: 9, 2: 4})
    a.members["oshb/gen"] = store.Member("oshb/gen", 3, "o", [0, 1, 2], {0: 9, 1: 9, 2: 4})
    a.members["gez/gen"] = store.Member("gez/gen", 2, "g", [-1, 1], {1: 6})
    return a


def test_store_round_trip_and_determinism(tmp_path) -> None:
    a = sample_alignment()
    assert store.save(tmp_path, a)
    assert not store.save(tmp_path, a)  # unchanged
    path = tmp_path / "book" / "gen.json"
    text = path.read_text()
    assert text == store.to_json(store.from_json(text))
    back = store.load(tmp_path, "book:gen")
    assert back is not None and back.members["gez/gen"].group_of == [-1, 1]
    raw = json.loads(text)
    assert [m["work_id"] for m in raw["members"]] == ["gez/gen", "kjv/gen", "oshb/gen"]
    assert raw["members"][0]["conf"] == "6"


def test_groups_of_drops_flagged_spans() -> None:
    a = sample_alignment()
    assert a.groups_of() == {
        0: {"kjv/gen": (0, 1), "oshb/gen": (0, 1)},
        1: {"gez/gen": (1, 2), "kjv/gen": (1, 2), "oshb/gen": (1, 2)},
    }
    assert 2 in a.groups_of(min_confidence=0)


def test_path_for() -> None:
    assert (store.path_for(store.DEFAULT_DIR, "book:gen").as_posix()
            == "data/alignments/book/gen.json")
    assert (store.path_for(store.DEFAULT_DIR, "oglt-pl/augustinus/pl38_0_s.").as_posix()
            == "data/alignments/oglt-pl/augustinus/pl38_0_s..json")
    with pytest.raises(ValueError):
        store.path_for(store.DEFAULT_DIR, "../x")


def test_tracked_alignments_match_the_corpus() -> None:
    """Every tracked alignment parses, and its members' units are the works' current chunks."""
    from pathlib import Path

    from patristica.versions import derive_version_groups

    norm = Path("data/normalized")
    entries = {e["work"]["work_id"]: e for e in
               (json.loads(line) for line in (norm / "_works.jsonl").open(encoding="utf-8"))}
    groups = derive_version_groups(
        {w: e["work"].get("translation_of") for w, e in entries.items()},
        external_ids={w: e["work"].get("external_ids", []) for w, e in entries.items()})
    for path, a in store.iter_store(store.DEFAULT_DIR):
        assert path == store.path_for(store.DEFAULT_DIR, a.group)
        assert a.group in groups.members, f"{path}: {a.group} is no longer a version group"
        assert a.pivot in a.members
        for wid, mem in a.members.items():
            assert wid in groups.members[a.group]
            chunks = json.loads((norm / entries[wid]["path"]).read_text(encoding="utf-8"))
            assert mem.units == len(chunks)
            assert mem.ids == store.ids_sha([c["chunk_id"] for c in chunks]), \
                f"{path}: {wid} changed since it was aligned (run scripts.align)"


def test_from_json_checks_counts() -> None:
    text = store.to_json(sample_alignment()).replace('"units": 2', '"units": 3')
    with pytest.raises(store.AlignmentFormatError):
        store.from_json(text)
