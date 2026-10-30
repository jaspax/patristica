"""
Ingestor for the English translations of the Christian Arabic texts on Roger
Pearse's *Early Church Fathers – Additional Texts* (tertullian.org, #479).

Source: the same pages as ``pearse_arabic`` (``_pearse_arabic``).
Output: ``data/raw/pearse-arabic-eng/{slug}.json``
Language: eng  Tradition: the original's  Genre: patristic  License: public_domain

Sam Noble's translations (Sbath 15–17 and 19, al-Majdalus) and Youhanna
Youssef's (Severus), made for Roger Pearse and placed in the public domain on
the pages.  Each work's ``translation_of`` is its Arabic work
``pearse-arabic/{slug}``; the source is enrolled for anchored derived verses
(#304), so its derived verses are cut on the Arabic.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._pearse_arabic import ENGLISH_SOURCE, ingest_pages

SOURCE_ID = ENGLISH_SOURCE


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    return ingest_pages(output_dir, force, english=True)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
