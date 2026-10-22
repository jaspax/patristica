"""
Ingestor for the Ethiopic (Ge'ez) Bible.

Source: https://github.com/LPettay/ethiopian-bible
        Ge'ez text originally from Beta Masaheft (Universität Hamburg)
Language: Ge'ez (``gez``)
License: CC BY-SA 4.0 (Beta Masaheft data)
Format: JSON chapter files at public/data/chapters/{book}/{chapter}.json

Coverage: 36 books — standard OT books, Ethiopian Orthodox deuterocanon,
and books unique to the Ethiopic tradition (1 Enoch, Jubilees, Meqabyan,
Kebra Nagast, etc.). NT books are NOT included in this source.

Some of the source's book codes don't name the book they hold, so
``_RENAMED_BOOKS`` maps them onto OSIS books (work id ``gez/{osis book}``,
refs ``{osis book}.{ch}.{v}``), which version groups and translation linking
key on:

- ``Kings`` ("Kings", ነገሥት፡) is only 2 Kings (4 Kingdoms): 25 chapters, from
  Moab's rebellion after Ahab's death (2 Kgs 1:1) to 25:30 (#62, #66, #188).
  1 Samuel – 1 Kings are not in the source (#64).
- ``ApEz`` ("Apocalypse of Ezra") is 1 Esdras (Esdras A), and its chapter 1 is
  a bare "Chapter 1" heading, so its chapter N is 1 Esdras N − 1 (#76).  The
  source has no separate Ezra apocalypse: its only 4 Ezra text is chapters
  11–13 of ``Ezra`` (4 Ezra 12–14).

Every book's ``Work.edition`` names the edition (``EDITION``), not the book's
Ge'ez title (#34).

Works after the collection period: Kebra Nagast (c.1200–1325 CE, a national epic, not scripture
or liturgy) is excluded (``_EXCLUDED_BOOKS``).  The Synaxarion (Ethiopic
recension 14th c.) is a hybrid hagiographic calendar commemorating mostly
early saints and is kept as liturgical, per the chunk-level policy for hybrid
texts in CLAUDE.md.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from tqdm import tqdm

from patristica.models import Work
from scripts.ingest._scripture_meta import BOOK_DATES, BOOK_TITLE

log = logging.getLogger(__name__)

SOURCE_ID = "gez"

_REPO_URL = "https://github.com/LPettay/ethiopian-bible.git"
# Books classified as patristic or liturgical rather than scripture.  The
# curated genres in patristica/data/genre_overrides.csv take precedence at
# normalize time (#103): Clem is scripture there, MysHE apocrypha, Lef liturgical.
_PATRISTIC_BOOKS = {"Clem"}
_LITURGICAL_BOOKS = {"Sinod", "Synax"}
#: Books left out of the corpus entirely, with the reason.
_EXCLUDED_BOOKS: dict[str, str] = {
    "KN": "Kebra Nagast — composed c.1200–1325 CE, after the collection period",
    "TestLd": "Testament of Our Lord — no Ge'ez text, only English chapter titles (#76)",
}
#: Source book code → (OSIS book, chapter offset).  Chapters that the offset
#: moves below 1 are headings and are left out.
_RENAMED_BOOKS: dict[str, tuple[str, int]] = {
    "Kings": ("2Kgs", 0),
    "ApEz": ("1Esd", -1),
}
#: Titles that differ from ``BOOK_TITLE``.
_TITLES: dict[str, str] = {"2Kgs": "2 Kings (4 Kingdoms)"}
EDITION = "Beta maṣāḥǝft Ge'ez text (Universität Hamburg), via LPettay/ethiopian-bible"


def _ensure_repo(repo_dir: Path, force: bool) -> None:
    """Shallow-clone the repo if absent; pull on force=True."""
    if not repo_dir.exists():
        log.info("Cloning ethiopian-bible repo into %s …", repo_dir)
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth=1", _REPO_URL, str(repo_dir)],
            check=True,
        )
    elif force:
        log.info("Pulling latest ethiopian-bible data …")
        subprocess.run(
            ["git", "-C", str(repo_dir), "pull", "--ff-only"],
            check=True,
        )


def _date_meta(abbrev: str) -> dict:
    """Return date fields for a book, falling back to uncertain defaults."""
    if abbrev in BOOK_DATES:
        d = BOOK_DATES[abbrev]
        return {
            "date_composed": d["date_composed"],
            "date_range": tuple(d["date_range"]),
            "date_confidence": d["date_confidence"],
        }
    return {
        "date_composed": None,
        "date_range": None,
        "date_confidence": "uncertain",
    }


def _genre(abbrev: str) -> str:
    if abbrev in _PATRISTIC_BOOKS:
        return "patristic"
    if abbrev in _LITURGICAL_BOOKS:
        return "liturgical"
    return "scripture"


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """
    Clone/update the LPettay/ethiopian-bible repo and extract Ge'ez verse text.

    Writes one JSON file per book to ``output_dir/gez/``.
    Returns list of Work metadata records.
    """
    repo_dir = output_dir / "_repos" / "ethiopian-bible"
    _ensure_repo(repo_dir, force)

    books_json = repo_dir / "public" / "data" / "books.json"
    if not books_json.exists():
        raise FileNotFoundError(f"books.json not found at {books_json}")

    books: list[dict] = json.loads(books_json.read_text(encoding="utf-8"))
    chapters_dir = repo_dir / "public" / "data" / "chapters"

    dest_dir = output_dir / "gez"
    dest_dir.mkdir(parents=True, exist_ok=True)

    works: list[Work] = []

    for book in tqdm(books, desc="gez books"):
        source_abbrev: str = book["abbrev"]
        if source_abbrev in _EXCLUDED_BOOKS:
            stale = dest_dir / f"{source_abbrev.lower()}.json"
            if stale.exists():
                log.info("Removing %s (%s)", stale, _EXCLUDED_BOOKS[source_abbrev])
                stale.unlink()
            continue
        abbrev, chapter_offset = _RENAMED_BOOKS.get(source_abbrev, (source_abbrev, 0))
        if abbrev != source_abbrev:
            stale = dest_dir / f"{source_abbrev.lower()}.json"
            if stale.exists():
                log.info("Removing %s (now %s)", stale, abbrev)
                stale.unlink()
        title: str = _TITLES.get(abbrev) or BOOK_TITLE.get(abbrev, book.get("name", abbrev))
        n_chapters: int = book.get("chapters", 0)

        dest_path = dest_dir / f"{abbrev.lower()}.json"
        if dest_path.exists() and not force:
            log.debug("Skipping %s (already written)", dest_path)
            raw = json.loads(dest_path.read_text(encoding="utf-8"))
            works.append(Work(**raw["work"]))
            continue

        book_chapters_dir = chapters_dir / source_abbrev
        if not book_chapters_dir.exists():
            log.warning("No chapter directory for %s — skipping", abbrev)
            continue

        dm = _date_meta(abbrev)
        genre = _genre(abbrev)

        work = Work(
            work_id=f"{SOURCE_ID}/{abbrev.lower()}",
            source_id=SOURCE_ID,
            title=title,
            author=None,
            language="gez",
            tradition="ethiopic",
            genre=genre,
            date_composed=dm["date_composed"],
            date_range=dm["date_range"],
            date_confidence=dm["date_confidence"],
            license="cc-by-sa-4.0",
            provenance_url="https://github.com/LPettay/ethiopian-bible",
            edition=EDITION,
        )

        verses: list[dict] = []
        for ch in range(1, n_chapters + 1):
            if ch + chapter_offset < 1:
                continue
            ch_file = book_chapters_dir / f"{ch}.json"
            if not ch_file.exists():
                log.debug("Missing chapter file %s", ch_file)
                continue
            try:
                ch_data = json.loads(ch_file.read_text(encoding="utf-8"))
            except Exception as exc:
                log.error("Failed to parse %s: %s", ch_file, exc)
                continue

            for verse in ch_data.get("verses", []):
                text: str = (verse.get("geez") or "").strip()
                if not text:
                    continue
                v_num = verse.get("num")
                ref = f"{abbrev}.{ch + chapter_offset}.{v_num}"
                verses.append({"ref": ref, "text": text})

        if not verses:
            log.warning("No verses extracted for %s", source_abbrev)
            continue

        key = "verses" if genre == "scripture" else "paragraphs"
        dest_path.write_text(
            json.dumps({"work": work.model_dump(), key: verses}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("Wrote %d verses for %s → %s", len(verses), abbrev, dest_path.name)
        works.append(work)

    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
