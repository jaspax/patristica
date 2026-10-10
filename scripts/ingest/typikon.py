"""
Ingestor for the Greek Typikon (Violakis edition, 1900).

Source: Internet Archive
        https://archive.org/details/typikontstou00orth
OCR plain text (typikontstou00orth_djvu.txt), ~1.6 MB.
Language: grc  Tradition: greek  Genre: liturgical  License: public_domain

The Violakis Typikon (1900) is the authoritative edition of the Ecumenical
Patriarchate, compiled by Georgios Violakis (Protopsaltis). It organizes
the full Byzantine liturgical year by feast day, giving rubrics and hymn
incipits for Vespers, Matins, and Liturgy at each commemoration. Hymnographic
material ranges from patristic-era (4th–10th c.) through later Byzantine practice.

All chunks default to out_of_period=False. A deferred second pass would set
out_of_period=True for feasts commemorating saints who lived after the
collection period (``patristica.period``), using a lookup table of such feasts.

Canonical ref format
--------------------
  ByzTyp.General.{n:04d}        — protheoria / general rubrics (before September)
  ByzTyp.{month_abbrev}.{n:04d} — fixed cycle Menaion (Sep … Aug)
  ByzTyp.Mov.{n:04d}            — moveable cycle (Triodion + Pentecostarion)
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from pathlib import Path

from patristica.models import Work
from patristica.period import COMPOSED_BY
from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

SOURCE_ID = "liturgical/typikon"
_WORK_SLUG = "violakis-1900"
_URL = "https://archive.org/download/typikontstou00orth/typikontstou00orth_djvu.txt"

# Months in ecclesiastical year order (September = new year).
# Each entry maps an OCR-observed spelling to the 3-letter abbreviation.
# Multiple spellings per month handle OCR character substitutions (Τ↔Υ, 0↔Ο, etc.).
_MONTH_ABBREVS: dict[str, str] = {
    "ΣΕΠΤΕΜΒΡΙΟΣ": "Sep",
    "ΟΚΤΩΒΡΙΟΣ": "Oct",
    "ΝΟΕΜΒΡΙΟΣ": "Nov",
    "ΔΕΚΕΜΒΡΙΟΣ": "Dec",
    "ΙΑΝΟΥΑΡΙΟΣ": "Jan",
    "ΦΕΒΡΟΥΑΡΙΟΣ": "Feb",
    "ΜΑΡΤΙΟΣ": "Mar",
    "ΑΠΡΙΛΙΟΣ": "Apr",
    "ΜΑΙΟΣ": "May",
    "ΙΟΥΝΙΟΣ": "Jun",
    "ΙΟΤΝΙΟΣ": "Jun",   # OCR variant: Τ substituted for Υ
    "ΙΟΥΛΙΟΣ": "Jul",
    "ΑΥΓΟΥΣΤΟΣ": "Aug",
}

_MONTH_RE = re.compile(r"\b(" + "|".join(_MONTH_ABBREVS.keys()) + r")\b")

# Menaion intro heading — marks transition from Protheoria to monthly Menaion
_MENAION_INTRO_RE = re.compile(r"ΚΑΤΑ\s+ΜΗΝΑ|ΤΥΠΙΚΗ\s+ΔΙΑΤΑΞΙΣ")

# Triodion section header — marks start of moveable cycle
_TRIODION_RE = re.compile(r"\bΤΡΙΩΔ")

# Page header pattern: short line that is just digit(s) + 1–3 Greek words,
# or 1–3 Greek words + digit(s).  E.g. "64  ΜΗΝ", "ΣΕΠΤΕΜΒΡΙΟΣ  87".
_PAGE_HEADER_RE = re.compile(
    r"^\s*(?:\d+(?:\s+\S+){1,3}|\S+(?:\s+\S+){0,2}\s+\d+)\s*$"
)


def _is_page_header(line: str) -> bool:
    """Return True if this line looks like an OCR page-running-header to strip."""
    s = line.strip()
    if len(s) > 45:
        return False
    if not re.search(r"\d", s):
        return False
    # Numbered paragraphs ("1.  Εἴς τόν Ὄρθρον…") must not be stripped
    if re.match(r"^\d+\.\s+\S{4,}", s):
        return False
    return bool(_PAGE_HEADER_RE.match(s))


def _clean_ocr(raw: str) -> str:
    """Strip IA front/back matter, page headers, and rejoin hyphenated line breaks."""
    lines = raw.splitlines()

    # ---- Strip Internet Archive front matter ----
    # The file starts with English/Latin OCR of library stamps (~30 lines).
    # Find first line with significant Greek characters as the real start.
    start = 0
    for i, line in enumerate(lines[:100]):
        if re.search(r"[ΤΥΠΚΝ]{3,}", line):
            start = i
            break

    # ---- Strip Internet Archive back matter ----
    # Last ~40 lines contain an English-language library catalog entry.
    # Find last line with significant Greek characters.
    end = len(lines)
    for i in range(len(lines) - 1, max(len(lines) - 80, start), -1):
        if re.search(r"[Α-ΩΪΫα-ωϊϋ]{4,}", lines[i]):
            end = i + 1
            break

    lines = lines[start:end]

    result: list[str] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()

        if not stripped:
            result.append("")
            i += 1
            continue

        if _is_page_header(stripped):
            i += 1
            continue

        # Rejoin hyphenated word split across lines.
        # Condition: current line ends with '-' and the next non-empty line
        # starts with a character that is not uppercase (continuation word).
        if stripped.endswith("-") and i + 1 < len(lines):
            next_stripped = lines[i + 1].strip()
            if next_stripped and not next_stripped[0].isupper():
                result.append(stripped[:-1] + next_stripped)
                i += 2
                continue

        result.append(stripped)
        i += 1

    return "\n".join(result)


def _extract_paragraphs(text: str) -> list[dict[str, str]]:
    """Parse cleaned OCR into paragraph dicts {ref, text}.

    Sections are detected by month-name headers and Triodion heading.
    Blank lines (after OCR cleaning) are used as paragraph boundaries.
    """
    # Split on two-or-more newlines to get paragraph blocks
    raw_blocks = re.split(r"\n{2,}", text)

    paragraphs: list[dict[str, str]] = []
    current_section = "General"
    section_counter: dict[str, int] = {}
    menaion_active = False    # True once we have entered the monthly Menaion
    mov_active = False        # True once we have entered the moveable cycle
    months_seen: set[str] = set()

    def next_ref(section: str) -> str:
        section_counter[section] = section_counter.get(section, 0) + 1
        return f"ByzTyp.{section}.{section_counter[section]:04d}"

    for raw_block in raw_blocks:
        # Collapse multiple spaces / newlines within a single block
        block = re.sub(r"[ \t]+", " ", raw_block.replace("\n", " ")).strip()

        if not block or len(block) < 4:
            continue

        # ---- Section-transition detection ----

        # Menaion intro heading — skip as structural non-content
        if _MENAION_INTRO_RE.search(block) and len(block) < 120:
            menaion_active = True
            continue

        # Month header: short block that names a Menaion month
        m = _MONTH_RE.search(block)
        if m and len(block) < 60:
            month = _MONTH_ABBREVS[m.group(1)]
            months_seen.add(month)
            current_section = month
            menaion_active = True
            mov_active = False
            log.debug("Section → %s", month)
            continue  # month headings are not output as paragraphs

        # Moveable cycle: Triodion header appears after the Menaion months
        if (
            menaion_active
            and not mov_active
            and _TRIODION_RE.search(block)
            and len(block) < 80
        ):
            current_section = "Mov"
            mov_active = True
            log.debug("Section → Mov (Triodion)")
            continue

        # Fallback: after all 12 Menaion months, an all-caps heading that is
        # not itself a month name switches us into the moveable cycle.
        if (
            menaion_active
            and not mov_active
            and "Aug" in months_seen
            and len(block) < 80
            and not _MONTH_RE.search(block)
            and re.match(r"^[Α-ΩΪΫ\s]+$", block)
        ):
            current_section = "Mov"
            mov_active = True
            log.debug("Section → Mov (heading: %r)", block[:40])
            continue

        # ---- Emit paragraph ----
        ref = next_ref(current_section)
        paragraphs.append({"ref": ref, "text": block})

    return paragraphs


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    out_dir = output_dir / SOURCE_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_WORK_SLUG}.json"

    if out_path.exists() and not force:
        return [Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"])]

    txt_path = output_dir / "_zips" / "typikon-violakis-1900.txt"
    download_file(_URL, txt_path, force=force)

    raw = txt_path.read_text(encoding="utf-8", errors="replace")
    log.info("Typikon OCR: %d bytes, %d lines", len(raw.encode()), raw.count("\n"))

    cleaned = _clean_ocr(raw)
    paragraphs = _extract_paragraphs(cleaned)

    section_counts = Counter(p["ref"].split(".")[1] for p in paragraphs)
    _ORDERED_SECTIONS = [
        "General", "Sep", "Oct", "Nov", "Dec", "Jan", "Feb",
        "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Mov",
    ]
    for section in _ORDERED_SECTIONS:
        if section in section_counts:
            log.info("  ByzTyp.%s: %d paragraphs", section, section_counts[section])
    log.info("Total: %d paragraphs", len(paragraphs))

    work = Work(
        work_id="typikon/violakis-1900",
        source_id=SOURCE_ID,
        author="Georgios Violakis",
        title="Τυπικόν",
        date_composed=None,
        date_range=(400, COMPOSED_BY),
        date_confidence="uncertain",
        genre="liturgical",
        language="grc",
        tradition="greek",
        license="public_domain",
        provenance_url="https://archive.org/details/typikontstou00orth",
        edition=(
            "Violakis Typikon, Ecumenical Patriarchate ed. (Athens, 1900); "
            "Internet Archive digitization"
        ),
        translation_of=None,
    )

    out_path.write_text(
        json.dumps(
            {"work": work.model_dump(), "paragraphs": paragraphs},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    log.info("Wrote %s (%d paragraphs)", out_path, len(paragraphs))
    return [work]


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
