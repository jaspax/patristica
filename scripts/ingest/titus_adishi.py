"""
Ingestor for the Adishi Gospels and khanmeti fragments (TITUS) (#515).

The Adishi Gospels (897) with the khanmeti fragments: the earliest
Georgian Gospel text, translated in the 5th century (from Armenian or
Syriac, revised towards the Greek). Variant lines (``Verse: 1V``) are the
apparatus and are left out.

Source: TITUS, https://titus.uni-frankfurt.de/texte/etca/cauc/ageo/nt/adisnt/adisn.htm
Licence: ``_titus.TITUS_LICENSE`` (``unknown`` until TITUS grants
permission, #514): never translated, embedded, indexed or published.
Shared logic: ``scripts/ingest/_titus_bible.py``.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._titus_bible import BibleSet, ingest_bible

SOURCE_ID = "titus-adishi"

SPEC = BibleSet(
    source_id=SOURCE_ID,
    set_path="etca/cauc/ageo/nt/adisnt/adisn.htm",
    witness="Adishi Gospels (897) with the khanmeti fragments",
    date_range=(450, 897),
    date_confidence="approximate",
    author=None,
    printed_edition=(
        "the original manuscripts, "
        "ed. Sophio Sarjveladze and Darejan Tvaltvadze, "
        "Tbilisi 2001-2002"
    ),
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one raw file per book to ``output_dir/titus-adishi/``."""
    return ingest_bible(SPEC, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
