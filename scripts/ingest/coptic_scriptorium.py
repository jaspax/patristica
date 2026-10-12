"""
Ingestor for the Coptic Scriptorium corpus.

Source: https://github.com/CopticScriptorium/corpora
Format: TEI P5 XML ({corpus}/{corpus}_TEI/*.xml), with linguistic annotation
License: CC-BY 4.0 (some corpora CC-BY-SA 4.0 or CC-BY 3.0)

Scope
-----
Ingests Coptic patristic texts: homilies, saints' lives, Shenoute, letters,
monastic texts and apocrypha.  None is a liturgy, so every work has genre
``patristic`` (#40); the ``liturgical/`` source_id prefix is historical.

Excludes:
  - Biblical NT/OT books (already in ``coptic_nt.py``)
  - Treebank/duplicate corpora (``coptic-treebank``, ``bohairic-treebank``)
  - Gnostic/apocryphal texts (Thomas, Pistis Sophia, Book of Bartholomew)
  - Documentary and magical papyri

One Work is written per qualifying corpus.  All TEI XML files in
``{corpus}/{corpus}_TEI/`` are concatenated into a single paragraph list.

TEI text extraction
-------------------
Coptic Scriptorium TEI files are linguistically annotated with ``<w>`` word
elements inside ``<ab>`` and ``<p>`` containers.  We join word texts within
each container to produce paragraph strings, skipping scholarly apparatus
(``<note>``, ``<gap>``, ``<unclear>``, ``<supplied>``).

Canonical references
--------------------
``CopScr.{corpus_slug}.{file_n:03d}.{para_n:04d}``

  corpus_slug  corpus name with ``-`` replaced by ``_``
  file_n       0-based index of the TEI file within the corpus
  para_n       sequential paragraph counter (0-based) within that file

Example: ``CopScr.shenoute_considering.000.0012``
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

from lxml import etree
from tqdm import tqdm

from patristica.models import Work
from scripts.ingest._common import slugify_ref

log = logging.getLogger(__name__)

SOURCE_ID = "liturgical/coptic-scriptorium"

_REPO_URL = "https://github.com/CopticScriptorium/corpora"

# TEI namespace used by Coptic Scriptorium
_TEI_NS = "http://www.tei-c.org/ns/1.0"
_TEI = f"{{{_TEI_NS}}}"

# Coptic Unicode block (U+2C80–U+2CFF) + Greek letters used in Coptic (U+0370–U+03FF)
_COPTIC_RE = re.compile(r"[Ⲁ-⳿Ͱ-Ͽ]")

# Tags whose text content we skip during extraction (scholarly apparatus)
_SKIP_TAGS = frozenset({
    f"{_TEI}note",
    f"{_TEI}gap",
    f"{_TEI}unclear",
    f"{_TEI}supplied",
    f"{_TEI}app",
    f"{_TEI}orig",   # inside <choice>: use <reg> instead
})

# ---------------------------------------------------------------------------
# Corpus definitions
# ---------------------------------------------------------------------------

# Explicit metadata for each qualifying corpus.
# Keys: genre, author, title, date_composed, date_range, date_confidence
_CORPUS_META: dict[str, dict] = {
    "AP": {
        "genre": "patristic",
        "author": "Various Desert Fathers",
        "title": "Apophthegmata Patrum",
        "date_composed": 425,
        "date_range": (350, 500),
        "date_confidence": "approximate",
    },
    "besa-letters": {
        "genre": "patristic",
        "author": "Besa",
        "title": "Letters of Besa",
        "date_composed": 475,
        "date_range": (450, 500),
        "date_confidence": "approximate",
    },
    "pachomius-instructions": {
        "genre": "patristic",
        "author": "Pachomius",
        "title": "Instructions of Pachomius",
        "date_composed": 330,
        "date_range": (320, 346),
        "date_confidence": "established",
    },
    "proclus-homilies": {
        "genre": "patristic",
        "author": "Proclus of Constantinople",
        "title": "Homilies of Proclus (Coptic translation)",
        "date_composed": 420,
        "date_range": (390, 446),
        "date_confidence": "established",
    },
    "pseudo-athanasius-discourses": {
        "genre": "patristic",
        "author": "Pseudo-Athanasius",
        "title": "Discourses Attributed to Athanasius (Coptic)",
        "date_composed": None,
        "date_range": (300, 500),
        "date_confidence": "uncertain",
    },
    "pseudo-basil": {
        "genre": "patristic",
        "author": "Pseudo-Basil",
        "title": "Works Attributed to Basil the Great (Coptic)",
        "date_composed": None,
        "date_range": (300, 500),
        "date_confidence": "uncertain",
    },
    "pseudo-chrysostom": {
        "genre": "patristic",
        "author": "Pseudo-Chrysostom",
        "title": "Works Attributed to John Chrysostom (Coptic)",
        "date_composed": None,
        "date_range": (380, 500),
        "date_confidence": "uncertain",
    },
    "pseudo-ephrem": {
        "genre": "patristic",
        "author": "Pseudo-Ephrem",
        "title": "Works Attributed to Ephrem the Syrian (Coptic)",
        "date_composed": None,
        "date_range": (306, 373),
        "date_confidence": "uncertain",
    },
    "pseudo-flavianus": {
        "genre": "patristic",
        "author": "Pseudo-Flavianus",
        "title": "Works Attributed to Flavianus (Coptic)",
        "date_composed": None,
        "date_range": (400, 500),
        "date_confidence": "uncertain",
    },
    "pseudo-timothy": {
        "genre": "patristic",
        "author": "Pseudo-Timothy",
        "title": "Works Attributed to Timothy (Coptic)",
        "date_composed": None,
        "date_range": (400, 550),
        "date_confidence": "uncertain",
    },
    "pseudo-celestinus": {
        "genre": "patristic",
        "author": "Pseudo-Celestinus",
        "title": "Works Attributed to Celestinus (Coptic)",
        "date_composed": None,
        "date_range": (400, 432),
        "date_confidence": "uncertain",
    },
    # Hagiographies
    "life-aphou": {
        "genre": "patristic",
        "author": None,
        "title": "Life of Aphou",
        "date_composed": None,
        "date_range": (300, 600),
        "date_confidence": "uncertain",
    },
    "life-cyrus": {
        "genre": "patristic",
        "author": None,
        "title": "Life of Cyrus",
        "date_composed": None,
        "date_range": (300, 700),
        "date_confidence": "uncertain",
    },
    "life-eustathius-theopiste": {
        "genre": "patristic",
        "author": None,
        "title": "Life of Eustathius and Theopiste",
        "date_composed": None,
        "date_range": (300, 700),
        "date_confidence": "uncertain",
    },
    "life-john-kalybites": {
        "genre": "patristic",
        "author": None,
        "title": "Life of John the Dweller in the Hovel",
        "date_composed": None,
        "date_range": (400, 600),
        "date_confidence": "uncertain",
    },
    "life-longinus-lucius": {
        "genre": "patristic",
        "author": None,
        "title": "Life of Longinus and Lucius",
        "date_composed": None,
        "date_range": (300, 600),
        "date_confidence": "uncertain",
    },
    "life-onnophrius": {
        "genre": "patristic",
        "author": None,
        "title": "Life of Onnophrius",
        "date_composed": None,
        "date_range": (300, 600),
        "date_confidence": "uncertain",
    },
    "life-paul-tamma": {
        "genre": "patristic",
        "author": None,
        "title": "Life of Paul of Tamma",
        "date_composed": None,
        "date_range": (300, 500),
        "date_confidence": "uncertain",
    },
    "life-phib": {
        "genre": "patristic",
        "author": None,
        "title": "Life of Phib",
        "date_composed": None,
        "date_range": (300, 600),
        "date_confidence": "uncertain",
    },
    "life-pisentius": {
        "genre": "patristic",
        "author": None,
        "title": "Life of Bishop Pisentius",
        "date_composed": 600,
        "date_range": (569, 632),
        "date_confidence": "approximate",
    },
    # Apocrypha.  None of these is a liturgy, so they are ``patristic`` like
    # the NT apocrypha in anf_works.py (#40).  The Lament of the Virgin
    # (Pseudo-Gamaliel) is read in Holy Week, but it is a narrative homily,
    # not a liturgical text.
    "dormition-john": {
        "genre": "patristic",
        "author": None,
        "title": "Dormition of John the Apostle (Coptic)",
        "date_composed": None,
        "date_range": (100, 400),
        "date_confidence": "uncertain",
    },
    "lament-mary": {
        "genre": "patristic",
        "author": None,
        "title": "Lament of the Virgin Mary (Coptic)",
        "date_composed": None,
        "date_range": (100, 600),
        "date_confidence": "uncertain",
    },
    "mysteries-john": {
        "genre": "patristic",
        "author": None,
        "title": "Mysteries of John (Coptic)",
        "date_composed": None,
        "date_range": (100, 600),
        "date_confidence": "uncertain",
    },
    # Other patristic/hagiographic
    "acts-pilate": {
        "genre": "patristic",
        "author": None,
        "title": "Acts of Pilate (Coptic)",
        "date_composed": None,
        "date_range": (100, 400),
        "date_confidence": "uncertain",
    },
    "helias": {
        "genre": "patristic",
        "author": None,
        "title": "Life of Helias (Coptic)",
        "date_composed": None,
        "date_range": (300, 600),
        "date_confidence": "uncertain",
    },
    "mercurius": {
        "genre": "patristic",
        "author": None,
        "title": "Martyrdom of Mercurius (Coptic)",
        "date_composed": None,
        "date_range": (300, 600),
        "date_confidence": "uncertain",
    },
    "theodosius-alexandria": {
        "genre": "patristic",
        "author": None,
        "title": "Life of Theodosius of Alexandria (Coptic)",
        "date_composed": None,
        "date_range": (400, 600),
        "date_confidence": "uncertain",
    },
    "abraham": {
        "genre": "patristic",
        "author": None,
        "title": "Life of Abraham (Coptic)",
        "date_composed": None,
        "date_range": (300, 600),
        "date_confidence": "uncertain",
    },
    "johannes-canons": {
        "genre": "patristic",
        "author": None,
        "title": "Canons of Johannes (Coptic)",
        "date_composed": None,
        "date_range": (300, 600),
        "date_confidence": "uncertain",
    },
    "john-constantinople": {
        "genre": "patristic",
        "author": None,
        "title": "Life of John of Constantinople (Coptic)",
        "date_composed": None,
        "date_range": (300, 600),
        "date_confidence": "uncertain",
    },
}

# Shenoute of Atripe corpora (prefix-matched below)
_SHENOUTE_META = {
    "genre": "patristic",
    "author": "Shenoute of Atripe",
    "date_composed": 420,
    "date_range": (385, 465),
    "date_confidence": "established",
}

# Corpora to exclude entirely
_EXCLUDED: frozenset[str] = frozenset({
    # Biblical (already in coptic_nt.py or out of scope)
    "bohairic.nt", "bohairic.ot", "sahidica.nt", "sahidic.ot",
    "sahidic.ruth", "sahidic.jonah",
    "sahidica.mark", "sahidica.1corinthians",
    "bohairic.1corinthians", "bohairic.mark",
    # Duplicate treebanks
    "coptic-treebank", "bohairic-treebank",
    # Gnostic / apocryphal
    "thomas-gospel", "pistis-sophia", "book-bartholomew",
    # Documentary
    "doc-papyri", "magical-papyri",
})


def _corpus_meta(corpus: str) -> dict | None:
    """Return metadata dict for a corpus name, or None if excluded/unknown."""
    if corpus in _EXCLUDED:
        return None
    if corpus in _CORPUS_META:
        return _CORPUS_META[corpus]
    if corpus.startswith("shenoute-"):
        title = corpus.replace("shenoute-", "").replace("-", " ").title()
        return {**_SHENOUTE_META, "title": f"Shenoute: {title}"}
    return None


# ---------------------------------------------------------------------------
# Repo management
# ---------------------------------------------------------------------------

def _ensure_repo(repo_dir: Path, force: bool) -> None:
    """Clone the Coptic Scriptorium repo if absent; pull on force."""
    if not repo_dir.exists():
        log.info("Cloning Coptic Scriptorium repo into %s …", repo_dir)
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth=1", _REPO_URL, str(repo_dir)],
            check=True,
        )
    elif force:
        log.info("Pulling latest Coptic Scriptorium data …")
        subprocess.run(
            ["git", "-C", str(repo_dir), "pull", "--ff-only"],
            check=True,
        )


# ---------------------------------------------------------------------------
# TEI text extraction
# ---------------------------------------------------------------------------

def _elem_words(el: etree._Element) -> list[str]:
    """Collect word-level text from an element, skipping apparatus tags."""
    words: list[str] = []
    _collect_words(el, words)
    return words


def _collect_words(el: etree._Element, out: list[str]) -> None:
    """Recursively collect text, preferring <w> and <reg> over raw PCDATA."""
    if not isinstance(el.tag, str):
        return
    tag = etree.QName(el.tag).localname
    ns_tag = el.tag

    # Skip scholarly apparatus entirely
    if ns_tag in _SKIP_TAGS:
        return

    # Inside <choice>, use <reg> (normalized) not <orig> (manuscript)
    if tag == "choice":
        reg = el.find(f"{_TEI}reg")
        if reg is not None:
            _collect_words(reg, out)
        else:
            # No <reg>; fall back to <corr> then first child
            corr = el.find(f"{_TEI}corr")
            target = corr if corr is not None else (el[0] if len(el) else None)
            if target is not None:
                _collect_words(target, out)
        return

    # Word element: use itertext() to handle split text across <lb> children
    if tag == "w":
        t = re.sub(r"\s+", " ", "".join(el.itertext())).strip()
        if t:
            out.append(t)
        return

    # For any other element, recurse into children; also pick up direct PCDATA
    if el.text and el.text.strip():
        out.append(el.text.strip())
    for child in el:
        _collect_words(child, out)
        if child.tail and child.tail.strip() and child.tag not in _SKIP_TAGS:
            out.append(child.tail.strip())


def _extract_paragraphs_tei(
    root: etree._Element, file_n: int, corpus_name: str, start_n: int
) -> list[dict]:
    """Extract paragraphs from a standard TEI P5 document.

    Tries candidate container element types in priority order, using the first
    type that yields results.  This prevents double-counting when both ``<p>``
    and ``<s>`` exist in the same document.
    """
    body = root.find(f".//{_TEI}body")
    if body is None:
        body = root.find(".//body")
    if body is None:
        return []

    # Try container types in priority order; stop at first type that yields text
    candidates = [
        [f"{_TEI}ab", "ab"],
        [f"{_TEI}p", "p"],
        [f"{_TEI}s", "s"],
        [f"{_TEI}l", "l"],
    ]

    for tag_variants in candidates:
        elements = [
            el for el in body.iter()
            if isinstance(el.tag, str)
            and etree.QName(el.tag).localname in tag_variants
        ]
        if not elements:
            continue

        paragraphs: list[dict] = []
        para_n = start_n
        for el in elements:
            words = _elem_words(el)
            if not words:
                continue
            text = " ".join(words)
            if not _COPTIC_RE.search(text):
                continue
            ref = slugify_ref(f"CopScr.{corpus_name}.{file_n:03d}.{para_n:04d}")
            paragraphs.append({"ref": ref, "text": text})
            para_n += 1

        if paragraphs:
            return paragraphs

    return []


def _extract_paragraphs_custom(
    root: etree._Element, file_n: int, corpus_name: str, start_n: int
) -> list[dict]:
    """Extract paragraphs from the Coptic Scriptorium custom ``<meta>`` format.

    This format stores word tokens in ``<norm_group norm_group="word">`` elements,
    grouped under ``<p_n>`` or ``<p>`` paragraph containers.
    """
    para_n = start_n
    paragraphs: list[dict] = []

    # Paragraph containers: <p_n> (most corpora) or <p p="p"> (some Shenoute)
    para_elems = root.findall(".//p_n")
    if not para_elems:
        para_elems = [el for el in root.iter("p") if el.get("p") == "p"]
    if not para_elems:
        # Last resort: treat the whole document as one paragraph
        para_elems = [root]

    for para_el in para_elems:
        words = [
            ng.get("norm_group", "").strip()
            for ng in para_el.findall(".//norm_group")
            if ng.get("norm_group", "").strip()
        ]
        if not words:
            continue
        text = " ".join(words)
        if not _COPTIC_RE.search(text):
            continue
        ref = slugify_ref(f"CopScr.{corpus_name}.{file_n:03d}.{para_n:04d}")
        paragraphs.append({"ref": ref, "text": text})
        para_n += 1

    return paragraphs


def _extract_paragraphs_from_tei(xml_path: Path, file_n: int, corpus_name: str) -> list[dict]:
    """Parse a single Coptic Scriptorium XML file into paragraph records.

    Dispatches to the appropriate parser based on the root element tag:
    - Standard TEI P5 (``{...}TEI`` root) → ``_extract_paragraphs_tei``
    - Custom format (``meta`` root) → ``_extract_paragraphs_custom``
    """
    try:
        parser = etree.XMLParser(recover=True, no_network=True, load_dtd=False)
        tree = etree.parse(str(xml_path), parser)
        root = tree.getroot()
    except Exception as exc:
        log.warning("  XML parse error %s: %s", xml_path.name, exc)
        return []

    root_local = etree.QName(root.tag).localname if isinstance(root.tag, str) else ""

    if root_local == "TEI":
        return _extract_paragraphs_tei(root, file_n, corpus_name, start_n=0)
    elif root_local == "meta":
        return _extract_paragraphs_custom(root, file_n, corpus_name, start_n=0)
    else:
        log.debug("  Unknown root element <%s> in %s; trying TEI parser", root_local, xml_path.name)
        return _extract_paragraphs_tei(root, file_n, corpus_name, start_n=0)


# ---------------------------------------------------------------------------
# Ingestor
# ---------------------------------------------------------------------------

def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Clone Coptic Scriptorium repo and write per-corpus JSON output files."""
    repo_dir = Path(output_dir) / "_repos" / "coptic-scriptorium"
    _ensure_repo(repo_dir, force)

    out_root = Path(output_dir) / SOURCE_ID
    out_root.mkdir(parents=True, exist_ok=True)

    # Discover all corpus directories
    corpus_dirs = sorted(
        d for d in repo_dir.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )
    log.info("Found %d corpus directories", len(corpus_dirs))

    works: list[Work] = []

    for corpus_dir in tqdm(corpus_dirs, desc="Coptic Scriptorium corpora"):
        corpus_name = corpus_dir.name
        meta = _corpus_meta(corpus_name)
        if meta is None:
            log.debug("  Skipping corpus: %s", corpus_name)
            continue

        corpus_slug = corpus_name.replace("-", "_")
        out_path = out_root / f"{corpus_slug}.json"

        if out_path.exists() and not force:
            log.debug("  Skipping %s (already exists)", out_path.name)
            with open(out_path) as f:
                saved = json.load(f)
            works.append(Work(**saved["work"]))
            continue

        # Find TEI XML files
        tei_dir = corpus_dir / f"{corpus_name}_TEI"
        if not tei_dir.exists():
            # Try alternative capitalization
            candidates = list(corpus_dir.glob("*_TEI"))
            tei_dir = candidates[0] if candidates else None

        if tei_dir is None or not tei_dir.exists():
            log.warning("  No TEI directory for %s", corpus_name)
            continue

        tei_files = sorted(tei_dir.glob("*.xml"))
        if not tei_files:
            log.warning("  No TEI XML files in %s", tei_dir)
            continue

        # Extract paragraphs from all TEI files in this corpus
        all_paragraphs: list[dict] = []
        for file_n, xml_path in enumerate(tei_files):
            paras = _extract_paragraphs_from_tei(xml_path, file_n, corpus_name)
            all_paragraphs.extend(paras)

        if not all_paragraphs:
            log.warning("  No text extracted from %s (%d files)", corpus_name, len(tei_files))
            continue

        work = Work(
            work_id=f"liturgical/coptic-scriptorium/{corpus_slug}",
            source_id=SOURCE_ID,
            author=meta["author"],
            title=meta["title"],
            date_composed=meta["date_composed"],
            date_range=meta["date_range"],
            date_confidence=meta["date_confidence"],
            genre=meta["genre"],
            language="cop",
            tradition="coptic",
            license="cc-by-4.0",
            provenance_url=f"{_REPO_URL}/tree/master/{corpus_name}",
            edition=f"Coptic Scriptorium, {corpus_name}",
        )

        out_path.write_text(
            json.dumps(
                {"work": work.model_dump(), "paragraphs": all_paragraphs},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        log.info(
            "  Wrote %s (%d paragraphs from %d files)",
            out_path.name, len(all_paragraphs), len(tei_files),
        )
        works.append(work)

    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
