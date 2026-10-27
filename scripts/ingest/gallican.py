"""
Ingestor for Gallican liturgical texts.

Sources (via Internet Archive OCR text):
  Neale & Forbes, "The Ancient Liturgies of the Gallican Church" (Pitsligo
  Press, 1855–67), IA item AncientLiturgiesOfTheGallicanChurch: an
  English/Latin edition in three parts, one work per missal it prints (#245):
    Rich     — Missale Richenovense (the Mone Masses)
    GothMiss — Missale Gothicum
    GallNF   — Missale Gallicanum (Vetus), the text Muratori also prints
    Vesont   — Missale Vesontionense, Neale & Forbes's name for Mabillon's
               "Sacramentarium Gallicanum", the Bobbio Missal
  GallVet  — Missale Gallicanum Vetus: Muratori, "Codices sacramentorum
             nongentis annis vetustiores" (1680), IA item bub_gb_6rVhPJ6sHdkC.
             Latin-only scholarly edition with 18th-century long-s OCR.

  The book is cut into its missals at their title lines (``_Part.starts``):
  the paragraph running at a title line ends there, and the new missal's
  text continues that section under the next paragraph number. Section
  numbers count through the whole book, so the Missale Gothicum keeps the
  refs it had when it held the whole book.

  NOTE: The Stowe Missal is available on Internet Archive only as a
  facsimile (photographic) edition with no usable OCR text, so it is not
  included here.

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


class _Part(NamedTuple):
    """One missal of a book that prints several (#245)."""
    slug: str
    title: str
    ms_location: str
    date_composed: int
    date_range: tuple[int, int]
    ref_abbrev: str
    #: The missal's title line; None for the book's first missal.
    starts: re.Pattern[str] | None


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
    #: The missals of a book that prints several, in book order; empty for one work.
    parts: tuple[_Part, ...] = ()


#: The missals of Neale & Forbes, at their title lines in the OCR (#245).
_NEALE_FORBES_PARTS: tuple[_Part, ...] = (
    _Part("missale-richenovense", "Missale Richenovense (Mone Masses)",
          "Karlsruhe, Badische Landesbibliothek, Aug. perg. 253",
          650, (600, 700), "Rich", None),
    _Part("missale-gothicum", "Missale Gothicum", "Vatican Reg. Lat. 317",
          700, (650, 750), "GothMiss", re.compile(r"MISSALE\s+GOTHICUM")),
    _Part("missale-gallicanum-vetus-neale-forbes", "Missale Gallicanum Vetus",
          "Vatican Pal. Lat. 493", 750, (700, 800), "GallNF",
          re.compile(r"^\s*MISSALE\s+GALLICANUM\.\s*$")),
    _Part("missale-vesontionense", "Missale Vesontionense (Bobbio Missal)",
          "Paris, BnF lat. 13246", 700, (650, 750), "Vesont",
          re.compile(r"^\s*MISSALE\s+VESONTIONENSE")),
)


_WORKS: list[_WorkSpec] = [
    _WorkSpec(
        slug="missale-gothicum",
        title="Missale Gothicum",
        ms_location="Vatican Reg. Lat. 317",
        date_composed=700, date_range=(650, 750),
        ref_abbrev="GothMiss",
        ia_id="AncientLiturgiesOfTheGallicanChurch",
        # The scan holds all three parts (title pages dated 1855, 1858, 1867);
        # each missal in it is a work of its own (_NEALE_FORBES_PARTS).
        edition="ed. Neale & Forbes (Burntisland: Pitsligo Press, 1855–67)",
        provenance_url="https://archive.org/details/AncientLiturgiesOfTheGallicanChurch",
        parts=_NEALE_FORBES_PARTS,
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
    """Extract prayer paragraphs from an OCR text string (see ``_extract_parts``)."""
    part = _Part("", "", "", 0, (0, 0), ref_abbrev, None)
    return _extract_parts(text, (part,))[0]


def _extract_parts(text: str, parts: tuple[_Part, ...]) -> list[list[dict[str, str]]]:
    """Extract prayer paragraphs from an OCR text string, one list per part.

    Splits on form-feed if present (DjVu pages); otherwise treats entire
    text as a single block.  Detects prayer headings and groups following
    lines into paragraph records.  Skips English-dominant blocks.

    A line matching the next part's ``starts`` ends the running paragraph;
    the lines from there on are that part's, continuing the section under
    the next paragraph number, without the previous part's heading.
    """
    pages = text.split("\x0c") if "\x0c" in text else [text]

    out: list[list[dict[str, str]]] = [[] for _ in parts]
    part_i = 0
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
        abbrev = parts[part_i].ref_abbrev
        ref = slugify_ref(f"GallLit.{abbrev}.{section_n:04d}.{para_n:04d}")
        display = f"[{current_heading}] {body}" if current_heading else body
        out[part_i].append({"ref": ref, "text": display})

    for page in pages:
        if not _is_latin_block(page):
            continue
        for raw_line in page.splitlines():
            line = raw_line.strip()
            if not line or _SKIP_LINE_RE.match(line):
                continue
            nxt = parts[part_i + 1] if part_i + 1 < len(parts) else None
            if nxt is not None and nxt.starts is not None and nxt.starts.search(line):
                _flush()
                part_i += 1
                current_heading = None
                current_lines = []
            if _HEADING_RE.match(line):
                _flush()
                current_heading = line.rstrip(":").strip()
                current_lines = []
                section_n += 1
                para_n = 0
            else:
                current_lines.append(line)

    _flush()
    if part_i != len(parts) - 1:
        raise ValueError(f"only {part_i + 1} of {len(parts)} parts found: "
                         f"no title line for {parts[part_i + 1].slug!r}")
    return out


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
        parts = spec.parts or (_Part(spec.slug, spec.title, spec.ms_location, spec.date_composed,
                                     spec.date_range, spec.ref_abbrev, None),)
        out_paths = [out_dir / f"{part.slug}.json" for part in parts]
        if not force and all(p.exists() for p in out_paths):
            works.extend(Work(**json.loads(p.read_text(encoding="utf-8"))["work"])
                         for p in out_paths)
            continue

        if spec.ia_id is None:
            log.info("No text source for %s — skipping", spec.slug)
            continue

        djvu_path = _download_ocr(spec.ia_id, cache_dir, force=force)
        if not djvu_path:
            log.warning("Cannot download OCR for %s (%s)", spec.slug, spec.ia_id)
            continue

        text = djvu_path.read_text(encoding="utf-8", errors="replace")
        log.info("Loaded %d chars for %s from IA %s", len(text), spec.slug, spec.ia_id)

        for part, out_path, paragraphs in zip(parts, out_paths, _extract_parts(text, parts)):
            if not paragraphs:
                log.error("No paragraphs extracted for %s", part.slug)
                continue
            work = Work(
                work_id=f"gallican/{part.slug}",
                source_id=SOURCE_ID,
                author=None,
                title=part.title,
                date_composed=part.date_composed,
                date_range=part.date_range,
                date_confidence="approximate",
                genre="liturgical",
                language="lat",
                tradition="latin",
                license="public_domain",
                provenance_url=spec.provenance_url,
                edition=f"{spec.edition}; MS: {part.ms_location}",
                translation_of=None,
            )
            out_path.write_text(
                json.dumps({"work": work.model_dump(), "paragraphs": paragraphs},
                           ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log.info("Wrote %s (%d paragraphs)", out_path, len(paragraphs))
            works.append(work)

    log.info("Gallican ingestion complete: %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
