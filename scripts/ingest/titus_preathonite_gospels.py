"""
Ingestor for the Pre-Athonite Gospels (TITUS) (#515).

The pre-Athonite ("protovulgate") redaction of the Georgian Gospels:
the old version revised against the Greek in the 8th-10th centuries, in
10th-century manuscripts (Ksani, Berta, Jruchi, Parkhali, Sinai).

Source: TITUS, https://titus.uni-frankfurt.de/texte/etca/cauc/ageo/nt/cinant/cinan.htm
Licence: ``_titus.TITUS_LICENSE`` (CC BY-NC-SA, #514).
Shared logic: ``scripts/ingest/_titus_bible.py``.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._titus_bible import BibleSet, ingest_bible

SOURCE_ID = "titus-preathonite-gospels"

SPEC = BibleSet(
    source_id=SOURCE_ID,
    set_path="etca/cauc/ageo/nt/cinant/cinan.htm",
    witness="pre-Athonite (protovulgate) Gospel redaction, 10th-century manuscripts",
    date_range=(750, 1000),
    date_confidence="approximate",
    author=None,
    printed_edition=(
        "the original manuscripts, ed. Elguja Giunashvili, "
        "Manana Machkhaneli, Sophio Sarjveladze, "
        "Zurab Sarjveladze and Darejan Tvaltvadze, "
        "Tbilisi and Frankfurt 1999-2002"
    ),
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one raw file per book to ``output_dir/titus-preathonite-gospels/``."""
    return ingest_bible(SPEC, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
