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


def test_squash_ignores_word_division():
    assert squash("ⲛ ⲧⲉ ⲕⲕⲗⲏⲥⲓⲁ") == squash("ⲛⲧⲉⲕⲕⲗⲏⲥⲓⲁ")


# fold_spans must agree with fold exactly: search highlights depend on it (#143).
SAMPLES = [
    "Ἐν ἀρχῇ ἦν ὁ λόγος,", "λόγος· καὶ", "כָּל־הָאָ֖רֶץ", "ܒܪܺܫܺܝܬ݂", "ϩ︤ⲛ︥ ⲧ ⲃⲁϣⲟⲣ⳿", "ⲙ̄ⲡⲛⲟⲩⲧⲉ",
    "Ո՞վ է", "Iustus vnus, caelum", "michi nichil", "cœlum", "Straße", "aee oee",
    "ወርእዮ ፡ እግዚአብሔር ፡ ለብርሃን", "𐌹𐌽 𐌰𐌽𐌰𐍃𐍄𐍉𐌳𐌴𐌹𐌽", "", "  ", " a  b ", "x\u200dy",
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
