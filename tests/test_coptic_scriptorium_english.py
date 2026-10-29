"""Tests for the English translation layer of Coptic Scriptorium (#346).

Every TreeTagger export carries sentence-aligned ``<translation>`` spans; the
``coptic_scriptorium_eng`` writes them as an English work on the Coptic units' refs.  The
fixtures are small inline documents shaped like the real ones.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.ingest import coptic_scriptorium
from scripts.ingest.coptic_scriptorium_eng import (
    CopticLicenseError,
    _english_editorial,
    _english_title,
    _english_work,
    _license,
    _read_translation,
    ingest,
)

_NC_HEADER = (
    'title="Doc" translation="Aurelio La Rotta" '
    "license=\"&lt;a href='https://creativecommons.org/licenses/by-nc-sa/4.0/'&gt;"
    'CC BY-NC-SA 4.0&lt;/a&gt;"'
)


def _group(norm: str) -> str:
    return f'<norm_group norm_group="{norm}">\n<norm norm="{norm}">\n{norm}\n</norm>\n</norm_group>'


def _doc(header: str, paragraphs: list[list[tuple[str, list[str]]]]) -> str:
    """A ``<meta>``-rooted export: per paragraph, its sentences as
    (translation, bound groups).  A sentence given as ``("@cont", groups)``
    continues the previous paragraph's last sentence (a span crossing
    ``<p_n>``), which the TT format allows."""
    out = [f"<meta {header}>"]
    for n, sentences in enumerate(paragraphs):
        out.append(f'<p_n p_n="{n}">')
        for text, groups in sentences:
            if text == "@cont":
                out.extend(_group(g) for g in groups)
                out.append("</translation>")
                continue
            out.append(f'<translation translation="{text}">')
            out.extend(_group(g) for g in groups)
            if not text.endswith("@open"):
                out.append("</translation>")
        out.append("</p_n>")
    out.append("</meta>")
    return "\n".join(out).replace("@open", "") + "\n"


def _corpus(root: Path, corpus: str, docs: dict[str, str]) -> None:
    """Lay out *docs* as a corpus whose TEI and TT directories both hold the
    export, the TEI copy without its header (as in the repo)."""
    base = root / "_repos" / "coptic-scriptorium" / corpus
    tei = base / f"{corpus.replace('-', '.')}_TEI"
    tt = base / f"{corpus.replace('-', '.')}_TT"
    tei.mkdir(parents=True)
    tt.mkdir()
    for name, xml in docs.items():
        (tt / f"{name}.tt").write_text(xml, encoding="utf-8")
        headerless = "<meta >" + xml.split(">", 1)[1]
        (tei / f"{name}.xml").write_text(headerless, encoding="utf-8")


def _raw(root: Path, source: str, slug: str) -> dict:
    return json.loads((root / source / f"{slug}.json").read_text(encoding="utf-8"))


def test_english_work_is_cut_on_the_coptic_refs(tmp_path: Path) -> None:
    _corpus(tmp_path, "life-aphou", {
        "life.aphou.01": _doc(_NC_HEADER, [
            [("The life of Apa Aphou.", ["ⲡⲃⲓⲟⲥ", "ⲛⲁⲫⲟⲩ"])],
            # Two sentences in one paragraph; the second runs on into the next.
            [("He went out.", ["ⲁϥⲉⲓ"]), ("And he said@open", ["ⲁϥϫⲟⲟⲥ"])],
            [("@cont", ["ⲛⲁϥ"]), ("...", ["ⲁⲩⲱ"])],
            [("Amen.", ["ϩⲁⲙⲏⲛ"])],
        ]),
    })
    coptic_scriptorium.ingest(tmp_path)
    ingest(tmp_path)

    coptic = _raw(tmp_path, "coptic-scriptorium", "life_aphou")
    english = _raw(tmp_path, "coptic-scriptorium-eng", "life_aphou")
    refs = [p["ref"] for p in coptic["paragraphs"]]
    assert len(refs) == 4
    # A sentence goes to the paragraph of its first bound group; a paragraph
    # with only a placeholder ("...") gets no English unit.
    assert [(p["ref"], p["text"]) for p in english["paragraphs"]] == [
        (refs[0], "The life of Apa Aphou."),
        (refs[1], "He went out. And he said"),
        (refs[3], "Amen."),
    ]
    work = english["work"]
    assert work["work_id"] == "coptic-scriptorium-eng/life_aphou"
    assert work["translation_of"] == "coptic-scriptorium/life_aphou"
    assert work["language"] == "eng"
    assert work["license"] == "cc-by-nc-sa-4.0"
    assert work["title"] == "Life of Aphou"
    assert "Aurelio La Rotta" in work["edition"]


def test_no_english_work_without_a_translation(tmp_path: Path) -> None:
    _corpus(tmp_path, "life-cyrus", {
        "life.cyrus.01": _doc('translation="none" license="CC-BY 4.0"', [
            [("...", ["ⲁϥⲉⲓ"])], [("…", ["ⲁϥϫⲟⲟⲥ"])], [("---", ["ⲛⲁϥ"])],
        ]),
    })
    works = ingest(tmp_path)
    assert works == []
    assert not (tmp_path / "coptic-scriptorium-eng" / "life_cyrus.json").exists()


def test_partial_translation_gives_a_partial_work(tmp_path: Path) -> None:
    _corpus(tmp_path, "life-phib", {
        "life.phib.01": _doc(_NC_HEADER, [[("He rose.", ["ⲁϥⲧⲱⲟⲩⲛ"])]]),
        "life.phib.02": _doc('translation="none" ' + _NC_HEADER.split(" ", 2)[2],
                             [[("...", ["ⲁϥⲉⲓ"])]]),
    })
    coptic_scriptorium.ingest(tmp_path)
    ingest(tmp_path)
    english = _raw(tmp_path, "coptic-scriptorium-eng", "life_phib")
    assert [p["ref"] for p in english["paragraphs"]] == ["CopScr.life-phib.000.0000"]
    assert english["work"]["edition"] == (
        "Coptic Scriptorium, life-phib: English translation by Aurelio La Rotta")


def test_read_translation_follows_crossing_spans(tmp_path: Path) -> None:
    # The translation opens inside an <entity> and closes outside it.
    path = tmp_path / "doc.tt"
    path.write_text(
        '<meta a="1">\n<entity entity="person">\n<translation translation="One &amp; two">\n'
        + _group("ⲁ") + "\n</entity>\n" + _group("ⲃ") + "\n</translation>\n"
        + _group("ⲅ") + "\n</meta>\n",
        encoding="utf-8",
    )
    tr = _read_translation(path)
    assert tr.header == {"a": "1"}
    assert tr.sentences == [("One & two", [0, 1], 0)]
    assert tr.groups == 3


@pytest.mark.parametrize(("text", "budge", "spans"), [
    ("he said (unto them) [that] it was so", True,
     [[8, 19, "supplement"], [20, 26, "supplement"]]),
    # Parentheses in the project's own translations are not insertions ...
    ("he said (unto them) [that]", False, [[20, 26, "supplement"]]),
    # ... but their queries and lacunae are marked everywhere.
    ("the Lord (?) came [...] and (sic) went (i. e., world)", False,
     [[9, 12, "note"], [18, 23, "lacuna"], [28, 33, "note"], [39, 53, "note"]]),
    ("no brackets", True, []),
])
def test_english_editorial(text: str, budge: bool, spans: list) -> None:
    assert _english_editorial(text, budge) == spans


@pytest.mark.parametrize(("value", "license"), [
    ("<a href='https://creativecommons.org/licenses/by/4.0/'>CC-BY 4.0</a> -", "cc-by-4.0"),
    ("<a href='https://creativecommons.org/licenses/by-nc-sa/4.0/'>CC BY-NC-SA 4.0</a>",
     "cc-by-nc-sa-4.0"),
    ("CC-BY-SA 4.0", "cc-by-sa-4.0"),
    ("<a href='https://creativecommons.org/licenses/by-sa/3.0/'>CC BY-SA 3.0 Unported</a>",
     "cc-by-sa-3.0"),
    # mercurius: the link and the label disagree; the more restrictive wins (#382).
    ("<a href='https://creativecommons.org/licenses/by-sa/4.0/'>CC-BY 4.0</a>", "cc-by-sa-4.0"),
])
def test_license(value: str, license: str) -> None:
    assert _license(value) == license


@pytest.mark.parametrize("value", ["", "CC BY 3.0", "CC BY-SA 3.0 and CC BY-SA 4.0",
                                   "Coptic text (c)2000-2006 by J Warren Wells"])
def test_unrecognised_license_is_an_error(value: str) -> None:
    with pytest.raises(CopticLicenseError):
        _license(value)


def test_english_work_takes_the_most_restrictive_licence_and_names_budge() -> None:
    meta = {"author": None, "title": "Works Attributed to Celestinus (Coptic)",
            "date_composed": None, "date_range": (400, 432), "date_confidence": "uncertain",
            "genre": "patristic"}
    budge = {"translation": "E. A. Wallis Budge", "license": "CC-BY 4.0",
             "Coptic_edition": "<a href='x'>Budge, 1914</a>"}
    work = _english_work("pseudo-celestinus", "pseudo_celestinus", meta,
                         [budge, {**budge, "license": "CC BY-NC-SA 4.0"}])
    assert work.license == "cc-by-nc-sa-4.0"
    assert work.title == "Works Attributed to Celestinus"
    assert work.edition == (
        "Coptic Scriptorium, pseudo-celestinus: English translation by E. A. Wallis Budge, "
        "from Budge, Coptic Martyrdoms, etc., in the Dialect of Upper Egypt (1914) "
        "(public domain), slightly revised and segmented by Coptic Scriptorium")


def test_english_title() -> None:
    assert _english_title("Homilies of Proclus (Coptic translation)") == "Homilies of Proclus"
    assert _english_title("Shenoute: Fox") == "Shenoute: Fox"
