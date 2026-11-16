"""Tests for scripts.ogpg_coverage (#706)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import ogpg_coverage as oc
from scripts import status
from scripts.ingest import _ogpg_index as pgi

HEADER = ("volume,slug,col_start,col_end,author,title,cpg,tlg,date_composed,date_start,date_end,"
          "date_confidence,basis,duplicate_of,note\n")
VOL = "vol-099"
GREEK = "καὶ ὁ λόγος ἦν πρὸς τὸν θεόν, καὶ θεὸς ἦν ὁ λόγος."


def _row(slug: str, start: int, end: int | str, date: str = "400,390,410") -> str:
    return f"{VOL},{slug},{start},{end},Anon,T {slug},,,{date},approximate,heads,,"


def _index(*rows: str) -> dict[str, list[pgi.IndexRow]]:
    return pgi.parse_index([HEADER, *(r + "\n" for r in rows)])


def _stem(page: int) -> str:
    return f"{page:03d}"


def _write(raw: Path, rel: str, refs: list[str], first: str = GREEK) -> None:
    path = raw / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    paras = [{"ref": f"ogpg.{VOL}.{r}.1", "text": first if i == 0 else GREEK}
             for i, r in enumerate(refs)]
    path.write_text(json.dumps({"work": {}, "paragraphs": paras}, ensure_ascii=False),
                    encoding="utf-8")


def _measure(raw: Path, index: dict, **kw) -> list[oc.WorkCoverage]:
    return oc.measure(raw, index, cache_dir=raw.parent / "cache", workers=1, **kw)


def _cols(*cols: int) -> list[str]:
    return [f"c{c:04d}" for c in cols]


@pytest.fixture
def raw(tmp_path: Path) -> Path:
    """A volume whose scan pages 10–29 print cols. 11–50 (page p: 2p-9, 2p-8),
    except that the scan lacks pages 15 (cols. 21–22) and 22 (cols. 35–36)."""
    raw = tmp_path / "ogpg"
    heads = [(_stem(p), [2 * p - 9, 2 * p - 8]) for p in range(10, 30) if p not in (15, 22)]
    extract = {"repo": "Vol.-99", "pipeline": {"primary_scan": "x_ocr"},
               "page_heads": heads,
               # The check reads only the map (the extract's own text would
               # be found repeated: every page here has the same).
               "paragraphs": [],
               "fills": []}
    (raw / "_extract").mkdir(parents=True)
    (raw / "_extract" / f"{VOL}.json").write_text(json.dumps(extract), encoding="utf-8")
    # a: cols. 11–20 and 31–34; col. 17 (page 13) has no text; starts mid-sentence.
    _write(raw, f"{VOL}/a.json", _cols(11, 13, 15, 19, 31, 33), first="ἦν ἀρχῇ.")
    # b: cols. 21–30; 21 is missing from the scan but its text sits under the
    # unplaced page ref p0015; 25 is in other.json.
    _write(raw, f"{VOL}/b.json", ["p0015"] + _cols(23, 27, 29))
    _write(raw, f"{VOL}/other.json", _cols(25))
    # c: cols. 35– (to the scan's end, col. 50); 35 is missing from the scan
    # with no text anywhere.
    _write(raw, f"{VOL}/c.json", _cols(37, 39, 41, 43, 45, 47, 49), first="Ἐν ἀρχῇ ἦν ὁ λόγος.")
    return raw


@pytest.fixture
def index() -> dict[str, list[pgi.IndexRow]]:
    return _index(_row("a", 11, 20), _row("b", 21, 30), _row("a", 31, 34),
                  _row("c", 35, ""), _row("late", 51, "", date="1200,1190,1210"))


def test_pages_are_counted_by_their_first_column() -> None:
    assert oc.page_of(17) == 17 and oc.page_of(18) == 17
    assert oc.pages_in([(11, 20), (31, 34)]) == [11, 13, 15, 17, 19, 31, 33]
    assert oc.pages_in([(1372, 1375)]) == [1371, 1373, 1375]


def test_coverage_and_causes(raw: Path, index) -> None:
    works = {w.work: w for w in _measure(raw, index)}
    assert set(works) == {f"ogpg/{VOL}/{s}" for s in "abc"}   # not the late row

    a = works[f"ogpg/{VOL}/a"]
    assert (a.expected, a.present) == (7, 6)
    assert [(h.first, h.last, dict(h.causes)) for h in a.holes] == [(17, 18, {"no_text": 1})]
    assert a.start_mid is True

    b = works[f"ogpg/{VOL}/b"]
    assert (b.expected, b.present) == (5, 3)
    assert dict(b.causes) == {"unplaced": 1, "elsewhere": 1}

    c = works[f"ogpg/{VOL}/c"]              # runs to col. 50, the scan's last
    assert (c.expected, c.present) == (8, 7)
    assert [(h.first, h.last, dict(h.causes)) for h in c.holes] == [(35, 36, {"unmapped": 1})]
    assert c.start_mid is False


def test_column_maps_are_cached_per_extract(raw: Path, index, monkeypatch) -> None:
    first = [w.to_json() for w in _measure(raw, index)]
    assert (raw.parent / "cache" / f"{VOL}.json").exists()

    def boom(extract: dict) -> None:
        raise AssertionError("recomputed")

    monkeypatch.setattr(oc, "_scan_map", boom)
    assert [w.to_json() for w in _measure(raw, index)] == first
    extract = raw / "_extract" / f"{VOL}.json"
    extract.write_text(extract.read_text(encoding="utf-8") + " ", encoding="utf-8")
    with pytest.raises(AssertionError, match="recomputed"):
        _measure(raw, index)


def test_parallel_run_matches_serial(raw: Path, index) -> None:
    serial = [w.to_json() for w in _measure(raw, index)]
    parallel = oc.measure(raw, index, cache_dir=None, workers=2)
    assert [w.to_json() for w in parallel] == serial


def test_holes_join_consecutive_pages(tmp_path: Path) -> None:
    holes = oc._holes([(11, "no_text"), (13, "unmapped"), (17, "no_text")])
    assert [(h.first, h.last, h.pages) for h in holes] == [(11, 14, 2), (17, 18, 1)]
    assert dict(holes[0].causes) == {"no_text": 1, "unmapped": 1}


def test_unindexed_volume_is_measured_over_its_mapped_columns(raw: Path) -> None:
    single = raw / f"{VOL}.json"
    _write(raw, f"{VOL}.json", _cols(*range(11, 51, 2)))
    for p in (raw / VOL).glob("*.json"):
        p.unlink()
    (raw / VOL).rmdir()
    [w] = _measure(raw, {})
    assert w.work == f"ogpg/{VOL}" and w.expected == 20 and w.present == 20
    assert single.exists()


def test_summary_and_tsvs(raw: Path, index) -> None:
    works = _measure(raw, index)
    s = oc.summary(works)
    assert s["works"] == 3 and s["missing_pages"] == 4 and s["expected_pages"] == 20
    assert s["causes"] == {"elsewhere": 1, "no_text": 1, "unmapped": 1, "unplaced": 1}
    line = oc.summary_line(s)
    assert "4 of 20 pages missing" in line and "unplaced 1" in line
    tsv = oc.works_tsv(works)
    assert tsv[0].startswith("work\t") and tsv[1].startswith(f"ogpg/{VOL}/b\t")
    assert len(oc.holes_tsv(works)) == 1 + 4
    assert json.dumps([w.to_json() for w in works])      # serialisable


def test_classify_page() -> None:
    lexicon = frozenset({"και", "ο", "λογος", "ην", "προς", "τον", "θεον", "θεος"})
    assert oc.classify_page("123\n", lexicon) == "blank"
    assert oc.classify_page("Et verbum erat apud Deum, et Deus erat verbum. " * 10,
                            lexicon) == "latin"
    assert oc.classify_page((GREEK + "\n") * 10, lexicon) == "dropped"
    assert oc.classify_page("ξζψ ϡϗ ββββ γγγ δδδ ζζζ ηηη θθθ, ιιι. " * 10, lexicon) == "garbled"


def test_status_row(monkeypatch, tmp_path: Path, raw: Path, index) -> None:
    works = _measure(raw, index)
    monkeypatch.setattr(oc, "measure", lambda raw_dir: works)
    [row] = status.ogpg_coverage_rows(raw.parent)
    assert (row.step, row.check, row.level) == ("ingest", "ogpg coverage", "warn")
    assert "4 of 20 pages missing" in row.detail
    assert status.ogpg_coverage_rows(tmp_path / "nowhere") == []
