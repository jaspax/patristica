"""
Ingestor for the Athonite Gospels of George the Athonite (TITUS) (#515).

George the Athonite's (1009-1065) revision of the Georgian Gospels
against the Greek, the Georgian vulgate.

Source: TITUS, https://titus.uni-frankfurt.de/texte/etca/cauc/ageo/nt/giornt/giorn.htm
Licence: ``_titus.TITUS_LICENSE`` (``unknown`` until TITUS grants
permission, #514): never translated, embedded, indexed or published.
Shared logic: ``scripts/ingest/_titus_bible.py``.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._titus_bible import BibleSet, ingest_bible

SOURCE_ID = "titus-athonite-gospels"

SPEC = BibleSet(
    source_id=SOURCE_ID,
    set_path="etca/cauc/ageo/nt/giornt/giorn.htm",
    witness="George the Athonite's Gospel redaction",
    date_range=(1040, 1065),
    date_confidence="approximate",
    author="George the Athonite",
    printed_edition=(
        "the original manuscripts, ed. Elguja Giunashvili, "
        "Manana Machkhaneli, Sophio Sarjveladze, "
        "Darejan Tvaltvadze and Zurab Sarjveladze, "
        "Tbilisi and Frankfurt 1999-2002"
    ),
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one raw file per book to ``output_dir/titus-athonite-gospels/``."""
    return ingest_bible(SPEC, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
