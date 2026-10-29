"""
Codex Marianus, the Old Church Slavonic Tetraevangelion (Glagolitic, early
11th c.), from the Corpus Cyrillo-Methodianum Helsingiense (#332).

Source:  https://www.kielipankki.fi/download/ccmh-src/www/marianus.txt
Format:  CCMH 7-bit ASCII transliteration of Jagić's edition, one line per
         ``GCCVVL0`` (Gospel, chapter, verse, line); converted to Cyrillic by
         ``_ccmh.MARIANUS`` (the table on marianus.html).
License: CC BY 4.0 (https://www.kielipankki.fi/lic/ccmh-eng/)

One work per Gospel (``ccmh-marianus/matt`` …): each codex is its own
Scripture source, so its books join the Gospel version groups. The codex
lacks Matt 1:1–5:23 and John 21:18–25. The chapter lists (kephalaia) before
Mark, Luke and John, which CCMH files under chapter 0, are units
``{book}.0.{n}`` marked as titles (``_ccmh.chapter_list``, #369).
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._ccmh import MARIANUS, MARIANUS_RENUMBER, Codex, ingest_codex

SOURCE_ID = "ccmh-marianus"

CODEX = Codex(
    source_id=SOURCE_ID,
    name="Codex Marianus",
    file="marianus.txt",
    table=MARIANUS,
    edition="after V. Jagić, Quattuor evangeliorum versionis palaeoslovenicae codex "
            "Marianus glagoliticus (Berlin 1883)",
    renumber=MARIANUS_RENUMBER,
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Convert Codex Marianus into one raw work per Gospel."""
    return ingest_codex(CODEX, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
