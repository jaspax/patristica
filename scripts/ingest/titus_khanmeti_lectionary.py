"""
Ingestor for the khanmeti lectionary (Lectionarium Gracense, TITUS; #515).

The oldest Georgian lectionary fragments (khanmeti, 6th-7th c. manuscript of
a 5th-7th c. translation), preserved in Graz (the Schuchardt bequest, Gr.
2058/1) and Paris (géorgien 30), after Shanidze (Tbilisi 1944) and Outtier
(1972), edited from photographs by Gippert, Imnaishvili and Sarjveladze.

TITUS gives the manuscript page by page and line by line, each line in
Asomtavruli and in a Mkhedruli transcription, with the Bible location of the
lection as manuscript-level markers (Book / Chapter / Verse). One work, a
``liturgical`` one: its units are the verses read, in manuscript order, under
the Bible ref they render (``Matt.28.4``), so the reader shows them by
chapter. The Mkhedruli transcription is the text kept; text outside any
Bible location (lection titles) has no verse and is left out.

Licence: ``_titus.TITUS_LICENSE`` (CC BY-NC-SA, #514).
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from patristica.models import Work
from scripts.ingest import _titus
from scripts.ingest._titus_bible import TITUS_BOOKS, book_key, chapter_verse, join_unit, osis_book

log = logging.getLogger(__name__)

SOURCE_ID = "titus-khanmeti-lectionary"
SET_PATH = "etcs/cauc/ageo/xanmeti/grlekt/grlek.htm"
WORK_SLUG = "lectionarium-gracense"


def _mkhedruli(segment: _titus.Segment) -> bool:
    return segment.script == "mx" and _titus.is_main_text(segment)


# A lection's location: a verse, or a range read as one block ("2-8_H.").
_LECTION_VERSE_RE = re.compile(r"^(\d+)(?:-\d+)?(?:_.*)?$")


def _ref(label: str, chapter: str, verse: str) -> str:
    """The unit ref of a lection or hymn.

    A Bible lection is its book, chapter and first verse (``Mark.16.2`` for a
    block of 16:2-8 that the edition doesn't divide into verses). The hymns of
    the oldest Iadgari copied into the manuscript (``Udzv.Iadg.``, numbered by
    feast: ``WPasch._1_d2``) are ``Iadgari.{feast}``.
    """
    key = book_key(label)
    if key == "udzviadg":
        return "Iadgari." + re.sub(r"[^0-9A-Za-z]+", "_", verse).strip("_")
    osis = osis_book(label, TITUS_BOOKS)
    if osis is None:
        raise _titus.TitusError(f"{SOURCE_ID}: unknown TITUS book label {label!r}")
    m = _LECTION_VERSE_RE.match(verse)
    cv = chapter_verse(chapter, m.group(1)) if m else None
    if cv is None:
        raise _titus.TitusError(f"{SOURCE_ID}: unexpected location {label} {chapter}:{verse}")
    return f"{osis}.{cv[0]}.{cv[1]}"


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write the lectionary to ``output_dir/titus-khanmeti-lectionary/``."""
    url = _titus.BASE_URL + SET_PATH
    try:
        pages = list(_titus.iter_pages(url, output_dir, force=force))
    except _titus.TitusRestricted as exc:
        log.error("%s: skipped, %s", SOURCE_ID, exc)
        return []
    header = _titus.parse_header(pages[0][1])
    events: list[_titus.Event] = []
    for _, page in pages:
        events.extend(_titus.parse_page(page))
    units = _titus.collect_units(
        _titus.locate(events), ("Book", "Chapter", "Verse"), include=_mkhedruli,
    )
    paragraphs: list[dict[str, object]] = []
    seen: dict[str, int] = {}
    for unit in units:
        label, chapter, verse = unit.key
        if label is None or chapter is None or verse is None:
            continue
        ref = _ref(label, chapter, verse)
        if ref in seen:
            # a verse the manuscript reads twice (in two lections) or a page
            # break inside it: join it to the unit already there
            join_unit(paragraphs[seen[ref]], unit)
            continue
        seen[ref] = len(paragraphs)
        paragraphs.append(unit.raw(ref))

    printed = header.printed_edition.removeprefix("Codex Chanmeticus").strip()
    work = Work(
        work_id=f"{SOURCE_ID}/{WORK_SLUG}",
        source_id=SOURCE_ID,
        author=None,
        title="Khanmeti Lectionary (Lectionarium Gracense)",
        date_range=(450, 700),
        date_confidence="approximate",
        genre="liturgical",
        language="oge",
        tradition="georgian",
        license=_titus.TITUS_LICENSE,  # type: ignore[arg-type]
        provenance_url=url,
        edition=_titus.edition_line(
            f"{printed} (khanmeti lectionary, Graz Gr. 2058/1 and Paris géorgien 30)",
            editors=header.version_by or ("Jost Gippert",),
            last_changed=max(_titus.page_date(p) for _, p in pages),
        ),
    )
    out = output_dir / SOURCE_ID / f"{WORK_SLUG}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if force or not out.exists():
        out.write_text(json.dumps({"work": work.model_dump(), "paragraphs": paragraphs},
                                  ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    log.info("%s: %d verses", SOURCE_ID, len(paragraphs))
    return [work]


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
