"""
Ingestor for the 14 Ethiopian Orthodox Anaphoras.

Source: "The Anaphoras of the Ethiopic Liturgy" (1928), Internet Archive
        item anaphorasofethio0000yait (_djvu.txt OCR text).
License: Public domain (published 1928, pre-copyright-cutoff)
Genre: liturgical  Language: eng  Tradition: ethiopic

The 14 Ethiopian Orthodox anaphoras are the core eucharistic prayers of the
Ethiopian Orthodox Tewahedo Church.  The oldest (Anaphora of the Apostles) is
among the most ancient surviving anaphoras, of Egyptian provenance attributed
to the 4th–5th century.

The 1928 IA volume contains English translations of all 14 anaphoras (with
scholarly notes interleaved).  We download the _djvu.txt OCR text, split it
into per-anaphora sections by recognizing the ALL-CAPS section headings, then
extract prayer-body paragraphs by filtering out footnote/note lines.

Beta Masaheft (betamasaheft.eu) was checked but only contains brief
bibliographic reference records for the anaphoras, not full text editions.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import NamedTuple

from tqdm import tqdm

from patristica.models import Work
from scripts.ingest._common import download_file, slugify_ref

log = logging.getLogger(__name__)

SOURCE_ID = "liturgical/gez-anaphoras"

_IA_ID = "anaphorasofethio0000yait"
_IA_DJVU_URL = f"https://archive.org/download/{_IA_ID}/{_IA_ID}_djvu.txt"

# Skip lines that appear to be footnote references, page numbers, or noise
_SKIP_LINE_RE = re.compile(
    r"^\s*(\d+\s*$"             # bare page number
    r"|[*’‘\xb9\xb2\xb3]\s*"  # footnote marker only
    r"|[-—–]{3,}"    # long dash
    r"|[A-Z\s]{3,}\s+\d+\s*$"  # "ANAPHORA OF THE APOSTLES 33" running header
    r")\s*$"
)
# Minimum paragraph length
_MIN_PARA = 25


class _AnaphoraMeta(NamedTuple):
    slug: str
    title: str
    date_composed: int
    date_range: tuple[int, int]
    # Pattern to match the section heading in the OCR text
    heading_pattern: str


# The 14 anaphoras and their OCR heading patterns.
# Patterns are matched case-insensitively against lines in the OCR text.
_ANAPHORAS: list[_AnaphoraMeta] = [
    _AnaphoraMeta("apostles",       "Anaphora of the Apostles",
                  380, (350, 500),
                  r"ANAPHORA\s+OF\s+THE\s+APOSTLES"),
    _AnaphoraMeta("our-lord",       "Anaphora of Our Lord Jesus Christ",
                  500, (400, 700),
                  r"ANAPHORA\s+OF\s+OUR\s+LORD\s+(?:JESUS\s+CHRIST)?"),
    _AnaphoraMeta("mary",           "Anaphora of Our Lady Mary",
                  500, (400, 700),
                  r"ANAPHORA\s+OF\s+OUR\s+LADY"),
    _AnaphoraMeta("john-evangelist","Anaphora of St. John the Evangelist",
                  500, (400, 700),
                  r"ANAPHORA\s+OF\s+SAINT\s+JOHN\s+THE\s+EVANGELIST"),
    _AnaphoraMeta("chrysostom",     "Anaphora of St. John Chrysostom",
                  407, (380, 450),
                  r"ANAPHORA\s+OF\s+SAINT\s+JOHN\s+CHRYSOSTOM"),
    _AnaphoraMeta("athanasios",     "Anaphora of St. Athanasios",
                  380, (350, 450),
                  r"ANAPHORA\s+OF\s+SAINT\s+ATHANA[SD]IU?S"),
    _AnaphoraMeta("epiphanius",     "Anaphora of St. Epiphanius",
                  403, (380, 430),
                  r"ANAPHORA\s+OF\s+SAINT\s+EPIPHA"),
    _AnaphoraMeta("orthodox-318",   "Anaphora of the 318 Orthodox",
                  325, (310, 400),
                  r"ANAPHORA\s+OF\s+THE\s+(?:318|CCCXVIII)"),
    _AnaphoraMeta("gregory-alex",   "Anaphora of St. Gregory of Alexandria",
                  444, (380, 500),
                  r"ANAPHORA\s+OF\s+SAINT\s+GREGORY\s+OF\s+ALEX"),
    _AnaphoraMeta("dioscorus",      "Anaphora of St. Dioscorus",
                  454, (430, 500),
                  r"ANAPHORA\s+OF\s+(?:SAINT\s+)?DIOSCORUS"),
    _AnaphoraMeta("jacob-serugh",   "Anaphora of Jacob of Serugh",
                  521, (450, 550),
                  r"ANAPHORA\s+OF\s+JAMES\s+OF\s+SERUG"),
    _AnaphoraMeta("gregory-arm",    "Anaphora of St. Gregory of Armenia",
                  331, (290, 380),
                  r"ANAPHORA\s+OF\s+SAINT\s+GREGORY\s+OF\s+ARM"),
    _AnaphoraMeta("cyril",          "Anaphora of St. Cyril",
                  444, (420, 500),
                  r"ANAPHORA\s+OF\s+SAINT\s+CYRIL"),
    _AnaphoraMeta("basil",          "Anaphora of St. Basil",
                  379, (350, 450),
                  r"ANAPHORA\s+OF\s+(?:SAINT\s+)?BASIL"),
]


# ---------------------------------------------------------------------------
# OCR text splitting and paragraph extraction
# ---------------------------------------------------------------------------

def _find_anaphora_sections(text: str) -> dict[str, tuple[int, int]]:
    """Locate the start and end character positions of each anaphora section.

    Returns a dict mapping anaphora slug → (start, end) in the full text.
    Only matches headings occurring after position 40000 (past the introduction).
    """
    # Build a combined regex that matches any anaphora heading
    compiled: list[tuple[str, re.Pattern]] = [
        (meta.slug, re.compile(meta.heading_pattern, re.IGNORECASE))
        for meta in _ANAPHORAS
    ]

    # Find first occurrence of each anaphora heading after the intro
    found: list[tuple[int, str]] = []  # (position, slug)
    for slug, pattern in compiled:
        for m in pattern.finditer(text):
            if m.start() > 40000:
                found.append((m.start(), slug))
                break  # take the first match after the intro

    found.sort(key=lambda x: x[0])

    sections: dict[str, tuple[int, int]] = {}
    for i, (start, slug) in enumerate(found):
        end = found[i + 1][0] if i + 1 < len(found) else len(text)
        sections[slug] = (start, end)

    return sections


def _extract_paragraphs_from_section(
    text: str,
    ref_prefix: str,
) -> list[dict[str, str]]:
    """Extract prayer paragraphs from an anaphora section.

    We group consecutive non-empty lines into paragraph blocks, skipping
    running headers (ALL-CAPS + page number) and footnote-only lines.
    Lines like 'The priest saith:' / 'The deacon saith:' are kept as
    context prefixes for the paragraph that follows.
    """
    lines = text.splitlines()
    paragraphs: list[dict[str, str]] = []
    para_n = 0
    current_lines: list[str] = []

    def _flush() -> None:
        nonlocal current_lines, para_n
        block = re.sub(r"\s+", " ", " ".join(current_lines)).strip()
        if len(block) >= _MIN_PARA:
            para_n += 1
            ref = slugify_ref(f"{ref_prefix}.{para_n:04d}")
            paragraphs.append({"ref": ref, "text": block})
        current_lines = []

    for raw_line in lines:
        line = raw_line.strip()

        if not line:
            _flush()
            continue

        if _SKIP_LINE_RE.match(line):
            continue

        current_lines.append(line)

    _flush()
    return paragraphs


# ---------------------------------------------------------------------------
# Main ingest
# ---------------------------------------------------------------------------

def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    out_dir = output_dir / SOURCE_ID
    cache_dir = out_dir / "_cache"
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Check if all already done
    works: list[Work] = []
    if not force:
        for meta in _ANAPHORAS:
            p = out_dir / f"{meta.slug}.json"
            if p.exists():
                try:
                    works.append(Work(**json.loads(p.read_text(encoding="utf-8"))["work"]))
                except Exception:
                    pass
        if len(works) == len(_ANAPHORAS):
            return works

    # Download the IA OCR text
    djvu_path = cache_dir / f"{_IA_ID}_djvu.txt"
    download_file(_IA_DJVU_URL, djvu_path, etag_cache=True, force=force)
    text = djvu_path.read_text(encoding="utf-8", errors="replace")
    log.info("Loaded %d chars from IA %s", len(text), _IA_ID)

    # Locate each anaphora section in the text
    sections = _find_anaphora_sections(text)
    log.info("Found %d anaphora sections in OCR text", len(sections))

    works = []
    for meta in tqdm(_ANAPHORAS, desc="Ethiopian anaphoras"):
        out_path = out_dir / f"{meta.slug}.json"
        if out_path.exists() and not force:
            try:
                works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
                continue
            except Exception:
                pass

        if meta.slug not in sections:
            log.warning("Anaphora %r not found in OCR text — skipping", meta.slug)
            continue

        start, end = sections[meta.slug]
        section_text = text[start:end]
        ref_prefix = f"EthLit.{meta.slug.replace('-', '').title()}"
        paragraphs = _extract_paragraphs_from_section(section_text, ref_prefix)

        if not paragraphs:
            log.warning("No paragraphs extracted for anaphora %r", meta.slug)
            continue

        work = Work(
            work_id=f"gez-anaphoras/{meta.slug}",
            source_id=SOURCE_ID,
            author=None,
            title=meta.title,
            date_composed=meta.date_composed,
            date_range=meta.date_range,
            date_confidence="uncertain",
            genre="liturgical",
            language="eng",
            tradition="ethiopic",
            license="public_domain",
            provenance_url=f"https://archive.org/details/{_IA_ID}",
            edition="The Anaphoras of the Ethiopic Liturgy (1928; SPCK)",
            translation_of=None,
        )

        out_path.write_text(
            json.dumps({"work": work.model_dump(), "paragraphs": paragraphs}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("%s: %d paragraphs", meta.slug, len(paragraphs))
        works.append(work)

    log.info("Gez anaphoras: %d works written", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
