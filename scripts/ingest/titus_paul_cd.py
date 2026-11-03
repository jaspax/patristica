"""
Ingestor for the Pauline Epistles, Georgian redaction CD (TITUS) (#515).

St Paul's Epistles in redactions C and D (Dzotsenidze and Danelia, Tbilisi
1974): the Athonite revisions of Euthymius (C) and George (D) the
Athonites. Ephrem Mtsire's redaction E is out of period and not here.

Source: TITUS, https://titus.uni-frankfurt.de/texte/etcs/cauc/ageo/nt/pavlecd/pavle.htm
Licence: ``_titus.TITUS_LICENSE`` (CC BY-NC-SA, #514).
Shared logic: ``scripts/ingest/_titus_bible.py``.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._titus_bible import BibleSet, ingest_bible

SOURCE_ID = "titus-paul-cd"

SPEC = BibleSet(
    source_id=SOURCE_ID,
    set_path="etcs/cauc/ageo/nt/pavlecd/pavle.htm",
    witness="Pauline Epistles, redaction CD",
    date_range=(978, 1065),
    date_confidence="approximate",
    author=None,
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one raw file per book to ``output_dir/titus-paul-cd/``."""
    return ingest_bible(SPEC, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
