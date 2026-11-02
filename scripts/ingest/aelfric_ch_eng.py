"""
Ingestor for Benjamin Thorpe's English translation of Ælfric's *Catholic
Homilies* I (#566).

Source: the same file as ``aelfric_ch`` (``_aelfric_ch``): Thorpe, *The
Homilies of the Anglo-Saxon Church* I (1844), Project Gutenberg eBook #38334
(public domain).
Output: ``data/raw/aelfric-ch-eng/{work}.json``
Language: eng  Tradition: latin  Genre: patristic  License: public_domain

41 works: the Old English preface and the 40 homilies (Thorpe gives no
English for the Latin preface). Each work's ``translation_of`` is its Old
English work ``aelfric-ch/{work}``, and its units have the Old English
work's refs, paragraph for paragraph.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._aelfric_ch import ENGLISH_SOURCE, ingest_source

SOURCE_ID = ENGLISH_SOURCE


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    return ingest_source(output_dir, force, english=True)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
