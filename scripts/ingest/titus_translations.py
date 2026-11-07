"""
Ingestor for Old Georgian translations of Greek Fathers on TITUS, one work per text (#517).

Old Georgian translations of Greek Fathers whose originals are (mostly) in
the corpus, each a TITUS set or a text of one:

* Euthymius the Athonite (d. 1028): Gregory of Nyssa *De virginitate*, John
  Climacus's *Ladder* with Daniel of Raithu's *Life*, *To the Shepherd* and the
  scholia (and Euthymius's own preface), Chrysostom's *Homilies on John*, and
  21 homilies of Basil (one work per homily);
* George the Athonite (d. 1065): Gregory of Nyssa *De hominis opificio*, the
  sermon *On Repentance, Continence and Virginity* (CPG 7555);
* the Athonite school: Gregory of Nyssa's *Homilies on the Song of Songs*;
* earlier versions: Basil's *Hexaemeron* (Abuladze's oldest redaction) and a
  fragment of Maximus's *Questions to Thalassius*.

Works are dated by their translation; their author is the Greek author (the
translator is in ``edition``). Units follow the edition (chapters,
paragraphs or pages), ref ``{Author}.{Work}.{…}`` (``GrNyss.HomOp.1``).
Works whose original is in the corpus are linked in
``patristica/data/version_links.csv`` and enrolled for anchored derived
verses (#304).

Curated table: ``scripts/ingest/data/titus_translations.csv``; shared machinery:
``_titus_works.py``.

Licence: ``_titus.TITUS_LICENSE`` (CC BY-NC-SA, #514).
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._titus_works import ingest_titus_source

SOURCE_ID = "titus-translations"


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one raw JSON file per translated work."""
    return ingest_titus_source(SOURCE_ID, output_dir, force)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
