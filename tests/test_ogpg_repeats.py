"""Tests for repeated pages in OGPG scans and the column mapping around them (#96)."""

from __future__ import annotations

from scripts.ingest import _ogpg_columns as oc
from scripts.ingest import _ogpg_repeats as rep
from scripts.ingest import ogpg

_LETTERS = "αβγδεζηθικλμνξοπρστυφχψω"


def _page_text(n: int, words: int = 60) -> str:
    """Deterministic text unique to page ``n``: random Greek-letter words, so
    two pages are as unlike as two real ones."""
    out = []
    x = n * 7919 + 13
    for _ in range(words):
        word = ""
        for _ in range(3 + x % 7):
            x = (x * 1103515245 + 12345) % 2**31
            word += _LETTERS[(x >> 8) % len(_LETTERS)]
        out.append(word)
    return " ".join(out)


def _noisy(text: str) -> str:
    """A second OCR of the same page: a few letters and accents differ."""
    words = text.split()
    return " ".join(w[:-1] + "ς" if i % 9 == 0 else w for i, w in enumerate(words))


def _paras(pages: list[tuple[int, str]]) -> list[dict]:
    return [{"stem": f"{p:03d}", "title": None, "text": t} for p, t in pages]


class TestFindRepeats:
    def test_repeated_run_is_found(self):
        # Pages 20–29, then 30–33 are a second copy of 24–27, then 34– go on.
        pages = [(p, _page_text(p)) for p in range(20, 30)]
        pages += [(30 + i, _noisy(_page_text(24 + i))) for i in range(4)]
        pages += [(p, _page_text(p - 4)) for p in range(34, 40)]
        stems = [f"{p:03d}" for p in range(20, 40)]
        r = rep.find_repeats(_paras(pages), stems)
        assert r.pages == {"030": "024", "031": "025", "032": "026", "033": "027"}

    def test_passage_printed_twice_far_apart_is_kept(self):
        # A quotation Migne prints again 100 pages on, alone, at another place
        # on its page: not a repeated leaf.
        quote = _page_text(5, 30)
        pages = [(p, _page_text(p)) for p in range(10, 200)]
        pages[150] = (160, _page_text(999, 30) + " " + quote)   # quote at the page's end…
        pages[5] = (15, quote + " " + _page_text(998, 30))      # …and at another's start
        r = rep.find_repeats(_paras(pages), [f"{p:03d}" for p, _ in pages])
        assert r.pages == {}

    def test_misaligned_match_is_not_a_repeat(self):
        # Same passage, but starting and ending elsewhere on the page.
        a = _page_text(1, 40)
        pages = [(10, _page_text(2, 30) + " " + a + " " + _page_text(3, 30)),
                 (12, _page_text(4, 30) + " " + a + " " + _page_text(5, 30))]
        assert rep.find_repeats(_paras(pages), ["010", "011", "012"]).pages == {}

    def test_page_without_text_inside_run(self):
        pages = [(p, _page_text(p)) for p in range(20, 30)]
        pages += [(30, _noisy(_page_text(24))), (32, _noisy(_page_text(26)))]
        stems = [f"{p:03d}" for p in range(20, 34)]
        r = rep.find_repeats(_paras(pages), stems)
        assert r.pages == {"030": "024", "031": "025", "032": "026"}

    def test_only_copy_takes_its_place(self):
        # Page 25's OCR failed; its second copy (page 31) is the only one.
        pages = [(p, _page_text(p)) for p in range(20, 30) if p != 25]
        pages += [(30, _noisy(_page_text(24))), (31, _page_text(25)),
                  (32, _noisy(_page_text(26)))]
        stems = [f"{p:03d}" for p in range(20, 34)]
        r = rep.find_repeats(_paras(pages), stems)
        assert r.pages == {"030": "024", "032": "026"}
        assert r.moved == {"031": "025"}

    def test_in_place_reorders_moved_pages(self):
        paras = _paras([(24, "a"), (26, "c"), (31, "b"), (33, "d")])
        out = ogpg._in_place(paras, {"031": "025"})
        assert [p["text"] for p in out] == ["a", "b", "c", "d"]


def _heads(pages: list[int], col_of: dict[int, int]) -> list[tuple[str, list[int]]]:
    return [(f"{p:03d}", [col_of[p]] if p in col_of else []) for p in pages]


class TestMapColumnsSkip:
    def test_skipped_run_keeps_the_offset(self):
        # Pages 10–39 print columns 1–60, but the scan repeats pages 20–24 as
        # 25–29 (heads 21, 23, …), so pages 30– print columns 31–.
        col_of = {p: 2 * (p - 10) + 1 for p in range(10, 25)}
        col_of.update({p: 2 * (p - 15) + 1 for p in range(25, 30)})
        col_of.update({p: 2 * (p - 15) + 1 for p in range(30, 60)})
        heads = _heads(list(range(10, 60)), col_of)
        skip = {f"{p:03d}" for p in range(25, 30)}
        m = oc.map_columns(heads, skip=skip)
        assert m.columns["024"] == (29, 30)
        assert m.columns["027"] is None
        assert m.columns["030"] == (31, 32)
        assert m.columns["059"] == (89, 90)

    def test_blank_pages_may_print_fewer_columns(self):
        # 40 blank scan pages that print only 20 columns' worth (10 pages):
        # the offset drops after them, and no page runs ahead of its heads.
        col_of = {p: 2 * (p - 10) + 1 for p in range(10, 40)}
        col_of.update({p: 2 * (p - 40) + 1 for p in range(80, 120)})
        pages = list(range(10, 120))
        heads = _heads(pages, col_of)
        m = oc.map_columns(heads)
        assert m.columns["039"] == (59, 60)
        assert m.columns["080"] == (81, 82)
        assert m.columns["119"] == (159, 160)
        assert all(m.columns[f"{p:03d}"] is None or m.columns[f"{p:03d}"][0] < 81
                   for p in range(40, 80))

    def test_window_min(self):
        states = [(2, 0), (2, 10), (2, 20), (2, 60)]
        cost = [5.0, 1.0, 3.0, 0.0]
        c, a = oc._window_min(cost, states, [0, 1, 2, 3], 20)
        assert (c[0], a[0]) == (1.0, 1)          # offsets 0..20
        assert (c[2], a[2]) == (3.0, 2)          # offsets 20..40
        assert (c[3], a[3]) == (0.0, 3)
