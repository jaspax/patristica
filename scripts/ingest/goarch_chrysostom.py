"""
Ingestor for the Divine Liturgy of St. John Chrysostom (Greek).

Source: https://dcs.goarch.org/goa/dcs/h/b/skeleton/liturgy/chrys/gr-en/index.html
Format: GOA Digital Chant Stand bilingual HTML (table#biTable, leftCell = Greek)
License: Text is 4th-century; public domain.

The base text of the Liturgy of St. John Chrysostom dates to the late
4th century (attributed to John Chrysostom, 349–407 CE).  The current
standard form was substantially settled by the 8th century.

Canonical references
--------------------
``ByzLit.Chrysostom.{section_n:04d}.{para_n:04d}``
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from patristica.models import Work
from scripts.ingest._goarch_common import fetch_dcs_html, parse_dcs_liturgy

log = logging.getLogger(__name__)

SOURCE_ID = "goarch-chrysostom"

_DCS_URL = (
    "https://dcs.goarch.org/goa/dcs/h/b/skeleton/liturgy/chrys/gr-en/index.html"
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Fetch the Greek Chrysostom skeleton liturgy from dcs.goarch.org and write JSON."""
    out_root = Path(output_dir) / SOURCE_ID
    out_root.mkdir(parents=True, exist_ok=True)
    out_path = out_root / "liturgy.json"

    cache_path = Path(output_dir) / "_cache" / "goarch-dcs-chrysostom.html"

    if out_path.exists() and not force:
        log.info("Skipping %s (already exists)", out_path)
        with open(out_path) as f:
            saved = json.load(f)
        return [Work(**saved["work"])]

    html = fetch_dcs_html(_DCS_URL, cache_path, force=force)
    if html is None:
        log.error("Could not obtain HTML for Chrysostom liturgy; skipping.")
        return []

    paragraphs = parse_dcs_liturgy(html, service_abbrev="Chrysostom")
    if not paragraphs:
        log.error("No Greek paragraphs extracted from Chrysostom liturgy HTML.")
        return []

    work = Work(
        work_id=f"{SOURCE_ID}/liturgy",
        source_id=SOURCE_ID,
        author="John Chrysostom",
        title="Divine Liturgy of St. John Chrysostom",
        date_composed=380,
        date_range=(380, 407),
        date_confidence="approximate",
        genre="liturgical",
        language="grc",
        tradition="greek",
        license="public_domain",
        provenance_url=_DCS_URL,
        edition="GOA Digital Chant Stand (dcs.goarch.org), skeleton liturgy",
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
