"""
Ingestor for the Catholic Epistles, Georgian redaction A1 (TITUS) (#515).

The Catholic Epistles in Lortkipanidze's redaction A1 (Tbilisi 1956), the
old version in the Sinai manuscripts 39 and 31.

Source: TITUS, https://titus.uni-frankfurt.de/texte/etcs/cauc/ageo/nt/kb/kba1/kba1.htm
Licence: ``_titus.TITUS_LICENSE`` (CC BY-NC-SA, #514).
Shared logic: ``scripts/ingest/_titus_bible.py``.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._titus_bible import BibleSet, ingest_bible

SOURCE_ID = "titus-catholic-a1"

SPEC = BibleSet(
    source_id=SOURCE_ID,
    set_path="etcs/cauc/ageo/nt/kb/kba1/kba1.htm",
    witness="Catholic Epistles, redaction A1 (Sinai mss. 39 and 31)",
    date_range=(450, 1000),
    date_confidence="uncertain",
    author=None,
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one raw file per book to ``output_dir/titus-catholic-a1/``."""
    return ingest_bible(SPEC, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
