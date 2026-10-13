"""
Ingestion module for the Clementine Vulgate (Latin Bible).

Source:  https://ebible.org/Scriptures/  (latVUC)
Format:  USFM zip archive with footnote annotations
License: Public domain (Latin Vulgate text; Clementine edition 1592/1598)
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._ebible_usfm import ingest_ebible_usfm

SOURCE_ID = "clementine"
ZIP_URL = "https://ebible.org/Scriptures/latVUC_usfm.zip"

# Clementine Vulgate: Jerome's translation completed ~405 CE; Clementine revision 1592
_DATE_COMPOSED = 405
_DATE_RANGE = (382, 405)
_DATE_CONFIDENCE = "established"


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download and parse the Clementine Vulgate Latin Bible."""
    return ingest_ebible_usfm(
        output_dir=output_dir,
        zip_url=ZIP_URL,
        zip_filename="latVUC_usfm.zip",
        source_id=SOURCE_ID,
        language="lat",
        license_="public_domain",
        edition="Clementine Vulgate (1592/1598), via eBible.org (latVUC)",
        tradition="latin",
        date_composed=_DATE_COMPOSED,
        date_range=_DATE_RANGE,
        date_confidence=_DATE_CONFIDENCE,
        force=force,
    )


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
