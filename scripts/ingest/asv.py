"""
Ingestion module for the American Standard Version (ASV, 1901).

Source:  https://github.com/scrollmapper/bible_databases  (formats/csv/ASV.csv)
License: Public domain (copyright expired)

The CSV prints a Psalm's title at the start of verse 1. The ASV doesn't number
titles, so the ingestor moves each title into its own unit ``Ps.N.0`` (shown as
a heading by the reader; ``patristica.versification`` maps it onto the org
title verse) and keeps verse 1 to the canonical text (#220).
"""

from __future__ import annotations

import csv
import re
from functools import cache
from pathlib import Path

from patristica.models import Work
from scripts.ingest._scrollmapper import ingest_scrollmapper

SOURCE_ID = "asv"

_TITLE_TABLE = Path(__file__).parent / "data" / "asv_psalm_titles.csv"

#: A title is a run of sentences, each opening with one of these words.
_TITLE_SENTENCE = re.compile(
    r"^(?:For the Chief Musician|A Psalm|A Song|A Prayer|Maschil|Michtam|Shiggaion)\b"
)
_SENTENCE_END = re.compile(r"(?<=[.?])\s+")


@cache
def _title_table() -> dict[str, str]:
    """Titles the rule can't find (``scripts/ingest/data/asv_psalm_titles.csv``), by ref."""
    with _TITLE_TABLE.open(encoding="utf-8") as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        return {row["ref"]: row["title"] for row in rows}


def split_psalm_title(ref: str, text: str) -> tuple[str | None, str]:
    """Split a Psalm's verse 1 into (title or None, verse text).

    The title is the longest run of leading sentences that each open with a
    title word (``For the Chief Musician``, ``A Psalm``, ``Maschil``, …), or the
    curated prefix from the title table. Raises ``ValueError`` when the table's
    title doesn't start the verse, or when nothing would be left of verse 1.
    """
    table = _title_table()
    if ref in table:
        title = table[ref]
        if not text.startswith(title):
            raise ValueError(f"ASV {ref}: the curated title is not the start of the verse")
        rest = text[len(title):].strip()
    else:
        sentences = _SENTENCE_END.split(text)
        n = 0
        while n < len(sentences) and _TITLE_SENTENCE.match(sentences[n]):
            n += 1
        if n == 0:
            return None, text
        title = " ".join(sentences[:n])
        rest = " ".join(sentences[n:]).strip()
    if not rest:
        raise ValueError(f"ASV {ref}: the title would take the whole verse")
    return title.strip(), rest


def split_psalm_titles(book: str, verses: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Give every titled psalm a ``Ps.N.0`` unit before verse 1 (other books unchanged)."""
    if book != "Ps":
        return verses
    out: list[tuple[str, str]] = []
    for ref, text in verses:
        if ref.endswith(".1"):
            title, text = split_psalm_title(ref, text)
            if title is not None:
                out.append((ref[:-1] + "0", title))
        out.append((ref, text))
    return out


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download and parse the American Standard Version (66 books)."""
    return ingest_scrollmapper(
        output_dir=output_dir,
        translation="ASV",
        source_id=SOURCE_ID,
        language="eng",
        license_="public_domain",
        edition="American Standard Version (1901)",
        tradition=None,
        force=force,
        transform=split_psalm_titles,
    )


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
