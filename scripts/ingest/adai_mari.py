"""
Ingestor for the Liturgy of the Holy Apostles Adai and Mari (English translation).

Source: CCEL Ante-Nicene Fathers Vol. 7 (Roberts-Donaldson, 1886)
        https://ccel.org/ccel/s/schaff/anf07.xml
License: Public domain
Genre: liturgical  Language: eng  Tradition: syriac

The Liturgy of Adai and Mari (also called the Liturgy of the Blessed Apostles)
is the foundational eucharistic prayer of the East Syriac tradition. It is
among the oldest complete anaphoras in existence, with origins plausibly in the
2nd–3rd century Edessene church — predating the Council of Nicaea and the
development of the Western canon formulae. It was the liturgy of the Church of
Persia (Church of the East) and, historically, of the Thomas Christians of
Kerala before Portuguese contact.

ANF Vol. 7 contains Roberts-Donaldson's English translation under the title
"The Liturgy of the Blessed Apostles, Composed by St. Adæus and St. Maris,
Teachers of the Easterns." The ANF07 XML is shared with the ccel_anf ingestor
cache to avoid duplicate downloads.

Note: The same ANF07 volume also contains the Liturgy of St. Mark (Coptic/
Alexandrian tradition) and the Liturgy of St. James, ingested separately in
syriac_james.py.
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

SOURCE_ID = "liturgical/adai-mari"
_ANF_VOL = "anf07"
_WORK_SLUG = "liturgy-of-adai-and-mari"


def _find_adai_mari_div2(body: etree._Element) -> etree._Element | None:
    """Locate the Liturgy of Adai and Mari <div2> within ANF07.

    The Early Liturgies div1 contains several div2 blocks. The Adai and Mari
    liturgy is the one titled "Liturgy of the Blessed Apostles, Composed by
    St. Adæus and St. Maris, Teachers of the Easterns."
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
            if "adæus" in text_preview or "adaeus" in text_preview or (
                "blessed apostles" in text_preview and "maris" in text_preview
            ):
                return div2
    return None


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    out_dir = output_dir / SOURCE_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_WORK_SLUG}.json"

    if out_path.exists() and not force:
        return [Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"])]

    # Share the ANF07 download cache with the ccel_anf ingestor.
    anf_cache = output_dir / "patristic" / "ccel-anf"
    anf_cache.mkdir(parents=True, exist_ok=True)
    xml_path = download_volume(_ANF_VOL, anf_cache, force=force)

    tree = etree.parse(str(xml_path))
    body = _find_body(tree.getroot())
    if body is None:
        raise RuntimeError(f"No body element found in {_ANF_VOL}.xml")

    div2 = _find_adai_mari_div2(body)
    if div2 is None:
        raise RuntimeError(
            "Liturgy of Adai and Mari not found in ANF07. "
            "Expected a div2 under 'Early Liturgies.' whose text mentions "
            "'adæus' or 'blessed apostles' + 'maris'."
        )

    log.info("Found Liturgy of Adai and Mari div2")
    paragraphs = _extract_paragraphs_from_div1(div2, "SyrLit.AdaiMari")
    log.info("Extracted %d paragraphs from Liturgy of Adai and Mari", len(paragraphs))

    work = Work(
        work_id=f"adai-mari/{_WORK_SLUG}",
        source_id=SOURCE_ID,
        author=None,
        title="The Liturgy of the Holy Apostles Adai and Mari",
        date_composed=200,
        date_range=(150, 400),
        date_confidence="uncertain",
        genre="liturgical",
        language="eng",
        tradition="syriac",
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
