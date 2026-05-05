"""
Ingestor for the Apostolic Constitutions (all 8 books).

Source: CCEL Ante-Nicene Fathers Vol. 7 (Roberts-Donaldson, 1886)
        https://ccel.org/ccel/s/schaff/anf07.xml
License: Public domain
Genre: patristic  Language: eng  Tradition: greek

The Apostolic Constitutions is a 4th-century Syrian compilation (c. 375–380 CE)
of church order, ethics, and liturgical rites, attributed pseudonymously to
Clement of Rome.  Its eight books cover:

  I–II:   Ethical instructions for laity, clergy
  III:    Rules for widows and deaconesses
  IV:     Charity and care for the poor
  V:      Treatment of martyrs and observance of holy days
  VI:     Refutation of heresies; revised Didascalia
  VII:    Christian moral life; baptismal/eucharistic rites (incorporates the
          Didache with expansions); the "Clementine" liturgical prayers
  VIII:   The Clementine Liturgy — a complete Greek anaphora and the fullest
          early liturgical text we possess; ordination rites; Apostolic Canons

Book VIII is of particular liturgical importance: its anaphora is the most
fully developed early Greek eucharistic prayer and a structural precursor to
the Byzantine rites.

Each book is extracted as a separate section with book-keyed canonical refs
(ApostConst.I, ApostConst.II, … ApostConst.VIII).

Note: ccel_anf.py already ingests this as patristic/ccel-anf/anf07/009.json
in a single anonymous blob. This ingestor supersedes it with correct metadata
and book-level structure.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from lxml import etree

from patristica.models import Work
from scripts.ingest._ccel_common import (
    _extract_paragraphs_from_div1,
    _find_body,
    _get_head_text,
    download_volume,
)

log = logging.getLogger(__name__)

SOURCE_ID = "patristic/apostolic-constitutions"
_ANF_VOL = "anf07"
_WORK_SLUG = "apostolic-constitutions"

_BOOK_ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII"]


def _find_ac_book_div2s(body: etree._Element) -> list[etree._Element]:
    """Return the 8 Book div2 elements from the Apostolic Constitutions div1."""
    for div1 in body:
        if div1.tag is etree.Comment:
            continue
        if etree.QName(div1.tag).localname != "div1":
            continue
        head1 = (_get_head_text(div1) or "").lower()
        if "constitution" not in head1:
            continue
        books = []
        for div2 in div1:
            if div2.tag is etree.Comment:
                continue
            if etree.QName(div2.tag).localname != "div2":
                continue
            from scripts.ingest._ccel_common import _element_inner_text
            preview = (_element_inner_text(div2) or "")[:120].lower()
            if "book" in preview and ("constitutions" in preview or "laity" in preview
                                       or "bishop" in preview or "widow" in preview
                                       or "poor" in preview or "martyr" in preview
                                       or "heresy" in preview or "heresies" in preview
                                       or "christian life" in preview
                                       or "gifts" in preview or "ordination" in preview):
                books.append(div2)
        if books:
            return books
    return []


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    out_dir = output_dir / SOURCE_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_WORK_SLUG}.json"

    if out_path.exists() and not force:
        return [Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"])]

    anf_cache = output_dir / "patristic" / "ccel-anf"
    anf_cache.mkdir(parents=True, exist_ok=True)
    xml_path = download_volume(_ANF_VOL, anf_cache, force=force)

    tree = etree.parse(str(xml_path))
    body = _find_body(tree.getroot())
    if body is None:
        raise RuntimeError(f"No body element found in {_ANF_VOL}.xml")

    book_divs = _find_ac_book_div2s(body)
    if not book_divs:
        raise RuntimeError("Apostolic Constitutions book div2s not found in ANF07.")

    log.info("Found %d Apostolic Constitutions book sections", len(book_divs))

    all_paragraphs: list[dict[str, str]] = []
    for i, div2 in enumerate(book_divs):
        roman = _BOOK_ROMAN[i] if i < len(_BOOK_ROMAN) else str(i + 1)
        paras = _extract_paragraphs_from_div1(div2, f"ApostConst.{roman}")
        log.debug("Book %s: %d paragraphs", roman, len(paras))
        all_paragraphs.extend(paras)

    log.info("Total paragraphs extracted: %d", len(all_paragraphs))

    work = Work(
        work_id=f"apostolic-constitutions/{_WORK_SLUG}",
        source_id=SOURCE_ID,
        author=None,
        title="Apostolic Constitutions",
        date_composed=380,
        date_range=(375, 400),
        date_confidence="approximate",
        genre="patristic",
        language="eng",
        tradition="greek",
        license="public_domain",
        provenance_url=f"https://ccel.org/ccel/s/schaff/{_ANF_VOL}.xml",
        edition="Ante-Nicene Fathers Vol. 7 (Roberts-Donaldson, 1886)",
        translation_of=None,
    )

    out_path.write_text(
        json.dumps({"work": work.model_dump(), "paragraphs": all_paragraphs}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("Wrote %s (%d paragraphs)", out_path, len(all_paragraphs))
    return [work]


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
