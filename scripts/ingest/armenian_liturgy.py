"""
Ingestor for the Armenian Divine Liturgy (Issaverdens 1873 English translation).

Source: Internet Archive
        https://archive.org/details/ArmenianRitual0104
OCR plain text (*_djvu.txt), ~449 KB.  This file contains Parts I–IV of
"The Armenian Ritual"; we ingest Part I only ("The Armenian Liturgy").
Language: eng  Tradition: armenian  Genre: liturgical  License: public_domain

The Armenian Divine Liturgy (Badarak) is one of the oldest complete Christian
liturgies. Its core anaphoral prayers reflect 4th–5th century Alexandrian and
Antiochene models, and the rite was substantially fixed by the time of Catholicos
Sahak I (c. 439 CE). F. James Issaverdens translated the liturgy into English
and published it at the Armenian Monastery of St. Lazaro, Venice, 1873 (2nd ed.).

Canonical ref format
--------------------
  ArmLit.{n:04d}   — sequential paragraphs
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from patristica.models import Work
from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

SOURCE_ID = "armenian-liturgy"
_WORK_SLUG = "issaverdens-1873"
_URL = "https://archive.org/download/ArmenianRitual0104/Armenian_Ritual_01-04_djvu.txt"

# Markers to stop ingestion (Part II title page)
_PART_II_RE = re.compile(r"PART\s+II\b", re.IGNORECASE)

# Google Books / digitization watermark lines
_GOOGLE_RE = re.compile(r"Digitized\s+by\s+Google", re.IGNORECASE)

# Page header: a line that is only digits (with optional trailing space)
_PAGE_NUM_RE = re.compile(r"^\s*\d{1,3}\s*$")


def _clean_ocr(raw: str) -> str:
    """Strip front/back matter, Google watermarks, page numbers, and rejoin hyphens."""
    lines = raw.splitlines()

    # Find start: "OF THE ANTIQUITY" heading that precedes the introduction essay.
    # Skip the Google Books front matter and the repeated title pages.
    start = 0
    for i, line in enumerate(lines[:300]):
        s = line.strip()
        if "OF THE ANTIQUITY" in s:
            start = i
            break

    # Find end: start of Part II title page.
    # Markers: "PART II." or "THE ARMENIAN RITUAL" appearing after line 2000
    # (which is deep enough into Part I that it can only be the Part II title page).
    end = len(lines)
    for i in range(max(start, 2000), len(lines)):
        s = lines[i].strip()
        if _PART_II_RE.search(s) and len(s) < 20:
            end = i
            break
        if s == "THE ARMENIAN RITUAL":
            end = i
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

        # Drop Google Books watermark lines
        if _GOOGLE_RE.search(stripped):
            i += 1
            continue

        # Drop bare page numbers
        if _PAGE_NUM_RE.match(stripped):
            i += 1
            continue

        # Rejoin hyphenated line breaks
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
    """Split cleaned OCR into paragraph dicts {ref, text}."""
    raw_blocks = re.split(r"\n{2,}", text)

    paragraphs: list[dict[str, str]] = []
    counter = 0

    for raw_block in raw_blocks:
        block = re.sub(r"[ \t]+", " ", raw_block.replace("\n", " ")).strip()
        if not block or len(block) < 8:
            continue
        counter += 1
        ref = f"ArmLit.{counter:04d}"
        paragraphs.append({"ref": ref, "text": block})

    return paragraphs


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    out_dir = output_dir / SOURCE_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_WORK_SLUG}.json"

    if out_path.exists() and not force:
        return [Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"])]

    txt_path = output_dir / "_zips" / "armenian-ritual-issaverdens-1873.txt"
    download_file(_URL, txt_path, force=force)

    raw = txt_path.read_text(encoding="utf-8", errors="replace")
    log.info("Armenian Ritual OCR: %d bytes, %d lines", len(raw.encode()), raw.count("\n"))

    cleaned = _clean_ocr(raw)
    paragraphs = _extract_paragraphs(cleaned)
    log.info("Total: %d paragraphs", len(paragraphs))

    work = Work(
        work_id="armenian-liturgy/issaverdens-1873",
        source_id=SOURCE_ID,
        author="Anonymous (trans. F. James Issaverdens)",
        title="The Armenian Divine Liturgy (Badarak)",
        date_composed=None,
        date_range=(350, 500),
        date_confidence="uncertain",
        genre="liturgical",
        language="eng",
        tradition="armenian",
        license="public_domain",
        provenance_url="https://archive.org/details/ArmenianRitual0104",
        edition=(
            "Issaverdens, F. James (trans.), The Armenian Ritual Part I: "
            "The Armenian Liturgy (Venice: Armenian Monastery of St. Lazaro, 1873, 2nd ed.); "
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
