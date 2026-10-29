"""
Shared helper for ingesting Bible translations from eBible.org USFM zip archives.

eBible USFM files follow the naming convention ``NN-BOOKid.usfm`` and may
contain Strong's-number annotations (``\\w word|strong="H1234"\\w*``) and
footnote blocks (``\\f + \\fr N:N \\ft text \\f*``).  This module pre-processes
the raw USFM text before handing it to the standard ``parse_usfm`` utility.
"""

from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from pathlib import Path

from tqdm import tqdm

from patristica.models import Work
from scripts.ingest._common import download_file, parse_usfm
from scripts.ingest._scripture_meta import BOOK_DATES, BOOK_TITLE, book_work_id

log = logging.getLogger(__name__)

# Map eBible 3-letter USFM codes → OSIS abbreviations
USFM_TO_OSIS: dict[str, str] = {
    # OT
    "GEN": "Gen", "EXO": "Exod", "LEV": "Lev", "NUM": "Num", "DEU": "Deut",
    "JOS": "Josh", "JDG": "Judg", "RUT": "Ruth", "1SA": "1Sam", "2SA": "2Sam",
    "1KI": "1Kgs", "2KI": "2Kgs", "1CH": "1Chr", "2CH": "2Chr",
    "EZR": "Ezra", "NEH": "Neh", "EST": "Esth", "JOB": "Job",
    "PSA": "Ps", "PRO": "Prov", "ECC": "Eccl", "SNG": "Song",
    "ISA": "Isa", "JER": "Jer", "LAM": "Lam", "EZK": "Ezek",
    "DAN": "Dan", "HOS": "Hos", "JOL": "Joel", "AMO": "Amos",
    "OBA": "Obad", "JON": "Jonah", "MIC": "Mic", "NAM": "Nah",
    "HAB": "Hab", "ZEP": "Zeph", "HAG": "Hag", "ZEC": "Zech", "MAL": "Mal",
    # NT
    "MAT": "Matt", "MRK": "Mark", "LUK": "Luke", "JHN": "John",
    "ACT": "Acts", "ROM": "Rom", "1CO": "1Cor", "2CO": "2Cor",
    "GAL": "Gal", "EPH": "Eph", "PHP": "Phil", "COL": "Col",
    "1TH": "1Thess", "2TH": "2Thess", "1TI": "1Tim", "2TI": "2Tim",
    "TIT": "Titus", "PHM": "Phlm", "HEB": "Heb", "JAS": "Jas",
    "1PE": "1Pet", "2PE": "2Pet", "1JN": "1John", "2JN": "2John",
    "3JN": "3John", "JUD": "Jude", "REV": "Rev",
    # Deuterocanon
    "TOB": "Tob", "JDT": "Jdt", "1MA": "1Macc", "2MA": "2Macc",
    "WIS": "Wis", "SIR": "Sir", "BAR": "Bar",
}

# Regex to strip footnote / cross-reference blocks
_FOOTNOTE_RE = re.compile(r"\\[fxe]\s.*?\\[fxe]\*", re.DOTALL)
# Regex to strip Strong's / morphology word attributes: |key="value" or |key=value
_WORD_ATTR_RE = re.compile(r"\|[^\\|\n]*")
# Regex to strip \\w* end-markers (\\w opening is handled by general marker strip)
_W_END_RE = re.compile(r"\\w\*")
# Any other character-style end marker (``\\+w*``, ``\\wj*``, ``\\qs*``, ``\\bk*``,
# ``\\it*``, …). ``parse_usfm`` strips leftover markers together with the
# whitespace after them, which is right for an opening marker (``\\wj word``)
# but ran the words together after an end marker (``\\+w I\\+w* \\+w have``
# → "Ihave", #393), so end markers are removed here. Group 1 is the
# whitespace before a run of end markers; newlines are never matched, so the
# line structure (``\\v``, ``\\c``) is unchanged.
_END_MARKER_RE = re.compile(
    r"([^\S\n]+)(?:\\[a-z+\d]+\*[^\S\n]*)+"  # after whitespace
    r"|\\[a-z+\d]+\*"                          # directly after a word
)


def _strip_end_markers(text: str) -> str:
    """Remove end markers, keeping the word break they stood in.

    End markers after whitespace keep that whitespace and drop the whitespace
    after them (``a \\wj* b`` → ``a b``, as ``parse_usfm`` always did); one
    directly after a word keeps the whitespace that follows it
    (``I\\+w* have`` → ``I have``).
    """
    return _END_MARKER_RE.sub(lambda m: m.group(1) or "", text)


def _preprocess_usfm(raw: str) -> str:
    """Strip eBible-specific markup before passing to the generic USFM parser."""
    # Remove footnote / cross-reference / extended-note blocks
    text = _FOOTNOTE_RE.sub("", raw)
    # Strip Strong's / lemma attributes from \\w...\\w* spans
    text = _WORD_ATTR_RE.sub("", text)
    text = _W_END_RE.sub("", text)
    return _strip_end_markers(text)


def _book_code_from_entry(entry_name: str) -> str | None:
    """Extract the USFM 3-letter book code from an eBible archive entry name.

    e.g. ``"02-GENengwebp.usfm"`` → ``"GEN"``
         ``"10-1SAengwebp.usfm"`` → ``"1SA"``
    """
    basename = entry_name.split("/")[-1]
    m = re.match(r"\d+-([A-Z0-9]{2,3})", basename)
    return m.group(1) if m else None


def ingest_ebible_usfm(
    output_dir: Path,
    zip_url: str,
    zip_filename: str,
    source_id: str,
    language: str,
    license_: str,
    edition: str,
    tradition: str | None = None,
    date_composed: int | None = None,
    date_range: tuple[int, int] | None = None,
    date_confidence: str = "uncertain",
    force: bool = False,
) -> list[Work]:
    """Download an eBible USFM zip and ingest all scripture books found in it.

    Parameters
    ----------
    zip_url:         Direct download URL for the USFM zip.
    zip_filename:    Local cache filename (stored under ``output_dir/_zips/``).
    source_id:       Patristica source identifier (e.g. ``"web"``).
    language:        ISO 639-3 language code.
    license_:        License string.
    edition:         Human-readable edition description.
    date_composed/date_range/date_confidence:
                     Work-level dates (used for all books when set; otherwise
                     per-book dates from ``BOOK_DATES`` are used).
    """
    source_dir = output_dir / source_id
    source_dir.mkdir(parents=True, exist_ok=True)

    zip_dest = output_dir / "_zips" / zip_filename
    zip_dest.parent.mkdir(parents=True, exist_ok=True)
    download_file(zip_url, zip_dest, force=force)

    works: list[Work] = []
    tmp_path = output_dir / "_tmp_ebible.usfm"

    with zipfile.ZipFile(zip_dest) as zf:
        usfm_entries = [n for n in zf.namelist() if n.lower().endswith(".usfm")]

        for entry in tqdm(usfm_entries, desc=source_id.split("/")[-1]):
            code = _book_code_from_entry(entry)
            if code is None:
                log.debug("Cannot parse book code from %s", entry)
                continue

            book_abbr = USFM_TO_OSIS.get(code)
            if book_abbr is None:
                log.debug("Unknown USFM code %r (%s)", code, entry)
                continue

            out_file = source_dir / f"{book_abbr}.json"
            if out_file.exists() and not force:
                with out_file.open(encoding="utf-8") as f:
                    data = json.load(f)
                works.append(Work(**data["work"]))
                continue

            raw_text = zf.read(entry).decode("utf-8", errors="replace")
            clean_text = _preprocess_usfm(raw_text)

            tmp_path.write_text(clean_text, encoding="utf-8")
            try:
                _meta, verses_raw = parse_usfm(tmp_path)
            finally:
                tmp_path.unlink(missing_ok=True)

            if not verses_raw:
                log.warning("No verses for %s (%s)", book_abbr, entry)
                continue

            # Remap whatever book_id parse_usfm produced to the canonical OSIS abbrev
            verses = []
            for ref, text in verses_raw:
                parts = ref.split(".", 1)
                raw_code = parts[0].upper()
                osis = USFM_TO_OSIS.get(raw_code, book_abbr)
                verses.append((f"{osis}.{parts[1]}" if len(parts) > 1 else ref, text))

            if date_composed is not None:
                book_date_composed = date_composed
                book_date_range = date_range
                book_date_confidence = date_confidence
            else:
                bd = BOOK_DATES.get(book_abbr, {})
                book_date_composed = bd.get("date_composed")
                book_date_range = bd.get("date_range")
                book_date_confidence = bd.get("date_confidence", "uncertain")

            work = Work(
                work_id=book_work_id(source_id, book_abbr),
                source_id=source_id,
                title=BOOK_TITLE.get(book_abbr, book_abbr),
                author=None,
                date_composed=book_date_composed,
                date_range=book_date_range,
                date_confidence=book_date_confidence,
                genre="scripture",
                language=language,
                tradition=tradition,
                license=license_,
                provenance_url=zip_url,
                edition=edition,
            )

            record = {
                "work": work.model_dump(),
                "verses": [{"ref": ref, "text": text} for ref, text in verses],
            }
            out_file.write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log.info("%s %s: %d verses → %s", source_id, book_abbr, len(verses), out_file)
            works.append(work)

    log.info("%s ingestion complete: %d books", source_id, len(works))
    return works
