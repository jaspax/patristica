"""
Ingestor for the Christian Arabic texts on Roger Pearse's *Early Church
Fathers – Additional Texts* (tertullian.org, #479): the Arabic.

Source: https://www.tertullian.org/fathers/index.htm (one page per work, the
English translation and the Arabic; parsed by ``_pearse_arabic``).
Output: ``data/raw/pearse-arabic/{slug}.json``
Language: arb  Tradition: arabic  Genre: patristic  License: public_domain

- Yaḥyā ibn ʿAdī (893–974), three treatises from Paul Sbath, *Vingt traités*
  (Cairo 1929), nos. 15–17;
- Abū al-Faraj ʿAbdallāh ibn al-Ṭayyib (d. 1043), Sbath no. 19;
- Severus ibn al-Muqaffaʿ, *Book of the Councils*, an unpublished portion in
  Cairo, Coptic Museum Theol. 196 (Graf's Cairo 111), ff. 268v–270v, in
  Youhanna Youssef's transcription (the manuscript lines are joined and split
  where a new speaker begins, "wa-qāla");
- al-Majdalus, *Commentary on the Nicene Creed* (Beirut USJ 569a/569b, with
  their variants as notes), of uncertain date: Pearse places him in the 10th
  century, and nothing places him after 1050.

The pages say "This file and all material on this page is in the public
domain - copy freely"; Sbath's edition of 1929 is public domain as well.
Works carry no date of their own (``date_confidence`` uncertain): the authors'
dates in the author index date them. Editorial material: see
``_pearse_arabic``.
"""

from __future__ import annotations

from pathlib import Path

from patristica.models import Work
from scripts.ingest._pearse_arabic import ARABIC_SOURCE, ingest_pages

SOURCE_ID = ARABIC_SOURCE


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    return ingest_pages(output_dir, force, english=False)


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
