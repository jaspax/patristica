"""
Ingestor for First1KGreek (OpenGreekAndLatin).

Source: https://github.com/OpenGreekAndLatin/First1KGreek
Format: TEI P5 XML, organised by TLG number (tlg{NNNN}/tlg{NNN}/)
License: CC-BY-SA 4.0

Acquisition
-----------
Shallow-clone the repo into ``data/raw/patristic/first1k/`` using git.
On ``force=True`` we pull the latest changes.

File filtering
--------------
We process only Greek-language files (xml:lang="grc" on the edition div) and skip:

- ``__cts__.xml``  — CTS catalog metadata
- Textgroups not in ``_cts_scope.IN_SCOPE_AUTHOR_IDS`` — most of the repo is
  classical/pagan (Galen, Libanius, Aristotle, scholia …); we keep only
  Christian/Jewish first-millennium literature
- Files whose version suffix is not ``grc`` (e.g. ``-lat1``, ``-eng1``, ``-ger1``)
- Works with ``date_composed < −50`` CE or dated after the collection period
  (``patristica.period``) — note that
  First1KGreek headers carry no ``creation/date``, so these rarely fire and the
  author allowlist does the real filtering

Canonical references
--------------------
``{author_id}.{work_id_short}.{div_n_path}.{para_index}``

e.g. ``tlg0559.tlg002.1.3`` (Justin Martyr, Second Apology, book 1, paragraph 3)
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
from patristica.period import work_in_period
from scripts.ingest._common import dedupe_refs, slugify_ref
from scripts.ingest._cts_scope import (
    author_id_from_path,
    edition_matches_language,
    is_in_scope,
    prune_out_of_scope,
)

log = logging.getLogger(__name__)

SOURCE_ID = "patristic/first1k"

_REPO_URL = "https://github.com/OpenGreekAndLatin/First1KGreek.git"

_TEI = "http://www.tei-c.org/ns/1.0"
_CTS_NS = "http://chs.harvard.edu/xmlns/cts"
_XML_NS = "http://www.w3.org/XML/1998/namespace"

# Skip works with a confidently-established composition date before this year.
# Keeps Philo, Josephus, all Christian authors; removes most classical pagan lit.
_CLASSICAL_CUTOFF = -50

# Div @type values that represent structural hierarchy levels (not semantic metadata).
_STRUCTURAL_DIV_TYPES = frozenset({
    "textpart", "book", "chapter", "section", "part",
    "act", "scene", "poem", "stanza", "fragment", "hypothesis",
    "praefatio", "epistle", "prologue", "appendix",
})

# Elements to suppress entirely (do not recurse or emit)
_SKIP_ELEMENTS = frozenset({
    "head", "note", "pb", "lb", "cb", "fw", "figure",
    "table", "speaker", "stage",
})


def _ensure_repo(repo_dir: Path, force: bool) -> None:
    """Clone the First1KGreek repo if absent; pull latest on force."""
    if not repo_dir.exists():
        log.info("Cloning First1KGreek repo into %s …", repo_dir)
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["git", "clone", "--depth=1", _REPO_URL, str(repo_dir)],
            check=True,
        )
    elif force:
        log.info("Pulling latest First1KGreek data …")
        subprocess.run(
            ["git", "-C", str(repo_dir), "pull", "--ff-only"],
            check=True,
        )


def _read_author_name(cts_path: Path) -> str | None:
    """Extract the English author name from a ``__cts__.xml`` catalog file."""
    try:
        tree = etree.parse(str(cts_path))
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


def _element_inner_text(el: etree._Element) -> str:
    """Collect all text inside an element, stripping child element tags."""
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        if child.tag is etree.Comment or child.tag is etree.ProcessingInstruction:
            if child.tail:
                parts.append(child.tail)
            continue
        local = etree.QName(child.tag).localname
        if local in _SKIP_ELEMENTS:
            if child.tail:
                parts.append(child.tail)
            continue
        parts.append(_element_inner_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _extract_paragraphs(
    body_el: etree._Element,
    work_cts_id: str,
    ns: dict[str, str],
) -> list[dict[str, str]]:
    """Recursively extract paragraphs from a TEI body or edition div.

    Handles both ``type="textpart"`` (PTA-style) and named div types used
    by First1KGreek (``type="book"``, ``type="chapter"``, ``type="section"``, etc.).
    """
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

    return dedupe_refs(records)


def _is_grc_file(xml_path: Path) -> bool:
    """Return True if this file looks like a Greek-language edition by name.

    Multilingual (``-mul``) or suffix-less files pass; the ``xml:lang`` check
    in the parser decides those.
    """
    return edition_matches_language(xml_path, "grc")


def _parse_first1k_file(
    xml_path: Path,
    author_name: str | None,
) -> tuple[Work, list[dict[str, str]]] | None:
    """Parse a single First1KGreek TEI file.

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

    # --- Find body element for text extraction ---
    # Prefer <div type="edition">, fall back to <body>
    edition_div = root.find(".//tei:text/tei:body/tei:div[@type='edition']", ns)
    body_el = edition_div if edition_div is not None else root.find(".//tei:text/tei:body", ns)
    if body_el is None:
        log.debug("No body content in %s — skipping", xml_path)
        return None

    # --- Language ---
    lang_el = edition_div if edition_div is not None else root.find(".//tei:text", ns)
    xml_lang = (lang_el.get(f"{{{_XML_NS}}}lang", "") if lang_el is not None else "")
    if not xml_lang:
        xml_lang = "grc"  # First1KGreek is primarily Greek; default to grc
    language: Language = "grc" if "grc" in xml_lang else None  # type: ignore[assignment]
    if language is None:
        log.debug("Non-Greek language %r in %s — skipping", xml_lang, xml_path)
        return None
    tradition: Tradition = "greek"

    # --- CTS URN → work identifiers ---
    # Try edition div @n first, then <text @xml:base>
    cts_urn = ""
    if edition_div is not None:
        cts_urn = edition_div.get("n", "")
    if not cts_urn:
        text_el = root.find(".//tei:text", ns)
        if text_el is not None:
            cts_urn = text_el.get(f"{{{_XML_NS}}}base", "")
    if not cts_urn:
        # Derive from filename: tlg0001.tlg001.1st1K-grc1.xml
        stem = xml_path.stem
        parts = stem.split(".")
        author_id = parts[0] if len(parts) > 0 else xml_path.parts[-3]
        work_id_short = parts[1] if len(parts) > 1 else xml_path.parts[-2]
        version = parts[2] if len(parts) > 2 else ""
    else:
        # e.g. "urn:cts:greekLit:tlg0001.tlg001.1st1K-grc1"
        cts_local = cts_urn.rsplit(":", 1)[-1]
        cts_parts = cts_local.split(".")
        author_id = cts_parts[0] if len(cts_parts) > 0 else xml_path.parts[-3]
        work_id_short = cts_parts[1] if len(cts_parts) > 1 else xml_path.parts[-2]
        version = cts_parts[2] if len(cts_parts) > 2 else ""

    work_cts_id = f"{author_id}.{work_id_short}"
    work_id = f"first1k/{author_id}/{work_id_short}"
    if version:
        work_id = f"{work_id}/{version}"

    # --- Dates ---
    date_composed, date_range, date_confidence = _extract_dates(root)

    # Classical filter: skip if confidently composed before −50 CE
    if date_composed is not None and date_confidence != "uncertain" and date_composed < _CLASSICAL_CUTOFF:
        log.debug(
            "Skipping classical work %s (date_composed=%s, confidence=%s)",
            work_cts_id, date_composed, date_confidence,
        )
        return None

    if not work_in_period(date_range):
        log.debug("Skipping work after the collection period %s (date_range=%s)",
                  work_cts_id, date_range)
        return None

    # --- Author ---
    author_el = root.find(".//tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author", ns)
    author_from_file = (author_el.text or "").strip() if author_el is not None else None
    author = author_name or author_from_file

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
        license="cc-by-sa-4.0",
        provenance_url=f"https://github.com/OpenGreekAndLatin/First1KGreek/blob/master/data/{author_id}/{work_id_short}/{xml_path.name}",
        edition=version or None,
        translation_of=None,
    )

    paragraphs = _extract_paragraphs(body_el, work_cts_id, ns)
    return work, paragraphs


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Clone/pull the First1KGreek repo and ingest all Greek text editions.

    Parameters
    ----------
    output_dir: Root raw output directory (``data/raw``).
    force:      If True, pull latest git changes before processing.

    Returns
    -------
    List of ``Work`` records written.
    """
    repo_dir = output_dir / "patristic" / "first1k"
    _ensure_repo(repo_dir, force)

    data_dir = repo_dir / "data"
    if not data_dir.exists():
        raise FileNotFoundError(f"Expected First1KGreek data directory at {data_dir}")

    xml_files = [
        p for p in sorted(data_dir.rglob("*.xml"))
        if p.name != "__cts__.xml"
        and is_in_scope(author_id_from_path(p, data_dir))
        and _is_grc_file(p)
    ]

    pruned = prune_out_of_scope(repo_dir, ("grc",))
    if pruned:
        log.info("Removed %d previously ingested out-of-scope First1KGreek files", pruned)

    log.info("Found %d First1KGreek text files to process", len(xml_files))

    works: list[Work] = []
    skipped = 0

    for xml_path in tqdm(xml_files, desc="First1KGreek ingest"):
        rel = xml_path.relative_to(data_dir)
        out_path = output_dir / "patristic" / "first1k" / rel.with_suffix(".json")

        if out_path.exists() and not force:
            try:
                saved = json.loads(out_path.read_text(encoding="utf-8"))
                works.append(Work(**saved["work"]))
            except Exception:
                pass
            continue

        # Read author name from __cts__.xml two levels up (textgroup dir)
        author_cts = xml_path.parents[1] / "__cts__.xml"
        author_name = _read_author_name(author_cts) if author_cts.exists() else None

        result = _parse_first1k_file(xml_path, author_name)
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
        "First1KGreek ingestion complete: %d works written, %d skipped",
        len(works),
        skipped,
    )
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
