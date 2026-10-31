"""
Ingestor for the Georgian Chronicle (Kartlis Tskhovreba), vol. I, on TITUS, one work per text (#517).

The first volume of the Georgian Chronicle (*Kartlis Tskhovreba*) on TITUS
(``etcs/cauc/ageo/kcx1/kcx1.htm``, J. Gippert, after S. Qaukhchishvili's
edition, Tbilisi 1955). Only the layers composed within the collection period
(``patristica/period.py``) are ingested: Leonti Mroveli's Lives of the Kings,
Conversion by Nino and Martyrdom of Archil, and Juansher's Life of Vakhtang
Gorgasali (both dated either c. 800 or to the 11th century: their ranges
start before 1050), and Sumbat Davitis-dze's Life of the Bagratids (c. 1030).
The Chronicle of Kartli (to 1072), the Life of David the Builder (12th c.)
and the Chronicle of Lasha-Giorgi's time (13th c.) are out of period and
skipped.

Units are the edition's pages within each part, ref ``KCx.{Work}.{part}.
{page}`` (``KCx.VitReg.1.3``): the edition's pages are how the chronicle is
cited.

Curated table: ``scripts/ingest/data/titus_chronicles.csv``; shared machinery:
``_titus_works.py``.

Licence: ``unknown`` until TITUS grants permission to republish (#514).
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._titus_works import ingest_titus_source

SOURCE_ID = "titus-chronicles"


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one raw JSON file per in-period text of the chronicle."""
    return ingest_titus_source(SOURCE_ID, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
