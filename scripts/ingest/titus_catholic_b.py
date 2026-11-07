"""
Ingestor for the Catholic Epistles, Georgian redaction B (TITUS) (#515).

The Catholic Epistles in Lortkipanidze's redaction B (Tbilisi 1956), the
old version in the Lagurka (Kala) manuscript from Svaneti.

Source: TITUS, https://titus.uni-frankfurt.de/texte/etcs/cauc/ageo/nt/kb/kbb/kbb.htm
Licence: ``_titus.TITUS_LICENSE`` (CC BY-NC-SA, #514).
Shared logic: ``scripts/ingest/_titus_bible.py``.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._titus_bible import BibleSet, ingest_bible

SOURCE_ID = "titus-catholic-b"

SPEC = BibleSet(
    source_id=SOURCE_ID,
    set_path="etcs/cauc/ageo/nt/kb/kbb/kbb.htm",
    witness="Catholic Epistles, redaction B (Lagurka ms.)",
    date_range=(450, 1000),
    date_confidence="uncertain",
    author=None,
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one raw file per book to ``output_dir/titus-catholic-b/``."""
    return ingest_bible(SPEC, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
