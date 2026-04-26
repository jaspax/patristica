"""
Ingestor for the Divine Liturgy of St. Basil the Great (Greek).

Source: https://www.goarch.org/-/the-divine-liturgy-of-saint-basil-the-great
Format: HTML scrape (Liferay CMS, ``languageId=el_GR``)
License: Text is 4th-century; public domain.

The Liturgy of St. Basil the Great is attributed to Basil of Caesarea
(330–379 CE).  It is used on ten occasions per year in the Byzantine rite.
The text preserves archaic liturgical forms predating the Great Schism.

Canonical references
--------------------
``ByzLit.Basil.{section_n:04d}.{para_n:04d}``
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from patristica.models import Work
from scripts.ingest._goarch_common import fetch_greek_html, parse_greek_liturgy

log = logging.getLogger(__name__)

SOURCE_ID = "liturgical/goarch-basil"

_ENGLISH_URL = (
    "https://www.goarch.org/-/the-divine-liturgy-of-saint-basil-the-great"
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Scrape the Greek Basil liturgy from goarch.org and write JSON."""
    out_root = Path(output_dir) / SOURCE_ID
    out_root.mkdir(parents=True, exist_ok=True)
    out_path = out_root / "liturgy.json"

    cache_path = Path(output_dir) / "_cache" / "goarch-basil.html"

    if out_path.exists() and not force:
        log.info("Skipping %s (already exists)", out_path)
        with open(out_path) as f:
            saved = json.load(f)
        return [Work(**saved["work"])]

    html = fetch_greek_html(_ENGLISH_URL, cache_path, force=force)
    if html is None:
        log.error("Could not obtain HTML for Basil liturgy; skipping.")
        return []

    paragraphs = parse_greek_liturgy(html, service_abbrev="Basil")
    if not paragraphs:
        log.error("No Greek paragraphs extracted from Basil liturgy HTML.")
        return []

    work = Work(
        work_id="liturgical/goarch-basil/liturgy",
        source_id=SOURCE_ID,
        author="Basil of Caesarea",
        title="Divine Liturgy of St. Basil the Great",
        date_composed=370,
        date_range=(370, 379),
        date_confidence="approximate",
        genre="liturgical",
        language="grc",
        tradition="greek",
        license="public_domain",
        provenance_url=_ENGLISH_URL,
        edition="Greek Orthodox Archdiocese of America, goarch.org",
    )

    out_path.write_text(
        json.dumps(
            {"work": work.model_dump(), "paragraphs": paragraphs},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    log.info("Wrote %s (%d paragraphs)", out_path.name, len(paragraphs))
    return [work]


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
