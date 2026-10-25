"""Tests for the Coptic Scriptorium ingestor's text extraction (#41).

Coptic is written in bound groups: an article, preposition or verb prefix is
written together with the following word.  Both input formats must produce
bound groups separated by spaces, never morphemes.  The fixtures are small
inline excerpts of the real files, so the tests need no ``data/raw``.
"""

from __future__ import annotations

from pathlib import Path

from scripts.ingest.coptic_scriptorium import _extract_paragraphs_from_tei

# Standard TEI P5: <phr> is a bound group, <w> a morpheme.  Excerpt of
# pseudo.basil.temple.xml, including a manuscript line break inside a <w>
# ("Ⲉ" / "ⲠⲒⲤⲔⲞⲠⲞⲤ"), <m> morphs inside a <w>, <hi> and <lb/>.
_TEI = """\
<TEI xmlns="http://www.tei-c.org/ns/1.0">
<teiHeader><fileDesc><titleStmt><title>t</title></titleStmt></fileDesc></teiHeader>
<text><body>
<div type="textpart">
<p n="1">
<s style="A HOMILY OF APA BASIL, BISHOP OF CAESAREA">
<phr>
<hi rend="ekthetic">
<w type="ART" lemma="ⲟⲩ">
ⲞⲨ
</w>
<w type="N" lemma="ϩⲟⲙⲟⲗⲟⲅⲓⲁ" xml:lang="Greek">
ϨⲞⲘⲞⲖⲞⲄⲒⲀ
</w>
</hi>
</phr>
<phr>
<w type="PREP" lemma="ⲛⲧⲉ">
Ⲛ̅ⲦⲈ
</w>
<w type="N" lemma="ⲁⲡⲁ">
ⲀⲠⲀ
</w>
</phr>
<phr>
<w type="NPROP" lemma="ⲃⲁⲥⲓⲗⲓⲟⲥ">
ⲂⲀⲤⲒⲖⲒⲞⲤ
</w>
</phr>
<phr>
<w type="ART" lemma="ⲡ">
Ⲡ
</w>
<w type="N" lemma="ⲉⲡⲓⲥⲕⲟⲡⲟⲥ" xml:lang="Greek">
Ⲉ
ⲠⲒⲤⲔⲞⲠⲞⲤ
</w>
</phr>
<lb n="2"/>
<phr>
<w type="PREP" lemma="ⲛ">
Ⲛ
</w>
<w type="ART" lemma="ⲡ">
Ⲧ̅
</w>
<w type="NPROP" lemma="ⲕⲁⲓⲥⲁⲣⲓⲁ">
ⲔⲀⲒⲤⲀⲢⲒⲀ
</w>
</phr>
</s>
</p>
<p n="2">
<s>
<phr>
<w type="CREL" lemma="ⲉ">
Ⲉ
</w>
<w type="APST" lemma="ⲁ">
Ⲁ
</w>
<w type="PPERS" lemma="ⲛⲧⲟϥ">
Ϥ
</w>
<w type="V" lemma="ⲧⲁⲩⲟ">
ⲦⲀⲨⲞ
</w>
<w type="PPERO" lemma="ⲛⲧⲟⲥ">
Ⲥ
</w>
</phr>
<phr>
<w type="ART" lemma="ⲡ">
Ⲧ
</w>
<w type="N" lemma="ϭⲓⲛⲉⲓ">
<m>
ϬⲒⲚ
</m>
<m>
ⲈⲒ̈
</m>
</w>
</phr>
<phr>
<w type="PREP" lemma="ⲙⲛ">
ⲛ̄ⲙ
<lb n="16"/>
ⲙⲁ
</w>
<w type="PPERO" lemma="ⲛⲧⲟⲟⲩ">
ⲩ
</w>
</phr>
<phr>
<w type="PREP" lemma="ϩⲛ">
<choice><orig>ϨⲘ</orig><reg>ϨⲚ</reg></choice>
</w>
<w type="ART" lemma="ⲡ">
Ⲡ
</w>
<w type="N" lemma="ⲥⲱⲙⲁ">
ⲤⲰⲘⲀ<note>a note</note>
</w>
</phr>
</s>
</p>
</div>
</body></text>
</TEI>
"""

# Custom <meta>-rooted export: the bound group is the norm_group attribute.
# Excerpt of life.aphou.01.xml.
_META = """\
<meta>
<p_n p_n="0">
<orig_group orig_group="ⲡⲃⲓⲟⲥ">
<norm_group norm_group="ⲡⲃⲓⲟⲥ">
<orig orig="ⲡ"><norm norm="ⲡ"><lemma lemma="ⲡ"><pos pos="ART">
ⲡ
</pos></lemma></norm></orig>
<orig orig="ⲃⲓⲟⲥ"><norm norm="ⲃⲓⲟⲥ"><lemma lemma="ⲃⲓⲟⲥ"><pos pos="N">
ⲃⲓⲟⲥ
</pos></lemma></norm></orig>
</norm_group>
</orig_group>
<orig_group orig_group="ⲛⲁⲡⲁⲁⲫⲟⲩ">
<norm_group norm_group="ⲛⲁⲡⲁⲁⲫⲟⲩ">
<orig orig="ⲛ"><norm norm="ⲛ">
ⲛ
</norm></orig>
<orig orig="ⲁⲡⲁ"><norm norm="ⲁⲡⲁ">
ⲁⲡⲁ
</norm></orig>
<orig orig="ⲁⲫⲟⲩ"><norm norm="ⲁⲫⲟⲩ">
ⲁⲫⲟⲩ
</norm></orig>
</norm_group>
</orig_group>
<orig_group orig_group="ⲡⲉⲡⲓⲥⲕⲟⲡⲟⲥ">
<norm_group norm_group="ⲡⲉⲡⲓⲥⲕⲟⲡⲟⲥ">
<orig orig="ⲡ"><norm norm="ⲡ">
ⲡ
</norm></orig>
<orig orig="ⲉⲡⲓⲥⲕⲟⲡⲟⲥ"><norm norm="ⲉⲡⲓⲥⲕⲟⲡⲟⲥ">
ⲉⲡⲓⲥⲕⲟⲡⲟⲥ
</norm></orig>
</norm_group>
</orig_group>
</p_n>
</meta>
"""


def _extract(tmp_path: Path, xml: str) -> list[dict]:
    path = tmp_path / "doc.xml"
    path.write_text(xml, encoding="utf-8")
    return _extract_paragraphs_from_tei(path, 0, "test-corpus")


def test_tei_joins_morphemes_into_bound_groups(tmp_path: Path) -> None:
    paras = _extract(tmp_path, _TEI)
    assert [p["text"] for p in paras] == [
        "ⲞⲨϨⲞⲘⲞⲖⲞⲄⲒⲀ Ⲛ̅ⲦⲈⲀⲠⲀ ⲂⲀⲤⲒⲖⲒⲞⲤ ⲠⲈⲠⲒⲤⲔⲞⲠⲞⲤ ⲚⲦ̅ⲔⲀⲒⲤⲀⲢⲒⲀ",
        "ⲈⲀϤⲦⲀⲨⲞⲤ ⲦϬⲒⲚⲈⲒ̈ ⲛ̄ⲙⲙⲁⲩ ϨⲚⲠⲤⲰⲘⲀ",
    ]
    assert [p["ref"] for p in paras] == [
        "CopScr.test-corpus.000.0000",
        "CopScr.test-corpus.000.0001",
    ]


def test_tei_keeps_combining_marks_and_prefers_reg(tmp_path: Path) -> None:
    text = " ".join(p["text"] for p in _extract(tmp_path, _TEI))
    # Supralinear strokes (U+0305, U+0304) and diaeresis (U+0308) survive
    assert "̅" in text and "̄" in text and "̈" in text
    # <choice>: <reg> wins over <orig>; <note> is skipped
    assert "ϨⲚⲠⲤⲰⲘⲀ" in text
    assert "ϨⲘ" not in text and "note" not in text


def test_meta_format_uses_norm_group(tmp_path: Path) -> None:
    paras = _extract(tmp_path, _META)
    assert [p["text"] for p in paras] == ["ⲡⲃⲓⲟⲥ ⲛⲁⲡⲁⲁⲫⲟⲩ ⲡⲉⲡⲓⲥⲕⲟⲡⲟⲥ"]


# Excerpts of on_abbaton.01.xml (pseudo-timothy), helias_martyrdom_part3.xml
# and Encomium_Michael_BL_OR_7021_part2.xml (theodosius-alexandria) with the
# layout placeholder ``▢`` and the printed editions' footnote markers
# (#28, #125).
_TEI_NOISE = """\
<TEI xmlns="http://www.tei-c.org/ns/1.0">
<teiHeader><fileDesc><titleStmt><title>t</title></titleStmt></fileDesc></teiHeader>
<text><body>
<p n="1">
<phr><w type="PUNCT" lemma="▢▢▢">
▢▢▢
</w></phr>
<phr><w type="PUNCT" lemma="ⲁ">
Ⲁ
</w></phr>
<phr><w type="PUNCT" lemma="▢▢▢▢">
▢▢▢▢
</w></phr>
<phr><w type="NPROP" lemma="ⲓⲏⲥⲟⲩⲥ">
Ⲓ̅Ⲥ̅
</w></phr>
<phr><w type="PUNCT" lemma="▢✠▢">
▢✠▢
</w></phr>
<phr><w type="N" lemma="ⲭⲣⲓⲥⲧⲟⲥ">
Ⲭ̅Ⲥ̅
</w></phr>
</p>
<p n="2">
<phr><w type="PREP" lemma="ⲉ">
ⲉⲣⲟ
</w><w type="PPERO" lemma="ⲛⲧⲟϥ">
ϥ
</w></phr>
<phr><w type="PUNCT" lemma="⁽²⁾ⲇⲩⲙⲟⲥⲓⲁ">
⁽²⁾
<lb n="18"/>
ⲇⲩⲙⲟⲥⲓ̈ⲁ
</w></phr>
<phr><w type="PUNCT" lemma="·">
·
</w></phr>
<phr><w type="PUNCT" lemma="¹">
¹
</w></phr>
<phr><w type="V" lemma="ϯ">
ϯ
</w><w type="V" lemma="ⲣⲁϣⲉ">
ⲣⲁϣⲉ
</w></phr>
</p>
</body></text>
</TEI>
"""


def test_drops_layout_placeholders_and_footnote_markers(tmp_path: Path) -> None:
    paras = _extract(tmp_path, _TEI_NOISE)
    assert [p["text"] for p in paras] == [
        "Ⲁ Ⲓ̅Ⲥ̅ ✠ Ⲭ̅Ⲥ̅",
        "ⲉⲣⲟϥ ⲇⲩⲙⲟⲥⲓ̈ⲁ · ϯⲣⲁϣⲉ",
    ]


def test_meta_format_drops_noise(tmp_path: Path) -> None:
    xml = _META.replace('norm_group="ⲡⲃⲓⲟⲥ"', 'norm_group="ⲡ⁽³⁾ⲃⲓⲟⲥ ▢"')
    assert 'norm_group="ⲡ⁽³⁾ⲃⲓⲟⲥ ▢"' in xml
    paras = _extract(tmp_path, xml)
    assert [p["text"] for p in paras] == ["ⲡⲃⲓⲟⲥ ⲛⲁⲡⲁⲁⲫⲟⲩ ⲡⲉⲡⲓⲥⲕⲟⲡⲟⲥ"]
