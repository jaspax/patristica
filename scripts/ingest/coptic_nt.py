"""
Ingestion module for the Sahidic Coptic New Testament.

Source:  https://github.com/scrollmapper/bible_databases  (formats/csv/CopSahBible2.csv)
         The scrollmapper CopSahBible2 translation provides a clean verse-per-row
         Sahidic Coptic NT in Unicode.
License: Presumed public domain (ancient text; digital encoding freely available)
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._scrollmapper import ingest_scrollmapper

SOURCE_ID = "scripture/coptic-nt"


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download and parse the Sahidic Coptic NT (scrollmapper CopSahBible2)."""
    return ingest_scrollmapper(
        output_dir=output_dir,
        translation="CopSahBible2",
        source_id=SOURCE_ID,
        language="cop",
        license_="public_domain",
        edition="Sahidic Coptic New Testament (CopSahBible2 edition, via scrollmapper)",
        tradition="coptic",
        force=force,
    )


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
