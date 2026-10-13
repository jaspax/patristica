"""
Ingestor for the Greek Septuagint (LXX) from the Patristic Text Archive (PTA).

Source: pta9999 Bible group in github.com/PatristicTextArchive/pta_data
        (already cloned by ``pta.py`` into ``data/raw/pta/``)
Language: Greek (``grc``)
License: CC-BY-SA 4.0 (OT); CC-BY 4.0 (NT, pta063–pta089)
Edition: Rahlfs 1935, Septuaginta (Stuttgart: Württembergische Bibelanstalt)

Coverage
--------
80 books — the full LXX OT including the Deuterocanon (Judith, Tobit,
1–4 Maccabees, Wisdom, Sirach, Baruch, Epistle of Jeremiah, 1 Esdras,
Odes, Psalms of Solomon) plus the NT (27 books).

Textual variants
----------------
Five books exist in two distinct Greek textual traditions:

    Judges      grc1 = Codex Alexandrinus   grc2 = Codex Vaticanus
    Tobit       grc1 = Codex Vaticanus/Al.  grc2 = Codex Sinaiticus
    Susanna     grc1 = Theodotionis versio   grc2 = translatio Graeca (OG)
    Daniel      grc1 = Theodotionis versio   grc2 = translatio Graeca (OG)
    Bel et Dr.  grc1 = Theodotionis versio   grc2 = translatio Graeca (OG)

Each version is ingested as a separate Work with a distinct OSIS abbreviation.

Relation to ``lxx-rahlfs``
-------------------------------------
``lxx-rahlfs`` (eliranwong repo) covers only 33 books from a word-list CSV.
This source provides the full 80-book Rahlfs text including the Deuterocanon.
The two sources overlap for the 33 books lxx-rahlfs already covers; both are
retained as separate works so ``link_translations.py`` can pair them by ref.

The PTA repo must already be cloned (``pta.py`` handles the clone).  This
ingestor does NOT re-clone; it only reads from the existing checkout.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from lxml import etree
from tqdm import tqdm

from patristica.models import DateConfidence, Work
from scripts.ingest._common import slugify_ref
from scripts.ingest._scripture_meta import BOOK_DATES

log = logging.getLogger(__name__)

SOURCE_ID = "pta-lxx"

_TEI = "http://www.tei-c.org/ns/1.0"

# ---------------------------------------------------------------------------
# Book map: (pta_work_id, grc_version, osis_abbrev, title, edition_note)
# ---------------------------------------------------------------------------
# For books with a single Greek manuscript tradition, grc_version = "grc1".
# For books with two traditions, both are listed with distinct osis_abbrev.

_BOOK_MAP: list[tuple[str, str, str, str, str]] = [
    # pta_work  version   osis_abbrev      title                               edition
    ("pta001", "grc1", "Gen",        "Genesis",                              "Rahlfs 1935"),
    ("pta002", "grc1", "Exod",       "Exodus",                               "Rahlfs 1935"),
    ("pta003", "grc1", "Lev",        "Leviticus",                            "Rahlfs 1935"),
    ("pta004", "grc1", "Num",        "Numbers",                              "Rahlfs 1935"),
    ("pta005", "grc1", "Deut",       "Deuteronomy",                          "Rahlfs 1935"),
    ("pta006", "grc1", "Josh",       "Joshua",                               "Rahlfs 1935"),
    ("pta007", "grc1", "Judg",       "Judges (Codex Alexandrinus)",          "Codex Alexandrinus"),
    ("pta007", "grc2", "JudgVat",    "Judges (Codex Vaticanus)",             "Codex Vaticanus"),
    ("pta008", "grc1", "Ruth",       "Ruth",                                 "Rahlfs 1935"),
    ("pta009", "grc1", "1Sam",       "1 Samuel (Regnorum I)",                "Rahlfs 1935"),
    ("pta010", "grc1", "2Sam",       "2 Samuel (Regnorum II)",               "Rahlfs 1935"),
    ("pta011", "grc1", "1Kgs",       "1 Kings (Regnorum III)",               "Rahlfs 1935"),
    ("pta012", "grc1", "2Kgs",       "2 Kings (Regnorum IV)",                "Rahlfs 1935"),
    ("pta013", "grc1", "1Chr",       "1 Chronicles (Paralipomenon I)",       "Rahlfs 1935"),
    ("pta014", "grc1", "2Chr",       "2 Chronicles (Paralipomenon II)",      "Rahlfs 1935"),
    # pta016 in Greek = 1 Esdras (liber apocryphus) — differs from Hebrew Ezra
    ("pta016", "grc1", "1Esr",       "1 Esdras (Esdrae I apocryphus)",       "Rahlfs 1935"),
    # pta017 in Greek = 2 Esdras = Ezra + Nehemiah combined
    ("pta017", "grc1", "EzraNeh",    "Ezra–Nehemiah (Esdrae II)",            "Rahlfs 1935"),
    ("pta020", "grc1", "Esth",       "Esther",                               "Rahlfs 1935"),
    ("pta021", "grc1", "Jdt",        "Judith",                               "Rahlfs 1935"),
    ("pta022", "grc1", "TobVatAl",   "Tobit (Codex Vaticanus/Alexandrinus)", "Codex Vaticanus/Alexandrinus"),
    ("pta022", "grc2", "TobSin",     "Tobit (Codex Sinaiticus)",             "Codex Sinaiticus"),
    ("pta023", "grc1", "1Macc",      "1 Maccabees",                          "Rahlfs 1935"),
    ("pta024", "grc1", "2Macc",      "2 Maccabees",                          "Rahlfs 1935"),
    ("pta025", "grc1", "3Macc",      "3 Maccabees",                          "Rahlfs 1935"),
    ("pta026", "grc1", "4Macc",      "4 Maccabees",                          "Rahlfs 1935"),
    ("pta031", "grc1", "Ps",         "Psalms",                               "Rahlfs 1935"),
    ("pta032", "grc1", "Odes",       "Odes",                                 "Rahlfs 1935"),
    ("pta033", "grc1", "Prov",       "Proverbs",                             "Rahlfs 1935"),
    ("pta034", "grc1", "Eccl",       "Ecclesiastes",                         "Rahlfs 1935"),
    ("pta035", "grc1", "Song",       "Song of Songs",                        "Rahlfs 1935"),
    ("pta036", "grc1", "Job",        "Job",                                  "Rahlfs 1935"),
    ("pta037", "grc1", "Wis",        "Wisdom of Solomon",                    "Rahlfs 1935"),
    ("pta038", "grc1", "Sir",        "Sirach (Ecclesiasticus)",              "Rahlfs 1935"),
    ("pta039", "grc1", "PsSol",      "Psalms of Solomon",                    "Rahlfs 1935"),
    ("pta040", "grc1", "Hos",        "Hosea",                                "Rahlfs 1935"),
    ("pta041", "grc1", "Amos",       "Amos",                                 "Rahlfs 1935"),
    ("pta042", "grc1", "Mic",        "Micah",                                "Rahlfs 1935"),
    ("pta043", "grc1", "Joel",       "Joel",                                 "Rahlfs 1935"),
    ("pta044", "grc1", "Obad",       "Obadiah",                              "Rahlfs 1935"),
    ("pta045", "grc1", "Jonah",      "Jonah",                                "Rahlfs 1935"),
    ("pta046", "grc1", "Nah",        "Nahum",                                "Rahlfs 1935"),
    ("pta047", "grc1", "Hab",        "Habakkuk",                             "Rahlfs 1935"),
    ("pta048", "grc1", "Zeph",       "Zephaniah",                            "Rahlfs 1935"),
    ("pta049", "grc1", "Hag",        "Haggai",                               "Rahlfs 1935"),
    ("pta050", "grc1", "Zech",       "Zechariah",                            "Rahlfs 1935"),
    ("pta051", "grc1", "Mal",        "Malachi",                              "Rahlfs 1935"),
    ("pta052", "grc1", "Isa",        "Isaiah",                               "Rahlfs 1935"),
    ("pta053", "grc1", "Jer",        "Jeremiah",                             "Rahlfs 1935"),
    ("pta054", "grc1", "Bar",        "Baruch",                               "Rahlfs 1935"),
    ("pta055", "grc1", "Lam",        "Lamentations (Threni)",                "Rahlfs 1935"),
    ("pta056", "grc1", "EpJer",      "Epistle of Jeremiah",                  "Rahlfs 1935"),
    ("pta059", "grc1", "Ezek",       "Ezekiel",                              "Rahlfs 1935"),
    # Susanna: two Greek textual traditions
    ("pta060", "grc1", "SusThdt",    "Susanna (Theodotion)",                 "Theodotionis versio"),
    ("pta060", "grc2", "Sus",        "Susanna (Old Greek)",                  "translatio Graeca (OG)"),
    # Daniel: two Greek textual traditions
    ("pta061", "grc1", "DanThdt",    "Daniel (Theodotion)",                  "Theodotionis versio"),
    ("pta061", "grc2", "Dan",        "Daniel (Old Greek)",                   "translatio Graeca (OG)"),
    # Bel and the Dragon: two Greek textual traditions
    ("pta062", "grc1", "BelDrThdt",  "Bel and the Dragon (Theodotion)",      "Theodotionis versio"),
    ("pta062", "grc2", "BelDr",      "Bel and the Dragon (Old Greek)",       "translatio Graeca (OG)"),
    # NT (CC-BY 4.0)
    ("pta063", "grc1", "Matt",       "Matthew",                              "Rahlfs 1935 NT"),
    ("pta064", "grc1", "Mark",       "Mark",                                 "Rahlfs 1935 NT"),
    ("pta065", "grc1", "Luke",       "Luke",                                 "Rahlfs 1935 NT"),
    ("pta066", "grc1", "John",       "John",                                 "Rahlfs 1935 NT"),
    ("pta067", "grc1", "Acts",       "Acts of the Apostles",                 "Rahlfs 1935 NT"),
    ("pta068", "grc1", "Rom",        "Romans",                               "Rahlfs 1935 NT"),
    ("pta069", "grc1", "1Cor",       "1 Corinthians",                        "Rahlfs 1935 NT"),
    ("pta070", "grc1", "2Cor",       "2 Corinthians",                        "Rahlfs 1935 NT"),
    ("pta071", "grc1", "Gal",        "Galatians",                            "Rahlfs 1935 NT"),
    ("pta072", "grc1", "Eph",        "Ephesians",                            "Rahlfs 1935 NT"),
    ("pta073", "grc1", "Phil",       "Philippians",                          "Rahlfs 1935 NT"),
    ("pta074", "grc1", "Col",        "Colossians",                           "Rahlfs 1935 NT"),
    ("pta075", "grc1", "1Thess",     "1 Thessalonians",                      "Rahlfs 1935 NT"),
    ("pta076", "grc1", "2Thess",     "2 Thessalonians",                      "Rahlfs 1935 NT"),
    ("pta077", "grc1", "1Tim",       "1 Timothy",                            "Rahlfs 1935 NT"),
    ("pta078", "grc1", "2Tim",       "2 Timothy",                            "Rahlfs 1935 NT"),
    ("pta079", "grc1", "Titus",      "Titus",                                "Rahlfs 1935 NT"),
    ("pta080", "grc1", "Phlm",       "Philemon",                             "Rahlfs 1935 NT"),
    ("pta081", "grc1", "Heb",        "Hebrews",                              "Rahlfs 1935 NT"),
    ("pta082", "grc1", "Jas",        "James",                                "Rahlfs 1935 NT"),
    ("pta083", "grc1", "1Pet",       "1 Peter",                              "Rahlfs 1935 NT"),
    ("pta084", "grc1", "2Pet",       "2 Peter",                              "Rahlfs 1935 NT"),
    ("pta085", "grc1", "1John",      "1 John",                               "Rahlfs 1935 NT"),
    ("pta086", "grc1", "2John",      "2 John",                               "Rahlfs 1935 NT"),
    ("pta087", "grc1", "3John",      "3 John",                               "Rahlfs 1935 NT"),
    ("pta088", "grc1", "Jude",       "Jude",                                 "Rahlfs 1935 NT"),
    ("pta089", "grc1", "Rev",        "Revelation",                           "Rahlfs 1935 NT"),
]

# NT pta work IDs (CC-BY 4.0); OT is CC-BY-SA 4.0
_NT_WORK_IDS = {f"pta{n:03d}" for n in range(63, 90)}


def _extract_license(root: etree._Element, pta_work_id: str) -> str:
    """Extract license from TEI availability element."""
    ns = {"tei": _TEI}
    lic_el = root.find(".//tei:teiHeader//tei:availability/tei:licence", ns)
    if lic_el is not None:
        target = lic_el.get("target", "")
        if "by-nc" in target:
            return "cc-by-nc-4.0"
        if "by-sa" in target:
            return "cc-by-sa-4.0"
        if "by" in target:
            return "cc-by-4.0"
    # Default: NT = CC-BY 4.0, OT = CC-BY-SA 4.0
    return "cc-by-4.0" if pta_work_id in _NT_WORK_IDS else "cc-by-sa-4.0"


def _extract_verses(
    root: etree._Element,
    book_abbrev: str,
) -> list[dict[str, str]]:
    """Extract all verses from a LXX TEI file.

    Returns list of ``{"ref": "Gen.1.1", "text": "…"}`` dicts.
    """
    ns = {"tei": _TEI}
    edition_div = root.find(".//tei:text/tei:body/tei:div[@type='edition']", ns)
    if edition_div is None:
        log.debug("No edition div found for %s", book_abbrev)
        return []

    verses: list[dict[str, str]] = []

    def _collect_verse(verse_div: etree._Element, ch_n: str) -> None:
        vs_n = verse_div.get("n", "")
        if not vs_n:
            return
        text_parts: list[str] = []
        for el in verse_div:
            tag = etree.QName(el.tag).localname
            if tag in ("p", "ab"):
                text = "".join(el.itertext()).strip()
                if text:
                    text_parts.append(text)
        text = re.sub(r"\s+", " ", " ".join(text_parts)).strip()
        if text:
            ref = slugify_ref(f"{book_abbrev}.{ch_n}.{vs_n}")
            verses.append({"ref": ref, "text": text})

    # Check whether verses are wrapped in chapters or sit directly under the edition div.
    # Single-chapter books (Obadiah, Jude, Susanna, etc.) use direct verse children.
    chapter_divs = edition_div.findall(
        "tei:div[@type='textpart'][@subtype='chapter']", ns
    )
    if chapter_divs:
        for chapter_div in chapter_divs:
            ch_n = chapter_div.get("n", "")
            if not ch_n:
                continue
            for verse_div in chapter_div.findall(
                "tei:div[@type='textpart'][@subtype='verse']", ns
            ):
                _collect_verse(verse_div, ch_n)
    else:
        # Direct verse children — treat as chapter 1
        for verse_div in edition_div.findall(
            "tei:div[@type='textpart'][@subtype='verse']", ns
        ):
            _collect_verse(verse_div, "1")

    return verses


def _book_dates(osis: str) -> tuple[int | None, tuple[int, int] | None, DateConfidence]:
    """Look up composition date from _scripture_meta.BOOK_DATES."""
    # Strip variant suffixes for the lookup (e.g. "JudgVat" → "Judg" not in BOOK_DATES,
    # try the base key or fall back to uncertain)
    entry = BOOK_DATES.get(osis)
    if entry is None:
        # Try stripping trailing non-alpha suffix (e.g. "JudgVat" → try "Judg")
        base = re.sub(r"(Vat|Al|Sin|Thdt|OG)$", "", osis)
        entry = BOOK_DATES.get(base)
    if entry is None:
        return None, None, "uncertain"
    return entry["date_composed"], entry["date_range"], entry["date_confidence"]


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Ingest the Greek LXX (Rahlfs 1935) from the PTA git clone.

    Reads from ``data/raw/pta/data/pta9999/``.
    Writes to ``output_dir/pta-lxx/{BookAbbrev}.json``.

    The PTA repo must already be cloned (``pta.py`` handles the clone).
    """
    repo_dir = output_dir / "pta"
    pta9999_dir = repo_dir / "data" / "pta9999"

    if not pta9999_dir.exists():
        raise FileNotFoundError(
            f"PTA repo not found at {repo_dir}. "
            "Run the pta ingestor first to clone the repo."
        )

    out_base = output_dir / "pta-lxx"
    out_base.mkdir(parents=True, exist_ok=True)

    works: list[Work] = []
    skipped = 0

    for pta_work_id, grc_version, osis_abbrev, title, edition in tqdm(
        _BOOK_MAP, desc="LXX (PTA)"
    ):
        work_dir = pta9999_dir / pta_work_id
        version_num = grc_version  # e.g. "grc1"

        # Find the target Greek file
        pattern = f"*pta-{version_num}.xml"
        grc_files = [
            f for f in work_dir.glob(pattern)
            if "Bibex" not in f.name and "Ms" not in f.name
        ]
        if not grc_files:
            log.debug("No Greek file %s in %s — skipping", pattern, work_dir)
            skipped += 1
            continue

        xml_path = grc_files[0]
        out_path = out_base / f"{osis_abbrev}.json"

        if out_path.exists() and not force:
            try:
                saved = json.loads(out_path.read_text(encoding="utf-8"))
                works.append(Work(**saved["work"]))
            except Exception:
                pass
            continue

        try:
            root = etree.parse(str(xml_path)).getroot()
        except etree.XMLSyntaxError as exc:
            log.warning("XML error in %s: %s", xml_path, exc)
            skipped += 1
            continue

        verses = _extract_verses(root, osis_abbrev)
        if not verses:
            log.debug("No verses extracted from %s — skipping", xml_path)
            skipped += 1
            continue

        license_val = _extract_license(root, pta_work_id)
        date_composed, date_range, date_confidence = _book_dates(osis_abbrev)

        work = Work(
            work_id=f"{SOURCE_ID}/{osis_abbrev.lower()}",
            source_id=SOURCE_ID,
            author=None,
            title=f"{title} (LXX)",
            date_composed=date_composed,
            date_range=date_range,
            date_confidence=date_confidence,
            genre="scripture",
            language="grc",
            tradition="greek",
            license=license_val,
            provenance_url=(
                f"https://github.com/PatristicTextArchive/pta_data/tree/main"
                f"/data/pta9999/{pta_work_id}"
            ),
            edition=f"Rahlfs 1935 — {edition}",
            translation_of=None,
        )

        payload = {"work": work.model_dump(), "verses": verses}
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        works.append(work)

    log.info(
        "LXX (PTA) ingestion complete: %d books written, %d skipped",
        len(works),
        skipped,
    )
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
