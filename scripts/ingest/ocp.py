"""
Ingestor for the Online Critical Pseudepigrapha (#78).

Source: https://github.com/OnlineCriticalPseudepigrapha/Online-Critical-Pseudepigrapha
        (``static/docs/{book}.xml``), pinned to commit :data:`_COMMIT`
Format: OCP XML: ``book/version/text`` with nested ``div[@number]`` and ``unit/reading``
License: CC-BY 4.0 (the repository's licence)

Only the books in :data:`BOOKS` are taken, and only their original-language
version from a public-domain edition: the Greek *Apocalypse of Moses*
(Tischendorf 1866).  OCP's other files are raw OCR (``ApEzra.xml``,
``Sedrach.xml``: the Wikisource texts are used instead), copied from Wikisource
(``T12P.xml``), or from an edition in copyright (``HistRech.xml``, Charlesworth
1982), so they are left out.

Refs are ``{prefix}.{chapter}``; the title is the heading (``{prefix}``) and
the prologue ``{prefix}.0``.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from patristica.models import Work
from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

SOURCE_ID = "ocp"

_COMMIT = "d2f4c59df0ad454935d84efb2e2c9844a1d31e30"
_RAW = ("https://raw.githubusercontent.com/OnlineCriticalPseudepigrapha/"
        f"Online-Critical-Pseudepigrapha/{_COMMIT}/static/docs")
_XML_PARSER = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False)


@dataclass(frozen=True)
class Book:
    slug: str
    filename: str
    version: str
    prefix: str
    title: str
    edition: str
    date_composed: int
    date_range: tuple[int, int]


BOOKS: tuple[Book, ...] = (
    Book("apocalypsis-mosis", "AdamEve", "Greek", "ApMos",
         "Διήγησις καὶ πολιτεία Ἀδὰμ καὶ Εὔας (Apocalypse of Moses)",
         "C. von Tischendorf, Apocalypses apocryphae (Leipzig 1866), 1–23", 200, (100, 400)),
)


def parse(book: Book, path: Path) -> list[dict[str, str]]:
    """The units of *book*'s chosen version: one per top-level ``div``."""
    root = etree.parse(str(path), _XML_PARSER).getroot()
    version = next((v for v in root.findall("version") if v.get("title") == book.version), None)
    if version is None:
        raise ValueError(f"{path.name}: no version {book.version!r}")
    records: list[dict[str, str]] = []
    for div in version.find("text").findall("div"):
        n = (div.get("number") or "").strip()
        text = re.sub(r"\s+", " ", " ".join(r.text or "" for r in div.iter("reading"))).strip()
        if not text:
            continue
        ref = book.prefix if n == "Title" else f"{book.prefix}.0" if n == "Prologus" else \
            f"{book.prefix}.{int(n)}"
        records.append({"ref": ref, "text": text})
    return records


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download the pinned books and write one raw JSON file per work."""
    works: list[Work] = []
    for book in BOOKS:
        out_path = output_dir / SOURCE_ID / f"{book.slug}.json"
        if out_path.exists() and not force:
            works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
            continue
        cached = output_dir / "_cache" / SOURCE_ID / f"{book.filename}-{_COMMIT[:12]}.xml"
        xml = download_file(f"{_RAW}/{book.filename}.xml", cached, etag_cache=False)
        work = Work(
            work_id=f"{SOURCE_ID}/{book.slug}",
            source_id=SOURCE_ID,
            author=None,
            title=book.title,
            date_composed=book.date_composed,
            date_range=book.date_range,
            date_confidence="uncertain",
            genre="apocrypha",
            language="grc",
            tradition="greek",
            license="cc-by-4.0",
            provenance_url=f"https://github.com/OnlineCriticalPseudepigrapha/"
                           f"Online-Critical-Pseudepigrapha/blob/{_COMMIT}/static/docs/{book.filename}.xml",
            edition=f"Online Critical Pseudepigrapha, {book.filename} ({book.version}); "
                    f"{book.edition}",
            translation_of=None,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"work": work.model_dump(), "paragraphs": parse(book, xml)},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
        works.append(work)
    log.info("Online Critical Pseudepigrapha: %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
