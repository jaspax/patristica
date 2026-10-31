"""
Ingestor for the Acts, Georgian redactions A and B (TITUS) (#515).

Acts in Abuladze's redactions A and B (Tbilisi 1950): the old version,
before the Athonite revisions.

Source: TITUS, https://titus.uni-frankfurt.de/texte/etcs/cauc/ageo/nt/actsab/actsa.htm
Licence: ``_titus.TITUS_LICENSE`` (``unknown`` until TITUS grants
permission, #514): never translated, embedded, indexed or published.
Shared logic: ``scripts/ingest/_titus_bible.py``.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._titus_bible import BibleSet, ingest_bible

SOURCE_ID = "titus-acts-ab"

SPEC = BibleSet(
    source_id=SOURCE_ID,
    set_path="etcs/cauc/ageo/nt/actsab/actsa.htm",
    witness="Acts, redactions A and B",
    date_range=(450, 1000),
    date_confidence="uncertain",
    author=None,
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one raw file per book to ``output_dir/titus-acts-ab/``."""
    return ingest_bible(SPEC, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
