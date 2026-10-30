"""The tertullian.org Christian Arabic pages (#479): notes, page markers, titles."""

from __future__ import annotations

import pytest

from patristica import editorial
from scripts.ingest import _pearse_arabic as pa

_SBATH = pa.PAGES[1]
_SEVERUS = next(p for p in pa.PAGES if p.split_lines)

_HTML = """<html><body>
<p align="center"><b>Heading</b></p>
<h3 align="center">On the Differences</h3>
<h3 align="center">By Yahya</h3>
<p align="center">[Translated by Sam Noble]</p>
<p>&nbsp;&nbsp;Difference is used in
various ways.<a href="#_ftn1" name="_ftnref1">[1]</a> It is so.</p>
<hr>
<p dir=RTL>&#1601;&#1610; &#1575;&#1582;&#1578;&#1604;&#1575;&#1601;</p>
<p dir=RTL>&#1575;&#1604;&#1575;&#1582;&#1578;&#1604;&#1575;&#1601; &lt;26&gt; &#1610;&#1615;&#1602;&#1575;&#1604;<a
href="#_ftn2" name="_ftnref2"><span dir=LTR>[2]</span></a> &#1593;&#1604;&#1609;</p>
<div id=ftn1><p><a href="#_ftnref1" name="_ftn1">[1]</a> Luke 1:3</p></div>
<div id=ftn2><p dir=RTL><a href="#_ftnref2" name="_ftn2"><span dir=LTR>[2]</span></a>&#1601;&#1610;</p></div>
<p align="left" class="small">This file and all material on this page is in the public domain.</p>
<table><tr><td><a href="index.htm">Early Church Fathers</a></td></tr></table>
</body></html>"""


def test_sbath_page() -> None:
    english, arabic = pa.parse(_SBATH, _HTML)
    assert english[0].text == "On the Differences — By Yahya"
    assert english[0].spans == [[0, len(english[0].text), "title"]]
    body = english[1]
    assert body.text == "Difference is used in various ways. [Luke 1:3] It is so."
    assert editorial.strip(body.text, body.spans) == "Difference is used in various ways. It is so."
    assert arabic[0].spans == [[0, len(arabic[0].text), "title"]]
    text = arabic[1].text
    assert "<26>" not in text and "[2]" not in text
    assert text == "الاختلاف يُقال [في] على"
    assert arabic[1].spans == [[text.index("["), text.index("]") + 1, "note"]]


def test_unreferenced_note_is_an_error() -> None:
    html = _HTML.replace('<a href="#_ftn1" name="_ftnref1">[1]</a>', "")
    with pytest.raises(pa.PearseParseError, match="never referenced"):
        pa.parse(_SBATH, html)


def test_severus_lines_split_by_speaker_and_margins_kept() -> None:
    html = """<html><body>
<p>Hermes said: one.</p><p>And Plato said: two.</p>
<p dir=RTL>&#1601;&#1604;&#1575; &#1610;&#1605;&#1606;&#1593;&#1607;&#1575;</p>
<p dir=RTL>&#1576;&#1610;&#1578;&#1607; &#1608;&#1602;&#1575;&#1604; &#1575;&#1601;&#1604;&#1575;&#1591;&#1608;&#1606;
[&#1575;&#1604;&#1593;&#1604;&#1608;&#1610;] &#1601;&#1610;</p>
</body></html>"""
    english, arabic = pa.parse(_SEVERUS, html)
    assert [u.text for u in english] == ["Hermes said: one.", "And Plato said: two."]
    assert [u.text for u in arabic] == ["فلا يمنعها بيته", "وقال افلاطون [العلوي] في"]
    second = arabic[1]
    start = second.text.index("[")
    assert second.spans == [[start, second.text.index("]") + 1, "supplement"]]
    assert editorial.source_text({"text": second.text, "editorial": second.spans}) == \
        "وقال افلاطون العلوي في"


def test_works_link_the_english_to_the_arabic() -> None:
    for page in pa.PAGES:
        eng = pa._work(page, english=True)
        arb = pa._work(page, english=False)
        assert eng.translation_of == arb.work_id
        assert (arb.language, eng.language) == ("arb", "eng")
        assert eng.license == arb.license == "public_domain"
    assert len({p.prefix for p in pa.PAGES}) == len(pa.PAGES)
