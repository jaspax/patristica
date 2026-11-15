"""
Ingestion module for the King James Version's 2 Esdras 3–14 (4 Ezra) (#355).

Source:  https://ebible.org/Scriptures/eng-kjv_usfm.zip (KJV with Apocrypha,
         1769 standard text)
Format:  USFM zip, one file per book
License: Public domain

Brenton's Septuagint (``brenton-eng``) covers every deuterocanonical book the
corpus has except 4 Ezra, which is not in the Septuagint. The KJV's 2 Esdras
gives it an English version: chapters 3–14 are 4 Ezra, translated (through the
Geneva Bible) from the Latin, so the work is an approximate English of the
Syriac and Ge'ez 4 Ezra (``pta-peshitta/4esr``, ``gez/4esr``), which it joins
by its book key. Chapters 1–2 and 15–16 (5 and 6 Ezra, Christian additions
extant in Latin only) are left out: they are other works, with no witness in
the corpus.

The KJV, like the Latin manuscripts it follows, lacks the "missing fragment"
(4 Ezra 7:36–105 in modern numbering), so its 7:36–70 are 7:106–140 of the
Syriac. Refs keep the KJV's numbering; passage alignment pairs them by content.
"""

from __future__ import annotations

import json
import logging
import zipfile
from pathlib import Path

from patristica.models import Work
from scripts.ingest._common import download_file
from scripts.ingest.brenton_eng import parse_brenton_usfm

log = logging.getLogger(__name__)

SOURCE_ID = "kjv-apocrypha-eng"
ZIP_URL = "https://ebible.org/Scriptures/eng-kjv_usfm.zip"
ZIP_NAME = "eng-kjv_usfm.zip"
ENTRY = "58-2ESeng-kjv.usfm"
BOOK = "4Esr"
CHAPTERS = range(3, 15)  # 2 Esdras 3–14 = 4 Ezra

EDITION = (
    "King James Version (1611), 2 Esdras 3–14, in the 1769 standard text; translated from "
    "the Latin (Vulgate appendix, 4 Esdras), not from the lost Greek; eBible.org (eng-kjv)"
)


def make_work() -> Work:
    return Work(
        work_id=f"{SOURCE_ID}/{BOOK.lower()}",
        source_id=SOURCE_ID,
        title="4 Ezra (2 Esdras 3–14)",
        author=None,
        date_composed=100,
        date_range=(90, 120),
        date_confidence="approximate",
        genre="apocrypha",
        language="eng",
        tradition=None,
        license="public_domain",
        provenance_url=ZIP_URL,
        edition=EDITION,
    )


def four_ezra_units(usfm: str) -> list[dict]:
    """The verses of 2 Esdras 3–14 as 4 Ezra (``4Esr.C.V``)."""
    units = parse_brenton_usfm(usfm, BOOK)
    return [u for u in units if int(u["ref"].split(".")[1]) in CHAPTERS]


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download the KJV with Apocrypha and write 4 Ezra."""
    source_dir = output_dir / SOURCE_ID
    source_dir.mkdir(parents=True, exist_ok=True)
    out_file = source_dir / f"{BOOK}.json"
    if out_file.exists() and not force:
        return [Work(**json.loads(out_file.read_text(encoding="utf-8"))["work"])]

    zip_path = output_dir / "_zips" / ZIP_NAME
    download_file(ZIP_URL, zip_path, force=force)
    with zipfile.ZipFile(zip_path) as zf:
        units = four_ezra_units(zf.read(ENTRY).decode("utf-8"))
    if not units:
        raise ValueError(f"{SOURCE_ID}: no verses of 2 Esdras 3–14 in {ENTRY}")
    work = make_work()
    record = {"work": work.model_dump(), "verses": units}
    out_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("%s: %d verses", SOURCE_ID, len(units))
    return [work]


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
