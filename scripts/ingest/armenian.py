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
from scripts.ingest._common import offline, require_network
from scripts.ingest._scripture_meta import BOOK_DATES, BOOK_TITLE

log = logging.getLogger(__name__)

SOURCE_ID = "armenian"

_BASE_URL = "https://arak29.org/bible/book/"

# Armenian Unicode block: U+0531–U+058F (Ա–֏)
_ARM_RE = re.compile(r"[Ա-֏]")
# "N:M"; continuation pages label verses "N_1:M" (e.g. Esther 13_1:8–18).
_VERSE_RE = re.compile(r"^(\d+)(?:_\d+)?:(\d+)$")

# Chapters where arak29.org restarts verse numbering mid-page.  Mapped onto
# LXX versification (matching pta-lxx / lxx-rahlfs) so translation linking works:
#   "continue"     — keep counting past the restart (LXX Ps 9 = Heb Ps 9 + 10,
#                    so the restarted 9:1–18 are LXX 9:22–39; the Armenian-only
#                    addition after Song 8:14 becomes 8:15–20)
#   ("letters", N) — restarted verses become N a, N b, … (LXX Prov 24:22a–e)
#   "next_chapter" — restarted verses belong to the following chapter (LXX
#                    Ps 151 is printed on the Ps 150 page)
# Sirach also goes backwards in places, but those labels are real verse
# numbers (the book's order is scrambled in the manuscript tradition),
# so they are kept as-is.
_RESTART_RULES: dict[tuple[str, int], str | tuple[str, int]] = {
    ("Ps", 9): "continue",
    ("Ps", 113): "continue",   # LXX 113 = Heb 114 + 115; restarted 1–18 → 9–26
    ("Ps", 150): "next_chapter",
    ("Song", 8): "continue",
    ("Prov", 24): ("letters", 22),
}

# Misprinted verse labels on arak29.org: (book, chapter, previous label, printed) → correct.
_LABEL_TYPOS: dict[tuple[str, int, int, int], int] = {
    ("Exod", 39, 36, 34): 37,  # sequence reads …35, 36, 34, 38…
}

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
    if cache_path.exists() and (not force or offline()):
        return cache_path.read_text(encoding="utf-8", errors="replace")
    require_network(f"fetching {url}")
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


def _parse_chapter_armenian(
    html: str, osis_abbrev: str, chapter: int, seen: set[str]
) -> list[dict]:
    """
    Parse Armenian verse text from one chapter HTML page.

    The page is a 2-column table. Two layouts are used:
    - Standard books (bgcolor=#FFFFCC): verse number in <b>N:M</b>, Armenian
      words each in an <a href="wNNNN.htm"> link.
    - Deuterocanonical books (bgcolor=#EEEEFF): plain text cells with the
      verse number as a "N:M " prefix and the Armenian text following it.

    Returns list of {"ref": str, "text": str} dicts.
    *chapter* is the real chapter number (from the page ID, not its position
    in the book: Daniel is fetched Susanna-first).  *seen* holds refs already
    emitted for this book, shared across pages so a continuation page (Esther
    13_1 starts at 13:8, where page 13 ends) cannot collide.
    """
    soup = BeautifulSoup(html, "lxml")
    numbered: list[tuple[int, str]] = []

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
            m = re.match(r"^(\d+)(?:_\d+)?:(\d+)\s+(.+)$", full_text, re.DOTALL)
            if not m:
                continue
            v_num = int(m.group(2))
            text = m.group(3).strip()

        if text and _ARM_RE.search(text):
            numbered.append((v_num, text))

    return _assign_refs(numbered, osis_abbrev, chapter, seen)


def _assign_refs(
    numbered: list[tuple[int, str]], osis_abbrev: str, ch_seq: int, seen: set[str]
) -> list[dict]:
    """Build refs, applying ``_RESTART_RULES`` where verse numbering restarts.

    Labels that still repeat (Sirach's scrambled partial verses, e.g. 16:13)
    get a letter suffix — ``Sir.16.13b`` — keeping refs in the 3-part
    ``Book.C.V`` form, as the LXX sources do for ``Prov.24.22a``.
    """
    rule = _RESTART_RULES.get((osis_abbrev, ch_seq))
    verses: list[dict] = []
    prev = 0
    high = 0
    offset: int | None = None  # set once numbering restarts
    for v_num, text in numbered:
        v_num = _LABEL_TYPOS.get((osis_abbrev, ch_seq, prev, v_num), v_num)
        if offset is None and v_num < prev:
            offset = high
            if rule is None:
                log.debug(
                    "%s %d: verse numbering restarts at %d with no rule; keeping labels",
                    osis_abbrev, ch_seq, v_num,
                )
        prev = v_num
        high = max(high, v_num)
        chapter = ch_seq
        verse: str = str(v_num)
        if offset is not None:
            if rule == "next_chapter":
                chapter = ch_seq + 1
            elif rule == "continue":
                verse = str(offset + v_num)
            elif isinstance(rule, tuple):
                verse = f"{rule[1]}{chr(ord('a') + v_num - 1)}"
        ref = f"{osis_abbrev}.{chapter}.{verse}"
        if ref in seen:
            suffix = "b"
            while f"{ref}{suffix}" in seen:
                suffix = chr(ord(suffix) + 1)
            ref = f"{ref}{suffix}"
        seen.add(ref)
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
    dest_dir = output_dir / "armenian"
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
                work_id=f"{SOURCE_ID}/{osis_abbrev.lower()}",
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
            seen_refs: set[str] = set()
            for ch_id in chapter_ids:
                url = _chapter_url(arak_id, ch_id)
                cache_path = cache_dir / f"{arak_id}_{ch_id}.html"
                html = _fetch_cached(url, cache_path, force, client)
                if html is None:
                    log.warning("Could not fetch %s — skipping chapter", url)
                    continue
                chapter = int(ch_id.split("_")[0])
                ch_verses = _parse_chapter_armenian(html, osis_abbrev, chapter, seen_refs)
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
