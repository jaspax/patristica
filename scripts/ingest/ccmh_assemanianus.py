"""
Codex Assemanianus, an Old Church Slavonic Gospel lectionary (aprakos;
Glagolitic, 11th c.), from the Corpus Cyrillo-Methodianum Helsingiense (#332).

Source:  https://www.kielipankki.fi/download/ccmh-src/www/assemanianus.txt
Format:  CCMH 7-bit ASCII transliteration of Vajs & Kurz's edition, arranged by
         Gospel verse (``GCCVVLP``: P numbers the readings of a verse the
         lectionary has on several days); converted to Cyrillic by
         ``_ccmh.ASSEMANIANUS``. CCMH has not checked this file ("%" marks
         places to check; dropped).
License: CC BY 4.0 (https://www.kielipankki.fi/lic/ccmh-eng/)

One work per Gospel book (``ccmh-assemanianus/matt`` …), in verse order, so
the lectionary joins the Gospel version groups. A lectionary has only the
verses it reads: the rest are absent. A verse read on several days is kept
once: its first reading (P = 0), unless that one is cut short and a later
reading has the whole verse (``_ccmh.choose_reading``, #370); the repeats are
the same verse again, often cut short or opened with a lection formula.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._ccmh import ASSEMANIANUS, Codex, ingest_codex

SOURCE_ID = "ccmh-assemanianus"

CODEX = Codex(
    source_id=SOURCE_ID,
    name="Codex Assemanianus (aprakos lectionary)",
    file="assemanianus.txt",
    table=ASSEMANIANUS,
    lectionary=True,
    edition="after J. Vajs & J. Kurz, Evangeliarium Assemani: Codex Vaticanus "
            "3. slavicus glagoliticus (Prague 1929–1955); the lectionary's readings "
            "arranged by Gospel verse, each verse once",
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Convert Codex Assemanianus into one raw work per Gospel book."""
    return ingest_codex(CODEX, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
