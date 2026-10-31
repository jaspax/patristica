"""
Ingestor for the Psalms and Odes, Georgian redaction A (TITUS) (#515).

The Psalter and Odes in Shanidze's redaction A (Tbilisi 1960), the old
Georgian Psalter of the 10th-century manuscripts.

Source: TITUS, https://titus.uni-frankfurt.de/texte/etcs/cauc/ageo/at/psa/psa.htm
Licence: ``_titus.TITUS_LICENSE`` (``unknown`` until TITUS grants
permission, #514): never translated, embedded, indexed or published.
Shared logic: ``scripts/ingest/_titus_bible.py``.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._titus_bible import BibleSet, ingest_bible

SOURCE_ID = "titus-psalter-a"

SPEC = BibleSet(
    source_id=SOURCE_ID,
    set_path="etcs/cauc/ageo/at/psa/psa.htm",
    witness="Psalter and Odes, redaction A",
    date_range=(450, 1000),
    date_confidence="approximate",
    author=None,
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one raw file per book to ``output_dir/titus-psalter-a/``."""
    return ingest_bible(SPEC, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
