from patristica.textfold import fold, squash


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
