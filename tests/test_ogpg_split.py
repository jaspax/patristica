"""Tests for OGPG column mapping, the work index and volume splitting (#67)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.ingest import _ogpg_columns as oc
from scripts.ingest import _ogpg_index as pgi
from scripts.ingest import ogpg

HEADER = ("volume,slug,col_start,col_end,author,title,cpg,date_composed,date_start,date_end,"
          "date_confidence,basis,duplicate_of,note\n")


def _index(*rows: str) -> dict[str, list[pgi.IndexRow]]:
    return pgi.parse_index(["# comment\n", HEADER, *(r + "\n" for r in rows)])


# ---------------------------------------------------------------------------
# Column mapping
# ---------------------------------------------------------------------------

class TestHeadNumbers:
    def test_running_head_and_lone_number(self):
        text = "Η S. GREGORII NYSSENI 12\nκαὶ ὁ λόγος ἦν πρὸς τὸν θεόν, 6 καὶ\n285\n"
        assert oc.head_numbers(text) == {12, 285}

    def test_ignores_small_bracketed_and_mid_line_numbers(self):
        text = "[216]\n6\nκαὶ 7&9 ὁ\nlong line with 345 in the middle of it\n"
        assert oc.head_numbers(text) == set()

    def test_long_lines_ignored(self):
        assert oc.head_numbers("1 2 3 4 5 6 7 8 300") == set()


def _two_column_heads(n_pages: int, first_page: int, first_col: int,
                      plate_after: int | None = None) -> list[tuple[str, list[int]]]:
    """Synthetic scan: page p prints columns (c, c+1); every 3rd page has no
    head; a plate (no columns) may be inserted; noise numbers on every page."""
    heads: list[tuple[str, list[int]]] = []
    col = first_col
    p = first_page
    for i in range(n_pages):
        nums = [7 + (i % 5) * 3]                    # chapter/footnote noise
        if i % 3:
            nums.append(col + (i % 2))              # left or right column number
        heads.append((f"{p:03d}", nums))
        p += 1
        col += 2
        if plate_after is not None and i == plate_after:
            heads.append((f"{p:03d}", []))         # unnumbered plate
            p += 1
    return heads


class TestMapColumns:
    def test_linear_two_column_scan(self):
        m = oc.map_columns(_two_column_heads(40, 12, 9))
        assert m.columns["012"] == (9, 10)
        assert m.columns["051"] == (87, 88)
        assert m.numbered == 40

    def test_plate_shifts_offset(self):
        m = oc.map_columns(_two_column_heads(60, 12, 9, plate_after=29))
        assert m.columns["041"] == (67, 68)      # last page before the plate
        assert m.columns["042"] is None          # the plate
        assert m.columns["043"] == (69, 70)

    def test_front_matter_gets_no_column(self):
        heads = [(f"{p:03d}", []) for p in range(1, 12)] + _two_column_heads(30, 12, 1)
        m = oc.map_columns(heads)
        assert m.columns["005"] is None
        assert m.columns["012"] == (1, 2)

    def test_facing_page_layout(self):
        # Chrysostom volumes: Greek and Latin pages carry the same two columns.
        heads = []
        for i in range(40):
            p, col = 20 + i, 533 + 2 * (i // 2)
            heads.append((f"{p:03d}", [col] if i % 3 == 0 else []))
        m = oc.map_columns(heads)
        assert m.columns["020"] == (533, 534)
        assert m.columns["030"] == (543, 544)

    def test_no_evidence(self):
        m = oc.map_columns([("010", []), ("011", [8])])
        assert m.columns == {"010": None, "011": None}
        assert m.support_ratio == 0.0


# ---------------------------------------------------------------------------
# Index CSV
# ---------------------------------------------------------------------------

class TestParseIndex:
    def test_end_defaults_to_next_start(self):
        idx = _index(
            "vol-045,b,115,,Gregory of Nyssa,Quod non sint tres dii,3139,,,,,elenchus,,",
            "vol-045,a,9,,Gregory of Nyssa,Oratio catechetica,3150,385,380,390,approximate,"
            "elenchus,,",
            "vol-045,c,135,140,Gregory of Nyssa,Ad Simplicium,,,,,,heads,,",
        )
        rows = idx["vol-045"]
        assert [r.slug for r in rows] == ["a", "b", "c"]
        assert rows[0].col_end == 114 and rows[1].col_end == 134 and rows[2].col_end == 140
        assert rows[0].date_range == (380, 390) and rows[0].date_composed == 385
        assert rows[1].date_range is None

    def test_last_row_open_ended(self):
        rows = _index("vol-045,a,9,,X,T,,,,,,elenchus,,")["vol-045"]
        assert rows[0].col_end is None

    @pytest.mark.parametrize("row,msg", [
        ("vol-045,a,9,,X,T,,,,,,guess,,", "basis"),
        ("vol-045,a,,,X,T,,,,,,elenchus,,", "col_start"),
        ("vol-045,A,9,,X,T,,,,,,elenchus,,", "slug"),
        ("vol-045,other,9,,X,T,,,,,,elenchus,,", "slug"),
        ("vol-045,a,9,,X,T,,500,300,400,,elenchus,,", "date_composed"),
        ("vol-045,a,9,,X,T,,,300,,,elenchus,,", "date range"),
        ("vol-045,a,9,8,X,T,,,,,,elenchus,,", "before it starts"),
    ])
    def test_rejects_bad_rows(self, row: str, msg: str):
        with pytest.raises(pgi.OgpgIndexError, match=msg):
            _index(row)

    def test_rejects_overlap_and_duplicates(self):
        with pytest.raises(pgi.OgpgIndexError, match="overlaps"):
            _index("vol-045,a,9,120,X,T,,,,,,elenchus,,", "vol-045,b,115,,X,T,,,,,,elenchus,,")
        with pytest.raises(pgi.OgpgIndexError, match="duplicate"):
            _index("vol-045,a,9,,X,T,,,,,,elenchus,,", "vol-045,a,15,,X,T,,,,,,elenchus,,")

    def test_out_of_period_row(self):
        rows = _index("vol-003,pach,700,,George Pachymeres,Paraphrasis,,1290,1280,1300,"
                      "approximate,elenchus,,")["vol-003"]
        assert not rows[0].in_period


def test_repository_index_is_valid():
    idx = pgi.load_index()
    for vol, rows in idx.items():
        assert vol.startswith("vol-")
        for row in rows:
            assert row.title and row.basis in pgi.BASES


# ---------------------------------------------------------------------------
# Refs and work assignment
# ---------------------------------------------------------------------------

def _p(cols: tuple[int, int] | None, title: str | None = None, stem: str = "100") -> dict:
    return {"stem": stem, "cols": list(cols) if cols else None, "title": title, "text": "t"}


class TestAssignRefs:
    def test_column_and_page_refs(self):
        paras = [_p((9, 10)), _p((9, 10)), _p(None, stem="042"), _p((11, 12))]
        assert pgi.assign_refs(paras, "vol-045") == [
            "ogpg.vol-045.c0009.1", "ogpg.vol-045.c0009.2",
            "ogpg.vol-045.p0042.1", "ogpg.vol-045.c0011.1",
        ]

    def test_recurring_column_continues_numbering(self):
        paras = [_p((9, 10)), _p((11, 12)), _p((9, 10))]
        refs = pgi.assign_refs(paras, "vol-029")
        assert refs[2] == "ogpg.vol-029.c0009.2"
        assert len(set(refs)) == 3


class TestAssignWorks:
    ROWS = _index(
        "vol-045,a,11,,X,A,,,,,,elenchus,,",
        "vol-045,b,16,,X,B,,,,,,elenchus,,",
        "vol-045,c,21,22,X,C,,,,,,elenchus,,",
    )["vol-045"]

    def test_pages_inside_works_and_front_matter(self):
        paras = [_p((7, 8)), _p((11, 12)), _p((13, 14)), _p((23, 24))]
        assert pgi.assign_works(paras, self.ROWS) == [None, 0, 0, None]

    def test_split_at_heading_on_boundary_page(self):
        # Work b starts in col 16, the second column of page (15, 16).
        paras = [_p((15, 16)), _p((15, 16), title="ΠΕΡΙ ΨΥΧΗΣ"), _p((15, 16)), _p((17, 18))]
        assert pgi.assign_works(paras, self.ROWS) == [0, 1, 1, 1]

    def test_boundary_page_without_heading(self):
        # b starts in the second column: the page stays with a.
        assert pgi.assign_works([_p((15, 16)), _p((17, 18))], self.ROWS) == [0, 1]
        # a starts in the first column: the whole page is a's.
        assert pgi.assign_works([_p((11, 12))], self.ROWS) == [0]

    def test_heading_before_first_work_splits_from_remainder(self):
        paras = [_p((9, 10)), _p((11, 12)), _p((11, 12), title="ΛΟΓΟΣ")]
        assert pgi.assign_works(paras, self.ROWS) == [None, None, 0]

    def test_unnumbered_pages_follow_previous_page(self):
        paras = [_p(None), _p((13, 14)), _p(None, stem="200"), _p((17, 18))]
        assert pgi.assign_works(paras, self.ROWS) == [None, 0, 0, 1]

    def test_explicit_end_leaves_gap(self):
        paras = [_p((21, 22)), _p((23, 24))]
        assert pgi.assign_works(paras, self.ROWS) == [2, None]


# ---------------------------------------------------------------------------
# Extraction headings and volume splitting
# ---------------------------------------------------------------------------

CLEAN = ("Ἐν ἀρχῇ ἦν ὁ λόγος, καὶ ὁ λόγος ἦν πρὸς τὸν θεόν. Οὗτος ἦν ἐν ἀρχῇ πρὸς "
         "τὸν θεόν. Πάντα δι’ αὐτοῦ ἐγένετο, καὶ χωρὶς αὐτοῦ ἐγένετο οὐδὲ ἕν.")


class TestTitleLines:
    @pytest.mark.parametrize("line,expected", [
        ("ΠΕΡΙ ΠΑΡΘΕΝΙΑΣ.", True),
        ("ΚΕΦΑΛ. Β’.", True),
        ("ΤΟΥ ΕΝ ΑΓΙΟΙΣ ΠΑΤΡΟΣ ΗΜΩΝ", True),
        ("Ἐν ἀρχῇ ἦν ὁ λόγος", False),
        ("DE VIRGINITATE", False),
        ("ΑΒ", False),
    ])
    def test_is_title_line(self, line: str, expected: bool):
        assert ogpg._is_title_line(line) is expected

    def test_heading_attached_to_following_paragraph(self):
        pages = [("010", f"{CLEAN}\n\nΠΕΡΙ ΨΥΧΗΣ.\n{CLEAN}"), ("011", CLEAN)]
        cands = ogpg._extract_candidates(pages)
        assert [(c.stem, c.title) for c in cands] == [
            ("010", None), ("010", "ΠΕΡΙ ΨΥΧΗΣ."), ("011", None)]

    def test_headings_do_not_change_paragraphs(self):
        with_heading = f"{CLEAN}\nΠΕΡΙ ΨΥΧΗΣ.\n{CLEAN}"
        cands = ogpg._extract_candidates([("010", with_heading)])
        assert [c.text for c in cands] == [CLEAN, CLEAN]


def _extract(heads: list[tuple[str, list[int]]], paras: list[tuple[str, str | None]]) -> dict:
    return {
        "repo": "Vol.-45",
        "pipeline": {"id": {}, "primary_scan": "nnc1.x_ocr"},
        "page_heads": heads,
        "paragraphs": [{"stem": s, "title": t, "text": f"text {i}"}
                       for i, (s, t) in enumerate(paras)],
    }


class TestSplitVolume:
    HEADS = [("010", [9]), ("011", [12]), ("012", [13]), ("013", [16]), ("014", [17])]
    PARAS = [("010", None), ("011", None), ("012", "ΛΟΓΟΣ"), ("013", None), ("014", None)]

    def test_unsplit_volume_is_one_work(self):
        out = ogpg.split_volume("Vol.-45", _extract(self.HEADS, self.PARAS), [])
        assert len(out) == 1
        rel, work, paras = out[0]
        assert rel == "vol-045.json" and work.work_id == "ogpg/vol-045"
        assert paras[0] == {"ref": "ogpg.vol-045.c0009.1", "text": "text 0"}

    def test_split_with_remainder_and_dropped_row(self):
        rows = _index(
            "vol-045,cat,11,14,Gregory of Nyssa,Oratio catechetica,3150,385,380,390,,elenchus,,",
            "vol-045,late,15,,George Pachymeres,Paraphrasis,,1290,1280,1300,,curated,,",
        )["vol-045"]
        out = ogpg.split_volume("Vol.-45", _extract(self.HEADS, self.PARAS), rows)
        by_rel = {rel: (work, paras) for rel, work, paras in out}
        assert set(by_rel) == {"vol-045/cat.json", "vol-045/other.json"}
        work, paras = by_rel["vol-045/cat.json"]
        assert work.work_id == "ogpg/vol-045/cat"
        assert work.title == "Oratio catechetica" and work.date_range == (380, 390)
        assert "cols. 11–14" in (work.edition or "") and "CPG 3150" in (work.edition or "")
        assert [p["text"] for p in paras] == ["text 1", "text 2"]
        other, rest = by_rel["vol-045/other.json"]
        assert other.work_id == "ogpg/vol-045/other" and other.author is None
        assert [p["text"] for p in rest] == ["text 0"]     # front matter; "late" is dropped

    def test_missing_dates_fall_back_to_volume(self):
        rows = _index("vol-045,cat,9,,Gregory of Nyssa,Oratio catechetica,,,,,,elenchus,,"
                      )["vol-045"]
        (_, work, _), = ogpg.split_volume("Vol.-45", _extract(self.HEADS, self.PARAS), rows)
        assert work.date_range == (370, 395) and work.date_confidence == "established"


def test_prune_removes_stale_files(tmp_path: Path):
    for rel in ("vol-045.json", "vol-045/a.json", "vol-046.json", "_extract/vol-045.json",
                "_volumes.json"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text("{}")
    ogpg._prune(tmp_path, {"vol-045/a.json"}, {"vol-045"})
    assert sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*.json")) == [
        "_extract/vol-045.json", "_volumes.json", "vol-045/a.json", "vol-046.json"]


def test_web_redirects_list_exactly_the_split_volumes():
    """Old ``/works/ogpg/vol-NNN`` URLs of split volumes redirect (web/src/lib/redirects.ts)."""
    import re

    ts = (Path(__file__).parents[1] / "web" / "src" / "lib" / "redirects.ts").read_text()
    block = ts[ts.index("SPLIT_OGPG_VOLUMES"):]
    block = block[block.index("= ["):block.index("];")]
    assert set(re.findall(r'"(vol-[^"]+)"', block)) == set(pgi.load_index())
