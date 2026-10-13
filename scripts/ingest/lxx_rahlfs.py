"""
Ingestion module for the Septuagint (Rahlfs 1935) — Greek LXX.

Source:  https://github.com/eliranwong/LXX-Rahlfs-1935
Format:  Word-per-line CSV (``01_wordlist_unicode/text_accented.csv``) plus
         verse-span index (``01_wordlist_unicode/alignment_with_OSSP/E-verse.csv``).
License: CC BY-NC-SA 4.0 (repo); underlying text requires CCAT user declaration.

NOTE: The CCAT user-declaration requirement means this source is for non-commercial
research use only.  Ensure compliance before redistribution.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import zipfile
from pathlib import Path

from tqdm import tqdm

from patristica.models import Work
from scripts.ingest._common import download_file
from scripts.ingest._scripture_meta import (
    BOOK_DATES,
    BOOK_TITLE,
    FULL_NAME_TO_ABBREV,
    book_work_id,
)

log = logging.getLogger(__name__)

SOURCE_ID = "lxx-rahlfs"
REPO_ZIP_URL = (
    "https://github.com/eliranwong/LXX-Rahlfs-1935/archive/refs/heads/master.zip"
)

# Regex for verse ref in E-verse.csv: 「Gen 1:1」
_REF_RE = re.compile(r"[「『](.+?)[」』]")

# Additional name mappings specific to the LXX canon (deuterocanon + variants)
_LXX_EXTRA: dict[str, str] = {
    "Tobit": "Tob", "Judith": "Jdt",
    "1 Maccabees": "1Macc", "2 Maccabees": "2Macc",
    "3 Maccabees": "3Macc", "4 Maccabees": "4Macc",
    "Wisdom": "Wis", "Wisdom of Solomon": "Wis",
    "Sirach": "Sir", "Ecclesiasticus": "Sir",
    "Baruch": "Bar",
    "Letter of Jeremiah": "EpJer",
    "Prayer of Azariah": "PrAzar",
    "Susanna": "Sus",
    "Bel and the Dragon": "Bel",
    "1 Esdras": "1Esd", "2 Esdras": "2Esd",
    "Prayer of Manasseh": "PrMan",
    "Psalms of Solomon": "PsSol",
    "Odes": "Odes",
}


_ALL_OSIS_ABBREVS: frozenset[str] = frozenset(
    list(FULL_NAME_TO_ABBREV.values()) + list(_LXX_EXTRA.values())
)


def _lxx_ref_to_osis(ref_str: str) -> tuple[str, str, str] | None:
    """Parse an LXX verse ref string into (book_abbr, chapter, verse).

    Input examples: ``"Gen 1:1"``, ``"Genesis 1:1"``, ``"1 Macc 3:5"``.
    Returns None if the book cannot be resolved.
    """
    ref_str = ref_str.strip()
    m = re.match(r"^(.+?)\s+(\d+):(\d+[a-z]?)$", ref_str)
    if not m:
        return None
    book_name, chapter, verse = m.group(1), m.group(2), m.group(3)

    # Direct OSIS abbreviation (e.g. "Gen", "1Macc")
    if book_name in _ALL_OSIS_ABBREVS:
        return book_name, chapter, verse

    abbrev = (
        FULL_NAME_TO_ABBREV.get(book_name)
        or _LXX_EXTRA.get(book_name)
    )
    if abbrev is None:
        return None
    return abbrev, chapter, verse


def _build_verse_map(
    word_lines: list[str],
    verse_lines: list[str],
) -> dict[str, list[str]]:
    """Reconstruct verse text from word list and verse-span index.

    The word list format is ``INDEX\\tINDEX\\tWORD`` (3 columns; indices are 1-based
    and identical in both columns — only the third column is the word).

    The verse index format is ``START_IDX\\tSTART_IDX\\tREF`` where both columns
    hold the 1-based start word index for that verse.  The verse ends immediately
    before the next verse's start index.

    Returns a dict mapping ``"{abbrev}.{chapter}.{verse}"`` → list of word strings.
    """
    # Build word list: extract the 3rd tab-separated column
    words: list[str] = []
    for line in word_lines:
        line = line.strip()
        if not line:
            continue
        parts = line.split("\t")
        # Format: idx\tidx\tword  (3 columns)
        word = parts[2].strip() if len(parts) >= 3 else parts[-1].strip()
        if word:
            words.append(word)

    # Parse verse index: collect (start_1based, ref_str) pairs
    verse_entries: list[tuple[int, str]] = []
    reader = csv.reader(io.StringIO("\n".join(verse_lines)), delimiter="\t")
    for row in reader:
        if len(row) < 3:
            continue
        try:
            start_1based = int(row[0].strip())
        except ValueError:
            continue
        ref_raw = row[2].strip()
        ref_match = _REF_RE.search(ref_raw)
        if ref_match:
            verse_entries.append((start_1based, ref_match.group(1)))

    # Build verse dict: each verse spans [start, next_start)
    verse_dict: dict[str, list[str]] = {}
    for i, (start_1based, ref_str) in enumerate(verse_entries):
        parsed = _lxx_ref_to_osis(ref_str)
        if not parsed:
            continue
        abbrev, chapter, verse = parsed
        canonical = f"{abbrev}.{chapter}.{verse}"

        start_0 = start_1based - 1  # convert to 0-based
        if i + 1 < len(verse_entries):
            end_0 = verse_entries[i + 1][0] - 1  # exclusive
        else:
            end_0 = len(words)

        verse_words = words[start_0:end_0]
        if verse_words:
            verse_dict[canonical] = verse_words

    return verse_dict


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download and parse the LXX Rahlfs 1935 Greek Septuagint."""
    source_dir = output_dir / SOURCE_ID
    source_dir.mkdir(parents=True, exist_ok=True)

    zip_dest = output_dir / "_zips" / "LXX-Rahlfs-1935-master.zip"
    zip_dest.parent.mkdir(parents=True, exist_ok=True)
    download_file(REPO_ZIP_URL, zip_dest, force=force)

    log.info("Extracting LXX word list and verse index from archive…")
    with zipfile.ZipFile(zip_dest) as zf:
        prefix = next(
            (n for n in zf.namelist() if n.endswith("/")), ""
        ).split("/")[0]

        words_entry = f"{prefix}/01_wordlist_unicode/text_accented.csv"
        verse_entry = f"{prefix}/01_wordlist_unicode/alignment_with_OSSP/E-verse.csv"

        try:
            word_bytes = zf.read(words_entry)
            verse_bytes = zf.read(verse_entry)
        except KeyError as exc:
            raise RuntimeError(
                f"Expected files not found in LXX ZIP: {exc}. "
                "Repository structure may have changed."
            ) from exc

    word_lines = word_bytes.decode("utf-8", errors="replace").splitlines()
    verse_lines = verse_bytes.decode("utf-8", errors="replace").splitlines()

    log.info("Building LXX verse map from %d words…", len(word_lines))
    verse_map = _build_verse_map(word_lines, verse_lines)

    # Group verses by book abbreviation
    books: dict[str, list[tuple[str, str]]] = {}
    for canonical_ref, verse_words in verse_map.items():
        book_abbr = canonical_ref.split(".")[0]
        text = " ".join(verse_words)
        books.setdefault(book_abbr, []).append((canonical_ref, text))

    # Sort verses within each book by chapter/verse numerically (all-string key)
    def _ref_sort_key(item: tuple[str, str]) -> tuple:
        parts = item[0].split(".")
        # Zero-pad numeric parts so lexicographic order matches numeric order
        return tuple(f"{int(p):010d}" if p.isdigit() else p for p in parts)

    for abbrev in books:
        books[abbrev].sort(key=_ref_sort_key)

    works: list[Work] = []

    for book_abbr, verse_list in tqdm(books.items(), desc="LXX-Rahlfs"):
        out_file = source_dir / f"{book_abbr}.json"

        if out_file.exists() and not force:
            with out_file.open(encoding="utf-8") as f:
                data = json.load(f)
            works.append(Work(**data["work"]))
            continue

        dates = BOOK_DATES.get(book_abbr, {})
        # LXX translation date: ca. 280–100 BCE
        lxx_dates = {
            "date_composed": -200,
            "date_range": (-280, -100),
            "date_confidence": "approximate",
        }
        # Override with specific book dates from LXX translation period
        dates = lxx_dates

        title = BOOK_TITLE.get(book_abbr, book_abbr)
        work = Work(
            work_id=book_work_id(SOURCE_ID, book_abbr),
            source_id=SOURCE_ID,
            title=title,
            author=None,
            date_composed=dates["date_composed"],
            date_range=dates["date_range"],
            date_confidence=dates["date_confidence"],
            genre="scripture",
            language="grc",
            tradition="greek",
            license="cc-by-nc-sa-4.0",
            provenance_url="https://github.com/eliranwong/LXX-Rahlfs-1935",
            edition="Septuagint (Rahlfs 1935), via eliranwong/LXX-Rahlfs-1935; requires CCAT user declaration",
        )

        record = {
            "work": work.model_dump(),
            "verses": [{"ref": ref, "text": text} for ref, text in verse_list],
        }
        out_file.write_text(
            json.dumps(record, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("LXX %s: %d verses → %s", book_abbr, len(verse_list), out_file)
        works.append(work)

    log.info("LXX-Rahlfs ingestion complete: %d books", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
