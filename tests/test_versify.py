import pytest

from patristica.models import Chunk
from patristica.versify import (
    MAX_VERSES,
    VERSE_TOKENS,
    count_tokens,
    is_derived_ref,
    split_text,
    versify_chunks,
)

LATIN = (
    "Christianam fidem noui ac ueteris testamenti pandit auctoritas. "
    "Haec autem religio nostra, quae uocatur Christiana atque catholica, his fundamentis nititur. "
    "Ex aeterno, id est ante mundi constitutionem, diuinam patris et filii ac spiritus sancti "
    "exstitisse substantiam, ita ut deum dicat patrem, deum filium, deum spiritum sanctum. "
    "Nec tamen tres deos sed unum deum confitemur, qui fecit caelum et terram."
)


def _squash(s: str) -> str:
    return " ".join(s.split())


def test_short_text_is_one_unit():
    assert split_text("In principio erat Verbum.", "lat") == ["In principio erat Verbum."]


def test_units_cover_the_text_in_order():
    units = split_text(LATIN, "lat")
    assert len(units) > 1
    assert _squash(" ".join(units)) == _squash(LATIN)
    assert all(u == u.strip() and u for u in units)


def test_prefers_sentence_ends():
    units = split_text(" ".join([LATIN] * 4), "lat")
    assert sum(u.endswith(".") for u in units) > len(units) / 2
    assert all(u[-1] in ".,;:" for u in units)


def test_unit_size_near_a_verse():
    text = " ".join([LATIN] * 20)
    sizes = [count_tokens(u) / VERSE_TOKENS["lat"] for u in split_text(text, "lat")]
    assert 0.8 < sum(sizes) / len(sizes) < 1.5
    assert max(sizes) <= MAX_VERSES


def test_unpunctuated_run_is_split_between_words():
    text = " ".join(["verbum"] * 400)
    units = split_text(text, "lat")
    assert len(units) > 5
    assert all(count_tokens(u) <= MAX_VERSES * VERSE_TOKENS["lat"] for u in units)
    assert _squash(" ".join(units)) == text


def test_greek_semicolon_ends_a_sentence_latin_does_not():
    q = "τί οὖν ἐροῦμεν περὶ τούτου τοῦ λόγου τοῦ μεγάλου καὶ θαυμαστοῦ καὶ φοβεροῦ;"
    greek = " ".join([q] * 8)
    assert all(u.endswith(";") for u in split_text(greek, "grc"))


def test_abbreviation_is_not_a_sentence_end():
    from patristica.versify import COMMA, SENTENCE, _strength

    assert _strength(" cf.", " Matth.", "lat") == COMMA
    assert _strength(" cap.", " 5", "lat") == COMMA
    assert _strength(" auctoritas.", " Haec", "lat") == SENTENCE


def test_geez_wordspace_separates_words():
    word = "ዝንቱ፡ሴኖዶስ፡ዘቀሌምንጦስ፡ዘጸሐፈ፡ጴጥሮስ፡"
    text = (word * 2 + "። ") * 12
    units = split_text(text.strip(), "gez")
    assert len(units) > 1
    assert all(u.endswith("።") for u in units)


def test_deterministic():
    text = " ".join([LATIN] * 10)
    assert split_text(text, "lat") == split_text(text, "lat")


def test_unknown_language_raises():
    with pytest.raises(ValueError, match="VERSE_TOKENS"):
        split_text("x y z " * 100, "xxx")


def _chunk(ref: str, text: str, i: int) -> Chunk:
    return Chunk(
        chunk_id=f"w/x#{ref}", work_id="w/x", canonical_ref=ref, language="lat",
        text=text, chunk_index=i, date_composed=500, date_confidence="approximate",
    )


def test_versify_chunks_derives_refs_and_keeps_metadata():
    chunks = [_chunk("1", "Titulus.", 0), _chunk("2", " ".join([LATIN] * 3), 2)]
    out = versify_chunks(chunks, "patristic")
    assert out[0] == chunks[0]
    derived = out[1:]
    assert [c.canonical_ref for c in derived] == [f"2.s{n}" for n in range(1, len(derived) + 1)]
    assert all(is_derived_ref(c.canonical_ref) for c in derived)
    assert derived[0].chunk_id == "w/x#2.s1"
    assert all(c.date_composed == 500 and c.work_id == "w/x" for c in derived)
    assert [c.chunk_index for c in out] == list(range(len(out)))


def test_versify_chunks_is_idempotent():
    chunks = [_chunk("1", " ".join([LATIN] * 3), 0)]
    once = versify_chunks(chunks, "patristic")
    assert versify_chunks(once, "patristic") == once


def test_scripture_is_never_split():
    chunks = [_chunk("Gen.1.1", " ".join([LATIN] * 3), 0)]
    assert versify_chunks(chunks, "scripture") == chunks


def test_is_derived_ref():
    assert is_derived_ref("Aug.Conf.1.1.s3")
    assert not is_derived_ref("Aug.Conf.1.1.3")
    assert not is_derived_ref("c12.p4")
