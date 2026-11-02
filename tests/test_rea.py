"""Referenzkorpus Altdeutsch (#567): relANNIS tables to works, units, refs and editorial spans."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica import editorial
from scripts.ingest import rea
from scripts.ingest.rea import (
    DROPPED, LACUNA, TEXTS, Document, ReAError, assemble, block_units, build_units,
    numbered_units, read_subcorpus, rhyme_lines,
)

_RAW = Path(__file__).resolve().parents[1] / "data" / "raw" / "rea"


def _tables(docs: dict[str, dict], top_meta: dict[str, str] | None = None) -> dict[str, str]:
    """relANNIS 3.3 tables for *docs*: name → {"meta": {...}, "edition": [tokens],
    "text": [tokens] (optional), "spans": [(name, first, last, value)]}, the tokens on
    a timeline that starts at 0 in each document, as in the ReA export."""
    corpus = ["0\tSUB_1.2\tCORPUS\tNULL\t0\t0\tFALSE"]
    annos = [f"0\tNULL\t{k}\t{v}" for k, v in (top_meta or {}).items()]
    nodes: list[str] = []
    node_annos: list[str] = []
    nid = 0
    for i, (name, d) in enumerate(docs.items(), start=1):
        corpus.append(f"{i}\t{name}\tDOCUMENT\tNULL\t{i}\t{i}\tFALSE")
        annos += [f"{i}\tNULL\t{k}\t{v}" for k, v in d.get("meta", {}).items()]
        for layer in ("edition", "text"):
            for pos, tok in enumerate(d.get(layer, [])):
                nodes.append(f"{nid}\t0\t{i}\tdefault_layer\tsTok{nid}\t{pos}\t{pos}\tNULL\t{pos}\t{pos}"
                             f"\t{pos}\t{layer}\t{tok}\tFALSE")
                nid += 1
        for sname, first, last, value in d.get("spans", []):
            nodes.append(f"{nid}\t0\t{i}\tdefault_ns\tsSpan{nid}\t{first}\t{last}\tNULL\t{first}\t{last}"
                         f"\tNULL\tNULL\tNULL\tTRUE")
            node_annos.append(f"{nid}\tdefault_ns\t{sname}\t{value}")
            nid += 1
    return {"corpus": "\n".join(corpus) + "\n", "corpus_annotation": "\n".join(annos) + "\n",
            "node": "\n".join(nodes) + "\n", "node_annotation": "\n".join(node_annos) + "\n"}


# Tatian's prologue and chapter 1, as ReA has them (shortened).
_TATIAN = {
    "T_Tat0": {"edition": ["Prologus", "Bithiu", "uuanta", "manage", "zilotun", ",", "Só", "ûns", "saltun", "."],
               "spans": [("subchapter", 1, 5, "1"), ("subchapter", 6, 9, "2"), ("verse", 0, 9, "n/a")]},
    "T_Tat1": {"edition": ["In", "anaginne", "uuas", "uuort", ".", "Thaz", "uuas", "in", "anaginne", "."],
               "spans": [("chapter", 0, 9, "1"), ("subchapter", 0, 4, "1"), ("subchapter", 5, 9, "2")]},
}


def _docs(spec: dict[str, dict], layer: str = "edition", meta: dict[str, str] | None = None) -> dict[str, Document]:
    return read_subcorpus(_tables(spec, meta or {"language": "ahd."}), layer)


def test_read_subcorpus_tokens_spans_and_metadata() -> None:
    docs = _docs(_TATIAN)
    assert set(docs) == {"T_Tat0", "T_Tat1"}
    doc = docs["T_Tat1"]
    assert [t[2] for t in doc.tokens][:3] == ["In", "anaginne", "uuas"]
    assert doc.spans["subchapter"] == [(0, 4, "1"), (5, 9, "2")]
    assert doc.meta["language"] == "ahd."  # inherited from the sub-corpus


def test_tatian_refs_heading_and_punctuation() -> None:
    text = next(t for t in TEXTS if t.slug == "tatian")
    units = build_units(text, _docs(_TATIAN))
    assert units == [
        {"ref": "Tat.0", "text": "Prologus"},
        {"ref": "Tat.0.1", "text": "Bithiu uuanta manage zilotun,"},
        {"ref": "Tat.0.2", "text": "Só ûns saltun."},
        {"ref": "Tat.1.1", "text": "In anaginne uuas uuort."},
        {"ref": "Tat.1.2", "text": "Thaz uuas in anaginne."},
    ]


def test_language_is_checked_against_rea() -> None:
    text = next(t for t in TEXTS if t.slug == "tatian")
    with pytest.raises(ReAError, match="'as.'"):
        build_units(text, _docs(_TATIAN, meta={"language": "as."}))


def test_uncovered_words_go_with_the_preceding_unit() -> None:
    docs = _docs({"D": {"edition": ["a", "b", "c", "d"],
                        "spans": [("verse", 0, 1, "1"), ("verse", 3, 3, "3")]}})
    units = numbered_units(docs["D"], "X", "verse")
    assert [(u.ref, u.tokens) for u in units] == [("X.1", ["a", "b", "c"]), ("X.3", ["d"])]


def test_non_contiguous_unit_is_an_error() -> None:
    docs = _docs({"D": {"edition": ["a", "b", "c"],
                        "spans": [("verse", 0, 0, "1"), ("verse", 1, 1, "2"), ("verse", 2, 2, "1")]}})
    with pytest.raises(ReAError, match="not contiguous"):
        numbered_units(docs["D"], "X", "verse")


def test_block_units_by_page() -> None:
    docs = _docs({"N_Ps_001": {"edition": ["TITLE", "a", "b", "c"],
                               "spans": [("page", 1, 2, "9"), ("page", 3, 3, "10")]}})
    units = block_units(docs["N_Ps_001"], lambda v: f"NPs.1.{v}", "page")
    assert [(u.ref, u.tokens) for u in units] == [("NPs.1.9", ["TITLE", "a", "b"]), ("NPs.1.10", ["c"])]


def test_assemble_spacing_quotes_and_brackets() -> None:
    text, spans = assemble(['"', "Uuela", ",", '"', "quað", "Âdam", ",", '"', "uƀilo", '"', "(", "ja", ")", "»In", "dheodun«", "."])
    assert text == '"Uuela," quað Âdam, "uƀilo" (ja) »In dheodun«.'
    assert spans == []


def test_assemble_lacunae() -> None:
    text, spans = assemble(["*", "*", "sagetun", "al", ".", ".", ".", "diubil", ".", "*"])
    assert text == f"{LACUNA} sagetun al {LACUNA} diubil. {LACUNA}"
    assert spans == [[0, 3, "lacuna"], [15, 18, "lacuna"], [27, 30, "lacuna"]]
    assert editorial.source_text({"text": text, "editorial": spans}) == "sagetun al diubil."


def test_assemble_supplements_and_notation() -> None:
    text, spans = assemble(["ú<m>be", "PSALteriu{m}", "in_hímele", "d(i)umagad", "°et", "/Sed", "gi|deda"])
    assert text == "ú<m>be PSALterium in hímele d(i)umagad et Sed gideda"
    assert spans == [[1, 4, "supplement"], [29, 32, "supplement"]]
    assert editorial.source_text({"text": text, "editorial": spans}).startswith("úmbe PSALterium in hímele diumagad")


def test_assemble_drops_printed_numbers_and_joins_hyphens() -> None:
    assert assemble(["(", "84", ")", "kezeichanne", "[", "227", "]", "."])[0] == "kezeichanne."
    assert assemble(["5", ".", "zuiflomes", "stritant"])[0] == "zuiflomes stritant"
    assert assemble(["DER", ".", "SÂ-", "lig", "."], join_hyphens=True)[0] == "DER. SÂlig."
    assert assemble(["ne-ge-giêng"], join_hyphens=True)[0] == "ne-ge-giêng"
    assert assemble(["SÂ-", "lig"])[0] == "SÂ- lig"


def test_roman_heading_is_editorial() -> None:
    text = next(t for t in TEXTS if t.slug == "genesis")
    docs = read_subcorpus(_tables({"Gen_1": {"edition": ["I", "Uuela", "."],
                                             "spans": [("verse", 0, 0, "n/a"), ("verse", 1, 2, "556")]}},
                                  {"language": "as."}))
    assert build_units(text, docs) == [
        {"ref": "AsGen.1", "text": "I", "editorial": [[0, 1, "heading"]]},
        {"ref": "AsGen.1.556", "text": "Uuela."},
    ]


def test_otfrid_lines_from_rhyme_marks() -> None:
    # Otfrid I,2 in ReA: verse spans one token late; rhyme marks end each half-line.
    toks = ["II", ".", "INVOCATIO", ".", "Wola", "drúhtin", "mín", ",", "já", "bin", "scálc", "thin", ",",
            "thiu", "múater", "min", "ist", "si", "thin", "!"]
    spans = [("verse", 0, 4, "n/a"), ("verse", 5, 13, "1"),
             ("rhyme", 6, 6, "E"), ("rhyme", 11, 11, "E"), ("rhyme", 15, 15, "E"), ("rhyme", 18, 18, "E")]
    doc = _docs({"O_Otfr.Ev.1.2": {"edition": toks, "spans": spans}})["O_Otfr.Ev.1.2"]
    lines = rhyme_lines(doc)
    assert lines == [(4, 12, "1"), (13, 19, "2")]
    units = numbered_units(doc, "Otfr.1.2", "verse", spans=lines)
    assert [(u.ref, assemble(u.tokens)[0]) for u in units] == [
        ("Otfr.1.2", "II. INVOCATIO."),
        ("Otfr.1.2.1", "Wola drúhtin mín, já bin scálc thin,"),
        ("Otfr.1.2.2", "thiu múater min ist si thin!"),
    ]


def test_latin_tatian_skips_repeated_chapter() -> None:
    same = ["Nolite", "iudicare", "."]
    docs = _docs({"T_TatianLatein_(39)": {"edition": same, "spans": [("chapter", 0, 2, "39")]},
                  "T_TatianLatein_(40)": {"edition": same, "spans": [("chapter", 0, 2, "39")]},
                  "T_Tatianlatein_(41)": {"edition": ["Attendite", "."], "spans": [("chapter", 0, 1, "41")]}},
                 meta={"language": "lat."})
    text = next(t for t in TEXTS if t.slug == "tatian-lat")
    assert [u["ref"] for u in build_units(text, docs)] == ["Tat.39", "Tat.41"]


def test_scope_and_configuration() -> None:
    slugs = [t.slug for t in TEXTS]
    assert len(slugs) == len(set(slugs))
    assert {t.language for t in TEXTS} == {"goh", "osx", "lat"}
    used = {t.subcorpus for t in TEXTS}
    # Nothing dropped is ingested: the school texts, glosses, the gappy Benedictine Rule, Physiologus.
    assert not used & {k for k in DROPPED if not k.startswith("minor:")}
    minor_docs = {d for t in TEXTS for d in (t.docs or ())}
    assert not minor_docs & {"H_Hildebrandlied", "MZ_MerseburgerZaubersprueche", "MM_MementoMori",
                             "StE_Strassb.Eide", "LS_Bienensegen"}
    assert all(t.genre != "hagiography" for t in TEXTS)  # hagiography is an override (#558)
    assert rea.LICENSE == "cc-by-nc-sa-3.0"


def _raw(slug: str) -> dict | None:
    path = _RAW / f"{slug}.json"
    if not path.exists() or path.read_bytes().startswith(b"version https://git-lfs"):
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("slug,key,first,count", [
    ("tatian", "verses", "Tat.0", 1598),
    ("heliand", "paragraphs", "Hel.1.1", 306),
    ("otfrid", "paragraphs", "Otfr.L", 3995),
    ("notker-psalter", "paragraphs", "NPs.1.8", 677),
])
def test_raw_files(slug: str, key: str, first: str, count: int) -> None:
    raw = _raw(slug)
    if raw is None:
        pytest.skip("raw ReA data not present")
    units = raw[key]
    assert units[0]["ref"] == first
    assert len(units) == count
    for unit in units:
        editorial.check(unit["text"], unit.get("editorial", []), unit["ref"])


def test_benedictine_rule_chapters_and_gaps() -> None:
    gap = [".", ".", "."]
    docs = _docs({"B_0": {"edition": ["keuuisso", *gap, "herzun", "."]},
                  "B_1": {"edition": ["fona", "chunnum", "municho", "."], "spans": [("chapter", 0, 3, "1")]},
                  "B_53": {"edition": ["gesti", *gap], "spans": [("chapter", 0, 3, "53")]}})
    text = next(t for t in TEXTS if t.slug == "benedictine-rule")
    units = build_units(text, docs)
    assert [u["ref"] for u in units] == ["RB.0", "RB.1", "RB.53"]
    assert units[0] == {"ref": "RB.0", "text": f"keuuisso {LACUNA} herzun.", "editorial": [[9, 12, "lacuna"]]}
    latin = read_subcorpus(_tables({"B_61_J": {"edition": ["Si", "quis", "."]}}, {"language": "lat."}))
    assert build_units(next(t for t in TEXTS if t.slug == "benedictine-rule-lat"), latin) == [
        {"ref": "RB.61", "text": "Si quis."}]


# --- Verse units (#586) -----------------------------------------------------------------

def _lines(*texts: str, first: int = 1) -> list[rea.Unit]:
    """Line units ``X.{n}`` from whitespace-separated tokens."""
    return [rea.Unit(f"X.{n}", t.split(), str(n)) for n, t in enumerate(texts, start=first)]


def _texts(units: list[rea.Unit]) -> list[tuple[str, str]]:
    return [(u.ref, rea.assemble_unit(u)[0]) for u in units]


def test_sentence_units_run_to_a_line_that_ends_a_sentence() -> None:
    # Heliand 3-7 as ReA has them: sentences end at the caesura, mid-line.
    lines = _lines("reckean that girûni , that thie rîceo Crist",
                   "undar mancunnea mâriða gifrumida",
                   "mid uuordun endi mid uuercun . That uuolda thô uuîsara filo",
                   "liudo barno loƀon , lêra Cristes .",
                   "frummian , firiho barn . Than uuârun thoh sia fiori te thiu", first=3)
    assert _texts(rea.sentence_units(lines)) == [
        ("X.3", "reckean that girûni, that thie rîceo Crist undar mancunnea mâriða gifrumida "
                "mid uuordun endi mid uuercun. That uuolda thô uuîsara filo liudo barno loƀon, "
                "lêra Cristes."),
        ("X.7", "frummian, firiho barn. Than uuârun thoh sia fiori te thiu"),
    ]


def test_sentence_end_ignores_closing_quotes_and_keeps_headings_apart() -> None:
    heading = rea.Unit("X", ["I"])
    lines = _lines('quað he : " uuela', 'uuesan . "', "Thô geng he")
    assert [u.ref for u in rea.sentence_units([heading, *lines])] == ["X", "X.1", "X.3"]


def test_lacuna_across_a_line_join_keeps_its_offsets() -> None:
    lines = _lines("Manega uuâron * *", "* * that sia bigunnun .", "* *", "uuord godes .")
    units = rea.sentence_units(lines)
    body, spans = rea.assemble_unit(units[0])
    assert body == f"Manega uuâron {LACUNA} {LACUNA} that sia bigunnun."
    assert spans == [[14, 17, "lacuna"], [18, 21, "lacuna"]]
    assert all(body[s:e] == LACUNA for s, e, _ in spans)
    # A line that is only a lacuna stays in its unit.
    body, spans = rea.assemble_unit(units[1])
    assert (units[1].ref, body, spans) == ("X.3", f"{LACUNA} uuord godes.", [[0, 3, "lacuna"]])
    assert editorial.source_text({"text": body, "editorial": spans}) == "uuord godes."


def test_grouped_text_is_the_lines_joined() -> None:
    # Each line is assembled as it was when every line was a unit, joined with a space.
    lines = _lines('sprac he " ja', 'Ni uuis thu " , quað he .')
    grouped = rea.sentence_units(lines)
    assert _texts(grouped) == [("X.1", " ".join(assemble(line.tokens)[0] for line in lines))]
    assert _texts(grouped)[0][1] == 'sprac he "ja Ni uuis thu ", quað he.'


def test_otfrid_couplets() -> None:
    title = rea.Unit("Otfr.1.1", ["I", ".", "CUR", "SCRIPTOR"])
    lines = _lines("Was líuto filu in flíze , in managemo ágaleize ,",
                   "sie thaz in scríp gicleiptin , thaz sie iro námon breittin ;",
                   "Sie thés in io gilícho flizzun gúallicho ,",
                   "in búachon man giméinti thio iro chúanheiti .")
    units = rea.couplet_units([title, *lines], "O_Otfr.Ev.1.1")
    assert [u.ref for u in units] == ["Otfr.1.1", "X.1", "X.3"]
    assert _texts(units)[1][1] == ("Was líuto filu in flíze, in managemo ágaleize, sie thaz in scríp "
                                   "gicleiptin, thaz sie iro námon breittin;")
    with pytest.raises(ReAError, match="couplets"):
        rea.couplet_units(lines[:3], "odd")


def test_rhymed_strophes_keep_triplets_and_refrains() -> None:
    # Ludwigslied 1-2 and 33-35: a couplet, and a three-line strophe kept whole.
    lud = _lines("Einan kuning uueiz ih , Heizsit her Hluduig ,",
                 "Ther gerno gode thionot : Ih uueiz her imos lonot .",
                 "Hera santa mih god Ioh mir selbo gibod ,",
                 "Ob hiu rat thuhti , Thaz ih hier geuuhti ,",
                 "Mih selbon nisparoti , Uncih hiu gineriti .")
    assert [u.ref for u in rea.strophe_units()(lud)] == ["X.1", "X.3"]
    # Petruslied: two lines and the Kyrie refrain.
    petr = _lines("Unsar trohtin hat farsalt sancte Petre giuualt ,",
                  "daz er mac ginerian ze imo dingenten man .",
                  "Kyrie eleyson , Christe eleyson .",
                  "Er hapet ouh mit uuortun himilriches portun :",
                  "dar in mach er skerian den er uuili nerian .",
                  "Kirie eleison , Christe eleyson .")
    units = rea.strophe_units(rea._PETR_REFRAIN)(petr)
    assert [u.ref for u in units] == ["X.1", "X.4"]
    assert _texts(units)[0][1].endswith("dingenten man. Kyrie eleyson, Christe eleyson.")


def test_printed_strophe_number_starts_a_unit_and_is_dropped() -> None:
    lines = _lines("1 . Gorio vuor zi mahalo ,", "vona dero marko .", "vuor er zi demo ringe ,",
                   "2 . Dô spuonun inan alla kuninga :", "woltôn si inan irkêren .")
    assert _texts(rea.strophe_units()(lines)) == [
        ("X.1", "Gorio vuor zi mahalo, vona dero marko."), ("X.3", "vuor er zi demo ringe,"),
        ("X.4", "Dô spuonun inan alla kuninga: woltôn si inan irkêren.")]


def test_verse_works_are_grouped_and_prose_is_not() -> None:
    by_slug = {t.slug: t for t in TEXTS}
    for slug in ("heliand", "genesis", "otfrid", "muspilli", "ludwigslied", "georgslied", "petruslied"):
        assert not by_slug[slug].as_verses, slug  # paragraphs: normalize cuts long units
    for slug in ("tatian", "murbach-hymns", "murbach-hymns-lat"):
        assert by_slug[slug].as_verses, slug
    # Prose builds no grouped units.
    docs = _docs({"B_1": {"edition": ["fona", "chunnum", "."], "spans": [("chapter", 0, 2, "1")]}})
    assert all(u.lines is None for u in by_slug["benedictine-rule"].build(docs))
