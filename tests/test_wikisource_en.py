"""English Wikisource (#653): Wylie's translation of the Xi'an stele, HTML to units."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from patristica import editorial
from scripts.ingest.wikisource_en import NESTORIAN_STELE, PAGES, Page, parse_stele

_RAW = Path(__file__).resolve().parents[1] / "data" / "raw" / "wikisource-en"

_PAGENUM = ('<span><span class="pagenum ws-pagenum" data-page-number="{n}">'
            '<span class="pagenum-inner ws-noexport">&#8203;</span></span></span>')

# A cut-down copy of the parsed page, with its markup: centred headings, a drop
# initial, footnote markers, a word hyphenated over a page break, the ode over
# two pages and the bracketed remarks of the colophon.
_HTML = f"""<div class="mw-parser-output"><div id="ws-data">Jingjing</div>
<div class="prp-pages-output" lang="en">
{_PAGENUM.format(n=11)}<div class="wst-dhr">&#160;</div>
<style>.x{{}}</style><div class="wst-center tiInherit">
<p><span style="font-size:120%;">TRANSLATION OF THE NESTORIAN INSCRIPTION.</span>
</p>
<p><span style="font-size:69%;">BY A. WYLIE.</span>
</p>
<p><i>Tablet Eulogizing the Propagation,<br />A Priest of the Syrian Church.</i>
</p>
</div>
<p><span class="dropinitial"><span class="dropinitial-initial">B</span></span>EHOLD the Persians<sup id="cite_ref-1" class="reference"><a href="#cite_note-1"><span class="cite-bracket">&#91;</span>1<span class="cite-bracket">&#93;</span></a></sup> observing; their&#32;{_PAGENUM.format(n=12)}intellects.
</p><p>He restored the con{_PAGENUM.format(n=13)}secrated timbers (A.&#160;D. 781).
</p><p>ODE.
</p>
<div class="poem">
<p>The true Lord is without origin, <br />
Profound, invisible. <br />
<br />
Divided in nature, <br />
To save and to help.<br />
</p>
</div>&#32;{_PAGENUM.format(n=14)}<div class="poem">
<p>The true doctrine was clearly announced, <br />
Overseers of the church.
</p>
</div>
<p>This was erected in 781.
</p><p><span style="font-size:83%;">[Kircher translates this as follows:]</span>
</p>
<div class="tiInherit" style="text-indent:-2em;">"Adam, Deacon.</div>
<div class="tiInherit" style="text-indent:-2em;">In the time of the Patriarch."</div>
<p><span style="font-size:83%;">[On the left-hand edge are names.]</span>&#32;
</p>
</div>
<div class="prp-pages-output"><div class="reflist"><ol class="references">
<li id="cite_note-1"><span class="mw-cite-backlink"><a href="#cite_ref-1">↑</a></span> <span class="reference-text"><i>Po-sz'</i>, "Persians."</span>
</li>
</ol></div></div></div>"""

_PAGE = dataclasses.replace(NESTORIAN_STELE, units=11)


def _units() -> dict[str, dict]:
    return {u["ref"]: u for u in parse_stele(_HTML, _PAGE)}


def test_units_and_refs() -> None:
    units = _units()
    assert list(units) == ["Stele", "Stele.1", "Stele.2", "Stele.3", "Ode", "Ode.1", "Ode.2",
                           "Ode.3", "Colophon.1", "Colophon.2", "Colophon.3"]
    assert units["Stele.1"]["text"] == ("Tablet Eulogizing the Propagation, "
                                        "A Priest of the Syrian Church.")
    assert units["Stele.3"]["text"] == "He restored the consecrated timbers (A. D. 781)."
    assert units["Ode.2"]["text"] == "Divided in nature, To save and to help."
    assert units["Ode.3"]["text"] == "The true doctrine was clearly announced, Overseers of the church."
    assert "editorial" not in units["Ode"]


def test_editorial_spans() -> None:
    units = _units()
    for unit in units.values():
        editorial.check(unit["text"], unit.get("editorial", []), unit["ref"])
    heading = units["Stele"]
    assert heading["text"] == "TRANSLATION OF THE NESTORIAN INSCRIPTION. BY A. WYLIE."
    assert heading["editorial"] == [[0, len(heading["text"]), "title"]]
    behold = units["Stele.2"]
    assert behold["text"] == ("BEHOLD the Persians [Po-sz', \"Persians.\"] observing; "
                              "their intellects.")
    (s, e, kind), = behold["editorial"]
    assert (behold["text"][s:e], kind) == ("[Po-sz', \"Persians.\"]", "note")
    syriac = units["Colophon.2"]
    assert syriac["text"] == ('[Kircher translates this as follows:] "Adam, Deacon. '
                              'In the time of the Patriarch."')
    assert syriac["editorial"] == [[0, 37, "note"]]
    last = units["Colophon.3"]
    assert last["editorial"] == [[0, len(last["text"]), "note"]]


def test_unit_count_is_checked() -> None:
    with pytest.raises(ValueError, match="11 units, expected 12"):
        parse_stele(_HTML, dataclasses.replace(_PAGE, units=12))


def test_unexpected_heading_raises() -> None:
    with pytest.raises(ValueError, match="expected TRANSLATION"):
        parse_stele(_HTML.replace("TRANSLATION OF", "TRANSLATIONS OF"), _PAGE)


def test_pages() -> None:
    assert PAGES == (NESTORIAN_STELE,)
    assert NESTORIAN_STELE.translation_of in (None, "wikisource-lzh/xian-stele")


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.slug)
def test_raw_files(page: Page) -> None:
    path = _RAW / f"{page.slug}.json"
    if not path.exists() or path.read_bytes().startswith(b"version https://git-lfs"):
        pytest.skip("raw data not present")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["work"]["language"] == "eng"
    assert data["work"]["translation_of"] == page.translation_of
    refs = [u["ref"] for u in data["paragraphs"]]
    assert len(refs) == len(set(refs)) == page.units
    for unit in data["paragraphs"]:
        editorial.check(unit["text"], unit.get("editorial", []), unit["ref"])
