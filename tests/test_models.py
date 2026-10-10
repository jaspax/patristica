"""Tests for patristica.models — Work and Chunk Pydantic models."""

import pytest
from pydantic import ValidationError

from patristica.models import Chunk, Work


class TestWork:
    def test_minimal_valid(self):
        w = Work(work_id="augustine/confessions", source_id="ccel/npnf1-01", title="Confessions", genre="patristic", language="lat")
        assert w.work_id == "augustine/confessions"
        assert w.author is None
        assert w.date_composed is None
        assert w.date_confidence == "uncertain"
        assert w.license == "unknown"

    def test_full_fields(self):
        w = Work(
            work_id="scripture/gen",
            source_id="scripture/oshb",
            author=None,
            title="Genesis",
            date_composed=-450,
            date_range=(-600, -400),
            date_confidence="approximate",
            genre="scripture",
            language="hbo",
            tradition="greek",
            license="cc-by-4.0",
            provenance_url="https://example.com/oshb",
            edition="OSHB v2.1",
            translation_of=None,
        )
        assert w.date_composed == -450
        assert w.date_range == (-600, -400)
        assert w.license == "cc-by-4.0"

    def test_invalid_genre(self):
        with pytest.raises(ValidationError):
            Work(work_id="x", source_id="y", title="T", genre="heretical", language="lat")

    def test_invalid_language(self):
        with pytest.raises(ValidationError):
            Work(work_id="x", source_id="y", title="T", genre="patristic", language="xyz")

    def test_invalid_license(self):
        with pytest.raises(ValidationError):
            Work(work_id="x", source_id="y", title="T", genre="patristic", language="lat", license="mit")

    def test_invalid_date_confidence(self):
        with pytest.raises(ValidationError):
            Work(work_id="x", source_id="y", title="T", genre="patristic", language="lat", date_confidence="maybe")

    def test_all_genres(self):
        for genre in ("scripture", "patristic", "liturgical", "council"):
            w = Work(work_id="x", source_id="y", title="T", genre=genre, language="lat")
            assert w.genre == genre

    def test_all_languages(self):
        for lang in ("grc", "lat", "hbo", "syc", "cop", "gez", "hye", "got", "eng"):
            w = Work(work_id="x", source_id="y", title="T", genre="patristic", language=lang)
            assert w.language == lang


class TestChunk:
    def test_minimal_valid(self):
        c = Chunk(
            chunk_id="augustine/confessions#Conf.1.1",
            work_id="augustine/confessions",
            canonical_ref="Conf.1.1",
            language="lat",
            text="Fecisti nos ad te",
            chunk_index=0,
        )
        assert c.chunk_id == "augustine/confessions#Conf.1.1"
        assert c.translation_group_id is None
        assert c.out_of_period is False
        assert c.date_confidence == "uncertain"

    def test_context_fields(self):
        c = Chunk(
            chunk_id="gen#Gen.1.1",
            work_id="gen",
            canonical_ref="Gen.1.1",
            language="hbo",
            text="בְּרֵאשִׁית",
            chunk_index=0,
            context_before="...",
            context_after="...",
        )
        assert c.context_before == "..."
        assert c.context_after == "..."

    def test_out_of_period_flag(self):
        c = Chunk(
            chunk_id="x#y",
            work_id="x",
            canonical_ref="y",
            language="lat",
            text="text",
            chunk_index=0,
            out_of_period=True,
            date_composed=1200,
        )
        assert c.out_of_period is True

    def test_invalid_language(self):
        with pytest.raises(ValidationError):
            Chunk(
                chunk_id="x#y",
                work_id="x",
                canonical_ref="y",
                language="zz",
                text="text",
                chunk_index=0,
            )

    def test_translation_group_id(self):
        c = Chunk(
            chunk_id="x#Gen.1.1",
            work_id="x",
            canonical_ref="Gen.1.1",
            language="grc",
            text="Ἐν ἀρχῇ",
            chunk_index=0,
            translation_group_id="Gen.1.1",
        )
        assert c.translation_group_id == "Gen.1.1"
