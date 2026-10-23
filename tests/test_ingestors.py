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
# OSHB (morphhb) parser tests
# ---------------------------------------------------------------------------

class TestOshbParser:
    # Gen 1:1 word text as in morphhb wlc/Gen.xml; the other "verses" combine real
    # morphhb words (some verses abridged from the real ones) to exercise suffix
    # separators, maqqef, paseq, nested <seg> letters and ketiv/qere notes.
    _XML = textwrap.dedent("""\
        <?xml version="1.0" encoding="utf-8"?>
        <osis xmlns="http://www.bibletechnologies.net/2003/OSIS/namespace">
        <osisText><div type="book" osisID="Gen"><chapter osisID="Gen.1">
          <verse osisID="Gen.1.1">
            <w lemma="b/7225" morph="HR/Ncfsa" id="01xeN">בְּ/רֵאשִׁ֖ית</w>
            <w lemma="1254 a" morph="HVqp3ms" id="01Nvk">בָּרָ֣א</w>
            <w lemma="430" morph="HNcmpa" id="01TyA">אֱלֹהִ֑ים</w>
            <w lemma="853" morph="HTo" id="01MAO">אֵ֥ת</w>
            <w lemma="d/8064" morph="HTd/Ncmpa" id="01uQ6">הַ/שָּׁמַ֖יִם</w>
            <w lemma="c/853" morph="HC/To" id="01EtS">וְ/אֵ֥ת</w>
            <w lemma="d/776" morph="HTd/Ncbsa" id="01Eoc">הָ/אָֽרֶץ</w>
            <seg type="x-sof-pasuq">׃</seg>
          </verse>
          <verse osisID="Gen.4.4">
            <w lemma="854" morph="HR/Sp2fs" id="018F2">אִתָּ֑/ךְ</w>
            <w lemma="5921 a" morph="HR" id="01cPC">עַל</w><seg type="x-maqqef">־</seg><w lemma="d/776" morph="HTd/Ncbsa" id="01Eod">הָ/אָ֖רֶץ</w>
          </verse>
          <verse osisID="Num.27.7">
            <w lemma="4941" morph="HNcmsc/Sp3fp" id="04DbS">מִשְׁפָּטָ֖/<seg type="x-large">ן</seg></w>
            <w lemma="7563" morph="HAampa" id="18wyD">רְשָׁ<seg type="x-suspended">עִ֣</seg>ים</w>
          </verse>
          <verse osisID="Gen.8.17">
            <w type="x-ketiv" lemma="3318" morph="HVhv2ms" id="01Pdv">אהל/ה</w><note type="variant"><catchWord>אהל/ה</catchWord><rdg type="x-qere"><w lemma="168" morph="HNcmsc/Sp3ms" id="01Gdj">אָֽהֳל/וֹ֙</w></rdg></note>
          </verse>
          <verse osisID="1Chr.1.11">
            <w lemma="3205" morph="HVqp3ms" id="13Xw6">יָלַ֞ד</w>
            <w lemma="853" morph="HTo" id="13eHJ">אֶת</w><seg type="x-maqqef">־</seg><w type="x-ketiv" lemma="3866" morph="HNp" id="13H6L">לודיים</w><note type="variant"><catchWord>לודיים</catchWord><rdg type="x-qere"><w lemma="3866" morph="HNp" id="13bmv">לוּדִ֧ים</w></rdg></note>
            <w lemma="c/853" morph="HC/To" id="13FV9">וְ/אֶת</w><seg type="x-maqqef">־</seg><w lemma="6047" morph="HNp" id="13Xm1">עֲנָמִ֛ים</w><seg type="x-sof-pasuq">׃</seg>
          </verse>
          <verse osisID="1Kgs.1.9">
            <w lemma="c/7121" morph="HC/Vqw3ms" id="11V27">וַ/יִּקְרָ֗א</w>
            <w lemma="853" morph="HTo" id="11ifp">אֶת</w><seg type="x-maqqef">־</seg><w lemma="3605" morph="HNcmsc" id="117ZG">כָּל</w><seg type="x-maqqef">־</seg><w lemma="251" morph="HNcmpc/Sp3ms" id="11B2d">אֶחָי/ו֙</w>
            <w lemma="1121 a" morph="HNcmpc" id="11ewe">בְּנֵ֣י</w>
          </verse>
          <verse osisID="2Sam.8.3">
            <w lemma="b/3212" morph="HR/Vqc/Sp3ms" id="108Vg">בְּ/לֶכְתּ֕/וֹ</w>
            <w lemma="b/5104" morph="HR/Ncmsc" id="10BJi">בִּֽ/נְהַר</w><seg type="x-maqqef">־</seg><note type="variant"><rdg type="x-qere"><w lemma="6578" morph="HNp" id="10dp9">פְּרָֽת</w></rdg></note><seg type="x-sof-pasuq">׃</seg>
            <note n="a">Adaptations to a Qere which L and BHS, by their design, do not indicate. </note>
          </verse>
          <verse osisID="Gen.1.5">
            <w lemma="430" morph="HNcmpa" id="01kfX">אֱלֹהִ֤ים</w>
            <seg type="x-paseq">׀</seg>
            <w lemma="l/216" morph="HRd/Ncbsa" id="01Wkf">לָ/אוֹר֙</w>
            <w lemma="c/1961" morph="HC/Vqw3ms" id="01Y3z">וַֽ/יְהִי</w><seg type="x-maqqef">־</seg><w lemma="6153" morph="HNcmsa" id="01NQN">עֶ֥רֶב</w>
            <w lemma="259" morph="HAcmsa" id="01NFp">אֶחָֽד</w><seg type="x-sof-pasuq">׃</seg>
          </verse>
        </chapter></div></osisText></osis>
        """).encode("utf-8")

    def _verses(self) -> dict[str, str]:
        from scripts.ingest.oshb import _parse_oshb_xml
        return dict(_parse_oshb_xml(self._XML))

    def test_morpheme_separators_stripped(self) -> None:
        verses = self._verses()
        assert verses["Gen.1.1"] == "בְּרֵאשִׁ֖ית בָּרָ֣א אֱלֹהִ֑ים אֵ֥ת הַשָּׁמַ֖יִם וְאֵ֥ת הָאָֽרֶץ"
        assert all("/" not in text for text in verses.values())

    def test_suffix_separator_and_maqqef(self) -> None:
        # A maqqef binds both neighbours into one word: no space on either side (#54).
        assert self._verses()["Gen.4.4"] == "אִתָּ֑ךְ עַל־הָאָ֖רֶץ"

    def test_maqqef_before_ketiv(self) -> None:
        # The ketiv after a maqqef attaches; the qere note in between is skipped.
        assert self._verses()["1Chr.1.11"] == "יָלַ֞ד אֶת־לודיים וְאֶת־עֲנָמִ֛ים"

    def test_chained_maqqefs(self) -> None:
        assert self._verses()["1Kgs.1.9"] == "וַיִּקְרָ֗א אֶת־כָּל־אֶחָיו֙ בְּנֵ֣י"

    def test_maqqef_at_verse_end(self) -> None:
        # 2Sam 8:3 ends in a qere-only word (no ketiv), so the maqqef is the last
        # character of the running text, with no trailing space.
        assert self._verses()["2Sam.8.3"] == "בְּלֶכְתּ֕וֹ בִּֽנְהַר־"

    def test_paseq_spaced_and_sof_pasuq_dropped(self) -> None:
        # Paseq stands between spaces as in morphhb; sof pasuq is omitted.
        assert self._verses()["Gen.1.5"] == "אֱלֹהִ֤ים ׀ לָאוֹר֙ וַֽיְהִי־עֶ֥רֶב אֶחָֽד"

    def test_nested_seg_letters_kept(self) -> None:
        # Large / suspended letters are <seg> children of <w>; they must not be dropped.
        assert self._verses()["Num.27.7"] == "מִשְׁפָּטָ֖ן רְשָׁעִ֣ים"

    def test_ketiv_note_not_included(self) -> None:
        # The qere reading inside <note> is not part of the running text (yet).
        assert self._verses()["Gen.8.17"] == "אהלה"


# ---------------------------------------------------------------------------
# Scrollmapper CSV parser tests
# ---------------------------------------------------------------------------

class TestScrollmapperParser:
    def test_basic_csv(self):
        csv_content = "Book,Chapter,Verse,Text\n"
        csv_content += "Genesis,1,1,In the beginning God created\n"
        csv_content += "Genesis,1,2,The earth was formless\n"
        csv_content += "Matthew,1,1,The book of genealogy\n"

        result = _parse_scrollmapper_csv(csv_content.encode(), "asv")
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

    def test_null_text_skipped(self):
        """CopSahBible2 spells a missing verse ``null`` (#187); a book of nulls is absent."""
        csv_content = "Book,Chapter,Verse,Text\nJude,1,1,null\nJude,1,2,NULL</ab>\n"
        csv_content += "Genesis,1,1,null\nGenesis,1,2,ⲁⲩⲱ\n"
        result = _parse_scrollmapper_csv(csv_content.encode(), "test")
        assert result == {"Gen": [("Gen.1.2", "ⲁⲩⲱ")]}

    def test_asv_psalm_titles_get_their_own_unit(self):
        """The ASV CSV starts Ps N:1 with the title; it becomes Ps.N.0 (#220)."""
        from scripts.ingest.asv import split_psalm_titles

        verses = [
            ("Ps.1.1", "Blessed is the man that walketh not in the counsel of the wicked,"),
            ("Ps.3.1", "A Psalm of David, when he fled from Absalom his son. Jehovah, how are"
                       " mine adversaries increased!"),
            ("Ps.3.2", "Many there are that say of my soul,"),
            ("Ps.4.1", "For the Chief Musician; on stringed instruments. A Psalm of David."
                       " Answer me when I call."),
            ("Ps.18.1", "For the Chief Musician. A Psalm of David the servant of Jehovah, who"
                        " spake unto Jehovah the words of this song in the day that Jehovah"
                        " delivered him from the hand of all his enemies, and from the hand of"
                        " Saul: and he said, I love thee, O Jehovah, my strength."),
            ("Ps.54.1", "For the Chief Musician; on stringed instruments. Maschil of David; when"
                        " the Ziphites came and said to Saul, Doth not David hide himself with"
                        " us? Save me, O God, by thy name,"),
        ]
        out = dict(split_psalm_titles("Ps", verses))
        assert "Ps.1.0" not in out
        assert out["Ps.3.0"] == "A Psalm of David, when he fled from Absalom his son."
        assert out["Ps.3.1"] == "Jehovah, how are mine adversaries increased!"
        assert out["Ps.4.0"] == "For the Chief Musician; on stringed instruments. A Psalm of David."
        assert out["Ps.18.1"] == "I love thee, O Jehovah, my strength."  # from the title table
        assert out["Ps.54.0"].endswith("Doth not David hide himself with us?")
        assert [r for r, _ in split_psalm_titles("Ps", verses)][:4] == [
            "Ps.1.1", "Ps.3.0", "Ps.3.1", "Ps.3.2"]
        assert split_psalm_titles("Hab", [("Hab.3.19", "A Psalm.")]) == [("Hab.3.19", "A Psalm.")]

    def test_asv_title_table_must_match(self):
        from scripts.ingest.asv import split_psalm_title

        with pytest.raises(ValueError):
            split_psalm_title("Ps.18.1", "I love thee, O Jehovah, my strength.")
        with pytest.raises(ValueError):
            split_psalm_title("Ps.98.1", "A Psalm.")

    def test_xml_tags_stripped_editorial_brackets_kept(self):
        """TEI residue goes; CopSahBible2's <…> editorial supplements are text (#220)."""
        csv_content = (
            "Book,Chapter,Verse,Text\n"
            'Genesis,5,4,ⲥⲁϣϥⲉ <ⲛϣⲉ> ⲛⲣⲟⲙⲡⲉ <gap reason="lost"/></ab>\n'
        )
        result = _parse_scrollmapper_csv(csv_content.encode(), "test")
        assert result == {"Gen": [("Gen.5.4", "ⲥⲁϣϥⲉ <ⲛϣⲉ> ⲛⲣⲟⲙⲡⲉ")]}

    def test_book_without_text_removed_from_raw(self, tmp_path, monkeypatch):
        from scripts.ingest import _scrollmapper

        (tmp_path / "_csvs").mkdir()
        (tmp_path / "_csvs" / "T.csv").write_text(
            "Book,Chapter,Verse,Text\nJude,1,1,null\nGenesis,1,1,In the beginning\n",
            encoding="utf-8")
        monkeypatch.setattr(_scrollmapper, "download_file", lambda url, dest, force=False: dest)
        (tmp_path / "t").mkdir()
        (tmp_path / "t" / "Jude.json").write_text("{}", encoding="utf-8")  # from an older run
        works = _scrollmapper.ingest_scrollmapper(
            tmp_path, "T", "t", "eng", "public_domain", "Test", force=False)
        assert [w.work_id for w in works] == ["t/gen"]
        assert sorted(p.name for p in (tmp_path / "t").iterdir()) == ["Gen.json"]


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
                "work_id": "test/gen",
                "source_id": "test",
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
        assert c.chunk_id == "test/gen#Gen.1.1"
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
            self._chunk("oshb/gen", "Gen.1.1", "hbo", 0),
            self._chunk("pta-lxx/gen", "Gen.1.1", "grc", 0),
            self._chunk("kjv/gen", "Gen.1.1", "eng", 0),
        ]
        result = link_scripture_translations(chunks)
        group_ids = [c.translation_group_id for c in result]
        assert all(g == "Gen.1.1" for g in group_ids)

    def test_singleton_no_group_id(self):
        # Only one language has this verse
        chunks = [self._chunk("wulfila/mark", "Mark.16.20", "got", 0)]
        result = link_scripture_translations(chunks)
        assert result[0].translation_group_id is None

    def test_mixed_refs(self):
        chunks = [
            self._chunk("oshb/gen", "Gen.1.1", "hbo", 0),
            self._chunk("pta-lxx/gen", "Gen.1.1", "grc", 0),
            self._chunk("oshb/gen", "Gen.1.2", "hbo", 1),
            # Gen.1.2 has only one language → no group
        ]
        result = link_scripture_translations(chunks)
        assert result[0].translation_group_id == "Gen.1.1"
        assert result[1].translation_group_id == "Gen.1.1"
        assert result[2].translation_group_id is None

    def test_original_chunks_unchanged(self):
        """link_scripture_translations must not mutate input."""
        chunks = [
            self._chunk("oshb/gen", "Gen.1.1", "hbo", 0),
            self._chunk("pta-lxx/gen", "Gen.1.1", "grc", 0),
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
            self._chunk("kjv/ps", "Ps.23.1", "eng", 0),
            self._chunk("pta-lxx/ps", "Ps.22.1", "grc", 0),
            self._chunk("clementine/ps", "Ps.22.1", "lat", 0),
            self._chunk("pta-lxx/ps", "Ps.23.1", "grc", 1),
        ]
        result = link_scripture_translations(chunks)
        assert [c.translation_group_id for c in result] == ["Ps.23.1", "Ps.23.1", "Ps.23.1", None]

    def test_english_psalm_titles_offset(self):
        # English Bibles leave the title unnumbered: KJV Ps 3:1 = Hebrew Ps 3:2.
        chunks = [
            self._chunk("kjv/ps", "Ps.3.1", "eng", 0),
            self._chunk("oshb/ps", "Ps.3.2", "hbo", 1),
        ]
        result = link_scripture_translations(chunks)
        assert {c.translation_group_id for c in result} == {"Ps.3.2"}

    def test_unregistered_source_raises(self):
        from patristica.versification import VersificationError
        with pytest.raises(VersificationError):
            link_scripture_translations([self._chunk("nope/gen", "Gen.1.1", "eng", 0)])

    def test_link_all_selects_works_by_genre(self, tmp_path: Path):
        """Only works whose Work.genre is scripture are linked, whatever their
        source (#74): a patristic work from a Bible source keeps None."""
        from scripts.link_translations import link_all

        chunks_dir = tmp_path / "chunks"
        files = {
            "oshb/Gen.json": [self._chunk("oshb/gen", "Gen.1.1", "hbo", 0)],
            "kjv/Gen.json": [self._chunk("kjv/gen", "Gen.1.1", "eng", 0)],
            # Ge'ez Clement: genre patristic, refs that are not Bible books.
            "gez/clem.json": [self._chunk("gez/clem", "Gen.1.1", "gez", 0)],
        }
        for rel, chunks in files.items():
            (chunks_dir / rel).parent.mkdir(parents=True, exist_ok=True)
            (chunks_dir / rel).write_text(json.dumps([c.model_dump() for c in chunks]))
        works = tmp_path / "_works.jsonl"
        works.write_text("".join(
            json.dumps({"path": rel, "work": {"genre": genre}}) + "\n"
            for rel, genre in (("oshb/Gen.json", "scripture"), ("kjv/Gen.json", "scripture"),
                               ("gez/clem.json", "patristic"))
        ))

        assert link_all(chunks_dir, works) == 2
        group = lambda rel: json.loads((chunks_dir / rel).read_text())[0]["translation_group_id"]
        assert group("oshb/Gen.json") == group("kjv/Gen.json") == "Gen.1.1"
        assert group("gez/clem.json") is None


# ---------------------------------------------------------------------------
# normalize_all: source-first layout (#102)
# ---------------------------------------------------------------------------

class TestNormalizeLayout:
    def _raw(self, raw: Path, rel: str, work_id: str) -> None:
        source_id = rel.split("/")[0]
        path = raw / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "work": {"work_id": work_id, "source_id": source_id, "title": "T",
                     "genre": "patristic", "language": "eng", "license": "public_domain"},
            "paragraphs": [{"ref": "T.1", "text": "Text"}],
        }))

    def test_mirrors_raw_paths_and_prunes_by_source(self, tmp_path: Path):
        from scripts.normalize import normalize_all

        raw, norm = tmp_path / "raw", tmp_path / "normalized"
        self._raw(raw, "anf-works/anf01/a.json", "anf-works/a")
        self._raw(raw, "didache/didache.json", "didache/didache")
        self._raw(raw, "ogpg/_extract/vol-001.json", "ogpg/x")  # cache: not a work
        normalize_all(raw, norm)
        assert sorted(p.relative_to(norm).as_posix() for p in norm.rglob("*.json")
                      if not p.name.startswith("_")) == [
            "anf-works/anf01/a.json", "didache/didache.json"]
        assert (norm / "_fingerprint.json").exists()
        manifest = [json.loads(line) for line in (norm / "_works.jsonl").read_text().splitlines()]
        assert [r["path"] for r in manifest] == ["anf-works/anf01/a.json", "didache/didache.json"]

        # A normalized file whose raw file is gone is pruned, but only inside
        # sources that have a raw directory.
        (raw / "anf-works/anf01/a.json").unlink()
        (norm / "pta").mkdir()
        (norm / "pta" / "w.json").write_text("[]")
        normalize_all(raw, norm)
        assert not (norm / "anf-works/anf01/a.json").exists()
        assert (norm / "didache/didache.json").exists()
        assert (norm / "pta/w.json").exists()


class TestGallicanHeadings:
    """Gallican OCR: real prayer headings open a section, OCR noise starting "Missa" doesn't (#241)."""

    def test_heading_regex(self):
        from scripts.ingest.gallican import _HEADING_RE

        for heading in ("MISSA  IN  DEDICATIONE.", "Missa  in  vigilia  natalis  domini.",
                        "ITEM  MISSA  JEJUNII.", "Collectio  sequitur.", "IN  DIE  PENTECOSTES."):
            assert _HEADING_RE.match(heading), heading
        for noise in ("MISSA LE  VESONTIONENSB.",  # running head
                      "Missa Dominicaii.”— Mab.  quo  ait  Salvator",  # footnote
                      "missa non  reddere.  Ne  dederis  os  tuum  ut"):  # prose
            assert not _HEADING_RE.match(noise), noise
