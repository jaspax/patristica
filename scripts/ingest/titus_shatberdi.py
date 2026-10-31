"""
Ingestor for the Shatberdi codex (TITUS), one work per text (#517).

The Shatberdi codex (Tbilisi, National Centre of Manuscripts, S-1141) was
copied at Shatberdi in Tao-Klarjeti in 973–976. It gathers Old Georgian
translations of patristic exegesis and theology (Gregory of Nyssa *On the
Making of Man*, Epiphanius *On the Twelve Stones*, the Physiologus, five works
of Hippolytus of Rome, Agathangelos, Aphrahat, Theodoret) and the original
Georgian *Conversion of Kartli* (version A).

Text: TITUS, ``etcs/cauc/ageo/satberd/satbe.htm`` (J. Gippert, after the
edition of B. Gigineishvili and E. Giunashvili, Tbilisi 1979). Each text of
the codex is one work, selected by TITUS's ``Text`` level; units are the
edition's chapters, ref ``Satb.{Work}.{chapter}`` (``Satb.HomOp.Intr``,
``Satb.HomOp.1``; ``.0`` is a title before the first chapter). The curated
table is ``scripts/ingest/data/titus_shatberdi.csv``; the shared machinery is
``_titus_works.py``.

Licence: ``unknown`` until TITUS grants permission to republish (#514).
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._titus_works import ingest_titus_source

SOURCE_ID = "titus-shatberdi"


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one raw JSON file per text of the Shatberdi codex."""
    return ingest_titus_source(SOURCE_ID, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
