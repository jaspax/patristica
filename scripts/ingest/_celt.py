"""
Shared helpers for CELT, the Corpus of Electronic Texts (celt.ucc.ie, University
College Cork; #541).

CELT publishes each text as one HTML page, ``published/{id}.html`` (``G…`` an
Irish text, ``T…`` its English translation), generated from its TEI master. The
page starts with the TEI header rendered as HTML (file description,
availability, sources, the edition used, the date of composition), then, after
``<h4 …>Corpus of Electronic Texts Edition: {id}</h4>`` and the
``<h3><cite>title</cite>: Author: …</h3>`` line, the text:

* page breaks of the printed edition, ``<hr><p align="right"><small><a
  name="p12">p.12</a></small></P>``, and manuscript locators in braces,
  ``{folio 22 a 1}``, ``{MS page 114}``: layout, dropped;
* the edition's line numbers, ``<br>17] `` (verse: every line or every
  quatrain; prose: per page), dropped, except where a text is cited by them
  (Saltair na Rann, see :func:`line_units`); paragraph numbers ``¶4]``;
* ``<li value="N">`` stanzas, ``<h4>N</h4>`` numbered sections, ``<p>`` and
  loose text paragraphs, ``<h2>``/``<h3>`` headings;
* inline markup with no meaning for us: ``<i>`` (expanded abbreviations),
  ``<u>`` (length marks supplied by the editor), ``<b>`` (tagged names),
  ``<a href="app001.html">`` (links into the apparatus); unwrapped;
* footnote calls ``<sup><a href="javascript:footNote(…)">1</a></sup>``: the
  notes are separate pages, which this ingestor does not fetch, so the call
  markers are dropped as layout;
* editorial material, marked as spans for the raw unit's ``editorial`` key
  (#236): ``[gap: …]`` lacunae (``lacuna``), other ``[…]`` restorations
  (``supplement``), deletions ``<s>…</s>`` and marginal references
  ``<p align="right">…</p>`` (``note``). Ingestors must not import
  ``patristica.editorial``, and nor does this module.

Licence (#541, #542): every CELT text says "Availability [RESTRICTED]:
Available with prior consent of the CELT programme for purposes of academic
research and teaching only". Until CELT grants permission, every CELT work is
``unknown`` (in ``EXCLUDED_LICENSES``: never translated, embedded, indexed or
published). :data:`CELT_LICENSE` is the one place to change when permission
arrives.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.ingest._common import download_file, offline

log = logging.getLogger(__name__)

# Licence of every CELT work. "unknown" until CELT grants permission to
# republish (#542); then "used-with-permission" plus a DATA_LICENSE.md record.
CELT_LICENSE = "unknown"

BASE_URL = "https://celt.ucc.ie/published/"
CACHE_SUBDIR = Path("_cache") / "celt"

# Seconds between two requests to CELT (be polite: one small server).
THROTTLE_SECONDS = 3.0

_last_request = 0.0


class CeltError(ValueError):
    """A CELT page is not structured as the ingestor expects."""


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def page_url(text_id: str) -> str:
    """The single-page edition of CELT text *text_id* (``G200001``)."""
    if not re.fullmatch(r"[GTL]\d{6}[A-Z]?", text_id):
        raise CeltError(f"not a CELT text id: {text_id!r}")
    return f"{BASE_URL}{text_id}.html"


def fetch(text_id: str, raw_dir: Path, *, force: bool = False) -> str:
    """The HTML of CELT text *text_id*, cached at ``{raw_dir}/_cache/celt/{id}.html``.

    Network requests are throttled to one per :data:`THROTTLE_SECONDS`; a cached
    page is used unless *force* (and never refetched ``--offline``, #215).
    """
    global _last_request
    dest = raw_dir / CACHE_SUBDIR / f"{text_id}.html"
    if not dest.exists() or (force and not offline()):
        wait = THROTTLE_SECONDS - (time.monotonic() - _last_request)
        if wait > 0 and not offline():
            time.sleep(wait)
        try:
            download_file(page_url(text_id), dest, etag_cache=False, force=force)
        finally:
            _last_request = time.monotonic()
    return decode(dest.read_bytes())


def decode(data: bytes) -> str:
    """A page's text. CELT pages are ASCII with character references, but a
    few carry raw Latin-1 letters (``Ca\\xefn``, ``\\xc1ed``): those are read
    as Windows-1252."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------


def _plain(fragment: str) -> str:
    text = re.sub(r"</?(?:i|u|b|em|cite|sup|small|a)(?:\s[^>]*)?>", "", fragment, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", html_lib.unescape(text)).strip()


@dataclass(frozen=True)
class Header:
    title: str
    author: str
    availability: str
    edition: str | None
    created: str | None


def _tidy_edition(text: str) -> str:
    """CELT's bibliographic line, with its rendering slips mended: a space
    before punctuation, and the publisher run into the place
    ("Dublin Institute for Advanced StudiesDublin")."""
    text = re.sub(r"\s+([.,;:)])", r"\1", text)
    return re.sub(r"(?<=[a-z])(?=(?:Dublin|London|Oxford|Cork|Halle|Paris)\b)", ", ", text)


def parse_header(page: str) -> Header:
    """The parts of the TEI header an ingestor records."""
    title = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S)
    author = re.search(r"<h2[^>]*>\s*Author:(.*?)</h2>", page, re.S)
    avail = re.search(r"Availability(.*?)<h4>", page, re.S)
    edition = re.search(
        r"<lh><b>The edition used in the digital edition</b></lh>\s*<li>(.*?)</li>", page, re.S
    ) or re.search(r"<lh><b>Editions?</b></lh>\s*<li>(.*?)</li>", page, re.S)
    created = re.search(r"Created:(.*?)<h[34]>", page, re.S)
    if not title or not avail:
        raise CeltError("no CELT header (title or availability statement missing)")
    return Header(
        title=_plain(title.group(1)),
        author=_plain(author.group(1)) if author else "",
        availability=_plain(avail.group(1)),
        edition=_tidy_edition(_plain(edition.group(1))) if edition else None,
        created=_plain(created.group(1)) if created else None,
    )


# ---------------------------------------------------------------------------
# Body
# ---------------------------------------------------------------------------


def body_html(page: str, text_id: str) -> str:
    """The text part of the page: after the ``Edition: {id}`` line and its ``<cite>`` title."""
    marker = f"Corpus of Electronic Texts Edition: {text_id}</h4>"
    i = page.rfind(marker)
    if i < 0:
        raise CeltError(f"{text_id}: no '{marker}' line")
    body = page[i + len(marker) :]
    m = re.match(r"\s*<h3><cite>.*?</h3>", body, re.S)
    if not m:
        raise CeltError(f"{text_id}: no <cite> title line after the edition line")
    body = body[m.end() :]
    end = body.rfind("</body>")
    return body[:end] if end >= 0 else body


_PAGE_BREAK = re.compile(
    r"<hr>\s*<p align=\"right\"><small><a name=\"[^\"]*\">[^<]*</a></small></P>", re.I
)
_FOOTNOTE = re.compile(r"\s*<sup><a href=\"javascript:footNote\([^)]*\)\">[^<]*</a></sup>", re.I)
_LOCATOR = re.compile(r"\{[^{}<>]{1,80}\}")
_SIGNATURE = re.compile(r"<div align=\"right\">.*?</div>", re.S | re.I)
_WITNESSES = re.compile(r"<h3>List of witnesses</h3>\s*<ul>.*?</ul>", re.S | re.I)
_LINE_NO = re.compile(r"(?<![\w&#])(\d{1,5})\]\s*")
_PARA_NO = re.compile(r"(?:&#182;|¶)\s*(\d{1,4})\]\s*")


def strip_layout(body: str) -> str:
    """Drop page breaks, footnote calls, manuscript locators, witness lists and signatures."""
    body = _PAGE_BREAK.sub("\n", body)
    body = _FOOTNOTE.sub("", body)
    body = _WITNESSES.sub("", body)
    body = _SIGNATURE.sub("", body)  # an editor's signature ("Charlottenburg. Kuno Meyer.")
    return _LOCATOR.sub("", body)


# Sentinels for editorial spans while the markup is reduced to text: a kind
# letter after OPEN, CLOSE at its end. Private-use code points, never in CELT.
_OPEN, _CLOSE = "\ue000", "\ue001"
_KIND_CODES = {"l": "lacuna", "s": "supplement", "n": "note", "m": "metadata", "h": "heading"}
_CODES = {v: k for k, v in _KIND_CODES.items()}


def mark(text: str, kind: str) -> str:
    """*text* wrapped as an editorial span of *kind* (resolved by :func:`inline`)."""
    return f"{_OPEN}{_CODES[kind]}{text}{_CLOSE}"


def inline(fragment: str) -> tuple[str, list[list[Any]]]:
    """An HTML fragment as plain text with its editorial spans.

    Line numbers and tags are dropped, character references resolved, a word
    hyphenated across a source line joined, whitespace collapsed; ``[gap: …]``
    becomes a ``lacuna`` span, any other ``[…]`` a ``supplement``, ``<s>``
    and right-aligned marginal references a ``note``.
    """
    s = _FOOTNOTE.sub("", fragment)
    s = re.sub(
        r"<p align=\"right\">(.*?)</p>",
        lambda m: " " + mark("[" + _plain(m.group(1)) + "]", "note") + " ",
        s,
        flags=re.S | re.I,
    )
    s = re.sub(r"<s>(.*?)</s>", lambda m: mark(m.group(1), "note"), s, flags=re.S)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</?(?:p|div|li|ol|ul|blockquote)(?:\s[^>]*)?>", " ", s, flags=re.I)  # blocks
    s = _PARA_NO.sub("", s)
    s = re.sub(r"(^|\n)\s*\d{1,5}\]", r"\1", s)
    s = re.sub(r"<[^>]+>", "", s)  # every other tag
    s = html_lib.unescape(s)
    s = s.replace("\xa0", " ")
    # A word hyphenated across a line of the source file: n-\n\ningen.
    s = re.sub(r"(?<=\w-)[ \t]*\n\s*(?=\w)", "", s)
    # CELT's placeholders for characters its HTML could not show.
    s = re.sub(r"\[macr\s*\]", "\u0304", s)  # a macron over the letter before
    s = re.sub(r"\s*\[excl\s*\]", "!", s)
    s = re.sub(r"\[sect\s*\]", "§", s)
    s = re.sub(
        r"\[\s*gap:([^\]]*)\]", lambda m: mark("[gap:" + m.group(1).rstrip() + "]", "lacuna"), s
    )
    s = re.sub(
        r"(?<!\ue000[ln])\[[^\[\]\ue000\ue001]{1,200}\]",
        lambda m: mark(m.group(0), "supplement"),
        s,
    )
    s = re.sub(r"\s+", " ", s).strip()
    return resolve(s)


def resolve(s: str) -> tuple[str, list[list[Any]]]:
    """Text with sentinels → ``(text, spans)``; spans in Python ``str`` offsets."""
    out: list[str] = []
    spans: list[list[Any]] = []
    stack: list[tuple[int, str]] = []
    i = 0
    n = 0
    while i < len(s):
        c = s[i]
        if c == _OPEN:
            stack.append((n, _KIND_CODES[s[i + 1]]))
            i += 2
            continue
        if c == _CLOSE:
            start, kind = stack.pop()
            if n > start and not any(a <= start and n <= b for a, b, _ in spans):
                spans = [sp for sp in spans if not (start <= sp[0] and sp[1] <= n)]
                spans.append([start, n, kind])
            i += 1
            continue
        out.append(c)
        n += 1
        i += 1
    if stack:
        raise CeltError(f"unbalanced editorial marks in {s[:80]!r}")
    text = "".join(out)
    # Trim spans to the text (whitespace at the edges) and drop empty ones.
    fixed: list[list[Any]] = []
    for start, end, kind in sorted(spans):
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if end > start:
            fixed.append([start, end, kind])
    return text, fixed


def unit(ref: str, text: str, spans: list[list[Any]] | None = None) -> dict[str, Any]:
    u: dict[str, Any] = {"ref": ref, "text": text}
    if spans:
        u["editorial"] = spans
    return u


def heading_unit(ref: str, text: str) -> dict[str, Any]:
    return unit(ref, text, [[0, len(text), "heading"]])


def join_units(parts: list[tuple[str, list[list[Any]]]]) -> tuple[str, list[list[Any]]]:
    """Several ``(text, spans)`` joined with spaces, the spans shifted."""
    text = ""
    spans: list[list[Any]] = []
    for t, sp in parts:
        if not t:
            continue
        if text:
            text += " "
        spans.extend([a + len(text), b + len(text), k] for a, b, k in sp)
        text += t
    return text, spans


# ---------------------------------------------------------------------------
# Events: the body as a flat run of headings, stanzas and paragraphs
# ---------------------------------------------------------------------------


@dataclass
class Event:
    kind: str  # "head", "stanza", "para"
    html: str
    level: int = 0  # heading level
    number: int | None = None  # stanza value, paragraph number (¶N)


_EVENT_RE = re.compile(
    r"<h([2-5])[^>]*>(?P<head>.*?)</h\1>"
    r"|<li(?: value=\"(?P<val>\d+)\")?>(?P<li>.*?)(?:</li>|(?=<li[ >]|</ol>))"
    r"|<p(?:\s[^>]*)?>|</p>|</?(?:ol|ul|blockquote|div|address)[^>]*>",
    re.S | re.I,
)


def events(body: str) -> list[Event]:
    """The body as headings, stanzas (``<li value>``) and paragraphs, in order.

    Paragraphs are the text between ``<p>`` boundaries (and between other
    blocks); empty ones are skipped. A right-aligned ``<p>`` (a marginal
    reference) stays inside the paragraph around it.
    """
    body = strip_layout(body)
    # Marginal references are inline notes, not paragraph boundaries.
    body = re.sub(
        r"<p align=\"right\">(.*?)</p>",
        lambda m: "<x-note>" + m.group(1) + "</x-note>",
        body,
        flags=re.S | re.I,
    )
    out: list[Event] = []
    pos = 0

    def flush(chunk: str) -> None:
        chunk = chunk.replace("<x-note>", '<p align="right">').replace("</x-note>", "</p>")
        if inline(chunk)[0]:
            m = _PARA_NO.search(chunk)
            number = int(m.group(1)) if m and not inline(chunk[: m.start()])[0] else None
            out.append(Event("para", chunk, number=number))

    for m in _EVENT_RE.finditer(body):
        flush(body[pos : m.start()])
        pos = m.end()
        if m.group("head") is not None:
            out.append(Event("head", m.group("head"), level=int(m.group(1))))
        elif m.group("li") is not None:
            li = m.group("li").replace("<x-note>", '<p align="right">').replace("</x-note>", "</p>")
            out.append(Event("stanza", li, number=int(m.group("val")) if m.group("val") else None))
    flush(body[pos:])
    return out
