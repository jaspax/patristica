"""
Ingestor for Gallican liturgical texts.

Sources (via Internet Archive OCR text):
  GothMiss — Missale Gothicum: Neale & Forbes, "Ancient Liturgies of the
             Gallican Church" (Pitsligo Press, 1855–67), IA item
             AncientLiturgiesOfTheGallicanChurch.  English/Latin bilingual edition.
  GallVet  — Missale Gallicanum Vetus: Muratori, "Codices sacramentorum
             nongentis annis vetustiores" (1680), IA item bub_gb_6rVhPJ6sHdkC.
             Latin-only scholarly edition with 18th-century long-s OCR.

  NOTE: The Bobbio Missal and Stowe Missal are available on Internet Archive
  only as facsimile (photographic) editions with no usable OCR text, so they
  are not included here.

License: Public domain
Genre: liturgical  Language: lat  Tradition: latin
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

SOURCE_ID = "gallican"

_IA_DJVU_TMPL = "https://archive.org/download/{ia_id}/{ia_id}_djvu.txt"

# Latin function words for language detection
_LATIN_FN = frozenset([
    "deus", "deum", "deo", "dei", "dominus", "dominum", "domino", "domini",
    "enim", "autem", "sed", "nisi", "ergo", "aut", "ipse", "ipsa", "ipsi",
    "tua", "tuum", "tuam", "tuae", "nostri", "miserere", "sanctus", "sanctam",
    "sancti", "christe", "christus", "spiritus", "spiritu", "haec", "hoc",
    "hanc", "tibi", "nobis", "vobis", "per", "propter", "quam", "quod",
    "qui", "quae", "omnis", "omnes", "omnibus", "ecclesiam", "ecclesiae",
    "populi", "populo", "populum", "peccata", "peccatorum", "gaudeamus",
    "alleluia", "benedictus", "benedicite", "kyrie",
])
_ENGLISH_FN = frozenset([
    "the", "and", "that", "this", "with", "have", "from", "they",
    "which", "their", "there", "were", "been", "also", "would", "could",
    "shall", "upon", "unto", "wherein", "thereof", "therefore",
])

# Prayer-type headings within Gallican masses. A bare "MISSA …" is not one:
# in the Neale & Forbes OCR it matches a running head ("MISSA LE
# VESONTIONENSB."), a footnote and a line of prose (#241).
_HEADING_RE = re.compile(
    r"^\s*(MISSA\s+IN|MISSA\s+DE|MISSA\s+PRO|MISSA\s+(?:AD|IN)\s|"
    r"COLLECTIO|COLLECTA|PRAEFATIO|POST\s+NOMINA|POST\s+PRIDIE|"
    r"CONTESTATIO|IMMOLATIO|ANTE\s+ORATIONEM|AD\s+PACEM|ORATIO|"
    r"BENEDICTIO|BENEDICTIONES|INCIPIT|ITEM|ALIA\s+ORATIO|ALIA\b|"
    r"KYRIE|IN\s+NATALE|IN\s+FESTO|IN\s+DIE|IN\s+VIGILIA|SECRITA)\b",
    re.IGNORECASE,
)

# Skip short lines that are likely headers/footers or page numbers
_SKIP_LINE_RE = re.compile(r"^\s*(\d+\s*$|[IVXivx]+\s*$|[-—–]+\s*$)")


class _WorkSpec(NamedTuple):
    slug: str
    title: str
    ms_location: str
    date_composed: int
    date_range: tuple[int, int]
    ref_abbrev: str
    ia_id: str | None          # None = no usable text source available
    edition: str
    provenance_url: str


_WORKS: list[_WorkSpec] = [
    _WorkSpec(
        slug="missale-gothicum",
        title="Missale Gothicum",
        ms_location="Vatican Reg. Lat. 317",
        date_composed=700, date_range=(650, 750),
        ref_abbrev="GothMiss",
        ia_id="AncientLiturgiesOfTheGallicanChurch",
        # The scan holds all three parts (title pages dated 1855, 1858, 1867),
        # and the work's text runs through all of them.
        edition="ed. Neale & Forbes (Burntisland: Pitsligo Press, 1855–67)",
        provenance_url="https://archive.org/details/AncientLiturgiesOfTheGallicanChurch",
    ),
    _WorkSpec(
        slug="missale-gallicanum-vetus",
        title="Missale Gallicanum Vetus",
        ms_location="Vatican Pal. Lat. 493",
        date_composed=750, date_range=(700, 800),
        ref_abbrev="GallVet",
        ia_id="bub_gb_6rVhPJ6sHdkC",
        edition="ed. Muratori, Codices sacramentorum (1680)",
        provenance_url="https://archive.org/details/bub_gb_6rVhPJ6sHdkC",
    ),
    # Bobbio and Stowe Missals: all IA editions are photographic facsimiles
    # with no usable OCR text. Omitted until a text edition is available.
]


# ---------------------------------------------------------------------------
# OCR text helpers
# ---------------------------------------------------------------------------

def _download_ocr(ia_id: str, cache_dir: Path, force: bool) -> Path | None:
    cache_path = cache_dir / f"{ia_id}_djvu.txt"
    url = _IA_DJVU_TMPL.format(ia_id=ia_id)
    try:
        return download_file(url, cache_path, etag_cache=True, force=force)
    except Exception as exc:
        log.error("Failed to download IA djvu text for %s: %s", ia_id, exc)
        return None


def _is_latin_block(text: str) -> bool:
    words = re.findall(r"\b[a-z]{3,}\b", text.lower())
    if not words:
        return False
    lat = sum(1 for w in words if w in _LATIN_FN)
    eng = sum(1 for w in words if w in _ENGLISH_FN)
    return lat >= 2 and lat > eng


def _extract_paragraphs(text: str, ref_abbrev: str) -> list[dict[str, str]]:
    """Extract prayer paragraphs from an OCR text string.

    Splits on form-feed if present (DjVu pages); otherwise treats entire
    text as a single block.  Detects prayer headings and groups following
    lines into paragraph records.  Skips English-dominant blocks.
    """
    pages = text.split("\x0c") if "\x0c" in text else [text]

    paragraphs: list[dict[str, str]] = []
    section_n = 0
    para_n = 0
    current_heading: str | None = None
    current_lines: list[str] = []

    def _flush() -> None:
        nonlocal current_heading, current_lines, section_n, para_n
        if not current_lines:
            return
        body = re.sub(r"\s+", " ", " ".join(current_lines)).strip()
        if len(body) < 15:
            return
        para_n += 1
        ref = slugify_ref(f"GallLit.{ref_abbrev}.{section_n:04d}.{para_n:04d}")
        display = f"[{current_heading}] {body}" if current_heading else body
        paragraphs.append({"ref": ref, "text": display})

    for page in pages:
        if not _is_latin_block(page):
            continue
        for raw_line in page.splitlines():
            line = raw_line.strip()
            if not line or _SKIP_LINE_RE.match(line):
                continue
            if _HEADING_RE.match(line):
                _flush()
                current_heading = line.rstrip(":").strip()
                current_lines = []
                section_n += 1
                para_n = 0
            else:
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

    works: list[Work] = []
    for spec in tqdm(_WORKS, desc="Gallican manuscripts"):
        out_path = out_dir / f"{spec.slug}.json"
        if out_path.exists() and not force:
            try:
                works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
                continue
            except Exception:
                pass

        if spec.ia_id is None:
            log.info("No text source for %s — skipping", spec.slug)
            continue

        djvu_path = _download_ocr(spec.ia_id, cache_dir, force=force)
        if not djvu_path:
            log.warning("Cannot download OCR for %s (%s)", spec.slug, spec.ia_id)
            continue

        text = djvu_path.read_text(encoding="utf-8", errors="replace")
        log.info("Loaded %d chars for %s from IA %s", len(text), spec.slug, spec.ia_id)

        paragraphs = _extract_paragraphs(text, spec.ref_abbrev)
        if not paragraphs:
            log.warning("No paragraphs extracted for %s", spec.slug)
            continue

        work = Work(
            work_id=f"gallican/{spec.slug}",
            source_id=SOURCE_ID,
            author=None,
            title=spec.title,
            date_composed=spec.date_composed,
            date_range=spec.date_range,
            date_confidence="approximate",
            genre="liturgical",
            language="lat",
            tradition="latin",
            license="public_domain",
            provenance_url=spec.provenance_url,
            edition=f"{spec.edition}; MS: {spec.ms_location}",
            translation_of=None,
        )

        out_path.write_text(
            json.dumps({"work": work.model_dump(), "paragraphs": paragraphs}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("Wrote %s (%d paragraphs)", out_path, len(paragraphs))
        works.append(work)

    log.info("Gallican ingestion complete: %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
