"""
Shared utilities for CCEL ANF/NPNF ingestion.

CCEL (Christian Classics Ethereal Library) hosts the Ante-Nicene Fathers and
Nicene & Post-Nicene Fathers translation series in ThML format — an XML-based
theological markup language.

ThML structure overview
-----------------------
- ``<ThML.body>`` (or ``<body>``) — top-level text container
- ``<div1 type="Book">`` — typically one treatise or author section per volume
- ``<div2 type="Chapter">`` / ``<div3 type="Section">`` — hierarchy within a work
- ``<head>`` — section title (first child of each div)
- ``<p>`` — text paragraphs
- ``<scripRef>`` — inline Scripture citation (strip element, keep surrounding text)
- ``<note>`` / ``<pb>`` — footnotes / page breaks (discard entirely)

Each volume XML file contains multiple works separated by ``<div1>`` boundaries.
One Work record is produced per ``<div1>``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from lxml import etree

from patristica.models import DateConfidence, License, Tradition, Work
from scripts.ingest._common import download_file, slugify_ref
from scripts.ingest._patristic_meta import AUTHORS, AuthorMeta

log = logging.getLogger(__name__)

_CCEL_BASE_URL = "https://ccel.org/ccel/s/schaff"
_SCHISM_YEAR = 1054

# ThML elements to skip entirely (discard text content and children)
_SKIP_LOCAL_NAMES = frozenset({
    "note", "pb", "lb", "cb", "fw", "figure", "table",
    "speaker", "stage", "milestone", "bibl", "index",
    "teiHeader", "header",
})

# ThML elements whose tags should be stripped but whose text content is kept
_INLINE_LOCAL_NAMES = frozenset({
    "scripRef", "scripture", "a", "abbr", "span", "i", "b", "em", "strong",
    "hi", "term", "name", "persName", "placeName", "q", "foreign", "title",
    "author", "publisher", "date",
})


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_volume(volume_id: str, cache_dir: Path, force: bool = False) -> Path:
    """Download a CCEL ThML XML file, using ETag caching.

    Parameters
    ----------
    volume_id:  Volume identifier, e.g. ``"anf01"`` or ``"npnf101"``.
    cache_dir:  Directory to cache downloaded files.
    force:      Re-download even if the file already exists.

    Returns
    -------
    Path to the downloaded XML file.
    """
    url = f"{_CCEL_BASE_URL}/{volume_id}.xml"
    dest = cache_dir / f"{volume_id}.xml"
    return download_file(url, dest, force=force)


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def _element_inner_text(el: etree._Element) -> str:
    """Extract text from a ThML element, stripping markup but keeping prose.

    Elements in ``_SKIP_LOCAL_NAMES`` are discarded entirely.
    Elements in ``_INLINE_LOCAL_NAMES`` (and all others) have their tags
    stripped but text content retained.
    """
    parts: list[str] = []

    def _collect(node: etree._Element) -> None:
        if node.text:
            parts.append(node.text)
        for child in node:
            if child.tag is etree.Comment:
                if child.tail:
                    parts.append(child.tail)
                continue
            local = etree.QName(child.tag).localname
            if local in _SKIP_LOCAL_NAMES:
                # Discard entirely; keep tail text (belongs to parent)
                if child.tail:
                    parts.append(child.tail)
                continue
            _collect(child)
            if child.tail:
                parts.append(child.tail)

    _collect(el)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _get_head_text(div: etree._Element) -> str | None:
    """Return the title text for a ``<div1>`` element.

    Checks heading elements first (``<head>``, ``<h1>``–``<h4>``), then falls
    back to the first non-empty ``<p>`` child.  ANF volumes use ``<h1>``; NPNF
    volumes use ``<p>`` for all headings.
    """
    first_p: str | None = None
    for child in div:
        if child.tag is etree.Comment:
            continue
        local = etree.QName(child.tag).localname
        if local in ("head", "h1", "h2", "h3", "h4"):
            text = _element_inner_text(child).strip()
            return text or None
        if local == "p" and first_p is None:
            text = _element_inner_text(child).strip()
            if text:
                first_p = text
    return first_p


def _get_identification_text(div: etree._Element, max_paras: int = 2) -> str:
    """Return a text blob suitable for author identification.

    Collects only the PRIMARY heading element (``<head>`` or ``<h1>``; not
    ``<h2>``/``<h3>`` sub-headings which often list multiple authors) plus the
    first ``max_paras`` non-empty ``<p>`` children.  This wider context helps
    match authors in NPNF volumes where headings like "St. Aurelius Augustin /
    Bishop of Hippo" are spread across multiple ``<p>`` elements.
    """
    parts: list[str] = []
    p_count = 0
    primary_heading_done = False
    for child in div:
        if child.tag is etree.Comment:
            continue
        local = etree.QName(child.tag).localname
        if local in ("head", "h1") and not primary_heading_done:
            text = _element_inner_text(child).strip()
            if text:
                parts.append(text)
            primary_heading_done = True
        elif local == "p" and p_count < max_paras:
            text = _element_inner_text(child).strip()
            if text:
                parts.append(text)
                p_count += 1
    return " ".join(parts)


def _find_body(root: etree._Element) -> etree._Element | None:
    """Locate the ThML body element, handling namespaced and unnamespaced variants."""
    for el in root.iter():
        if el.tag is etree.Comment:
            continue
        local = etree.QName(el.tag).localname
        # Accept "body" and the ThML-specific "ThML.body"
        if local in ("body", "ThML.body"):
            return el
    return None


# ---------------------------------------------------------------------------
# Author/work identification
# ---------------------------------------------------------------------------

_COMMON_WORDS = frozenset({
    "saint", "st", "blessed", "pseudo", "the", "and", "of", "to",
    "bishop", "pope", "father", "abbot", "monk",
    # Generic name words shared by multiple authors — too ambiguous alone
    "gregory", "john", "peter", "james", "paul", "clement",
    # Generic theological/structural words
    "epistle", "letter", "homily", "sermon", "works",
    # Titles/epithets shared across multiple people
    "martyr",
})

# Titles indicating non-author sections (index, preface, etc.) — skip author matching
_NON_AUTHOR_TITLE_WORDS = frozenset({
    "index", "indexes", "indices", "contents", "preface", "appendix",
    "foreword", "introduction", "dedication", "prolegomena",
    "bibliography", "chronological", "general", "introductory",
    "volume", "select", "library", "fathers", "ancient",
})


def _find_author_meta(head_text: str | None) -> AuthorMeta | None:
    """Try to match the div1 head text to a known author in _patristic_meta.

    Three-pass strategy (most specific first):

    1. Full name is contained in the head text (e.g., "Clement of Rome").
    2. Single-word head text exactly matches a word in the full name
       (e.g., "Polycarp" matches "Polycarp of Smyrna").
    3. Scored word overlap: sum of lengths of significant name words (>4 chars,
       not common prepositions) found in the head text; highest score wins.
       This handles multi-word heads like "Justin Martyr" or "John Chrysostom".
    """
    if not head_text:
        return None
    head_lower = re.sub(r"\s+", " ", head_text.lower().strip())

    # Pass 1: full name substring match
    for meta in AUTHORS.values():
        if meta.full_name.lower() in head_lower:
            return meta

    # Pass 2: single-word head matches a word in the full name
    if " " not in head_lower and len(head_lower) > 3:
        for meta in AUTHORS.values():
            if head_lower in [w.lower() for w in meta.full_name.split()]:
                return meta

    # Pass 3: scored significant-word overlap.
    # Only applied to short texts (≤ 20 words) that look like headings or
    # bylines, not long body text like index entries or prefaces.
    if len(head_lower.split()) > 20:
        return None

    best_score = 0
    best_meta: AuthorMeta | None = None
    for meta in AUTHORS.values():
        score = 0
        for word in meta.full_name.lower().split():
            if word in _COMMON_WORDS or len(word) <= 4:
                continue
            if re.search(r"\b" + re.escape(word) + r"\b", head_lower):
                score += len(word)
        if score > best_score:
            best_score = score
            best_meta = meta
    return best_meta if best_score > 0 else None


def _slugify_title(title: str) -> str:
    """Convert a title to a filesystem-safe slug (max 60 chars)."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:60]


# ---------------------------------------------------------------------------
# ThML paragraph extractor
# ---------------------------------------------------------------------------

def _extract_paragraphs_from_div1(
    div1: etree._Element,
    ref_prefix: str,
) -> list[dict[str, str]]:
    """Extract paragraphs from a ``<div1>`` element with canonical refs.

    Canonical refs follow the pattern::

        {ref_prefix}.{div2_n}.{div3_n}[.counter]

    where ``div2_n`` / ``div3_n`` come from ``@n`` attributes (falling back
    to sequential numbering) and a dot-counter is appended on duplicate refs.

    Parameters
    ----------
    div1:       The ``<div1>`` element to process.
    ref_prefix: Author abbreviation or title slug to prefix all refs.
    """
    records: list[dict[str, str]] = []
    seen: dict[str, int] = {}

    def _unique_ref(parts: list[str]) -> str:
        base = slugify_ref(".".join([ref_prefix] + [p for p in parts if p]))
        if base not in seen:
            seen[base] = 0
            return base
        seen[base] += 1
        return f"{base}.{seen[base]}"

    div2_counter = 0
    div3_counter = 0

    def _walk(el: etree._Element, path: list[str]) -> None:
        nonlocal div2_counter, div3_counter

        if el.tag is etree.Comment:
            return

        local = etree.QName(el.tag).localname

        if local == "p":
            text = _element_inner_text(el)
            if text:
                records.append({"ref": _unique_ref(path), "text": text})
            return

        if local in _SKIP_LOCAL_NAMES or local in ("head", "h1", "h2", "h3", "h4"):
            return

        if local == "div2":
            div3_counter = 0
            n = el.get("n", "")
            n_clean = re.sub(r"[^A-Za-z0-9]", "", n)[:20] if n else ""
            if not n_clean:
                div2_counter += 1
                n_clean = str(div2_counter)
            new_path = path + [n_clean]
            for child in el:
                _walk(child, new_path)
            return

        if local == "div3":
            n = el.get("n", "")
            n_clean = re.sub(r"[^A-Za-z0-9]", "", n)[:20] if n else ""
            if not n_clean:
                div3_counter += 1
                n_clean = str(div3_counter)
            new_path = path + [n_clean]
            for child in el:
                _walk(child, new_path)
            return

        if local in ("div4", "div5", "div6"):
            n = el.get("n", "")
            n_clean = re.sub(r"[^A-Za-z0-9]", "", n)[:20] if n else ""
            new_path = path + [n_clean] if n_clean else path
            for child in el:
                _walk(child, new_path)
            return

        for child in el:
            _walk(child, path)

    for child in div1:
        _walk(child, [])

    return records


# ---------------------------------------------------------------------------
# Volume parser
# ---------------------------------------------------------------------------

def parse_thml_volume(
    xml_path: Path,
    source_id: str,
    volume_id: str,
    volume_label: str,
) -> list[tuple[Work, list[dict[str, str]]]]:
    """Parse a CCEL ThML volume and return one ``(Work, paragraphs)`` pair per ``<div1>``.

    Parameters
    ----------
    xml_path:     Path to the downloaded ThML XML file.
    source_id:    Source ID string, e.g. ``"patristic/ccel-anf"``.
    volume_id:    Volume code, e.g. ``"anf01"``.
    volume_label: Human-readable label, e.g. ``"ANF Vol. 1"``.
    """
    try:
        tree = etree.parse(str(xml_path))
    except etree.XMLSyntaxError as exc:
        log.warning("XML parse error in %s: %s", xml_path, exc)
        return []
    except Exception as exc:
        log.error("Failed to parse %s: %s", xml_path, exc)
        return []

    root = tree.getroot()
    body = _find_body(root)
    if body is None:
        log.warning("No body element found in %s", xml_path)
        return []

    results: list[tuple[Work, list[dict[str, str]]]] = []
    div1_counter = 0
    series_prefix = source_id.split("/")[-1].upper().replace("-", "")  # e.g. "CCELANF"

    for child in body:
        if child.tag is etree.Comment:
            continue
        local = etree.QName(child.tag).localname
        if local != "div1":
            continue

        div1_counter += 1
        head_text = _get_head_text(child)
        title_words = set((head_text or "").lower().split())
        is_non_author = bool(title_words & _NON_AUTHOR_TITLE_WORDS)
        ident_text = _get_identification_text(child, max_paras=2)
        author_meta = None if is_non_author else _find_author_meta(ident_text)

        title = head_text or f"{volume_label} Part {div1_counter}"
        author_name = author_meta.full_name if author_meta else None

        # work_id uses the positional div1 counter so it is stable across re-runs
        # even when the title changes (e.g. after improving author detection).
        series_key = source_id.split("/")[-1]  # e.g. "ccel-anf"
        work_id = f"{series_key}/{volume_id}/{div1_counter:03d}"

        # Date info from author meta; fall back to uncertain
        if author_meta:
            birth, death = author_meta.dates
            date_composed: int | None = (birth + death) // 2
            date_range: tuple[int, int] | None = (birth, death)
            date_confidence: DateConfidence = "approximate"
            tradition: Tradition | None = author_meta.tradition
        else:
            date_composed = None
            date_range = None
            date_confidence = "uncertain"
            tradition = None

        post_schism = bool(date_composed is not None and date_composed > _SCHISM_YEAR)

        # Canonical ref prefix: author abbreviation when identified, else vol+div slug
        if author_meta:
            ref_prefix = author_meta.abbrev
        else:
            n_attr = child.get("n", "")
            n_clean = re.sub(r"[^A-Za-z0-9]", "", n_attr)[:8] if n_attr else str(div1_counter)
            ref_prefix = f"{series_prefix}{volume_id[-2:]}{n_clean}"

        paragraphs = _extract_paragraphs_from_div1(child, ref_prefix)

        if not paragraphs:
            log.debug("No paragraphs in div1 %d (%r) of %s", div1_counter, title, xml_path.name)
            continue

        work = Work(
            work_id=work_id,
            source_id=source_id,
            author=author_name,
            title=title,
            date_composed=date_composed,
            date_range=date_range,
            date_confidence=date_confidence,
            genre="patristic",
            language="eng",
            tradition=tradition,
            license="public_domain",
            provenance_url=f"https://ccel.org/ccel/s/schaff/{volume_id}.xml",
            edition=volume_label,
            translation_of=None,
        )

        results.append((work, paragraphs))

    log.debug("Parsed %d works from %s", len(results), xml_path.name)
    return results
