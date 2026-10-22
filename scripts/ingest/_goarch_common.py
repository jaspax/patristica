"""
Shared scraping logic for goarch.org Greek liturgical texts.

Sources
-------
- www.goarch.org: Liferay CMS pages (returns 403 for automated requests; kept for reference)
- dcs.goarch.org: GOA Digital Chant Stand — static HTML files, publicly accessible

The DCS (https://dcs.goarch.org/goa/dcs/) serves liturgical texts as plain static HTML
with a bilingual table layout: ``leftCell`` (Greek) and ``rightCell`` (English).
These pages are fetched directly with httpx; no browser automation is required.

License: Site content freely available; texts themselves are public domain
         (4th-century compositions).
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import httpx
from bs4 import BeautifulSoup, Tag

from scripts.ingest._common import offline, require_network, slugify_ref

log = logging.getLogger(__name__)

_POLITE_DELAY = 1.0  # seconds between requests

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "el-GR,el;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Greek Unicode: Basic Greek (U+0370–U+03FF) + Greek Extended (U+1F00–U+1FFF)
_GREEK_RE = re.compile(r"[Ͱ-Ͽἀ-῿]")

# Paragraph classes that carry no liturgical text
_DCS_SKIP_CLASSES = frozenset({
    "break",
    "rubric",
    "bmc_collapse",
    "emc_collapse",
    "servicesourcestitle",
    "servicesources",
    "servicesourcessection",
})

# Span child classes inside <p class="mixed"> that mark major section breaks
_DCS_SECTION_SPAN_CLASSES = frozenset({"boldred", "smaller"})

# Paragraph classes that open a new top-level section
_DCS_SECTION_P_CLASSES = frozenset({"smallcenterboldred"})


# ---------------------------------------------------------------------------
# DCS fetch helper
# ---------------------------------------------------------------------------

def fetch_dcs_html(
    dcs_url: str,
    cache_path: Path,
    force: bool = False,
) -> str | None:
    """
    Fetch a GOA Digital Chant Stand HTML page.

    The DCS serves static HTML files that are publicly accessible without
    bot-blocking.  This is a simple fetch-and-cache wrapper.

    Returns the HTML string, or None if the fetch fails.
    """
    if cache_path.exists() and (not force or offline()):
        log.info("Using cached HTML: %s", cache_path)
        return cache_path.read_text(encoding="utf-8")
    require_network(f"fetching {dcs_url}")

    cache_path.parent.mkdir(parents=True, exist_ok=True)

    log.info("Fetching DCS page: %s", dcs_url)
    try:
        time.sleep(_POLITE_DELAY)
        with httpx.Client(follow_redirects=True) as client:
            resp = client.get(dcs_url, headers=_HEADERS, timeout=30)
            resp.raise_for_status()
            html = resp.text
    except httpx.HTTPStatusError as exc:
        log.error("HTTP %d fetching %s", exc.response.status_code, dcs_url)
        return None
    except Exception as exc:
        log.error("Failed to fetch %s: %s", dcs_url, exc)
        return None

    cache_path.write_text(html, encoding="utf-8")
    log.info("Cached DCS HTML to %s", cache_path)
    return html


# ---------------------------------------------------------------------------
# DCS HTML parsing
# ---------------------------------------------------------------------------

def _is_greek(text: str) -> bool:
    """Return True if the text contains Greek characters."""
    return bool(_GREEK_RE.search(text))


def _clean_text(text: str) -> str:
    """Normalize whitespace in extracted text."""
    return re.sub(r"\s+", " ", text).strip()


def parse_dcs_liturgy(
    html: str,
    service_abbrev: str,
) -> list[dict]:
    """
    Parse a GOA DCS bilingual (gr-en) liturgy HTML page into paragraph records.

    The DCS renders liturgical text as a two-column table (``table#biTable``).
    Only the Greek left column (``td.leftCell``) is extracted.

    Paragraph classes handled:

    Included:
      dialog, inaudible, reading, hymn — liturgical text
      actor, actorinaudible            — speaker labels (ΔΙΑΚΟΝΟΣ, ΙΕΡΕΥΣ…)
      designation                      — structural labels (Ἀντίφωνον Αʹ…)
      mixed (non-rubric content)       — headings, prayer labels, rubrics

    Skipped:
      break, rubric, bmc_collapse, emc_collapse — UI / navigation elements
      servicesourcestitle/sources/section       — source-book metadata block

    Section tracking:
      ``p.mixed`` containing a ``span.boldred`` or ``span.smaller`` child, and
      ``p.smallcenterboldred``, trigger a section increment (``section_n``).
      All other content increments ``para_n`` within the current section.

    Parameters
    ----------
    html:            Raw HTML of the DCS gr-en liturgy page.
    service_abbrev:  Short abbreviation used in canonical refs (e.g. 'Chrysostom').

    Returns
    -------
    List of ``{"ref": ..., "text": ...}`` dicts, one per liturgical passage.
    Only paragraphs containing Greek text are included.
    """
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", id="biTable")
    if table is None:
        log.warning("No biTable found in %s DCS HTML", service_abbrev)
        return []

    paragraphs: list[dict] = []
    section_n = 0
    para_n = 0

    for tr in table.find_all("tr"):
        left: Tag | None = tr.find("td", class_="leftCell")
        if left is None:
            continue

        for p in left.find_all("p"):
            cls = set(p.get("class", []))

            # Skip UI/metadata paragraphs
            if cls & _DCS_SKIP_CLASSES:
                continue

            if "mixed" in cls:
                # Inspect the first meaningful span child
                first_span = p.find("span", class_=True, recursive=False)
                if first_span is None:
                    continue
                span_cls = set(first_span.get("class", []))
                if "rubric" in span_cls:
                    continue  # "(Δείτε τά μεταβλητά.)" — variable-parts notice
                text = _clean_text(p.get_text())
                if not text or not _is_greek(text):
                    continue
                if span_cls & _DCS_SECTION_SPAN_CLASSES:
                    # Major section break — reset paragraph counter
                    section_n += 1
                    para_n = 0
                ref = slugify_ref(
                    f"ByzLit.{service_abbrev}.{section_n:04d}.{para_n:04d}"
                )
                paragraphs.append({"ref": ref, "text": text})
                para_n += 1
                continue

            if cls & _DCS_SECTION_P_CLASSES:
                text = _clean_text(p.get_text())
                if not text or not _is_greek(text):
                    continue
                section_n += 1
                para_n = 0
                ref = slugify_ref(
                    f"ByzLit.{service_abbrev}.{section_n:04d}.{para_n:04d}"
                )
                paragraphs.append({"ref": ref, "text": text})
                para_n += 1
                continue

            # All remaining paragraph classes: dialog, inaudible, reading, hymn,
            # actor, actorinaudible, designation, etc.
            text = _clean_text(p.get_text())
            if not text or not _is_greek(text):
                continue
            ref = slugify_ref(
                f"ByzLit.{service_abbrev}.{section_n:04d}.{para_n:04d}"
            )
            paragraphs.append({"ref": ref, "text": text})
            para_n += 1

    log.info(
        "  Parsed %d Greek paragraphs from %s DCS HTML",
        len(paragraphs),
        service_abbrev,
    )
    return paragraphs


# ---------------------------------------------------------------------------
# Legacy www.goarch.org helpers (kept for reference; site blocks automated access)
# ---------------------------------------------------------------------------

def _fetch_url(url: str, client: httpx.Client) -> str:
    """Fetch a URL with browser-like headers; return response text."""
    time.sleep(_POLITE_DELAY)
    resp = client.get(url, headers=_HEADERS, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


def _find_greek_url(english_html: str, base_url: str) -> str | None:
    """Extract the Greek-language URL from the English page's language switcher."""
    soup = BeautifulSoup(english_html, "lxml")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "el_GR" in href or "languageId=el_GR" in href:
            if href.startswith("http"):
                return href
            if href.startswith("/"):
                m = re.match(r"(https?://[^/]+)", base_url)
                if m:
                    return m.group(1) + href
    return None


def fetch_greek_html(
    english_url: str,
    cache_path: Path,
    force: bool = False,
) -> str | None:
    """
    Fetch the Greek-language version of a www.goarch.org liturgy page.

    NOTE: www.goarch.org currently returns 403 for all automated requests.
    Use ``fetch_dcs_html`` with a dcs.goarch.org URL instead.

    If manual HTML is available at ``cache_path``, it will be used as-is.
    """
    if cache_path.exists() and (not force or offline()):
        log.info("Using cached HTML: %s", cache_path)
        return cache_path.read_text(encoding="utf-8")
    require_network(f"fetching the Greek page for {english_url}")

    cache_path.parent.mkdir(parents=True, exist_ok=True)

    with httpx.Client(follow_redirects=True) as client:
        log.info("Fetching English page to discover Greek URL: %s", english_url)
        try:
            english_html = _fetch_url(english_url, client)
        except httpx.HTTPStatusError as exc:
            log.error(
                "HTTP %d fetching %s.\n"
                "goarch.org blocks automated requests. To proceed manually:\n"
                "  1. Open in a browser: %s\n"
                "  2. Switch to Greek (Ελληνικά) using the language selector\n"
                "  3. Save the page source (Ctrl+U → Save As) to:\n"
                "     %s",
                exc.response.status_code,
                english_url,
                english_url,
                cache_path,
            )
            return None
        except Exception as exc:
            log.error("Failed to fetch %s: %s", english_url, exc)
            return None

        greek_url = _find_greek_url(english_html, english_url)
        if greek_url is None:
            log.warning(
                "Could not find Greek URL in language switcher; trying parameter append."
            )
            greek_url = english_url + "?languageId=el_GR"

        log.info("Fetching Greek page: %s", greek_url)
        try:
            greek_html = _fetch_url(greek_url, client)
        except httpx.HTTPStatusError as exc:
            log.error(
                "HTTP %d fetching Greek page %s\n"
                "Save the Greek-language page source to:\n"
                "  %s",
                exc.response.status_code,
                greek_url,
                cache_path,
            )
            return None
        except Exception as exc:
            log.error("Failed to fetch Greek page %s: %s", greek_url, exc)
            return None

    cache_path.write_text(greek_html, encoding="utf-8")
    log.info("Cached Greek HTML to %s", cache_path)
    return greek_html


def _find_content_div(soup: BeautifulSoup) -> Tag | None:
    """Find the main article/content container on a www.goarch.org page."""
    for selector in [
        "div.portlet-body",
        "div.journal-content-article",
        "article",
        "div#content",
        "div.main-content",
        "div[class*='content']",
    ]:
        el = soup.select_one(selector)
        if el:
            return el
    return soup.body


def parse_greek_liturgy(
    html: str,
    service_abbrev: str,
) -> list[dict]:
    """
    Parse a www.goarch.org Greek liturgy HTML page into paragraph records.

    NOTE: Kept for legacy/manual-cache use. For new fetches use
    ``fetch_dcs_html`` + ``parse_dcs_liturgy`` instead.
    """
    soup = BeautifulSoup(html, "lxml")
    content = _find_content_div(soup)
    if content is None:
        log.warning("No content div found in %s HTML", service_abbrev)
        return []

    paragraphs: list[dict] = []
    section_n = 0
    para_n = 0

    for el in content.find_all(["h1", "h2", "h3", "h4", "h5", "p", "li", "div"]):
        tag_name = el.name

        if tag_name in ("h1", "h2", "h3", "h4", "h5"):
            heading_text = _clean_text(el.get_text())
            if heading_text:
                section_n += 1
                para_n = 0
            continue

        if tag_name == "div":
            if el.find(["p", "div", "h1", "h2", "h3", "h4", "li"]):
                continue

        text = _clean_text(el.get_text())
        if not text or not _is_greek(text):
            continue

        ref = slugify_ref(f"ByzLit.{service_abbrev}.{section_n:04d}.{para_n:04d}")
        paragraphs.append({"ref": ref, "text": text})
        para_n += 1

    log.info(
        "  Parsed %d Greek paragraphs from %s liturgy HTML",
        len(paragraphs),
        service_abbrev,
    )
    return paragraphs
