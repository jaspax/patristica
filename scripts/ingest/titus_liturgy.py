"""
Ingestor for the Old Georgian liturgies on TITUS, one work per text (#517).

* The Liturgy of St James and the Liturgy of the Presanctified Gifts, from the
  Prague and Graz fragments (TITUS ``etca/cauc/ageo/liturg/litjak/litja.htm``,
  after *Uʒvelesi kartuli xelnac̣erebi avsṭriaši*, Tbilisi 2004);
* the Liturgy of St James in the Old Georgian Arkhieratikon (``litjakgg``,
  after K. Kekelidze, *Drevne-gruzinskij arxieratikon*, Tiflis 1912), whose
  lines TITUS gives in the manuscript's script and in Mkhedruli (the
  Mkhedruli is kept);
* the Liturgy of St John Chrysostom from the Graz manuscript (``chryslit``).

Units are the editions' chapters (and paragraphs), ref ``LitJac.{chapter}.
{paragraph}``; the editions' apparatus (TITUS's ``Notes`` chapter) is left
out. TITUS marks no rubrics in these sets (no ``b`` segments), so there are
no rubric spans. Curated table: ``scripts/ingest/data/titus_liturgy.csv``;
shared machinery: ``_titus_works.py``.

Licence: ``unknown`` until TITUS grants permission to republish (#514).
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._titus_works import ingest_titus_source

SOURCE_ID = "titus-liturgy"


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one raw JSON file per liturgy."""
    return ingest_titus_source(SOURCE_ID, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
