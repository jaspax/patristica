"""
Ingestor for the Catholic Epistles, Georgian redaction G (TITUS) (#515).

The Catholic Epistles in Lortkipanidze's redaction G (Tbilisi 1956), an
Athonite revision (by analogy with the Pauline redactions, Euthymius's).

Source: TITUS, https://titus.uni-frankfurt.de/texte/etcs/cauc/ageo/nt/kb/kbg/kbg.htm
Licence: ``_titus.TITUS_LICENSE`` (``unknown`` until TITUS grants
permission, #514): never translated, embedded, indexed or published.
Shared logic: ``scripts/ingest/_titus_bible.py``.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._titus_bible import BibleSet, ingest_bible

SOURCE_ID = "titus-catholic-g"

SPEC = BibleSet(
    source_id=SOURCE_ID,
    set_path="etcs/cauc/ageo/nt/kb/kbg/kbg.htm",
    witness="Catholic Epistles, redaction G (mss. A-584, A-34)",
    date_range=(978, 1065),
    date_confidence="uncertain",
    author=None,
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one raw file per book to ``output_dir/titus-catholic-g/``."""
    return ingest_bible(SPEC, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
