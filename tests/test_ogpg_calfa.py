"""Tests for scripts.ogpg_calfa (#719): placing Calfa's PDF pages on our columns."""

from __future__ import annotations

import gzip
import json
import zipfile
from pathlib import Path

from scripts import ogpg_calfa as oc
from scripts import ogpg_images as oi
from tests.test_ogpg_images import VOL, _passage, _raw


def _vert(pages: dict[int, str]) -> str:
    """A Calfa file: one ``<w>`` per word, by PDF page and line (CRLF, as released)."""
    out = ['<doc id="PG 99 - AI processed">']
    n = 0
    for p, text in sorted(pages.items()):
        for li, line in enumerate(text.split("\n"), 1):
            for w in line.split():
                n += 1
                out += [f'<w id="PDF Page {p}, Line {li} - word id {n}">',
                        f"{w}\tx\tx\tx\tN", "</w>"]
    return "\r\n".join(out + ["</doc>"])


def test_volume_of() -> None:
    assert oc.volume_of("PG/PG087_1_tagged_text.vert") == "vol-087-pt1"
    assert oc.volume_of("PG/PG021_tagged_text.txt") == "vol-021"
    assert oc.volume_of("PG/README") is None


def test_read_pages_keeps_lines() -> None:
    pages = oc.read_pages(_vert({12: "Τοῦτον μὲν\nτὸν τρόπον", 13: "εἰς"}))
    assert pages == {12: ["Τοῦτον μὲν", "τὸν τρόπον"], 13: ["εἰς"]}


def _calfa_zip(tmp_path: Path, pages: dict[int, str]) -> Path:
    cache = tmp_path / "calfa"
    cache.mkdir()
    with zipfile.ZipFile(cache / f"PG-{oc.RECORD}.zip", "w") as z:
        z.writestr("PG/PG099_tagged_text.vert", _vert(pages))
    return cache


def test_place_and_fill_only_holes(tmp_path: Path) -> None:
    # Our text: cols 11-199 except the hole 61-79 (PDF pages 30-39: col = 2p + 1).
    ours_pages = [c for c in range(11, 200, 2) if not 61 <= c <= 79]
    raw = _raw(tmp_path, ours_pages)
    calfa = {(c - 1) // 2: _passage(c) for c in range(11, 200, 2)}
    cache = _calfa_zip(tmp_path, calfa)
    pl = oc.place(VOL, oc.read_pages(_vert(calfa)), oi.OurText(raw))
    assert pl.cols[30] == (61, 62) and pl.agree == 1.0
    wanted = tmp_path / "pages.jsonl"
    recs = [{"volume": VOL, "cols": [c, c + 1], "needs_ocr": c != 79} for c in range(61, 81, 2)]
    wanted.write_text("".join(json.dumps(r) + "\n" for r in recs))
    out = tmp_path / "ocr"
    filled = oc.fill(wanted, raw, cache, out, tmp_path / "no-images")
    assert filled == {VOL: 9}                       # not col 79: it doesn't need OCR
    got = [json.loads(line) for line in (out / f"{VOL}.jsonl").read_text().splitlines()]
    assert got[0]["cols"] == [61, 62] and got[0]["pdf_page"] == 30
    assert got[0]["lines"] == [_passage(61)] and got[0]["confirmed_by"] == "text"
    assert oc.SOURCE in json.loads((out / "_sources.json").read_text())


def test_a_hole_at_the_end_is_confirmed_by_the_located_leaf(tmp_path: Path) -> None:
    # Calfa's text stops inside our hole (cols 61-): no text of ours after it.
    raw = _raw(tmp_path, range(11, 61, 2))
    calfa = {(c - 1) // 2: _passage(c) for c in range(11, 80, 2)}
    cache = _calfa_zip(tmp_path, calfa)
    wanted = tmp_path / "pages.jsonl"
    wanted.write_text("".join(json.dumps({"volume": VOL, "cols": [c, c + 1], "needs_ocr": True})
                              + "\n" for c in (61, 63)))
    # The Internet Archive leaf located for col 61 has the same text; none for 63.
    images = tmp_path / "images"
    (images / "ia").mkdir(parents=True)
    (images / "ia" / "copy.json.gz").write_bytes(gzip.compress(json.dumps(
        {"pages": ["", _passage(61)]}).encode()))
    (images / "pages.jsonl").write_text(json.dumps(
        {"volume": VOL, "cols": [61, 62], "ia_id": "copy", "leaf": 1}) + "\n")
    out = tmp_path / "ocr"
    assert oc.fill(wanted, raw, cache, out, images) == {VOL: 1}
    (rec,) = [json.loads(line) for line in (out / f"{VOL}.jsonl").read_text().splitlines()]
    assert rec["cols"] == [61, 62] and rec["confirmed_by"] == "leaf"
