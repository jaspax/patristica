"""
Ingestor for the Old Georgian Jerusalem lectionary (Paris manuscript, TITUS; #515).

The Georgian version of the Great Lectionary of Jerusalem (5th-8th c.), as
Tarchnischvili edited it from the Paris, Kala, Latali and Sinai manuscripts
(CSCO 188 + 204, Louvain 1959), with the full pericopes TITUS inserted from
Danelia, Chkhenkeli and Shavishvili's edition of the Paris manuscript (Tbilisi
1987, 1997) and, for the Kala (Lagurka) manuscript, Lortkipanidze (Tbilisi
1956).

One ``liturgical`` work. A unit is one of the edition's numbered entries (a
service, a chant, a lection), under its day: ``M12_24.3`` is entry 3, on 24
December (TITUS's date reference; movable feasts have their own,
``WQuadr_1_1``); the appendix the edition adds (``Lect.App.I``) is under
``App_I.``. Within an entry:

* the manuscripts' rubrics (``b`` classes) are ``rubric`` spans;
* the incipit and desinit the manuscripts give of a lection (``x`` classes
  outside a pericope) are ``note`` spans when TITUS also prints the full
  pericope, so the words aren't embedded twice;
* the pericope citation TITUS adds (``Jer_23_2-6``) is kept as a ``note``,
  ``[Jer 23:2-6]``;
* the inserted pericope itself is the text.

Licence: ``_titus.TITUS_LICENSE`` (CC BY-NC-SA, #514).
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
from collections.abc import Iterator
from pathlib import Path

from patristica.models import Work
from scripts.ingest import _titus
from scripts.ingest._titus_bible import join_unit

log = logging.getLogger(__name__)

SOURCE_ID = "titus-paris-lectionary"
SET_PATH = "etcs/cauc/ageo/lekt/lektpar/lektp.htm"
WORK_SLUG = "lectionarium-hierosolymitanum"

# TITUS's pericope citations: "Jer_23_2-6", "[Lk_2_14]", "Ps_66_7-8".
_CITATION_RE = re.compile(r"^\[?\s*([1-4]?[A-Z][A-Za-z.]*)_(\d+)_([\d,\-a-z]+)\s*\]?$")


def _citation(text: str) -> str | None:
    m = _CITATION_RE.match(text.strip())
    return f"[{m.group(1)} {m.group(2)}:{m.group(3)}]" if m else None


def _slug(value: str) -> str:
    """A date reference or entry as a ref segment: "WQuadr.1_1" → "WQuadr_1_1".

    Letters outside ASCII (one entry is typed "1426Ⴀქ") are dropped.
    """
    return re.sub(r"[^0-9A-Za-z]+", "_", value).strip("_")


def _in_pericope(item: _titus.Located) -> bool:
    return item.xloc.get("Biblical book", "_") not in ("_", "")


def _prepare(located: list[_titus.Located]) -> Iterator[_titus.Located]:
    """Citations as Georgian-script-free notes the unit filter keeps."""
    for item in located:
        cite = _citation(item.segment.text) if not item.segment.script else None
        if cite:
            seg = dataclasses.replace(item.segment, cls="citation", text=f" {cite} ")
            yield dataclasses.replace(item, segment=seg)
        else:
            yield item


def _include(segment: _titus.Segment) -> bool:
    return segment.cls == "citation" or _titus.is_main_text(segment)


def _kind(item: _titus.Located) -> str | None:
    seg = item.segment
    if seg.cls == "citation":
        return "note"
    if "b" in seg.flags:
        return "rubric"
    return None


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write the lectionary to ``output_dir/titus-paris-lectionary/``."""
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
    located = list(_prepare(list(_titus.locate(events))))

    # Entries that print a full pericope: their incipits/desinits are notes.
    with_pericope = {
        item.loc.get("Entry") for item in located
        if _in_pericope(item) and _titus.is_main_text(item.segment)
    }

    def kind(item: _titus.Located) -> str | None:
        k = _kind(item)
        if k:
            return k
        if ("x" in item.segment.flags and not _in_pericope(item)
                and item.loc.get("Entry") in with_pericope):
            return "note"
        return None

    units = _titus.collect_units(
        located, ("Book", "Date reference", "Entry"), include=_include, located_kind=kind,
    )
    paragraphs: list[dict[str, object]] = []
    by_ref: dict[str, dict[str, object]] = {}
    for unit in units:
        book, date, entry = unit.key
        if date is None:
            continue  # the edition's preface, before the first day
        section = _slug(date)
        if book and book != "Lect.Par.":
            section = f"{_slug(book.removeprefix('Lect.'))}.{section}"  # "App_I.M12_23"
        entry_slug = _slug(entry or "")
        if not entry_slug:
            # an entry without a number: part of the one before
            if paragraphs:
                join_unit(paragraphs[-1], unit)
            continue
        ref = f"{section}.{entry_slug}"  # "282a": an entry the edition inserted
        if ref in by_ref:
            log.warning("%s: %s twice; the texts are joined", SOURCE_ID, ref)
            join_unit(by_ref[ref], unit)
            continue
        by_ref[ref] = unit.raw(ref)
        paragraphs.append(by_ref[ref])

    work = Work(
        work_id=f"{SOURCE_ID}/{WORK_SLUG}",
        source_id=SOURCE_ID,
        author=None,
        title="Jerusalem Lectionary (Georgian version, Paris manuscript)",
        date_range=(450, 800),
        date_confidence="approximate",
        genre="liturgical",
        language="oge",
        tradition="georgian",
        license=_titus.TITUS_LICENSE,  # type: ignore[arg-type]
        provenance_url=url,
        edition=_titus.edition_line(
            header.printed_edition,
            editors=header.version_by or ("Jost Gippert",),
            last_changed=max(_titus.page_date(p) for _, p in pages),
        ),
    )
    out = output_dir / SOURCE_ID / f"{WORK_SLUG}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    if force or not out.exists():
        out.write_text(json.dumps({"work": work.model_dump(), "paragraphs": paragraphs},
                                  ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    log.info("%s: %d entries", SOURCE_ID, len(paragraphs))
    return [work]


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
