"""
Ingestor for the Pauline Epistles, Georgian redaction AB (TITUS) (#515).

St Paul's Epistles in the old Georgian redactions A and B (Dzotsenidze and
Danelia, Tbilisi 1974), before the Athonite revisions.

Source: TITUS, https://titus.uni-frankfurt.de/texte/etcs/cauc/ageo/nt/pavleni/pavle.htm
Licence: ``_titus.TITUS_LICENSE`` (CC BY-NC-SA, #514).
Shared logic: ``scripts/ingest/_titus_bible.py``.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._titus_bible import BibleSet, ingest_bible

SOURCE_ID = "titus-paul-ab"

SPEC = BibleSet(
    source_id=SOURCE_ID,
    set_path="etcs/cauc/ageo/nt/pavleni/pavle.htm",
    witness="Pauline Epistles, redaction AB",
    date_range=(450, 1000),
    date_confidence="uncertain",
    author=None,
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one raw file per book to ``output_dir/titus-paul-ab/``."""
    return ingest_bible(SPEC, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
