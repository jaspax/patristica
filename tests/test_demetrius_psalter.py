"""Tests for the Psalter of Demetrius ingestor (#337)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from scripts.ingest import demetrius_psalter as dp


def test_join_rejoins_words_broken_at_line_ends() -> None:
    assert dp._join(["въꙁдъ-", "ханемъ і"]) == "въꙁдъханемъ і"
    # the hyphen before a closing bracket: "сл[а-]" / "ва"
    assert dp._join(["сл[а-]", "ва"]) == "сл[а]ва"


def test_join_keeps_an_erasure_inside_a_broken_word() -> None:
    assert dp._join(["полъск- [...]", "ъиѩ"]) == "полъск[...]ъиѩ"


def test_join_drops_line_ends_of_marginal_additions() -> None:
    assert dp._join(["[во]/ꙁ[вахъ] / [къ] тебѣ"]) == "[во]ꙁ[вахъ] [къ] тебѣ"


def test_haplography_hyphen_inside_a_line_is_kept() -> None:
    assert dp._join(["іꙁ-д-рѫкъі грѣшънаго"]) == "іꙁ-д-рѫкъі грѣшънаго"


def test_one_titlo_per_word() -> None:
    assert dp._one_titlo("П҃С҃Л҃М҃Ъ г҃і") == "П҃СЛМЪ г҃і"


def test_editorial_spans() -> None:
    text = "н[е] ідетъ {....} ꙋ<с>та [.]"
    spans = dp._editorial(text)
    assert [text[s:e] for s, e, _ in spans] == ["[е]", "{....}", "<с>", "[.]"]
    assert [k for _, _, k in spans] == ["supplement", "lacuna", "supplement", "lacuna"]


def test_label_regex_reads_cyrillic_a() -> None:
    m = dp._LABEL_RE.match("1а")
    assert m and m.group(2) == "1" and m.group(3) == "а"
    assert dp._LABEL_RE.match("108.1").groups() == ("108", "1", "")


RAW = Path(__file__).resolve().parents[1] / "data" / "raw" / dp.SOURCE_ID / "Ps.json"


def _raw() -> dict:
    if not RAW.exists() or RAW.read_bytes().startswith(b"version https://git-lfs"):
        pytest.skip(f"data/raw/{dp.SOURCE_ID} not materialized")
    return json.loads(RAW.read_text(encoding="utf-8"))


def test_ingested_psalter_is_whole_and_in_order() -> None:
    verses = _raw()["verses"]
    keys = [tuple(int(x) for x in v["ref"].split(".")[1:]) for v in verses]
    assert keys == sorted(keys) and len(set(keys)) == len(keys)
    assert {p for p, _ in keys} == set(range(1, dp.PSALMS + 1))
    assert len(verses) > 2500


def test_ingested_psalter_has_no_layout_leftovers() -> None:
    for v in _raw()["verses"]:
        # verse labels, line numbers, folios and Latin letters of the layout
        assert not re.search(r"[0-9A-Za-z/⁄]", v["text"]), v
        assert v["text"] == v["text"].strip() and "  " not in v["text"], v
        for s, e, kind in v.get("editorial", []):
            assert v["text"][s] in "[<{" and v["text"][e - 1] in "]>}", v
