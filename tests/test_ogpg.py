"""Tests for the OGPG dictionary filter, cross-scan voting and volume metadata."""

from __future__ import annotations

import pytest

from scripts.ingest import _greek_lexicon as lex
from scripts.ingest import _ogpg_volumes as pgv
from scripts.ingest import ogpg

LEXICON = frozenset(lex.normalize_token(w) for w in (
    "καὶ ὁ λόγος ἦν πρὸς τὸν θεόν οὗτος ἐν ἀρχῇ πάντα δι’ αὐτοῦ ἐγένετο "
    "χωρὶς οὐδὲ ἓν γέγονεν ζωὴ φῶς τῶν ἀνθρώπων σκοτίᾳ φαίνει"
).split())

CLEAN = ("Ἐν ἀρχῇ ἦν ὁ λόγος, καὶ ὁ λόγος ἦν πρὸς τὸν θεόν. Οὗτος ἦν ἐν ἀρχῇ πρὸς "
         "τὸν θεόν. Πάντα δι’ αὐτοῦ ἐγένετο, καὶ χωρὶς αὐτοῦ ἐγένετο οὐδὲ ἕν.")
GARBLED = ("Ἐν ἀρχῇ ξιιωιναιί ὁ λόγος, ηιμ ιιιιιι ςωλοῦκ ὲθεῆρὲμὰνθη sva; tristem; "
           "ειιϊερὶήῑ πρὸς Ilum unm. ξξιν ἀνᾳλαόὼῆξ καὶ ιυιιιινινιιι")
_NOISE = " ξιιωιναιί ιυιιιινινιιι ηιμ ιιιιιι tristem; sva; unm. ςωλοῦκ ὲθεῆρὲμὰνθη ξξιν ηιμ."


class TestNormalizeToken:
    def test_strips_accents_breathings_and_case(self):
        assert lex.normalize_token("Ἐν") == "εν"
        assert lex.normalize_token("ἀρχῇ") == "αρχη"

    def test_final_and_lunate_sigma_and_beta_variant(self):
        assert lex.normalize_token("λόγος") == "λογοσ"
        assert lex.normalize_token("λόγοϲ") == "λογοσ"
        assert lex.normalize_token("ϐασιλεύς") == "βασιλευσ"

    def test_drops_punctuation_digits_and_elision(self):
        assert lex.normalize_token("δι’") == "δι"
        assert lex.normalize_token("θεόν.¹²") == "θεον"
        assert lex.normalize_token("—") == ""

    def test_mixed_script_stays_mixed(self):
        form = lex.normalize_token("ἐπωλvυμία")
        assert not lex.is_greek_form(form)


class TestScoreText:
    def test_clean_text_scores_high(self):
        s = lex.score_text(CLEAN, LEXICON)
        assert s.score > 0.9
        assert s.foreign == 0

    def test_garbled_text_scores_low(self):
        s = lex.score_text(GARBLED, LEXICON)
        assert s.score < ogpg.LEXICON_THRESHOLD
        assert s.foreign >= 4      # Latin and mixed-script tokens count against

    def test_empty_text(self):
        assert lex.score_text("", LEXICON).score == 0.0
        assert lex.score_text("12 — .", LEXICON).total == 0

    def test_accent_errors_tolerated(self):
        # OCR often confuses accents; base letters are what count.
        assert lex.score_text("ὲν ἀρχἢ ἢν ὀ λὸγος", LEXICON).score == 1.0


def test_cached_lexicon_loads_and_contains_common_forms():
    lexicon = lex.load_lexicon()
    assert len(lexicon) > 100_000
    for word in ("καὶ", "Θεοῦ", "ἐκκλησίας", "ἐγένετο", "Χριστοῦ"):
        assert lex.normalize_token(word) in lexicon


class TestExtractCandidates:
    def test_greek_lines_grouped_latin_and_front_matter_dropped(self):
        pages = [
            ("003", CLEAN),                              # front matter (stem < 9)
            ("010", f"{CLEAN}\nHaec est versio Latina columnae alterius.\n{CLEAN}"),
        ]
        cands = ogpg._extract_candidates(pages)
        assert [c.page for c in cands] == [1, 1]
        assert all("Latina" not in c.text for c in cands)

    def test_page_boundary_flushes(self):
        pages = [("010", CLEAN), ("011", CLEAN)]
        assert len(ogpg._extract_candidates(pages)) == 2


def _scan(name: str, texts: list[tuple[int, str]], n_pages: int = 10) -> ogpg._Scan:
    cands = [ogpg.Candidate(p, t, lex.score_text(t, LEXICON)) for p, t in texts]
    return ogpg._Scan(name, cands, n_pages)


class TestVote:
    def test_primary_is_scan_with_most_valid_greek(self):
        a = _scan("hvd.1_ocr", [(2, GARBLED), (5, CLEAN)])
        b = _scan("coo.2_ocr", [(2, CLEAN), (5, CLEAN)])
        primary, texts, stats = ogpg._vote([a, b], LEXICON)
        assert primary.name == "coo.2_ocr"
        assert stats.kept == 2 and stats.replaced == 0 and stats.dropped == 0

    def test_low_scoring_paragraph_replaced_from_matching_scan(self):
        garbled_variant = CLEAN[:70] + _NOISE
        clean2 = "Ζωὴ ἦν τὸ φῶς τῶν ἀνθρώπων, καὶ τὸ φῶς ἐν τῇ σκοτίᾳ φαίνει καὶ ὁ λόγος ἦν."
        a = _scan("hvd.1_ocr", [(3, garbled_variant), (6, clean2), (7, clean2), (8, clean2)])
        b = _scan("coo.2_ocr", [(3, CLEAN), (8, GARBLED)])
        primary, texts, stats = ogpg._vote([a, b], LEXICON)
        assert primary.name == "hvd.1_ocr"
        assert stats.replaced == 1
        assert texts[0] == CLEAN

    def test_replacement_must_be_at_same_position(self):
        garbled_variant = CLEAN[:70] + _NOISE
        a = _scan("hvd.1_ocr", [(1, garbled_variant), (2, CLEAN), (3, CLEAN)], n_pages=100)
        b = _scan("coo.2_ocr", [(90, CLEAN)], n_pages=100)
        _, texts, stats = ogpg._vote([a, b], LEXICON)
        assert stats.replaced == 0 and stats.dropped == 1
        assert len(texts) == 2


class TestVolumeTable:
    def test_every_volume_covered(self):
        assert set(range(1, 162)) <= set(pgv.PG_VOLUMES)

    def test_ranges_are_consistent(self):
        for vol, meta in pgv.PG_VOLUMES.items():
            lo, hi = meta.date_range
            assert lo <= hi, vol
            if meta.date_composed is not None:
                assert lo <= meta.date_composed <= hi, vol

    @pytest.mark.parametrize("vol,post", [(50, False), (112, False), (115, False),
                                          (120, False), (121, True), (150, True)])
    def test_post_schism_boundary(self, vol: int, post: bool):
        assert (pgv.PG_VOLUMES[vol].date_range[0] > 1054) is post

    def test_combined_lookup_merges(self):
        meta = pgv.lookup([86, 87])
        assert meta is not None
        assert meta.date_range == (500, 700)
        assert "Procopius of Gaza" in meta.authors

    def test_part_lookup(self):
        meta = pgv.lookup([16], part=3)
        assert meta is not None and "Hippolytus of Rome" in meta.authors


class TestMakeWork:
    def test_single_author_title(self):
        w = ogpg._make_work("Vol.-11", [11], None, "vol-011", "hvd.x_ocr")
        assert w.title == "Works in PG Vol. 11 (Origen)"
        assert w.author == "Origen"
        assert "Migne" in (w.edition or "") and "hvd.x_ocr" in (w.edition or "")
        assert "PATROLOGIA GRAECA" not in w.title.upper()

    def test_many_authors_abbreviated(self):
        w = ogpg._make_work("Vol.-65", [65], None, "vol-065")
        assert w.title.endswith("et al.)")
        assert w.author is not None and w.author.endswith("et al.")

    def test_part_label(self):
        w = ogpg._make_work("Vol.-87.3", [87], 3, "vol-087-pt3")
        assert w.title.startswith("Works in PG Vol. 87, Part 3 (Procopius of Gaza")
