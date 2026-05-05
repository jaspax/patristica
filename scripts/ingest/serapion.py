"""
Ingestor for Bishop Sarapion's Prayer-Book (Wordsworth 1899 English translation).

Source: Internet Archive
        https://archive.org/details/bishopsarapionsp06sera
OCR plain text (*_djvu.txt), ~174 KB.
Language: eng  Tradition: coptic  Genre: liturgical  License: public_domain

Sarapion of Thmuis (d. after 362 CE) was Bishop of Thmuis in the Nile Delta
and a close associate of Athanasius. His prayer-book (c. 350–356 CE) is one
of the earliest datable Egyptian liturgical collections, containing 30 prayers
including the eucharistic anaphora, baptismal rites, ordination prayers,
blessing of oils, commendation of the dead, and pro-anaphoral prayers.

John Wordsworth (Bishop of Salisbury) translated and introduced the text for
the Society for Promoting Christian Knowledge in 1899, working from Georg
Wobbermin's 1899 critical edition of the Athos MS. (Lavra 149).

Canonical ref format
--------------------
  Sarap.{n:04d}   — sequential paragraphs across introduction + prayers
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from patristica.models import Work
from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

SOURCE_ID = "liturgical/serapion"
_WORK_SLUG = "wordsworth-1899"
_URL = "https://archive.org/download/bishopsarapionsp06sera/bishopsarapionsp06sera_djvu.txt"

# Page-running-header pattern: short line with a digit (page number) and
# a few words, e.g. "62 the prayers", "I. EUCHARISTIC ANAPHORA 61"
_PAGE_HEADER_RE = re.compile(
    r"^\s*(?:\d+(?:\s+\S+){1,4}|\S+(?:\s+\S+){0,3}\s+\d+)\s*$"
)

# Section-break markers in the index/notes that should stop ingestion.
# Once we see "I.  INDEX TO THE INTRODUCTION" we are in back-matter only.
_BACK_MATTER_RE = re.compile(r"I\.\s+INDEX\s+TO\s+THE\s+INTRODUCTION")


def _is_page_header(line: str) -> bool:
    s = line.strip()
    if len(s) > 50:
        return False
    if not re.search(r"\d", s):
        return False
    # Numbered paragraphs ("30. Laying on of hands…") must not be stripped
    if re.match(r"^\d+\.\s+\S{3,}", s):
        return False
    return bool(_PAGE_HEADER_RE.match(s))


def _clean_ocr(raw: str) -> str:
    """Strip IA front/back matter, page headers, and rejoin hyphenated line breaks."""
    lines = raw.splitlines()

    # Find start: the actual body INTRODUCTION heading (not the TOC entry).
    # The table of contents has "Introduction :—" (with colon/dash).
    # The body heading is a bare "INTRODUCTION" or "INTRODUCriON" line.
    # We take the LAST such bare occurrence in the first 300 lines.
    start = 0
    for i, line in enumerate(lines[:300]):
        s = line.strip()
        if re.match(r"INTRODUC", s, re.IGNORECASE) and len(s) < 20 and ":" not in s:
            start = i

    # Find end: back-matter starts with index (I. INDEX TO THE INTRODUCTION)
    end = len(lines)
    for i, line in enumerate(lines):
        if _BACK_MATTER_RE.search(line):
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

        if _is_page_header(stripped):
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
        if not block or len(block) < 10:
            continue
        # Skip footnote-only blocks (start with a footnote marker digit followed by space)
        if re.match(r"^\d+\s+[A-Z][a-z]", block) and len(block) < 80:
            # Could be a page header that slipped through; skip if very short
            if len(block) < 40:
                continue
        counter += 1
        ref = f"Sarap.{counter:04d}"
        paragraphs.append({"ref": ref, "text": block})

    return paragraphs


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    out_dir = output_dir / SOURCE_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_WORK_SLUG}.json"

    if out_path.exists() and not force:
        return [Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"])]

    txt_path = output_dir / "_zips" / "serapion-wordsworth-1899.txt"
    download_file(_URL, txt_path, force=force)

    raw = txt_path.read_text(encoding="utf-8", errors="replace")
    log.info("Serapion OCR: %d bytes, %d lines", len(raw.encode()), raw.count("\n"))

    cleaned = _clean_ocr(raw)
    paragraphs = _extract_paragraphs(cleaned)
    log.info("Total: %d paragraphs", len(paragraphs))

    work = Work(
        work_id="serapion/wordsworth-1899",
        source_id=SOURCE_ID,
        author="Sarapion of Thmuis",
        title="Bishop Sarapion's Prayer-Book",
        date_composed=353,
        date_range=(350, 360),
        date_confidence="approximate",
        genre="liturgical",
        language="eng",
        tradition="coptic",
        license="public_domain",
        provenance_url="https://archive.org/details/bishopsarapionsp06sera",
        edition=(
            "Wordsworth, John (trans.), Bishop Sarapion's Prayer-Book "
            "(London: SPCK, 1899); Internet Archive digitization"
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
