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
from bs4 import BeautifulSoup, NavigableString, Tag

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


# Rubrics (#500): the DCS marks the book's rubrics with classes, and the ingestor
# records them as editorial spans of kind "rubric" (shown red in the reader, not
# embedded). Paragraphs that are a speaker label, with any stage direction:
_DCS_ACTOR_P_CLASSES = frozenset({"actor", "actorinaudible"})
# ... except the words spoken after the label ("ΧΟΡΟΣ· Σοί, Κύριε."):
_DCS_SPOKEN_SPAN_CLASSES = frozenset({"dialogafteractor"})
# A <p class="mixed"> whose first span has one of these is a red label line
# ("Ἀντίφωνον Αʹ", "Ἦχος βʹ.", "ΕΥΧΗ Αʹ ΑΝΤΙΦΩΝΟΥ", "Προκείμενον."):
_DCS_LABEL_SPAN_CLASSES = frozenset({"designation", "mode", "red", "smallred"})
# Paragraphs that are a red label as a whole ("Η ΕΙΣΟΔΟΣ"):
_DCS_LABEL_P_CLASSES = frozenset({"designation"})
# Red runs inside the text that are rubrics as a whole ("ΙΕΡΕΥΣ (χαμηλοφώνως)",
# "Ἤ, ἐν συλλειτούργῳ, τὸ ἑξῆς·"):
_DCS_RUBRIC_SPAN_CLASSES = frozenset({"boldred", "smallred", "italicsred"})
# Plain red inside the text marks the variable parts: only a parenthesised
# instruction or placeholder is a rubric ("(3)", "(δεῖνος)"); the rest is spoken
# ("τοῦ Ἀρχιεπισκόπου ἡμῶν").
_DCS_RED_SPAN_CLASS = "red"
_PARENTHESISED_RE = re.compile(r"\([^()]*\)")
RUBRIC = "rubric"


def _span_classes(node: NavigableString, p: Tag) -> list[set[str]]:
    """The classes of every element between ``node`` and ``p``, innermost first."""
    out: list[set[str]] = []
    parent = node.parent
    while parent is not None and parent is not p:
        out.append(set(parent.get("class", [])))
        parent = parent.parent
    return out


def _rubric_flags(node: NavigableString, p: Tag, whole: bool) -> list[bool]:
    """Per character of ``node``: is it part of a rubric?"""
    text = str(node)
    chain = _span_classes(node, p)
    if whole:
        spoken = any(c & _DCS_SPOKEN_SPAN_CLASSES for c in chain)
        return [not spoken] * len(text)
    if any(c & _DCS_RUBRIC_SPAN_CLASSES for c in chain):
        return [True] * len(text)
    flags = [False] * len(text)
    if any(_DCS_RED_SPAN_CLASS in c for c in chain):
        for m in _PARENTHESISED_RE.finditer(text):
            flags[m.start():m.end()] = [True] * (m.end() - m.start())
    return flags


def _text_and_rubrics(p: Tag) -> tuple[str, list[list]]:
    """
    ``_clean_text(p.get_text())`` and the rubric spans in it, ``[[start, end,
    "rubric"], …]`` (offsets into the cleaned text).

    Which parts are rubrics comes from the DCS classes (the ``_DCS_*`` sets
    above). A whitespace run between two rubric pieces belongs to the rubric,
    so "ΙΕΡΕΥΣ (χαμηλοφώνως)" is one span.
    """
    cls = set(p.get("class", []))
    whole = bool(cls & (_DCS_ACTOR_P_CLASSES | _DCS_LABEL_P_CLASSES))
    if "mixed" in cls:
        first = p.find("span", class_=True, recursive=False)
        first_cls = set(first.get("class", [])) if first is not None else set()
        if first_cls & _DCS_SECTION_SPAN_CLASSES:
            # A section heading: the reader shows it as one, not as a rubric.
            text = _clean_text(p.get_text())
            return text, []
        if first_cls & _DCS_LABEL_SPAN_CLASSES:
            whole = True
    chars: list[str] = []
    flags: list[bool] = []
    # The strings get_text() joins: text nodes, not comments.
    for node in p.descendants:
        if type(node) is NavigableString:
            chars.extend(node)
            flags.extend(_rubric_flags(node, p, whole))
    raw = "".join(chars)
    if raw != p.get_text():
        raise ValueError(f"DCS paragraph text walk disagrees with get_text(): {raw!r}")

    # Collapse whitespace as _clean_text does, keeping one flag per character.
    text_chars: list[str] = []
    text_flags: list[bool | None] = []  # None: a collapsed space, decided below
    for m in re.finditer(r"\s+|\S", raw):
        if m.group().isspace():
            if text_chars and text_chars[-1] != " ":
                text_chars.append(" ")
                text_flags.append(None)
        else:
            text_chars.append(m.group())
            text_flags.append(flags[m.start()])
    while text_chars and text_chars[-1] == " ":
        text_chars.pop()
        text_flags.pop()
    text = "".join(text_chars)
    if text != _clean_text(raw):
        raise ValueError(f"DCS whitespace collapse disagrees with _clean_text: {text!r}")

    # A space is a rubric's only between two rubric characters.
    for i, f in enumerate(text_flags):
        if f is None:
            before = text_flags[i - 1] if i > 0 else False
            after = text_flags[i + 1] if i + 1 < len(text_flags) else False
            text_flags[i] = bool(before and after)
    spans: list[list] = []
    i = 0
    while i < len(text):
        if not text_flags[i]:
            i += 1
            continue
        j = i
        while j < len(text) and text_flags[j]:
            j += 1
        start, end = i, j
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end:
            spans.append([start, end, RUBRIC])
        i = j
    return text, spans


def _record(ref: str, text: str, spans: list[list]) -> dict:
    """A raw paragraph record, with its rubric spans when it has any."""
    out: dict = {"ref": ref, "text": text}
    if spans:
        out["editorial"] = spans
    return out


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

    Rubrics:
      speaker labels and their stage directions, red label lines and red
      instructions inside the text are marked as editorial spans of kind
      ``rubric`` (``_text_and_rubrics``); the text itself is unchanged.

    Returns
    -------
    List of ``{"ref": ..., "text": ...}`` dicts, one per liturgical passage,
    with ``"editorial": [[start, end, "rubric"], …]`` on a paragraph that has
    rubrics. Only paragraphs containing Greek text are included.
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
                text, rubrics = _text_and_rubrics(p)
                if not text or not _is_greek(text):
                    continue
                if span_cls & _DCS_SECTION_SPAN_CLASSES:
                    # Major section break — reset paragraph counter
                    section_n += 1
                    para_n = 0
                ref = slugify_ref(
                    f"ByzLit.{service_abbrev}.{section_n:04d}.{para_n:04d}"
                )
                paragraphs.append(_record(ref, text, rubrics))
                para_n += 1
                continue

            if cls & _DCS_SECTION_P_CLASSES:
                text, rubrics = _text_and_rubrics(p)
                if not text or not _is_greek(text):
                    continue
                section_n += 1
                para_n = 0
                ref = slugify_ref(
                    f"ByzLit.{service_abbrev}.{section_n:04d}.{para_n:04d}"
                )
                paragraphs.append(_record(ref, text, rubrics))
                para_n += 1
                continue

            # All remaining paragraph classes: dialog, inaudible, reading, hymn,
            # actor, actorinaudible, designation, etc.
            text, rubrics = _text_and_rubrics(p)
            if not text or not _is_greek(text):
                continue
            ref = slugify_ref(
                f"ByzLit.{service_abbrev}.{section_n:04d}.{para_n:04d}"
            )
            paragraphs.append(_record(ref, text, rubrics))
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
