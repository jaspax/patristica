"""
Ingestor for CCEL Nicene & Post-Nicene Fathers Series 2 (NPNF2), 14 volumes.

Source: https://ccel.org/ccel/s/schaff/npnf2{01-14}.xml
License: Public domain (19th-century English translations)
Language: English (eng)

Each volume is downloaded as ThML XML and split into one Work per <div1>.
"""

from __future__ import annotations

import logging
from pathlib import Path

from patristica.models import Work
from scripts.ingest._ccel_common import ingest_ccel_series

log = logging.getLogger(__name__)

SOURCE_ID = "ccel-npnf2"

# NPNF Series 2 volumes 1–14
_VOLUMES = [f"npnf2{i:02d}" for i in range(1, 15)]


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download and ingest all NPNF2 volumes (see ``ingest_ccel_series``).

    Parameters
    ----------
    output_dir: Root raw output directory (``data/raw``).
    force:      Re-download the volume XML even if cached.
    """
    volumes = [(v, f"NPNF Series 2 Vol. {int(v[5:])}") for v in _VOLUMES]
    return ingest_ccel_series(output_dir, SOURCE_ID, volumes, force=force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
