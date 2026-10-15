"""Tests for patristica.section_numbers and its use in normalize/validate (#30)."""

from __future__ import annotations

import pytest

from patristica.section_numbers import leading_section_number, strip_section_number
from scripts.normalize import normalize_patristic_work, normalize_scripture_work
from scripts.validate import _check_section_numbers


@pytest.mark.parametrize(
    ("text", "ref", "lang", "expected"),
    [
        # Arabic forms
        ("3 Αὐτοκράτορι Καίσαρι", "tlg0317.tlg002.3", "grc", "Αὐτοκράτορι Καίσαρι"),
        ("1. Great art Thou, O Lord", "Aug.Conf.I.I.1", "eng", "Great art Thou, O Lord"),
        ("[3] And when Jesus came", "Tat.Diat.XXII.3", "eng", "And when Jesus came"),
        ("(9) Οὗ τὰς προσευχὰς", "x.9", "grc", "Οὗ τὰς προσευχὰς"),
        ("4) He will judge", "Iren.Haer.4.4", "eng", "He will judge"),
        ("2. Εί δέ τύχοι", "ByzTyp.Dec.0002", "grc", "Εί δέ τύχοι"),  # zero-padded ref
        (
            "9. John, the apostle and evangelist.",
            "Hier.Vir.9",
            "eng",
            "John, the apostle and evangelist.",
        ),
        # Greek numerals
        ("α. Πᾶσαι μὲν ἅγιαι", "pta0002.pta161.1.1.1", "grc", "Πᾶσαι μὲν ἅγιαι"),
        ("ιβʹ. Καὶ πάλιν", "a.12", "grc", "Καὶ πάλιν"),
        ("κγ΄. Καὶ πάλιν", "a.23", "grc", "Καὶ πάλιν"),
        ("η΄ Περὶ τοῦ φόρου", "pta0036.pta001.3.pinax.8", "grc", "Περὶ τοῦ φόρου"),
        ("ϛ. Εἰ βούλει", "a.6", "grc", "Εἰ βούλει"),
        ("στʹ Εἰ βούλει", "a.6", "grc", "Εἰ βούλει"),
        # Roman numerals (punctuation required)
        (
            "IV. Whether the Soul is Incorporeal.",
            "PsGregThaum.4.IV",
            "eng",
            "Whether the Soul is Incorporeal.",
        ),
        ("I. Festal Letters.", "Ath.EpFest.I", "eng", "Festal Letters."),
    ],
)
def test_strips_matching_number(text: str, ref: str, lang: str, expected: str) -> None:
    assert strip_section_number(text, ref, lang) == expected


@pytest.mark.parametrize(
    ("text", "ref", "lang", "source_id"),
    [
        # number differs from the ref
        ("3. Great art Thou", "Aug.Conf.I.I.1", "eng", None),
        ("γ. Πᾶσαι", "a.4", "grc", None),
        # no separator / decimals / verse refs / runs of numbers
        ("3.5 cubits long", "a.3", "eng", None),
        ("3:16 For God so loved", "a.3", "eng", None),
        ("3 4 5 6", "a.3", "eng", None),
        ("27. 0 fallax, lætitia", "PL16.SA.27", "lat", None),
        # nothing left but the number
        ("3.", "a.3", "eng", None),
        ("3 —", "a.3", "eng", None),
        # scripture citations after a bare number
        ("1 Cor. i. 1–3", "Chrys.Hom1Cor.I.1", "eng", None),
        ("1 Timothy i. 1, 2", "Chrys.Hom1Tim.I.1", "eng", None),
        ("1 Thessalonians i. 8–10", "Chrys.Hom1Thess.1.1", "eng", None),
        ("1 Joann. v. 7, 8. Tres sunt testes", "Aug.Tract1Jn.1.1", "lat", None),
        ("2 Βασ. ιβʹ. 3", "a.2", "grc", None),
        # content after a bare number
        ("29 bis. Quosdam igitur spiritus", "PL65.S.29", "lat", None),
        ("8 (al. die 3) kal. decembris.", "PL8.UNKNOWN.13.29.8", "lat", None),
        ("3 id. martii obiit", "a.3", "lat", None),
        # Roman: bare "I" is the English pronoun; lettered subsections
        ("I have become acquainted with your name", "Ign.Eph.i", "eng", None),
        ("C. Julius Caesar", "a.c", "lat", None),
        ("D. Augustinus", "a.d", "lat", None),
        # Greek numerals need a keraia or dot, and only in Greek text
        ("α Πᾶσαι", "a.1", "grc", None),
        ("a. Prima", "a.1", "lat", None),
        # serial-counter refs: any match is a coincidence
        ("(90) Μεταεύ. Α Β μετά.", "ogpg.vol-046.00090", "grc", "ogpg"),
    ],
)
def test_leaves_content_alone(text: str, ref: str, lang: str, source_id: str | None) -> None:
    assert leading_section_number(text, ref, lang, source_id) is None
    assert strip_section_number(text, ref, lang, source_id) == text


def test_bare_book_name_guard_does_not_apply_to_dotted_numbers() -> None:
    assert strip_section_number("1. John who was a torch", "a.1", "eng") == "John who was a torch"


def test_bare_greek_name_without_dot_is_stripped() -> None:
    # "1 Βασιλεύοντος …" starts a sentence; only "1 Βασ." would be a citation.
    assert strip_section_number("1 Βασιλεύοντος τῶν Ἰουδαίων", "tlg0317.tlg001.1", "grc") == (
        "Βασιλεύοντος τῶν Ἰουδαίων"
    )


def test_number_followed_by_digit_is_left_alone() -> None:
    # "11. 2Τριῶν" (a glued line number) is ambiguous: keep it rather than guess.
    assert strip_section_number("3. 3. text", "a.3", "eng") == "3. 3. text"


def test_idempotent_on_stripped_text() -> None:
    once = strip_section_number("12. Time passed", "a.12", "eng")
    assert strip_section_number(once, "a.12", "eng") == once


def _raw(
    genre: str, source_id: str, key: str, items: list[tuple[str, str]], lang: str = "eng"
) -> dict:
    return {
        "work": {
            "work_id": f"{source_id}/w",
            "source_id": source_id,
            "title": "W",
            "language": lang,
            "genre": genre,
            "license": "public_domain",
            "provenance_url": "https://example.org",
        },
        key: [{"ref": r, "text": t} for r, t in items],
    }


def test_normalize_strips_prose_numbers() -> None:
    raw = _raw(
        "patristic",
        "npnf-works",
        "paragraphs",
        [
            ("Aug.Conf.I.I.1", "  1. Great art Thou, O Lord  "),
            ("Aug.Conf.I.I.2", "And how shall I call upon my God"),
        ],
    )
    _, chunks = normalize_patristic_work(raw)
    assert [c.text for c in chunks] == [
        "Great art Thou, O Lord",
        "And how shall I call upon my God",
    ]
    assert [c.canonical_ref for c in chunks] == ["Aug.Conf.I.I.1", "Aug.Conf.I.I.2"]


def test_normalize_leaves_scripture_alone() -> None:
    raw = _raw("scripture", "kjv", "verses", [("Num.1.3", "3 From twenty years old")])
    _, chunks = normalize_scripture_work(raw)
    assert chunks[0].text == "3 From twenty years old"


def test_validate_flags_remaining_numbers() -> None:
    chunks = [
        {
            "chunk_id": "p/w#a.3",
            "work_id": "p/w",
            "canonical_ref": "a.3",
            "language": "eng",
            "text": "3. Left over",
        },
        {
            "chunk_id": "p/w#a.4",
            "work_id": "p/w",
            "canonical_ref": "a.4",
            "language": "eng",
            "text": "Clean",
        },
        {
            "chunk_id": "s/w#Num.1.3",
            "work_id": "s/w",
            "canonical_ref": "Num.1.3",
            "language": "eng",
            "text": "3 From twenty years old",
        },
    ]
    entries = {
        "p/w": {"source_id": "npnf-works", "genre": "patristic"},
        "s/w": {"source_id": "kjv", "genre": "scripture"},
    }
    result = _check_section_numbers(chunks, entries)["text_starts_with_section_number"]
    assert result["status"] == "warn"
    assert result["violation_count"] == 1
    assert result["examples"] == ["p/w#a.3 ('3.')"]


# --- #121: superscript and glued numbers -------------------------------------


@pytest.mark.parametrize(
    ("text", "ref", "lang", "expected"),
    [
        # superscript digits, glued or followed by a space
        ("⁴καὶ ὁ θεὸς τοῦ αἰῶνος", "tlg1463.tlg001.1.4", "grc", "καὶ ὁ θεὸς τοῦ αἰῶνος"),
        ("¹¹ Καὶ εἶπεν Μιχαὴλ", "tlg1463.tlg001.10.11", "grc", "Καὶ εἶπεν Μιχαὴλ"),
        ("²AI δὲ ἐν γαστρὶ", "tlg1463.tlg001.7.2", "grc", "AI δὲ ἐν γαστρὶ"),
        # mixed runs where OCR lost the superscript on one digit
        ("¹7τὸ ἔδαφος αὐτοῦ", "tlg1463.tlg001.14.17", "grc", "τὸ ἔδαφος αὐτοῦ"),
        ("1¹καὶ αἱ στέγαι", "tlg1463.tlg001.14.11", "grc", "καὶ αἱ στέγαι"),
        # Arabic digits glued to the word
        ("3Καὶ περὶ τῶν ἐκλεκτῶν", "tlg1463.tlg001.1.3", "grc", "Καὶ περὶ τῶν ἐκλεκτῶν"),
        ("18Ἐθεώρουν δὲ", "tlg1463.tlg001.14.18", "grc", "Ἐθεώρουν δὲ"),
        ("2.δι’ ἣν καὶ ἀπετάξατο", "tlg1271.tlg010.1.4.2", "grc", "δι’ ἣν καὶ ἀπετάξατο"),
        ("4.Principium vero", "tlg2042.tlg021.17.4", "lat", "Principium vero"),
        ("29.Virga enim furoris", "PL83.21.10.1.29", "lat", "Virga enim furoris"),
        ("[3]And when Jesus came", "a.3", "eng", "And when Jesus came"),
        ("(3)Καὶ πάλιν", "a.3", "grc", "Καὶ πάλιν"),
    ],
)
def test_strips_superscript_and_glued_numbers(
    text: str, ref: str, lang: str, expected: str
) -> None:
    assert strip_section_number(text, ref, lang) == expected
    # idempotent
    assert strip_section_number(expected, ref, lang) == expected


@pytest.mark.parametrize(
    ("text", "ref", "lang", "source_id"),
    [
        # damaged superscript that does not equal the ref: left for validate
        ("⁰Καὶ ἀναλαβὼν", "tlg1463.tlg001.1.2", "grc", None),
        ("²⁸καὶ καθαρισθήσεται", "tlg1463.tlg001.10.22", "grc", None),
        # glued number that differs from the ref
        ("420Η πολλῷ πλέον", "tlg2042.tlg005.32.382", "grc", None),
        # English ordinals and lettered numbers
        ("1st. That Joseph was only putatively", "Jer.Helv.1", "eng", None),
        ("2d. That the brethren", "Jer.Helv.2", "eng", None),
        ("3rd of the month", "a.3", "eng", None),
        ("4th day", "a.4", "eng", None),
        ("3a. I have wandered", "Jer.Ep.CXXVIII.3", "eng", None),
        ("3o. What, then", "a.3", "eng", None),
        # one-letter note marker and short abbreviations after a glued number
        ("1.a Tantis exstantibus", "PL48.III.3.1", "lat", None),
        ("4.col.a. ὅτε δὲ ὡς ἐν πυρὶ", "tlg1750.tlg002.4.4", "grc", None),
        # glued citation
        ("1Cor. 13, 4", "a.1", "eng", None),
        # decimals and glued numbers followed by digits
        ("3.5 cubits", "a.3", "eng", None),
        ("3²", "a.3", "eng", None),
        # mid-chunk superscripts are never touched
        ("κρίμα ὲ́νδικόν ἐστι².", "tlg2021.tlg002.26.11.2", "grc", None),
        # serial-counter refs
        ("¹ῑ μάθημα τι", "ogpg.vol-003.p0294.1", "grc", "ogpg"),
        ("1νιι, c. l9", "ogpg.vol-005.c0231.1", "grc", "ogpg"),
    ],
)
def test_leaves_superscript_and_glued_content_alone(
    text: str, ref: str, lang: str, source_id: str | None
) -> None:
    assert leading_section_number(text, ref, lang, source_id) is None


def test_normalize_strips_superscript_numbers_in_apocrypha() -> None:
    raw = _raw(
        "apocrypha",
        "first1k",
        "paragraphs",
        [
            ("tlg1463.tlg001.1.2", "⁰Καὶ ἀναλαβὼν"),
            ("tlg1463.tlg001.1.3", "3Καὶ περὶ τῶν ἐκλεκτῶν"),
            ("tlg1463.tlg001.1.4", "⁴καὶ ὁ θεὸς"),
        ],
        lang="grc",
    )
    _, chunks = normalize_patristic_work(raw)
    assert [c.text for c in chunks] == ["⁰Καὶ ἀναλαβὼν", "Καὶ περὶ τῶν ἐκλεκτῶν", "καὶ ὁ θεὸς"]


def test_validate_flags_superscript_forms_and_stray_digits() -> None:
    chunks = [
        {
            "chunk_id": "p/w#a.4",
            "work_id": "p/w",
            "canonical_ref": "a.4",
            "language": "grc",
            "text": "⁴καὶ ὁ θεὸς",
        },
        {
            "chunk_id": "p/w#a.5",
            "work_id": "p/w",
            "canonical_ref": "a.5",
            "language": "grc",
            "text": "⁰καὶ ἤρξαντο",
        },
        {
            "chunk_id": "p/w#a.6",
            "work_id": "p/w",
            "canonical_ref": "a.6",
            "language": "grc",
            "text": "Clean",
        },
        {
            "chunk_id": "s/w#Num.1.3",
            "work_id": "s/w",
            "canonical_ref": "Num.1.3",
            "language": "cop",
            "text": "ⲡⲉϫⲁϥ · ¹ ϯⲣⲁϣⲉ",
        },
    ]
    entries = {
        "p/w": {"source_id": "first1k", "genre": "apocrypha"},
        "s/w": {"source_id": "coptic-nt", "genre": "scripture"},
    }
    result = _check_section_numbers(chunks, entries)
    dup = result["text_starts_with_section_number"]
    assert dup["violation_count"] == 1
    assert dup["examples"] == ["p/w#a.4 ('⁴')"]
    stray = result["text_has_superscript_digits"]
    assert stray["status"] == "warn"
    assert stray["violation_count"] == 3
    assert [e.split(" ")[0] for e in stray["examples"]] == ["p/w#a.4", "p/w#a.5", "s/w#Num.1.3"]
