"""
Ingestor for the Old Testament of the Oshki and Jerusalem manuscripts (TITUS) (#515).

The Old Testament of the Oshki Bible (Athos, 978) and the Jerusalem
manuscripts: the old Georgian version of the books it has.

Source: TITUS, https://titus.uni-frankfurt.de/texte/etcs/cauc/ageo/at/oskijer/oskij.htm
Licence: ``_titus.TITUS_LICENSE`` (``unknown`` until TITUS grants
permission, #514): never translated, embedded, indexed or published.
Shared logic: ``scripts/ingest/_titus_bible.py``.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._titus_bible import BibleSet, ingest_bible

SOURCE_ID = "titus-oshki"

SPEC = BibleSet(
    source_id=SOURCE_ID,
    set_path="etcs/cauc/ageo/at/oskijer/oskij.htm",
    witness="Oshki Bible (978) and Jerusalem manuscripts",
    date_range=(450, 978),
    date_confidence="approximate",
    author=None,
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one raw file per book to ``output_dir/titus-oshki/``."""
    return ingest_bible(SPEC, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
