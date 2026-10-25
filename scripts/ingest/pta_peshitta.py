"""
Ingestor for the Syriac Peshitta from the Patristic Text Archive (PTA).

Source: pta9999 Bible group in github.com/PatristicTextArchive/pta_data
        (already cloned by ``pta.py`` into ``data/raw/pta/``)
Language: Syriac (``syc``)
Format: TEI P5 XML with verse-level structure:
    <div type="textpart" subtype="chapter" n="1">
        <div type="textpart" subtype="verse" n="1">
            <p>Syriac text…</p>
        </div>
    </div>

License:
    NT (pta063–pta089): CC-BY 4.0 (Digital Syriac Corpus / Syriaca.org)
    OT (pta001–pta062): CC-BY-NC 4.0 (ETCBC/peshitta, Zenodo 2018)

Coverage:
    85 books — the full Peshitta OT + NT plus several books present only in
    the Syriac tradition: Prayer of Manasseh (B), 3 Esdras, 4 Esdras,
    Letter of Baruch, Apocalypse of Baruch (2 Baruch), Psalms of Solomon.

The PTA repo must already exist at ``data/raw/pta/``
(cloned by the ``pta.py`` ingestor or manually).  This ingestor does NOT
re-clone; it only reads from the existing checkout.

OT word breaks (#60):
    PTA converted the OT from ETCBC/peshitta, whose plain text wraps each
    verse at about 70 characters, always between words. The conversion
    dropped those line breaks instead of turning them into spaces, so about
    half of the OT verses run two words together at each wrap
    (``ܐܢܫܐܘܡܢ`` for ``ܐܢܫܐ ܘܡܢ``, Jer 33:10). The ingestor downloads the
    ETCBC plain text at a pinned commit (``data/raw/_cache/etcbc-peshitta/``)
    and takes its word breaks for a verse only when its letters are exactly
    PTA's. A verse that differs otherwise, or that ETCBC lacks, keeps PTA's
    text and is logged at ERROR.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from lxml import etree
from tqdm import tqdm

from patristica.models import DateConfidence, Work
from scripts.ingest._common import download_file, slugify_ref
from scripts.ingest._scripture_meta import BOOK_DATES

log = logging.getLogger(__name__)

SOURCE_ID = "pta-peshitta"

_TEI = "http://www.tei-c.org/ns/1.0"

# ---------------------------------------------------------------------------
# PTA work ID → OSIS book abbreviation + metadata
# ---------------------------------------------------------------------------

# (pta_work_id, osis_abbrev, full_title)
# Books present only in the Syriac canon use non-standard abbreviations.
_BOOK_MAP: list[tuple[str, str, str]] = [
    ("pta001",  "Gen",      "Genesis"),
    ("pta002",  "Exod",     "Exodus"),
    ("pta003",  "Lev",      "Leviticus"),
    ("pta004",  "Num",      "Numbers"),
    ("pta005",  "Deut",     "Deuteronomy"),
    ("pta006",  "Josh",     "Joshua"),
    ("pta007",  "Judg",     "Judges"),
    ("pta008",  "Ruth",     "Ruth"),
    ("pta009",  "1Sam",     "1 Samuel"),
    ("pta010",  "2Sam",     "2 Samuel"),
    ("pta011",  "1Kgs",     "1 Kings"),
    ("pta012",  "2Kgs",     "2 Kings"),
    ("pta013",  "1Chr",     "1 Chronicles"),
    ("pta014",  "2Chr",     "2 Chronicles"),
    ("pta015",  "PrMan",    "Prayer of Manasseh"),
    ("pta016",  "Ezra",     "Ezra"),
    ("pta017",  "Neh",      "Nehemiah"),
    ("pta018",  "3Esr",     "3 Esdras"),
    ("pta019",  "4Esr",     "4 Esdras"),
    ("pta020",  "Esth",     "Esther"),
    ("pta021",  "Jdt",      "Judith"),
    ("pta022",  "Tob",      "Tobit"),
    ("pta023",  "1Macc",    "1 Maccabees"),
    ("pta024",  "2Macc",    "2 Maccabees"),
    ("pta025",  "3Macc",    "3 Maccabees"),
    ("pta026",  "4Macc",    "4 Maccabees"),
    ("pta031",  "Ps",       "Psalms"),
    ("pta032",  "Odes",     "Odes"),
    ("pta033",  "Prov",     "Proverbs"),
    ("pta034",  "Eccl",     "Ecclesiastes"),
    ("pta035",  "Song",     "Song of Songs"),
    ("pta036",  "Job",      "Job"),
    ("pta037",  "Wis",      "Wisdom of Solomon"),
    ("pta038",  "Sir",      "Sirach"),
    ("pta039",  "PsSol",    "Psalms of Solomon"),
    ("pta040",  "Hos",      "Hosea"),
    ("pta041",  "Amos",     "Amos"),
    ("pta042",  "Mic",      "Micah"),
    ("pta043",  "Joel",     "Joel"),
    ("pta044",  "Obad",     "Obadiah"),
    ("pta045",  "Jonah",    "Jonah"),
    ("pta046",  "Nah",      "Nahum"),
    ("pta047",  "Hab",      "Habakkuk"),
    ("pta048",  "Zeph",     "Zephaniah"),
    ("pta049",  "Hag",      "Haggai"),
    ("pta050",  "Zech",     "Zechariah"),
    ("pta051",  "Mal",      "Malachi"),
    ("pta052",  "Isa",      "Isaiah"),
    ("pta053",  "Jer",      "Jeremiah"),
    ("pta054",  "Bar",      "Baruch"),
    ("pta055",  "Lam",      "Lamentations"),
    ("pta056",  "EpJer",    "Epistle of Jeremiah"),
    ("pta057",  "LetBar",   "Letter of Baruch"),
    ("pta058",  "2Bar",     "2 Baruch (Apocalypse of Baruch)"),
    ("pta059",  "Ezek",     "Ezekiel"),
    ("pta060",  "Sus",      "Susanna"),
    ("pta061",  "Dan",      "Daniel"),
    ("pta062",  "BelDr",    "Bel and the Dragon"),
    ("pta063",  "Matt",     "Matthew"),
    ("pta064",  "Mark",     "Mark"),
    ("pta065",  "Luke",     "Luke"),
    ("pta066",  "John",     "John"),
    ("pta067",  "Acts",     "Acts of the Apostles"),
    ("pta068",  "Rom",      "Romans"),
    ("pta069",  "1Cor",     "1 Corinthians"),
    ("pta070",  "2Cor",     "2 Corinthians"),
    ("pta071",  "Gal",      "Galatians"),
    ("pta072",  "Eph",      "Ephesians"),
    ("pta073",  "Phil",     "Philippians"),
    ("pta074",  "Col",      "Colossians"),
    ("pta075",  "1Thess",   "1 Thessalonians"),
    ("pta076",  "2Thess",   "2 Thessalonians"),
    ("pta077",  "1Tim",     "1 Timothy"),
    ("pta078",  "2Tim",     "2 Timothy"),
    ("pta079",  "Titus",    "Titus"),
    ("pta080",  "Phlm",     "Philemon"),
    ("pta081",  "Heb",      "Hebrews"),
    ("pta082",  "Jas",      "James"),
    ("pta083",  "1Pet",     "1 Peter"),
    ("pta084",  "2Pet",     "2 Peter"),
    ("pta085",  "1John",    "1 John"),
    ("pta086",  "2John",    "2 John"),
    ("pta087",  "3John",    "3 John"),
    ("pta088",  "Jude",     "Jude"),
    ("pta089",  "Rev",      "Revelation"),
]

_PTA_TO_OSIS: dict[str, str] = {p: o for p, o, _ in _BOOK_MAP}
_PTA_TO_TITLE: dict[str, str] = {p: t for p, _, t in _BOOK_MAP}

# NT work IDs (CC-BY 4.0); OT is CC-BY-NC 4.0
_NT_WORK_IDS = {f"pta{n:03d}" for n in range(63, 90)}

# ---------------------------------------------------------------------------
# ETCBC plain text: the word breaks PTA's OT lost (#60)
# ---------------------------------------------------------------------------

ETCBC_COMMIT = "9850f5addade26f681334aa475570bef9b0b440a"
_ETCBC_URL = "https://raw.githubusercontent.com/ETCBC/peshitta/{commit}/plain/0.2/{name}.txt"
ETCBC_TREE_URL = f"https://github.com/ETCBC/peshitta/tree/{ETCBC_COMMIT}/plain/0.2"

# OSIS book → ETCBC plain/0.2 file name. Where ETCBC has two texts of a book
# (A/B), PTA's is the A text: every verse of it matches.
ETCBC_FILES: dict[str, str] = {
    "Gen": "Genesis", "Exod": "Exodus", "Lev": "Leviticus", "Num": "Numbers",
    "Deut": "Deuteronomy", "Josh": "Joshua", "Judg": "Judges", "Ruth": "Ruth",
    "1Sam": "Samuel_1", "2Sam": "Samuel_2", "1Kgs": "Kings_1", "2Kgs": "Kings_2",
    "1Chr": "Chronicles_1", "2Chr": "Chronicles_2", "PrMan": "Prayer_of_Manasseh_A",
    "Ezra": "Ezra", "Neh": "Nehemia", "3Esr": "Esdras_3", "4Esr": "Esdras_4",
    "Esth": "Esther", "Jdt": "Judith", "Tob": "Tobit_A", "1Macc": "Maccabees_1_A",
    "2Macc": "Maccabees_2", "3Macc": "Maccabees_3", "4Macc": "Maccabees_4",
    "Ps": "Psalms", "Odes": "Odes", "Prov": "Proverbs", "Eccl": "Ecclesiastes",
    "Song": "Song_of_Songs", "Job": "Job", "Wis": "Wisdom_of_Solomon", "Sir": "Sirach",
    "PsSol": "Psalms_of_Solomon", "Hos": "Hosea", "Amos": "Amos", "Mic": "Micah",
    "Joel": "Joel", "Obad": "Obadiah", "Jonah": "Jonah", "Nah": "Nahum",
    "Hab": "Habakkuk", "Zeph": "Zephaniah", "Hag": "Haggai", "Zech": "Zechariah",
    "Mal": "Malachi", "Isa": "Isaiah", "Jer": "Jeremiah", "Bar": "Baruch",
    "Lam": "Lamentations", "EpJer": "Letter_of_Jeremiah", "LetBar": "Letter_of_Baruch_A",
    "2Bar": "Apocalypse_of_Baruch", "Ezek": "Ezekiel", "Sus": "Susanna", "Dan": "Daniel",
    "BelDr": "Bel_and_the_Dragon",
}

_OT_EDITION = (
    "Peshitta (ETCBC via PTA; word breaks restored from ETCBC plain text 0.2, "
    f"commit {ETCBC_COMMIT[:10]})"
)
_NT_EDITION = "Peshitta (Digital Syriac Corpus / ETCBC via PTA)"


def etcbc_path(output_dir: Path, osis: str) -> Path:
    """Cache path of the ETCBC plain text of *osis* under ``output_dir``."""
    return (output_dir / "_cache" / "etcbc-peshitta" / ETCBC_COMMIT[:10]
            / f"{ETCBC_FILES[osis]}.txt")


def fetch_etcbc(output_dir: Path, osis: str) -> Path:
    """Download (once) the ETCBC plain text of *osis*; the commit is pinned."""
    url = _ETCBC_URL.format(commit=ETCBC_COMMIT, name=ETCBC_FILES[osis])
    return download_file(url, etcbc_path(output_dir, osis), etag_cache=False)


def parse_etcbc_plain(text: str) -> dict[tuple[str, str], list[str]]:
    """ETCBC plain text → ``{(chapter, verse): [line, …]}``.

    A ``Chapter N`` line starts a chapter, a line starting with a number
    starts a verse, and any other non-empty line continues the verse.
    """
    verses: dict[tuple[str, str], list[str]] = {}
    chapter: str | None = None
    current: tuple[str, str] | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.fullmatch(r"Chapter (\S+)", line)
        if m:
            chapter = m.group(1)
            current = None
            continue
        m = re.match(r"(\d+)\s+(.*)$", line)
        if m and chapter is not None:
            current = (chapter, m.group(1))
            if current in verses:
                raise ValueError(f"ETCBC verse {chapter}:{m.group(1)} occurs twice")
            verses[current] = [m.group(2)]
        elif current is not None:
            verses[current].append(line)
        else:
            raise ValueError(f"ETCBC line outside a verse: {line[:40]!r}")
    return verses


def restore_word_breaks(
    text: str, lines: list[str] | None, where: str
) -> tuple[str, bool]:
    """PTA verse *text* with ETCBC's word breaks, if its letters are PTA's.

    Returns ``(text, changed)``. A verse ETCBC lacks (*lines* None) or whose
    letters differ keeps PTA's text and is logged at ERROR.
    """
    if lines is None:
        log.error("%s: not in the ETCBC text; PTA's word breaks kept", where)
        return text, False
    etcbc = " ".join(" ".join(lines).split())
    if etcbc == text:
        return text, False
    if etcbc.replace(" ", "") != text.replace(" ", ""):
        log.error("%s: PTA and ETCBC texts differ beyond word breaks; PTA's kept", where)
        return text, False
    return etcbc, True


def _extract_license(root: etree._Element) -> str:
    """Extract license from TEI availability element."""
    ns = {"tei": _TEI}
    lic_el = root.find(".//tei:teiHeader//tei:availability/tei:licence", ns)
    if lic_el is not None:
        target = lic_el.get("target", "")
        if "by-nc" in target or "by-nc" in (lic_el.text or ""):
            return "cc-by-nc-4.0"
        if "by-sa" in target:
            return "cc-by-sa-4.0"
        if "by" in target:
            return "cc-by-4.0"
    return "cc-by-nc-4.0"  # ETCBC default


def _extract_verses(
    root: etree._Element,
    book_abbrev: str,
    word_breaks: dict[tuple[str, str], list[str]] | None = None,
) -> list[dict[str, str]]:
    """Extract all verses from a Peshitta TEI file.

    With *word_breaks* (ETCBC lines per verse, #60), each verse takes
    ETCBC's word breaks where ``restore_word_breaks`` allows.

    Returns list of ``{"ref": "Matt.1.1", "text": "…"}`` dicts.
    """
    ns = {"tei": _TEI}
    edition_div = root.find(".//tei:text/tei:body/tei:div[@type='edition']", ns)
    if edition_div is None:
        log.debug("No edition div in %s", book_abbrev)
        return []

    verses: list[dict[str, str]] = []
    restored = 0

    for chapter_div in edition_div.findall(
        "tei:div[@type='textpart'][@subtype='chapter']", ns
    ):
        ch_n = chapter_div.get("n", "")
        if not ch_n:
            continue

        for verse_div in chapter_div.findall(
            "tei:div[@type='textpart'][@subtype='verse']", ns
        ):
            vs_n = verse_div.get("n", "")
            if not vs_n:
                continue

            # Collect all text from <p> and <ab> children
            text_parts: list[str] = []
            for el in verse_div:
                tag = etree.QName(el.tag).localname
                if tag in ("p", "ab"):
                    # Flatten all text including nested elements
                    text = "".join(el.itertext()).strip()
                    if text:
                        text_parts.append(text)

            text = re.sub(r"\s+", " ", " ".join(text_parts)).strip()
            if not text:
                continue

            ref = slugify_ref(f"{book_abbrev}.{ch_n}.{vs_n}")
            if word_breaks is not None:
                text, changed = restore_word_breaks(text, word_breaks.get((ch_n, vs_n)), ref)
                restored += changed
            verses.append({"ref": ref, "text": text})

    if word_breaks is not None:
        log.info("%s: word breaks restored from ETCBC in %d of %d verses",
                 book_abbrev, restored, len(verses))
    return verses


def _book_dates(osis: str) -> tuple[int | None, tuple[int, int] | None, DateConfidence]:
    """Look up composition date for a book from _scripture_meta.BOOK_DATES."""
    entry = BOOK_DATES.get(osis)
    if entry is None:
        return None, None, "uncertain"
    return entry["date_composed"], entry["date_range"], entry["date_confidence"]


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Ingest Syriac Peshitta from the PTA git clone.

    Reads from ``data/raw/pta/data/pta9999/``.
    Writes to ``output_dir/pta-peshitta/{BookAbbrev}.json``.

    The PTA repo must already be cloned (``pta.py`` handles the clone).
    """
    repo_dir = output_dir / "pta"
    pta9999_dir = repo_dir / "data" / "pta9999"

    if not pta9999_dir.exists():
        raise FileNotFoundError(
            f"PTA repo not found at {repo_dir}. "
            "Run the pta ingestor first to clone the repo."
        )

    out_base = output_dir / "pta-peshitta"
    out_base.mkdir(parents=True, exist_ok=True)

    works: list[Work] = []
    skipped = 0

    for pta_work_id, osis_abbrev, title in tqdm(_BOOK_MAP, desc="Peshitta"):
        work_dir = pta9999_dir / pta_work_id

        # Find the syc text file (prefer syc1, fall back to syc2+)
        syc_files = sorted(
            f for f in work_dir.glob("*.xml")
            if "syc" in f.name
            and "Bibex" not in f.name
            and "Ms" not in f.name
            and f.name != "__cts__.xml"
        )
        if not syc_files:
            log.debug("No Syriac file for %s (%s) — skipping", pta_work_id, osis_abbrev)
            skipped += 1
            continue

        xml_path = syc_files[0]
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

        is_ot = pta_work_id not in _NT_WORK_IDS
        word_breaks = None
        if is_ot:
            etcbc_file = fetch_etcbc(output_dir, osis_abbrev)
            word_breaks = parse_etcbc_plain(etcbc_file.read_text(encoding="utf-8"))
        verses = _extract_verses(root, osis_abbrev, word_breaks)
        if not verses:
            log.debug("No verses extracted from %s — skipping", xml_path)
            skipped += 1
            continue

        license_val = _extract_license(root)
        date_composed, date_range, date_confidence = _book_dates(osis_abbrev)

        work = Work(
            work_id=f"{SOURCE_ID}/{osis_abbrev.lower()}",
            source_id=SOURCE_ID,
            author=None,
            title=f"{title} (Peshitta)",
            date_composed=date_composed,
            date_range=date_range,
            date_confidence=date_confidence,
            genre="scripture",
            language="syc",
            tradition="syriac",
            license=license_val,
            provenance_url=(
                f"https://github.com/PatristicTextArchive/pta_data/tree/main"
                f"/data/pta9999/{pta_work_id}"
            ),
            edition=_OT_EDITION if is_ot else _NT_EDITION,
            translation_of=None,
        )

        payload = {"work": work.model_dump(), "verses": verses}
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        works.append(work)

    log.info(
        "Peshitta ingestion complete: %d books written, %d skipped",
        len(works),
        skipped,
    )
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
