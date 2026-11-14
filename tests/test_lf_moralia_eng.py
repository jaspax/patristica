"""The Library of the Fathers *Moralia* from Lectionary Central (#348)."""

from __future__ import annotations

import pytest

from patristica import editorial
from scripts.ingest import lf_moralia_eng as lf


def _page(*paras: str) -> str:
    nav = '<p><a href="../index.html">Home</a> <a href="Book02.html">Book II</a></p>'
    body = "".join(f"<p>{p}</p>" for p in paras)
    return f"<html><body>{nav}{body}<p><a href='index.html'>Moralia Index</a></p></body></html>"


_HEADER = (
    "THE", "BOOKS OF THE MORALS", "________",
    "VOLUME I - THE FIRST PART.", "________", "BOOK I.",
    'The first verses are explained <a href="#hist">historically</a>,',
    "then in a moral sense.",
)


def _by_ref(records: list[dict]) -> dict[str, dict]:
    return {r["ref"]: r for r in records}


@pytest.mark.parametrize("printed, kept", [
    ([1, 2, 3], [1, 2, 3]),
    ([4, 5, 5, 7], [4, 5, 6, 7]),           # a repeated number fills the gap
    ([52, 58, 54, 5, 56], [52, 53, 54, 55, 56]),
    ([56, 57, 58, 32, 59], [56, 57, 58, None, 59]),  # a verse number, not a section
    ([None, 2, None, 3], [None, 2, None, 3]),
    ([81, 82, 82], [81, 82, 83]),            # a misprint at the end
    ([], []),
])
def test_validate_numbers(printed: list[int | None], kept: list[int | None]) -> None:
    assert lf.validate_numbers(printed) == kept


def test_roman() -> None:
    assert [lf.roman(s) for s in ("i", "iv", "xix", "XLII", "lxix")] == [1, 4, 19, 42, 69]


def test_book_page_sections_chapters_and_marks() -> None:
    html = _page(
        *_HEADER,
        "HISTORICAL INTERPRETATION.",
        "1. <i>There was a man.</i> [Job 1, 1] It is for this reason.",
        "And that man was simple [so Vulg.] and upright.",
        "[ii]",
        "2. For there are some in such wise simple [c] as not to know.",
        "[iii]",
        "Greater wealth usually becomes the cause of discord. " * 6,
        "[iv] [ALLEGORICAL INTERPRETATION]",
        "Ver. 2. And there were born unto him seven sons.",
        "2. What is conveyed to us in the number of seven.",   # misprint for 3
        "4. The Apostles.",
    )
    page = lf.parse_page(html)
    assert page.key == "1" and page.part == "THE FIRST PART"
    records = _by_ref(lf.page_records(page, None))
    assert list(records) == ["Greg.Mor.1", "Greg.Mor.1.1.1", "Greg.Mor.1.2.2",
                             "Greg.Mor.1.4.3", "Greg.Mor.1.4.4"]

    title = records["Greg.Mor.1"]
    assert title["text"] == ("THE FIRST PART. BOOK I. The first verses are explained "
                             "historically, then in a moral sense.")
    assert title["editorial"] == [[0, len(title["text"]), "title"]]

    first = records["Greg.Mor.1.1.1"]
    assert first["text"].startswith("HISTORICAL INTERPRETATION There was a man.")
    assert editorial.strip(first["text"], first["editorial"]) == "There was a man. It is for this reason."

    # The lemma goes with the section after it, the stray letter marker is
    # dropped, and a chapter marker inside a section stays as a note.
    second = records["Greg.Mor.1.2.2"]
    assert second["text"].startswith("And that man was simple [so Vulg.] and upright. For there")
    assert "[c]" not in second["text"]
    assert "[iii] Greater wealth" in second["text"]
    assert editorial.strip(second["text"], second["editorial"]).startswith(
        "And that man was simple and upright. For there are some")
    assert "[iii]" not in editorial.strip(second["text"], second["editorial"])

    third = records["Greg.Mor.1.4.3"]
    assert third["text"].startswith("ALLEGORICAL INTERPRETATION Ver. 2. And there were born")
    assert third["editorial"][0] == [0, len("ALLEGORICAL INTERPRETATION"), "heading"]


def test_part_is_named_only_when_it_changes() -> None:
    page = lf.parse_page(_page(*_HEADER, "1. Text."))
    assert lf.page_records(page, "THE FIRST PART")[0]["text"].startswith("BOOK I.")


def test_unnumbered_opening_and_long_argument() -> None:
    opening = "IT is the case for the most part in Holy Writ. " * 10
    html = _page(
        "VOLUME II - THE FOURTH PART.", "BOOK XVIII.",
        "Contains the exposition of the twenty-seventh", "chapter.",
        opening,
        "Chap. xxvii. 1. Moreover Job added taking up his parable.",
        "[i]",
        "2. For in Holy Scripture.",
    )
    records = lf.page_records(lf.parse_page(html), None)
    assert [r["ref"] for r in records] == ["Greg.Mor.18", "Greg.Mor.18.1.1", "Greg.Mor.18.1.2"]
    assert records[0]["text"].endswith("twenty-seventh chapter.")
    assert records[1]["text"] == opening.strip()
    assert records[2]["text"].startswith("Chap. xxvii. 1. Moreover")


def test_book_preface_and_tail_note() -> None:
    html = _page(
        "BOOK IV.", "Wherein Gregory explains.", "THE PREFACE.",
        "HE who looks to the text.", "[ii]", "See here, for instance.",
        "[HISTORICAL INTERPRETATION]",
        "Ver. 1. After this Job opened his mouth.",
        "[i]",
        "1. Holy men.",
        "2. Therefore.",
        "______________________________",
        "Note from §. 2 above:",
        "St. Gregory speaks here [of the Son].",
    )
    records = _by_ref(lf.page_records(lf.parse_page(html), None))
    assert list(records) == ["Greg.Mor.4", "Greg.Mor.4.Praef.1", "Greg.Mor.4.Praef.2",
                             "Greg.Mor.4.1.1", "Greg.Mor.4.1.2"]
    assert records["Greg.Mor.4.Praef.1"]["text"] == "THE PREFACE HE who looks to the text."
    assert records["Greg.Mor.4.Praef.2"]["text"] == "[ii] See here, for instance."
    last = records["Greg.Mor.4.1.2"]
    assert last["text"] == "Therefore. [Note: St. Gregory speaks here [of the Son].]"
    assert editorial.strip(last["text"], last["editorial"]) == "Therefore."


def test_epistle_notes_in_place() -> None:
    html = _page(
        "VOLUME I - THE FIRST PART.", "THE EPISTLE,", "Wherein he explains.", "________",
        "To my fellow Bishop Leander [a],", "Gregory, the servant of God's servants.",
        "I. WHEN I knew you [b] long since.",
        "II. At first however.",
        "______________________________________",
        "[a] Leander, Bishop of Seville [Hispalis].",
        "[b] Responsa, matters of the Roman See.",
        "He was Apocrisiarius.",
        "[e] There",
    )
    records = lf.page_records(lf.parse_page(html), None)
    assert [r["ref"] for r in records] == ["Greg.Mor.Ep", "Greg.Mor.Ep.1", "Greg.Mor.Ep.2"]
    first = records[1]
    assert first["text"] == (
        "To my fellow Bishop Leander [Leander, Bishop of Seville (Hispalis).], Gregory, the "
        "servant of God's servants. WHEN I knew you [Responsa, matters of the Roman See. "
        "He was Apocrisiarius.] long since.")
    assert editorial.strip(first["text"], first["editorial"]) == (
        "To my fellow Bishop Leander , Gregory, the servant of God's servants. "
        "WHEN I knew you long since.")


def test_text_outside_paragraphs_is_kept() -> None:
    html = "<html><body><p>1. Inside.</p> stray text <p>2. Next.</p></body></html>"
    assert lf.paragraphs(html) == ["1. Inside.", "stray text", "2. Next."]


def test_works_link_the_latin_volumes() -> None:
    work = lf._work(lf.WORKS[0])
    assert work.translation_of == "oglt-pl/gregorius-i-magnus/pl75_5_san"
    assert work.language == "eng" and work.license == "public_domain"
    assert lf._work(lf.WORKS[1]).translation_of == "oglt-pl/gregorius-i-magnus/pl76_0_san"
    pages = [p for spec in lf.WORKS for p in spec.pages]
    assert pages == ["Epistle", "Preface"] + [f"Book{n:02d}" for n in range(1, 36)]
