"""CCMH ASCII → Cyrillic conversion and the Gospel-codex ingest (#332)."""

import json
import unicodedata
from pathlib import Path

import pytest

from patristica import editorial
from patristica.textfold import fold
from scripts.ingest import _ccmh
from scripts.ingest._ccmh import (
    ASSEMANIANUS,
    MARIANUS,
    SAVVINA,
    VITAE,
    ZOGR_B,
    ZOGRAPHENSIS,
    convert,
    gospel_books,
    join_lines,
    merge_leaves,
    parse_gospels,
)
from scripts.validate import _SCRIPT_RES, _script_ratio

TITLO, POKRYTIE = "\u0483", "\u0487"


def text(ascii_text: str, table=MARIANUS) -> str:
    return convert(ascii_text, table).text


def test_marianus_matt_5_24_as_torot_has_it():
    # TOROT's Cyrillic Marianus comes from the same CCMH file.
    src = ("ostavi tu dar& tvoi pr@d& ol&tarem& . J Sed& pr@Zde s&miri sE . "
           "s& bratrom& svoim& . i togda priSed& prinesi dar& tvoi ::")
    assert text(src) == ("остави тоу даръ твои прѣдъ олътаремъ. ꙇ шедъ прѣжде съмири сѧ. "
                         "съ братромъ своимъ. и тогда пришедъ принеси даръ твои⁘")


def test_letters_of_the_glagolitic_tables():
    assert text("ju jE jO E O @ y & $ D G I i J w q C S Z T x U A") == \
        "ю ѩ ѭ ѧ ѫ ѣ ꙑ ъ ь ѕ ꙉ і и ꙇ ѡ щ ч ш ж ѳ х ѵ ꙙ"
    assert text("tu") == "тоу"                      # uk is the digraph оу
    assert text("*bOdi *u") == "Бѫди Оу"            # * is a capital


def test_letters_of_the_cyrillic_tables():
    assert text("tu tU ja je X P", VITAE) == "тѹ тꙋ ꙗ ѥ ѯ ѱ"
    # Savvina writes jat as "e, ja as "E and iotated jat as j"e.
    assert text('pr"e(ide pri("Eti j"eko', SAVVINA) == "прѣи\u0485де приꙗ\u0485ти ꙓко"


def test_titlo_over_a_word_and_letters_above_the_line():
    assert text("!gljO !is !b") == f"гл{TITLO}ѭ ис{TITLO} б{TITLO}"
    assert text("by!s") == f"бꙑⷭ{POKRYTIE}"       # бꙑⷭ҇
    assert text("!!iUxva", ASSEMANIANUS) == f"иѵ{TITLO}хва"   # !! is one titlo
    assert text("v& /D d$n$", VITAE) == f"въ ѕ{TITLO} дьнь"  # / marks a numeral in the Vitae


def test_diacritics_sit_on_the_right_letter():
    # Marianus ^ goes on the next letter, Zographensis ^ on the previous one.
    assert text("zemle^jO") == "землеѭ\u0484"
    assert text("ogn^em$", ZOGRAPHENSIS) == "огн\u0484емь"
    joan = unicodedata.normalize("NFC", "ꙇ\u0485о\u0306а\u0306ноу")
    assert text("(J~o~anu", ZOGRAPHENSIS) == joan
    assert text("kostan'tina", VITAE) == "костанꙿтина"


def test_assemanianus_reads_jery_and_its_strokes():
    assert text("*k$nIg&I", ASSEMANIANUS) == "Кьнігꙑ"
    assert text("/isa/aka", ASSEMANIANUS) == "и\u0301саа\u0301ка"
    # Two strokes over one letter are one double mark (#368).
    assert text("//wt& d``&va", ASSEMANIANUS) == "ѡ\u030bтъ дъ\u030fва"
    assert text("/i/ak/ova", MARIANUS) != text("/i/ak/ova", ASSEMANIANUS)


def test_assemanianus_dash_is_punctuation_not_a_lacuna():
    # Its "-" never touches a word: the scribe's dash after a stop (#368).
    conv = convert("sv/i grad& :: . -", ASSEMANIANUS)
    assert conv.text == "сви\u0301 градъ⁘ . –" and conv.editorial == []
    assert text("d@latelem& - /JZe", ASSEMANIANUS) == "дѣлателемъ – ꙇ\u0301же"
    assert convert("-to", MARIANUS).editorial == [[0, 1, "lacuna"]]   # Marianus's "-" still is


def test_punctuation():
    assert text("a :. b :: c :- d -- e : f") == "а⁖ б⁘ в⁛ д⁓ е: ф".replace("в", "ц")
    assert text("x& :: ::") == "хъ⁘ ⁘"                # two marks keep their space


def test_editorial_spans():
    conv = convert("blagov[o]lix& . v& {mEr} mEr . =sti= ?a -to %", MARIANUS)
    assert conv.text == "благов[о]лихъ. въ {мѧр} мѧр. сти ?а -то"
    spans = [(conv.text[s:e], kind) for s, e, kind in conv.editorial]
    assert spans == [("[о]", "supplement"), ("{мѧр}", "note"), ("сти", "supplement"),
                     ("?", "lacuna"), ("-", "lacuna")]
    assert conv.dropped == {"%": 1}
    chunk = {"text": conv.text, "editorial": conv.editorial}
    assert editorial.source_text(chunk) == "благоволихъ. въ мѧр. сти а то"


def test_zogr_b_brackets_and_unbalanced_markup():
    conv = convert("uCenikom<&> svoim& .", ZOGR_B)
    assert conv.text == "оученикомꙿ своимъ.".replace("ꙿ", "\u27e8ъ\u27e9")
    assert conv.editorial == [[9, 12, "supplement"]]
    stray = convert("s&tvorim =", ASSEMANIANUS)
    assert stray.text == "сътворим" and stray.editorial == []


def test_unknown_characters_are_reported():
    assert convert("a#b", MARIANUS).unknown == {"#": 1}


def test_join_lines():
    assert join_lines(["razli-", "-C$n&"]) == "razliC$n&"
    assert join_lines(["v& sjO-", "botO ."]) == "v& sjObotO ."
    assert join_lines(["razdr@Se", "<-n&> na"]) == "razdr@Se<n&> na"
    assert join_lines(["grEdO . -", "x"]) == "grEdO . - x"


def test_lectionary_keeps_the_first_reading():
    lines = [("1010100", "*a"), ("1010110", "b"), ("1010101", "*v& (ono!v . a"),
             ("1010200", "c")]
    gt = parse_gospels(lines)
    books, unknown, _ = gospel_books(gt, MARIANUS)
    assert [u["text"] for u in books[0].verses] == ["А б", "ц"]
    assert books[0].repeats_dropped == 1 and not unknown and not books[0].later_readings


def _reading(ascii_text: str) -> _ccmh.Converted:
    return convert(ascii_text, MARIANUS)


def test_a_cut_short_first_reading_gives_way_to_the_full_verse():
    # Savvina Matt 10:40: the first reading lacks the verse's second clause (#370).
    full = "prijemlEi vas& mene prijemlet& . a prijemlEi mene prijemlet& pos&lav&Sago mE ."
    reference = _ccmh.comparable(_reading(full))
    readings = {"0": _reading("prijemlEi vas& mene prijemlet& ."), "1": _reading(full)}
    assert _ccmh.choose_reading(readings, reference) == "1"
    # Without a continuous text to compare with, the first is kept.
    assert _ccmh.choose_reading(readings, None) == "0"


def test_a_lection_formula_or_other_wording_keeps_the_first_reading():
    verse = "jegda pridet& !sn& !Clsky v& slav@ svojeI . i vsi !stiI !aggli s& nim$ ."
    reference = _ccmh.comparable(_reading(verse))
    # A later reading that only adds a lection formula is not "fuller".
    formula = {"0": _reading(verse), "1": _reading("*reCe !g$ . uCenikom& svoim& . " + verse)}
    assert _ccmh.choose_reading(formula, reference) == "0"
    # Nor is one that is only worded differently, though it is closer to the reference.
    wording = {"0": _reading("jegda pride !sn& v& slav@ svoei . i vsi angeli s& nim$ ."),
               "1": _reading(verse)}
    assert _ccmh.choose_reading(wording, reference) == "0"


def test_lectionary_book_records_the_later_reading():
    gt = parse_gospels([("1104000", "prijemlEi vas& mene prijemlet& ."),
                        ("1104001", "prijemlEi vas& mene prijemlet& . a prijemlEi mene "
                                    "prijemlet& pos&lav&Sago mE .")])
    full = _ccmh.comparable(_reading("prijemlEi vas& mene prijemlet& . a prijemlEi mene "
                                     "prijemlet& pos&lav&Sago mE ."))
    books, _, _ = gospel_books(gt, MARIANUS, {("1", 10, 40): full})
    assert books[0].later_readings == [("Matt.10.40", "1")]
    assert books[0].verses[0]["text"].endswith("посълавъшаго мѧ.")


def test_chapter_lists_are_title_units_in_chapter_0():
    # Marianus Mark's list (#369): the title line is 0, each later line its own
    # unit; a word broken over two lines (Zographensis) joins its first line.
    lines = [("2000010", "*g*l*a!v *e*v*n*&!G*l*i*@ *e*Z*e *o*t*& *m*a*r*&*k*a :: ::"),
             ("2000020", "!a *o b@s&nujOStiim& . ::"),
             ("2000030", "*w (Jc@l@v&SIx& ot& razli-"), ("2000040", "-C$n& nedOg& : +"),
             ("2000050", "*w t$Sti petrov@ : +"),
             ("2010100", "*zaCElo !evan$Gli@ !isxva !sna !bZi@ .")]
    gt = parse_gospels(lines)
    assert gt.lists == {"2": [(1, lines[0][1]), (2, lines[1][1]), (3, lines[2][1]),
                              (4, lines[3][1]), (5, lines[4][1])]}
    books, unknown, _ = gospel_books(gt, ZOGRAPHENSIS)
    assert not unknown
    units = books[0].verses
    assert [u["ref"] for u in units] == ["Mark.0.0", "Mark.0.1", "Mark.0.2", "Mark.0.4", "Mark.1.1"]
    assert units[2]["text"] == "Ѡ ꙇ\u0485цѣлѣвъшіхъ отъ различьнъ недѫгъ: ✝"
    for u in units[:4]:
        assert u["editorial"] == [[0, len(u["text"]), "title"]]
        assert editorial.source_text(u) == ""
    assert books[0].list_units == 4
    assert "editorial" not in units[4]


def test_chapter_list_refs_are_their_own_versification_group():
    from patristica.versification import to_org_ref
    assert to_org_ref("ccmh-marianus", "Mark.0.3") == "Mark.0.3"


def test_renumbered_lines_and_lection_titles():
    gt = parse_gospels([("3105500", "a"), ("3020010", "*v& veCer& :: ::")], {"3105500": "3015500"})
    books, _, _ = gospel_books(gt, MARIANUS)
    units = {u["ref"]: u for u in books[0].verses}
    assert set(units) == {"Luke.1.55", "Luke.2.0"}
    assert units["Luke.2.0"]["editorial"] == [[0, len(units["Luke.2.0"]["text"]), "title"]]


def test_zogr_b_leaves_fill_the_gap():
    main = parse_gospels([("1161900", "a"), ("1161910", "razdr@Se"), ("1242010", "botO ."),
                          ("1242100", "b")])
    leaves = parse_gospels([("1161930", "<-n&> na"), ("1170100", "F"), ("1242000", "zim@ v& sjO-")])
    books, unknown, _ = gospel_books(merge_leaves(main, leaves, ZOGR_B), ZOGRAPHENSIS)
    assert not unknown
    assert [(u["ref"], u["text"]) for u in books[0].verses] == [
        ("Matt.16.19", "а раздрѣше\u27e8нъ\u27e9 на"), ("Matt.17.1", "ф"),
        ("Matt.24.20", "зимѣ въ сѭботѫ."), ("Matt.24.21", "б")]


def test_output_is_cyrillic_and_folds():
    out = text("!glE . az& tr@bujO ot& tebe kr$stiti sE", ZOGRAPHENSIS)
    letters = [c for c in out if c.isalpha() or unicodedata.category(c) == "Mn"]
    assert _script_ratio("".join(letters), _SCRIPT_RES["chu"]) == 1.0
    assert fold(out) == fold("глѧ. азъ трѣбоуѭ от тебе крьстити сѧ")


RAW = Path(__file__).resolve().parents[1] / "data" / "raw"


@pytest.mark.parametrize("source", ["ccmh-marianus", "ccmh-zographensis", "ccmh-assemanianus",
                                    "ccmh-savvina"])
def test_ingested_codices(source):
    path = RAW / source / "Matt.json"
    if not path.exists() or path.read_bytes().startswith(b"version https://git-lfs"):
        pytest.skip(f"data/raw/{source} not materialized")
    record = json.loads(path.read_text(encoding="utf-8"))
    refs = [u["ref"] for u in record["verses"]]
    assert len(refs) == len(set(refs))
    for unit in record["verses"]:
        editorial.check(unit["text"], unit.get("editorial", []), unit["ref"])
        assert not any(c in unit["text"] for c in "&$@*!%=")   # no ASCII markup left


def test_tables_are_distinct_objects():
    # Every table the ingestors use is defined (a renamed one would fail here).
    assert {t.name for t in (_ccmh.MARIANUS, _ccmh.ZOGRAPHENSIS, _ccmh.ZOGR_B, _ccmh.ASSEMANIANUS,
                             _ccmh.SAVVINA, _ccmh.VITAE)} == {
        "Codex Marianus", "Codex Zographensis", "Codex Zographensis, Zogr-B",
        "Codex Assemanianus", "Savvina kniga", "Vitae Constantini et Methodii"}


def test_lection_marks_are_metadata_but_the_preposition_za_is_text():
    conv = convert("tu i !srdce vaSe . k!c ::", MARIANUS)
    assert conv.text == f"тоу и ср{TITLO}дце ваше. кⷰ{POKRYTIE}⁘"   # ц above the line
    (s, e, kind), = conv.editorial
    assert (conv.text[s:e], kind) == (f"кⷰ{POKRYTIE}", "metadata")
    assert "кⷰ" not in editorial.source_text({"text": conv.text, "editorial": conv.editorial})
    assert convert("!za!C v& ono vr@mE", ZOGRAPHENSIS).editorial[0][2] == "metadata"
    assert convert("za nE", MARIANUS).editorial == []       # за "for", not зачѧло


def test_a_dot_opening_a_numeral_keeps_its_space():
    assert text("s&t& i ./i/i. ot$c$", VITAE) == f"сътъ и .и{TITLO}и{TITLO}. отьць"
    assert text("s&t& i . ot$c$", VITAE) == "сътъ и. отьць"
    assert text("Clvkom& .pride") == "члвкомъ. приде"   # a stop against the next word
    assert text("iz-d-raja", VITAE) == "из-д-раꙗ"         # the Vitae's hyphen
    assert text("v@k[om& .] amin$") == "вѣк[омъ.] аминь"
    assert text("esm& ..") == "есмъ.."
