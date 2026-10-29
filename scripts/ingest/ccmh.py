"""
The Slavonic Lives of Constantine-Cyril and Methodius (the "Pannonian
legends"), from the Corpus Cyrillo-Methodianum Helsingiense (#332).

Source:  https://www.kielipankki.fi/download/ccmh-src/www/vita_constantini.txt
         and vita_methodii.txt
Format:  CCMH 7-bit ASCII transliteration of Tomšič's edition, one line per
         ``CCVVVL0`` (chapter, verse, line); converted to Cyrillic by
         ``_ccmh.VITAE`` (Suprasliensis's principles; the edition's modern
         punctuation kept).
License: CC BY 4.0 (https://www.kielipankki.fi/lic/ccmh-eng/)

Both are original Slavonic compositions of the late 9th century, written in
Methodius's circle soon after each saint's death (Constantine 869, Methodius
885), and anonymous: tradition names Clement of Ohrid, or Methodius for the
Vita Constantini (``author_strings.csv``). They survive only in later copies
(15th c. and after). One work each (``ccmh/vita-constantini``,
``ccmh/vita-methodii``), one unit per verse of the edition (``{chapter}.{verse}``);
the manuscript's title is unit ``0``. ``genre: patristic``. Not anchored: no
original in another language exists.

The source id ``ccmh`` holds CCMH's non-Scripture texts; the Gospel codices
are sources of their own (``ccmh-marianus`` …), as Scripture witnesses.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from patristica.models import Work
from scripts.ingest._ccmh import (
    BASE_URL,
    CORPUS,
    VITAE,
    convert,
    fetch,
    group_units,
    join_lines,
    log_conversion,
    read_lines,
)

SOURCE_ID = "ccmh"

AUTHOR = "Anonymous (Pannonian legends)"
EDITION = ("F. Tomšič, in F. Grivec & F. Tomšič, Constantinus et Methodius Thessalonicenses: "
           "Fontes (Radovi Staroslavenskog Instituta 4, Zagreb 1960)")


@dataclass(frozen=True)
class Vita:
    slug: str
    file: str
    title: str
    date_composed: int
    date_range: tuple[int, int]


VITAE_WORKS = (
    # After Constantine's death (869) and before Methodius's (885).
    Vita("vita-constantini", "vita_constantini.txt",
         "Vita Constantini (Life of Constantine-Cyril)", 875, (869, 885)),
    # Soon after Methodius's death (6 April 885).
    Vita("vita-methodii", "vita_methodii.txt",
         "Vita Methodii (Life of Methodius)", 886, (885, 890)),
)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Convert the two Vitae into one raw work each."""
    source_dir = output_dir / SOURCE_ID
    source_dir.mkdir(parents=True, exist_ok=True)
    works: list[Work] = []
    for vita in VITAE_WORKS:
        out = source_dir / f"{vita.slug}.json"
        if out.exists() and not force:
            works.append(Work(**json.loads(out.read_text(encoding="utf-8"))["work"]))
            continue
        units = group_units(read_lines(fetch(vita.file, output_dir, force)), (2, 5))
        paragraphs: list[dict] = []
        unknown, dropped = Counter(), Counter()
        for (chapter, verse), lines in sorted(units.items()):
            conv = convert(join_lines(lines), VITAE)
            unknown.update(conv.unknown)
            dropped.update(conv.dropped)
            if not conv.text:
                continue
            unit: dict = {"ref": "0" if chapter == 0 else f"{chapter}.{verse}", "text": conv.text}
            if conv.editorial:
                unit["editorial"] = conv.editorial
            paragraphs.append(unit)
        log_conversion(vita.title, unknown, dropped)
        work = Work(
            work_id=f"{SOURCE_ID}/{vita.slug}",
            source_id=SOURCE_ID,
            title=vita.title,
            author=AUTHOR,
            date_composed=vita.date_composed,
            date_range=vita.date_range,
            date_confidence="approximate",
            genre="patristic",
            language="chu",
            tradition="slavonic",
            license="cc-by-4.0",
            provenance_url=BASE_URL + vita.file,
            edition=f"{EDITION}; {CORPUS}, ASCII transliteration converted to Cyrillic",
        )
        out.write_text(json.dumps({"work": work.model_dump(), "paragraphs": paragraphs},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        works.append(work)
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
