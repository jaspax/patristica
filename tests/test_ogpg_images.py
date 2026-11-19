"""Tests for scripts.ogpg_images (#719): identifying IA copies, choosing leaves, fetching."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import httpx

from scripts import ogpg_images as oi

VOL = "vol-099"


def _passage(n: int) -> str:
    """A distinct Greek passage per page (words made from the page number)."""
    letters = "αβγδεζηθικλμνξοπρστυφχψω"
    words = []
    for i in range(100):
        k = n * 101 + i
        words.append("".join(letters[(k // 24 ** j + j) % 24] for j in range(4)))
    return " ".join(words)


def _raw(tmp_path: Path, pages: range) -> Path:
    raw = tmp_path / "ogpg"
    (raw / VOL).mkdir(parents=True)
    paras = [{"ref": f"ogpg.{VOL}.c{p:04d}.1", "text": _passage(p)} for p in pages]
    (raw / VOL / "a.json").write_text(json.dumps({"work": {}, "paragraphs": paras},
                                                 ensure_ascii=False), encoding="utf-8")
    return raw


def _copy_pages(cols: dict[int, int | None]) -> list[str]:
    """OCR pages of a copy: leaf -> first column printed (None: no text, no head)."""
    out = []
    for leaf in range(max(cols) + 1):
        c = cols.get(leaf)
        out.append("" if c is None else f"{c} TITLE {c + 1}\n{_passage(c)}")
    return out


def test_fold_words_and_shingles_ignore_accents() -> None:
    assert oi.fold_words("Καὶ ὁ Λόγος ἦν, τοῖς") == ["και", "λογοσ", "τοισ"]
    assert oi.shingles("καὶ λόγος ἦν θεὸς") == oi.shingles("ΚΑΙ ΛΟΓΟΣ ΗΝ ΘΕΟΣ")


def test_google_id() -> None:
    assert oi._google_id("http://books.google.com/books?id=tBYRAAAAYAAJ&oe=UTF-8") == "tBYRAAAAYAAJ"
    assert oi._google_id("") == ""


def test_identify_copy_finds_volume_and_checks_its_map(tmp_path: Path) -> None:
    ours = oi.OurText(_raw(tmp_path, range(11, 200, 2)))
    # Leaves 3.. print cols 11, 13, ...; leaf 0-2 are front matter.
    pages = _copy_pages({leaf: 11 + 2 * (leaf - 3) if leaf >= 3 else None for leaf in range(60)})
    c = oi.identify_copy("x", pages, ours, {"source": "", "contributor": "Harvard"})
    assert c.volume == VOL and c.shift == 0 and c.agree == 1.0 and c.ok
    assert c.first_col <= 11 and c.row()["ok"] == "y"
    # A copy whose heads are a page off from its text (a bad map) is not ok.
    bad = [f"{11 + 2 * (leaf - 3)} TITLE\n{_passage(13 + 2 * (leaf - 3))}" if leaf >= 3 else ""
           for leaf in range(60)]
    c = oi.identify_copy("y", bad, ours, {})
    assert c.volume == VOL and c.shift == 2 and not c.ok


def test_trust_comes_from_the_text_at_both_edges_of_a_hole() -> None:
    # Our text matches leaves 0-19 and 60-79 where the map puts them; 20-59 is a hole.
    diffs = {leaf: [0] for leaf in [*range(20), *range(60, 80)]}
    assert oi.trust(diffs, 40, False) == (True, True)
    assert oi.Leaf("x", 40, (91, 92), False, 0, True, True).trusted
    # After the hole the map is a page off: only a leaf whose own head prints
    # its column is trusted.
    diffs = {leaf: [0] for leaf in range(20)} | {leaf: [4] for leaf in range(60, 80)}
    assert oi.trust(diffs, 40, False) == (True, False)
    assert not oi.Leaf("x", 40, (91, 92), False, 0, True, False).trusted
    assert oi.Leaf("x", 40, (91, 92), True, 0, True, False).trusted
    # Stray matches at scattered offsets (repeated phrases) don't outvote the edges.
    noisy = {leaf: [0] for leaf in [*range(20), *range(60, 80)]} | {
        leaf: [leaf * 7] for leaf in range(30, 55)}
    assert oi.trust(noisy, 40, False) == (True, True)
    # ... nor does one leaf matching a repeated passage many times.
    assert oi.trust(noisy | {45: [-300] * 9, 35: [-300] * 9}, 40, False) == (True, True)
    # Too far from any text: nothing.
    assert oi.trust({0: [0] * 9}, 0 + oi.REACH + 5, True) == (False, False)


def test_leaves_prefer_trusted_then_greek_then_head_support() -> None:
    pages = _copy_pages({leaf: 11 + 2 * leaf for leaf in range(20)})
    pages[5] = "21 TITLE\n"            # page 21: a head but no text
    ls = oi.leaves_of("x", pages, {leaf: [0] for leaf in range(20)})
    assert [lf.leaf for lf in ls[21]] == [5] and ls[21][0].supported and ls[21][0].trusted
    assert ls[21][0].greek < oi.GREEK_LETTERS
    other = oi.Leaf("y", 7, (23, 24), False, 1000, True, True)
    assert max(ls[23] + [other], key=oi.Leaf.rank).item == "x"   # a head beats no head
    untrusted = oi.Leaf("z", 7, (23, 24), False, 1000, True, False)
    assert not untrusted.trusted and max(ls[23] + [untrusted], key=oi.Leaf.rank).item == "x"


class _FakeArchive:
    """Serves a jp2 zip listing, a scandata whose leaves start at ``first``, and
    image bytes; records URLs."""

    def __init__(self, jp2: list[str], first: int = 0, pages: int = 20) -> None:
        self.urls: list[str] = []
        self.jp2, self.first, self.pages = jp2, first, pages

    def get(self, url: str, **params) -> httpx.Response:
        self.urls.append(url)
        req = httpx.Request("GET", url)
        if url.endswith("_jp2.zip/"):
            if not self.jp2:
                return httpx.Response(404, request=req)
            body = "".join(f'<a href="//ia1.us.archive.org/view_archive.php?archive=/1/items/'
                           f'{n.rsplit("_", 1)[0]}/{n.rsplit("_", 1)[0]}_jp2.zip&amp;file='
                           f'{n.rsplit("_", 1)[0]}_jp2%2F{n}">{n}</a>' for n in self.jp2)
            return httpx.Response(200, text=body, request=req)
        if url.endswith("_scandata.xml"):
            leaves = "".join(f'<page leafNum="{self.first + i}"><x/></page>'
                             for i in range(self.pages))
            leaves += f'<page leafNum="{self.first + self.pages}">' \
                      "<addToAccessFormats>false</addToAccessFormats></page>"
            return httpx.Response(200, text=f"<book>{leaves}</book>", request=req)
        return httpx.Response(200, content=b"IMG" + url.encode(), request=req)


def _cache_item(cache: Path, item: str, pages: list[str]) -> None:
    (cache / "ia").mkdir(parents=True, exist_ok=True)
    (cache / "ia" / f"{item}.json.gz").write_bytes(
        gzip.compress(json.dumps({"pages": pages}).encode()))


def test_locate_and_fetch(tmp_path: Path) -> None:
    cache, images = tmp_path / "cache", tmp_path / "img"
    pages = _copy_pages({leaf: 11 + 2 * leaf for leaf in range(20)})
    _cache_item(cache, "good", pages)
    _cache_item(cache, "bad", pages)
    good = oi.Copy("good", VOL, 20, 20, 11, 50, 100, 0.95, 0, 0,
                   diffs={leaf: [0] for leaf in range(20)})
    bad = oi.Copy("bad", VOL, 20, 20, 11, 50, 100, 0.5, 4, 0,
                  diffs={leaf: [4] for leaf in range(20)})
    oi.save_diffs(good, cache)
    oi.save_diffs(bad, cache)
    table = tmp_path / "t.csv"
    oi.write_table([good, bad], table)
    assert [r["ok"] for r in oi.read_table(table)] == ["y", "n"]
    wanted = tmp_path / "pages.jsonl"
    recs = [{"volume": VOL, "work": f"ogpg/{VOL}/a", "cols": [c, c + 1], "cause": "blank",
             "needs_ocr": True} for c in (15, 99)]
    recs.append({**recs[0], "cols": [17, 18], "needs_ocr": False})
    wanted.write_text("".join(json.dumps(r) + "\n" for r in recs))
    ia = _FakeArchive([f"good_{i:04d}.jp2" for i in range(20)])
    out = oi.locate(ia, wanted, cache, table)
    assert [(r["cols"][0], r["ia_id"]) for r in out] == [(15, "good"), (99, None)]
    assert out[0]["leaf"] == 2 and out[0]["supported"] and out[0]["options"] == 1
    assert out[1]["untrusted"] == 0

    assert oi.fetch(ia, cache, images) == 1
    f = images / VOL / "c0015.jp2"
    assert f.read_bytes().endswith(b"good_jp2%2Fgood_0002.jp2")
    man = [json.loads(line) for line in (images / VOL / "manifest.jsonl").read_text().splitlines()]
    assert man[0]["page"] == 2 and man[0]["url"].endswith("good_0002.jp2")
    n = len(ia.urls)
    assert oi.fetch(ia, cache, images) == 0 and len(ia.urls) == n   # idempotent


def test_image_url_follows_the_scandata_leaf_numbers(tmp_path: Path) -> None:
    # Leaves numbered from 1: page 1 of the OCR is leaf 2, in the zip and in IIIF.
    ia = _FakeArchive([f"a_{i:04d}.jp2" for i in range(1, 4)], first=1, pages=3)
    assert oi.image_url(ia, "a", 1, 3, tmp_path) == (
        "https://archive.org/download/a/a_jp2.zip/a_jp2%2Fa_0002.jp2", 2)
    ia = _FakeArchive([], first=1, pages=3)
    assert oi.image_url(ia, "b", 1, 3, tmp_path) == (
        "https://iiif.archive.org/iiif/b$2/full/max/0/default.jpg", 2)
    # A scandata that doesn't match the OCR, and no zip: not guessed.
    assert oi.image_url(_FakeArchive([], pages=5), "c", 1, 3, tmp_path) is None
