import json
from pathlib import Path

import pytest

from patristica.textfold import fold, fold_spans, squash


def test_greek_accents_breathings_and_final_sigma():
    assert fold("Ἐν ἀρχῇ ἦν ὁ λόγος,") == fold("εν αρχη ην ο λογοσ") == "εν αρχη ην ο λογοσ"


def test_greek_ano_teleia_is_a_separator():
    assert fold("λόγος· καὶ") == "λογοσ και"


def test_hebrew_points_cantillation_and_maqaf():
    assert fold("כָּל־הָאָ֖רֶץ") == "כל הארץ"


def test_syriac_vowels_removed():
    assert fold("ܒܪܺܫܺܝܬ݂") == "ܒܪܫܝܬ"


def test_coptic_supralinear_strokes_and_divider():
    assert fold("ϩ︤ⲛ︥ ⲧ ⲃⲁϣⲟⲣ⳿") == "ϩⲛ ⲧ ⲃⲁϣⲟⲣ"
    assert fold("ⲙ̄ⲡⲛⲟⲩⲧⲉ") == "ⲙⲡⲛⲟⲩⲧⲉ"


def test_armenian_in_word_marks_do_not_split_words():
    assert fold("Ո՞վ է") == "ով է"


def test_latin_spelling_variants():
    assert fold("Iustus vnus, caelum") == fold("justus unus celum")
    assert fold("michi nichil") == "mihi nihil"
    assert fold("cœlum") == fold("caelum")


def test_church_slavonic_witnesses_fold_alike():
    # John 1:1 in Marianus (TOROT's Glagolitic transliteration) and as a
    # Cyrillic manuscript or a modern reader would write it.
    marianus = "Искони бѣ слово. ꙇ слово бѣ отъ б҃а. ꙇ б҃ъ бѣ слово."
    assert fold(marianus) == fold("искони бѣ слово и слово бѣ от ба и бъ бѣ слово")
    assert fold("ꙇже") == fold("іже") == fold("иже") == fold("їже") == "иже"
    assert fold("оученици") == fold("ѹченици") == fold("ꙋченици") == fold("ученици") == "ученици"
    assert fold("ѡтъ") == fold("отъ") == fold("от") == "от"
    assert fold("ѿ") == "от"
    assert fold("бꙑти") == fold("бъіти") == fold("быти") == "быти"
    assert fold("ѥсть") == fold("єсть") == fold("есть") == "ест"
    assert fold("ꙗко") == fold("ѣко") == fold("яко") == "яко"
    assert fold("ѕвѣзда") == fold("ꙁвѣзда") == fold("звѣзда")
    assert fold("ꙙзыкъ") == fold("ѩзыкъ") == fold("ѧзыкъ")
    assert fold("ѭже") == fold("ѫже")
    assert fold("ѳома") == fold("фома")
    assert fold("ѵпокрити") == fold("ипокрити")


def test_church_slavonic_yat_by_position():
    # Glagolitic Ⱑ is ja at a word start and after a vowel, ě after a consonant.
    assert fold("ѣко") == fold("ꙗко") == fold("яко") == "яко"
    assert fold("моѣ") == fold("моꙗ") == fold("моя") == "моя"
    assert fold("тѣло") == fold("тело") == "тело"
    assert fold("ѣсти") == "ясти"  # word start
    assert fold("оуѣзвити") == "уязвити"  # after оу → у
    assert fold("бꙑѣ") == "быя"  # after ꙑ → ы
    assert fold("ꙇѣ") == fold("іѣ") == "ия"  # after і/ꙇ → и
    assert fold("ѣѣ") == "яя"  # after a yat that became я
    # A yer is a vowel, and so is the paerok standing for one: Glagolitic
    # братрьѣ / марьѣ are Cyrillic братрьꙗ / марьꙗ.
    assert fold("братрьѣ") == fold("братрьꙗ") == "братръя"
    assert fold("марьѣ") == fold("марьꙗ") == "маръя"
    assert fold("сꙿѣсти") == "сясти"  # ѣ is folded before the paerok goes
    assert fold("сѣсти") == "сести"
    assert fold("ꙓ") == "я"  # iotated yat
    assert fold("Ѣко") == "яко"


def test_church_slavonic_yers_paerok_titlo_and_marks():
    assert fold("дьнь") == fold("дънъ") == "дън"  # ь merges into ъ
    assert fold("богъ") == fold("бог") == "бог"  # word-final yers go
    assert fold("кръстъ") == "кръст"  # word-internal yers stay
    assert fold("кръстъ") != fold("крстъ")
    assert fold("сꙿ нимь") == fold("съ нимь") == "с ним"
    assert fold("пⸯцѣте") == fold("пцѣте") == "пцете"  # the paerok goes
    assert fold("пьцѣте") == "пъцете"
    assert fold("отъъ, богь") == "от бог"  # a run of final yers before a separator
    assert fold("ꙏ") == ""
    assert fold("г҃лѭ") == fold("глѭ")  # titlo
    assert fold("а͑гг҄ела") == "аггела"  # dasia, palatalization
    assert fold("ъ") == ""  # a lone yer is no word


def test_church_slavonic_superscript_letters_are_letters():
    assert fold("хрⷭ҇тосъ") == fold("хрстосъ") == "хрстос"
    assert fold("кⷰ҇") == "кц"
    # ꙶ becomes ї after NFKD has run, so ї must fold like the decomposed one.
    assert fold("аꙶти") == fold("аїти") == fold("аити") == "аити"


def test_church_slavonic_capitals():
    assert fold("Ꙇсправите ѼТ") == fold("исправите от")


def test_other_scripts_fold_as_before():
    """The Cyrillic rules (#330) leave every other script's folding alone."""
    assert fold("Ἐν ἀρχῇ ἦν ὁ λόγος, καὶ ὁ λόγος ἦν πρὸς τὸν θεόν") == (
        "εν αρχη ην ο λογοσ και ο λογοσ ην προσ τον θεον")
    assert fold("In principio erat Verbum, et Verbum erat apud Deum") == (
        "in principio erat uerbum et uerbum erat apud deum")
    assert fold("ϩⲛ̄ ⲧⲉⲩⲁⲣⲭⲏ ⲛⲉϥϣⲟⲟⲡ ⲛ̄ϭⲓ ⲡϣⲁϫⲉ") == "ϩⲛ ⲧⲉⲩⲁⲣⲭⲏ ⲛⲉϥϣⲟⲟⲡ ⲛϭⲓ ⲡϣⲁϫⲉ"
    assert fold("Իսկզբանէ էր Բանն") == "իսկզբանէ էր բանն"
    assert fold("ܒܪܫܝܬ ܐܝܬܘܗܝ ܗܘܐ ܡܠܬܐ") == "ܒܪܫܝܬ ܐܝܬܘܗܝ ܗܘܐ ܡܠܬܐ"
    assert fold("בְּרֵאשִׁית בָּרָא") == "בראשית ברא"
    assert fold("ቀዳሚሁ ፡ ቃል ፡ ውእቱ") == "ቀዳሚሁ ቃል ውእቱ"
    assert fold("𐌹𐌽 𐌰𐌽𐌰𐍃𐍄𐍉𐌳𐌴𐌹𐌽 𐍅𐌰𐍃 𐍅𐌰𐌿𐍂𐌳") == "𐌹𐌽 𐌰𐌽𐌰𐍃𐍄𐍉𐌳𐌴𐌹𐌽 𐍅𐌰𐍃 𐍅𐌰𐌿𐍂𐌳"
    assert fold("In the beginning was the Word") == "in the beginning was the word"


def test_squash_ignores_word_division():
    assert squash("ⲛ ⲧⲉ ⲕⲕⲗⲏⲥⲓⲁ") == squash("ⲛⲧⲉⲕⲕⲗⲏⲥⲓⲁ")


# fold_spans must agree with fold exactly: search highlights depend on it (#143).
SAMPLES = [
    "Ἐν ἀρχῇ ἦν ὁ λόγος,", "λόγος· καὶ", "כָּל־הָאָ֖רֶץ", "ܒܪܺܫܺܝܬ݂", "ϩ︤ⲛ︥ ⲧ ⲃⲁϣⲟⲣ⳿", "ⲙ̄ⲡⲛⲟⲩⲧⲉ",
    "Ո՞վ է", "Iustus vnus, caelum", "michi nichil", "cœlum", "Straße", "aee oee",
    "ወርእዮ ፡ እግዚአብሔር ፡ ለብርሃን", "𐌹𐌽 𐌰𐌽𐌰𐍃𐍄𐍉𐌳𐌴𐌹𐌽", "", "  ", " a  b ", "x\u200dy",
    "Искони бѣ слово. ꙇ слово бѣ отъ б҃а.", "оученици ѹченици", "бъіти ꙑ ъ", "ѿ Ѿца",
    "хрⷭ҇тосъ кⷰ҇ ⁘", "сꙿ нимь· пⸯцѣте", "ѯ ѱ ꙗко", "ооу оъу", "ъ ь ꙿ", "а͑гг҄ела",
    "ѣко тѣло моѣ", "Ѣѣ ꙇѣ въѣ сꙿѣ ꙓ", "оуѣ ъѣ ѣ", "дьнь кръстъ отъъ, богь.", "ьи ъи ъі",
    "aѣ 1ѣ ѣ̈", "ꙿѣ ъꙿ ꙿъ", "братрьѣ сⸯѣ ꙿꙿѣ ъꙿѣ", "аꙶти ꙵꙶ",
]


@pytest.mark.parametrize("text", SAMPLES)
def test_fold_spans_agrees_with_fold(text: str) -> None:
    folded, starts, ends = fold_spans(text)
    assert folded == fold(text)
    assert len(starts) == len(ends) == len(folded)
    assert all(0 <= a <= b <= len(text) for a, b in zip(starts, ends))


def test_fold_spans_maps_back_to_the_source() -> None:
    text = "Straße michi; Cœlum"
    folded, starts, ends = fold_spans(text)
    assert folded == "strasse mihi celum"
    pieces = [text[a:b] for a, b in zip(starts, ends)]
    assert pieces[3:6] == ["a", "ß", "ß"]  # ß folds to two letters from one
    assert set(pieces[8:12]) == {"michi"}  # a replaced word spans the whole word
    assert pieces[12] == "; "  # a word break spans the gap
    assert pieces[14] == "œ"


def test_fold_spans_maps_church_slavonic_back_to_the_source() -> None:
    text = "оучи ѿ хрⷭ҇тъ"
    folded, starts, ends = fold_spans(text)
    assert folded == "учи от хрст"
    pieces = [text[a:b] for a, b in zip(starts, ends)]
    assert pieces[0] == "оу"  # a digraph spans both letters
    assert pieces[4:6] == ["ѿ", "ѿ"]  # ѿ folds to two letters
    assert pieces[9] == "ⷭ"  # a superscript letter is a letter


def test_fold_spans_maps_yat_and_yers_back_to_the_source() -> None:
    text = "ѣко тѣло дьнь сꙿѣ"
    folded, starts, ends = fold_spans(text)
    assert folded == "яко тело дън ся"
    pieces = [text[a:b] for a, b in zip(starts, ends)]
    assert pieces[0] == "ѣ"  # ѣ → я keeps its source letter
    assert pieces[5] == "ѣ"  # ѣ → е too
    assert pieces[9:12] == ["д", "ь", "н"]  # ь → ъ inside the word; the final ь is gone
    assert pieces[12] == "ь "  # the word break spans the dropped final yer
    assert pieces[13:15] == ["с", "ѣ"]  # the paerok is gone (after folding ѣ → я)


def test_fold_spans_agrees_with_fold_on_the_corpus() -> None:
    """A few works of every language in the corpus (tracked in data/normalized)."""
    root = Path(__file__).resolve().parent.parent / "data" / "normalized"
    manifest = root / "_works.jsonl"
    if not manifest.exists():
        pytest.skip("no normalized corpus")
    seen: dict[str, int] = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        language = entry["work"]["language"]
        if seen.get(language, 0) >= 2:
            continue
        seen[language] = seen.get(language, 0) + 1
        for chunk in json.loads((root / entry["path"]).read_text(encoding="utf-8"))[:300]:
            assert fold_spans(chunk["text"])[0] == fold(chunk["text"]), chunk["chunk_id"]
    assert len(seen) >= 8
