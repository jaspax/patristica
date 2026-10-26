"""Tests for patristica.translation_links (curated translation_of, #153)."""

from __future__ import annotations

from pathlib import Path

import pytest

from patristica import translation_links as tl

HEADER = "source_id,books,translation_of,note\n"


def _rules(tmp_path: Path, rows: list[str]) -> Path:
    p = tmp_path / "rules.csv"
    p.write_text(HEADER + "\n".join(rows) + "\n", encoding="utf-8")
    return p


@pytest.fixture
def tables(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    rules = tl.load_scripture_rules(_rules(tmp_path, [
        "heb,*,original,Hebrew",
        "grk,ot,heb,from Hebrew",
        "grk,nt,original,Greek NT",
        "grk,wis|sir,original,composed in Greek",
        "lat,*,grk,from Greek",
        "lat,gen,heb,from Hebrew",
        "lat,tob,unlinked,from Aramaic",
        "lat,dan,grk/danth,Theodotion",
    ]))
    monkeypatch.setattr(tl, "_scripture_rules", lambda: rules)
    monkeypatch.setattr(tl, "scripture_sources", lambda: frozenset({"heb", "grk", "lat"}))
    monkeypatch.setattr(tl, "_curated_links", lambda: {"pl/versio": "pg/opus"})


class TestRules:
    def test_precedence(self, tables: None) -> None:
        assert tl.curated_translation_of("lat/gen") == "heb/gen"   # book beats *
        assert tl.curated_translation_of("lat/exod") == "grk/exod"  # * otherwise
        assert tl.curated_translation_of("grk/gen") == "heb/gen"   # ot
        assert tl.curated_translation_of("grk/sir") is None        # book beats ot
        assert tl.curated_translation_of("grk/john") is None       # nt

    def test_work_id_target(self, tables: None) -> None:
        assert tl.curated_translation_of("lat/dan") == "grk/danth"

    def test_original_and_unlinked_set_nothing(self, tables: None) -> None:
        assert tl.curated_translation_of("heb/gen") is None
        assert tl.curated_translation_of("lat/tob") is None
        assert tl.scripture_rule("lat/tob").translation_of == tl.UNLINKED

    def test_other_works_use_the_curated_links(self, tables: None) -> None:
        assert tl.curated_translation_of("pl/versio") == "pg/opus"
        assert tl.curated_translation_of("pl/other") is None
        # A deeper id in a Scripture source is not a book.
        assert tl.scripture_rule("lat/a/b") is None

    def test_duplicate_rule_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(tl.TranslationOfError, match="listed twice"):
            tl.load_scripture_rules(_rules(tmp_path, ["a,gen|exod,b,x", "a,exod,c,y"]))

    def test_note_required(self, tmp_path: Path) -> None:
        with pytest.raises(tl.TranslationOfError, match="no note"):
            tl.load_scripture_rules(_rules(tmp_path, ["a,*,b,"]))

    def test_tracked_table_loads(self) -> None:
        assert tl.load_scripture_rules()


class TestApply:
    def test_sets_the_link(self, tables: None) -> None:
        work = {"work_id": "lat/gen"}
        assert tl.apply_translation_of(work) == {"work_id": "lat/gen", "translation_of": "heb/gen"}
        assert work == {"work_id": "lat/gen"}  # a copy

    def test_agreeing_ingestor_link_is_kept(self, tables: None) -> None:
        work = {"work_id": "lat/gen", "translation_of": "heb/gen"}
        assert tl.apply_translation_of(work) is work

    def test_conflict_raises(self, tables: None) -> None:
        with pytest.raises(tl.TranslationOfError, match="ingestor"):
            tl.apply_translation_of({"work_id": "lat/gen", "translation_of": "grk/gen"})

    def test_uncurated_work_is_untouched(self, tables: None) -> None:
        work = {"work_id": "eng/x", "translation_of": "pg/opus"}
        assert tl.apply_translation_of(work) is work


class TestCuratedLinks:
    def test_reads_only_translation_rows(self, tmp_path: Path) -> None:
        p = tmp_path / "links.csv"
        p.write_text("work_id,other_work_id,relation,reason\n"
                     "a,b,translation_of,r\nc,d,same_work,r\n", encoding="utf-8")
        assert tl.load_curated_links(p) == {"a": "b"}

    def test_two_originals_rejected(self, tmp_path: Path) -> None:
        p = tmp_path / "links.csv"
        p.write_text("work_id,other_work_id,relation,reason\n"
                     "a,b,translation_of,r\na,c,translation_of,r\n", encoding="utf-8")
        with pytest.raises(tl.TranslationOfError, match="already"):
            tl.load_curated_links(p)


class TestChain:
    def test_follows_links(self) -> None:
        assert tl.translation_chain("cop", {"cop": "grc", "grc": "hbo", "hbo": None}) == [
            "cop", "grc", "hbo"]

    def test_cycle_raises(self) -> None:
        with pytest.raises(tl.TranslationOfError, match="cycle"):
            tl.translation_chain("a", {"a": "b", "b": "a"})
