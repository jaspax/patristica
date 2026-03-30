"""
Ingestion module for the World English Bible (WEB).

Source:  https://ebible.org/Scriptures/  (engwebp — Protestant canon)
Format:  USFM zip archive with Strong's-number word annotations
License: Public domain (Michael Paul Johnson dedication)
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._ebible_usfm import ingest_ebible_usfm

SOURCE_ID = "scripture/web"
ZIP_URL = "https://ebible.org/Scriptures/engwebp_usfm.zip"


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download and parse the World English Bible (Protestant canon)."""
    return ingest_ebible_usfm(
        output_dir=output_dir,
        zip_url=ZIP_URL,
        zip_filename="engwebp_usfm.zip",
        source_id=SOURCE_ID,
        language="eng",
        license_="public_domain",
        edition="World English Bible (WEB, 2000), via eBible.org",
        tradition=None,
        force=force,
    )


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
