"""
Shared helper for ingesting Bible translations from the scrollmapper/bible_databases repo.

Source:  https://github.com/scrollmapper/bible_databases
Format:  CSV with header ``Book,Chapter,Verse,Text``; one row per verse; full book names.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
from pathlib import Path

from tqdm import tqdm

from patristica.models import Work
from scripts.ingest._common import download_file
from scripts.ingest._scripture_meta import (
    BOOK_DATES,
    BOOK_TITLE,
    book_abbrev,
    book_work_id,
)

log = logging.getLogger(__name__)

_CSV_BASE = (
    "https://raw.githubusercontent.com/scrollmapper/bible_databases"
    "/master/formats/csv/{translation}.csv"
)


#: How the CSVs spell a missing verse.
_NULL = "null"
_XML_TAG_RE = re.compile(r"</?[A-Za-z][^>]*>")


def _csv_url(translation: str) -> str:
    return _CSV_BASE.format(translation=translation)


def _parse_scrollmapper_csv(
    csv_bytes: bytes,
    source_id: str,
) -> dict[str, list[tuple[str, str]]]:
    """Parse a scrollmapper CSV file into a dict keyed by OSIS book abbreviation.

    Returns ``{abbrev: [(canonical_ref, text), ...]}``.  Verses with no text are
    left out: empty cells, and cells holding the string ``null`` (CopSahBible2 has
    no Sahidic text for 1 Enoch, 1 Esdras and Jude, and every verse reads
    ``null``; #187).  A book with no text at all is therefore absent.
    """
    text = csv_bytes.decode("utf-8", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    books: dict[str, list[tuple[str, str]]] = {}
    unknown: set[str] = set()

    for row in reader:
        book_name = row.get("Book", "").strip()
        chapter = row.get("Chapter", "").strip()
        verse = row.get("Verse", "").strip()
        verse_text = row.get("Text", "").strip()

        # Some CSVs (e.g. older CopSahBible2) contain residual TEI/XML tags such as
        # </ab> at the end of every verse and <gap reason="…"/> for lacunae. Only
        # strip tags with an ASCII name: CopSahBible2 marks editorial supplements
        # with angle brackets around Coptic text (Gen 5:4 "<ⲛϣⲉ>"), which is text.
        verse_text = _XML_TAG_RE.sub("", verse_text).strip()

        abbrev = book_abbrev(book_name)
        if abbrev is None:
            if book_name not in unknown:
                unknown.add(book_name)
                log.warning(
                    "Unknown book name %r in %s CSV; skipping its rows", book_name, source_id
                )
            continue
        if not verse_text or verse_text.lower() == _NULL:
            continue

        ref = f"{abbrev}.{chapter}.{verse}"
        books.setdefault(abbrev, []).append((ref, verse_text))

    return books


def ingest_scrollmapper(
    output_dir: Path,
    translation: str,
    source_id: str,
    language: str,
    license_: str,
    edition: str,
    tradition: str | None = None,
    force: bool = False,
) -> list[Work]:
    """Download a scrollmapper CSV translation and write per-book JSON files.

    Parameters
    ----------
    translation:  scrollmapper CSV filename stem (e.g. ``"ASV"``, ``"WEB"``).
    source_id:    Patristica source identifier (e.g. ``"asv"``).
    language:     ISO 639-3 language code.
    license_:     License string from ``patristica.models.License``.
    edition:      Human-readable edition description.
    tradition:    Optional tradition string.
    """
    source_dir = output_dir / source_id
    source_dir.mkdir(parents=True, exist_ok=True)

    csv_dest = output_dir / "_csvs" / f"{translation}.csv"
    csv_dest.parent.mkdir(parents=True, exist_ok=True)
    download_file(_csv_url(translation), csv_dest, force=force)

    csv_bytes = csv_dest.read_bytes()
    books_data = _parse_scrollmapper_csv(csv_bytes, source_id)

    works: list[Work] = []

    # Books the CSV no longer gives any text for (#187).
    for stale in sorted(source_dir.glob("*.json")):
        if stale.stem not in books_data and not stale.name.startswith("_"):
            log.info("Removing %s (no text in %s)", stale, translation)
            stale.unlink()

    for book_abbr, verse_list in tqdm(books_data.items(), desc=source_id.split("/")[-1].upper()):
        out_file = source_dir / f"{book_abbr}.json"

        if out_file.exists() and not force:
            with out_file.open(encoding="utf-8") as f:
                data = json.load(f)
            works.append(Work(**data["work"]))
            continue

        if not verse_list:
            continue

        dates = BOOK_DATES.get(book_abbr, {})
        title = BOOK_TITLE.get(book_abbr, book_abbr)

        work = Work(
            work_id=book_work_id(source_id, book_abbr),
            source_id=source_id,
            title=title,
            author=None,
            date_composed=dates.get("date_composed"),
            date_range=dates.get("date_range"),
            date_confidence=dates.get("date_confidence", "uncertain"),
            genre="scripture",
            language=language,
            tradition=tradition,
            license=license_,
            provenance_url=f"https://github.com/scrollmapper/bible_databases",
            edition=edition,
        )

        record = {
            "work": work.model_dump(),
            "verses": [{"ref": ref, "text": text} for ref, text in verse_list],
        }
        out_file.write_text(
            json.dumps(record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("%s %s: %d verses → %s", translation, book_abbr, len(verse_list), out_file)
        works.append(work)

    log.info("%s ingestion complete: %d books", translation, len(works))
    return works
