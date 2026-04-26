"""
Shared scraping logic for goarch.org Greek liturgical texts.

Source: https://www.goarch.org/ (Greek Orthodox Archdiocese of America)
Format: Liferay CMS HTML pages, language parameter ``languageId=el_GR``
License: Site content freely available; texts themselves are public domain
         (4th-century compositions)

Notes
-----
The site uses Liferay Portal.  Greek-language pages are fetched by appending
a portlet instance ``languageId`` parameter to the page URL.  The exact
instance ID (e.g. ``_101_INSTANCE_ulcNzWPdScz6_``) is extracted dynamically
from the English page's language-switcher links.

If the site returns 403 (bot-blocking), the raw HTML can be downloaded
manually and placed at the cache path printed in the error message.
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path

import httpx
from bs4 import BeautifulSoup, Tag

from scripts.ingest._common import slugify_ref

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


# ---------------------------------------------------------------------------
# Fetch helpers
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
    # Liferay language switcher links contain languageId=el_GR
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "el_GR" in href or "languageId=el_GR" in href:
            if href.startswith("http"):
                return href
            if href.startswith("/"):
                # Build absolute URL from the base
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
    Fetch the Greek-language version of a goarch.org liturgy page.

    Strategy:
    1. Serve from cache if available (and not force).
    2. Fetch the English page to discover the Greek URL from the language switcher.
    3. Fetch the Greek page.
    4. Cache the result.

    Returns the HTML string, or None if the fetch fails.
    """
    if cache_path.exists() and not force:
        log.info("Using cached HTML: %s", cache_path)
        return cache_path.read_text(encoding="utf-8")

    cache_path.parent.mkdir(parents=True, exist_ok=True)

    with httpx.Client(follow_redirects=True) as client:
        # Step 1: fetch English page to find Greek URL
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

        # Step 2: extract Greek URL
        greek_url = _find_greek_url(english_html, english_url)
        if greek_url is None:
            # Fall back: try a common Liferay pattern with el_GR
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


# ---------------------------------------------------------------------------
# HTML parsing
# ---------------------------------------------------------------------------

def _is_greek(text: str) -> bool:
    """Return True if the text contains Greek characters."""
    return bool(_GREEK_RE.search(text))


def _clean_text(text: str) -> str:
    """Normalize whitespace in extracted text."""
    return re.sub(r"\s+", " ", text).strip()


def _find_content_div(soup: BeautifulSoup) -> Tag | None:
    """Find the main article/content container on a goarch.org page."""
    # Try common Liferay/goarch content containers in order of specificity
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
    # Last resort: the largest <div> by text length
    return soup.body


def parse_greek_liturgy(
    html: str,
    service_abbrev: str,
) -> list[dict]:
    """
    Parse a goarch.org Greek liturgy HTML page into paragraph records.

    Parameters
    ----------
    html:            Raw HTML of the Greek-language liturgy page.
    service_abbrev:  Short abbreviation used in canonical refs (e.g. 'Chrysostom').

    Returns
    -------
    List of ``{"ref": ..., "text": ...}`` dicts, one per liturgical passage.
    Only paragraphs containing Greek text are included.
    """
    soup = BeautifulSoup(html, "lxml")
    content = _find_content_div(soup)
    if content is None:
        log.warning("No content div found in %s HTML", service_abbrev)
        return []

    paragraphs: list[dict] = []
    section_n = 0
    para_n = 0
    current_section: str = "intro"

    for el in content.find_all(["h1", "h2", "h3", "h4", "h5", "p", "li", "div"]):
        tag_name = el.name

        # Section headings become new section markers
        if tag_name in ("h1", "h2", "h3", "h4", "h5"):
            heading_text = _clean_text(el.get_text())
            if heading_text:
                section_n += 1
                para_n = 0
                # Slugify the heading for the ref
                slug = re.sub(r"[^A-Za-z0-9Ͱ-Ͽἀ-῿]+", "_", heading_text)
                slug = slug.strip("_")[:40]  # cap length
                current_section = f"{section_n:04d}"
            continue

        # For <div> elements, only emit if they are leaf-level text nodes
        if tag_name == "div":
            # Skip containers that hold block children — those will be processed recursively
            if el.find(["p", "div", "h1", "h2", "h3", "h4", "li"]):
                continue

        text = _clean_text(el.get_text())
        if not text:
            continue
        if not _is_greek(text):
            continue

        ref = slugify_ref(f"ByzLit.{service_abbrev}.{current_section}.{para_n:04d}")
        paragraphs.append({"ref": ref, "text": text})
        para_n += 1

    log.info(
        "  Parsed %d Greek paragraphs from %s liturgy HTML",
        len(paragraphs), service_abbrev,
    )
    return paragraphs
