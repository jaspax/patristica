"""
Ingestor for Perseus Digital Library canonical Greek and Latin texts.

Sources
-------
- Greek: https://github.com/PerseusDL/canonical-greekLit
- Latin: https://github.com/PerseusDL/canonical-latinLit

Format: TEI P5 XML, organised by CTS URN (author_id/work_id/)
License: CC-BY-SA 4.0 per-file (some files are CC-BY 4.0)

Deduplication
-------------
Greek texts already processed by First1KGreek are skipped; First1K uses
newer editions of the same TLG texts.  Dedup is based on the CTS work ID
(e.g. ``tlg0001.tlg001``).  Latin texts have no equivalent overlap source,
so all passing the date filter are included.

Date filtering
--------------
Same as First1KGreek:
- Skip works with a confidently-established composition date before −50 CE
  (removes classical pagan literature; uncertain-date works are included)
- Skip works where ``date_range[0] > 1054`` (post-schism)

Canonical references
--------------------
``{author_id}.{work_id_short}.{div_n_path}``
e.g. ``tlg0001.tlg001.1.3``
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

from lxml import etree
from tqdm import tqdm

from patristica.models import DateConfidence, Language, License, Tradition, Work
from scripts.ingest._common import slugify_ref

log = logging.getLogger(__name__)

SOURCE_ID = "patristic/perseus"

_GREEK_REPO_URL = "https://github.com/PerseusDL/canonical-greekLit.git"
_LATIN_REPO_URL = "https://github.com/PerseusDL/canonical-latinLit.git"

_TEI = "http://www.tei-c.org/ns/1.0"
_XML_NS = "http://www.w3.org/XML/1998/namespace"

_SCHISM_YEAR = 1054
_CLASSICAL_CUTOFF = -50

_STRUCTURAL_DIV_TYPES = frozenset({
    "textpart", "book", "chapter", "section", "part",
    "act", "scene", "poem", "stanza", "fragment", "hypothesis",
    "praefatio", "epistle", "prologue", "appendix",
})

_SKIP_ELEMENTS = frozenset({
    "head", "note", "pb", "lb", "cb", "fw", "figure",
    "table", "speaker", "stage",
})

# Parser that never tries to fetch remote DTDs (Perseus files reference
# http://www.perseus.tufts.edu/DTD/... which is unavailable offline).
_XML_PARSER = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False)


def _ensure_repo(repo_dir: Path, repo_url: str, label: str, force: bool) -> None:
    """Clone a repo if absent; pull latest on force."""
    if not repo_dir.exists():
        log.info("Cloning %s repo into %s …", label, repo_dir)
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth=1", repo_url, str(repo_dir)],
            check=True,
        )
    elif force:
        log.info("Pulling latest %s data …", label)
        subprocess.run(
            ["git", "-C", str(repo_dir), "pull", "--ff-only"],
            check=True,
        )


def _build_first1k_ids(raw_dir: Path) -> set[str]:
    """Return the set of CTS work IDs already present in First1KGreek output.

    Scans ``data/raw/patristic/first1k/`` for JSON files and extracts the
    ``{author_id}.{work_id_short}`` pair from each filename stem.
    """
    first1k_dir = raw_dir / "patristic" / "first1k"
    if not first1k_dir.exists():
        log.debug("First1KGreek output not found at %s; dedup disabled", first1k_dir)
        return set()
    ids: set[str] = set()
    for p in first1k_dir.rglob("*.json"):
        stem = p.stem  # e.g. "tlg0001.tlg001.1st1K-grc1"
        parts = stem.split(".")
        if len(parts) >= 2 and parts[0].startswith("tlg") and parts[1].startswith("tlg"):
            ids.add(f"{parts[0]}.{parts[1]}")
    log.debug("Built First1KGreek dedup set: %d work IDs", len(ids))
    return ids


def _read_author_name_from_cts(cts_path: Path) -> str | None:
    """Extract the English author name from a ``__cts__.xml`` catalog file."""
    _CTS_NS = "http://chs.harvard.edu/xmlns/cts"
    try:
        tree = etree.parse(str(cts_path), _XML_PARSER)
        root = tree.getroot()
        ns = {"ti": _CTS_NS}
        for el in root.findall(".//ti:groupname", ns):
            if el.get(f"{{{_XML_NS}}}lang") == "eng":
                return (el.text or "").strip() or None
        el = root.find(".//ti:groupname", ns)
        if el is not None:
            return (el.text or "").strip() or None
    except Exception as exc:
        log.debug("Could not read %s: %s", cts_path, exc)
    return None


def _extract_dates(
    root: etree._Element,
) -> tuple[int | None, tuple[int, int] | None, DateConfidence]:
    """Extract composition date info from teiHeader/profileDesc/creation/date."""
    ns = {"tei": _TEI}
    date_el = root.find(".//tei:profileDesc/tei:creation/tei:date", ns)
    if date_el is None:
        return None, None, "uncertain"

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
    else:
        date_composed = y_after

    return date_composed, date_range, "approximate"


def _parse_license(root: etree._Element) -> License:
    """Extract license from teiHeader, defaulting to cc-by-sa-4.0."""
    ns = {"tei": _TEI}
    for lic_el in root.findall(".//tei:availability/tei:licence", ns):
        target = lic_el.get("target", "")
        if "by-nc-sa" in target:
            return "cc-by-nc-sa-4.0"
        if "by-sa" in target:
            return "cc-by-sa-4.0"
        if "by-nc" in target:
            return "cc-by-nc-4.0"
        if "by" in target:
            return "cc-by-4.0"
    return "cc-by-sa-4.0"


def _element_inner_text(el: etree._Element) -> str:
    """Collect all text inside an element, stripping child element tags."""
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        parts.append(_element_inner_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _extract_paragraphs(
    body_el: etree._Element,
    work_cts_id: str,
    ns: dict[str, str],
) -> list[dict[str, str]]:
    """Recursively extract paragraphs from a TEI body or edition div."""
    records: list[dict[str, str]] = []

    def _walk(element: etree._Element, path_parts: list[str]) -> None:
        tag = etree.QName(element.tag).localname if element.tag != etree.Comment else ""

        if tag in ("p", "ab"):
            text = _element_inner_text(element).strip()
            text = re.sub(r"\s+", " ", text)
            if text:
                ref = slugify_ref(".".join([work_cts_id] + path_parts))
                records.append({"ref": ref, "text": text})
            return

        if tag == "div":
            div_type = element.get("type", "")
            if div_type in _STRUCTURAL_DIV_TYPES:
                n = element.get("n", "")
                new_parts = path_parts + [n] if n and re.match(r"^[\w\-]+$", n) else path_parts
                for child in element:
                    _walk(child, new_parts)
                return

        if tag not in _SKIP_ELEMENTS:
            for child in element:
                _walk(child, path_parts)

    for child in body_el:
        _walk(child, [])

    # Deduplicate refs by appending a counter
    seen: dict[str, int] = {}
    result: list[dict[str, str]] = []
    for rec in records:
        ref = rec["ref"]
        if ref not in seen:
            seen[ref] = 0
            result.append(rec)
        else:
            seen[ref] += 1
            result.append({"ref": f"{ref}.{seen[ref]}", "text": rec["text"]})

    return result


def _detect_language_from_path(xml_path: Path, repo_lang: str) -> str | None:
    """Return expected language code based on repo type and filename edition suffix.

    ``repo_lang`` is ``"grc"`` for the Greek repo or ``"lat"`` for the Latin repo.
    Returns None if the file's edition suffix indicates a different language.
    """
    stem = xml_path.stem  # e.g. "tlg0001.tlg001.perseus-grc1" or "phi0448.phi001.perseus-lat2"
    parts = stem.split(".")
    if len(parts) >= 3:
        version = parts[2].lower()
        if repo_lang == "grc":
            if re.search(r"grc", version):
                return "grc"
            if re.search(r"lat\d|eng\d|ara\d|heb\d|syr\d|cop\d", version):
                return None  # skip non-Greek editions in the Greek repo
            return "grc"  # ambiguous: assume Greek for greekLit repo
        else:  # lat repo
            if re.search(r"lat", version):
                return "lat"
            if re.search(r"grc\d|eng\d|ara\d", version):
                return None  # skip non-Latin editions in the Latin repo
            return "lat"  # ambiguous: assume Latin for latinLit repo
    # No edition suffix — use repo default
    return repo_lang


def _parse_perseus_file(
    xml_path: Path,
    repo_lang: str,
    author_name: str | None,
    first1k_ids: set[str],
) -> tuple[Work, list[dict[str, str]]] | None:
    """Parse a single Perseus TEI file.

    Returns ``(Work, paragraphs)`` or ``None`` if the file should be skipped.
    """
    # Language check by filename before parsing
    lang_code = _detect_language_from_path(xml_path, repo_lang)
    if lang_code is None:
        return None

    try:
        tree = etree.parse(str(xml_path), _XML_PARSER)
    except (etree.XMLSyntaxError, OSError) as exc:
        log.warning("XML parse error in %s: %s", xml_path, exc)
        return None

    root = tree.getroot()
    ns = {"tei": _TEI}

    # --- CTS URN → work identifiers ---
    edition_div = root.find(".//tei:text/tei:body/tei:div[@type='edition']", ns)
    body_el = edition_div if edition_div is not None else root.find(".//tei:text/tei:body", ns)
    if body_el is None:
        log.debug("No body content in %s — skipping", xml_path)
        return None

    cts_urn = ""
    if edition_div is not None:
        cts_urn = edition_div.get("n", "")
    if not cts_urn:
        text_el = root.find(".//tei:text", ns)
        if text_el is not None:
            cts_urn = text_el.get(f"{{{_XML_NS}}}base", "")
    if not cts_urn:
        stem = xml_path.stem
        parts = stem.split(".")
        author_id = parts[0] if len(parts) > 0 else xml_path.parts[-3]
        work_id_short = parts[1] if len(parts) > 1 else xml_path.parts[-2]
        version = parts[2] if len(parts) > 2 else ""
    else:
        cts_local = cts_urn.rsplit(":", 1)[-1]
        cts_parts = cts_local.split(".")
        author_id = cts_parts[0] if len(cts_parts) > 0 else xml_path.parts[-3]
        work_id_short = cts_parts[1] if len(cts_parts) > 1 else xml_path.parts[-2]
        version = cts_parts[2] if len(cts_parts) > 2 else ""

    work_cts_id = f"{author_id}.{work_id_short}"

    # Deduplication: skip if First1KGreek already has this work
    if work_cts_id in first1k_ids:
        log.debug("Skipping %s — already in First1KGreek", work_cts_id)
        return None

    # --- Language from XML (authoritative over filename) ---
    lang_el = edition_div if edition_div is not None else root.find(".//tei:text", ns)
    xml_lang = lang_el.get(f"{{{_XML_NS}}}lang", "") if lang_el is not None else ""
    if xml_lang:
        if "grc" in xml_lang:
            language: Language = "grc"
            tradition: Tradition = "greek"
        elif "lat" in xml_lang:
            language = "lat"
            tradition = "latin"
        else:
            log.debug("Non-Greek/Latin language %r in %s — skipping", xml_lang, xml_path)
            return None
    else:
        language = lang_code  # type: ignore[assignment]
        tradition = "greek" if lang_code == "grc" else "latin"

    # --- Dates ---
    date_composed, date_range, date_confidence = _extract_dates(root)

    # Classical filter
    if date_composed is not None and date_confidence != "uncertain" and date_composed < _CLASSICAL_CUTOFF:
        log.debug(
            "Skipping classical work %s (date_composed=%s, confidence=%s)",
            work_cts_id, date_composed, date_confidence,
        )
        return None

    # Post-schism filter
    if date_range is not None and date_range[0] > _SCHISM_YEAR:
        log.debug("Skipping post-schism work %s (date_range=%s)", work_cts_id, date_range)
        return None

    # --- Title ---
    title_el = root.find(".//tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", ns)
    title = (title_el.text or "").strip() if title_el is not None else xml_path.stem

    # --- Author ---
    author_el = root.find(".//tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author", ns)
    author_from_file = (author_el.text or "").strip() if author_el is not None else None
    author = author_name or author_from_file

    # --- License ---
    license_ = _parse_license(root)

    work_id = f"perseus/{author_id}/{work_id_short}"
    if version:
        work_id = f"{work_id}/{version}"

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
        license=license_,
        provenance_url=(
            f"https://github.com/PerseusDL/canonical-{'greekLit' if lang_code == 'grc' else 'latinLit'}"
            f"/blob/master/data/{author_id}/{work_id_short}/{xml_path.name}"
        ),
        edition=version or None,
        translation_of=None,
    )

    paragraphs = _extract_paragraphs(body_el, work_cts_id, ns)
    return work, paragraphs


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Clone/pull both Perseus repos and ingest all Greek and Latin text editions.

    Parameters
    ----------
    output_dir: Root raw output directory (``data/raw``).
    force:      If True, pull latest git changes before processing.
    """
    # Store repos under _repos/ (alongside _zips/ and _csvs/) so they don't
    # appear as spurious source IDs in the catalog.
    greek_repo_dir = output_dir / "_repos" / "perseus-greeklit"
    latin_repo_dir = output_dir / "_repos" / "perseus-latinlit"

    _ensure_repo(greek_repo_dir, _GREEK_REPO_URL, "Perseus canonical-greekLit", force)
    _ensure_repo(latin_repo_dir, _LATIN_REPO_URL, "Perseus canonical-latinLit", force)

    first1k_ids = _build_first1k_ids(output_dir)

    repo_specs: list[tuple[Path, str]] = [
        (greek_repo_dir, "grc"),
        (latin_repo_dir, "lat"),
    ]

    works: list[Work] = []
    total_skipped = 0

    for repo_dir, repo_lang in repo_specs:
        data_dir = repo_dir / "data"
        if not data_dir.exists():
            log.warning("Expected Perseus data directory not found at %s", data_dir)
            continue

        xml_files = [
            p for p in sorted(data_dir.rglob("*.xml"))
            if p.name != "__cts__.xml"
        ]

        log.info(
            "Found %d Perseus %s files to process",
            len(xml_files),
            "Greek" if repo_lang == "grc" else "Latin",
        )
        skipped = 0

        for xml_path in tqdm(xml_files, desc=f"Perseus {repo_lang} ingest"):
            rel = xml_path.relative_to(data_dir)
            out_path = output_dir / "patristic" / "perseus" / rel.with_suffix(".json")

            if out_path.exists() and not force:
                try:
                    saved = json.loads(out_path.read_text(encoding="utf-8"))
                    works.append(Work(**saved["work"]))
                except Exception:
                    pass
                continue

            # Author name from __cts__.xml two levels up (textgroup dir)
            author_cts = xml_path.parents[1] / "__cts__.xml"
            author_name = _read_author_name_from_cts(author_cts) if author_cts.exists() else None

            result = _parse_perseus_file(xml_path, repo_lang, author_name, first1k_ids)
            if result is None:
                skipped += 1
                continue

            work, paragraphs = result
            if not paragraphs:
                log.debug("No paragraphs extracted from %s — skipping", xml_path)
                skipped += 1
                continue

            out_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"work": work.model_dump(), "paragraphs": paragraphs}
            out_path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            works.append(work)

        total_skipped += skipped
        log.info(
            "Perseus %s ingestion: %d works written, %d skipped",
            "Greek" if repo_lang == "grc" else "Latin",
            sum(1 for w in works if w.language == ("grc" if repo_lang == "grc" else "lat")),
            skipped,
        )

    log.info(
        "Perseus ingestion complete: %d total works, %d total skipped",
        len(works),
        total_skipped,
    )
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
