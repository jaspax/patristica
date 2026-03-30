"""
Ingestion module for the Gothic Bible (Wulfila, ca. 350 CE).

Source:  https://www.wulfila.be/gothic/text/gotica.xml
Format:  TEI P5 XML (Wulfila Project edition)
License: Academic non-commercial (Wulfila Project)

The Gothic Bible is fragmentary.  Surviving material: portions of the four
Gospels (Matthew, John, Luke, Mark), Paul's epistles (Romans, 1–2 Corinthians,
Galatians, Ephesians, Philippians, Colossians, 1–2 Thessalonians, Philemon,
1–2 Timothy, Titus), and OT fragments (Nehemiah 5–7).

TEI structure:
  <div type="book" xml:id="B1" n="1">    (books numbered 1..21)
    <head xml:lang="de">Matthaeus</head>
    <div type="chapter" n="5">
      <ab type="verse" n="15">
        <app>
          <rdg wit="#CA">
            <w xml:id="T1">ak</w>
            <pc>,</pc>
            ...
          </rdg>
        </app>
      </ab>
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from lxml import etree

from patristica.models import Work
from scripts.ingest._common import download_file
from scripts.ingest._scripture_meta import BOOK_TITLE, book_work_id

log = logging.getLogger(__name__)

SOURCE_ID = "scripture/wulfila"
TEI_URL = "https://www.wulfila.be/gothic/text/gotica.xml"

_TEI_NS = "http://www.tei-c.org/ns/1.0"
_TEI = f"{{{_TEI_NS}}}"
_XML_NS = "http://www.w3.org/XML/1998/namespace"

# Map Wulfila xml:id (B1..B18) to OSIS book abbreviations
# Based on German headings observed in the XML
_BOOK_ID_TO_OSIS: dict[str, str] = {
    "B1": "Matt",    # Matthaeus
    "B2": "John",    # Johannes
    "B3": "Luke",    # Lukas
    "B4": "Mark",    # Markus
    "B5": "Rom",     # An die Römer
    "B6": "1Cor",    # An die Korinther I
    "B7": "2Cor",    # [An die Korinther II]
    "B8": "Eph",     # [An die Epheser]
    "B9": "Gal",     # [An die Galater]
    "B10": "Phil",   # An die Philipper
    "B11": "Col",    # An die Kolosser
    "B12": "1Thess", # An die Thessalonicher I
    "B13": "2Thess", # [An die Thessalonicher II]
    "B14": "1Tim",   # [An Timotheus I]
    "B15": "2Tim",   # [An Timotheus II]
    "B16": "Titus",  # [An Titus]
    "B17": "Phlm",   # An Philemon
    "B18": "Neh",    # Nehemias (OT fragment, chapters 5-7)
    # B19 Skeireins, B20 Urkunden, B21 Kalender: non-canonical, skip
}

_WULFILA_DATE = {
    "date_composed": 360,
    "date_range": (350, 383),
    "date_confidence": "approximate",
}


def _verse_text(ab: etree._Element) -> str:
    """Extract plain Gothic text from a Wulfila <ab type="verse"> element.

    The text is encoded as ``<app><rdg><w>word</w><pc>,</pc>...</rdg></app>``.
    We take the first (primary) ``<rdg>`` reading and join its ``<w>`` and
    ``<pc>`` children.
    """
    tokens: list[str] = []

    # Prefer the first <rdg> under any <app>; fall back to any <w> found
    rdg = ab.find(f".//{_TEI}rdg")
    source = rdg if rdg is not None else ab

    for child in source.iter(f"{_TEI}w", f"{_TEI}pc"):
        local = etree.QName(child.tag).localname
        word = (child.text or "").strip()
        if not word:
            continue
        if local == "pc":
            # Attach punctuation to previous token without a space
            if tokens:
                tokens[-1] = tokens[-1] + word
            else:
                tokens.append(word)
        else:
            tokens.append(word)

    return " ".join(tokens)


def _parse_wulfila_tei(xml_bytes: bytes) -> dict[str, list[tuple[str, str]]]:
    """Parse the Wulfila TEI XML into a books dict.

    Returns ``{osis_book_abbr: [(canonical_ref, text), ...]}``.
    """
    root = etree.fromstring(xml_bytes)
    body = root.find(f".//{_TEI}body")
    if body is None:
        raise ValueError("No <body> element found in Wulfila TEI")

    books: dict[str, list[tuple[str, str]]] = {}

    for book_div in body.findall(f"{_TEI}div[@type='book']"):
        xml_id = book_div.get(f"{{{_XML_NS}}}id", "")
        book_abbr = _BOOK_ID_TO_OSIS.get(xml_id)
        if book_abbr is None:
            log.debug("Wulfila: skipping book xml:id=%r (not mapped)", xml_id)
            continue

        verses: list[tuple[str, str]] = []

        for chap_div in book_div.findall(f"{_TEI}div[@type='chapter']"):
            chap_n = chap_div.get("n", "0")

            for ab in chap_div.findall(f"{_TEI}ab[@type='verse']"):
                verse_n = ab.get("n", "").strip()
                if not verse_n:
                    continue
                text = _verse_text(ab)
                if text:
                    ref = f"{book_abbr}.{chap_n}.{verse_n}"
                    verses.append((ref, text))

        if verses:
            books[book_abbr] = verses
            log.debug("Wulfila %s: %d verses", book_abbr, len(verses))

    return books


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download and parse the Wulfila Gothic Bible."""
    source_dir = output_dir / SOURCE_ID
    source_dir.mkdir(parents=True, exist_ok=True)

    tei_dest = output_dir / "_zips" / "wulfila_gotica.xml"
    tei_dest.parent.mkdir(parents=True, exist_ok=True)
    download_file(TEI_URL, tei_dest, force=force)

    log.info("Parsing Wulfila Gothic Bible TEI…")
    xml_bytes = tei_dest.read_bytes()
    books = _parse_wulfila_tei(xml_bytes)

    if not books:
        log.warning("Wulfila parser produced no output — check %s", tei_dest)

    works: list[Work] = []

    for book_abbr, verse_list in books.items():
        out_file = source_dir / f"{book_abbr}.json"

        if out_file.exists() and not force:
            with out_file.open(encoding="utf-8") as f:
                data = json.load(f)
            works.append(Work(**data["work"]))
            continue

        work = Work(
            work_id=book_work_id(SOURCE_ID, book_abbr),
            source_id=SOURCE_ID,
            title=BOOK_TITLE.get(book_abbr, book_abbr),
            author="Wulfila (Ulfilas)",
            date_composed=_WULFILA_DATE["date_composed"],
            date_range=_WULFILA_DATE["date_range"],
            date_confidence=_WULFILA_DATE["date_confidence"],
            genre="scripture",
            language="got",
            tradition=None,
            license="academic-noncommercial",
            provenance_url="https://www.wulfila.be/gothic/text/gotica.xml",
            edition="Wulfila Gothic Bible (Wulfila Project TEI edition, gotica.xml)",
        )

        record = {
            "work": work.model_dump(),
            "verses": [{"ref": ref, "text": text} for ref, text in verse_list],
        }
        out_file.write_text(
            json.dumps(record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("Wulfila %s: %d verses → %s", book_abbr, len(verse_list), out_file)
        works.append(work)

    log.info("Wulfila ingestion complete: %d books", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
