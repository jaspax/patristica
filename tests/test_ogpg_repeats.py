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


# ---------------------------------------------------------------------------
# Cross-scan fill and misbound leaves (#90)
# ---------------------------------------------------------------------------

def _scan(name: str, pages: dict[int, str], cols_per_page: int = 2) -> ogpg._Scan:
    """A scan whose page p (all numbered from 10) prints columns 2(p-10)+1…, every
    page with its head number, each page one paragraph."""
    cands = []
    for i, (p, text) in enumerate(sorted(pages.items())):
        c = ogpg.Candidate(page=i, text=text, stem=f"{p:03d}")
        c.score = ogpg.lex.LexScore(100, 100, 1.0)
        cands.append(c)
    heads = [(f"{p:03d}", [cols_per_page * (p - 10) + 1]) for p in sorted(pages)]
    return ogpg._Scan(name, cands, len(pages), heads)


class TestCrossScan:
    def test_fills_columns_the_primary_lacks(self):
        full = {p: _page_text(p) for p in range(10, 40)}
        primary = _scan("pst.x_ocr", {p: t for p, t in full.items() if p < 30})
        other = _scan("hvd.y_ocr", {p: _noisy(t) for p, t in full.items()})
        kept = [{"stem": c.stem, "title": None, "text": c.text} for c in primary.candidates]
        # Primary pages 30–39 exist but have no text.
        primary.heads += [(f"{p:03d}", [2 * (p - 10) + 1]) for p in range(30, 40)]
        misbound, fills = ogpg._cross_scan(primary, kept, [other])
        assert misbound == set()
        assert [f["stem"] for f in fills] == [f"{p:03d}" for p in range(30, 40)]
        assert fills[0]["cols"] == [41, 42] and fills[0]["scan"] == "hvd.y_ocr"

    def test_text_already_present_is_not_filled(self):
        full = {p: _page_text(p) for p in range(10, 40)}
        primary = _scan("pst.x_ocr", full)
        other = _scan("hvd.y_ocr", {p: _noisy(t) for p, t in full.items()})
        kept = [{"stem": c.stem, "title": None, "text": c.text} for c in primary.candidates]
        assert ogpg._cross_scan(primary, kept, [other]) == (set(), [])

    def test_misbound_leaves_are_replaced(self):
        full = {p: _page_text(p) for p in range(10, 40)}
        bound_wrong = {p: (_page_text(500 + p) if 20 <= p <= 23 else t) for p, t in full.items()}
        primary = _scan("pst.x_ocr", bound_wrong)
        other = _scan("hvd.y_ocr", {p: _noisy(t) for p, t in full.items()})
        kept = [{"stem": c.stem, "title": None, "text": c.text} for c in primary.candidates]
        misbound, fills = ogpg._cross_scan(primary, kept, [other])
        assert misbound == {"020", "021", "022", "023"}
        assert [f["stem"] for f in fills] == ["020", "021", "022", "023"]

    def test_merge_fills_in_column_order(self):
        paras = [{"text": "a", "cols": (1, 2)}, {"text": "b", "cols": None},
                 {"text": "d", "cols": (7, 8)}]
        fills = [{"text": "c", "cols": (5, 6)}, {"text": "e", "cols": (9, 10)}]
        assert [p["text"] for p in ogpg._merge_fills(paras, fills)] == list("abcde")

    def test_misbinding_shared_by_another_scan(self):
        full = {p: _page_text(p) for p in range(10, 40)}
        bound_wrong = {p: (_page_text(500 + p) if 20 <= p <= 23 else t) for p, t in full.items()}
        primary = _scan("pst.x_ocr", bound_wrong)
        twin = _scan("njp.z_ocr", {p: _noisy(t) for p, t in bound_wrong.items()})
        good = [_scan(f"hvd.{i}_ocr", {p: _noisy(t) for p, t in full.items()}) for i in range(2)]
        kept = [{"stem": c.stem, "title": None, "text": c.text} for c in primary.candidates]
        misbound, fills = ogpg._cross_scan(primary, kept, [twin, *good])
        assert misbound == {"020", "021", "022", "023"}
        assert {f["scan"] for f in fills} == {"hvd.0_ocr"}
        assert all(_page_text(500 + int(f["stem"])) != f["text"] for f in fills)

    def test_page_mapped_to_wrong_columns_is_not_misbound(self):
        # The primary's pages 20–23 carry text the other scans have at other
        # columns (its map runs ahead there): not leaves of another volume.
        full = {p: _page_text(p) for p in range(10, 60)}
        shifted = {p: (full[p + 20] if 20 <= p <= 23 else t) for p, t in full.items()}
        primary = _scan("pst.x_ocr", shifted)
        others = [_scan(f"hvd.{i}_ocr", {p: _noisy(t) for p, t in full.items()}) for i in range(2)]
        kept = [{"stem": c.stem, "title": None, "text": c.text} for c in primary.candidates]
        misbound, _ = ogpg._cross_scan(primary, kept, others)
        assert misbound == set()
