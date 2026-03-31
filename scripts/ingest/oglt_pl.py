"""
Ingestor for the OGLT Patrologia Latina (OpenGreekAndLatin).

Source: https://github.com/OpenGreekAndLatin/patrologia_latina-dev
Format: TEI/EpiDoc XML, Migne Patrologia Latina volumes
License: CC-BY-SA 4.0

Acquisition
-----------
Shallow-clone the repo into ``data/raw/patristic/oglt_pl/`` using git.
On ``force=True`` we pull the latest changes.

File selection
--------------
We prefer the ``split/`` directory (one work per XML file).  If ``split/``
is absent or empty we fall back to ``corrected/`` (one volume per file;
each work is still encoded as a distinct ``<div>`` within the volume).

Filtering
---------
- Works with ``date_range[0] > 1054`` are skipped (post-schism).
- If dates cannot be extracted from the header, we try a substring-match
  of the author name against ``_patristic_meta.AUTHORS``.
- Default: include when uncertain (``post_schism = False``).

Canonical references
--------------------
``{work_prefix}.{div_n_path}.{para_index}``

Where *work_prefix* is derived from the CTS URN if present, otherwise from
the filename stem (``PL67_48_HO`` → ``PL67.HO``).
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

from lxml import etree
from tqdm import tqdm

from patristica.models import DateConfidence, Work
from scripts.ingest._common import slugify_ref
from scripts.ingest._patristic_meta import AUTHORS

log = logging.getLogger(__name__)

SOURCE_ID = "patristic/oglt-pl"

_REPO_URL = "https://github.com/OpenGreekAndLatin/patrologia_latina-dev.git"

_TEI = "http://www.tei-c.org/ns/1.0"
_XML_NS = "http://www.w3.org/XML/1998/namespace"

_SCHISM_YEAR = 1054

_STRUCTURAL_DIV_TYPES = frozenset({
    "textpart", "book", "chapter", "section", "part",
    "epistle", "sermon", "commentary", "prologue", "appendix",
    "praefatio", "fragment", "inscription",
})

_SKIP_ELEMENTS = frozenset({
    "head", "note", "pb", "lb", "cb", "fw", "figure",
    "table", "speaker", "stage",
})

# Regex to extract a usable work prefix from PL filenames like PL67_48_HO.xml
_PL_FILENAME_RE = re.compile(r"(PL\d+)(?:_\d+)?_([A-Z]+)", re.IGNORECASE)


def _ensure_repo(repo_dir: Path, force: bool) -> None:
    """Clone the patrologia_latina-dev repo if absent; pull latest on force."""
    if not repo_dir.exists():
        log.info("Cloning OGLT Patrologia Latina repo into %s …", repo_dir)
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth=1", _REPO_URL, str(repo_dir)],
            check=True,
        )
    elif force:
        log.info("Pulling latest OGLT PL data …")
        subprocess.run(
            ["git", "-C", str(repo_dir), "pull", "--ff-only"],
            check=True,
        )


def _extract_dates(
    root: etree._Element,
) -> tuple[int | None, tuple[int, int] | None, DateConfidence]:
    """Extract composition dates from teiHeader/profileDesc/creation/date."""
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


def _lookup_author_dates(
    author_name: str,
) -> tuple[int | None, tuple[int, int] | None, DateConfidence]:
    """Try to find date info for *author_name* from the patristic metadata table."""
    name_lower = author_name.lower()
    for meta in AUTHORS.values():
        if meta.full_name.lower() in name_lower or name_lower in meta.full_name.lower():
            birth, death = meta.dates
            return death, (birth, death), "approximate"
    return None, None, "uncertain"


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
    work_prefix: str,
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
                ref = slugify_ref(".".join([work_prefix] + path_parts))
                records.append({"ref": ref, "text": text})
            return

        if tag == "l":
            # Verse line — collect a group of lines into one paragraph record
            # (handled by parent <lg> below)
            text = _element_inner_text(element).strip()
            text = re.sub(r"\s+", " ", text)
            if text:
                ref = slugify_ref(".".join([work_prefix] + path_parts))
                records.append({"ref": ref, "text": text})
            return

        if tag == "div":
            div_type = element.get("type", "")
            if div_type in _STRUCTURAL_DIV_TYPES or div_type == "":
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

    # Deduplicate refs
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


def _work_prefix_from_filename(xml_path: Path) -> str:
    """Derive a stable work prefix from a PL filename like ``PL67_48_HO.xml``."""
    m = _PL_FILENAME_RE.search(xml_path.stem)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    # Fall back to the stem with non-alphanumeric chars replaced by dots
    return re.sub(r"[^A-Za-z0-9]+", ".", xml_path.stem).strip(".")


def _parse_oglt_pl_file(
    xml_path: Path,
) -> tuple[Work, list[dict[str, str]]] | None:
    """Parse a single OGLT PL TEI/EpiDoc file.

    Returns ``(Work, paragraphs)`` or ``None`` if the file should be skipped.
    """
    try:
        tree = etree.parse(str(xml_path))
    except etree.XMLSyntaxError as exc:
        log.warning("XML parse error in %s: %s", xml_path, exc)
        return None

    root = tree.getroot()
    ns = {"tei": _TEI}

    # --- Title & Author ---
    # titleStmt/title is often empty or a generic "Patrologiae Cursus Completus" header.
    # titleStmt/author is always a placeholder <author ref="urn:tmp"/> with no text.
    # The real metadata lives in sourceDesc/listBibl/biblStruct/monogr — take the first
    # non-empty author and title found there.
    title_el = root.find(".//tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", ns)
    title = (title_el.text or "").strip() if title_el is not None else ""

    author: str | None = None

    # Try sourceDesc monogr for both author and title
    for monogr_el in root.findall(".//tei:teiHeader/tei:fileDesc/tei:sourceDesc//tei:monogr", ns):
        if author is None:
            auth_el = monogr_el.find("tei:author", ns)
            if auth_el is not None:
                candidate = (auth_el.text or "").strip()
                if candidate:
                    author = candidate
        if not title or re.search(r"patrologiae\s+cursus\s+completus", title, re.IGNORECASE):
            t_el = monogr_el.find("tei:title", ns)
            if t_el is not None:
                candidate = (t_el.text or "").strip()
                if candidate and not re.search(r"patrologiae\s+cursus\s+completus", candidate, re.IGNORECASE):
                    title = candidate
        if author and title:
            break

    # Final fallback: filename stem (e.g. "PL10_10_56" — stable volume+column identifier)
    if not title or re.search(r"patrologiae\s+cursus\s+completus", title, re.IGNORECASE):
        title = xml_path.stem

    # --- Body element ---
    edition_div = root.find(".//tei:text/tei:body/tei:div[@type='edition']", ns)
    body_el = edition_div if edition_div is not None else root.find(".//tei:text/tei:body", ns)
    if body_el is None:
        log.debug("No body content in %s — skipping", xml_path)
        return None

    # --- CTS URN for work prefix ---
    cts_urn = ""
    if edition_div is not None:
        cts_urn = edition_div.get("n", "")
    if not cts_urn:
        text_el = root.find(".//tei:text", ns)
        if text_el is not None:
            cts_urn = text_el.get(f"{{{_XML_NS}}}base", "")

    # work_id: use author slug + filename stem for a stable, human-readable identifier.
    # The filename (e.g. PL12_0_SAN) is unique per file and encodes PL volume + column,
    # so collision-free even when multiple files share the same author/title.
    author_slug = re.sub(r"[^a-z0-9]+", "-", (author or "unknown").lower()).strip("-")
    work_id = f"oglt_pl/{author_slug}/{xml_path.stem.lower()}"

    # work_prefix for canonical refs: derive from CTS URN if proper, else from filename.
    if cts_urn and cts_urn.startswith("urn:cts:"):
        cts_local = cts_urn.rsplit(":", 1)[-1]
        cts_parts = cts_local.split(".")
        a_id = cts_parts[0] if len(cts_parts) > 0 else ""
        w_id = cts_parts[1] if len(cts_parts) > 1 else ""
        work_prefix = f"{a_id}.{w_id}" if (a_id and w_id) else _work_prefix_from_filename(xml_path)
    else:
        work_prefix = _work_prefix_from_filename(xml_path)

    provenance_url = f"https://github.com/OpenGreekAndLatin/patrologia_latina-dev/blob/master/split/{xml_path.name}"

    # --- Dates ---
    date_composed, date_range, date_confidence = _extract_dates(root)
    if date_composed is None and author:
        date_composed, date_range, date_confidence = _lookup_author_dates(author)

    # Post-schism filter
    if date_range is not None and date_range[0] > _SCHISM_YEAR:
        log.debug("Skipping post-schism work %s (date_range=%s)", work_id, date_range)
        return None
    post_schism = bool(date_composed is not None and date_composed > _SCHISM_YEAR)

    work = Work(
        work_id=work_id,
        source_id=SOURCE_ID,
        author=author,
        title=title,
        date_composed=date_composed,
        date_range=date_range,
        date_confidence=date_confidence,
        genre="patristic",
        language="lat",
        tradition="latin",
        license="cc-by-sa-4.0",
        provenance_url=provenance_url,
        edition=None,
        translation_of=None,
    )

    paragraphs = _extract_paragraphs(body_el, work_prefix, ns)
    return work, paragraphs


def _collect_xml_files(repo_dir: Path) -> list[Path]:
    """Return the list of XML files to process, preferring ``split/`` over ``corrected/``."""
    split_dir = repo_dir / "split"
    corrected_dir = repo_dir / "corrected"

    split_files = sorted(split_dir.rglob("*.xml")) if split_dir.exists() else []
    # Filter out __cts__.xml and catalog files
    split_files = [p for p in split_files if p.name != "__cts__.xml"]

    if split_files:
        log.info("Using split/ directory: %d XML files found", len(split_files))
        return split_files

    corrected_files = sorted(corrected_dir.rglob("*.xml")) if corrected_dir.exists() else []
    corrected_files = [p for p in corrected_files if p.name != "__cts__.xml"]

    if corrected_files:
        log.info("split/ empty/absent — falling back to corrected/: %d XML files", len(corrected_files))
        return corrected_files

    # Last resort: scan entire repo
    all_files = [
        p for p in sorted(repo_dir.rglob("*.xml"))
        if p.name != "__cts__.xml"
        and not any(part.startswith(".") for part in p.parts)
    ]
    log.info("No split/ or corrected/ found — scanning repo: %d XML files", len(all_files))
    return all_files


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Clone/pull the OGLT PL repo and ingest all Latin text editions.

    Parameters
    ----------
    output_dir: Root raw output directory (``data/raw``).
    force:      If True, pull latest git changes before processing.

    Returns
    -------
    List of ``Work`` records written.
    """
    repo_dir = output_dir / "patristic" / "oglt_pl"
    _ensure_repo(repo_dir, force)

    xml_files = _collect_xml_files(repo_dir)
    if not xml_files:
        raise FileNotFoundError(f"No XML files found in {repo_dir}")

    log.info("Found %d OGLT PL text files to process", len(xml_files))

    works: list[Work] = []
    skipped = 0

    for xml_path in tqdm(xml_files, desc="OGLT PL ingest"):
        rel = xml_path.relative_to(repo_dir)
        out_path = output_dir / "patristic" / "oglt_pl" / rel.with_suffix(".json")

        if out_path.exists() and not force:
            try:
                saved = json.loads(out_path.read_text(encoding="utf-8"))
                works.append(Work(**saved["work"]))
            except Exception:
                pass
            continue

        result = _parse_oglt_pl_file(xml_path)
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

    log.info(
        "OGLT PL ingestion complete: %d works written, %d skipped",
        len(works),
        skipped,
    )
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
