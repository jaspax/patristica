"""
Ingestor for Gloss Corpus base texts (#540, part of #225).

Source: Gloss Corpus, ed. Pádraic Moran (University of Galway),
        https://www.glossing.org/glosscorpus, GitHub padraicmoran/glosscorpus
Format: TEI P5 XML, one ``data/texts/{text}/basetext.xml`` per glossed text
License: CC BY-NC-SA 4.0 (each file's ``<availability>``)

Gloss Corpus edits medieval glossed texts together with their glosses. Its
base texts are the glossed texts themselves; :data:`TEXTS` lists the ones
ingested, so another base text is one more entry there. Only the *Félire
Óengusso* is ingested so far: the other base texts are Latin (Isidore,
Priscian) or the Vulgate as printed in *Thesaurus Palaeohibernicus*.

Félire Óengusso
---------------
The *Martyrology of Óengus*, an Old Irish metrical calendar of saints by
Óengus the Culdee, one quatrain for each day of the year. Gloss Corpus gives
the text of Oxford, Bodleian Library, Rawlinson B 505, the base manuscript of
Stokes's edition (*Félire Óengusso Céli Dé*, Henry Bradshaw Society 29,
London 1905), as the manuscript has it: no length marks added, the
manuscript's word division, abbreviations expanded. The digital edition is
by Nike Stam. The prologue and epilogue are not part of it.

The body is twelve ``<div type="section" n="jan">`` with a ``<head>`` (the
English month name) and one ``<ab n="DDMM">`` per day. Inside a quatrain:

- ``<term>`` (lemmata the glosses are keyed to), ``<persName>``, ``<expan>``,
  ``<ex>`` and ``<abbr>`` keep their text: the expansions are the edition's
  and are not marked, as the manuscript text is otherwise unreadable;
- ``<supplied>`` (letters the editor supplied) is kept between ``⟨…⟩`` and
  marked as a ``supplement`` (#236), so the letters stay in the source text
  that is translated and embedded and only the brackets are left out;
- ``<gap/>`` becomes ``[…]``, marked as a ``lacuna``;
- ``<lb/>`` (only at the end of a quatrain, once also within one) and
  ``<pb/>`` are layout and dropped; whitespace is collapsed.

One quatrain (30 December) is given twice in the file, the second copy after
an ``<lb/>``; an ``<ab>`` whose lines are all the same is kept once (logged).

Canonical references
--------------------
``Fel.{Mon}.{day}`` (``Fel.Jan.1`` … ``Fel.Dec.31``), from the ``<ab>``'s
``n``. Each month's ``<head>`` is a unit of its own at ``Fel.{Mon}``, wholly
editorial (``heading``), so the reader shows it as the month's heading. The
quatrains are ingested as ``verses``: they are the work's own units, never
split into derived verses.
"""

from __future__ import annotations

import json
import logging
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lxml import etree

from patristica.models import Work
from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

SOURCE_ID = "glosscorpus"

#: The upstream repository and the commit ingested (pinned, so a re-ingest
#: reads the same text; the cached copy carries the commit in its name).
REPO = "padraicmoran/glosscorpus"
COMMIT = "83586e508e154123f2006585957ae3cf6d247a0f"
RAW_URL = "https://raw.githubusercontent.com/{repo}/{commit}/data/texts/{text}/basetext.xml"

TEI_NS = "http://www.tei-c.org/ns/1.0"
_NS = {"tei": TEI_NS}
_XML_ID = "{http://www.w3.org/XML/1998/namespace}id"

#: Elements whose text is dropped (layout).
_LAYOUT = {"lb", "pb"}
#: Elements whose text is kept as plain text.
_INLINE = {"term", "persName", "expan", "ex", "abbr", "hi", "name", "placeName"}

SUPPLIED_OPEN = "⟨"
SUPPLIED_CLOSE = "⟩"
LACUNA = "[…]"

_MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]


class GlossCorpusError(ValueError):
    """The base text is not structured as this ingestor expects."""


@dataclass(frozen=True)
class Text:
    slug: str  # Gloss Corpus text directory and our work slug
    title: str
    author: str | None
    date_composed: int | None
    date_range: tuple[int, int] | None
    date_confidence: str
    genre: str
    language: str
    tradition: str
    edition: str


FELIRE = Text(
    slug="felire",
    title="Félire Óengusso (The Martyrology of Óengus the Culdee)",
    author="Óengus mac Óengobann",
    # Stokes and the older view: 797-808 (Áed Oirdnide king, Donnchad of
    # Tara's death not yet named); Ó Riain and Dumville: c. 828-833.
    date_composed=None,
    date_range=(797, 833),
    date_confidence="approximate",
    genre="liturgical",
    language="sga",
    tradition="latin",
    edition=("Gloss Corpus, ed. Pádraic Moran (University of Galway, 2024), digital edition by "
             "Nike Stam: the text of Oxford, Bodleian Library, Rawlinson B 505 (diplomatic, "
             "abbreviations expanded), the base manuscript of Whitley Stokes, Félire Óengusso "
             "Céli Dé: The Martyrology of Oengus the Culdee (Henry Bradshaw Society 29, "
             f"London 1905); {REPO} commit {COMMIT[:12]}"),
)

TEXTS: tuple[Text, ...] = (FELIRE,)


def _norm_space(text: str) -> str:
    return re.sub(r"\s+", " ", text)


class _Builder:
    """Collects a unit's text and its editorial spans."""

    def __init__(self) -> None:
        self.parts: list[str] = []
        self.spans: list[list[Any]] = []
        self.length = 0

    def add(self, text: str | None) -> None:
        if text:
            self.parts.append(text)
            self.length += len(text)

    def marked(self, text: str, kind: str) -> None:
        start = self.length
        self.add(text)
        self.spans.append([start, self.length, kind])


def _walk(el: etree._Element, out: _Builder, where: str) -> None:
    for child in el:
        if not isinstance(child.tag, str):  # comment or processing instruction
            out.add(child.tail)
            continue
        tag = etree.QName(child).localname
        if tag in _LAYOUT:
            out.add(" ")
        elif tag == "supplied":
            inner = _norm_space("".join(child.itertext())).strip()
            if inner:
                out.marked(SUPPLIED_OPEN + inner + SUPPLIED_CLOSE, "supplement")
        elif tag == "gap":
            out.marked(LACUNA, "lacuna")
        elif tag in _INLINE:
            out.add(child.text)
            _walk(child, out, where)
        else:
            raise GlossCorpusError(f"{where}: unexpected element <{tag}>")
        out.add(child.tail)


def unit_text(ab: etree._Element, where: str = "") -> tuple[str, list[list[Any]]]:
    """An ``<ab>``'s text with whitespace collapsed, and its editorial spans."""
    out = _Builder()
    out.add(ab.text)
    _walk(ab, out, where)
    raw = "".join(out.parts)
    # Collapse whitespace and move the span offsets with it.
    text_chars: list[str] = []
    offset_map: list[int] = []  # raw index -> new index
    prev_space = True  # also strips leading space
    for ch in raw:
        offset_map.append(len(text_chars))
        if ch.isspace():
            if not prev_space:
                text_chars.append(" ")
            prev_space = True
        else:
            text_chars.append(ch)
            prev_space = False
    offset_map.append(len(text_chars))
    text = "".join(text_chars)
    stripped = text.rstrip(" ")
    spans = [[offset_map[s], min(offset_map[e], len(stripped)), k] for s, e, k in out.spans]
    # A span's own text never starts or ends in whitespace, so its ends map exactly.
    return stripped, spans


def _dedupe_lines(ab: etree._Element, text: str, spans: list[list[Any]],
                  where: str) -> tuple[str, list[list[Any]]]:
    """Keep one copy of an ``<ab>`` that is the same line given twice or more."""
    if not ab.findall(".//tei:lb", _NS):
        return text, spans
    pieces: list[str] = []
    cur = etree.Element("ab")
    cur.text = ab.text
    for child in ab:
        if isinstance(child.tag, str) and etree.QName(child).localname == "lb":
            pieces.append(unit_text(cur)[0])
            cur = etree.Element("ab")
            cur.text = child.tail
        else:
            cur.append(deepcopy(child))
    pieces.append(unit_text(cur)[0])
    lines = [p for p in pieces if p]
    if len(lines) > 1 and len(set(lines)) == 1:
        log.warning("%s: the same line is given %d times; kept once", where, len(lines))
        line = lines[0]
        return line, [s for s in spans if s[1] <= len(line)]
    return text, spans


def parse_basetext(xml: bytes, prefix: str) -> list[dict[str, Any]]:
    """The raw units of a calendar base text: a heading per month, a quatrain per day."""
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=True)
    root = etree.fromstring(xml, parser)
    body = root.find("tei:text/tei:body", _NS)
    if body is None:
        raise GlossCorpusError("no <body>")
    units: list[dict[str, Any]] = []
    seen: set[str] = set()
    divs = body.findall("tei:div", _NS)
    if [d.get("n") for d in divs] != _MONTHS:
        raise GlossCorpusError(f"expected twelve month <div>s, got {[d.get('n') for d in divs]}")
    for month_no, div in enumerate(divs, start=1):
        month = (div.get("n") or "").capitalize()
        head = div.find("tei:head", _NS)
        if head is None:
            raise GlossCorpusError(f"{month}: no <head>")
        heading = _norm_space("".join(head.itertext())).strip()
        month_ref = f"{prefix}.{month}"
        units.append({"ref": month_ref, "text": heading,
                      "editorial": [[0, len(heading), "heading"]]})
        expected_day = 1
        for child in div:
            if not isinstance(child.tag, str):
                continue
            tag = etree.QName(child).localname
            if tag == "head":
                continue
            if tag != "ab":
                raise GlossCorpusError(f"{month}: unexpected element <{tag}>")
            n = child.get("n") or ""
            if not re.fullmatch(r"\d{4}", n) or int(n[2:]) != month_no:
                raise GlossCorpusError(f"{month}: <ab n={n!r}> is not a day of this month")
            day = int(n[:2])
            if day != expected_day:
                raise GlossCorpusError(f"{month}: day {day} follows day {expected_day - 1}")
            expected_day += 1
            ref = f"{month_ref}.{day}"
            text, spans = unit_text(child, ref)
            text, spans = _dedupe_lines(child, text, spans, ref)
            if not text:
                raise GlossCorpusError(f"{ref}: empty quatrain")
            if ref in seen:
                raise GlossCorpusError(f"duplicate ref {ref}")
            seen.add(ref)
            unit: dict[str, Any] = {"ref": ref, "text": text}
            if spans:
                unit["editorial"] = spans
            units.append(unit)
    return units


def _work(text: Text) -> Work:
    return Work(
        work_id=f"{SOURCE_ID}/{text.slug}",
        source_id=SOURCE_ID,
        author=text.author,
        title=text.title,
        date_composed=text.date_composed,
        date_range=text.date_range,
        date_confidence=text.date_confidence,  # type: ignore[arg-type]
        genre=text.genre,  # type: ignore[arg-type]
        language=text.language,  # type: ignore[arg-type]
        tradition=text.tradition,  # type: ignore[arg-type]
        license="cc-by-nc-sa-4.0",
        provenance_url=f"https://github.com/{REPO}/blob/{COMMIT}/data/texts/{text.slug}/basetext.xml",
        edition=text.edition,
        translation_of=None,
    )


_PREFIXES = {"felire": "Fel"}


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download the pinned base texts and write one raw JSON file per work."""
    works: list[Work] = []
    for text in TEXTS:
        out_path = output_dir / SOURCE_ID / f"{text.slug}.json"
        if out_path.exists() and not force:
            works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
            continue
        xml_path = download_file(
            RAW_URL.format(repo=REPO, commit=COMMIT, text=text.slug),
            output_dir / "_cache" / SOURCE_ID / f"{text.slug}-{COMMIT[:12]}.xml",
            etag_cache=False,
            force=False,  # pinned commit: the cached copy never changes
        )
        units = parse_basetext(xml_path.read_bytes(), _PREFIXES[text.slug])
        work = _work(text)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"work": work.model_dump(), "verses": units},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("%s: %d units", work.work_id, len(units))
        works.append(work)
    log.info("Gloss Corpus: %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
