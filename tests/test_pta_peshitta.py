"""Tests for the Peshitta ingestor's word breaks from the ETCBC plain text (#60)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from lxml import etree

from scripts.ingest import pta_peshitta as pp

# Jer 33:10, wrapped in ETCBC's plain text; PTA joined the wrap (ܐܢܫܐܘܡܢ).
ETCBC = """Chapter 33

10 ܚܪܒ ܗܘ ܡܢ ܒ̈ܢܝ ܐܢܫܐ
ܘܡܢ ܒܠܝ ܒܥܝܪܐ ܘܡܢ
ܒܠܝ ܕܝܬܒ
11 ܩܠܐ ܕܚܕܘܬܐ
"""

TEI = """<TEI xmlns="http://www.tei-c.org/ns/1.0"><text><body><div type="edition">
<div type="textpart" subtype="chapter" n="33">
  <div type="textpart" subtype="verse" n="10">
    <p>ܚܪܒ ܗܘ ܡܢ ܒ̈ܢܝ ܐܢܫܐܘܡܢ ܒܠܝ ܒܥܝܪܐ ܘܡܢܒܠܝ ܕܝܬܒ</p></div>
  <div type="textpart" subtype="verse" n="11"><p>ܩܠܐ ܕܚܕܘܬܐ</p></div>
  <div type="textpart" subtype="verse" n="12"><p>ܬܘܒ ܢܗܘܐ</p></div>
</div></div></body></text></TEI>"""


def test_parse_etcbc_plain_joins_wrapped_lines() -> None:
    verses = pp.parse_etcbc_plain(ETCBC)
    assert verses[("33", "10")] == ["ܚܪܒ ܗܘ ܡܢ ܒ̈ܢܝ ܐܢܫܐ", "ܘܡܢ ܒܠܝ ܒܥܝܪܐ ܘܡܢ", "ܒܠܝ ܕܝܬܒ"]
    assert verses[("33", "11")] == ["ܩܠܐ ܕܚܕܘܬܐ"]


def test_parse_etcbc_plain_rejects_repeated_verse() -> None:
    with pytest.raises(ValueError, match="twice"):
        pp.parse_etcbc_plain("Chapter 1\n1 ܐ\n1 ܒ\n")


def test_restore_word_breaks_splits_at_wraps() -> None:
    lines = ["ܐܢܫܐ", "ܘܡܢ ܒܠܝ"]
    assert pp.restore_word_breaks("ܐܢܫܐܘܡܢ ܒܠܝ", lines, "Jer.33.10") == ("ܐܢܫܐ ܘܡܢ ܒܠܝ", True)
    assert pp.restore_word_breaks("ܐܢܫܐ ܘܡܢ ܒܠܝ", lines, "Jer.33.10") == ("ܐܢܫܐ ܘܡܢ ܒܠܝ", False)


def test_restore_word_breaks_keeps_pta_on_mismatch(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR):
        assert pp.restore_word_breaks("ܐܢܫܐܘܡܢ", ["ܐܢܫܐ", "ܘܡܐ"], "X.1.1") == ("ܐܢܫܐܘܡܢ", False)
        assert pp.restore_word_breaks("ܐܢܫܐ", None, "X.1.2") == ("ܐܢܫܐ", False)
    assert [r.levelname for r in caplog.records] == ["ERROR", "ERROR"]


def test_extract_verses_with_word_breaks(caplog: pytest.LogCaptureFixture) -> None:
    root = etree.fromstring(TEI.encode())
    with caplog.at_level(logging.ERROR):
        verses = pp._extract_verses(root, "Jer", pp.parse_etcbc_plain(ETCBC))
    assert verses == [
        {"ref": "Jer.33.10", "text": "ܚܪܒ ܗܘ ܡܢ ܒ̈ܢܝ ܐܢܫܐ ܘܡܢ ܒܠܝ ܒܥܝܪܐ ܘܡܢ ܒܠܝ ܕܝܬܒ"},
        {"ref": "Jer.33.11", "text": "ܩܠܐ ܕܚܕܘܬܐ"},
        {"ref": "Jer.33.12", "text": "ܬܘܒ ܢܗܘܐ"},  # not in ETCBC: kept, logged
    ]
    assert len(caplog.records) == 1 and "Jer.33.12" in caplog.records[0].getMessage()


def test_extract_verses_without_word_breaks_is_unchanged() -> None:
    root = etree.fromstring(TEI.encode())
    assert pp._extract_verses(root, "Jer")[0]["text"].split()[4] == "ܐܢܫܐܘܡܢ"


def test_every_ot_book_has_an_etcbc_file() -> None:
    ot = {osis for pid, osis, _ in pp._BOOK_MAP if pid not in pp._NT_WORK_IDS}
    assert set(pp.ETCBC_FILES) == ot


RAW = Path(__file__).resolve().parents[1] / "data" / "raw" / "pta-peshitta" / "Jer.json"


def test_ingested_jeremiah_has_its_word_breaks() -> None:
    if not RAW.exists() or RAW.read_bytes().startswith(b"version https://git-lfs"):
        pytest.skip("data/raw/pta-peshitta not materialized")
    verses = {v["ref"]: v["text"] for v in json.loads(RAW.read_text(encoding="utf-8"))["verses"]}
    words = verses["Jer.33.10"].split()
    assert "ܐܢܫܐܘܡܢ" not in words and "ܘܡܢܒܠܝ" not in words
