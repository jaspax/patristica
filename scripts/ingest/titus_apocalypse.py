"""
Ingestor for the Apocalypse, Georgian version of Euthymius the Athonite (TITUS) (#515).

The Apocalypse, translated from the Greek by Euthymius the Athonite (with
Andrew of Caesarea's commentary, 978), after Imnaishvili (Tbilisi 1961).

Source: TITUS, https://titus.uni-frankfurt.de/texte/etcs/cauc/ageo/nt/apjo/apjo.htm
Licence: ``_titus.TITUS_LICENSE`` (``unknown`` until TITUS grants
permission, #514): never translated, embedded, indexed or published.
Shared logic: ``scripts/ingest/_titus_bible.py``.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._titus_bible import BibleSet, ingest_bible

SOURCE_ID = "titus-apocalypse"

SPEC = BibleSet(
    source_id=SOURCE_ID,
    set_path="etcs/cauc/ageo/nt/apjo/apjo.htm",
    witness="Euthymius the Athonite's version of the Apocalypse",
    date_range=(978, 1028),
    date_confidence="approximate",
    author="Euthymius the Athonite",
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one raw file per book to ``output_dir/titus-apocalypse/``."""
    return ingest_bible(SPEC, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
