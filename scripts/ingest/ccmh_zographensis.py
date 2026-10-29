"""
Codex Zographensis, the Old Church Slavonic Tetraevangelion (Glagolitic,
10th/11th c.), from the Corpus Cyrillo-Methodianum Helsingiense (#332).

Source:  https://www.kielipankki.fi/download/ccmh-src/www/zographensis.txt
         and zogr-b.txt (the later replacement leaves)
Format:  CCMH 7-bit ASCII transliteration of Jagić's edition with Moszyński's
         corrections, one line per ``GCCVVL0``; converted to Cyrillic by
         ``_ccmh.ZOGRAPHENSIS`` and, for the leaves, ``_ccmh.ZOGR_B`` (the two
         tables on zographensis.html).
License: CC BY 4.0 (https://www.kielipankki.fi/lic/ccmh-eng/)

One work per Gospel (``ccmh-zographensis/matt`` …). The codex lacks Matt
1:1–3:10. Matt 16:19–24:20 survive only on leaves a later scribe wrote to
replace lost ones (Zogr-B, 11th c., Glagolitic). They are part of the codex as
it is bound and fill its gap without overlap, so they are read into
``ccmh-zographensis/matt`` in verse order (their own table; the two verses
split at the leaf edges, 16:19 and 24:20, are joined), and the edition says
which verses they are. The chapter list before Luke and the title before
John, under chapter 0, are units ``{book}.0.{n}`` marked as titles
(``_ccmh.chapter_list``, #369).
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._ccmh import ZOGR_B, ZOGRAPHENSIS, Codex, ingest_codex

SOURCE_ID = "ccmh-zographensis"

CODEX = Codex(
    source_id=SOURCE_ID,
    name="Codex Zographensis",
    file="zographensis.txt",
    table=ZOGRAPHENSIS,
    edition="after V. Jagić, Quattuor evangeliorum codex glagoliticus olim Zographensis "
            "(Berlin 1879), with L. Moszyński's corrections (1961); Matt 16:19–24:20 from "
            "the later replacement leaves (Zogr-B)",
    leaves=("zogr-b.txt", ZOGR_B),
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Convert Codex Zographensis (with Zogr-B) into one raw work per Gospel."""
    return ingest_codex(CODEX, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
