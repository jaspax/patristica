"""
Ingestor for the Würzburg glosses on the Pauline epistles, in Old Irish (#539).

Source: Adrian Doyle's digital text of *Thesaurus Palaeohibernicus* I 499–712
(Zenodo 5508250, CC BY 4.0); parsing in ``_wb_glosses``.
Output: ``data/raw/wb-glosses/{epistle}.json`` (``rom``, ``1cor``, … ``heb``)
Language: sga  Tradition: latin  Genre: patristic  License: cc-by-4.0

One work per epistle, one unit per gloss (``Wb.1a.8``). The English
translation is the companion source ``wb-glosses-eng``.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._wb_glosses import IRISH_SOURCE, ingest_source

SOURCE_ID = IRISH_SOURCE


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    return ingest_source(output_dir, force, english=False)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
