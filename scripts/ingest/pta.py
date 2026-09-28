"""
Ingestor for the Patristic Text Archive (PTA).

Source: https://github.com/PatristicTextArchive/pta_data
Format: TEI P5 XML, organised by CTS URN (pta{NNNN}/pta{NNN}/)
License: CC-BY / CC-BY-SA per file (stated in <availability>)

Acquisition
-----------
The PTA GitHub zip archive (archive/refs/heads/main.zip) returns 404.
Instead we shallow-clone the repo into ``data/raw/patristic/pta/`` using the
git credentials available in the environment.  On ``force=True`` we pull the
latest changes.

File filtering
--------------
We process only "edition" files (``pta-grcN``, ``pta-sycN``, ``pta-latN``,
``pta-xcl1``, ``pta-eng1``, etc.) and skip:

- ``__cts__.xml``  — CTS catalog metadata (not text)
- ``pta9999/``     — Bible textgroup (already have dedicated scripture ingestors)
- ``*Bibex*``      — biblical-excerpt versions (thin wrappers around scripture)
- ``*Ms*``         — individual manuscript witnesses (not critical text)
- ``*deu*``        — German translations (not in our language set)

Canonical references
--------------------
Each work's ``canonical_ref`` uses the PTA CTS work ID plus the ``@n``
attributes of every enclosing ``<div type="textpart">`` and a per-paragraph
counter::

    pta0001.pta001.1.3   # author_id.work_id.section_n.paragraph_n

The ``work_id`` in the ``Work`` model follows our slug convention::

    pta/pta0001/pta001   # pta/{author_id}/{work_id_without_author}
"""

from __future__ import annotations

import logging
import re
import subprocess
from pathlib import Path

from lxml import etree
from tqdm import tqdm

from patristica.models import DateConfidence, Language, License, Tradition, Work
from scripts.ingest._common import dedupe_refs, slugify_ref

log = logging.getLogger(__name__)

SOURCE_ID = "patristic/pta"

_REPO_URL = "https://github.com/PatristicTextArchive/pta_data.git"

# TEI namespace
_TEI = "http://www.tei-c.org/ns/1.0"
_CTS_NS = "http://chs.harvard.edu/xmlns/cts"

# Language code mapping: PTA lang tag → ISO 639-3 used in our models
_LANG_MAP: dict[str, Language] = {
    "grc": "grc",
    "lat": "lat",
    "syc": "syc",
    "xcl": "hye",   # Classical Armenian → hye
    "cop": "cop",
    "gez": "gez",
    "eng": "eng",
    "got": "got",
}

# Language → Tradition
_LANG_TRADITION: dict[Language, Tradition | None] = {
    "grc": "greek",
    "lat": "latin",
    "syc": "syriac",
    "hye": "armenian",
    "cop": "coptic",
    "gez": "ethiopic",
    "eng": None,
    "got": "gothic",
    "hbo": None,
}

_SCHISM_YEAR = 1054

# File name patterns to skip
_SKIP_PATTERNS = re.compile(r"Bibex|MsA|MsB|MsC|MsD|MsE|MsF|MsG|MsH|MsI|MsJ|MsK|MsL|MsM|MsN|MsO|MsP|MsQ|MsR|MsS|MsT|MsU|MsV|MsW|MsX|MsY|MsZ|Ms[A-Z]|deu")


def _ensure_repo(repo_dir: Path, force: bool) -> None:
    """Clone the PTA repo if absent; pull latest on force."""
    if not repo_dir.exists():
        log.info("Cloning PTA repo into %s …", repo_dir)
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth=1", _REPO_URL, str(repo_dir)],
            check=True,
        )
    elif force:
        log.info("Pulling latest PTA data …")
        subprocess.run(
            ["git", "-C", str(repo_dir), "pull", "--ff-only"],
            check=True,
        )


def _read_author_name(cts_path: Path) -> str | None:
    """Extract the English author name from a ``__cts__.xml`` file."""
    try:
        tree = etree.parse(str(cts_path))
        root = tree.getroot()
        ns = {"ti": _CTS_NS}
        for el in root.findall(".//ti:groupname", ns):
            if el.get("{http://www.w3.org/XML/1998/namespace}lang") == "eng":
                return (el.text or "").strip() or None
        # Fallback: first groupname
        el = root.find(".//ti:groupname", ns)
        if el is not None:
            return (el.text or "").strip() or None
    except Exception as exc:
        log.debug("Could not read %s: %s", cts_path, exc)
    return None


def _extract_dates(root: etree._Element) -> tuple[int | None, tuple[int, int] | None, DateConfidence]:
    """Extract composition date info from teiHeader/profileDesc/creation/date."""
    ns = {"tei": _TEI}
    date_el = root.find(".//tei:profileDesc/tei:creation/tei:date", ns)
    if date_el is None:
        return None, None, "uncertain"

    when = date_el.get("when") or date_el.get("notBefore") or date_el.get("notAfter")

    not_before_s = date_el.get("notBefore") or date_el.get("when")
    not_after_s = date_el.get("notAfter") or date_el.get("when")

    def _parse_year(s: str | None) -> int | None:
        if not s:
            return None
        m = re.search(r"-?(\d{3,4})", s)
        if m:
            year = int(m.group(1))
            return -year if s.startswith("-") else year
        return None

    y_before = _parse_year(not_before_s)
    y_after = _parse_year(not_after_s)

    if y_before is None and y_after is None:
        return None, None, "uncertain"

    if y_before == y_after:
        return y_before, None, "established"

    date_range: tuple[int, int] | None = None
    date_composed: int | None = None
    if y_before is not None and y_after is not None:
        date_range = (y_before, y_after)
        date_composed = (y_before + y_after) // 2
    elif y_before is not None:
        date_composed = y_before
    elif y_after is not None:
        date_composed = y_after

    return date_composed, date_range, "approximate"


def _element_inner_text(el: etree._Element) -> str:
    """Collect all text inside an element, stripping child element tags but keeping their text."""
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        parts.append(_element_inner_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _extract_paragraphs(
    body_div: etree._Element,
    work_cts_id: str,
    ns: dict[str, str],
) -> list[dict[str, str]]:
    """Recursively extract paragraphs from a TEI body div.

    Traverses ``<div type="textpart">`` elements, building a dotted path from
    their ``@n`` attributes.  ``<p>`` and ``<ab>`` elements become individual
    paragraph records.

    Parameters
    ----------
    body_div:    The ``<div type="edition">`` element.
    work_cts_id: E.g. ``"pta0001.pta001"`` — prepended to all refs.
    ns:          Namespace map.

    Returns
    -------
    List of ``{"ref": "...", "text": "..."}`` dicts.
    """
    records: list[dict[str, str]] = []

    def _walk(element: etree._Element, path_parts: list[str]) -> None:
        tag = etree.QName(element.tag).localname if element.tag != etree.Comment else ""

        if tag in ("p", "ab"):
            text = _element_inner_text(element).strip()
            # Collapse whitespace
            text = re.sub(r"\s+", " ", text)
            if text:
                ref = slugify_ref(".".join([work_cts_id] + path_parts))
                records.append({"ref": ref, "text": text})
            return

        if tag == "div" and element.get("type") == "textpart":
            n = element.get("n", "")
            # Skip non-numeric n values like "Index" or "Titulus" (front matter)
            new_parts = path_parts + [n] if n and re.match(r"^[\w\-]+$", n) else path_parts
            for child in element:
                _walk(child, new_parts)
            return

        # For other elements (head, note, pb, etc.) recurse without adding to path
        if tag not in ("head", "note", "pb", "lb", "cb", "fw", "figure", "table"):
            for child in element:
                _walk(child, path_parts)

    for child in body_div:
        _walk(child, [])

    return dedupe_refs(records)


def _parse_pta_file(
    xml_path: Path,
    author_name: str | None,
) -> tuple[Work, list[dict[str, str]]] | None:
    """Parse a single PTA TEI file.

    Returns ``(Work, paragraphs)`` or ``None`` if the file should be skipped.
    """
    try:
        tree = etree.parse(str(xml_path))
    except etree.XMLSyntaxError as exc:
        log.warning("XML parse error in %s: %s", xml_path, exc)
        return None

    root = tree.getroot()
    ns = {"tei": _TEI}

    # --- Title ---
    title_el = root.find(".//tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", ns)
    title = (title_el.text or "").strip() if title_el is not None else xml_path.stem

    # --- Edition div → language ---
    edition_div = root.find(".//tei:text/tei:body/tei:div[@type='edition']", ns)
    if edition_div is None:
        log.debug("No edition div in %s — skipping", xml_path)
        return None

    xml_lang = edition_div.get("{http://www.w3.org/XML/1998/namespace}lang", "")
    language = _LANG_MAP.get(xml_lang)
    if language is None:
        log.debug("Unsupported language %r in %s — skipping", xml_lang, xml_path)
        return None

    tradition = _LANG_TRADITION.get(language)

    # --- CTS URN → work identifiers ---
    cts_urn = edition_div.get("n", "")
    # e.g. "urn:cts:pta:pta0001.pta001.pta-grc1"
    cts_parts = cts_urn.rsplit(":", 1)[-1].split(".")
    # cts_parts = ["pta0001", "pta001", "pta-grc1"]
    if len(cts_parts) >= 2:
        author_id = cts_parts[0]   # "pta0001"
        work_id_short = cts_parts[1]  # "pta001"
        version = cts_parts[2] if len(cts_parts) > 2 else ""  # "pta-grc1"
    else:
        # Fallback: derive from file path
        author_id = xml_path.parts[-3]  # e.g. "pta0001"
        work_id_short = xml_path.parts[-2]  # e.g. "pta001"
        version = ""

    work_cts_id = f"{author_id}.{work_id_short}"  # "pta0001.pta001"
    work_id = f"pta/{author_id}/{work_id_short}"
    if version:
        work_id = f"{work_id}/{version}"

    # --- Dates ---
    date_composed, date_range, date_confidence = _extract_dates(root)

    # Post-schism filter: skip only if we have positive evidence (notBefore > 1054)
    if date_range is not None and date_range[0] > _SCHISM_YEAR:
        log.debug("Skipping post-schism work %s (date_range=%s)", work_cts_id, date_range)
        return None
    post_schism = False
    if date_composed is not None and date_composed > _SCHISM_YEAR:
        post_schism = True

    # --- License ---
    avail_el = root.find(".//tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability", ns)
    avail_text = ""
    if avail_el is not None:
        # Try to get text from <licence> child
        lic_el = avail_el.find("tei:licence", ns)
        if lic_el is not None:
            avail_text = (lic_el.text or "").lower()
        else:
            avail_text = (avail_el.text or "").lower()
    if "cc-by-sa" in avail_text or "by-sa" in avail_text:
        license_val: License = "cc-by-sa-4.0"
    elif "cc-by" in avail_text or "by 4.0" in avail_text:
        license_val = "cc-by-4.0"
    else:
        license_val = "cc-by-4.0"  # PTA default

    # --- Author ---
    author_el = root.find(".//tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author/tei:persName", ns)
    if author_el is None:
        author_el = root.find(".//tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author", ns)
    author_from_file = (author_el.text or "").strip() if author_el is not None else None
    author = author_name or author_from_file

    # --- Edition note ---
    edition_note = version or None

    work = Work(
        work_id=work_id,
        source_id=SOURCE_ID,
        author=author,
        title=title,
        date_composed=date_composed,
        date_range=date_range,
        date_confidence=date_confidence,
        genre="patristic",
        language=language,
        tradition=tradition,
        license=license_val,
        provenance_url=f"https://github.com/PatristicTextArchive/pta_data/blob/main/data/{author_id}/{work_id_short}/{xml_path.name}",
        edition=edition_note,
        translation_of=None,
    )

    paragraphs = _extract_paragraphs(edition_div, work_cts_id, ns)
    return work, paragraphs


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Clone/pull the PTA repo and ingest all text editions.

    Parameters
    ----------
    output_dir: Root raw output directory (``data/raw``).
    force:      If True, pull latest git changes before processing.

    Returns
    -------
    List of ``Work`` records written.
    """
    repo_dir = output_dir / "patristic" / "pta"
    _ensure_repo(repo_dir, force)

    pta_data_dir = repo_dir / "data"
    if not pta_data_dir.exists():
        raise FileNotFoundError(f"Expected PTA data directory at {pta_data_dir}")

    # Collect all XML files to process
    xml_files = [
        p for p in sorted(pta_data_dir.rglob("*.xml"))
        if p.name != "__cts__.xml"
        and "pta9999" not in p.parts  # skip Bible group
        and not _SKIP_PATTERNS.search(p.name)
    ]

    log.info("Found %d PTA text files to process", len(xml_files))

    works: list[Work] = []
    skipped = 0

    for xml_path in tqdm(xml_files, desc="PTA ingest"):
        # Derive output path: data/raw/patristic/pta/{author_id}/{work_id}/{file}.json
        # Use relative path within pta_data_dir
        rel = xml_path.relative_to(pta_data_dir)  # e.g. pta0001/pta001/pta0001.pta001.pta-grc1.xml
        out_path = output_dir / "patristic" / "pta" / rel.with_suffix(".json")

        if out_path.exists() and not force:
            # Still need to return the work metadata; read it from the saved file
            import json
            try:
                saved = json.loads(out_path.read_text(encoding="utf-8"))
                works.append(Work(**saved["work"]))
            except Exception:
                pass
            continue

        # Read author name from __cts__.xml in the author directory
        author_cts = xml_path.parents[1] / "__cts__.xml"
        author_name = _read_author_name(author_cts) if author_cts.exists() else None

        result = _parse_pta_file(xml_path, author_name)
        if result is None:
            skipped += 1
            continue

        work, paragraphs = result

        if not paragraphs:
            log.debug("No paragraphs extracted from %s — skipping", xml_path)
            skipped += 1
            continue

        out_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        payload = {"work": work.model_dump(), "paragraphs": paragraphs}
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        works.append(work)

    log.info(
        "PTA ingestion complete: %d works written, %d skipped",
        len(works),
        skipped,
    )
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
