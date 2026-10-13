"""
Ingestion module for the SBL Greek New Testament (SBLGNT).

Source:  https://github.com/LogosBible/SBLGNT
Format:  Proprietary word-level XML (one file per NT book in data/sblgnt/xml/)
License: Free for non-commercial use with attribution (Logos/Faithlife)
"""

from __future__ import annotations

import json
import logging
import re
import zipfile
from pathlib import Path

from lxml import etree
from tqdm import tqdm

from patristica.models import Work
from scripts.ingest._common import download_file
from scripts.ingest._scripture_meta import (
    BOOK_DATES,
    BOOK_TITLE,
    NT_BOOKS,
    book_work_id,
)

log = logging.getLogger(__name__)

SOURCE_ID = "sblgnt"
REPO_ZIP_URL = "https://github.com/LogosBible/SBLGNT/archive/refs/heads/master.zip"

# Pattern to extract chapter:verse from verse-number id strings like "1 John 1:1"
_CV_RE = re.compile(r"(\d+):(\d+)\s*$")


def _ref_from_verse_number_id(book_abbr: str, id_str: str) -> str:
    """Convert SBLGNT verse-number id to OSIS canonical ref.

    >>> _ref_from_verse_number_id("1John", "1 John 1:1")
    '1John.1.1'
    """
    m = _CV_RE.search(id_str)
    if m:
        return f"{book_abbr}.{m.group(1)}.{m.group(2)}"
    # Fallback: strip spaces and colons
    return id_str.replace(" ", "").replace(":", ".")


def _parse_sblgnt_xml(xml_bytes: bytes, book_abbr: str) -> list[tuple[str, str]]:
    """Return list of (canonical_ref, verse_text) from an SBLGNT book XML file.

    SBLGNT XML structure::

        <book id="...">
          <title>...</title>
          <p>
            <verse-number id="Matt 1:1">1:1</verse-number>
            <w>Βίβλος</w><suffix></suffix>
            <w>γενέσεως</w><suffix> </suffix>
            ...
          </p>
        </book>

    Words are ``<w>`` elements; ``<suffix>`` holds trailing punctuation/space.
    """
    root = etree.fromstring(xml_bytes)

    verses: list[tuple[str, str]] = []
    current_ref: str | None = None
    current_tokens: list[str] = []  # each entry: word + optional suffix

    def flush() -> None:
        if current_ref and current_tokens:
            text = "".join(current_tokens).strip()
            if text:
                verses.append((current_ref, text))

    prev_tag: str | None = None

    for el in root.iter():
        tag = el.tag

        if tag == "verse-number":
            flush()
            current_tokens = []
            current_ref = _ref_from_verse_number_id(book_abbr, el.get("id", ""))

        elif tag == "w":
            word = (el.text or "").strip()
            if word:
                # Add a leading space unless this is the first token
                if current_tokens:
                    current_tokens.append(" " + word)
                else:
                    current_tokens.append(word)
            prev_tag = "w"

        elif tag == "suffix":
            suffix_text = el.text or ""
            # Append suffix directly to last token (no extra space)
            if suffix_text.strip() and current_tokens:
                current_tokens[-1] = current_tokens[-1].rstrip() + suffix_text.rstrip()
            prev_tag = "suffix"

    flush()
    return verses


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download and parse the SBL Greek New Testament (27 NT books)."""
    source_dir = output_dir / SOURCE_ID
    source_dir.mkdir(parents=True, exist_ok=True)

    zip_dest = output_dir / "_zips" / "SBLGNT-master.zip"
    zip_dest.parent.mkdir(parents=True, exist_ok=True)
    download_file(REPO_ZIP_URL, zip_dest, force=force)

    works: list[Work] = []

    with zipfile.ZipFile(zip_dest) as zf:
        prefix = next(
            (n for n in zf.namelist() if n.endswith("/")), ""
        ).split("/")[0]

        for book_abbr in tqdm(NT_BOOKS, desc="SBLGNT"):
            out_file = source_dir / f"{book_abbr}.json"

            if out_file.exists() and not force:
                with out_file.open(encoding="utf-8") as f:
                    data = json.load(f)
                works.append(Work(**data["work"]))
                continue

            xml_entry = f"{prefix}/data/sblgnt/xml/{book_abbr}.xml"
            try:
                xml_bytes = zf.read(xml_entry)
            except KeyError:
                log.warning("Not found in archive: %s", xml_entry)
                continue

            verses = _parse_sblgnt_xml(xml_bytes, book_abbr)
            if not verses:
                log.warning("No verses extracted for %s", book_abbr)
                continue

            dates = BOOK_DATES.get(book_abbr, {})
            work = Work(
                work_id=book_work_id(SOURCE_ID, book_abbr),
                source_id=SOURCE_ID,
                title=BOOK_TITLE[book_abbr],
                author=None,
                date_composed=dates.get("date_composed"),
                date_range=dates.get("date_range"),
                date_confidence=dates.get("date_confidence", "uncertain"),
                genre="scripture",
                language="grc",
                tradition="greek",
                license="academic-noncommercial",
                provenance_url="https://github.com/LogosBible/SBLGNT",
                edition="SBL Greek New Testament (Logos/Faithlife edition)",
            )

            record = {
                "work": work.model_dump(),
                "verses": [{"ref": ref, "text": text} for ref, text in verses],
            }
            out_file.write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log.info("SBLGNT %s: %d verses → %s", book_abbr, len(verses), out_file)
            works.append(work)

    log.info("SBLGNT ingestion complete: %d books", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
