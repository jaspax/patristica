"""OCR eval set (#718): PAGE-XML reading, Calfa extraction, OGL trimming, manifest."""

import zipfile
from pathlib import Path

from scripts.ocr.eval import groundtruth, ogl
from scripts.ocr.eval.__main__ import GT_DIR, MANIFEST, read_hypothesis, read_manifest
from scripts.ocr.eval.pagexml import read_page

NS = "http://schema.primaresearch.org/PAGE/gts/pagecontent/2013-07-15"


def _page_xml(regions: str, image: str = "PG_2-633.jpg") -> str:
    return f"""<?xml version="1.0"?>
<PcGts xmlns="{NS}"><Page imageFilename="{image}" imageHeight="100" imageWidth="50">
<ReadingOrder><OrderedGroup id="g">
  <RegionRefIndexed index="1" regionRef="r1"/><RegionRefIndexed index="0" regionRef="r2"/>
</OrderedGroup></ReadingOrder>
{regions}
</Page></PcGts>"""


def _line(text: str) -> str:
    return f'<TextLine id="l"><TextEquiv><Unicode>{text}</Unicode></TextEquiv></TextLine>'


REGIONS = (
    '<TextRegion id="r1" custom="structure {type:col_greek;}">'
    '<Coords points="10,20 30,20 30,90 10,90"/>'
    + _line("καὶ τί γὰρ ἂν ἄλλο") + _line("τι προοίμιον") + "</TextRegion>"
    '<TextRegion id="r2" custom="structure {type:col_latin;}">'
    + _line("Et quid enim aliud") + "</TextRegion>"
    '<TextRegion id="r3" type="paragraph">' + _line("Θαυμαστὸς ὁ Θεὸς") + "</TextRegion>"
)


def test_read_page(tmp_path: Path) -> None:
    p = tmp_path / "p.xml"
    p.write_text(_page_xml(REGIONS), encoding="utf-8")
    page = read_page(p)
    assert page.image == "PG_2-633.jpg"
    # Reading order puts r2 first; an unordered region goes last.
    assert [r.id for r in page.regions] == ["r2", "r1", "r3"]
    assert [r.label for r in page.regions] == ["col_latin", "col_greek", "paragraph"]
    assert page.regions[1].text == "καὶ τί γὰρ ἂν ἄλλο\nτι προοίμιον"
    assert page.regions[1].box == (10, 20, 30, 90)


def test_greek_lines_skip_latin(tmp_path: Path) -> None:
    p = tmp_path / "p.xml"
    p.write_text(_page_xml(REGIONS), encoding="utf-8")
    assert groundtruth.greek_lines(p) == ["καὶ τί γὰρ ἂν ἄλλο", "τι προοίμιον", "Θαυμαστὸς ὁ Θεὸς"]


def test_extract(tmp_path: Path) -> None:
    zpath = tmp_path / "data.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("task2/PG_2-633.xml", _page_xml(REGIONS))
        z.writestr("task2/PG_2-633.jpg", b"jpeg")
        z.writestr("task1/PG_123_075.xml", _page_xml(
            '<TextRegion id="r1" custom="structure {type:col_greek;}"/>', "PG_123_075.jpeg"))
        z.writestr("__MACOSX/task2/._PG_2-633.xml", b"junk")
    gt, img = tmp_path / "gt", tmp_path / "img"
    gt.mkdir()
    img.mkdir()
    rows = groundtruth.extract(zpath, groundtruth.SOURCES[0], gt, img, tmp_path)
    assert [r["page_id"] for r in rows] == ["calfa-v2-PG_2-633"]  # layout-only page skipped
    row = rows[0]
    assert (row["pg_volume"], row["image"], row["lines"]) == ("2", "task2/PG_2-633.jpg", "3")
    assert (gt / "calfa-v2-PG_2-633.txt").read_text(encoding="utf-8").count("\n") == 3
    assert (img / "calfa-v2-PG_2-633.jpg").read_bytes() == b"jpeg"


def test_volume_of() -> None:
    assert groundtruth.volume_of("task2/PG_145-352.xml") == "145"
    assert groundtruth.volume_of("task1/PG_123_075.xml") == "123"
    assert groundtruth.volume_of("x/PG_16.3_012.xml") == "16.3"
    assert groundtruth.volume_of("grc_tlg_mpg114-1001.xml") == "114"
    assert groundtruth.volume_of("grc_grna_or_396.xml") == "35"


def test_trim_to_keeps_the_covered_run() -> None:
    ref = "Θαυμαστὸς ὁ Θεὸς ἐν τοῖς ἁγίοις αὐτοῦ\nκαὶ τί γὰρ ἂν ἄλλο τι προοίμιον"
    page = "\n".join([
        "ΤΟΥ ΕΝ ΑΓΙΟΙΣ ΠΑΤΡΟΣ ΗΜΩΝ ΕΦΡΑΙΜ",
        "Θαυμαστὸς ό Θεὸς ἐν τοῖς ἁγίοις αὑτοῦ",
        "καὶ τι γὰρ ἂν ἄλλο τι προοίμιον",
        "ΒΑΡΙΑΕ ΛΕΚΤΙΟΝΕΣ πρῶτα μὲν Ῥώμης",
    ])
    assert ogl.trim_to(page, ref).splitlines() == page.splitlines()[1:3]
    assert ogl.trim_to("ἄσχετον κείμενον ἐνθάδε", ref) == ""


def test_greek_lines_like_the_ingestor() -> None:
    assert ogl.greek_lines("καὶ τί γὰρ\nEt quid enim\n") == "καὶ τί γὰρ"


def test_read_hypothesis(tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("ὁ λόγος", encoding="utf-8")
    (tmp_path / "b.json").write_text('{"text": "ὁ", "columns": [11, 12]}', encoding="utf-8")
    assert read_hypothesis(tmp_path, "a") == ("ὁ λόγος", None)
    assert read_hypothesis(tmp_path, "b") == ("ὁ", (11, 12))
    assert read_hypothesis(tmp_path, "c") is None


def test_tracked_manifest_matches_gt_files() -> None:
    rows = read_manifest(MANIFEST)
    ids = {r["page_id"] for r in rows}
    assert len(ids) == len(rows)
    assert ids == {p.stem for p in GT_DIR.glob("*.txt")}
    for r in rows:
        text = (GT_DIR / f"{r['page_id']}.txt").read_text(encoding="utf-8")
        assert len(text.splitlines()) == int(r["lines"]), r["page_id"]
        assert r["status"] in ("checked", "draft")
