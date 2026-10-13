"""
Ingestion module for the American Standard Version (ASV, 1901).

Source:  https://github.com/scrollmapper/bible_databases  (formats/csv/ASV.csv)
License: Public domain (copyright expired)
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._scrollmapper import ingest_scrollmapper

SOURCE_ID = "asv"


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download and parse the American Standard Version (66 books)."""
    return ingest_scrollmapper(
        output_dir=output_dir,
        translation="ASV",
        source_id=SOURCE_ID,
        language="eng",
        license_="public_domain",
        edition="American Standard Version (1901)",
        tradition=None,
        force=force,
    )


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
