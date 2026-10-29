"""
Savvina kniga (Liber Sabbae), an Old Church Slavonic Gospel lectionary
(aprakos; Cyrillic, 11th c.), from the Corpus Cyrillo-Methodianum
Helsingiense (#332).

Source:  https://www.kielipankki.fi/download/ccmh-src/www/savvina.txt
Format:  CCMH 7-bit ASCII transliteration of Shchepkin's edition, arranged by
         Gospel verse (``GCCVVLP``; P numbers repeated readings); converted to
         Cyrillic by ``_ccmh.SAVVINA`` (Suprasliensis's principles, with this
         file's own jat ``"e``). A working version CCMH has not checked ("%"
         marks places to check; dropped).
License: CC BY 4.0 (https://www.kielipankki.fi/lic/ccmh-eng/)

One work per Gospel book (``ccmh-savvina/matt`` …), in verse order; verses
the lectionary doesn't read are absent, and a verse read on several days is
kept once, its first reading (``_ccmh.gospel_books``).
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._ccmh import SAVVINA, Codex, ingest_codex

SOURCE_ID = "ccmh-savvina"

CODEX = Codex(
    source_id=SOURCE_ID,
    name="Savvina kniga (aprakos lectionary)",
    file="savvina.txt",
    table=SAVVINA,
    edition="after V. N. Shchepkin, Savvina kniga (St Petersburg 1903); the "
            "lectionary's readings arranged by Gospel verse, each verse once",
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Convert Savvina kniga into one raw work per Gospel book."""
    return ingest_codex(CODEX, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
