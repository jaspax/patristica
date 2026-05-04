"""
Ingestor for the Classical Armenian Bible (Zohrab text).

Source: https://arak29.org/bible/book/
        Classical Armenian Bible, 1895 Constantinople edition
        (based on the Zohrab 1805 Venice edition)
Language: Classical Armenian / Grabar (``hye``)
License: Public domain (1895 text)
Format: HTML per chapter, one page per chapter at
        https://arak29.org/bible/book/t{BookID}_{chapter}.htm

HTML structure per chapter page:
    <strong>1:1</strong> <a href="...">word</a> <a>word</a>...  ← Armenian
    <strong>1:1</strong> English translation text               ← skip
The verse number appears twice per verse; Armenian uses hyperlinked words.

Coverage: Full Bible (OT + LXX additions to Esther/Daniel, Deuterocanon
including 3 Maccabees and 1 Esdras, NT). 3 Corinthians is not present on
this site despite being in the traditional Armenian canon.

Note on LXX book numbering: The site follows LXX tradition where
1Kings=1Sam, 2Kings=2Sam, 3Kings=1Kgs, 4Kings=2Kgs.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from tqdm import tqdm

from patristica.models import Work
from scripts.ingest._scripture_meta import BOOK_DATES, BOOK_TITLE

log = logging.getLogger(__name__)

SOURCE_ID = "scripture/armenian"

_BASE_URL = "https://arak29.org/bible/book/"

# Armenian Unicode block: U+0531–U+058F (Ա–֏)
_ARM_RE = re.compile(r"[Ա-֏]")
_VERSE_RE = re.compile(r"^(\d+):(\d+)$")

# Rate limit: seconds between HTTP requests
_REQUEST_DELAY = 1.0

# ---------------------------------------------------------------------------
# Book map: (arak29_id, osis_abbrev, chapter_ids)
# chapter_ids: list of strings used in the URL (e.g. "1", "11", "13_1")
# ---------------------------------------------------------------------------
# For standard sequential chapters: list of strings "1".."N"
# For Esther (non-sequential LXX additions): explicit list


def _seq(n: int) -> list[str]:
    return [str(i) for i in range(1, n + 1)]


# fmt: off
_BOOK_MAP: list[tuple[str, str, list[str]]] = [
    # OT — LXX numbering (1Kings=1Sam, 2Kings=2Sam, 3Kings=1Kgs, 4Kings=2Kgs)
    ("Gen",    "Gen",   _seq(50)),
    ("Ex",     "Exod",  _seq(40)),
    ("Lev",    "Lev",   _seq(27)),
    ("Num",    "Num",   _seq(36)),
    ("Deut",   "Deut",  _seq(34)),
    ("Josh",   "Josh",  _seq(24)),
    ("Judg",   "Judg",  _seq(21)),
    ("Ruth",   "Ruth",  _seq(4)),
    ("1Kings", "1Sam",  _seq(31)),
    ("2Kings", "2Sam",  _seq(24)),
    ("3Kings", "1Kgs",  _seq(22)),
    ("4Kings", "2Kgs",  _seq(25)),
    ("1Chron", "1Chr",  _seq(29)),
    ("2Chron", "2Chr",  _seq(36)),
    ("Ezra",   "Ezra",  _seq(10)),
    ("Neh",    "Neh",   _seq(13)),
    # Esther with LXX additions (chapters 11-14 precede 1-4 and follow 4)
    ("Esther", "Esth",  ["11", "12", "1", "2", "3", "4", "13", "13_1", "14"]),
    ("Job",    "Job",   _seq(42)),
    ("Ps",     "Ps",    _seq(150)),
    ("Prov",   "Prov",  _seq(31)),
    ("Eccles", "Eccl",  _seq(12)),
    ("Song",   "Song",  _seq(8)),
    ("Is",     "Isa",   _seq(66)),
    ("Jer",    "Jer",   _seq(52)),
    ("Lam",    "Lam",   _seq(5)),
    ("Ezek",   "Ezek",  _seq(48)),
    # Daniel with LXX additions (ch 13=Susanna, ch 14=Bel and Dragon)
    ("Dan",    "Dan",   ["13"] + _seq(12) + ["14"]),
    ("Hos",    "Hos",   _seq(14)),
    ("Joel",   "Joel",  _seq(3)),
    ("Amos",   "Amos",  _seq(9)),
    ("Obad",   "Obad",  _seq(1)),
    ("Jon",    "Jonah", _seq(4)),
    ("Mic",    "Mic",   _seq(7)),
    ("Nahum",  "Nah",   _seq(3)),
    ("Hab",    "Hab",   _seq(3)),
    ("Zeph",   "Zeph",  _seq(3)),
    ("Hag",    "Hag",   _seq(2)),
    ("Zech",   "Zech",  _seq(14)),
    ("Mal",    "Mal",   _seq(4)),
    # Deuterocanon
    ("Tob",     "Tob",   _seq(14)),
    ("Judith",  "Jdt",   _seq(16)),
    ("Wis",     "Wis",   _seq(19)),
    ("Sir",     "Sir",   _seq(43)),
    ("Bar",     "Bar",   _seq(5)),
    ("1Mac",    "1Macc", _seq(16)),
    ("2Mac",    "2Macc", _seq(15)),
    ("3Mac",    "3Macc", _seq(7)),
    ("1Esdras", "1Esd",  _seq(9)),
    # NT
    ("Mt",     "Matt",   _seq(28)),
    ("Mk",     "Mark",   _seq(16)),
    ("Lk",     "Luke",   _seq(24)),
    ("Jn",     "John",   _seq(21)),
    ("Acts",   "Acts",   _seq(28)),
    ("Rom",    "Rom",    _seq(16)),
    ("1Cor",   "1Cor",   _seq(16)),
    ("2Cor",   "2Cor",   _seq(13)),
    ("Gal",    "Gal",    _seq(6)),
    ("Eph",    "Eph",    _seq(6)),
    ("Phil",   "Phil",   _seq(4)),
    ("Col",    "Col",    _seq(4)),
    ("1Thess", "1Thess", _seq(5)),
    ("2Thess", "2Thess", _seq(3)),
    ("1Tim",   "1Tim",   _seq(6)),
    ("2Tim",   "2Tim",   _seq(4)),
    ("Tit",    "Titus",  _seq(3)),
    ("Philem", "Phlm",   _seq(1)),
    ("Heb",    "Heb",    _seq(13)),
    ("Jas",    "Jas",    _seq(5)),
    ("1Pet",   "1Pet",   _seq(5)),
    ("2Pet",   "2Pet",   _seq(3)),
    ("1Jn",    "1John",  _seq(5)),
    ("2Jn",    "2John",  _seq(1)),
    ("3Jn",    "3John",  _seq(1)),
    ("Jude",   "Jude",   _seq(1)),
    ("Rev",    "Rev",    _seq(22)),
]
# fmt: on


def _chapter_url(arak_id: str, ch_id: str) -> str:
    return f"{_BASE_URL}t{arak_id}_{ch_id}.htm"


def _fetch_cached(url: str, cache_path: Path, force: bool, client: httpx.Client) -> str | None:
    """Return HTML from cache or live fetch. Returns None on HTTP error."""
    if cache_path.exists() and not force:
        return cache_path.read_text(encoding="utf-8", errors="replace")
    try:
        resp = client.get(url, timeout=30)
        if resp.status_code == 404:
            log.debug("404 for %s — skipping", url)
            return None
        resp.raise_for_status()
        html = resp.text
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(html, encoding="utf-8")
        time.sleep(_REQUEST_DELAY)
        return html
    except httpx.HTTPError as exc:
        log.warning("HTTP error fetching %s: %s", url, exc)
        return None


def _parse_chapter_armenian(html: str, osis_abbrev: str, ch_seq: int) -> list[dict]:
    """
    Parse Armenian verse text from one chapter HTML page.

    The page is a 2-column table. Two layouts are used:
    - Standard books (bgcolor=#FFFFCC): verse number in <b>N:M</b>, Armenian
      words each in an <a href="wNNNN.htm"> link.
    - Deuterocanonical books (bgcolor=#EEEEFF): plain text cells with the
      verse number as a "N:M " prefix and the Armenian text following it.

    Returns list of {"ref": str, "text": str} dicts.
    ch_seq is the sequential chapter number (1-based) used in the ref.
    """
    soup = BeautifulSoup(html, "lxml")
    verses: list[dict] = []

    _ARM_COLS = {"#FFFFCC", "#EEEEFF"}

    for td in soup.find_all("td"):
        if td.get("bgcolor") not in _ARM_COLS:
            continue

        # Standard format: <b>N:M</b> with linked Armenian words
        b_tag = td.find("b")
        if b_tag:
            m = _VERSE_RE.match(b_tag.get_text(strip=True))
            if not m:
                continue
            v_num = int(m.group(2))
            word_links = [
                a.get_text(strip=True)
                for a in td.find_all("a")
                if a.get("href", "").startswith("w") and a.get_text(strip=True)
            ]
            if word_links:
                text = " ".join(word_links)
            else:
                # Fallback: full text after the verse-number bold tag
                text = td.get_text(" ", strip=True)
                text = text[len(b_tag.get_text(strip=True)):].strip()
        else:
            # Deuterocanon plain-text format: "N:M verse text…"
            full_text = td.get_text(" ", strip=True)
            m = re.match(r"^(\d+):(\d+)\s+(.+)$", full_text, re.DOTALL)
            if not m:
                continue
            v_num = int(m.group(2))
            text = m.group(3).strip()

        if text and _ARM_RE.search(text):
            ref = f"{osis_abbrev}.{ch_seq}.{v_num}"
            verses.append({"ref": ref, "text": text})

    return verses


def _date_meta(abbrev: str) -> dict:
    if abbrev in BOOK_DATES:
        d = BOOK_DATES[abbrev]
        return {
            "date_composed": d["date_composed"],
            "date_range": tuple(d["date_range"]),
            "date_confidence": d["date_confidence"],
        }
    return {"date_composed": None, "date_range": None, "date_confidence": "uncertain"}


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """
    Scrape the Arak-29 Classical Armenian Bible and write one JSON file per book.

    Downloaded HTML pages are cached in ``output_dir/_cache/arak29/`` and
    reused on subsequent runs unless ``force=True``.
    """
    cache_dir = output_dir / "_cache" / "arak29"
    dest_dir = output_dir / "scripture" / "armenian"
    dest_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    works: list[Work] = []
    total_books = len(_BOOK_MAP)

    with httpx.Client(headers={"User-Agent": "patristica-bot/1.0 (+research)"}) as client:
        for arak_id, osis_abbrev, chapter_ids in tqdm(_BOOK_MAP, desc="armenian books", total=total_books):
            dest_path = dest_dir / f"{osis_abbrev.lower()}.json"
            if dest_path.exists() and not force:
                log.debug("Skipping %s (already written)", dest_path)
                raw = json.loads(dest_path.read_text(encoding="utf-8"))
                works.append(Work(**raw["work"]))
                continue

            title = BOOK_TITLE.get(osis_abbrev, osis_abbrev)
            dm = _date_meta(osis_abbrev)

            work = Work(
                work_id=f"scripture/armenian/{osis_abbrev.lower()}",
                source_id=SOURCE_ID,
                title=title,
                author=None,
                language="hye",
                tradition="armenian",
                genre="scripture",
                date_composed=dm["date_composed"],
                date_range=dm["date_range"],
                date_confidence=dm["date_confidence"],
                license="public_domain",
                provenance_url="https://arak29.org/bible/book/",
                edition="Classical Armenian Bible, 1895 Constantinople (Zohrab text)",
            )

            all_verses: list[dict] = []
            for ch_seq, ch_id in enumerate(chapter_ids, start=1):
                url = _chapter_url(arak_id, ch_id)
                cache_path = cache_dir / f"{arak_id}_{ch_id}.html"
                html = _fetch_cached(url, cache_path, force, client)
                if html is None:
                    log.warning("Could not fetch %s — skipping chapter", url)
                    continue
                ch_verses = _parse_chapter_armenian(html, osis_abbrev, ch_seq)
                if not ch_verses:
                    log.debug("No Armenian verses parsed from %s", url)
                all_verses.extend(ch_verses)

            if not all_verses:
                log.warning("No verses for %s (%s)", osis_abbrev, arak_id)
                continue

            dest_path.write_text(
                json.dumps({"work": work.model_dump(), "verses": all_verses}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log.info("Wrote %d verses for %s → %s", len(all_verses), osis_abbrev, dest_path.name)
            works.append(work)

    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
