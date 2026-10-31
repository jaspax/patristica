"""
Ingestor for the Acts, oldest Georgian redaction (Sinai manuscripts, TITUS) (#515).

The oldest Georgian version of Acts, after Garitte's edition of two
Sinai manuscripts (Louvain 1955).

Source: TITUS, https://titus.uni-frankfurt.de/texte/etcs/cauc/ageo/nt/sakme/sakme.htm
Licence: ``_titus.TITUS_LICENSE`` (``unknown`` until TITUS grants
permission, #514): never translated, embedded, indexed or published.
Shared logic: ``scripts/ingest/_titus_bible.py``.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._titus_bible import BibleSet, ingest_bible

SOURCE_ID = "titus-acts-sinai"

SPEC = BibleSet(
    source_id=SOURCE_ID,
    set_path="etcs/cauc/ageo/nt/sakme/sakme.htm",
    witness="oldest redaction of Acts, Sinai manuscripts",
    date_range=(450, 1000),
    date_confidence="uncertain",
    author=None,
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one raw file per book to ``output_dir/titus-acts-sinai/``."""
    return ingest_bible(SPEC, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
