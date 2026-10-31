"""
Ingestor for the Khanmeti Gospels from the palimpsest A-89 / A-844 (TITUS) (#515).

The oldest layer of the Georgian Gospels (khanmeti, 5th-7th c.), as
Kajaia read the palimpsest (Tbilisi 1984). TITUS prints each manuscript
line in Asomtavruli and in a Mkhedruli transcription; the transcription
(``mx`` classes) is the text kept. Books are ``Text`` and verses ``Paragraph`` there.

Source: TITUS, https://titus.uni-frankfurt.de/texte/etcs/cauc/ageo/xanmeti/saxareba/saxar.htm
Licence: ``_titus.TITUS_LICENSE`` (``unknown`` until TITUS grants
permission, #514): never translated, embedded, indexed or published.
Shared logic: ``scripts/ingest/_titus_bible.py``.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._titus import Segment, is_main_text
from scripts.ingest._titus_bible import BibleSet, ingest_bible

SOURCE_ID = "titus-khanmeti-gospels"


def _mkhedruli_main(segment: Segment) -> bool:
    """The Mkhedruli transcription, not the diplomatic Asomtavruli line."""
    return segment.script == "mx" and is_main_text(segment)


SPEC = BibleSet(
    source_id=SOURCE_ID,
    set_path="etcs/cauc/ageo/xanmeti/saxareba/saxar.htm",
    witness="khanmeti Gospel palimpsest A-89 / A-844",
    date_range=(450, 700),
    date_confidence="approximate",
    author=None,
    book_label="Text",
    verse_label="Paragraph",
    include=_mkhedruli_main,
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one raw file per book to ``output_dir/titus-khanmeti-gospels/``."""
    return ingest_bible(SPEC, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
