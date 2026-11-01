"""
Ingestor for Stokes and Strachan's English translation of the Würzburg glosses
(#539).

Source: the same file as ``wb_glosses`` (``_wb_glosses``): Adrian Doyle's
digital text of *Thesaurus Palaeohibernicus* I 499–712 (Zenodo 5508250,
CC BY 4.0; the 1901 translation itself is in the public domain).
Output: ``data/raw/wb-glosses-eng/{epistle}.json``
Language: eng  Tradition: latin  Genre: patristic  License: cc-by-4.0

Each work's ``translation_of`` is its Irish work ``wb-glosses/{epistle}``, and
its units have the Irish work's refs, so the two align gloss for gloss. Not
enrolled for anchored derived verses: both are ingested as verses.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._wb_glosses import ENGLISH_SOURCE, ingest_source

SOURCE_ID = ENGLISH_SOURCE


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    return ingest_source(output_dir, force, english=True)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
