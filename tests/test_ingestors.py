"""
Tests for M2 scripture ingestor modules and pipeline scripts.

These tests focus on parsing logic (private helpers) without any network I/O.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from scripts.ingest._scrollmapper import _parse_scrollmapper_csv
from scripts.ingest.kjv import _parse_kjv_json, _book_filename
from scripts.ingest.sblgnt import _parse_sblgnt_xml, _ref_from_verse_number_id
from scripts.ingest.lxx_rahlfs import _lxx_ref_to_osis, _build_verse_map
from scripts.normalize import normalize_scripture_work
from scripts.chunk import add_context, _truncate_to_tokens
from scripts.link_translations import link_scripture_translations
from patristica.models import Chunk, Work


# ---------------------------------------------------------------------------
# KJV parser tests
# ---------------------------------------------------------------------------

class TestKjvParser:
    def _book(self, book_name: str, chapters: list[dict]) -> dict:
        return {"book": book_name, "chapters": chapters}

    def _chapter(self, num: str, verses: list[tuple[str, str]]) -> dict:
        return {
            "chapter": num,
            "verses": [{"verse": v, "text": t} for v, t in verses],
        }

    def test_simple_book(self):
        data = self._book("Genesis", [
            self._chapter("1", [("1", "In the beginning..."), ("2", "The earth was formless.")]),
        ])
        verses = _parse_kjv_json(data)
        assert len(verses) == 2
        assert verses[0] == ("Gen.1.1", "In the beginning...")
        assert verses[1] == ("Gen.1.2", "The earth was formless.")

    def test_multi_chapter(self):
        data = self._book("Matthew", [
            self._chapter("1", [("1", "The book of genealogy...")]),
            self._chapter("2", [("1", "Now after Jesus was born...")]),
        ])
        verses = _parse_kjv_json(data)
        assert len(verses) == 2
        assert verses[0][0] == "Matt.1.1"
        assert verses[1][0] == "Matt.2.1"

    def test_unknown_book_returns_empty(self):
        data = self._book("Hezekiah", [self._chapter("1", [("1", "Some text")])])
        verses = _parse_kjv_json(data)
        assert verses == []

    def test_empty_text_skipped(self):
        data = self._book("John", [
            self._chapter("1", [("1", "In the beginning was the Word."), ("2", "")]),
        ])
        verses = _parse_kjv_json(data)
        assert len(verses) == 1

    def test_book_filename_override(self):
        assert _book_filename("Song") == "SongofSolomon"

    def test_book_filename_normal(self):
        assert _book_filename("Gen") == "Genesis"


# ---------------------------------------------------------------------------
# SBLGNT parser tests
# ---------------------------------------------------------------------------

class TestSblgntParser:
    def test_ref_from_verse_number_id(self):
        assert _ref_from_verse_number_id("1John", "1 John 1:1") == "1John.1.1"
        assert _ref_from_verse_number_id("Matt", "Matthew 5:3") == "Matt.5.3"
        assert _ref_from_verse_number_id("Rev", "Revelation 22:21") == "Rev.22.21"

    def test_parse_simple_xml(self):
        xml = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <book id="1Jn">
              <title>ΙΩΑΝΝΟΥ Α</title>
              <p>
                <verse-number id="1 John 1:1">1:1</verse-number>
                <w>Ὃ</w><suffix></suffix>
                <w>ἦν</w><suffix></suffix>
                <w>ἀπʼ</w><suffix></suffix>
                <w>ἀρχῆς</w><suffix>,</suffix>
              </p>
            </book>
        """).encode("utf-8")
        verses = _parse_sblgnt_xml(xml, "1John")
        assert len(verses) == 1
        ref, text = verses[0]
        assert ref == "1John.1.1"
        assert "Ὃ" in text
        assert "ἦν" in text
        assert "ἀρχῆς" in text

    def test_parse_multi_verse(self):
        xml = textwrap.dedent("""\
            <?xml version="1.0" encoding="UTF-8"?>
            <book id="Jhn">
              <p>
                <verse-number id="John 1:1">1:1</verse-number>
                <w>Ἐν</w><suffix></suffix>
                <w>ἀρχῇ</w><suffix></suffix>
                <verse-number id="John 1:2">1:2</verse-number>
                <w>οὗτος</w><suffix></suffix>
              </p>
            </book>
        """).encode("utf-8")
        verses = _parse_sblgnt_xml(xml, "John")
        assert len(verses) == 2
        assert verses[0][0] == "John.1.1"
        assert verses[1][0] == "John.1.2"
        assert "Ἐν" in verses[0][1]
        assert "οὗτος" in verses[1][1]


# ---------------------------------------------------------------------------
# Scrollmapper CSV parser tests
# ---------------------------------------------------------------------------

class TestScrollmapperParser:
    def test_basic_csv(self):
        csv_content = "Book,Chapter,Verse,Text\n"
        csv_content += "Genesis,1,1,In the beginning God created\n"
        csv_content += "Genesis,1,2,The earth was formless\n"
        csv_content += "Matthew,1,1,The book of genealogy\n"

        result = _parse_scrollmapper_csv(csv_content.encode(), "scripture/asv")
        assert "Gen" in result
        assert "Matt" in result
        assert len(result["Gen"]) == 2
        assert result["Gen"][0] == ("Gen.1.1", "In the beginning God created")

    def test_unknown_book_skipped(self):
        csv_content = "Book,Chapter,Verse,Text\nHezekiah,1,1,Some text\n"
        result = _parse_scrollmapper_csv(csv_content.encode(), "test")
        assert result == {}

    def test_empty_text_skipped(self):
        csv_content = "Book,Chapter,Verse,Text\nGenesis,1,1,\n"
        result = _parse_scrollmapper_csv(csv_content.encode(), "test")
        assert result == {}


# ---------------------------------------------------------------------------
# LXX Rahlfs parser tests
# ---------------------------------------------------------------------------

class TestLxxRahlfsParser:
    def test_lxx_ref_to_osis_ot(self):
        result = _lxx_ref_to_osis("Gen 1:1")
        assert result == ("Gen", "1", "1")

    def test_lxx_ref_to_osis_ps(self):
        result = _lxx_ref_to_osis("Psalms 22:1")
        assert result == ("Ps", "22", "1")

    def test_lxx_ref_to_osis_invalid(self):
        assert _lxx_ref_to_osis("NotABook 1:1") is None

    def test_build_verse_map(self):
        # word list: words 1-5
        word_lines = ["1\tἐν", "2\tἀρχῇ", "3\tἐποίησεν", "4\tὁ", "5\tθεὸς"]
        # verse index: words 1-3 = Gen 1:1, words 4-5 = Gen 1:2
        verse_lines = ["1\t3\t「Gen 1:1」", "4\t5\t「Gen 1:2」"]
        result = _build_verse_map(word_lines, verse_lines)
        assert "Gen.1.1" in result
        assert "Gen.1.2" in result
        assert result["Gen.1.1"] == ["ἐν", "ἀρχῇ", "ἐποίησεν"]
        assert result["Gen.1.2"] == ["ὁ", "θεὸς"]


# ---------------------------------------------------------------------------
# normalize.py tests
# ---------------------------------------------------------------------------

class TestNormalizeScripture:
    def _raw_record(self, lang="hbo", verses=None):
        if verses is None:
            verses = [{"ref": "Gen.1.1", "text": "In the beginning"}]
        return {
            "work": {
                "work_id": "scripture/test/gen",
                "source_id": "scripture/test",
                "title": "Genesis",
                "genre": "scripture",
                "language": lang,
                "license": "public_domain",
            },
            "verses": verses,
        }

    def test_basic_normalization(self):
        work, chunks = normalize_scripture_work(self._raw_record())
        assert len(chunks) == 1
        c = chunks[0]
        assert c.chunk_id == "scripture/test/gen#Gen.1.1"
        assert c.canonical_ref == "Gen.1.1"
        assert c.text == "In the beginning"
        assert c.chunk_index == 0
        assert c.out_of_period is False

    def test_empty_text_skipped(self):
        raw = self._raw_record(verses=[
            {"ref": "Gen.1.1", "text": "Valid verse"},
            {"ref": "Gen.1.2", "text": "   "},
            {"ref": "Gen.1.3", "text": "Another verse"},
        ])
        _, chunks = normalize_scripture_work(raw)
        assert len(chunks) == 2
        assert all(c.text.strip() for c in chunks)

    def test_chunk_index_sequential(self):
        verses = [{"ref": f"Gen.1.{i}", "text": f"Verse {i}"} for i in range(1, 6)]
        _, chunks = normalize_scripture_work(self._raw_record(verses=verses))
        for i, c in enumerate(chunks):
            assert c.chunk_index == i

    def test_language_inherited_from_work(self):
        _, chunks = normalize_scripture_work(self._raw_record(lang="grc"))
        assert all(c.language == "grc" for c in chunks)


# ---------------------------------------------------------------------------
# chunk.py tests
# ---------------------------------------------------------------------------

class TestAddContext:
    def _make_chunk(self, idx: int, text: str, work_id="test/gen") -> Chunk:
        return Chunk(
            chunk_id=f"{work_id}#ref.1.{idx}",
            work_id=work_id,
            canonical_ref=f"Gen.1.{idx}",
            language="hbo",
            text=text,
            chunk_index=idx,
        )

    def test_single_chunk_no_context(self):
        chunks = [self._make_chunk(0, "Only verse")]
        result = add_context(chunks)
        assert result[0].context_before is None
        assert result[0].context_after is None

    def test_first_chunk_no_before(self):
        chunks = [self._make_chunk(i, f"Verse {i}") for i in range(3)]
        result = add_context(chunks)
        assert result[0].context_before is None
        assert result[0].context_after is not None

    def test_last_chunk_no_after(self):
        chunks = [self._make_chunk(i, f"Verse {i}") for i in range(3)]
        result = add_context(chunks)
        assert result[-1].context_before is not None
        assert result[-1].context_after is None

    def test_middle_chunk_has_both(self):
        chunks = [self._make_chunk(i, f"Verse {i}") for i in range(3)]
        result = add_context(chunks)
        assert result[1].context_before is not None
        assert result[1].context_after is not None

    def test_context_content(self):
        chunks = [
            self._make_chunk(0, "First verse text"),
            self._make_chunk(1, "Second verse text"),
            self._make_chunk(2, "Third verse text"),
        ]
        result = add_context(chunks)
        # Middle chunk's context_before should contain text from first chunk
        assert "First" in result[1].context_before
        # Middle chunk's context_after should contain text from third chunk
        assert "Third" in result[1].context_after

    def test_truncate_to_tokens(self):
        long_text = "word " * 200
        truncated = _truncate_to_tokens(long_text, 50)
        # Truncated version should be much shorter
        assert len(truncated.split()) <= 55  # some slack for tokenization


# ---------------------------------------------------------------------------
# link_translations.py tests
# ---------------------------------------------------------------------------

class TestLinkTranslations:
    def _chunk(self, work_id: str, ref: str, lang: str, idx: int) -> Chunk:
        return Chunk(
            chunk_id=f"{work_id}#{ref}",
            work_id=work_id,
            canonical_ref=ref,
            language=lang,
            text=f"Text in {lang}",
            chunk_index=idx,
        )

    def test_parallel_verses_get_group_id(self):
        chunks = [
            self._chunk("scripture/oshb/gen", "Gen.1.1", "hbo", 0),
            self._chunk("scripture/pta-lxx/gen", "Gen.1.1", "grc", 0),
            self._chunk("scripture/kjv/gen", "Gen.1.1", "eng", 0),
        ]
        result = link_scripture_translations(chunks)
        group_ids = [c.translation_group_id for c in result]
        assert all(g == "Gen.1.1" for g in group_ids)

    def test_singleton_no_group_id(self):
        # Only one language has this verse
        chunks = [self._chunk("scripture/wulfila/mark", "Mark.16.20", "got", 0)]
        result = link_scripture_translations(chunks)
        assert result[0].translation_group_id is None

    def test_mixed_refs(self):
        chunks = [
            self._chunk("scripture/oshb/gen", "Gen.1.1", "hbo", 0),
            self._chunk("scripture/pta-lxx/gen", "Gen.1.1", "grc", 0),
            self._chunk("scripture/oshb/gen", "Gen.1.2", "hbo", 1),
            # Gen.1.2 has only one language → no group
        ]
        result = link_scripture_translations(chunks)
        assert result[0].translation_group_id == "Gen.1.1"
        assert result[1].translation_group_id == "Gen.1.1"
        assert result[2].translation_group_id is None

    def test_original_chunks_unchanged(self):
        """link_scripture_translations must not mutate input."""
        chunks = [
            self._chunk("scripture/oshb/gen", "Gen.1.1", "hbo", 0),
            self._chunk("scripture/pta-lxx/gen", "Gen.1.1", "grc", 0),
        ]
        original_ids = [id(c) for c in chunks]
        result = link_scripture_translations(chunks)
        # Result should be new objects
        result_ids = [id(c) for c in result]
        assert result_ids != original_ids

    def test_psalms_grouped_across_versifications(self):
        # Heb/Eng Ps 23 ("The LORD is my shepherd") = LXX/Vulgate Ps 22;
        # LXX Ps 23 ("The earth is the Lord's") = Heb Ps 24.
        chunks = [
            self._chunk("scripture/kjv/ps", "Ps.23.1", "eng", 0),
            self._chunk("scripture/pta-lxx/ps", "Ps.22.1", "grc", 0),
            self._chunk("scripture/clementine/ps", "Ps.22.1", "lat", 0),
            self._chunk("scripture/pta-lxx/ps", "Ps.23.1", "grc", 1),
        ]
        result = link_scripture_translations(chunks)
        assert [c.translation_group_id for c in result] == ["Ps.23.1", "Ps.23.1", "Ps.23.1", None]

    def test_english_psalm_titles_offset(self):
        # English Bibles leave the title unnumbered: KJV Ps 3:1 = Hebrew Ps 3:2.
        chunks = [
            self._chunk("scripture/kjv/ps", "Ps.3.1", "eng", 0),
            self._chunk("scripture/oshb/ps", "Ps.3.2", "hbo", 1),
        ]
        result = link_scripture_translations(chunks)
        assert {c.translation_group_id for c in result} == {"Ps.3.2"}

    def test_unregistered_source_raises(self):
        from patristica.versification import VersificationError
        with pytest.raises(VersificationError):
            link_scripture_translations([self._chunk("scripture/nope/gen", "Gen.1.1", "eng", 0)])
