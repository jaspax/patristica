"""OCR pipeline on the OGPG holes (#721): crops, the running-head check, export."""

from __future__ import annotations

import json
from pathlib import Path

from PIL import Image, ImageDraw

from scripts.ocr import ogpg


def test_gutter_is_the_blank_band_between_the_columns() -> None:
    img = Image.new("L", (1000, 1600), 255)
    d = ImageDraw.Draw(img)
    for y in range(200, 1300, 30):
        d.rectangle((60, y, 460, y + 12), fill=0)       # left column
        d.rectangle((540, y, 940, y + 12), fill=0)      # right column
    assert 460 <= ogpg.gutter(img) <= 540


def test_greek_side(monkeypatch) -> None:
    greek = "καὶ ὁ λόγος σὰρξ ἐγένετο καὶ ἐσκήνωσεν " * 4
    texts = iter(["Hoc est corpus meum, quod pro vobis", greek])
    monkeypatch.setattr(ogpg, "tesseract", lambda img: next(texts))
    side, greek, latin = ogpg.greek_side(Image.new("L", (400, 400), 255), 200)
    assert side == "right" and greek[1] > greek[0] and latin[0] > latin[1]
    texts = iter(["Latin only here", "and here too"])
    assert ogpg.greek_side(Image.new("L", (400, 400), 255), 200)[0] is None


def test_head_check() -> None:
    page = "461 THESAURUS.\nΑΛΛΟ.\n« Οὕτω, φησὶν"
    assert ogpg.head_check([page], [461, 462]) == "ok"
    assert ogpg.head_check(["ANDRINI ARCHIEP. 464\nκαὶ"], [463, 464]) == "ok"
    # A reader reads another page's number: the leaf is a page off.
    assert ogpg.head_check(["459 THESAURUS.\nκαὶ", "\nκαὶ"], [461, 462]) == "off"
    assert ogpg.head_check(["THESAURUS.\nκαὶ"], [461, 462]) == "unread"


def test_drop_head_keeps_greek_headings() -> None:
    assert ogpg.drop_head("461\nTHES\nΑΛΛΟ.\n« Οὕτω, φησὶν", [461, 462]) == "ΑΛΛΟ.\n« Οὕτω, φησὶν"
    assert ogpg.drop_head("ANDRINI ARCHIEP. 464\nἐγείροντι τοὺς", [463, 464]) == "ἐγείροντι τοὺς"
    assert ogpg.drop_head("ἐγείροντι τοὺς", [463, 464]) == "ἐγείροντι τοὺς"


def test_clean_drops_margin_letters_and_the_notes_after_the_text() -> None:
    text = ("A ἐγείροντι τοὺς νεκρούς\nB μὲν ὡς Υἱός\nτοῦ Θεοῦ τῷ\n"
            "59 I Cor. iv, 1. 61 Galat. i, 12.\nDigitized by Google")
    assert ogpg.clean(text) == "ἐγείροντι τοὺς νεκρούς\nμὲν ὡς Υἱός\nτοῦ Θεοῦ τῷ"


GREEK = "καὶ ὁ λόγος ἦν πρὸς τὸν θεόν, καὶ θεὸς ἦν ὁ λόγος. " * 10


def _prep(tmp_path: Path) -> tuple[Path, Path]:
    prep, run = tmp_path / "prep", tmp_path / "run"
    prep.mkdir()
    recs = []
    for col, side in ((461, "left"), (463, "right"), (465, "left"), (467, None)):
        recs.append(ogpg.Prepared("vol-075", [col, col + 1], ogpg.page_id("vol-075", col), side,
                                  1900, [300, 0], [0, 300],
                                  {"ia_id": "x", "leaf": 1, "url": "u"}))
    (prep / "prepare.jsonl").write_text("".join(json.dumps(ogpg.asdict(r)) + "\n" for r in recs))
    for stage in ("final", "gemini_page", "opus_page"):
        (run / stage).mkdir(parents=True)
    pages = {461: "461 THESAURUS.\n" + GREEK, 463: "459 THESAURUS.\n" + GREEK,
             465: "465\nκαὶ"}
    for col, text in pages.items():
        for stage in ("final", "gemini_page", "opus_page"):
            (run / stage / f"vol-075-c{col:04d}.txt").write_text(text)
    return prep, run


def test_export_merges_without_replacing_another_source(tmp_path: Path) -> None:
    prep, run = _prep(tmp_path)
    ocr = tmp_path / "ocr"
    ocr.mkdir()
    (ocr / "vol-075.jsonl").write_text(
        json.dumps({"cols": [461, 462], "lines": ["calfa"], "source": "calfa"}) + "\n"
        + json.dumps({"cols": [501, 502], "lines": ["calfa"], "source": "calfa"}) + "\n")
    counts = ogpg.export(run, prep, ocr)
    # 463's head reads 459 (a page off); 465 has too little Greek; 461 is Calfa's.
    assert counts == {"exported": 1, "off": 1, "unread": 0, "thin": 1, "missing": 0}
    recs = [json.loads(line) for line in (ocr / "vol-075.jsonl").read_text().splitlines()]
    assert [(r["cols"][0], r["source"]) for r in recs] == [(461, "calfa"), (501, "calfa")]
    assert ogpg.SOURCE in json.loads((ocr / "_sources.json").read_text())
    # Without Calfa's page, ours goes in, without its head line.
    (ocr / "vol-075.jsonl").unlink()
    ogpg.export(run, prep, ocr)
    (rec,) = [json.loads(line) for line in (ocr / "vol-075.jsonl").read_text().splitlines()]
    assert rec["cols"] == [461, 462] and rec["head"] == "ok" and rec["ia_id"] == "x"
    assert rec["lines"][0].startswith("καὶ ὁ λόγος")


def test_a_later_partial_export_keeps_the_pages_exported_before(tmp_path: Path) -> None:
    prep, run = _prep(tmp_path)
    ocr = tmp_path / "ocr"
    ocr.mkdir()
    (ocr / "vol-075.jsonl").write_text(
        json.dumps({"cols": [601, 602], "lines": ["earlier"], "source": ogpg.SOURCE}) + "\n"
        + json.dumps({"cols": [461, 462], "lines": ["stale"], "source": ogpg.SOURCE}) + "\n")
    ogpg.export(run, prep, ocr)
    recs = {r["cols"][0]: r for r in map(json.loads, (ocr / "vol-075.jsonl").read_text()
                                          .splitlines())}
    assert recs[601]["lines"] == ["earlier"]            # not in this run: kept
    assert recs[461]["lines"][0].startswith("καὶ")       # accepted again: replaced


def test_prepare_redoes_a_page_whose_leaf_changed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ogpg, "greek_side", lambda img, gx: ("left", [300, 0], [0, 300]))
    images, out = tmp_path / "img" / "vol-075", tmp_path / "prep"
    images.mkdir(parents=True)
    Image.new("L", (400, 600), 255).save(images / "c0461.jpg")
    located = tmp_path / "pages.jsonl"

    def locate(item: str, leaf: int) -> None:
        located.write_text(json.dumps({"volume": "vol-075", "cols": [461, 462], "ia_id": item,
                                       "leaf": leaf}) + "\n")
        (images / "manifest.jsonl").write_text(json.dumps(
            {"file": "c0461.jpg", "ia_id": item, "page": leaf, "leaf": leaf + 1,
             "url": f"u/{item}/{leaf}"}) + "\n")
    locate("a", 7)
    (p,) = ogpg.prepare("vol-075", out, images.parent, located)
    assert p.source["url"] == "u/a/7" and (out / "images" / "vol-075-c0461.jpg").exists()
    (out / "run" / "final").mkdir(parents=True)
    (out / "run" / "final" / "vol-075-c0461.txt").write_text("old reading")
    # Unchanged: kept, its reading too.
    ogpg.prepare("vol-075", out, images.parent, located)
    assert (out / "run" / "final" / "vol-075-c0461.txt").exists()
    # Another leaf was located and fetched: cropped again, its readings removed.
    locate("b", 9)
    (p,) = ogpg.prepare("vol-075", out, images.parent, located)
    assert p.source["url"] == "u/b/9"
    assert not (out / "run" / "final" / "vol-075-c0461.txt").exists()
    assert len((out / "prepare.jsonl").read_text().splitlines()) == 1
