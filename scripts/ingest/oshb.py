"""
Ingestion module for the Open Scriptures Hebrew Bible (morphhb).

Source:  https://github.com/openscriptures/morphhb
Format:  OSIS XML per book, one file per OT book in wlc/
License: CC BY 4.0 (OSHB additions); base WLC text is Public Domain
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from pathlib import Path

from lxml import etree
from tqdm import tqdm

from patristica.models import Work
from scripts.ingest._common import download_file
from scripts.ingest._scripture_meta import (
    BOOK_DATES,
    BOOK_TITLE,
    OT_BOOKS,
    book_work_id,
)

log = logging.getLogger(__name__)

SOURCE_ID = "oshb"
REPO_ZIP_URL = "https://github.com/openscriptures/morphhb/archive/refs/heads/master.zip"

_OSIS_NS = "http://www.bibletechnologies.net/2003/OSIS/namespace"
_OSIS = f"{{{_OSIS_NS}}}"

# morphhb marks morpheme boundaries (prefix/stem/suffix) inside <w> text with
# "/", e.g. "בְּ/רֵאשִׁ֖ית".  The WLC text itself never contains a slash.
_MORPHEME_SEPARATOR = "/"
_MAQQEF = "\u05be"


def _word_text(w_el: etree._Element) -> str:
    """Return the surface text of a morphhb ``<w>`` element.

    Morpheme separators are removed (morphemes are joined with no space), and
    text in nested ``<seg>`` children (large/small/suspended letters such as
    the large ע and ד of Deut 6:4) is kept.
    """
    return "".join(w_el.itertext()).replace(_MORPHEME_SEPARATOR, "").strip()


def _is_ketiv(el: etree._Element) -> bool:
    """True for a ketiv word or the maqqef joining two ketiv words.

    morphhb marks the written-but-not-read consonants as ``<w type="x-ketiv">``
    and a maqqef inside a multi-word ketiv as ``<seg type="x-maqqef"
    subType="x-ketiv">`` (1 Kgs 17:15).
    """
    return el.get("type") == "x-ketiv" or el.get("subType") == "x-ketiv"


def _qere_children(note: etree._Element) -> list[etree._Element] | None:
    """Return the words and segs of a ketiv/qere note's qere, else None.

    ``None`` means *note* is not a qere note (an editorial note, an accent
    alternative, …).  An empty list is a ketiv without qere (*ketiv we-lo
    qere*, e.g. 2 Kgs 5:18 ``נא``): the ketiv is written but not read.
    """
    if note.get("type") != "variant":
        return None
    rdgs = [r for r in note if etree.QName(r.tag).localname == "rdg" and r.get("type") == "x-qere"]
    if not rdgs:
        return None
    return [child for rdg in rdgs for child in rdg]


def _parse_oshb_xml(xml_bytes: bytes) -> list[tuple[str, str]]:
    """Return list of (osisID, verse_text) from a morphhb OSIS XML book file.

    The morphhb XML stores each word as a ``<w>`` child of ``<verse>``.  This
    function reconstructs verse text by joining word tokens, stripping morpheme
    separators, handling maqqef connectors and discarding verse-end markers
    (sof-pasuq).

    The running text is the text as read (#55): every ketiv (``<w
    type="x-ketiv">``, bare consonants) is replaced by the pointed qere of the
    ``<note type="variant"><rdg type="x-qere">`` that follows it.  A qere with no
    ketiv (*qere we-lo ketiv*, 2 Sam 8:3 ``פְּרָֽת``) is read in place, and a ketiv
    with an empty qere (*ketiv we-lo qere*) is left out, together with a maqqef
    that bound it to the word before.  The ketiv itself is not kept: the raw
    format has no place for editorial readings yet (#236).  Qere perpetuum
    (the divine name) has no markup and stays as the WLC points it.

    A maqqef (``־``) binds the words on both sides into one prosodic word, so
    it is written with no space on either side: ``עַל־הָאָ֖רֶץ``.  Elements
    skipped from the running text (a ketiv, an editorial ``<note>``) do not
    break the binding.  Paseq (``׀``) stays a separate, space-delimited token.
    """
    root = etree.fromstring(xml_bytes)
    verses: list[tuple[str, str]] = []

    for verse_el in root.iter(f"{_OSIS}verse"):
        osis_id = verse_el.get("osisID", "").strip()
        if not osis_id:
            continue

        tokens: list[str] = []
        after_maqqef = False  # the next token attaches to tokens[-1]

        def add(el: etree._Element) -> None:
            nonlocal after_maqqef
            local = etree.QName(el.tag).localname
            token = ""
            is_maqqef = False

            if local == "w":
                token = _word_text(el)
            elif local == "seg":
                seg_type = el.get("type", "")
                if seg_type != "x-sof-pasuq":  # omit end-of-verse marker
                    token = (el.text or "").strip()
                    is_maqqef = seg_type == "x-maqqef"

            if not token:
                return
            if (is_maqqef or after_maqqef) and tokens:
                tokens[-1] += token
            else:
                tokens.append(token)
            after_maqqef = is_maqqef

        for child in verse_el:
            if _is_ketiv(child):
                continue  # replaced by the qere of the note that follows
            if etree.QName(child.tag).localname == "note":
                qere = _qere_children(child)
                if qere is None:
                    continue  # editorial note: skipped (a maqqef binds across it)
                if not qere and after_maqqef and tokens:
                    # ketiv we-lo qere after a maqqef: nothing is read, so the
                    # maqqef binds nothing.
                    tokens[-1] = tokens[-1].removesuffix(_MAQQEF)
                    after_maqqef = False
                for el in qere:
                    add(el)
                continue
            add(child)

        text = " ".join(tokens)
        if text:
            verses.append((osis_id, text))

    return verses


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download and parse the Open Scriptures Hebrew Bible (39 OT books)."""
    source_dir = output_dir / SOURCE_ID
    source_dir.mkdir(parents=True, exist_ok=True)

    zip_dest = output_dir / "_zips" / "morphhb-master.zip"
    zip_dest.parent.mkdir(parents=True, exist_ok=True)
    download_file(REPO_ZIP_URL, zip_dest, force=force)

    works: list[Work] = []

    with zipfile.ZipFile(zip_dest) as zf:
        # Detect the top-level prefix (e.g. "morphhb-master/")
        prefix = next(
            (n for n in zf.namelist() if n.endswith("/")), ""
        ).split("/")[0]

        for book_abbr in tqdm(OT_BOOKS, desc="OSHB"):
            out_file = source_dir / f"{book_abbr}.json"

            if out_file.exists() and not force:
                with out_file.open(encoding="utf-8") as f:
                    data = json.load(f)
                works.append(Work(**data["work"]))
                continue

            xml_entry = f"{prefix}/wlc/{book_abbr}.xml"
            try:
                xml_bytes = zf.read(xml_entry)
            except KeyError:
                log.warning("Not found in archive: %s", xml_entry)
                continue

            verses = _parse_oshb_xml(xml_bytes)
            if not verses:
                log.warning("No verses extracted for %s", book_abbr)
                continue

            dates = BOOK_DATES.get(book_abbr, {})
            work = Work(
                work_id=book_work_id(SOURCE_ID, book_abbr),
                source_id=SOURCE_ID,
                title=BOOK_TITLE[book_abbr],
                author=None,
                date_composed=dates.get("date_composed"),
                date_range=dates.get("date_range"),
                date_confidence=dates.get("date_confidence", "uncertain"),
                genre="scripture",
                language="hbo",
                tradition=None,
                license="cc-by-4.0",
                provenance_url="https://github.com/openscriptures/morphhb",
                edition="Open Scriptures Hebrew Bible (morphhb), Westminster Leningrad Codex",
            )

            record = {
                "work": work.model_dump(),
                "verses": [{"ref": ref, "text": text} for ref, text in verses],
            }
            out_file.write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log.info("OSHB %s: %d verses → %s", book_abbr, len(verses), out_file)
            works.append(work)

    log.info("OSHB ingestion complete: %d books", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
