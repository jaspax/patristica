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


def test_leaves_prefer_greek_then_head_support() -> None:
    pages = _copy_pages({leaf: 11 + 2 * leaf for leaf in range(20)})
    pages[5] = "21 TITLE\n"            # page 21: a head but no text
    ls = oi.leaves_of("x", pages, 0.9)
    assert [lf.leaf for lf in ls[21]] == [5] and ls[21][0].supported
    assert ls[21][0].greek < oi.GREEK_LETTERS
    best = max(ls[23] + [oi.Leaf("y", 7, (23, 24), False, 1000, 0.95)], key=oi.Leaf.rank)
    assert best.item == "x"           # Greek and a head beat a better-agreeing copy without one


class _FakeArchive:
    """Serves cached OCR (written by the test) and image bytes; records URLs."""

    def __init__(self, jp2: list[str]) -> None:
        self.urls: list[str] = []
        self.jp2 = jp2

    def get(self, url: str, **params) -> httpx.Response:
        self.urls.append(url)
        req = httpx.Request("GET", url)
        if url.endswith("_jp2.zip/"):
            body = "".join(f'<a href="//x/{n}">{n}</a>' for n in self.jp2)
            return httpx.Response(200, text=body, request=req)
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
    table = tmp_path / "t.csv"
    row = dict(oi.Copy("good", VOL, 20, 20, 11, 50, 100, 0.95, 0, 0).row())
    oi.write_table([oi.Copy("good", VOL, 20, 20, 11, 50, 100, 0.95, 0, 0),
                    oi.Copy("bad", VOL, 20, 20, 11, 50, 100, 0.5, 0, 0)], table)
    assert row["ok"] == "y" and [r["ok"] for r in oi.read_table(table)] == ["y", "n"]
    wanted = tmp_path / "pages.jsonl"
    recs = [{"volume": VOL, "work": f"ogpg/{VOL}/a", "cols": [c, c + 1], "cause": "blank",
             "needs_ocr": True} for c in (15, 99)]
    recs.append({**recs[0], "cols": [17, 18], "needs_ocr": False})
    wanted.write_text("".join(json.dumps(r) + "\n" for r in recs))
    ia = _FakeArchive([f"good_{i:04d}.jp2" for i in range(20)])
    out = oi.locate(ia, wanted, cache, table)
    assert [(r["cols"][0], r["ia_id"]) for r in out] == [(15, "good"), (99, None)]
    assert out[0]["leaf"] == 2 and out[0]["supported"]

    assert oi.fetch(ia, cache, images) == 1
    f = images / VOL / "c0015.jp2"
    assert f.read_bytes().endswith(b"good_jp2%2Fgood_0002.jp2")
    man = [json.loads(line) for line in (images / VOL / "manifest.jsonl").read_text().splitlines()]
    assert man[0]["leaf"] == 2 and man[0]["url"].endswith("good_0002.jp2")
    n = len(ia.urls)
    assert oi.fetch(ia, cache, images) == 0 and len(ia.urls) == n   # idempotent


def test_image_url_falls_back_to_iiif_when_the_zip_does_not_line_up(tmp_path: Path) -> None:
    ia = _FakeArchive(["a_0000.jp2", "a_0001.jp2"])
    assert oi.image_url(ia, "a", 1, 2, tmp_path).endswith("a_jp2%2Fa_0001.jp2")
    assert oi.image_url(ia, "a", 1, 3, tmp_path) == \
        "https://iiif.archive.org/iiif/a$1/full/max/0/default.jpg"
