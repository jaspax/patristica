"""Tests for the Coptic Scriptorium ingestor's text extraction (#41, #57).

Coptic is written in bound groups: an article, preposition or verb prefix is
written together with the following word.  Both input formats must produce
bound groups separated by spaces, never morphemes.  The text is the
normalized layer for every work (#57): for a TEI file, the ``norm_group`` of
its TreeTagger export, one per ``<phr>``; the diplomatic form is kept as
``orig``.  The fixtures are small inline excerpts of the real files, so the
tests need no ``data/raw``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from scripts.ingest.coptic_scriptorium import (
    CopticLayerError,
    _extract_paragraphs_from_tei,
    ingest,
)

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


def _tt(*norm_groups: str) -> str:
    """A TreeTagger export with one bound group per *norm_groups* item (the
    real files nest morphemes, lemmas and tags inside each)."""
    groups = "\n".join(
        f'<orig_group orig_group="x">\n<norm_group norm_group="{n}">\n<orig orig="x">\n'
        f'<norm norm="{n}">\n{n}\n</norm>\n</orig>\n</norm_group>\n</orig_group>'
        for n in norm_groups
    )
    return f'<meta corpus="test.corpus">\n<verse_n verse_n="1">\n{groups}\n</verse_n>\n</meta>\n'


# The normalized layer of _TEI: pseudo.basil.temple.tt's norm_group values
# for the same bound groups.
_TEI_TT = _tt(
    "ⲟⲩϩⲟⲙⲟⲗⲟⲅⲓⲁ", "ⲛⲧⲉⲁⲡⲁ", "ⲃⲁⲥⲓⲗⲓⲟⲥ", "ⲡⲉⲡⲓⲥⲕⲟⲡⲟⲥ", "ⲛⲧⲕⲁⲓⲥⲁⲣⲓⲁ",
    "ⲉⲁϥⲧⲁⲩⲟⲥ", "ⲧϭⲓⲛⲉⲓ", "ⲛⲙⲙⲁⲩ", "ϩⲛⲡⲥⲱⲙⲁ",
)


def _extract(tmp_path: Path, xml: str, tt: str | None = None) -> list[dict]:
    """Extract *xml* laid out as in the repo: ``{corpus}/{corpus}_TEI/`` with
    its TreeTagger export *tt* in ``{corpus}_TT/``, named in other case (as
    AP's are)."""
    tei_dir = tmp_path / "test-corpus" / "test.corpus_TEI"
    tei_dir.mkdir(parents=True, exist_ok=True)
    path = tei_dir / "doc.01.xml"
    path.write_text(xml, encoding="utf-8")
    if tt is not None:
        tt_dir = tmp_path / "test-corpus" / "test.corpus_TT"
        tt_dir.mkdir(exist_ok=True)
        (tt_dir / "DOC.01.tt").write_text(tt, encoding="utf-8")
    return _extract_paragraphs_from_tei(path, 0, "test-corpus")


def test_tei_text_is_the_normalized_layer(tmp_path: Path) -> None:
    paras = _extract(tmp_path, _TEI, _TEI_TT)
    assert [p["text"] for p in paras] == [
        "ⲟⲩϩⲟⲙⲟⲗⲟⲅⲓⲁ ⲛⲧⲉⲁⲡⲁ ⲃⲁⲥⲓⲗⲓⲟⲥ ⲡⲉⲡⲓⲥⲕⲟⲡⲟⲥ ⲛⲧⲕⲁⲓⲥⲁⲣⲓⲁ",
        "ⲉⲁϥⲧⲁⲩⲟⲥ ⲧϭⲓⲛⲉⲓ ⲛⲙⲙⲁⲩ ϩⲛⲡⲥⲱⲙⲁ",
    ]
    # Paragraphs and refs still come from the TEI
    assert [p["ref"] for p in paras] == [
        "CopScr.test-corpus.000.0000",
        "CopScr.test-corpus.000.0001",
    ]


def test_tei_orig_joins_morphemes_into_bound_groups(tmp_path: Path) -> None:
    paras = _extract(tmp_path, _TEI, _TEI_TT)
    assert [p["orig"] for p in paras] == [
        "ⲞⲨϨⲞⲘⲞⲖⲞⲄⲒⲀ Ⲛ̅ⲦⲈⲀⲠⲀ ⲂⲀⲤⲒⲖⲒⲞⲤ ⲠⲈⲠⲒⲤⲔⲞⲠⲞⲤ ⲚⲦ̅ⲔⲀⲒⲤⲀⲢⲒⲀ",
        "ⲈⲀϤⲦⲀⲨⲞⲤ ⲦϬⲒⲚⲈⲒ̈ ⲛ̄ⲙⲙⲁⲩ ϨⲚⲠⲤⲰⲘⲀ",
    ]


def test_tei_orig_keeps_combining_marks_and_prefers_reg(tmp_path: Path) -> None:
    paras = _extract(tmp_path, _TEI, _TEI_TT)
    orig = " ".join(p["orig"] for p in paras)
    # Supralinear strokes (U+0305, U+0304) and diaeresis (U+0308) survive
    assert "̅" in orig and "̄" in orig and "̈" in orig
    # <choice>: <reg> wins over <orig>; <note> is skipped
    assert "ϨⲚⲠⲤⲰⲘⲀ" in orig
    assert "ϨⲘ" not in orig and "note" not in orig
    # ... and none of them is in the normalized text
    text = " ".join(p["text"] for p in paras)
    assert not any(mark in text for mark in "̅̄̈")


def test_tei_without_tt_export_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(CopticLayerError, match="no TreeTagger export"):
        _extract(tmp_path, _TEI)


def test_tei_tt_count_mismatch_is_an_error(tmp_path: Path) -> None:
    # One norm_group short: the layers can't be paired, so nothing is guessed.
    short = _tt("ⲟⲩϩⲟⲙⲟⲗⲟⲅⲓⲁ", "ⲛⲧⲉⲁⲡⲁ", "ⲃⲁⲥⲓⲗⲓⲟⲥ", "ⲡⲉⲡⲓⲥⲕⲟⲡⲟⲥ", "ⲛⲧⲕⲁⲓⲥⲁⲣⲓⲁ",
                "ⲉⲁϥⲧⲁⲩⲟⲥ", "ⲧϭⲓⲛⲉⲓ", "ⲛⲙⲙⲁⲩ")
    with pytest.raises(CopticLayerError, match="9 bound groups.*8 norm_group"):
        _extract(tmp_path, _TEI, short)


def test_ingest_skips_a_corpus_without_its_normalized_layer(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    corpus = tmp_path / "_repos" / "coptic-scriptorium" / "dormition-john"
    (corpus / "dormition.john_TEI").mkdir(parents=True)
    (corpus / "dormition.john_TEI" / "dormition.xml").write_text(_TEI, encoding="utf-8")
    (corpus / "dormition.john_TT").mkdir()
    (corpus / "dormition.john_TT" / "dormition.tt").write_text(_tt("ⲁ"), encoding="utf-8")

    with caplog.at_level(logging.ERROR):
        works = ingest(tmp_path)

    assert works == []
    assert not (tmp_path / "coptic-scriptorium" / "dormition_john.json").exists()
    assert any(r.levelno == logging.ERROR and "dormition-john" in r.getMessage()
               for r in caplog.records)


def test_meta_format_uses_norm_group(tmp_path: Path) -> None:
    # Give one bound group a diplomatic form that differs from its norm.
    xml = _META.replace('orig_group="ⲡⲉⲡⲓⲥⲕⲟⲡⲟⲥ"', 'orig_group="ⲠⲈⲠⲒⲤⲔⲞⲠⲞⲤ"')
    assert xml != _META
    paras = _extract(tmp_path, xml)
    assert [p["text"] for p in paras] == ["ⲡⲃⲓⲟⲥ ⲛⲁⲡⲁⲁⲫⲟⲩ ⲡⲉⲡⲓⲥⲕⲟⲡⲟⲥ"]
    assert [p["orig"] for p in paras] == ["ⲡⲃⲓⲟⲥ ⲛⲁⲡⲁⲁⲫⲟⲩ ⲠⲈⲠⲒⲤⲔⲞⲠⲞⲤ"]


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


# The normalized layer keeps ``▢`` too (#28), and expands the nomina sacra.
_TEI_NOISE_TT = _tt(
    "▢▢▢", "ⲁ", "▢▢▢▢", "ⲓⲏⲥⲟⲩⲥ", "▢✠▢", "ⲭⲣⲓⲥⲧⲟⲥ",
    "ⲉⲣⲟϥ", "⁽²⁾ⲇⲏⲙⲟⲥⲓⲁ", "·", "¹", "ϯⲣⲁϣⲉ",
)


def test_drops_layout_placeholders_and_footnote_markers(tmp_path: Path) -> None:
    paras = _extract(tmp_path, _TEI_NOISE, _TEI_NOISE_TT)
    assert [p["text"] for p in paras] == [
        "ⲁ ⲓⲏⲥⲟⲩⲥ ✠ ⲭⲣⲓⲥⲧⲟⲥ",
        "ⲉⲣⲟϥ ⲇⲏⲙⲟⲥⲓⲁ · ϯⲣⲁϣⲉ",
    ]
    assert [p["orig"] for p in paras] == [
        "Ⲁ Ⲓ̅Ⲥ̅ ✠ Ⲭ̅Ⲥ̅",
        "ⲉⲣⲟϥ ⲇⲩⲙⲟⲥⲓ̈ⲁ · ϯⲣⲁϣⲉ",
    ]


def test_lacunae_are_marked_as_editorial_material() -> None:
    """``[....]``-style lacunae stay in the text and are marked (#236); brackets
    around letters (the editor's restoration of a word) are not."""
    from scripts.ingest.coptic_scriptorium import _paragraph

    text = "ⲁⲩⲱ […] ⲛⲟⲛ [..] ⲡⲣ[ⲉ]ⲥⲃⲩⲧⲉⲣⲟⲥ []"
    para = _paragraph("test-corpus", 1, 2, text, "orig")
    assert para["text"] == text
    assert [text[s:e] for s, e, _ in para["editorial"]] == ["[…]", "[..]", "[]"]
    assert {k for _, _, k in para["editorial"]} == {"lacuna"}
    assert "editorial" not in _paragraph("test-corpus", 1, 3, "ⲡⲣ[ⲉ]ⲥⲃⲩⲧⲉⲣⲟⲥ", "orig")


def test_meta_format_drops_noise(tmp_path: Path) -> None:
    xml = _META.replace('norm_group="ⲡⲃⲓⲟⲥ"', 'norm_group="ⲡ⁽³⁾ⲃⲓⲟⲥ ▢"')
    assert 'norm_group="ⲡ⁽³⁾ⲃⲓⲟⲥ ▢"' in xml
    paras = _extract(tmp_path, xml)
    assert [p["text"] for p in paras] == ["ⲡⲃⲓⲟⲥ ⲛⲁⲡⲁⲁⲫⲟⲩ ⲡⲉⲡⲓⲥⲕⲟⲡⲟⲥ"]
