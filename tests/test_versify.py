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


# Codex Suprasliensis 1 (TOROT, from obdurodon.org), the start of the
# Martyrdom of Basiliscus: "." ends sentences, "·" introduces speech, ⁛ ends
# the heading.
SUPRASLIENSIS = (
    "Мѣсѧца марта въ е͆ день͗. мѫчениѥ ст͆ааго василиска⁛ Въ то врѣмѧ цѣсарь͗ствовавъшоу "
    "маѯимия͑ноу. приде прѣмѣнь͗никъ въ а͑сꙿклипиѡ̑да мѣсто. и͑нъ воѥ͑вода и͑менемь а͑грипа. "
    "и͑ пои͑де на въсточь͗нѫѭ̑ странѫ привести крьстия͑ны жрь͗ти и͑мъ велѧ богомъ. "
    "блаженыи͑ же василискъ бѣа͑ше вь͗ темници. плачѧ сѧ и͑ молѧ сѧ и глагол̑ѧ· г͆и помѧни "
    "мѧ и͑ о͑бличи моѥ͑ призꙿваниѥ͗. да не о͑тълѫченъ бѫдѫ о͑тъ с͆тыи͗хъ мѫжь. и͑ я͑ви сѧ "
    "ѥ͑моу г͞ь и͑ рече· помѧнѫхъ тѧ и вь͗писахъ твоѥ и͑мѧ съ сѫштиїми съ тобоѭ̑ прь͗воѥ "
    "мѫченикы. ты же си пожали и͑мꙿже послѣжде възъванъ ѥ͑си."
)


def test_church_slavonic_punctuation():
    from patristica.versify import CLAUSE, SENTENCE, _strength

    assert _strength(" ѥ͑си.", " ты", "chu") == SENTENCE
    assert _strength(" вьꙿси;", " ꙇ", "chu") == SENTENCE  # ";" asks a question
    assert _strength(" твои ⁘", " Въ", "chu") == SENTENCE
    assert _strength(" василиска⁛", " Въ", "chu") == SENTENCE
    assert _strength(" рече·", " помѧнѫхъ", "chu") == CLAUSE
    assert _strength(" ѥзыци:", " ꙇ", "chu") == CLAUSE


def test_church_slavonic_paragraph_splits_at_its_stops():
    units = split_text(SUPRASLIENSIS, "chu")
    assert len(units) > 3
    assert _squash(" ".join(units)) == _squash(SUPRASLIENSIS)
    assert all(u[-1] in ".·⁛" for u in units)
    sizes = [count_tokens(u) / VERSE_TOKENS["chu"] for u in units]
    assert 0.7 < sum(sizes) / len(sizes) < 1.5


# The opening of the Apology of al-Kindī (OpenITI SyriacStudies00001), #83.
KINDI = (
    "ذكر أنه كان في زمن عبد الله المأمون رجل من نبلاء الهاشميين وأظنه من ولد العباس، "
    "قريب القرابة من الخليفة، معروف بالنسك والورع والتمسك بدين الإسلام وشدة الإغراق فيه "
    "والقيام بفرائضه وسننه، مشهور بذلك عند الخاصة والعامة. وكان له صديق من الفضلاء ذو أدب "
    "وعلم، كندي الأصل مشهور بالتمسك بدين النصرانية، وكان في خدمة الخليفة وقريبا منه مكانا. "
    "فكانا يتوادان ويتحابان ويثق كل منهما بصاحبه وبالإخلاص له. وكان أمير المؤمنين \"المأمون\" "
    "وجماعة أصحابه والمتصلون به قد عرفوهما بذلك، وهما عبد الله بن إسماعيل الهاشمي، وعبد "
    "المسيح بن اسحق الكندي، فكتب الهاشمي إلى الكندي هذه نسخته:"
)


def test_arabic_punctuation():
    from patristica.versify import CLAUSE, COMMA, SENTENCE, _strength

    assert _strength(" نسخته.", " وكان", "arb") == SENTENCE
    assert _strength(" هذا؟", " قال", "arb") == SENTENCE
    assert _strength(" قال؛", " لأن", "arb") == CLAUSE
    assert _strength(" العباس،", " قريب", "arb") == COMMA


def test_arabic_paragraph_splits_at_its_stops():
    units = split_text(KINDI, "arb")
    assert len(units) > 3
    assert _squash(" ".join(units)) == _squash(KINDI)
    assert all(u[-1] in ".،:" for u in units)
    sizes = [count_tokens(u) / VERSE_TOKENS["arb"] for u in units]
    assert 0.7 < sum(sizes) / len(sizes) < 1.5


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
    out = versify_chunks(chunks)
    assert out[0] == chunks[0]
    derived = out[1:]
    assert [c.canonical_ref for c in derived] == [f"2.s{n}" for n in range(1, len(derived) + 1)]
    assert all(is_derived_ref(c.canonical_ref) for c in derived)
    assert derived[0].chunk_id == "w/x#2.s1"
    assert all(c.date_composed == 500 and c.work_id == "w/x" for c in derived)
    assert [c.chunk_index for c in out] == list(range(len(out)))


def test_versify_chunks_is_idempotent():
    chunks = [_chunk("1", " ".join([LATIN] * 3), 0)]
    once = versify_chunks(chunks)
    assert versify_chunks(once) == once


def test_standard_versification_is_never_split():
    chunks = [_chunk("Gen.1.1", " ".join([LATIN] * 3), 0)]
    assert versify_chunks(chunks, standard=True) == chunks


def test_listed_units_of_a_standard_work_are_split(monkeypatch: pytest.MonkeyPatch):
    """Only the units in UNVERSIFIED_UNITS are split in a standard work (#129)."""
    import patristica.versify as versify

    long = " ".join([LATIN] * 3)
    chunks = [_chunk("Gen.1.1", long, 0), _chunk("Gen.1.2", long, 1), _chunk("Gen.1.3", "Fiat.", 2)]
    monkeypatch.setattr(versify, "UNVERSIFIED_UNITS", {"w/x#Gen.1.2": "test"})
    out = versify_chunks(chunks, standard=True)
    refs = [c.canonical_ref for c in out]
    assert refs[0] == "Gen.1.1" and refs[-1] == "Gen.1.3"   # a long real verse is kept
    assert out[0].text == long
    assert all(r.startswith("Gen.1.2.s") for r in refs[1:-1]) and len(refs) > 3
    assert [c.chunk_index for c in out] == list(range(len(out)))
    assert versify_chunks(out, standard=True) == out          # idempotent

    # A listed work splits every long unit, and a short one keeps its ref.
    monkeypatch.setattr(versify, "UNVERSIFIED_UNITS", {"w/x": "test"})
    refs = [c.canonical_ref for c in versify_chunks(chunks, standard=True)]
    assert "Gen.1.3" in refs and "Gen.1.1" not in refs and "Gen.1.2" not in refs


def test_unversified_units_name_corpus_works():
    """Every UNVERSIFIED_UNITS key is a work id, or a chunk id of a work, in the corpus."""
    import json
    from pathlib import Path

    from patristica.versify import UNVERSIFIED_UNITS

    manifest = Path(__file__).parent.parent / "data" / "normalized" / "_works.jsonl"
    works = {json.loads(line)["work"]["work_id"]
             for line in manifest.read_text(encoding="utf-8").splitlines()}
    for key, reason in UNVERSIFIED_UNITS.items():
        assert key.split("#")[0] in works and reason


def test_is_derived_ref():
    assert is_derived_ref("Aug.Conf.1.1.s3")
    assert not is_derived_ref("Aug.Conf.1.1.3")
    assert not is_derived_ref("c12.p4")


# From the Martyrdom of Shushanik (ka.wikisource, §3), #222.
SHUSHANIK = (
    "ხოლო ეპისკოპოსი იგი სახლისა მის პიტიახშისაჲ, რომელსა სახელი ერქუა აფოც, არა მუნ იყო, "
    "არამედ კაცისა ვისამე წმიდისა ვანად მისრულ იყო კითხვად რაჲსამე სიტყჳსა. და მეცა, ხუცესი "
    "დედოფლისა შუშანიკისი, თანავჰყვანდი ეპისკოპოსსა მას. და მყის მოიწია ჩუენდა დიაკონი "
    "შინაჲთ და გჳთხრა ჩუენ ესე ყოველი - მოსლვაჲ პიტიახშისაჲ და საქმენი დედოფლისანი. ხოლო "
    "ჩუენ აღვივსენით მწუხარებითა და დიდითაი ტირილითა ვტიროდეთ განმწარებულნი ცოდვათ ჩუენთა "
    "წარმოჩინებისათჳს."
)


def test_old_georgian_punctuation():
    from patristica.versify import CLAUSE, COMMA, SENTENCE, _strength

    assert _strength(" სიტყჳსა.", " და", "oge") == SENTENCE
    assert _strength(" მისსა?", " ზოგნი", "oge") == SENTENCE
    assert _strength(" ქართლისაჲ჻", " ხოლო", "oge") == SENTENCE  # ჻ (U+10FB)
    assert _strength(" მას:", " შენ", "oge") == CLAUSE  # before speech
    assert _strength(" ისაკი;", " ისაკმან", "oge") == CLAUSE
    assert _strength(" აფოც,", " არა", "oge") == COMMA


def test_old_georgian_paragraph_splits_at_its_stops():
    units = split_text(SHUSHANIK, "oge")
    assert len(units) > 2
    assert _squash(" ".join(units)) == _squash(SHUSHANIK)
    assert all(u[-1] == "." for u in units)
    sizes = [count_tokens(u) / VERSE_TOKENS["oge"] for u in units]
    assert 0.7 < sum(sizes) / len(sizes) < 1.5
