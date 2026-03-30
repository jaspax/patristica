"""
Ingestion module for the Open Scriptures Hebrew Bible (morphhb).

Source:  https://github.com/openscriptures/morphhb
Format:  OSIS XML per book, one file per OT book in wlc/
License: CC BY 4.0 (OSHB additions); base WLC text is Public Domain
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from pathlib import Path

from lxml import etree
from tqdm import tqdm

from patristica.models import Work
from scripts.ingest._common import download_file
from scripts.ingest._scripture_meta import (
    BOOK_DATES,
    BOOK_TITLE,
    OT_BOOKS,
    book_work_id,
)

log = logging.getLogger(__name__)

SOURCE_ID = "scripture/oshb"
REPO_ZIP_URL = "https://github.com/openscriptures/morphhb/archive/refs/heads/master.zip"

_OSIS_NS = "http://www.bibletechnologies.net/2003/OSIS/namespace"
_OSIS = f"{{{_OSIS_NS}}}"


def _parse_oshb_xml(xml_bytes: bytes) -> list[tuple[str, str]]:
    """Return list of (osisID, verse_text) from a morphhb OSIS XML book file.

    The morphhb XML stores each word as a ``<w>`` child of ``<verse>``.  This
    function reconstructs verse text by joining word tokens, handling maqqef
    connectors and discarding verse-end markers (sof-pasuq).
    """
    root = etree.fromstring(xml_bytes)
    verses: list[tuple[str, str]] = []

    for verse_el in root.iter(f"{_OSIS}verse"):
        osis_id = verse_el.get("osisID", "").strip()
        if not osis_id:
            continue

        tokens: list[str] = []
        for child in verse_el:
            local = etree.QName(child.tag).localname

            if local == "w":
                word = (child.text or "").strip()
                if word:
                    tokens.append(word)

            elif local == "seg":
                seg_type = child.get("type", "")
                seg_text = (child.text or "").strip()

                if seg_type == "x-maqqef":
                    # Maqqef (֊) connects to the previous token without a space
                    if tokens and seg_text:
                        tokens[-1] = tokens[-1] + seg_text
                elif seg_type == "x-sof-pasuq":
                    pass  # omit end-of-verse marker from stored text
                elif seg_text:
                    tokens.append(seg_text)

            # <note>, <hi>, other elements: skip

        text = " ".join(tokens)
        if text:
            verses.append((osis_id, text))

    return verses


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download and parse the Open Scriptures Hebrew Bible (39 OT books)."""
    source_dir = output_dir / SOURCE_ID
    source_dir.mkdir(parents=True, exist_ok=True)

    zip_dest = output_dir / "_zips" / "morphhb-master.zip"
    zip_dest.parent.mkdir(parents=True, exist_ok=True)
    download_file(REPO_ZIP_URL, zip_dest, force=force)

    works: list[Work] = []

    with zipfile.ZipFile(zip_dest) as zf:
        # Detect the top-level prefix (e.g. "morphhb-master/")
        prefix = next(
            (n for n in zf.namelist() if n.endswith("/")), ""
        ).split("/")[0]

        for book_abbr in tqdm(OT_BOOKS, desc="OSHB"):
            out_file = source_dir / f"{book_abbr}.json"

            if out_file.exists() and not force:
                with out_file.open(encoding="utf-8") as f:
                    data = json.load(f)
                works.append(Work(**data["work"]))
                continue

            xml_entry = f"{prefix}/wlc/{book_abbr}.xml"
            try:
                xml_bytes = zf.read(xml_entry)
            except KeyError:
                log.warning("Not found in archive: %s", xml_entry)
                continue

            verses = _parse_oshb_xml(xml_bytes)
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
                language="hbo",
                tradition=None,
                license="cc-by-4.0",
                provenance_url="https://github.com/openscriptures/morphhb",
                edition="Open Scriptures Hebrew Bible (morphhb), Westminster Leningrad Codex",
            )

            record = {
                "work": work.model_dump(),
                "verses": [{"ref": ref, "text": text} for ref, text in verses],
            }
            out_file.write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log.info("OSHB %s: %d verses → %s", book_abbr, len(verses), out_file)
            works.append(work)

    log.info("OSHB ingestion complete: %d books", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
