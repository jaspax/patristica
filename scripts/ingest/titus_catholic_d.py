"""
Ingestor for the Catholic Epistles, Georgian redaction D (TITUS) (#515).

The Catholic Epistles in Lortkipanidze's redaction D (Tbilisi 1956), an
Athonite revision (by analogy with the Pauline redactions, George's).

Source: TITUS, https://titus.uni-frankfurt.de/texte/etcs/cauc/ageo/nt/kb/kbd/kbd.htm
Licence: ``_titus.TITUS_LICENSE`` (CC BY-NC-SA, #514).
Shared logic: ``scripts/ingest/_titus_bible.py``.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._titus_bible import BibleSet, ingest_bible

SOURCE_ID = "titus-catholic-d"

SPEC = BibleSet(
    source_id=SOURCE_ID,
    set_path="etcs/cauc/ageo/nt/kb/kbd/kbd.htm",
    witness="Catholic Epistles, redaction D (mss. A-137, A-677, K-12)",
    date_range=(978, 1065),
    date_confidence="uncertain",
    author=None,
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one raw file per book to ``output_dir/titus-catholic-d/``."""
    return ingest_bible(SPEC, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
