"""CCEL English translations (#351): McClure and Feltoe's Etheria, HTML to units."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica import editorial
from scripts.ingest.ccel_eng import BOOKS, ETHERIA, parse_etheria, spionic

_RAW = Path(__file__).resolve().parents[1] / "data" / "raw" / "ccel-eng"

# A cut-down copy of the transcription's markup: the opening lacuna before the
# first heading, footnotes at each page's foot (one marker left as a plain
# digit, one note running over the page break), a paragraph running over the
# page break, Greek in the SPIonic font, the Mac em dash, a supplement, a
# bracketed remark, and the numbered headings of the liturgical part.
_HTML = """<HTML><BODY>
<P CLASS="TH">A. K. M. Adam<BR>
<P CLASS="MH">THE PILGRIMAGE OF ETHERIA</P><P>
<P>

<FONT SIZE="-1"><I>(Much is wanting.)</I></FONT>\t<BR>
<BR>


THE APPROACH TO SINAI <P>


. . . . . . . . .<P>


. . . were pointed out. Here are the graves of lust.<SUP>1</SUP> The mount
of God, which is in sight here\xe3[because] the ascent was easier\xe3and Faran,2 our route
was to cross the valley, and its <P>


<SUP>1</SUP> Eng. Bible, <I>Kibroth-hattaavah</I>.<BR>

<SUP>2 </SUP>LXX, <FONT SIZE="+1" FACE="spionic, symbol">Fara&n</FONT>: Eng. Bible, Paran.
{footnote continued below}

<hr>
<2><P>


breadth four miles.<SUP>1</SUP><P>


I<BR>


DAILY OFFICES<P>


1. <I>Matins</I>.<SUP>2</SUP><P>


Every day before cockcrow. [Mr. Conybeare believes this to be a later custom of the
church.]<P>


{footnote continued from above} Num. x. 12.<BR>

<SUP>1</SUP> Exod. xxiv. 18.<BR>

<SUP>2</SUP> <FONT SIZE="+1" FACE="spionic, symbol">to_ luxniko&n</FONT>.

<HR>
<P CLASS="TH">
A K M Adam<BR>
</BODY></HTML>"""


def _units() -> dict[str, dict]:
    return {u["ref"]: u for u in parse_etheria(_HTML)}


def _spans(unit: dict) -> list[tuple[str, str]]:
    return [(unit["text"][s:e], k) for s, e, k in unit.get("editorial", [])]


def test_units_and_refs() -> None:
    units = _units()
    assert list(units) == ["Eth.1", "Eth.1.1", "Eth.1.2", "Eth.2", "Eth.2.1"]
    for unit in units.values():
        editorial.check(unit["text"], unit.get("editorial", []), unit["ref"])


def test_opening_lacuna_and_heading() -> None:
    units = _units()
    assert _spans(units["Eth.1"]) == [("THE APPROACH TO SINAI", "heading")]
    assert _spans(units["Eth.1.1"]) == [("(Much is wanting.)", "lacuna"),
                                        (". . . . . . . . .", "lacuna")]


def test_paragraph_over_page_break_with_notes() -> None:
    unit = _units()["Eth.1.2"]
    assert unit["text"].startswith(". . . were pointed out. Here are the graves of lust. "
                                   "[Eng. Bible, Kibroth-hattaavah.] The mount of God")
    assert "which is in sight here—[because] the ascent was easier—and Faran," in unit["text"]
    assert unit["text"].endswith("and its breadth four miles. [Exod. xxiv. 18.]")
    assert _spans(unit) == [
        (". . . ", "lacuna"),
        ("[Eng. Bible, Kibroth-hattaavah.]", "note"),
        ("[because]", "supplement"),
        ("[LXX, Φαράν: Eng. Bible, Paran. Num. x. 12.]", "note"),
        ("[Exod. xxiv. 18.]", "note"),
    ]


def test_merged_headings_and_remarks() -> None:
    units = _units()
    head = units["Eth.2"]
    assert head["text"] == "I. DAILY OFFICES. 1. Matins. [τὸ λυχνικόν.]"
    assert _spans(head) == [("I. DAILY OFFICES. 1. Matins.", "heading"),
                            ("[τὸ λυχνικόν.]", "note")]
    body = units["Eth.2.1"]
    assert _spans(body) == [("[Mr. Conybeare believes this to be a later custom of the "
                             "church.]", "note")]


@pytest.mark.parametrize(("code", "greek"), [
    ("Fara&n", "Φαράν"),
    ("e)n gh|~ Ge&sem 'Arabi/a.", "ἐν γῇ Γέσεμ Ἀραβία."),
    ("9Hrw&wn po&lin", "Ἡρώων πόλιν"),
    ("o1ros", "ὄρος"),
    ("o3pou", "ὅπου"),
    ("Au)si=tiv", "Αὐσῖτις"),
    ("kata_", "κατὰ"),
    ("th~v", "τῆς"),
])
def test_spionic(code: str, greek: str) -> None:
    assert spionic(code) == greek


def test_spionic_rejects_unknown() -> None:
    with pytest.raises(ValueError, match="unknown SPIonic"):
        spionic("a@b")


def test_missing_note_raises() -> None:
    with pytest.raises(ValueError, match="footnote 1 has no marker"):
        parse_etheria(_HTML.replace("lust.<SUP>1</SUP>", "lust."))


def test_books() -> None:
    assert BOOKS == (ETHERIA,)
    assert ETHERIA.translation_of == "csel/stoa0111/stoa001/opp-lat3"


def test_raw_file() -> None:
    path = _RAW / f"{ETHERIA.slug}.json"
    if not path.exists() or path.read_bytes().startswith(b"version https://git-lfs"):
        pytest.skip("raw data not present")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["work"]["translation_of"] == ETHERIA.translation_of
    assert data["work"]["license"] == "public_domain"
    refs = [u["ref"] for u in data["paragraphs"]]
    assert len(refs) == len(set(refs)) == ETHERIA.units
    for unit in data["paragraphs"]:
        editorial.check(unit["text"], unit.get("editorial", []), unit["ref"])
        assert "" not in unit["text"] and "<" not in unit["text"]
