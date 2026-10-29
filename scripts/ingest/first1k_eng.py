"""
Ingestor for First1KGreek's English translations (#343).

Source: https://github.com/OpenGreekAndLatin/First1KGreek
Format: TEI P5 XML (EpiDoc), ``*.1st1K-eng1.xml`` beside each Greek edition
License: the translations are public domain; First1KGreek's TEI markup is
CC BY-SA 4.0, so the works carry ``cc-by-sa-4.0`` like the Greek editions.

Why a source of its own
-----------------------
``scripts.ingest.first1k`` keeps only the Greek editions. Its English files are
read here instead, from the same clone (``data/raw/first1k/data/``), and
written to ``data/raw/first1k-eng/``: the Greek works' ids, raw files and
ingest stamp stay exactly as they were. This ingestor never clones or pulls;
run ``scripts.ingest.first1k`` first (``all.py`` runs them in that order).

Scope
-----
Only the textgroups in :data:`TEXTGROUPS`: C. D. Yonge's Philo (1854–55),
whose Greek originals are all in the corpus and had no English. The other
English files of the repo are left out on purpose:

- out of the project's scope (``_cts_scope``): Agathemerus, Ps.-Plutarch,
  Sextus Empiricus, the paradoxographers, the *Excerpta Vaticana*, and
  Ottley's Isaiah (Hebrew and LXX textgroups covered by Scripture sources);
- English already in the corpus (ANF Vol. 8): M. R. James's *Acts of John*,
  *Acts of Thomas* and *Acts of Philip* (1924);
- Eusebius' *Historia ecclesiastica* in the Loeb of Lake and Oulton
  (1926–32): NPNF II/1 already has it, and Oulton's volume (1932) is not
  clearly public domain.

Each work is ``translation_of`` its Greek edition from ``scripts.ingest.first1k``
(``first1k/{tlg}/{tlg}/{version}``), and its refs are the Greek work's:
``{textgroup}.{work}.{book}.{section}``.

Units and editorial material (#236)
-----------------------------------
One unit per section (the lowest ``div``), its paragraphs joined, so it pairs
with the Greek section of the same ref. Translator's and digital editors'
material is marked, not deleted:

- the work's title and a book's title (``<head>`` before the first section)
  become a heading record at the work's or book's ref, wholly ``title``;
- a ``<head>`` inside a section (Yonge's sub-treatise headings in *De
  specialibus legibus*) starts that section's unit as a ``heading`` span;
- a ``<note>`` (Yonge's footnotes, the editors' remarks) stays in place in
  brackets as a ``note`` span; the TEI repeats many notes (a page's notes
  again after the page, or a flattened copy) with the same ``@n``, and only
  the first of each ``@n`` is kept;
- an empty ``<unclear/>`` (a word lost in the transcription) is a ``[…]``
  ``lacuna`` span.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree
from tqdm import tqdm

from patristica.models import Work
from scripts.ingest._common import slugify_ref

log = logging.getLogger(__name__)

SOURCE_ID = "first1k-eng"

#: The Greek source whose clone holds the files and whose works they translate.
GREEK_SOURCE_ID = "first1k"

#: Textgroups whose English translations are ingested (see the module docstring).
TEXTGROUPS: frozenset[str] = frozenset({"tlg0018"})

#: Series of a translation, where the TEI header doesn't say.
_SERIES: dict[str, str] = {"tlg0018": "Bohn's Ecclesiastical Library"}

_TEI = "http://www.tei-c.org/ns/1.0"
_NS = {"tei": _TEI}

_FILE_RE = re.compile(r"^(?P<group>[a-z]+\d+[a-z]?)\.(?P<work>[a-z]+\d+[a-z]?)\.(?P<version>[\w-]+-eng\d+)$")
_N_RE = re.compile(r"^[\w\-]+$")

#: Milestones and layout: dropped, their tail kept.
_LAYOUT = frozenset({"pb", "lb", "cb", "milestone", "fw", "figure"})


def _local(el: etree._Element) -> str:
    return etree.QName(el.tag).localname if isinstance(el.tag, str) else ""


class _Text:
    """A unit's text under construction: whitespace collapsed, editorial spans tracked."""

    def __init__(self) -> None:
        self.chars: list[str] = []
        self.spans: list[list] = []
        self._space = False

    def space(self) -> None:
        self._space = True

    def add(self, text: str | None, kind: str | None = None) -> None:
        if not text:
            return
        start: int | None = None
        for ch in text:
            if ch.isspace():
                self._space = True
                continue
            if self._space and self.chars:
                self.chars.append(" ")
            self._space = False
            if start is None:
                start = len(self.chars)
            self.chars.append(ch)
        if kind is not None and start is not None:
            self.spans.append([start, len(self.chars), kind])

    @property
    def text(self) -> str:
        return "".join(self.chars)


def _is_structural(div: etree._Element) -> bool:
    return _local(div) == "div" and div.get("type") == "textpart"


def _title_only(el: etree._Element) -> bool:
    """A ``<p>``/``<ab>`` that holds nothing but a ``<title>`` (``PART I.``): a heading."""
    if (el.text or "").strip():
        return False
    kids = [c for c in el if isinstance(c.tag, str)]
    return bool(kids) and all(_local(c) == "title" and not (c.tail or "").strip() for c in kids)


def _plain(el: etree._Element) -> str:
    """The text of a heading or note, whitespace collapsed (nested notes dropped)."""
    out = _Text()
    _emit_children(el, out, notes=None)
    return out.text


@dataclass
class _NoteState:
    """The ``@n`` of the notes kept so far in a work, to leave out the TEI's repeats."""

    seen: set[str] = field(default_factory=set)
    skipped: int = 0


def _emit_children(el: etree._Element, out: _Text, notes: _NoteState | None) -> None:
    out.add(el.text)
    prev: str | None = None
    for child in el:
        tag = _local(child)
        if not tag:  # comment, processing instruction
            pass
        elif tag in _LAYOUT:
            pass
        elif tag == "note":
            if notes is not None:
                n = child.get("n")
                if n and n in notes.seen:
                    notes.skipped += 1  # the TEI repeats a page's notes after the page
                else:
                    if n:
                        notes.seen.add(n)
                    text = _plain(child)
                    if text:
                        out.space()
                        out.add(f"[{text}]", "note")
                        out.space()
        elif tag == "head" or (tag in ("p", "ab") and _title_only(child)):
            text = _plain(child)
            if notes is not None and text:
                out.space()
                out.add(text, "heading")
            out.space()
        elif tag == "unclear" and not "".join(child.itertext()).strip():
            out.space()
            out.add("[…]", "lacuna")
            out.space()
        elif tag in ("p", "ab", "lg", "quote", "cit"):
            out.space()
            _emit_children(child, out, notes)
            out.space()
        elif tag == "l":
            if prev == "l":
                out.add(" /")
            out.space()
            _emit_children(child, out, notes)
        else:
            _emit_children(child, out, notes)
        if tag:
            prev = tag
        out.add(child.tail)


@dataclass
class _Extraction:
    units: list[dict] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    skipped_notes: int = 0


def _extract_units(translation: etree._Element, work_cts_id: str) -> _Extraction:
    """The units of a translation div: heading records and one unit per section."""
    result = _Extraction()
    notes = _NoteState()

    def ref_of(parts: list[str]) -> str:
        return slugify_ref(".".join([work_cts_id, *parts]))

    def walk(container: etree._Element, parts: list[str]) -> None:
        heads: list[str] = []

        def flush() -> None:
            if heads:
                text = " ".join(heads)
                result.units.append({"ref": ref_of(parts), "text": text,
                                     "editorial": [[0, len(text), "title"]]})
                heads.clear()

        for child in container:
            tag = _local(child)
            if not tag or tag in _LAYOUT:
                continue
            if _is_structural(child):
                n = child.get("n", "")
                sub = [*parts, n] if n and _N_RE.match(n) else parts
                flush()
                if any(_is_structural(d) for d in child.iter(f"{{{_TEI}}}div") if d is not child):
                    walk(child, sub)
                else:
                    section(child, sub)
            elif tag == "head" or (tag in ("p", "ab") and _title_only(child)):
                text = _plain(child)
                if text:
                    heads.append(text)
            elif "".join(child.itertext()).strip():
                result.problems.append(f"text outside a section at {ref_of(parts)}: <{tag}>")
        if heads:
            result.problems.append(f"heading after the last section of {ref_of(parts)}: {heads!r}")

    def section(div: etree._Element, parts: list[str]) -> None:
        out = _Text()
        _emit_children(div, out, notes)
        if not out.text:
            return
        unit: dict = {"ref": ref_of(parts), "text": out.text}
        if out.spans:
            unit["editorial"] = out.spans
        result.units.append(unit)

    walk(translation, [])
    result.skipped_notes = notes.skipped
    seen: set[str] = set()
    for unit in result.units:
        if unit["ref"] in seen:
            result.problems.append(f"duplicate ref {unit['ref']}")
        seen.add(unit["ref"])
    return result


def _header_text(root: etree._Element, path: str) -> str | None:
    el = root.find(path, _NS)
    if el is None:
        return None
    text = " ".join("".join(el.itertext()).split())
    return text or None


def _edition(root: etree._Element, group: str) -> str:
    """Translator, book, volume, imprint and series, from the TEI's source description."""
    mono = ".//tei:sourceDesc//tei:monogr"
    translator = _header_text(root, f"{mono}/tei:editor[@role='translator']") \
        or _header_text(root, ".//tei:titleStmt/tei:editor[@role='translator']")
    book = _header_text(root, f"{mono}/tei:title")
    volume = _header_text(root, f"{mono}/tei:biblScope[@unit='volume']")
    place = _header_text(root, f"{mono}/tei:imprint/tei:pubPlace")
    publisher = _header_text(root, f"{mono}/tei:imprint/tei:publisher")
    date = _header_text(root, f"{mono}/tei:imprint/tei:date")
    imprint = ", ".join(p for p in (": ".join(p for p in (place, publisher) if p), date) if p)
    citation = ", ".join(p for p in (
        f"tr. {translator}" if translator else None,
        book,
        f"vol. {volume}" if volume else None,
    ) if p)
    if imprint:
        citation = f"{citation} ({imprint})" if citation else imprint
    return "; ".join(p for p in (citation, _SERIES.get(group),
                                 "TEI by First1KGreek (University of Leipzig)") if p)


def _greek_original(raw_root: Path, group: str, work: str) -> str | None:
    """The work id of the Greek edition ``scripts.ingest.first1k`` wrote for this work."""
    found = sorted((raw_root / GREEK_SOURCE_ID / group / work).glob(f"{group}.{work}.*-grc*.json"))
    if len(found) != 1:
        return None
    version = found[0].stem.split(".", 2)[2]
    return f"{GREEK_SOURCE_ID}/{group}/{work}/{version}"


def parse_file(xml_path: Path, raw_root: Path, author: str | None) -> tuple[Work, list[dict]] | None:
    """Parse one English TEI file into ``(Work, units)``; None (logged) if it can't be."""
    m = _FILE_RE.match(xml_path.stem)
    if m is None:
        log.error("%s: unexpected file name", xml_path)
        return None
    group, work_short, version = m["group"], m["work"], m["version"]
    root = etree.parse(str(xml_path)).getroot()
    translation = root.find(".//tei:text/tei:body/tei:div[@type='translation']", _NS)
    if translation is None:
        log.error("%s: no translation div", xml_path)
        return None

    original = _greek_original(raw_root, group, work_short)
    if original is None:
        log.error("%s: no single Greek edition of %s.%s in %s; run scripts.ingest.first1k first",
                  xml_path.name, group, work_short, raw_root / GREEK_SOURCE_ID)
        return None

    extraction = _extract_units(translation, f"{group}.{work_short}")
    for problem in extraction.problems:
        log.error("%s: %s", xml_path.name, problem)
    if extraction.problems or not extraction.units:
        return None
    if extraction.skipped_notes:
        log.info("%s: %d repeated notes left out", xml_path.name, extraction.skipped_notes)

    title = _header_text(root, ".//tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title") or xml_path.stem
    work = Work(
        work_id=f"{SOURCE_ID}/{group}/{work_short}/{version}",
        source_id=SOURCE_ID,
        author=author or _header_text(root, ".//tei:titleStmt/tei:author"),
        title=title,
        date_composed=None,
        date_range=None,
        date_confidence="uncertain",
        genre="patristic",
        language="eng",
        tradition="greek",
        license="cc-by-sa-4.0",
        provenance_url=("https://github.com/OpenGreekAndLatin/First1KGreek/blob/master/data/"
                        f"{group}/{work_short}/{xml_path.name}"),
        edition=_edition(root, group),
        translation_of=original,
    )
    return work, extraction.units


def _author_name(cts_path: Path) -> str | None:
    """The English group name of a textgroup's ``__cts__.xml``."""
    if not cts_path.exists():
        return None
    root = etree.parse(str(cts_path)).getroot()
    for el in root.iter("{http://chs.harvard.edu/xmlns/cts}groupname"):
        if el.get("{http://www.w3.org/XML/1998/namespace}lang") == "eng" and (el.text or "").strip():
            return el.text.strip()
    return None


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Ingest the English translations of :data:`TEXTGROUPS` from the First1KGreek clone.

    Parameters
    ----------
    output_dir: Root raw output directory (``data/raw``); the clone is
                ``output_dir/first1k`` and the output ``output_dir/first1k-eng``.
    force:      Re-parse files whose output exists. The clone is never pulled.
    """
    data_dir = output_dir / GREEK_SOURCE_ID / "data"
    if not data_dir.is_dir():
        raise FileNotFoundError(f"No First1KGreek clone at {data_dir}: run scripts.ingest.first1k first")
    out_root = output_dir / SOURCE_ID

    xml_files = sorted(p for group in sorted(TEXTGROUPS)
                       for p in (data_dir / group).glob("*/*.xml") if _FILE_RE.match(p.stem))
    log.info("Found %d English First1KGreek files to process", len(xml_files))

    expected = {out_root / p.relative_to(data_dir).with_suffix(".json") for p in xml_files}
    for stale in sorted(set(out_root.glob("*/*/*.json")) - expected):
        log.info("Removing %s: no longer in scope", stale)
        stale.unlink()

    works: list[Work] = []
    for xml_path in tqdm(xml_files, desc="First1KGreek English"):
        out_path = out_root / xml_path.relative_to(data_dir).with_suffix(".json")
        if out_path.exists() and not force:
            works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
            continue
        result = parse_file(xml_path, output_dir, _author_name(xml_path.parents[1] / "__cts__.xml"))
        if result is None:
            continue
        work, units = result
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"work": work.model_dump(), "paragraphs": units},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
        works.append(work)

    log.info("First1KGreek English: %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
