"""
Common utilities shared across all ingestion modules.

Functions
---------
download_file   — idempotent HTTP download with ETag caching
parse_tei       — TEI P5 XML parser → (metadata, paragraphs)
parse_osis      — OSIS XML parser  → (metadata, [(ref, text)])
parse_usfm      — USFM line parser → (metadata, [(ref, text)])
clean_html      — HTML → plain text
slugify_ref     — normalize dot-separated canonical references
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup
from lxml import etree

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# HTTP download
# ---------------------------------------------------------------------------

_ETAG_SUFFIX = ".etag"


def download_file(
    url: str,
    dest: Path,
    *,
    etag_cache: bool = True,
    force: bool = False,
) -> Path:
    """Download *url* to *dest*, skipping if already present (idempotent).

    ETag caching
    ~~~~~~~~~~~~
    When *etag_cache* is True, the last-received ETag is stored in a sidecar
    file ``{dest}.etag``.  Subsequent calls send ``If-None-Match`` so that
    servers can reply with 304 Not Modified without retransmitting the body.

    Parameters
    ----------
    url:        Remote URL to fetch.
    dest:       Local path to write the file to.  Parent directories are
                created automatically.
    etag_cache: Use ETag sidecar for conditional requests.
    force:      Re-download even if *dest* already exists.

    Returns
    -------
    Path to the downloaded (or already-present) file.
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    etag_path = dest.with_suffix(dest.suffix + _ETAG_SUFFIX)

    if dest.exists() and not force:
        if not etag_cache:
            log.debug("Skipping %s (already exists)", dest)
            return dest
        # Attempt conditional request with cached ETag
        headers: dict[str, str] = {}
        if etag_path.exists():
            headers["If-None-Match"] = etag_path.read_text().strip()
        with httpx.Client(follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
        if resp.status_code == 304:
            log.debug("304 Not Modified — keeping cached %s", dest)
            return dest
        if resp.is_error:
            log.debug("Conditional GET returned %s — keeping cached %s", resp.status_code, dest)
            return dest
        # Fall through to write new content
        _write_response(resp, dest, etag_path)
        return dest

    log.info("Downloading %s → %s", url, dest)
    with httpx.Client(follow_redirects=True) as client:
        resp = client.get(url)
    resp.raise_for_status()
    _write_response(resp, dest, etag_path)
    return dest


def _write_response(resp: httpx.Response, dest: Path, etag_path: Path) -> None:
    dest.write_bytes(resp.content)
    etag = resp.headers.get("etag")
    if etag:
        etag_path.write_text(etag)
    log.debug("Wrote %d bytes to %s", len(resp.content), dest)


# ---------------------------------------------------------------------------
# TEI P5 parser
# ---------------------------------------------------------------------------

# TEI P5 namespace
_TEI_NS = "http://www.tei-c.org/ns/1.0"
_TEI = f"{{{_TEI_NS}}}"


def parse_tei(path: Path) -> tuple[dict[str, Any], list[str]]:
    """Parse a TEI P5 XML file.

    Extracts metadata from ``<teiHeader>`` and collects paragraph / line text
    from the ``<text><body>`` element.

    Returns
    -------
    (metadata, paragraphs)
        *metadata* is a dict with keys: ``title``, ``author``, ``language``,
        ``publisher``, ``date``.  Missing fields are ``None``.
        *paragraphs* is a list of non-empty strings, one per ``<p>``, ``<l>``,
        or ``<ab>`` element.
    """
    tree = etree.parse(str(path))
    root = tree.getroot()

    # Strip namespace prefix for convenience
    ns = {"tei": _TEI_NS} if _TEI_NS in (root.nsmap.get(None, "") or root.nsmap.get("tei", "")) else {}

    def find(xpath: str) -> str | None:
        el = root.find(xpath, namespaces={"tei": _TEI_NS})
        return _element_text(el) if el is not None else None

    metadata: dict[str, Any] = {
        "title": find(".//tei:teiHeader//tei:titleStmt/tei:title"),
        "author": find(".//tei:teiHeader//tei:titleStmt/tei:author"),
        "language": find(".//tei:teiHeader//tei:langUsage/tei:language"),
        "publisher": find(".//tei:teiHeader//tei:publicationStmt/tei:publisher"),
        "date": find(".//tei:teiHeader//tei:publicationStmt/tei:date"),
    }

    # Collect body text elements
    body = root.find(".//tei:text/tei:body", namespaces={"tei": _TEI_NS})
    paragraphs: list[str] = []
    if body is not None:
        for el in body.iter(
            f"{_TEI}p",
            f"{_TEI}l",
            f"{_TEI}ab",
        ):
            text = _element_text(el)
            if text:
                paragraphs.append(text)

    log.debug("parse_tei: %s → %d paragraphs", path.name, len(paragraphs))
    return metadata, paragraphs


# ---------------------------------------------------------------------------
# OSIS parser
# ---------------------------------------------------------------------------

_OSIS_NS = "http://www.bibletechnologies.net/2003/OSIS/namespace"
_OSIS = f"{{{_OSIS_NS}}}"


def parse_osis(path: Path) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Parse an OSIS XML file (used by OSHB, SBLGNT, etc.).

    Returns
    -------
    (metadata, verses)
        *metadata*: dict with ``work_id``, ``title``, ``language``, ``description``.
        *verses*: list of ``(osisID, text)`` pairs, one per ``<verse>`` element.
        The ``osisID`` is the canonical reference in OSIS notation (e.g.
        ``"Gen.1.1"``).
    """
    tree = etree.parse(str(path))
    root = tree.getroot()

    ns = {"osis": _OSIS_NS}

    def find_el(xpath: str) -> etree._Element | None:
        return root.find(xpath, namespaces=ns)

    def find(xpath: str) -> str | None:
        el = find_el(xpath)
        return _element_text(el) if el is not None else None

    # Work metadata lives in <header><work>
    work_el = find_el(".//osis:header/osis:work")
    metadata: dict[str, Any] = {
        "work_id": work_el.get("osisWork") if work_el is not None else None,
        "title": find(".//osis:header/osis:work/osis:title"),
        "language": find(".//osis:header/osis:work/osis:language"),
        "description": find(".//osis:header/osis:work/osis:description"),
    }

    # Collect verses
    verses: list[tuple[str, str]] = []
    for verse_el in root.iter(f"{_OSIS}verse"):
        osis_id: str = verse_el.get("osisID", "")
        text = _element_text(verse_el)
        if osis_id and text:
            verses.append((osis_id, text))

    log.debug("parse_osis: %s → %d verses", path.name, len(verses))
    return metadata, verses


# ---------------------------------------------------------------------------
# USFM parser (pure Python, handles common markers)
# ---------------------------------------------------------------------------

# Markers that carry the book/chapter context
_USFM_ID_RE = re.compile(r"\\id\s+(\S+)")
_USFM_CHAPTER_RE = re.compile(r"\\c\s+(\d+)")
_USFM_VERSE_RE = re.compile(r"\\v\s+(\d+)\s*(.*)")
_USFM_TITLE_RE = re.compile(r"\\(?:h|mt\d?|toc\d)\s+(.*)")
# Strip any remaining backslash markers from verse text
_USFM_MARKER_RE = re.compile(r"\\[a-z+*\d]+\s*")


def parse_usfm(path: Path) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    """Parse a USFM file using a simple line-by-line approach.

    Handles the most common markers: ``\\id``, ``\\h``, ``\\mt``, ``\\c``,
    ``\\v``.  Continuation lines (no marker) are appended to the current verse.

    Returns
    -------
    (metadata, verses)
        *metadata*: dict with ``book_id``, ``title``.
        *verses*: list of ``(canonical_ref, text)`` where *canonical_ref* is
        ``"{BOOK}.{chapter}.{verse}"``, e.g. ``"Gen.1.1"``.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    book_id = ""
    title = ""
    chapter = 0
    current_ref: str | None = None
    current_parts: list[str] = []
    verses: list[tuple[str, str]] = []

    def flush() -> None:
        if current_ref and current_parts:
            verse_text = _USFM_MARKER_RE.sub("", " ".join(current_parts)).strip()
            if verse_text:
                verses.append((current_ref, verse_text))

    for line in lines:
        line = line.strip()
        if not line:
            continue

        m = _USFM_ID_RE.match(line)
        if m:
            book_id = m.group(1).strip()
            continue

        m = _USFM_TITLE_RE.match(line)
        if m and not title:
            title = m.group(1).strip()
            continue

        m = _USFM_CHAPTER_RE.match(line)
        if m:
            flush()
            current_ref = None
            current_parts = []
            chapter = int(m.group(1))
            continue

        m = _USFM_VERSE_RE.match(line)
        if m:
            flush()
            verse_num = m.group(1)
            rest = m.group(2).strip()
            current_ref = f"{book_id}.{chapter}.{verse_num}"
            current_parts = [rest] if rest else []
            continue

        # Continuation text for the current verse
        if current_ref is not None:
            current_parts.append(line)

    flush()
    metadata: dict[str, Any] = {"book_id": book_id, "title": title}
    log.debug("parse_usfm: %s → %d verses", path.name, len(verses))
    return metadata, verses


# ---------------------------------------------------------------------------
# HTML cleaner
# ---------------------------------------------------------------------------

def clean_html(html: str) -> str:
    """Strip HTML markup and normalize whitespace, returning plain text."""
    soup = BeautifulSoup(html, "lxml")
    # Remove script/style elements before extracting text
    for tag in soup(["script", "style"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    # Collapse runs of whitespace (including newlines) to a single space
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Canonical reference normalizer
# ---------------------------------------------------------------------------

_REF_INVALID_RE = re.compile(r"[^A-Za-z0-9.\-]")


def slugify_ref(ref: str) -> str:
    """Normalize a dot-separated canonical reference.

    - Strips characters outside ``[A-Za-z0-9.-]``
    - Collapses runs of dots
    - Strips leading/trailing dots

    >>> slugify_ref("Gen. 1.1 ")
    'Gen.1.1'
    >>> slugify_ref("Aug.Conf.1.1.1")
    'Aug.Conf.1.1.1'
    """
    ref = ref.strip()
    # Remove spaces around dots
    ref = re.sub(r"\s*\.\s*", ".", ref)
    # Strip characters not allowed in canonical refs
    ref = _REF_INVALID_RE.sub("", ref)
    # Collapse repeated dots and strip outer dots
    ref = re.sub(r"\.{2,}", ".", ref).strip(".")
    return ref


def dedupe_refs(records: list[dict[str, str]]) -> list[dict[str, str]]:
    """Make ``ref`` values unique within a work by suffixing ``.1``, ``.2``, …

    Generated suffixes are reserved so they can never collide with a real ref
    that appears later (e.g. a second ``X.4`` becoming ``X.4.1`` while the
    source also has its own ``X.4.1``).
    """
    seen: dict[str, int] = {}
    result: list[dict[str, str]] = []
    for rec in records:
        ref = rec["ref"]
        if ref not in seen:
            seen[ref] = 0
            result.append(rec)
            continue
        while True:
            seen[ref] += 1
            candidate = f"{ref}.{seen[ref]}"
            if candidate not in seen:
                seen[candidate] = 0
                result.append({**rec, "ref": candidate})
                break
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _element_text(el: etree._Element | None) -> str | None:
    """Return all text content of *el* (including tail text of children), stripped."""
    if el is None:
        return None
    parts = [el.text or ""]
    for child in el:
        parts.append(etree.tostring(child, encoding="unicode", method="text"))
    text = " ".join(parts)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None
