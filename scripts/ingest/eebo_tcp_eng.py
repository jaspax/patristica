"""
Ingestor for English translations in EEBO-TCP (#354).

Source: the Text Creation Partnership's TEI P5 files on GitHub
        (https://github.com/textcreationpartnership/{TCP id}), the same texts
        as the Oxford Text Archive's EEBO-TCP Phase 1 deposit
Format: TEI P5 XML, pinned to a commit; cached in ``data/raw/_cache/eebo-tcp/``
License: CC0 1.0 (every Phase 1 text's ``<availability>``); the printed books
        are public domain

So far one book: George Wither's translation of Nemesius of Emesa, *De natura
hominis*: *The Nature of Man* (London: M. Flesher for Henry Taunton, 1636;
STC 18427; TCP A08062).  Wither translated the Greek and divided it into the
44 chapters of the editions of his day, the chapters of Migne's PG 40
(``ogpg/vol-040/nemesius``), adding sections and a summary ("argument") to
each.

Text
----
The spelling is kept as printed (``underſtanding`` → ``understanding``,
``wiſedome`` stays ``wisedome``, ``Vnderſtanding`` stays ``Vnderstanding``):
the TCP keyboarding has no regularised or expanded readings (no ``<choice>``),
only its own marks, which are resolved as follows:

- long s (``ſ``) is printed as ``s``: a letter form, not a spelling;
- words broken at a line end (``<g ref="char:EOLhyphen"/>``) are joined;
- the abbreviation stroke (``<g ref="char:cmbAbbrStroke">``, a combining
  macron, ``cō``) stays, as in ``aelfric-ch``; ``fold()`` drops it;
- ``<g ref="char:punc">`` (punctuation the keyboarders could not read, 22
  places) is dropped;
- the keyboarders' gaps are ``lacuna`` spans with the TCP's own description:
  ``•`` per illegible letter, ``〈in non-Latin alphabet〉`` for Greek they did
  not key; a page left out as a duplicate is no gap in the text and is dropped;
- italics, page breaks and decorated initials are dropped.

Search needs nothing more for the old spelling: ``fold()`` makes no English
spelling equivalent, and a reader searching Wither's words searches them as
printed; vector search reads early-modern English as English.

Units and editorial material (#236)
-----------------------------------
- ``Nem.{c}``: "CAP. c.", and in a chapter with no sections Wither's
  argument; wholly ``heading``;
- ``Nem.{c}.{s}``: "SECT. s." and its argument, wholly ``heading``;
- ``Nem.{c}.{n}`` (a chapter with no sections) or ``Nem.{c}.{s}.{n}``:
  paragraph *n*.
- Wither's dedication, his preface to the reader and the licence are not
  carried (as other English sources leave out translators' essays).
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from patristica.models import Work
from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

SOURCE_ID = "eebo-tcp-eng"

_TEI = "{http://www.tei-c.org/ns/1.0}"


@dataclass(frozen=True)
class Book:
    tcp_id: str
    commit: str
    slug: str
    work_title: str
    author: str
    edition: str
    translation_of: str | None
    date_composed: int | None
    date_range: tuple[int, int] | None
    date_confidence: str
    tradition: str
    chapters: int
    units: int  # expected unit count, a check on the parse

    @property
    def url(self) -> str:
        return (f"https://raw.githubusercontent.com/textcreationpartnership/"
                f"{self.tcp_id}/{self.commit}/{self.tcp_id}.xml")


NEMESIUS = Book(
    tcp_id="A08062",
    commit="cdd98d6a40f6ccb9d9bba0e15488b7e1ef50374b",
    slug="nemesius-nature-of-man-wither",
    work_title="The Nature of Man",
    author="Nemesius of Emesa",
    edition=("Translated by George Wither, The Nature of Man: A Learned and Usefull Tract "
             "Written in Greek by Nemesius (London: M. Flesher for Henry Taunton, 1636; "
             "STC 18427); EEBO-TCP Phase 1 transcription A08062 (CC0); long s printed as "
             "s, spelling as printed; the dedication and the translator's preface are not "
             "included"),
    translation_of="ogpg/vol-040/nemesius",
    date_composed=400,
    date_range=(390, 400),
    date_confidence="approximate",
    tradition="greek",
    chapters=44,
    units=901,
)

BOOKS: tuple[Book, ...] = (NEMESIUS,)


class _Text:
    """A unit's text under construction: whitespace collapsed, lacunae tracked."""

    def __init__(self) -> None:
        self.parts: list[tuple[str, str | None]] = []

    def add(self, text: str, kind: str | None = None) -> None:
        if text:
            self.parts.append((text, kind))

    def mark(self, combining: str) -> None:
        """A combining mark on the letter before it (so NFC can compose them)."""
        if not self.parts or self.parts[-1][1] is not None:
            raise ValueError(f"a combining mark {combining!r} with no letter before it")
        self.parts[-1] = (self.parts[-1][0] + combining, None)

    def record(self, ref: str) -> dict:
        text, spans = "", []
        for part, kind in self.parts:
            part = unicodedata.normalize("NFC", re.sub(r"\s+", " ", part))
            if kind is not None:
                part = part.strip()
                # A described gap ("〈in non-Latin alphabet〉") is a word of
                # its own; illegible letters ("b•dily") are part of one.
                if part.startswith("〈") and text and not text.endswith(" "):
                    text += " "
            elif text.endswith(" ") or not text:
                part = part.lstrip()
            elif (spans and spans[-1][1] == len(text) and part[:1].isalnum()
                  and text[spans[-1][0]] == "〈"):
                part = " " + part  # a word after a gap
            start = len(text)
            text += part
            if kind is not None:
                spans.append([start, len(text), kind])
        text = text.rstrip()
        rec: dict = {"ref": ref, "text": text}
        if spans:
            rec["editorial"] = spans
        return rec


def _render(el: etree._Element, out: _Text) -> None:
    """*el*'s content into *out* (its tail is the caller's)."""
    if el.text:
        out.add(el.text.replace("ſ", "s"))
    for child in el:
        tag = etree.QName(child).localname if isinstance(child.tag, str) else None
        if tag == "g":
            ref = child.get("ref", "")
            if ref == "char:cmbAbbrStroke":
                out.mark(child.text or "\u0304")
            elif ref == "char:punc":
                # Unreadable punctuation: dropped, but it still parts two words
                # ("hollow▪worke").
                if (child.tail or "")[:1].isalpha():
                    out.add(" ")
            elif ref not in ("char:EOLhyphen", "char:EOLunhyphen"):
                out.add((child.text or "").replace("ſ", "s"))
        elif tag == "gap":
            if child.get("reason") != "duplicate":
                desc = child.find(f"{_TEI}desc")
                text = "".join(desc.itertext()).strip() if desc is not None else "…"
                text = re.sub(r"〈\s*(.*?)\s*〉", r"〈\1〉", text)
                out.add(text, "lacuna")
        elif tag in ("pb", "milestone", "lb", None):
            pass
        elif tag == "note":
            raise ValueError(f"a note in the text: {''.join(child.itertext())[:60]!r}")
        else:
            _render(child, out)
        if child.tail:
            out.add(child.tail.replace("ſ", "s"))


def _plain(el: etree._Element) -> str:
    text = _Text()
    _render(el, text)
    return text.record("")["text"]


def _heading(div: etree._Element) -> str:
    """The div's head and argument as one heading text."""
    head = div.find(f"{_TEI}head")
    parts = [_plain(head)] if head is not None else []
    argument = div.find(f"{_TEI}argument")
    if argument is not None:
        parts.append(_plain(argument))
    return " ".join(p for p in parts if p)


def _heading_unit(ref: str, div: etree._Element) -> dict:
    text = _heading(div)
    return {"ref": ref, "text": text, "editorial": [[0, len(text), "heading"]]}


def _paragraphs(div: etree._Element, prefix: str) -> list[dict]:
    units = []
    for n, p in enumerate(div.findall(f"{_TEI}p"), 1):
        text = _Text()
        _render(p, text)
        units.append(text.record(f"{prefix}.{n}"))
    return units


def parse_nemesius(xml: bytes, chapters: int = 44) -> list[dict]:
    """Wither's translation (TEI) as raw units."""
    root = etree.fromstring(xml)
    body = root.find(f"{_TEI}text/{_TEI}body")
    if body is None:
        raise ValueError("no <body>")
    units: list[dict] = []
    divs = body.findall(f".//{_TEI}div[@type='chapter']")
    if len(divs) != chapters:
        raise ValueError(f"{len(divs)} chapters, expected {chapters}")
    for number, chapter in enumerate(divs, 1):
        if chapter.get("n") != str(number):
            raise ValueError(f"chapter {number} is numbered {chapter.get('n')!r}")
        units.append(_heading_unit(f"Nem.{number}", chapter))
        sections = chapter.findall(f"{_TEI}div[@type='section']")
        if sections and chapter.findall(f"{_TEI}p"):
            raise ValueError(f"chapter {number}: paragraphs outside its sections")
        for s, section in enumerate(sections, 1):
            if section.get("n") != str(s):
                raise ValueError(f"chapter {number}: section {s} is "
                                 f"numbered {section.get('n')!r}")
            units.append(_heading_unit(f"Nem.{number}.{s}", section))
            units.extend(_paragraphs(section, f"Nem.{number}.{s}"))
        if not sections:
            units.extend(_paragraphs(chapter, f"Nem.{number}"))
    return units


_PARSERS = {NEMESIUS.slug: parse_nemesius}


def _work(book: Book) -> Work:
    return Work(
        work_id=f"{SOURCE_ID}/{book.slug}",
        source_id=SOURCE_ID,
        author=book.author,
        title=book.work_title,
        date_composed=book.date_composed,
        date_range=book.date_range,
        date_confidence=book.date_confidence,  # type: ignore[arg-type]
        genre="patristic",
        language="eng",
        tradition=book.tradition,  # type: ignore[arg-type]
        license="public_domain",  # the 1636 book; the TCP keyboarding is CC0
        provenance_url=f"https://github.com/textcreationpartnership/{book.tcp_id}",
        edition=book.edition,
        translation_of=book.translation_of,
    )


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Fetch the pinned TEI files (cached) and write one raw JSON file per work."""
    cache_dir = output_dir / "_cache" / "eebo-tcp"
    works: list[Work] = []
    for book in BOOKS:
        out_path = output_dir / SOURCE_ID / f"{book.slug}.json"
        if out_path.exists() and not force:
            works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
            continue
        xml = download_file(book.url, cache_dir / f"{book.tcp_id}-{book.commit[:12]}.xml",
                            etag_cache=False)
        units = _PARSERS[book.slug](xml.read_bytes(), book.chapters)
        if len(units) != book.units:
            raise ValueError(f"{book.slug}: {len(units)} units, expected {book.units}")
        work = _work(book)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"work": work.model_dump(), "paragraphs": units},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
        works.append(work)
    log.info("EEBO-TCP (English): %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
