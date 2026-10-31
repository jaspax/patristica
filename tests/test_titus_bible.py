# ruff: noqa: E501
"""Tests for the TITUS Old Georgian Bible ingestor (scripts/ingest/_titus_bible.py, #515). No network."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from scripts.ingest import _common, _titus
from scripts.ingest import _titus_bible as B

FRAME = '<frameset><frame src="tst001.htm"\nname="etatext"\nscrolling="auto"></frameset>'

PAGE = """<BODY>
<span id=textdescr>On the basis of the edition by</span><span id=bibliogr>K. Ʒoc̣eniʒe, Tbilisi 1974</span><span id=n16>
<BR>TITUS version by Jost Gippert,
<BR>Frankfurt a/M, 1.6.2000
<BR><span id=h2><!Level 2>Book: 2.Jo.<A NAME="a">&nbsp;</A></sPAN>
<BR></span><span id=mxag22>იოვანესი</span><span id=n16>
<BR><span id=h3><!Level 3>Chapter: _<A NAME="b">&nbsp;</A></sPAN>
<BR><span id=h4><!Level 4>Verse: 1<A NAME="c">&nbsp;</A></sPAN>&nbsp;</span><span id=mxag16>ხუცესი [რჩეულსა] დედოფალსა</span><span id=n16>
<BR><span id=h4><!Level 4>Verse: 1V<A NAME="d">&nbsp;</A></sPAN>&nbsp;</span><span id=mxags12>რჩეულისა</span><span id=n16>
<BR><span id=h4><!Level 4>Verse: 2,<A NAME="e">&nbsp;</A></sPAN>&nbsp;</span><span id=mxag16>ჭეშმარიტებისათჳს ...</span><span id=n16>
<BR><span id=h2><!Level 2>Book: Od.<A NAME="f">&nbsp;</A></sPAN>
<BR><span id=h3><!Level 3>Chapter: 9a_(Lk._1)<A NAME="g">&nbsp;</A></sPAN>
<BR><span id=h4><!Level 4>Verse: 46<A NAME="h">&nbsp;</A></sPAN>&nbsp;</span><span id=mxag16>ადიდებს სული ჩემი უფალსა</span><span id=n16>
<BR><span id=h3><!Level 3>Chapter: 9b_(Lk._1)<A NAME="i">&nbsp;</A></sPAN>
<BR><span id=h4><!Level 4>Verse: 68<A NAME="j">&nbsp;</A></sPAN>&nbsp;</span><span id=mxag16>კურთხეულ არს უფალი</span><span id=n16>
<HR><BR>This text is part of the TITUS edition.
<BR>Copyright <A HREF="javascript:mm('TITUS')">TITUS Project</A>,
Frankfurt a/M, 3.11.2005.
</BODY>"""


@pytest.mark.parametrize(("label", "osis"), [
    ("Mt.", "Matt"), ("1.Petr.", "1Pet"), ("1Petr.", "1Pet"), ("Ap.Jo.", "Rev"), ("Jac.", "Jas"), ("Od.", "Odes"),
])
def test_book_labels(label: str, osis: str) -> None:
    assert B.TITUS_BOOKS[B.book_key(label)] == osis


@pytest.mark.parametrize(("chapter", "verse", "expected"), [
    ("1", "1", (1, "1")), ("13", "7,", (13, "7")), ("_", "3", (1, "3")),
    ("1_(Ex._15)", "1", (1, "1")), ("9b_(Lk._1)", "68", (9, "68")), ("1", "1V", None),
    ("2", "35a", (2, "35a")), ("5", "35-01", (5, "35")), ("6", "10rb)atimd", (6, "10")),
    ("3", "9*", (3, "9")), ("1", "3_(4)", (1, "3")),
])
def test_chapter_verse(chapter: str, verse: str, expected: tuple[int, str] | None) -> None:
    assert B.chapter_verse(chapter, verse) == expected


def test_ingest_bible_from_cache(tmp_path: Path) -> None:
    base = "https://titus.uni-frankfurt.de/texte/etcs/test/"
    for name, body in (("tst.htm", FRAME), ("tst001.htm", PAGE)):
        dest = _titus.cache_path(base + name, tmp_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(gzip.compress(body.encode()))
    spec = B.BibleSet(source_id="titus-test", set_path="etcs/test/tst.htm",
                      witness="test redaction", date_range=(450, 1000))
    with _common.offline_mode():
        works = B.ingest_bible(spec, tmp_path, force=True)
    assert [w.work_id for w in works] == ["titus-test/2john", "titus-test/odes"]
    w = works[0]
    assert w.license == _titus.TITUS_LICENSE == "unknown"
    assert w.language == "oge" and w.genre == "scripture" and w.tradition == "georgian"
    assert w.provenance_url == base + "tst.htm"
    assert w.edition == ("TITUS (ed. Jost Gippert), after K. Ʒoc̣eniʒe, Tbilisi 1974 (test redaction); "
                         "last changed 2005-11-03")
    raw = json.loads((tmp_path / "titus-test" / "2john.json").read_text())
    assert raw["verses"] == [
        {"ref": "2John.1.1", "text": "ხუცესი [რჩეულსა] დედოფალსა", "editorial": [[7, 16, "supplement"]]},
        {"ref": "2John.1.2", "text": "ჭეშმარიტებისათჳს ...", "editorial": [[17, 20, "lacuna"]]},
    ]
    odes = json.loads((tmp_path / "titus-test" / "odes.json").read_text())
    assert [v["ref"] for v in odes["verses"]] == ["Odes.9.46", "Odes.9.68"]


@pytest.mark.parametrize("label", ["1V", "30-31V", "10VV", "8.V", "16Ⴅ", "22X", "h1", "h2-1N", "col", "7-1Q", "3a-1N"])
def test_lines_beside_the_verse_are_skipped(label: str) -> None:
    assert B._VARIANT_RE.match(label)
    assert not B._VARIANT_RE.match("16")


def test_join_unit_shifts_spans() -> None:
    rec: dict[str, object] = {"ref": "Rom.12.16", "text": "ა [ბ]", "editorial": [[2, 5, "supplement"]]}
    B.join_unit(rec, _titus.Unit(key=(), loc={}, text="გ [დ]", editorial=[[2, 5, "supplement"]]))
    assert rec == {"ref": "Rom.12.16", "text": "ა [ბ] გ [დ]",
                   "editorial": [[2, 5, "supplement"], [8, 11, "supplement"]]}
