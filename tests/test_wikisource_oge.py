"""Georgian Wikisource, Old Georgian (#513): wikitext to units, chapters, editorial spans."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica import editorial
from scripts.ingest.wikisource_oge import (
    CONVERSION,
    PAGES,
    SHUSHANIK,
    Page,
    georgian_numeral,
    mark_conversion,
    parse_conversion,
    parse_shushanik,
)

_RAW = Path(__file__).resolve().parents[1] / "data" / "raw" / "wikisource-oge"

_SHUSHANIK_PAGE = Page("s", "შუშანიკის წამება", 1, "Shushanik", 2, "t", "a", 480, (475, 484),
                       "approximate", "e")

_SHUSHANIK_WIKITEXT = """{{ანონსი
| სათაური = შუშანიკის წამება
| ავტორი = იაკობ ცურტაველი
|დამატებითი შენიშვნები = „წამებაჲ“ არის ჰაგიოგრაფიული ნაწარმოები.}}
{{სარჩევი მარჯვნივ}}
<div style="float:left; width:85%;">
{{ბლოკი|ტიპი=|პუნქტი=1
|ფაილი=
[[File:Shushanik.jpg|150 px]]
|ტექსტი= იყო, მერვესა წელსა სპარსთა მეფისასა,    კარად სამეფოდ წარემართა.

და უკეთურებისა მის სახისა „მტკი...“ და დადუმნა.
}}
</div>
{{ბლოკი|ტიპი=|პუნქტი=2
|ფაილი=
|კრიტერიუმი=შუშანიკის წამება, II
|ტექსტი=
და იჯმნა მეფისაგან სპარსთაჲსა პიტიახშმან.}}
</div>

[[კატეგორია:იაკობ ცურტაველის ნაწარმოებები]]
"""

_CONVERSION_PAGE = Page("c", "მოქცევაჲ", 1, "MoktsKartl", 4, "t", None, 900, (800, 976),
                        "approximate", "e")

_CONVERSION_WIKITEXT = """[[File:ალავერდის ოთხთავი.png|300px|frameless|left]]
<div style="font-size: 20px;"><center>'''[["მოქცევაჲ ქართლისაჲ"]]'''</center>
==პუბლიკაციები==
*'''[[1890 - ექვთიმე თაყაიშვილი - "სამი ისტორიული ხრონიკა"]]
----

==ტექსტი==
<div style="font-size: 22px;>
     <div class="text">

====<center>'''[თავი ა]'''</center>====

პირველ ოდეს ალექსანდრე მეფემან ნათესავნი იგი წარიქცინა.

ვ~. და მეფობდა არს(ოკ) [და] ქალაქსა ზღუდენი მოაქმნნა.

====<center>'''თავი გ<br>ცხორებაჲ წმიდისა ნინოჲსი'''</center>====

იყო მათ ჟამთა ოდენ გეორგი კაბადუკიელი იწამა,
და მათ-ვე დღეთა მიზეზი\\სათჳს.

====<center>'''თქუმული მისი-ვე'''</center>====

ძალთა ზეცისა მგა....: [აღყ]უავილდა (ვითარცა სწერია და მოვემართე.]

[[კატეგორია:ქართული საისტორიო მწერლობის ძეგლები]]
"""


def test_georgian_numeral() -> None:
    assert [georgian_numeral(n) for n in ("ა", "ე", "ვ", "ჱ", "თ", "ი", "იგ", "კ", "ჟთ")] == [
        1, 5, 6, 8, 9, 10, 13, 20, 99]
    with pytest.raises(ValueError):
        georgian_numeral("ხ")
    with pytest.raises(ValueError):
        georgian_numeral("აა")


def test_shushanik_chapters_and_paragraphs() -> None:
    units = parse_shushanik(_SHUSHANIK_WIKITEXT, _SHUSHANIK_PAGE)
    assert [u["ref"] for u in units] == [
        "Shushanik.1", "Shushanik.1.1", "Shushanik.1.2", "Shushanik.2", "Shushanik.2.1"]
    assert units[0] == {"ref": "Shushanik.1", "text": "I", "editorial": [[0, 1, "heading"]]}
    assert units[3]["text"] == "II"
    # Spaces collapsed, the image and the page's modern note dropped.
    assert units[1]["text"] == "იყო, მერვესა წელსა სპარსთა მეფისასა, კარად სამეფოდ წარემართა."
    # A speaker breaking off is text, not a lacuna.
    assert "editorial" not in units[2]
    assert units[4]["text"] == "და იჯმნა მეფისაგან სპარსთაჲსა პიტიახშმან."


def test_shushanik_chapter_count_is_checked() -> None:
    page = Page("s", "t", 1, "Shushanik", 3, "t", "a", 480, (475, 484), "approximate", "e")
    with pytest.raises(ValueError, match="2 chapters, expected 3"):
        parse_shushanik(_SHUSHANIK_WIKITEXT, page)


def test_conversion_sections() -> None:
    units = parse_conversion(_CONVERSION_WIKITEXT, _CONVERSION_PAGE)
    refs = [u["ref"] for u in units]
    # Numbered by the heading's numeral; an unnumbered section takes the next number.
    assert refs == ["MoktsKartl.1", "MoktsKartl.1.1", "MoktsKartl.1.2",
                    "MoktsKartl.3", "MoktsKartl.3.1", "MoktsKartl.4", "MoktsKartl.4.1"]
    heading = units[3]
    assert heading["text"] == "თავი გ ცხორებაჲ წმიდისა ნინოჲსი"
    assert heading["editorial"] == [[0, len(heading["text"]), "heading"]]
    assert units[0]["text"] == "[თავი ა]"
    # Print lines are joined; the backslash typo is dropped.
    assert units[4]["text"] == "იყო მათ ჟამთა ოდენ გეორგი კაბადუკიელი იწამა, და მათ-ვე დღეთა მიზეზისათჳს."
    for unit in units:
        editorial.check(unit["text"], unit.get("editorial", []), unit["ref"])


def test_conversion_editorial_spans() -> None:
    text = "ვ~. და მეფობდა არს(ოკ) [და] ქალაქსა ზღუდენი მოაქმნნა."
    spans = mark_conversion(text)
    assert [(text[s:e], k) for s, e, k in spans] == [("(ოკ)", "supplement"), ("[და]", "supplement")]
    assert editorial.source_text({"text": text, "editorial": spans}) == \
        "ვ~. და მეფობდა არსოკ და ქალაქსა ზღუდენი მოაქმნნა."
    # Dots are a lacuna; an unclosed parenthesis and a stray bracket stay text.
    text = "ძალთა ზეცისა მგა....: [აღყ]უავილდა (ვითარცა სწერია და მოვემართე.]"
    assert [(text[s:e], k) for s, e, k in mark_conversion(text)] == [
        ("....", "lacuna"), ("[აღყ]", "supplement")]


def test_conversion_numbering_must_increase() -> None:
    wikitext = _CONVERSION_WIKITEXT.replace("თავი გ<br>", "თავი ა<br>")
    with pytest.raises(ValueError, match="after 1"):
        parse_conversion(wikitext, _CONVERSION_PAGE)


def test_pages() -> None:
    assert PAGES == (SHUSHANIK, CONVERSION)
    assert len({p.slug for p in PAGES}) == len(PAGES)
    assert len({p.prefix for p in PAGES}) == len(PAGES)


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.slug)
def test_raw_files(page: Page) -> None:
    path = _RAW / f"{page.slug}.json"
    if not path.exists() or path.read_bytes().startswith(b"version https://git-lfs"):
        pytest.skip("raw data not present")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["work"]["language"] == "oge"
    refs = [u["ref"] for u in data["paragraphs"]]
    assert len(refs) == len(set(refs))
    headings = [u for u in data["paragraphs"]
                if u.get("editorial") and u["editorial"][0][2] == "heading"]
    assert len(headings) == (20 if page is SHUSHANIK else 14)
    for unit in data["paragraphs"]:
        editorial.check(unit["text"], unit.get("editorial", []), unit["ref"])
