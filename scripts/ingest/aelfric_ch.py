"""
Ingestor for Ælfric's *Catholic Homilies* I in Old English, Thorpe's edition
(#566).

Source: Benjamin Thorpe, *The Homilies of the Anglo-Saxon Church* I (1844),
Project Gutenberg eBook #38334, HTML edition (public domain); parsed by
``_aelfric_ch``.
Output: ``data/raw/aelfric-ch/{work}.json``
Language: ang (the Latin preface: lat)  Tradition: latin  Genre: patristic
License: public_domain

42 works: Ælfric's Latin preface (``ch1-praefatio-lat``), his Old English
preface (``ch1-praefatio``) and the 40 homilies (``ch1-01`` … ``ch1-40``).
Thorpe's facing English is the source ``aelfric-ch-eng``, with the same refs.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._aelfric_ch import OE_SOURCE, ingest_source

SOURCE_ID = OE_SOURCE


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    return ingest_source(output_dir, force, english=False)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
