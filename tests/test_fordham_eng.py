"""Tests for the Internet Medieval Sourcebook ingestor (#352), on inline fixtures."""

from __future__ import annotations

import pytest

from patristica.models import Work
from scripts.ingest import fordham_eng as f
from scripts.ingest.fordham_eng import Line, Run


def _span_texts(unit: f.Unit) -> list[tuple[str, str]]:
    return [(unit.text[s:e], k) for s, e, k in unit.spans]


# ---------------------------------------------------------------------------
# HTML blocks and inline editorial material
# ---------------------------------------------------------------------------

def test_html_blocks_keep_bold_and_hyphens() -> None:
    src = ("<html><body><script>x</script><p><center><b>1.</b></center></p>"
           "<p class='H_body_text'>an eye&#173;witness<br/>of it</p></body></html>")
    blocks = f.html_blocks(src)
    assert blocks == [f.B + "1." + f.B_END, "an eye-witness of it"]


def test_inline_unit_marks_notes_and_scripture_and_drops_layout() -> None:
    block = (f.B + "T4" + f.B_END + " the armour of God [Eph. 6:13]. He was there "
             "[" + f.I + f.B + "note:" + f.B_END + " the Arians" + f.I_END + "] {Halsall's aside} today.")
    unit = f.inline_unit("X.1.1", block)
    assert unit.text == "the armour of God [Eph. 6:13]. He was there [the Arians] today."
    assert _span_texts(unit) == [("[Eph. 6:13]", "note"), ("[the Arians]", "note")]


def test_inline_unit_keeps_translator_supplements() -> None:
    unit = f.inline_unit("X.1.1", "[I believe] that he has always been")
    assert unit.text == "[I believe] that he has always been"
    assert unit.spans == []


# ---------------------------------------------------------------------------
# Porphyry
# ---------------------------------------------------------------------------

def _porphyry_blocks(chapters: int) -> list[str]:
    blocks = ["Navigation", "PREFACE", "THE present translation ...",
              f.B + "BIBLIOGRAPHY" + f.B_END, "Teubner 1895.",
              f.B + "THE LIFE OF SAINT PORPHYRY, BISHOP OF GAZA" + f.B_END]
    for n in range(1, chapters + 1):
        blocks += [f.B + f"{n}." + f.B_END, f"Chapter {n} text {f.B}T{n}{f.B_END} goes on."]
        if n == 2:
            blocks += [f.B + "NOTES:" + f.B_END, f.I + "lemma." + f.I_END + " A note."]
    blocks += ["Additional Information on The Life", "Halsall's own summary."]
    return blocks


def test_parse_porphyry() -> None:
    units = f.parse_porphyry(_porphyry_blocks(103))
    by_ref = {u.ref: u for u in units}
    assert by_ref["VPorph.int.1"].spans == [[0, 7, "heading"]]
    assert by_ref["VPorph.int.2"].spans[0][2] == "note"
    assert by_ref["VPorph.int.3"].spans[0][2] == "heading"
    assert by_ref["VPorph.1.1"].text == "Chapter 1 text goes on."
    assert by_ref["VPorph.2.2"].text == "Notes: lemma. A note."
    assert by_ref["VPorph.2.2"].spans == [[0, len("Notes: lemma. A note."), "note"]]
    assert "Halsall" not in " ".join(u.text for u in units)
    assert units[-1].ref == "VPorph.103.1"


def test_parse_porphyry_checks_chapters() -> None:
    with pytest.raises(f.FordhamParseError):
        f.parse_porphyry(_porphyry_blocks(102))


# ---------------------------------------------------------------------------
# Gregory
# ---------------------------------------------------------------------------

def _gregory_blocks() -> list[str]:
    b = f.B + "{}" + f.B_END
    blocks = ["INTRODUCTORY COMMENTS", "Halsall's comments.", "INTRODUCTION",
              "By Earnest Brehaut, [from his 1916 translation]",
              "[Note: Many of Brehaut's opinions ...]", "The History of the Franks ...", "E. B.",
              "PREFACE", "HERE BEGINS GREGORY'S FIRST PREFACE", "With liberal culture on the wane."]
    for n, roman in enumerate(["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"], 1):
        blocks += [f"BOOK {roman}", "HERE BEGIN THE CHAPTERS OF THE BOOK",
                   b.format("1. Adam and Eve"), "2. Cain and Abel."]
        if n != 9:  # Book IX's list has no explicit
            blocks.append("HERE END THE CHAPTERS")
        blocks += ["------", "HERE BEGINS THE BOOK", "A prologue.",
                   b.format("1."), "Chapter one, [I believe] [" + f.I + "note: a note" + f.I_END + "].",
                   "[" + b.format("2.") + " Summary of two. " + b.format("3.") + " Of three.]",
                   b.format("3.") + " The rest of three."]
        if n == 8:
            blocks += [b.format("20."), "Exstitit enim in hac synodo ...", "There came forward ...",
                       "[-see article by Michael Nolan]"]
    blocks += ["Source:", "Bibliography"]
    return blocks


def test_parse_gregory() -> None:
    units = f.parse_gregory(_gregory_blocks())
    by_ref = {u.ref: u for u in units}
    assert by_ref["HF.int.1"].spans == [[0, 12, "heading"]]
    assert not any("Many of Brehaut" in u.text for u in units)
    assert by_ref["HF.0.1"].spans[0][2] == "heading"
    assert by_ref["HF.0.2"].text == "With liberal culture on the wane."
    assert by_ref["HF.1"].text == "Book I"
    assert by_ref["HF.1.0.1"].spans[0][2] == "heading"
    assert by_ref["HF.1.0.2"].text == "1. Adam and Eve 2. Cain and Abel."
    assert by_ref["HF.1.0.2"].spans == []
    assert by_ref["HF.1.0.3"].text == "HERE END THE CHAPTERS"
    assert by_ref["HF.1.0.5"].text == "A prologue."
    assert by_ref["HF.1.1.1"].text == "Chapter one, [I believe] [a note]."
    assert _span_texts(by_ref["HF.1.1.1"]) == [("[a note]", "note")]
    # A summary is filed under the first chapter it covers; the rest of 3 follows it.
    assert by_ref["HF.1.2.1"].spans[0][2] == "note"
    assert by_ref["HF.1.3.1"].text == "The rest of three."
    # Book IX: the list ends at the incipit.
    assert by_ref["HF.9.0.2"].text == "1. Adam and Eve 2. Cain and Abel."
    assert by_ref["HF.9.0.3"].text == "HERE BEGINS THE BOOK"
    # VIII 20 is Halsall's insertion, not Brehaut.
    assert not any(u.ref.startswith("HF.8.20.") for u in units)
    assert not any("Exstitit" in u.text or "Nolan" in u.text for u in units)


# ---------------------------------------------------------------------------
# Isidore (PDF lines)
# ---------------------------------------------------------------------------

def _ln(page: int, x: float, y: float, *runs: tuple[float, str]) -> Line:
    return Line(page, x, y, [Run(s, t) for s, t in runs])


def _isidore_lines() -> list[Line]:
    return [
        _ln(1, 287, 700, (11.0, "BOOK"), (9.0, " "), (11.0, "I")),
        _ln(1, 268, 680, (10.0, "INTRODUCTION")),
        _ln(1, 122, 660, (11.0, "Grammar did not appear"), (6.5, "1")),
        _ln(1, 280, 640, (10.0, "EXTRACTS")),
        _ln(1, 112, 620, (11.0, "Chapter 2. On the seven liberal arts."), (6.5, "2")),
        _ln(1, 122, 600, (11.0, "1.  The  disciplines  are  seven.  First,  well-")),
        _ln(1, 112, 590, (11.0, "known, that is, "), (8.0, "[96]"), (11.0, " the γραµµατική.")),
        _ln(1, 122, 580, (11.0, "2. Fourth, arithmetic.")),
        _ln(1, 112, 207, (6.5, "1")),
        _ln(1, 121, 202, (8.0, " Sandys.")),
        _ln(1, 112, 190, (6.5, "2")),
        _ln(1, 121, 185, (8.0, " Du Breul has")),
        _ln(1, 301, 162, (8.0, "57")),
        _ln(2, 112, 700, (8.0, "disciplinis.")),  # a note continued on the next page
        _ln(2, 112, 680, (11.0, "Chapter 68.")),
        _ln(2, 122, 660, (11.0, "1. Praecedentia of stars.")),
        _ln(2, 122, 640, (11.0, "1. Again.")),
        _ln(2, 270, 620, (13.0, "BOOK X")),
        _ln(2, 280, 600, (10.0, "EXTRACTS")),
        _ln(2, 122, 580, (11.0, "44. Compilator, one who mixes words.")),
        _ln(2, 270, 560, (13.0, "APPENDIX I")),
        _ln(2, 122, 540, (11.0, "Further light.")),
    ]


def test_pdf_notes() -> None:
    notes = f.pdf_notes(_isidore_lines())
    assert notes == {1: "Sandys.", 2: "Du Breul has disciplinis."}


def test_parse_isidore() -> None:
    units = f.parse_isidore(_isidore_lines())
    by_ref = {u.ref: u for u in units}
    assert list(by_ref) == ["Etym.1.2", "Etym.1.2.1", "Etym.1.2.2", "Etym.1.68",
                            "Etym.1.68.1", "Etym.1.68.1b", "Etym.10.44"]
    heading = by_ref["Etym.1.2"]
    assert heading.text == "Chapter 2. On the seven liberal arts. [Du Breul has disciplinis.]"
    assert heading.spans == [[0, len(heading.text), "heading"]]
    assert by_ref["Etym.1.2.1"].text == "The disciplines are seven. First, well-known, that is, the γραμματική."
    assert by_ref["Etym.10.44"].text == "Compilator, one who mixes words."
    assert not any("Grammar did not" in u.text or "Further light" in u.text for u in units)


def test_parse_isidore_needs_footnote_text() -> None:
    lines = [_ln(1, 287, 700, (11.0, "BOOK I")), _ln(1, 280, 640, (10.0, "EXTRACTS")),
             _ln(1, 112, 620, (11.0, "Chapter 2. On arts.")),
             _ln(1, 122, 600, (11.0, "1. Text."), (6.5, "9"))]
    with pytest.raises(f.FordhamParseError):
        f.parse_isidore(lines)


# ---------------------------------------------------------------------------
# Works
# ---------------------------------------------------------------------------

def test_works_link_their_originals() -> None:
    works = {t.slug: f._work(t) for t in f.TEXTS}
    assert all(isinstance(w, Work) and w.language == "eng" and w.license == "public_domain"
               for w in works.values())
    assert works["mark-the-deacon-life-of-porphyry"].translation_of == "first1k/tlg2806/tlg001/1st1K-grc1"
    assert works["gregory-of-tours-history-of-the-franks"].translation_of == \
        "oglt-pl/gregorius-turonensis/pl71_0_s."
    assert works["isidore-etymologies-brehaut"].translation_of == "oglt-pl/isidorus-hispalensis/pl82_0_san"
    assert all(w.work_id.startswith("fordham-eng/") for w in works.values())
