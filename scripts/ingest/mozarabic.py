"""
Ingestor for Mozarabic (Visigothic) rite liturgical texts.

Sources (both via Internet Archive OCR text / _djvu.txt):
  - Ferotin (1912): Liber Mozarabicus Sacramentorum — collected Mozarabic mass prayers
  - Ferotin (1904): Liber Ordinum — ordination rites and blessings

License: Public domain (editions published before 1928)
Genre: liturgical  Language: lat  Tradition: latin

The Mozarabic rite is the ancient liturgy of the Iberian Peninsula, used by
Visigothic Spain and surviving in Toledo after the Arab conquest (711 CE).
Major texts are attributed to Isidore of Seville (d. 636) and Ildefonsus of
Toledo (d. 667) with roots in earlier Iberian liturgical practice (5th–6th c.).

The Ferotin editions are scholarly Latin editions with French introductions
and footnotes.  We identify Latin liturgical sections by detecting ALL-CAPS
feast-day headings (IN FESTO …, MISSA IN …, etc.) and extract the prayer
bodies that follow.

Internet Archive items are discovered at runtime via the IA search API so that
the correct identifiers are found even if the exact IDs change.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import NamedTuple

import httpx
from tqdm import tqdm

from patristica.models import Work
from scripts.ingest._common import download_file, offline, require_network, slugify_ref

log = logging.getLogger(__name__)

SOURCE_ID = "mozarabic"

_IA_SEARCH = "https://archive.org/advancedsearch.php"
_IA_DJVU_TMPL = "https://archive.org/download/{ia_id}/{ia_id}_djvu.txt"

# Latin function words used to identify Latin (vs French) sections
_LATIN_FN = frozenset([
    "deus", "deum", "deo", "dei", "dominus", "dominum", "domino", "domini",
    "enim", "autem", "sed", "nisi", "ergo", "aut", "ipse", "ipsa", "ipsi",
    "tua", "tuum", "tuam", "tuae", "nostri", "miserere", "sanctus", "sanctam",
    "sancti", "christe", "christus", "spiritus", "spiritu", "haec", "hoc",
    "hanc", "tibi", "nobis", "vobis", "per", "propter", "quam", "quod",
    "qui", "quae", "omnis", "omnes", "omnibus", "ecclesiam", "ecclesiae",
    "populi", "populo", "populum", "peccata", "peccatorum",
])
_FRENCH_FN = frozenset([
    "les", "des", "est", "dans", "pour", "avec", "sur", "par", "une",
    "qui", "que", "sont", "cette", "dont", "comme", "mais", "ses",
    "leur", "leurs", "plus", "aussi", "bien", "tout", "avoir", "notre",
])

# Prayer / section heading patterns for the Mozarabic liturgy
_HEADING_RE = re.compile(
    r"^\s*(IN\s+FESTO|IN\s+VIGILIA|IN\s+DIE|MISSA\s+IN|MISSA\s+DE|"
    r"MISSA\s+PRO|MISSA\s+(?:AD|IN)\s|ORATIO|COLLECTIO|CONTESTATIO|"
    r"POST\s+NOMINA|POST\s+PRIDIE|AD\s+PACEM|PRAEFATIO|BENEDICTIO|"
    r"ITEM\s+MISSA|INCIPIT\s+MISSA|INCIPIT\s+ORDO|ORDO\s+AD|"
    r"COMPLETURIA|ALIA\s+ORATIO|ALIA)\b",
    re.IGNORECASE,
)

# Skip lines that are page headers/footers, column numbers, etc.
_SKIP_LINE_RE = re.compile(
    r"^\s*(\d+\s*$|[IVXivx]+\s*$|^\s*[-—–]+\s*$)"
)


class _WorkSpec(NamedTuple):
    slug: str
    title: str
    edition: str
    ia_query: str
    date_composed: int
    date_range: tuple[int, int]
    provenance_url: str


_WORKS: list[_WorkSpec] = [
    _WorkSpec(
        slug="liber-mozarabicus-sacramentorum",
        title="Liber Mozarabicus Sacramentorum",
        edition="ed. Ferotin (Monumenta Ecclesiae Liturgica VI, Paris 1912)",
        ia_query='title:"liber mozarabicus sacramentorum"',
        date_composed=700,
        date_range=(550, 900),
        provenance_url="https://archive.org/search?query=liber+mozarabicus+sacramentorum+ferotin",
    ),
    _WorkSpec(
        slug="liber-ordinum",
        title="Liber Ordinum",
        edition="ed. Ferotin (Monumenta Ecclesiae Liturgica V, Paris 1904)",
        ia_query='title:"liber ordinum" ferotin',
        date_composed=700,
        date_range=(550, 900),
        provenance_url="https://archive.org/search?query=liber+ordinum+ferotin+mozarabic",
    ),
]

_REF_PREFIXES = {
    "liber-mozarabicus-sacramentorum": "MozLit.LMSacr",
    "liber-ordinum": "MozLit.LibOrd",
}


# ---------------------------------------------------------------------------
# Internet Archive helpers
# ---------------------------------------------------------------------------

def _ia_search_first_id(query: str, cache_dir: Path, force: bool) -> str | None:
    """Search Internet Archive and return the identifier of the best match."""
    cache_key = re.sub(r"[^a-z0-9]", "_", query.lower())[:50]
    cache_path = cache_dir / f"_ia_search_{cache_key}.json"
    if cache_path.exists() and (not force or offline()):
        try:
            return json.loads(cache_path.read_text())["identifier"]
        except Exception:
            pass

    require_network(f"searching the Internet Archive for {query!r}")
    params = {
        "q": query,
        "fl[]": ["identifier", "title"],
        "rows": "5",
        "output": "json",
        "sort[]": "downloads desc",
    }
    try:
        with httpx.Client(timeout=20, follow_redirects=True) as client:
            r = client.get(_IA_SEARCH, params=params)
        r.raise_for_status()
        docs = r.json().get("response", {}).get("docs", [])
    except Exception as exc:
        log.warning("IA search for %r failed: %s", query, exc)
        return None

    if not docs:
        log.warning("IA search for %r returned no results", query)
        return None

    ia_id = docs[0]["identifier"]
    log.info("IA search %r → %s (%s)", query, ia_id, docs[0].get("title", ""))
    cache_path.write_text(json.dumps({"identifier": ia_id, "title": docs[0].get("title")}))
    return ia_id


def _download_djvu_text(ia_id: str, cache_dir: Path, force: bool) -> Path | None:
    """Download the _djvu.txt OCR text for an Internet Archive item."""
    cache_path = cache_dir / f"{ia_id}_djvu.txt"
    url = _IA_DJVU_TMPL.format(ia_id=ia_id)
    try:
        return download_file(url, cache_path, etag_cache=True, force=force)
    except Exception as exc:
        log.warning("Failed to download IA djvu text for %s: %s", ia_id, exc)
        return None


# ---------------------------------------------------------------------------
# OCR text parser
# ---------------------------------------------------------------------------

def _is_latin_page(page_text: str) -> bool:
    """Heuristic: return True if this OCR page is predominantly Latin."""
    words = re.findall(r"\b[a-z]{3,}\b", page_text.lower())
    if not words:
        return False
    latin_count = sum(1 for w in words if w in _LATIN_FN)
    french_count = sum(1 for w in words if w in _FRENCH_FN)
    # Require at least some Latin signal and more Latin than French
    return latin_count >= 2 and latin_count > french_count


def _extract_paragraphs_from_ocr(
    djvu_text: str,
    ref_prefix: str,
) -> list[dict[str, str]]:
    """Parse _djvu.txt OCR text into prayer-level paragraphs with canonical refs.

    Strategy:
    1. Split into pages on form-feed (\\x0c).
    2. Keep only pages that are predominantly Latin.
    3. Within Latin pages, detect prayer headings and group subsequent lines
       into paragraph blocks.
    4. Each heading + its following body = one paragraph record.
    """
    pages = djvu_text.split("\x0c")
    latin_pages = [p for p in pages if _is_latin_page(p)]
    log.debug("%d/%d pages identified as Latin", len(latin_pages), len(pages))

    paragraphs: list[dict[str, str]] = []
    section_n = 0
    para_n = 0
    current_heading: str | None = None
    current_lines: list[str] = []

    def _flush() -> None:
        nonlocal current_heading, current_lines, section_n, para_n
        if not current_lines:
            return
        body = " ".join(current_lines).strip()
        body = re.sub(r"\s+", " ", body)
        if len(body) < 15:
            return
        para_n += 1
        ref = slugify_ref(f"{ref_prefix}.{section_n:04d}.{para_n:04d}")
        text = f"[{current_heading}] {body}" if current_heading else body
        paragraphs.append({"ref": ref, "text": text})

    for page in latin_pages:
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
                # Continuation of current prayer body
                current_lines.append(line)

    _flush()
    log.debug("Extracted %d prayer paragraphs", len(paragraphs))
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

    for spec in tqdm(_WORKS, desc="Mozarabic works"):
        out_path = out_dir / f"{spec.slug}.json"
        if out_path.exists() and not force:
            try:
                works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
                continue
            except Exception:
                pass

        ia_id = _ia_search_first_id(spec.ia_query, cache_dir, force=force)
        if not ia_id:
            log.warning("Cannot find IA item for %r — skipping", spec.slug)
            continue

        djvu_path = _download_djvu_text(ia_id, cache_dir, force=force)
        if not djvu_path:
            log.warning("Cannot download djvu text for %s — skipping", ia_id)
            continue

        djvu_text = djvu_path.read_text(encoding="utf-8", errors="replace")
        ref_prefix = _REF_PREFIXES[spec.slug]
        paragraphs = _extract_paragraphs_from_ocr(djvu_text, ref_prefix)

        if not paragraphs:
            log.warning("No paragraphs extracted from %s", ia_id)
            continue

        work = Work(
            work_id=f"mozarabic/{spec.slug}",
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
            provenance_url=f"https://archive.org/details/{ia_id}",
            edition=spec.edition,
            translation_of=None,
        )

        out_path.write_text(
            json.dumps({"work": work.model_dump(), "paragraphs": paragraphs}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("Wrote %s (%d paragraphs from IA %s)", out_path, len(paragraphs), ia_id)
        works.append(work)

    log.info("Mozarabic ingestion complete: %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
