"""Same-language editions aligned by their text (#199)."""

from __future__ import annotations

import random

import pytest

np = pytest.importorskip("numpy")

from patristica import alignment as al  # noqa: E402
from patristica import text_alignment as ta  # noqa: E402

WORDS = ("alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi omicron pi rho "
         "sigma tau upsilon phi chi psi omega").split()


def _text(n: int, seed: int = 0) -> list[str]:
    rng = random.Random(seed)
    return [rng.choice(WORDS) + str(rng.randrange(50)) for _ in range(n)]


def _cut(words: list[str], sizes: list[int]) -> list[str]:
    out, k = [], 0
    for s in sizes:
        out.append(" ".join(words[k:k + s]))
        k += s
    assert k == len(words)
    return out


def test_align_words_matches_identical_and_skips_insertions() -> None:
    a = _text(2000)
    b = a[:700] + _text(50, seed=1) + a[700:]
    pairs = ta.align_words(a, b, ta.Params(small=40))
    assert len(pairs) == 2000
    assert all(a[i] == b[j] for i, j in pairs)
    assert all(i < i2 and j < j2 for (i, j), (i2, j2) in zip(pairs, pairs[1:]))


def test_in_runs_keeps_only_long_runs() -> None:
    pairs = [(0, 0), (1, 1), (2, 2), (5, 9), (7, 10), (8, 11), (9, 12), (10, 13)]
    assert ta.in_runs(pairs, 3) == [(0, 0), (1, 1), (2, 2), (7, 10), (8, 11), (9, 12), (10, 13)]


def test_same_text_cut_differently_gives_n_to_m_beads() -> None:
    words = _text(60)
    a = _cut(words, [10, 10, 10, 10, 20])
    b = _cut(words, [10, 15, 5, 10, 20])  # unit 2/3 boundary moved by half a unit
    r = ta.align_texts(a, b)
    spans = [(t.i0, t.i1, t.j0, t.j1) for t in r.beads]
    assert spans == [(0, 1, 0, 1), (1, 3, 1, 3), (3, 4, 3, 4), (4, 5, 4, 5)]
    assert all(t.conf == 1.0 for t in r.beads)
    assert r.shared == 1.0


def test_small_spill_does_not_link_neighbours() -> None:
    words = _text(100)
    a = _cut(words, [50, 50])
    b = _cut(words, [48, 52])  # two words of A's first unit in B's second
    r = ta.align_texts(a, b)
    assert [(t.i0, t.i1, t.j0, t.j1) for t in r.beads] == [(0, 1, 0, 1), (1, 2, 1, 2)]


def test_noise_and_partial_overlap() -> None:
    words = _text(300)
    noisy = list(words)
    for k in range(0, 300, 17):
        noisy[k] = "ocr" + noisy[k][::-1]  # damaged words
    a = _cut(words, [100, 100, 100])
    b = _cut(_text(80, seed=5), [80]) + _cut(noisy[100:], [100, 100])  # lacks A's first unit
    r = ta.align_texts(a, b)
    assert [(t.i0, t.i1, t.j0, t.j1) for t in r.beads] == [(1, 2, 1, 2), (2, 3, 2, 3)]
    assert all(0.8 < t.dice < 1.0 for t in r.beads)


def test_unrelated_texts_share_nothing() -> None:
    a = _cut(_text(500, seed=1), [100] * 5)
    b = _cut(_text(500, seed=2), [100] * 5)
    r = ta.align_texts(a, b)
    assert r.shared < ta.Params().min_shared
    assert r.beads == []


def test_folding_matches_accents_and_case() -> None:
    r = ta.align_texts(["Ἀπειρηκότα με ἤδη πρὸς τὰς παρὰ τῆς"],
                       ["ἀπειρηκοτα με ηδη προς τας παρα της"])
    assert r.shared == 1.0 and len(r.beads) == 1


def _bead(i0: int, i1: int, j0: int, j1: int, conf: float = 0.9) -> al.Bead:
    return al.Bead(i0, i1, j0, j1, 0.5, 0.2, conf)


def _tb(i0: int, i1: int, j0: int, j1: int, conf: float = 1.0) -> ta.TextBead:
    return ta.TextBead(i0, i1, j0, j1, conf, conf)


def test_text_beads_with_the_pivot_as_head_are_used_as_they_are() -> None:
    out = al.text_beads([_tb(0, 1, 0, 1), _tb(1, 3, 1, 2)], None)
    assert [(b.i0, b.i1, b.j0, b.j1, b.conf) for b in out] == [(0, 1, 0, 1, 1.0),
                                                                (1, 3, 1, 2, 1.0)]


def test_text_beads_are_carried_through_the_head() -> None:
    head = [_bead(0, 1, 0, 2, 0.8), _bead(1, 2, 2, 3), _bead(2, 3, 3, 4), _bead(3, 4, 9, 10),
            _bead(4, 5, 4, 5)]
    texts = [_tb(0, 1, 0, 1), _tb(1, 2, 1, 3),  # head units 1-2: pivot 2-4
             _tb(2, 3, 3, 5)]  # head units 3-4 are a moved block: dropped
    out = al.text_beads(texts, head)
    assert [(b.i0, b.i1, b.j0, b.j1, b.conf) for b in out] == [(0, 1, 0, 2, 0.8),
                                                                (1, 2, 2, 4, 0.9)]


def test_text_beads_through_one_head_bead_are_joined() -> None:
    head = [_bead(0, 2, 0, 1)]
    out = al.text_beads([_tb(0, 1, 0, 1), _tb(1, 2, 1, 2)], head)
    assert [(b.i0, b.i1, b.j0, b.j1) for b in out] == [(0, 2, 0, 1)]


def test_prefer_text_drops_vector_beads_that_touch_text_beads() -> None:
    text = [_bead(0, 2, 0, 2)]
    vector = [_bead(0, 1, 0, 1), _bead(2, 3, 1, 2), _bead(3, 4, 3, 4)]
    assert [(b.i0, b.j0) for b in al.prefer_text(text, vector)] == [(0, 0), (3, 3)]


def test_merge_keeps_a_joined_text_bead_in_one_group() -> None:
    # The pivot's units 0 and 1 are cut apart by a 1:1 version, but an edition's
    # text bead covers both: they stay one group.
    pairs = {"v": (2, [_bead(0, 1, 0, 1), _bead(1, 2, 1, 2)]),
             "e": (1, [_bead(0, 1, 0, 2)])}
    pairs["w"] = (2, [_bead(0, 1, 0, 1), _bead(1, 2, 1, 2)])
    assert al.merge("p", 2, pairs).n_groups == 2
    merged = al.merge("p", 2, pairs, joined_by=[_bead(0, 1, 0, 2)])
    assert merged.n_groups == 1
    assert list(merged.group_of["e"]) == [0]


def test_choose_pivot_prefers_editions_then_the_cleaner_text() -> None:
    members = {"eng": ("eng", 1000), "migne": ("grc", 990), "crit": ("grc", 960)}
    assert al.choose_pivot(members) == "eng"
    weights = {"migne": 900, "crit": 900}
    assert al.choose_pivot(members, weights, {"migne": 0.85, "crit": 0.88}) == "crit"
    assert al.choose_pivot(members, weights) == "migne"  # the longer of the two
    # A small overlap in English doesn't outweigh the Greek editions.
    assert al.choose_pivot(members, {**weights, "eng": 30}) == "migne"


# --- Chinese (#648) ----------------------------------------------------------

# The same passage of the Xi'an stele in zh.wikisource (punctuated, the stone's
# variant characters) and in the Taishō (T2144: only 。, standard forms).
WIKISOURCE = ["粵若常然真寂，先先而无元；窅然靈虗，後後而妙有。惣玄摳而造化，妙衆聖以元尊者，",
              "其唯我三一妙身无元真主阿羅訶歟！判十字以㝎四方，皷元風而生二氣。",
              "暗空易而天地開，日月運而晝夜作。"]
TAISHO = ["粵若。常然真寂。先先而無元。窅然靈虛。後後而妙有。總玄摳而造化。妙眾聖以元尊者。"
          "其唯我三一妙身無元真主阿羅訶歟判。十字以定四方。鼓元風而生二氣。",
          "暗空易而天地開。日月運而晝夜作。"]


def test_chinese_tokens_are_characters() -> None:
    assert ta.tokens("大秦㬌教，流行 Syriac") == ["大", "秦", "景", "教", "流", "行", "syriac"]
    assert ta.tokens("In the beginning, God") == ["in", "the", "beginning", "god"]


def test_chinese_editions_align_by_text() -> None:
    r = ta.align_texts(WIKISOURCE, TAISHO)
    assert r.shared > 0.9
    assert [(b.i0, b.i1, b.j0, b.j1) for b in r.beads] == [(0, 2, 0, 1), (2, 3, 1, 2)]
