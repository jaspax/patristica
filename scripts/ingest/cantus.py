"""
Ingestor for the CANTUS Latin Chant Database.

Source: https://cantusdatabase.org/
Format: REST API — source metadata via /json-node/{id}; chant data via
        /source/{id}/csv/ (CSV, one row per chant entry)
License: Open/free for published data

Scope
-----
CANTUS indexes Latin chants found in medieval liturgical manuscripts.  We
include manuscripts whose date field parses to ≤ 1200 CE, since:

  * Manuscripts dated within the collection period (``patristica.period``)
    are dated by their year.
  * Manuscripts dated 1055–1200 are still early witnesses to a chant
    repertoire that was substantially fixed by the 9th–10th century.

Manuscripts with unparseable or absent date fields are skipped.

One ``Work`` is written per qualifying source (manuscript).  Each chant
row in the CSV becomes a ``paragraph`` entry (skipped if both
``fulltext_standardized`` and ``fulltext_ms`` are empty).

Canonical references
--------------------
``CANTUS.{siglum_slug}.{node_id}``

where ``siglum_slug`` is the RISM siglum with spaces and punctuation
replaced by underscores, and ``node_id`` is the chant's unique database
node identifier.  Rows that lack a node_id fall back to
``{folio_slug}.{sequence:04d}``.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import re
import time
from pathlib import Path

import httpx
from tqdm import tqdm

from patristica.models import DateConfidence, Work
from patristica.period import COMPOSED_BY
from scripts.ingest._common import slugify_ref

log = logging.getLogger(__name__)

SOURCE_ID = "cantus"

_BASE = "https://cantusdatabase.org"
_POLITE_DELAY = 0.15  # seconds between requests

# Manuscripts dated ≤ this year are included.
_MAX_YEAR = 1200


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

def _parse_earliest_year(date_str: str | None) -> int | None:
    """Return the earliest plausible year from a free-text date string.

    Returns None if no parseable year is found.
    """
    if not date_str:
        return None
    nums = re.findall(r"\b(\d{3,4})\b", date_str)
    years = [int(n) for n in nums if 400 <= int(n) <= 1900]
    return min(years) if years else None


def _date_metadata(year: int) -> tuple[int, tuple[int, int], DateConfidence]:
    """Return (date_composed, date_range, date_confidence) for a given year."""
    if year <= 1000:
        return year, (max(400, year - 50), year + 50), "established"
    elif year <= COMPOSED_BY:
        return year, (year - 25, COMPOSED_BY), "approximate"
    else:
        # Later manuscript, but first-millennium chant tradition
        return 950, (800, COMPOSED_BY), "approximate"


# ---------------------------------------------------------------------------
# Siglum slug
# ---------------------------------------------------------------------------

def _siglum_slug(siglum: str) -> str:
    """Convert a RISM siglum to a slug suitable for use in a canonical ref."""
    return re.sub(r"[^A-Za-z0-9]+", "_", siglum).strip("_")


# ---------------------------------------------------------------------------
# API helpers
# ---------------------------------------------------------------------------

def _get_all_source_ids(client: httpx.Client) -> list[str]:
    """Return all source IDs from the /json-sources/ endpoint."""
    r = client.get(f"{_BASE}/json-sources/", timeout=30)
    r.raise_for_status()
    return list(r.json().keys())


def _get_source_meta(client: httpx.Client, source_id: str) -> dict:
    """Fetch source metadata from /json-node/{id}."""
    r = client.get(f"{_BASE}/json-node/{source_id}", timeout=20)
    r.raise_for_status()
    return r.json()


def _get_source_csv(client: httpx.Client, source_id: str) -> list[dict]:
    """Download and parse the chant CSV for a given source ID."""
    r = client.get(f"{_BASE}/source/{source_id}/csv/", timeout=60)
    r.raise_for_status()
    reader = csv.DictReader(io.StringIO(r.text))
    return list(reader)


# ---------------------------------------------------------------------------
# Ingestor
# ---------------------------------------------------------------------------

def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download CANTUS source metadata and chant data; write per-source JSON."""
    out_root = Path(output_dir) / SOURCE_ID
    out_root.mkdir(parents=True, exist_ok=True)

    works: list[Work] = []

    with httpx.Client(follow_redirects=True) as client:
        log.info("Fetching CANTUS source list…")
        source_ids = _get_all_source_ids(client)
        log.info("  %d sources found", len(source_ids))

        # --- Pass 1: collect metadata for all sources and filter ---
        qualifying: list[tuple[str, dict, int]] = []  # (id, meta, earliest_year)

        for sid in tqdm(source_ids, desc="Fetching source metadata"):
            time.sleep(_POLITE_DELAY)
            try:
                meta = _get_source_meta(client, sid)
            except Exception as exc:
                log.error("  Skipping source %s: %s", sid, exc)
                continue

            year = _parse_earliest_year(meta.get("date"))
            if year is None:
                log.debug("  Skipping source %s: no parseable date (%r)", sid, meta.get("date"))
                continue
            if year > _MAX_YEAR:
                log.debug("  Skipping source %s: date too late (%r, year=%d)", sid, meta.get("date"), year)
                continue

            qualifying.append((sid, meta, year))

        log.info("%d sources qualify (date ≤ %d CE)", len(qualifying), _MAX_YEAR)

        # --- Pass 2: download chants and write output ---
        for sid, meta, earliest_year in tqdm(qualifying, desc="Downloading chant CSVs"):
            siglum = meta.get("siglum") or sid
            slug = _siglum_slug(siglum)
            out_path = out_root / f"{slug}.json"

            if out_path.exists() and not force:
                log.debug("  Skipping %s (already exists)", out_path.name)
                # Still reconstruct the Work so we can return it
                with open(out_path) as f:
                    saved = json.load(f)
                works.append(Work(**saved["work"]))
                continue

            time.sleep(_POLITE_DELAY)
            try:
                rows = _get_source_csv(client, sid)
            except Exception as exc:
                log.error("  Failed to download CSV for %s: %s", sid, exc)
                continue

            # Build Work
            date_composed, date_range, date_confidence = _date_metadata(earliest_year)
            work = Work(
                work_id=f"{SOURCE_ID}/{slug}",
                source_id=SOURCE_ID,
                author=None,
                title=meta.get("title") or siglum,
                date_composed=date_composed,
                date_range=date_range,
                date_confidence=date_confidence,
                genre="liturgical",
                language="lat",
                tradition="latin",
                license="public_domain",
                provenance_url=f"https://cantusdatabase.org/source/{sid}/csv/",
                edition=(
                    f"{siglum}; date: {meta.get('date','unknown')}; "
                    f"cursus: {meta.get('cursus') or 'unknown'}; "
                    f"CANTUS source id: {sid}"
                ),
            )

            # Build paragraphs from CSV rows
            paragraphs = []
            for row in rows:
                text = (row.get("fulltext_standardized") or "").strip()
                if not text:
                    text = (row.get("fulltext_ms") or "").strip()
                if not text:
                    text = (row.get("incipit") or "").strip()
                if not text:
                    continue

                node_id = (row.get("node_id") or "").strip()
                if node_id:
                    ref = slugify_ref(f"CANTUS.{slug}.{node_id}")
                else:
                    folio = re.sub(r"[^A-Za-z0-9]+", "_", (row.get("folio") or "").strip())
                    seq = (row.get("sequence") or "0").strip()
                    try:
                        seq_int = int(seq)
                    except ValueError:
                        seq_int = 0
                    ref = slugify_ref(f"CANTUS.{slug}.{folio}.{seq_int:04d}")

                # Store liturgical metadata as part of the text context
                feast = (row.get("feast") or "").strip()
                service = (row.get("service") or "").strip()
                genre_tag = (row.get("genre") or "").strip()
                cantus_id = (row.get("cantus_id") or "").strip()
                mode = (row.get("mode") or "").strip()
                position = (row.get("position") or "").strip()

                meta_parts = []
                if feast:
                    meta_parts.append(f"[{feast}]")
                if service:
                    meta_parts.append(f"[{service}]")
                if genre_tag:
                    meta_parts.append(f"[{genre_tag}]")
                if position:
                    meta_parts.append(f"[{position}]")
                if cantus_id:
                    meta_parts.append(f"[CANTUS:{cantus_id}]")
                if mode:
                    meta_parts.append(f"[mode:{mode}]")

                full_text = (" ".join(meta_parts) + " " + text).strip() if meta_parts else text

                paragraphs.append({"ref": ref, "text": full_text})

            if not paragraphs:
                log.warning("  No text found for source %s (%s)", sid, siglum)
                continue

            out_path.write_text(
                json.dumps(
                    {"work": work.model_dump(), "paragraphs": paragraphs},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            log.info("  Wrote %s (%d chants)", out_path.name, len(paragraphs))
            works.append(work)

    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
