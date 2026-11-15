"""
Ingestion module for Brenton's English Septuagint (#355).

Source:  https://ebible.org/Scriptures/eng-Brenton_usfm.zip (eBible.org's
         corrected edition of Brenton's 1870 diglot text)
Format:  USFM zip, one file per book
License: Public domain (Sir Lancelot C. L. Brenton, 1844; with the Apocrypha, 1851)

Brenton translated the Septuagint as printed in the Sixtine edition, which
follows Codex Vaticanus: Judges is the B text (``pta-lxx/judgvat``), Tobit the
short recension (``pta-lxx/tobvatal``), Daniel, Susanna and Bel Theodotion's.
Which Greek work each book translates is curated in
``patristica/data/scripture_translation_of.csv``, never here (#153). For the
Apocrypha Brenton adapted the Authorized Version, so those books keep the
English verse numbering (``BOOK_SCHEME_OVERRIDES`` in
``patristica/versification.py``).

Verses keep Brenton's own numbering, including lettered verses (3 Kingdoms
2:35a–o, Greek Esther's additions). His footnotes (alternative renderings,
literal sense) and cross-references are editorial material (#236): each is
kept at the end of its verse in brackets and marked as a ``note`` span, so a
verse's own words stay contiguous for phrase search.

eBible's ``NEH`` file repeats 2 Esdras 11–23 (Brenton's book is Ezra and
Nehemiah as one book, like the Septuagint), and the front and back matter
(introduction, prefaces, appendix, errata, tables) are not Scripture: those
files are skipped.
"""

from __future__ import annotations

import json
import logging
import re
import zipfile
from pathlib import Path

from patristica.models import Work
from scripts.ingest._common import download_file
from scripts.ingest._scripture_meta import BOOK_DATES, BOOK_TITLE, book_work_id

log = logging.getLogger(__name__)

SOURCE_ID = "brenton-eng"
ZIP_URL = "https://ebible.org/Scriptures/eng-Brenton_usfm.zip"
ZIP_NAME = "eng-Brenton_usfm.zip"

EDITION = (
    "English translation of Sir Lancelot Charles Lee Brenton, The Septuagint Version of "
    "the Old Testament (London: Samuel Bagster and Sons, 1844; with the Apocrypha, 1851), "
    "translated from the Sixtine (Vatican) text; the Apocrypha adapt the Authorized "
    "Version. eBible.org edition (eng-Brenton), correcting the 1870 diglot printing"
)

#: eBible file code → our OSIS book (the work id's book and the refs' prefix).
#: Codes not listed (front and back matter, the duplicate NEH) are skipped.
BOOKS: dict[str, str] = {
    "GEN": "Gen", "EXO": "Exod", "LEV": "Lev", "NUM": "Num", "DEU": "Deut",
    "JOS": "Josh", "JDG": "Judg", "RUT": "Ruth", "1SA": "1Sam", "2SA": "2Sam",
    "1KI": "1Kgs", "2KI": "2Kgs", "1CH": "1Chr", "2CH": "2Chr",
    "EZR": "EzraNeh",  # 2 Esdras: Ezra 1–10 + Nehemiah 11–23, as in the LXX
    "JOB": "Job", "PSA": "Ps", "PRO": "Prov", "ECC": "Eccl", "SNG": "Song",
    "ISA": "Isa", "JER": "Jer", "LAM": "Lam", "EZK": "Ezek", "DAG": "Dan",
    "HOS": "Hos", "JOL": "Joel", "AMO": "Amos", "OBA": "Obad", "JON": "Jonah",
    "MIC": "Mic", "NAM": "Nah", "HAB": "Hab", "ZEP": "Zeph", "HAG": "Hag",
    "ZEC": "Zech", "MAL": "Mal",
    "TOB": "Tob", "JDT": "Jdt", "ESG": "Esth", "WIS": "Wis", "SIR": "Sir",
    "BAR": "Bar", "LJE": "EpJer", "SUS": "Sus", "BEL": "BelDr",
    "1MA": "1Macc", "2MA": "2Macc", "3MA": "3Macc", "4MA": "4Macc",
    "1ES": "1Esd", "MAN": "PrMan",
}

#: Titles with the Septuagint's own book names, or the recension translated.
TITLES: dict[str, str] = {
    "Judg": "Judges (Codex Vaticanus)",
    "1Sam": "1 Samuel (1 Kingdoms)",
    "2Sam": "2 Samuel (2 Kingdoms)",
    "1Kgs": "1 Kings (3 Kingdoms)",
    "2Kgs": "2 Kings (4 Kingdoms)",
    "1Chr": "1 Chronicles (1 Paralipomenon)",
    "2Chr": "2 Chronicles (2 Paralipomenon)",
    "EzraNeh": "Ezra–Nehemiah (2 Esdras)",
    "Esth": "Esther (Greek)",
    "Dan": "Daniel (Theodotion)",
    "Sus": "Susanna (Theodotion)",
    "BelDr": "Bel and the Dragon (Theodotion)",
    "Tob": "Tobit (short recension)",
    "EpJer": "Epistle of Jeremiah",
    "1Esd": "1 Esdras",
    "3Macc": "3 Maccabees",
    "4Macc": "4 Maccabees",
    "PrMan": "Prayer of Manasseh",
}

_CHAPTER_RE = re.compile(r"^\\c\s+(\d+)\s*$")
_VERSE_RE = re.compile(r"^\\v\s+(\d+[a-z]?)\s*(.*)$")
_NOTE_RE = re.compile(r"\\(f|x)\s.*?\\\1\*", re.DOTALL)
_NOTE_REF_RE = re.compile(r"\\(?:fr|xo)\s+[^\\]*")
_LINE_MARKER_RE = re.compile(r"^\\(?:p|m|nb|b|d|q\d?|pi\d?|li\d?)(?:\s+|$)")
_MARKER_RE = re.compile(r"\\\+?[a-z]+\d*\*?")
_SPACE_RE = re.compile(r"\s+")


def _plain(text: str) -> str:
    """Text without character markers (``\\add``, ``\\sc``, ``\\it``, ``\\+it``…)."""
    text = _MARKER_RE.sub(" ", text)
    text = _SPACE_RE.sub(" ", text).strip()
    # A marker between a word and its punctuation left a space before it.
    return re.sub(r" ([,.;:!?’”)\]])", r"\1", text)


def _note_text(block: str) -> str:
    """A footnote's or cross-reference's text, without its verse reference."""
    inner = block[2:-3]  # drop the opening "\f"/"\x" and the closing "\f*"/"\x*"
    inner = inner.lstrip()
    if inner[:1] in "+-":
        inner = inner[1:]
    return _plain(_NOTE_REF_RE.sub(" ", inner))


def _plain_with_notes(text: str) -> tuple[str, list[str]]:
    notes: list[str] = []

    def take(m: re.Match[str]) -> str:
        note = _note_text(m.group(0))
        if note:
            notes.append(note)
        return " "

    body = _plain(_NOTE_RE.sub(take, text))
    return body, notes


def parse_brenton_usfm(usfm: str, book: str) -> list[dict]:
    """Parse one Brenton USFM book into raw units ``{"ref", "text"[, "editorial"]}``.

    Footnotes and cross-references are appended to their verse, each as
    ``[note]`` marked with a ``note`` span.
    """
    verses: list[tuple[str, list[str]]] = []
    chapter = 0
    current: list[str] | None = None
    for line in usfm.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _CHAPTER_RE.match(line)
        if m:
            chapter = int(m.group(1))
            current = None
            continue
        m = _VERSE_RE.match(line)
        if m:
            if chapter == 0:
                raise ValueError(f"{book}: verse {m.group(1)} before the first chapter")
            current = [m.group(2)]
            verses.append((f"{book}.{chapter}.{m.group(1)}", current))
            continue
        if current is None:
            continue  # book headings, titles before the first verse
        m = _LINE_MARKER_RE.match(line)
        if m:
            line = line[m.end():]
        elif line.startswith("\\"):
            raise ValueError(f"{book} {chapter}: unexpected USFM line {line[:40]!r}")
        if line:
            current.append(line)

    units: list[dict] = []
    seen: set[str] = set()
    for ref, parts in verses:
        if ref in seen:
            raise ValueError(f"{book}: verse {ref} twice")
        seen.add(ref)
        body, notes = _plain_with_notes(" ".join(parts))
        if not body:
            log.warning("%s: empty verse", ref)
            continue
        text = body
        spans: list[list[int | str]] = []
        for note in notes:
            text += " "
            start = len(text)
            text += f"[{note}]"
            spans.append([start, len(text), "note"])
        unit: dict = {"ref": ref, "text": text}
        if spans:
            unit["editorial"] = spans
        units.append(unit)
    return units


def _book_code(entry: str) -> str | None:
    m = re.match(r"\d+-([A-Z0-9]{3})", entry.rsplit("/", 1)[-1])
    return m.group(1) if m else None


def make_work(book: str) -> Work:
    dates = BOOK_DATES.get(book, {})
    return Work(
        work_id=book_work_id(SOURCE_ID, book),
        source_id=SOURCE_ID,
        title=TITLES.get(book) or BOOK_TITLE.get(book, book),
        author=None,
        date_composed=dates.get("date_composed"),
        date_range=dates.get("date_range"),
        date_confidence=dates.get("date_confidence", "uncertain"),
        genre="scripture",
        language="eng",
        tradition=None,
        license="public_domain",
        provenance_url=ZIP_URL,
        edition=EDITION,
    )


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download Brenton's Septuagint and write one JSON file per book."""
    source_dir = output_dir / SOURCE_ID
    source_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / "_zips" / ZIP_NAME
    download_file(ZIP_URL, zip_path, force=force)

    works: list[Work] = []
    with zipfile.ZipFile(zip_path) as zf:
        for entry in sorted(zf.namelist()):
            code = _book_code(entry) if entry.endswith(".usfm") else None
            book = BOOKS.get(code or "")
            if book is None:
                log.debug("skipping %s", entry)
                continue
            out_file = source_dir / f"{book}.json"
            if out_file.exists() and not force:
                works.append(Work(**json.loads(out_file.read_text(encoding="utf-8"))["work"]))
                continue
            units = parse_brenton_usfm(zf.read(entry).decode("utf-8"), book)
            if not units:
                log.error("%s: no verses in %s", book, entry)
                continue
            work = make_work(book)
            record = {"work": work.model_dump(), "verses": units}
            out_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            log.info("%s %s: %d verses", SOURCE_ID, book, len(units))
            works.append(work)
    if len(works) != len(BOOKS):
        log.error("%s: %d books written, expected %d", SOURCE_ID, len(works), len(BOOKS))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
