"""
Ingestor for the Didache (Teaching of the Twelve Apostles).

Source: CCEL Ante-Nicene Fathers Vol. 7 (Roberts-Donaldson, 1886)
        https://ccel.org/ccel/s/schaff/anf07.xml
License: Public domain
Genre: patristic  Language: eng  Tradition: greek

The Didache is one of the earliest surviving Christian documents outside the
New Testament, likely composed in Syria c. 50–120 CE. Its 16 chapters cover:
  - Chs. 1–6:  The "Two Ways" (ethical teaching), probably of Jewish origin
  - Chs. 7–10: Baptism, fasting, prayer, and the eucharist — among the oldest
                liturgical texts in Christianity
  - Chs. 11–15: Church order (prophets, bishops, deacons)
  - Ch. 16:    Eschatological warning

The ANF07 XML is shared with the ccel_anf, syriac_james, adai_mari, and
mark_liturgy ingestor caches.

Note: ccel_anf.py already ingests this text as ccel-anf/anf07/008.json
but with anonymous attribution and no date or tradition metadata. This dedicated
ingestor supersedes that entry with correct metadata.

Refs are ``Did.{chapter}.{verse}``: ANF prints the verse numbers inline, and
each chapter is cut at them (#122), as in the Greek. The editor's (Coxe's)
*Elucidations* that close the div2 are left out (#256), as the other CCEL
carve-outs leave out theirs: they are 19th-century commentary, not the Didache.
"""

from __future__ import annotations

import copy
import json
import logging
import re
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

from scripts.ingest._ccel_works import _EDITORIAL_TITLE_RE
from scripts.ingest._printed_verses import rechunk

log = logging.getLogger(__name__)

SOURCE_ID = "didache"
#: The Greek original in the corpus (Work.translation_of).
ORIGINAL = "first1k/tlg1311/tlg001/1st1K-grc1"
_ANF_VOL = "anf07"
_WORK_SLUG = "didache"


def _find_didache_div2(body: etree._Element) -> etree._Element | None:
    """Locate the Didache text <div2> within ANF07.

    The div1 "THE TEACHING OF THE TWELVE APOSTLES." has three div2 children:
    two introductory notices, then the actual text starting with Chapter I.
    """
    for div1 in body:
        if div1.tag is etree.Comment:
            continue
        if etree.QName(div1.tag).localname != "div1":
            continue
        head1 = (_get_head_text(div1) or "").lower()
        if "teaching" not in head1 or "apostles" not in head1:
            continue
        for div2 in div1:
            if div2.tag is etree.Comment:
                continue
            if etree.QName(div2.tag).localname != "div2":
                continue
            preview = (_element_inner_text(div2) or "")[:300].lower()
            if "chapter i" in preview and "two ways" in preview:
                return div2
    return None


def without_editorial(div2: etree._Element) -> etree._Element:
    """A copy of *div2* without its editorial child divs (the Elucidations, #256)."""
    div2 = copy.deepcopy(div2)
    for child in list(div2):
        if child.tag is etree.Comment or not isinstance(child.tag, str):
            continue
        if not etree.QName(child.tag).localname.startswith("div"):
            continue
        if _EDITORIAL_TITLE_RE.match(child.get("title", "")):
            log.info("Leaving out editorial div %s (%r)", child.get("id"), child.get("title"))
            div2.remove(child)
    return div2


#: The 16 chapters.
_CHAPTER_RE = re.compile(r"Did\.(\d+)")
_CHAPTERS = 16


def rechunk_chapters(paragraphs: list[dict[str, str]]) -> list[dict[str, str]]:
    """Cut each chapter ``Did.C`` at its printed verse numbers into ``Did.C.V`` (#122)."""
    def chapter(ref: str) -> str | None:
        m = _CHAPTER_RE.fullmatch(ref)
        return ref if m and int(m.group(1)) <= _CHAPTERS else None
    return rechunk(paragraphs, chapter, restart=True)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    out_dir = output_dir / SOURCE_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{_WORK_SLUG}.json"

    if out_path.exists() and not force:
        return [Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"])]

    anf_cache = output_dir / "ccel-anf"
    anf_cache.mkdir(parents=True, exist_ok=True)
    xml_path = download_volume(_ANF_VOL, anf_cache, force=force)

    tree = etree.parse(str(xml_path))
    body = _find_body(tree.getroot())
    if body is None:
        raise RuntimeError(f"No body element found in {_ANF_VOL}.xml")

    div2 = _find_didache_div2(body)
    if div2 is None:
        raise RuntimeError(
            "Didache text not found in ANF07. "
            "Expected a div2 under 'THE TEACHING OF THE TWELVE APOSTLES.' "
            "whose text includes 'Chapter I' and 'Two Ways'."
        )

    log.info("Found Didache div2")
    paragraphs = _extract_paragraphs_from_div1(without_editorial(div2), "Did")
    log.info("Extracted %d paragraphs from Didache", len(paragraphs))
    paragraphs = rechunk_chapters(paragraphs)

    work = Work(
        work_id=f"didache/{_WORK_SLUG}",
        source_id=SOURCE_ID,
        author=None,
        title="The Didache (Teaching of the Twelve Apostles)",
        date_composed=100,
        date_range=(50, 120),
        date_confidence="uncertain",
        genre="patristic",
        language="eng",
        tradition="greek",
        license="public_domain",
        provenance_url=f"https://ccel.org/ccel/s/schaff/{_ANF_VOL}.xml",
        edition="Ante-Nicene Fathers Vol. 7 (Roberts-Donaldson, 1886)",
        translation_of=ORIGINAL,
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
