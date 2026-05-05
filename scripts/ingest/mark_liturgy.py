"""
Ingestor for the Divine Liturgy of St. Mark (English translation).

Source: CCEL Ante-Nicene Fathers Vol. 7 (Roberts-Donaldson, 1886)
        https://ccel.org/ccel/s/schaff/anf07.xml
License: Public domain
Genre: liturgical  Language: eng  Tradition: greek

The Liturgy of St. Mark is the ancient eucharistic rite of the Alexandrian
church, attributed to the apostle and evangelist Mark. It is the liturgical
ancestor of the Coptic Liturgy of St. Cyril and the Greek Orthodox Liturgy of
St. Mark still used on the feast of St. Mark in Alexandria. The extant form
reflects Egyptian Christianity of the 3rd–5th centuries, though the anaphora
core may be earlier.

ANF Vol. 7 contains Roberts-Donaldson's English translation under the title
"The Divine Liturgy of the Holy Apostle and Evangelist Mark." The ANF07 XML is
shared with the ccel_anf, syriac_james, and adai_mari ingestor caches.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from lxml import etree

from patristica.models import Work
from scripts.ingest._ccel_common import (
    _element_inner_text,
    _extract_paragraphs_from_div1,
    _find_body,
    _get_head_text,
    download_volume,
)

log = logging.getLogger(__name__)

SOURCE_ID = "liturgical/mark-liturgy"
_ANF_VOL = "anf07"
_WORK_SLUG = "liturgy-of-mark"


def _find_mark_div2(body: etree._Element) -> etree._Element | None:
    """Locate the Liturgy of St. Mark <div2> within ANF07.

    The Early Liturgies div1 contains several div2 blocks. The Mark liturgy is
    the one titled "The Divine Liturgy of the Holy Apostle and Evangelist Mark."
    """
    for div1 in body:
        if div1.tag is etree.Comment:
            continue
        if etree.QName(div1.tag).localname != "div1":
            continue
        head1 = (_get_head_text(div1) or "").lower()
        if "liturgi" not in head1:
            continue
        for div2 in div1:
            if div2.tag is etree.Comment:
                continue
            if etree.QName(div2.tag).localname != "div2":
                continue
            text_preview = (_element_inner_text(div2) or "")[:400].lower()
            if "mark" in text_preview and "evangelist" in text_preview:
                return div2
    return None


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

    div2 = _find_mark_div2(body)
    if div2 is None:
        raise RuntimeError(
            "Liturgy of St. Mark not found in ANF07. "
            "Expected a div2 under 'Early Liturgies.' whose text mentions "
            "'mark' and 'evangelist'."
        )

    log.info("Found Liturgy of St. Mark div2")
    paragraphs = _extract_paragraphs_from_div1(div2, "AlexLit.Mark")
    log.info("Extracted %d paragraphs from Liturgy of St. Mark", len(paragraphs))

    work = Work(
        work_id=f"mark-liturgy/{_WORK_SLUG}",
        source_id=SOURCE_ID,
        author=None,
        title="The Divine Liturgy of St. Mark",
        date_composed=300,
        date_range=(200, 500),
        date_confidence="uncertain",
        genre="liturgical",
        language="eng",
        tradition="greek",
        license="public_domain",
        provenance_url=f"https://ccel.org/ccel/s/schaff/{_ANF_VOL}.xml",
        edition="Ante-Nicene Fathers Vol. 7 (Roberts-Donaldson, 1886)",
        translation_of=None,
    )

    out_path.write_text(
        json.dumps({"work": work.model_dump(), "paragraphs": paragraphs}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("Wrote %s (%d paragraphs)", out_path, len(paragraphs))
    return [work]


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
