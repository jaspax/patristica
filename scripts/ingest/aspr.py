"""
Ingestor for the Anglo-Saxon Poetic Records (#565, part of #223).

Source: *The Anglo-Saxon Poetic Records*, ed. G. P. Krapp and E. V. K. Dobbie,
        6 vols. (New York 1931–1953); digital text by Gregory Hidley for the
        Toronto *Dictionary of Old English*, corrected by O. Duncan
        Macrae-Gibson. Oxford Text Archive item 3009,
        https://hdl.handle.net/20.500.14106/3009
Format: one TEI P5 XML file (``3009.xml``), every poem a ``<div>`` of ``<l>``
License: CC BY-SA 3.0 (the file's ``<availability><licence>`` and the OTA
         record); the legacy item 1936 is CC BY-NC-SA 3.0 and is not used.

Scope
-----
Religious, homiletic, devotional and wisdom poems are ingested, one work per
poem (:data:`POEMS`). Clearly secular texts are left out (the scope rule of
the #223 survey; :data:`DROPPED` gives each a reason): heroic and historical
poetry, the riddles and the metrical charms. The metrical Paris Psalter
(``A5.*``) and the psalm fragments of the Benedictine Office (``A24.*``) are
held back (:data:`DEFERRED`): the TEI has no verse numbers, so they cannot be
ingested as Scripture with ``Ps.{n}.{v}`` refs yet (#569). Every ``<div>``
of the file must be listed in one of the three tables, so an upstream change
is an error, not a silent drop.

*Christ* is one ``<div>`` (ASPR's continuous lines 1–1664) and is split into
*Christ I–III* at ASPR's divisions (440, 867), since Cynewulf signed only
*Christ II*; the three keep ASPR's continuous line numbers. The *Meters of
Boethius* (``A6.*``, proem and 31 meters) are one work with a section per
meter.

Lines and units
---------------
The TEI has no line numbers. A verse line is an ``<l>`` with a
``<caesura/>``; counting those gives ASPR's line numbers (checked: *Genesis*
2936, *Christ* 1664, *Guthlac* 1379, *Christ and Satan* 729, *Juliana* 731,
*The Lord's Prayer II* 123, *The Creed* 58, *Psalm 50* 157). An ``<l>``
without a caesura is not a numbered line: a closing *Amen*, the Brussels
Cross's prose inscription, or a line wholly in square brackets, which is a
Latin cue the poem paraphrases (*Lord's Prayer II–III*, *Gloria I*, *Creed*,
*Psalm 50*) or a scribe's *Finit*.

Units are sentence groups, by a fixed rule: a unit runs from a numbered line
through the next numbered line whose text ends a sentence (``.``, ``!`` or
``?``, closing quotes and brackets aside). A Latin cue starts a new unit, and
unnumbered lines at the end of a poem join its last unit. The ref is the
poem's ref prefix and the unit's first line number (``Dream.1``,
``Christ.440``; ``MBo.{meter}.{line}`` in the Meters, whose meter headings are
units of their own at ``MBo.{meter}``, wholly ``heading``). Normalize cuts
long units into derived verses.

Text
----
Lines are joined with a space and the caesura is a space; whitespace is
collapsed. The spelling is the TEI's (þ ð æ, ę for the TEI's ``<g
ref="ecaudata">``; ASPR prints no length marks). Editorial material (#236):

- ``<unclear>`` is ASPR's emended or supplied reading (e.g. *Dream of the
  Rood* 2 *hwæt*, MS *hæt*; 17 *wealdendes*, MS *wealdes*): kept as printed
  and marked ``supplement``, so it is translated and embedded;
- ``<gap/>`` (text lost) becomes ``[…]``, marked ``lacuna``, and so is each
  run of ``/``, the digital text's sign for letters lost to damage (the
  Exeter Book's burnt leaves);
- a Latin cue or *Finit* line is marked ``rubric``;
- ``<foreign xml:lang="rune">`` gives a rune as its transliteration (``F``,
  ``EA``); it becomes the Anglo-Saxon rune ASPR prints (``ᚠ``, ``ᛠ``),
  :data:`RUNES`;
- square brackets inside a line (Roman numerals ``[XXX]``, macaronic Latin)
  are the manuscript's text and stay unmarked.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lxml import etree

from patristica.models import Work
from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

SOURCE_ID = "aspr"

HANDLE = "https://hdl.handle.net/20.500.14106/3009"
URL = ("https://llds.phon.ox.ac.uk/llds/xmlui/bitstream/handle/20.500.14106/3009/"
       "3009.xml?sequence=9&isAllowed=y")
LICENSE = "cc-by-sa-3.0"
LICENSE_URL = "http://creativecommons.org/licenses/by-sa/3.0/"

TEI_NS = "http://www.tei-c.org/ns/1.0"
_NS = {"tei": TEI_NS}
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

LACUNA = "[…]"

#: The TEI's rune transliterations → the Anglo-Saxon futhorc (Unicode Runic).
#: ``Z`` is eoh (*Rune Poem* 41, "byþ utan unsmeþe treow") and ``X`` eolhx;
#: ``Q`` is cweorð (*Solomon and Saturn*, beside its Latin letter).
RUNES: dict[str, str] = {
    "F": "ᚠ", "U": "ᚢ", "þ": "ᚦ", "O": "ᚩ", "R": "ᚱ", "C": "ᚳ", "G": "ᚷ",
    "W": "ᚹ", "H": "ᚻ", "N": "ᚾ", "I": "ᛁ", "J": "ᛄ", "Z": "ᛇ", "P": "ᛈ",
    "X": "ᛉ", "S": "ᛋ", "T": "ᛏ", "B": "ᛒ", "E": "ᛖ", "M": "ᛗ", "L": "ᛚ",
    "NG": "ᛝ", "OE": "ᛟ", "D": "ᛞ", "A": "ᚪ", "æ": "ᚫ", "Y": "ᚣ", "IO": "ᛡ",
    "EA": "ᛠ", "Q": "ᛢ",
}

_SENTENCE_END = re.compile(r"[.!?][\"'”’)\]]*$")
_BRACKETED = re.compile(r"\[[^\[\]]*\][.,;:]*")


class AsprError(ValueError):
    """The TEI is not structured as this ingestor expects."""


@dataclass(frozen=True)
class Poem:
    div: str            # the TEI <div xml:id> (Cameron numbers: A2.5), or a prefix ("A6")
    slug: str           # local work id: a slug of ASPR's title, never renamed
    title: str
    prefix: str         # ref prefix
    date_range: tuple[int, int]
    date_confidence: str = "approximate"
    author: str | None = None
    lines: tuple[int, int] | None = None  # ASPR line range, for a split <div>
    note: str = ""      # for the edition string where the <div> has no <bibl>


_EXETER = (700, 975)   # composed before the Exeter Book (c. 965-975)
_VERCELLI = (700, 975)  # before the Vercelli Book (c. 950-975)

#: The poems ingested, in ASPR order.
POEMS: tuple[Poem, ...] = (
    # ASPR 1, the Junius Manuscript
    Poem("A1.1", "genesis", "Genesis (Genesis A and B)", "Genesis", (700, 900)),
    Poem("A1.2", "exodus", "Exodus", "Exodus", (700, 900)),
    Poem("A1.3", "daniel", "Daniel", "Daniel", (700, 900)),
    Poem("A1.4", "christ-and-satan", "Christ and Satan", "ChristSatan", (800, 975), "uncertain"),
    # ASPR 2, the Vercelli Book
    Poem("A2.1", "andreas", "Andreas", "Andreas", (800, 950)),
    Poem("A2.2", "fates-of-the-apostles", "The Fates of the Apostles", "Fates", (800, 900),
         author="Cynewulf"),
    Poem("A2.3", "soul-and-body-i", "Soul and Body I", "SoulBodyI", _VERCELLI, "uncertain"),
    Poem("A2.4", "homiletic-fragment-i", "Homiletic Fragment I", "HomFragI", _VERCELLI,
         "uncertain"),
    Poem("A2.5", "dream-of-the-rood", "The Dream of the Rood", "Dream", _VERCELLI),
    Poem("A2.6", "elene", "Elene", "Elene", (800, 900), author="Cynewulf"),
    # ASPR 3, the Exeter Book
    Poem("A3.1", "christ-i", "Christ I (The Advent Lyrics)", "Christ", _EXETER, "uncertain",
         lines=(1, 439)),
    Poem("A3.1", "christ-ii", "Christ II (The Ascension)", "Christ", (800, 900),
         author="Cynewulf", lines=(440, 866)),
    Poem("A3.1", "christ-iii", "Christ III (Christ in Judgement)", "Christ", _EXETER,
         "uncertain", lines=(867, 1664)),
    Poem("A3.2", "guthlac", "Guthlac (Guthlac A and B)", "Guthlac", (730, 975)),
    Poem("A3.3", "azarias", "Azarias", "Azarias", _EXETER, "uncertain"),
    Poem("A3.4", "phoenix", "The Phoenix", "Phoenix", (800, 950)),
    Poem("A3.5", "juliana", "Juliana", "Juliana", (800, 900), author="Cynewulf"),
    Poem("A3.6", "wanderer", "The Wanderer", "Wanderer", _EXETER, "uncertain"),
    Poem("A3.7", "gifts-of-men", "The Gifts of Men", "Gifts", _EXETER, "uncertain"),
    Poem("A3.8", "precepts", "Precepts", "Precepts", _EXETER, "uncertain"),
    Poem("A3.9", "seafarer", "The Seafarer", "Seafarer", _EXETER, "uncertain"),
    Poem("A3.10", "vainglory", "Vainglory", "Vainglory", _EXETER, "uncertain"),
    Poem("A3.12", "fortunes-of-men", "The Fortunes of Men", "Fortunes", _EXETER, "uncertain"),
    Poem("A3.13", "maxims-i", "Maxims I", "MaximsI", _EXETER, "uncertain"),
    Poem("A3.14", "order-of-the-world", "The Order of the World", "OrderWorld", _EXETER,
         "uncertain"),
    Poem("A3.15", "riming-poem", "The Riming Poem", "Riming", (850, 975), "uncertain"),
    Poem("A3.16", "panther", "The Panther", "Panther", _EXETER, "uncertain"),
    Poem("A3.17", "whale", "The Whale", "Whale", _EXETER, "uncertain"),
    Poem("A3.18", "partridge", "The Partridge", "Partridge", _EXETER, "uncertain"),
    Poem("A3.19", "soul-and-body-ii", "Soul and Body II", "SoulBodyII", _EXETER, "uncertain"),
    Poem("A3.24", "judgment-day-i", "The Judgment Day I", "JudgmentDayI", _EXETER, "uncertain"),
    Poem("A3.25", "resignation", "Resignation", "Resignation", _EXETER, "uncertain"),
    Poem("A3.26", "descent-into-hell", "The Descent into Hell", "Descent", _EXETER, "uncertain"),
    Poem("A3.27", "alms-giving", "Alms-Giving", "Alms", _EXETER, "uncertain"),
    Poem("A3.28", "pharaoh", "Pharaoh", "Pharaoh", _EXETER, "uncertain"),
    Poem("A3.29", "lords-prayer-i", "The Lord's Prayer I", "LordsPrayerI", _EXETER, "uncertain"),
    Poem("A3.30", "homiletic-fragment-ii", "Homiletic Fragment II", "HomFragII", _EXETER,
         "uncertain"),
    # ASPR 4
    Poem("A4.2", "judith", "Judith", "Judith", (850, 1000), "uncertain"),
    # ASPR 5
    Poem("A6", "meters-of-boethius", "The Meters of Boethius", "MBo", (880, 950),
         author="Alfred the Great",
         note="Krapp, G.P., The Paris Psalter and the Meters of Boethius, ASPR 5 (New York 1932)"),
    # ASPR 6, the minor poems
    Poem("A12", "rune-poem", "The Rune Poem", "Rune", (800, 1000), "uncertain"),
    Poem("A13", "solomon-and-saturn", "Solomon and Saturn", "SolSat", (850, 1000), "uncertain"),
    Poem("A14", "menologium", "The Menologium", "Menologium", (965, 1000)),
    Poem("A15", "maxims-ii", "Maxims II", "MaximsII", (900, 1050), "uncertain"),
    Poem("A16", "proverb-from-winfrids-time", "A Proverb from Winfrid's Time", "Winfrid",
         (725, 760)),
    Poem("A17", "judgment-day-ii", "The Judgment Day II", "JudgmentDayII", (950, 1050)),
    Poem("A18", "rewards-of-piety", "The Rewards of Piety", "Rewards", (950, 1050)),
    Poem("A19", "summons-to-prayer", "A Summons to Prayer", "Summons", (950, 1050),
         note="Dobbie, E.V.K., The Anglo-Saxon Minor Poems, ASPR 6 (New York 1942)"),
    Poem("A20", "lords-prayer-ii", "The Lord's Prayer II", "LordsPrayerII", (950, 1050)),
    Poem("A21", "gloria-i", "The Gloria I", "GloriaI", (950, 1050)),
    Poem("A22", "lords-prayer-iii", "The Lord's Prayer III", "LordsPrayerIII", (950, 1050)),
    Poem("A23", "creed", "The Creed", "Creed", (950, 1050)),
    Poem("A25", "kentish-hymn", "The Kentish Hymn", "KentishHymn", (900, 975)),
    Poem("A26", "psalm-50", "Psalm 50", "Psalm50", (900, 975)),
    Poem("A27", "gloria-ii", "The Gloria II", "GloriaII", (900, 1050), "uncertain"),
    Poem("A28", "prayer", "A Prayer", "Prayer", (950, 1050), "uncertain"),
    Poem("A29", "thureth", "Thureth", "Thureth", (1000, 1050)),
    Poem("A30", "aldhelm", "Aldhelm", "Aldhelm", (925, 1000)),
    Poem("A31", "seasons-for-fasting", "The Seasons for Fasting", "Seasons", (950, 1050)),
    Poem("A32.1", "caedmons-hymn-northumbrian", "Cædmon's Hymn (Northumbrian Version)",
         "CaedmonN", (657, 680), author="Cædmon"),
    Poem("A32.2", "caedmons-hymn-west-saxon", "Cædmon's Hymn (West-Saxon Version)",
         "CaedmonWS", (657, 680), author="Cædmon"),
    Poem("A33.1", "bedes-death-song-northumbrian", "Bede's Death Song (Northumbrian Version)",
         "BedeN", (731, 735), author="Bede"),
    Poem("A33.2", "bedes-death-song-hague", "Bede's Death Song (The Hague Version)", "BedeH",
         (731, 735), author="Bede"),
    Poem("A33.3", "bedes-death-song-west-saxon", "Bede's Death Song (West Saxon Version)",
         "BedeWS", (731, 735), author="Bede"),
    Poem("A35", "latin-english-proverbs", "Latin-English Proverbs", "LatEngProverbs",
         (900, 1050), "uncertain"),
    Poem("A36", "metrical-preface-to-the-pastoral-care",
         "The Metrical Preface to the Pastoral Care", "PastoralPreface", (890, 899),
         author="Alfred the Great"),
    Poem("A37", "metrical-epilogue-to-the-pastoral-care",
         "The Metrical Epilogue to the Pastoral Care", "PastoralEpilogue", (890, 899),
         author="Alfred the Great"),
    Poem("A38", "metrical-preface-to-waerferths-dialogues",
         "The Metrical Preface to Wærferth's Translation of Gregory's Dialogues",
         "DialoguesPreface", (889, 900)),
    Poem("A39", "metrical-epilogue-to-ms-41-ccc",
         "The Metrical Epilogue to MS. 41, Corpus Christi College, Cambridge",
         "Ccc41Epilogue", (950, 1050), "uncertain"),
    Poem("A41", "brussels-cross", "The Brussels Cross", "BrusselsCross", (975, 1050),
         note="Dobbie, E.V.K., The Anglo-Saxon Minor Poems, ASPR 6 (New York 1942)"),
)

#: Left out under the scope rule (#223): div id or prefix → reason.
DROPPED: dict[str, str] = {
    "A3.11": "Widsith: heroic",
    "A3.20": "Deor: heroic",
    "A3.21": "Wulf and Eadwacer: secular elegy",
    "A3.22.": "Riddles 1-59",
    "A3.23": "The Wife's Lament: secular elegy",
    "A3.31.": "Riddles 30b and 60",
    "A3.32": "The Husband's Message: secular",
    "A3.33": "The Ruin: secular",
    "A3.34.": "Riddles 61-95",
    "A4.1": "Beowulf: heroic",
    "A7": "The Battle of Finnsburh: heroic",
    "A8.": "Waldere: heroic",
    "A9": "The Battle of Maldon: historical",
    "A10.": "the Chronicle poems: historical",
    "A11": "Durham: composed 1104-1109, out of period",
    "A34": "The Leiden Riddle: riddle",
    "A43.": "the metrical charms",
}

#: Held back for a follow-up (#569): no verse numbers in the TEI.
DEFERRED: dict[str, str] = {
    "A5.": "the metrical Paris Psalter (Ps 51-150)",
    "A24.": "psalm fragments of the Benedictine Office",
}


def _listed(div_id: str, table: dict[str, str]) -> bool:
    return any(div_id == k or (k.endswith(".") and div_id.startswith(k)) for k in table)


def _poem_divs(poem: Poem, div_id: str) -> bool:
    return div_id == poem.div or (poem.div == "A6" and div_id.startswith("A6."))


def _norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", text)


class _Builder:
    """Collects a line's text and its editorial spans."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.spans: list[list[Any]] = []
        self.length = 0

    def add(self, text: str | None) -> None:
        if text:
            self.parts.append(text)
            self.length += len(text)

    def text(self) -> str:
        return "".join(self.parts)


def _walk(el: etree._Element, out: _Builder, where: str) -> None:
    for child in el:
        if not isinstance(child.tag, str):  # comment or processing instruction
            out.add(child.tail)
            continue
        tag = etree.QName(child).localname
        if tag == "caesura":
            out.add(" ")
        elif tag == "unclear":
            start = out.length
            out.add(child.text)
            _walk(child, out, where)
            out.spans.append([start, out.length, "supplement"])
        elif tag == "gap":
            start = out.length
            out.add(LACUNA)
            out.spans.append([start, out.length, "lacuna"])
        elif tag == "g":
            out.add(child.text)
        elif tag == "foreign":
            if child.get(_XML_LANG) != "rune" or len(child):
                raise AsprError(f"{where}: unexpected <foreign> {etree.tostring(child)[:60]!r}")
            letters = (child.text or "").strip()
            if letters not in RUNES:
                raise AsprError(f"{where}: unknown rune transliteration {letters!r}")
            out.add(RUNES[letters])
        else:
            raise AsprError(f"{where}: unexpected element <{tag}>")
        out.add(child.tail)


def _collapse(raw: str, spans: list[list[Any]]) -> tuple[str, list[list[Any]]]:
    """Collapse whitespace in *raw* and move the span offsets with it."""
    chars: list[str] = []
    offset_map: list[int] = []
    prev_space = True  # also strips leading space
    for ch in raw:
        offset_map.append(len(chars))
        if ch.isspace():
            if not prev_space:
                chars.append(" ")
            prev_space = True
        else:
            chars.append(ch)
            prev_space = False
    offset_map.append(len(chars))
    text = "".join(chars).rstrip(" ")
    out: list[list[Any]] = []
    for s, e, k in spans:
        ns, ne = offset_map[s], min(offset_map[e], len(text))
        # Trim whitespace the span may have picked up at its ends.
        while ns < ne and text[ns] == " ":
            ns += 1
        while ne > ns and text[ne - 1] == " ":
            ne -= 1
        if ns < ne:
            out.append([ns, ne, k])
    return text, out


def line_text(el: etree._Element, where: str = "") -> tuple[str, list[list[Any]]]:
    """An ``<l>``'s text, whitespace collapsed, and its editorial spans."""
    out = _Builder()
    out.add(el.text)
    _walk(el, out, where)
    text, spans = _collapse(out.text(), out.spans)
    # Runs of "/" mark letters lost to damage: lacunae, unless inside a marked span.
    for m in re.finditer(r"/+", text):
        if not any(s < m.end() and m.start() < e for s, e, _ in spans):
            spans.append([m.start(), m.end(), "lacuna"])
    spans.sort()
    return text, spans


@dataclass
class _Line:
    num: int | None     # ASPR line number; None for an unnumbered line
    text: str
    spans: list[list[Any]]
    cue: bool           # a wholly bracketed unnumbered line (Latin cue, Finit)


def read_lines(div: etree._Element, where: str) -> list[_Line]:
    """A poem ``<div>``'s lines, numbered as ASPR numbers them."""
    lines: list[_Line] = []
    num = 0
    for child in div:
        if not isinstance(child.tag, str):
            continue
        tag = etree.QName(child).localname
        if tag in ("head", "bibl"):
            continue
        if tag != "l":
            raise AsprError(f"{where}: unexpected element <{tag}>")
        text, spans = line_text(child, f"{where} after line {num}")
        if not text:
            raise AsprError(f"{where}: empty line after line {num}")
        if child.find("tei:caesura", _NS) is not None:
            num += 1
            lines.append(_Line(num, text, spans, cue=False))
        else:
            cue = bool(_BRACKETED.fullmatch(text))
            if cue:
                spans = [[0, len(text), "rubric"]]
            lines.append(_Line(None, text, spans, cue=cue))
    return lines


def _join(lines: list[_Line]) -> tuple[str, list[list[Any]]]:
    text = ""
    spans: list[list[Any]] = []
    for line in lines:
        if text:
            text += " "
        spans.extend([s + len(text), e + len(text), k] for s, e, k in line.spans)
        text += line.text
    return text, spans


def group_units(lines: list[_Line], prefix: str) -> list[dict[str, Any]]:
    """Sentence-group units of a poem's lines (see the module docstring)."""
    groups: list[list[_Line]] = []
    cur: list[_Line] = []
    for line in lines:
        if line.cue and any(x.num is not None for x in cur):
            groups.append(cur)
            cur = []
        cur.append(line)
        if line.num is not None and _SENTENCE_END.search(line.text):
            groups.append(cur)
            cur = []
    if cur:
        if any(x.num is not None for x in cur) or not groups:
            groups.append(cur)
        else:  # trailing unnumbered lines (Amen, Finit) join the last unit
            groups[-1].extend(cur)
    units: list[dict[str, Any]] = []
    for group in groups:
        first = next((x.num for x in group if x.num is not None), None)
        if first is None:
            raise AsprError(f"{prefix}: a unit with no numbered line: {group[0].text!r}")
        text, spans = _join(group)
        unit: dict[str, Any] = {"ref": f"{prefix}.{first}", "text": text}
        if spans:
            unit["editorial"] = spans
        units.append(unit)
    return units


def _divs(xml: bytes) -> list[etree._Element]:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=True)
    root = etree.fromstring(xml, parser)
    body = root.find("tei:text/tei:body", _NS)
    if body is None:
        raise AsprError("no <body>")
    divs = body.findall("tei:div", _NS)
    for div in divs:
        if div.findall("tei:div", _NS):
            raise AsprError(f"{div.get(_XML_ID)}: nested <div>")
    return divs


def check_licence(xml: bytes) -> None:
    """Raise unless the file's own header gives CC BY-SA 3.0."""
    root = etree.fromstring(xml, etree.XMLParser(resolve_entities=False, no_network=True))
    lic = root.find(".//tei:availability/tei:licence", _NS)
    target = lic.get("target") if lic is not None else None
    if target != LICENSE_URL:
        raise AsprError(f"the file's licence is not CC BY-SA 3.0: {target!r}")


def bibl(div: etree._Element) -> str:
    el = div.find("tei:bibl", _NS)
    return _norm_space("".join(el.itertext())).strip() if el is not None else ""


def parse_poems(
    xml: bytes,
    poems: tuple[Poem, ...] = POEMS,
    dropped: dict[str, str] = DROPPED,
    deferred: dict[str, str] = DEFERRED,
) -> list[tuple[Poem, list[dict[str, Any]], str]]:
    """Every kept poem with its raw units and ASPR citation, in ASPR order."""
    divs = _divs(xml)
    by_id: dict[str, etree._Element] = {}
    for div in divs:
        div_id = div.get(_XML_ID) or ""
        kept = any(_poem_divs(p, div_id) for p in poems)
        listed = [kept, _listed(div_id, dropped), _listed(div_id, deferred)]
        if sum(listed) != 1:
            raise AsprError(f"<div xml:id={div_id!r}> is not listed exactly once "
                            "in POEMS, DROPPED or DEFERRED")
        by_id[div_id] = div
    out: list[tuple[Poem, list[dict[str, Any]], str]] = []
    for poem in poems:
        if poem.div == "A6":
            units = _meters(poem, [d for i, d in by_id.items() if i.startswith("A6.")])
            out.append((poem, units, poem.note))
            continue
        div = by_id.get(poem.div)
        if div is None:
            raise AsprError(f"{poem.slug}: no <div xml:id={poem.div!r}>")
        lines = read_lines(div, poem.div)
        if poem.lines:
            lo, hi = poem.lines
            idx = [i for i, x in enumerate(lines) if x.num is not None and lo <= x.num <= hi]
            if not idx or lines[idx[0]].num != lo or lines[idx[-1]].num != hi:
                raise AsprError(f"{poem.slug}: lines {lo}-{hi} not found")
            # Unnumbered lines after the range's last line go with it only at the end.
            end = idx[-1] + 1
            if hi == max(x.num or 0 for x in lines):
                end = len(lines)
            lines = lines[idx[0]:end]
        out.append((poem, group_units(lines, poem.prefix), bibl(div) or poem.note))
    return out


def _meters(poem: Poem, divs: list[etree._Element]) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    expected = 0
    for div in divs:
        div_id = div.get(_XML_ID) or ""
        n = int(div_id.split(".")[1])
        if n != expected:
            raise AsprError(f"{div_id}: meter {n} follows meter {expected - 1}")
        expected += 1
        head = div.find("tei:head", _NS)
        title = _norm_space("".join(head.itertext())).strip() if head is not None else ""
        m = re.fullmatch(r"The Meters of Boethius: (Proem|Meter \d+)", title)
        if not m:
            raise AsprError(f"{div_id}: unexpected heading {title!r}")
        heading = m.group(1)
        sect = f"{poem.prefix}.{n}"
        units.append({"ref": sect, "text": heading, "editorial": [[0, len(heading), "heading"]]})
        units.extend(group_units(read_lines(div, div_id), sect))
    return units


def edition(citation: str) -> str:
    base = ("The Anglo-Saxon Poetic Records, ed. G. P. Krapp and E. V. K. Dobbie (New York, "
            "1931-1953); digital text by Gregory Hidley for the Dictionary of Old English "
            "(Toronto), corrected by O. Duncan Macrae-Gibson; Oxford Text Archive 3009 "
            "(University of Oxford, CC BY-SA 3.0)")
    return f"{base}; {citation}" if citation else base


def make_work(poem: Poem, citation: str) -> Work:
    return Work(
        work_id=f"{SOURCE_ID}/{poem.slug}",
        source_id=SOURCE_ID,
        author=poem.author,
        title=poem.title,
        date_composed=None,
        date_range=poem.date_range,
        date_confidence=poem.date_confidence,  # type: ignore[arg-type]
        genre="patristic",  # exceptions: patristica/data/genre_overrides.csv
        language="ang",
        tradition="latin",
        license=LICENSE,
        provenance_url=HANDLE,
        edition=edition(citation),
        translation_of=None,
    )


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Read the ASPR TEI file and write one raw JSON file per kept poem."""
    out_dir = output_dir / SOURCE_ID
    paths = {p.slug: out_dir / f"{p.slug}.json" for p in POEMS}
    if not force and all(path.exists() for path in paths.values()):
        return [Work(**json.loads(path.read_text(encoding="utf-8"))["work"])
                for path in paths.values()]
    xml_path = download_file(URL, output_dir / "_cache" / SOURCE_ID / "3009.xml",
                             etag_cache=False, force=False)
    xml = xml_path.read_bytes()
    check_licence(xml)
    works: list[Work] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for poem, units, citation in parse_poems(xml):
        work = make_work(poem, citation)
        path = paths[poem.slug]
        if force or not path.exists():
            path.write_text(json.dumps({"work": work.model_dump(), "paragraphs": units},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
            log.debug("%s: %d units", work.work_id, len(units))
        works.append(work)
    log.info("ASPR: %d works (%d left out by scope, %d groups deferred)",
             len(works), len(DROPPED), len(DEFERRED))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
