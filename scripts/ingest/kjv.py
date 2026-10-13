"""
Ingestion module for the King James Version Bible (KJV).

Source:  https://github.com/aruljohn/Bible-kjv
Format:  One JSON file per book at repo root:
         {"book": "Genesis", "chapters": [{"chapter": "1", "verses": [{"verse": "1", "text": "..."}]}]}
License: Public domain (KJV text)
"""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path

from tqdm import tqdm

from patristica.models import Work
from scripts.ingest._common import download_file
from scripts.ingest._scripture_meta import (
    BOOK_DATES,
    BOOK_TITLE,
    FULL_NAME_TO_ABBREV,
    PROTESTANT_BOOKS,
    book_work_id,
)

log = logging.getLogger(__name__)

SOURCE_ID = "kjv"
REPO_ZIP_URL = "https://github.com/aruljohn/Bible-kjv/archive/refs/heads/master.zip"

# The aruljohn repo uses "Song of Solomon" rather than "Song of Songs"
_REPO_NAME_OVERRIDES: dict[str, str] = {
    "Song": "SongofSolomon",
}


def _book_filename(abbrev: str) -> str:
    """Return the filename stem (without .json) as used in the aruljohn repo.

    The aruljohn repo uses full English book names with no spaces:
    ``Genesis.json``, ``1Samuel.json``, ``SongofSolomon.json``, etc.
    """
    if abbrev in _REPO_NAME_OVERRIDES:
        return _REPO_NAME_OVERRIDES[abbrev]
    title = BOOK_TITLE.get(abbrev, abbrev)
    return title.replace(" ", "")


def _parse_kjv_json(book_data: dict) -> list[tuple[str, str]]:
    """Parse an aruljohn Bible-kjv book JSON dict into (canonical_ref, text) pairs."""
    book_name = book_data.get("book", "")
    abbrev = FULL_NAME_TO_ABBREV.get(book_name)
    if abbrev is None:
        # Try title map fallback
        for title, ab in FULL_NAME_TO_ABBREV.items():
            if title.lower() == book_name.lower():
                abbrev = ab
                break
    if abbrev is None:
        log.warning("Unknown book name in KJV JSON: %r", book_name)
        return []

    verses: list[tuple[str, str]] = []
    for chap in book_data.get("chapters", []):
        chapter_num = chap.get("chapter", "0")
        for verse in chap.get("verses", []):
            verse_num = verse.get("verse", "0")
            text = verse.get("text", "").strip()
            if text:
                ref = f"{abbrev}.{chapter_num}.{verse_num}"
                verses.append((ref, text))
    return verses


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download and parse the King James Version (66 books)."""
    source_dir = output_dir / SOURCE_ID
    source_dir.mkdir(parents=True, exist_ok=True)

    zip_dest = output_dir / "_zips" / "Bible-kjv-master.zip"
    zip_dest.parent.mkdir(parents=True, exist_ok=True)
    download_file(REPO_ZIP_URL, zip_dest, force=force)

    works: list[Work] = []

    with zipfile.ZipFile(zip_dest) as zf:
        prefix = next(
            (n for n in zf.namelist() if n.endswith("/")), ""
        ).split("/")[0]

        for book_abbr in tqdm(PROTESTANT_BOOKS, desc="KJV"):
            out_file = source_dir / f"{book_abbr}.json"

            if out_file.exists() and not force:
                with out_file.open(encoding="utf-8") as f:
                    data = json.load(f)
                works.append(Work(**data["work"]))
                continue

            filename = _book_filename(book_abbr)
            json_entry = f"{prefix}/{filename}.json"
            try:
                raw_bytes = zf.read(json_entry)
            except KeyError:
                log.warning("Not found in archive: %s", json_entry)
                continue

            book_data = json.loads(raw_bytes.decode("utf-8"))
            verses = _parse_kjv_json(book_data)
            if not verses:
                log.warning("No verses extracted for KJV %s", book_abbr)
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
                language="eng",
                tradition=None,
                license="public_domain",
                provenance_url="https://github.com/aruljohn/Bible-kjv",
                edition="King James Version (1769 Oxford standard text)",
                translation_of=None,  # set by link_translations.py
            )

            record = {
                "work": work.model_dump(),
                "verses": [{"ref": ref, "text": text} for ref, text in verses],
            }
            out_file.write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log.info("KJV %s: %d verses → %s", book_abbr, len(verses), out_file)
            works.append(work)

    log.info("KJV ingestion complete: %d books", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
