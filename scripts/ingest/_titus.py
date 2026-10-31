"""
Shared helpers for TITUS (titus.uni-frankfurt.de) text sets (#514).

TITUS publishes each text set as a frame page (``adisn.htm``) whose text
frame shows numbered part pages (``adisn001.htm``, ``adisn002.htm``, …),
each ending with a "Next part" link. A part page is a flat run of
``<span id=…>`` elements:

* **location markers**, ``<span id=h4><!Level 4>Verse: 1<A NAME=…>``: a
  regular level (Text collection, Book, Chapter, Verse, Text, Page of ed.,
  Line of ed., Entry, Paragraph, …) or, with ``<!XLevel n>``, a parallel
  manuscript level (Ms. page, Line of ms.);
* **text segments** whose id encodes script, language, style flags and
  size: ``mx`` Mkhedruli / ``as`` Asomtavruli / ``nu`` Nuskhuri, then
  ``ag`` Old Georgian / ``xg`` khanmeti / ``hg`` haemeti / ``ng`` modern
  Georgian (an editor's heading), then flags (``v`` variant reading,
  ``b`` rubric, ``p`` proper name, ``x`` biblical text, ``l``/``n`` layers
  of the Paris lectionary, …), then the font size: ``mxagx16``,
  ``mxagv12``, ``asxgx16``;
* sigla and editors' notes in Latin script (``nc12``, ``nx16``), and the
  set's header (``title``, ``subtitle``, ``textdescr``, ``bibliogr``).

Every word of the text is a concordance link (``<a href="javascript:ci(…)">``);
parsing keeps only the link text.

This module gives an ingestor:

* :func:`fetch` / :func:`iter_pages`: polite, throttled fetching with a
  browser User-Agent and Referer, cached gzipped under
  ``data/raw/_cache/titus/`` so a source regenerates offline (#215);
  members-only / private-use sets raise :class:`TitusRestricted`;
* :func:`parse_page`: a page as a list of :class:`Marker` and
  :class:`Segment`; :func:`locate` carries the current location onto each
  segment; :func:`collect_units` joins the segments of each location into
  :class:`Unit` s with their editorial spans;
* :func:`clean_text`: TITUS's editorial signs to ``(text, spans)``:
  ``[…]`` restorations, ``(…)`` abbreviation expansions and ``<…>``
  additions as ``supplement``, ``...`` / ``[...]`` as ``lacuna``, ``[!]`` and
  ``{…}`` as ``note``; spans are ``[start, end, kind]`` in Python ``str``
  offsets, for the raw unit's ``editorial`` key (#236). Ingestors must not
  import ``patristica.editorial``, and nor does this module;
* :func:`parse_header`, :data:`TITUS_LICENSE`, :func:`edition_line`.

Licence (#514): TITUS allows free scholarly, non-commercial use, but every
page says "No parts of this document may be republished in any form without
prior permission by the copyright holder". Until TITUS grants permission,
every TITUS work is ``unknown`` (in ``EXCLUDED_LICENSES``: never translated,
embedded, indexed or published). :data:`TITUS_LICENSE` is the one place to
change when permission arrives.
"""

from __future__ import annotations

import gzip
import html as html_lib
import logging
import re
import time
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from scripts.ingest._common import offline, require_network

log = logging.getLogger(__name__)

# Licence of every TITUS work. "unknown" until TITUS grants permission to
# republish (#514); then "used-with-permission" plus a DATA_LICENSE.md record.
TITUS_LICENSE = "unknown"

BASE_URL = "https://titus.uni-frankfurt.de/texte/"
CACHE_SUBDIR = Path("_cache") / "titus"

# Seconds between two requests to TITUS (be polite: one small server).
THROTTLE_SECONDS = 3.0

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,de;q=0.8",
}

_last_request = 0.0


class TitusError(RuntimeError):
    """A TITUS page could not be fetched or parsed."""


class TitusRestricted(TitusError):
    """A members-only or private-use TITUS set: never ingested (log and skip)."""


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def is_restricted_url(url: str) -> bool:
    """Whether *url* is in TITUS's restricted areas (members only, private use)."""
    parsed = urlparse(url)
    return (
        "/etcc/" in parsed.path
        or "/private/" in parsed.path
        or parsed.netloc.startswith("titus.fkidg1.")
    )


def cache_path(url: str, raw_dir: Path) -> Path:
    """Where the page at *url* is cached: ``{raw_dir}/_cache/titus/{path}.gz``."""
    path = urlparse(url).path
    rel = path.split("/texte/", 1)[1] if "/texte/" in path else path.lstrip("/")
    if not rel or ".." in Path(rel).parts:
        raise TitusError(f"not a TITUS text URL: {url}")
    return raw_dir / CACHE_SUBDIR / (rel + ".gz")


def fetch(url: str, raw_dir: Path, *, force: bool = False, referer: str | None = None) -> str:
    """The HTML of the TITUS page *url*, from the cache or the network.

    A cached page is used unless *force* (and not ``--offline``, #215). Network
    requests are throttled to one per :data:`THROTTLE_SECONDS` and carry a
    browser User-Agent and a Referer (the page's directory unless given): TITUS
    has answered bare requests with 403. A restricted URL, or a 401/403 answer,
    raises :class:`TitusRestricted`.
    """
    global _last_request
    if is_restricted_url(url):
        raise TitusRestricted(f"TITUS set is members-only / private use: {url}")
    dest = cache_path(url, raw_dir)
    if dest.exists() and (not force or offline()):
        return gzip.decompress(dest.read_bytes()).decode("utf-8")
    require_network(f"fetching {url}")

    wait = THROTTLE_SECONDS - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    headers = dict(_HEADERS, Referer=referer or url.rsplit("/", 1)[0] + "/")
    log.info("Fetching %s", url)
    try:
        with httpx.Client(follow_redirects=True, timeout=120) as client:
            resp = client.get(url, headers=headers)
    finally:
        _last_request = time.monotonic()
    if is_restricted_url(str(resp.url)) or resp.status_code in (401, 403):
        raise TitusRestricted(f"TITUS refused {url} (HTTP {resp.status_code}, {resp.url})")
    if resp.status_code == 404:
        raise TitusError(f"TITUS page not found: {url}")
    resp.raise_for_status()
    text = resp.content.decode("utf-8")
    dest.parent.mkdir(parents=True, exist_ok=True)
    # mtime 0: the same page gives the same bytes (git-lfs objects stay stable).
    dest.write_bytes(gzip.compress(resp.content, mtime=0))
    return text


_FRAME_TEXT_RE = re.compile(r'<frame\s+src="([^"]+)"\s+name="etatext"', re.I)
_NEXT_RE = re.compile(r'<A HREF="([^"]+)"><img src="/arribar\.gif" alt="Next part">', re.I)


def first_page_url(frame_url: str, frame_html: str) -> str:
    """The first part page of a set, from its frame page."""
    m = _FRAME_TEXT_RE.search(frame_html)
    if not m:
        raise TitusError(f"no text frame in {frame_url}")
    return urljoin(frame_url, m.group(1))


def next_page_url(page_url: str, page_html: str) -> str | None:
    """The page's "Next part" link, or None on the last page."""
    m = _NEXT_RE.search(page_html)
    return urljoin(page_url, m.group(1)) if m else None


def iter_pages(
    frame_url: str, raw_dir: Path, *, force: bool = False,
) -> Iterator[tuple[str, str]]:
    """Every part page of the set whose frame page is *frame_url*: ``(url, html)``.

    Follows the "Next part" links from the frame's first page. A restricted
    set raises :class:`TitusRestricted` before anything is fetched.
    """
    frame_html = fetch(frame_url, raw_dir, force=force)
    url: str | None = first_page_url(frame_url, frame_html)
    seen: set[str] = set()
    while url is not None:
        if url in seen:
            raise TitusError(f"page cycle at {url} in {frame_url}")
        seen.add(url)
        page = fetch(url, raw_dir, force=force, referer=frame_url)
        yield url, page
        url = next_page_url(url, page)


# ---------------------------------------------------------------------------
# Parsing a part page
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Marker:
    """A location marker: ``Verse: 1`` at level 4, or (``extra``) ``Ms. page: 1r``."""

    level: int
    label: str
    value: str
    extra: bool = False  # an <!XLevel>: manuscript page/line, parallel to the levels
    # The &nbsp;s after the marker, before the text it locates. Prose sets mark a
    # paragraph's first line by indenting it (Coll. hag.: 6 against 3, #516).
    # Not compared, so a Marker built by hand equals the parsed one.
    indent: int = field(default=0, compare=False)


# Old Georgian language codes in a segment class; ``ng`` (modern Georgian) is
# an editor's heading, not text.
OLD_GEORGIAN_LANGS = frozenset({"ag", "xg", "hg"})
GEORGIAN_SCRIPTS = frozenset({"mx", "as", "nu"})

_CLASS_RE = re.compile(r"^(?P<script>[a-z]{2})(?P<lang>[a-z]{2})(?P<flags>[a-z]*)(?P<size>\d+)$")


@dataclass(frozen=True)
class Segment:
    """A run of text in one span class (``mxagx16``)."""

    cls: str
    text: str  # tags stripped, entities decoded, <BR> as "\n"; whitespace as in the page
    # A <BR> or a whitespace-only span came between the previous segment and
    # this one (both dropped), so a word ends before it even when neither text
    # has a space there (#516). Not compared.
    space_before: bool = field(default=False, compare=False)

    @property
    def _parts(self) -> re.Match[str] | None:
        return _CLASS_RE.match(self.cls)

    @property
    def script(self) -> str:
        """``mx``, ``as``, ``nu``, or ``""`` for a non-Georgian class (``nc12``)."""
        m = self._parts
        return m.group("script") if m and m.group("script") in GEORGIAN_SCRIPTS else ""

    @property
    def lang(self) -> str:
        m = self._parts
        return m.group("lang") if m and self.script else ""

    @property
    def flags(self) -> str:
        m = self._parts
        return m.group("flags") if m and self.script else ""

    @property
    def size(self) -> int:
        m = re.search(r"\d+$", self.cls)
        return int(m.group()) if m else 0

    @property
    def is_old_georgian(self) -> bool:
        return self.lang in OLD_GEORGIAN_LANGS

    @property
    def is_variant(self) -> bool:
        return "v" in self.flags


Event = Marker | Segment

# Header spans: read by parse_header, never text.
HEADER_CLASSES = frozenset({"titus", "title", "subtitle", "textdescr", "bibliogr"})

_LEVEL_RE = re.compile(r"<!(X?)Level\s+(\d+)>\s*([^<:]+?):\s*([^<]*?)\s*<A NAME", re.I)
_SPAN_OPEN_RE = re.compile(r"<span id=([A-Za-z0-9_]+)>", re.I)
_FOOTER_RE = re.compile(
    r"<DIV ALIGN=RIGHT><A HREF=[^>]*><img src=\"/arribar|<HR><BR>This text is part of", re.I)


def _strip_tags(fragment: str) -> str:
    fragment = re.sub(r"<BR\s*/?>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"<![^>]*>", "", fragment)  # <!Level 4> comments
    fragment = re.sub(r"<[^>]+>", "", fragment)
    return html_lib.unescape(fragment).replace("\xa0", " ")


_BR_RE = re.compile(r"<BR\b", re.I)
_INDENT_RE = re.compile(r"(?:&nbsp;|\s)*", re.I)


def _indent_after(rest: str) -> int:
    """The &nbsp;s right after a marker span's ``</sPAN>`` in *rest* (0 if none)."""
    close = re.search(r"</span>", rest, re.I)
    if not close:
        return 0
    return _INDENT_RE.match(rest, close.end()).group().lower().count("&nbsp;")


def parse_page(page_html: str) -> list[Event]:
    """A part page as its markers and segments, in page order.

    Spans are flat in TITUS's HTML (a marker span may sit inside an ``n16``
    or ``nc12`` span, which is closed later), so this scans span openings: a
    segment is the text from one opening to the next ``</span>`` or opening.
    Header spans and the page footer are left out; empty segments too.
    """
    end = _FOOTER_RE.search(page_html)
    body = page_html[: end.start()] if end else page_html
    body_start = re.search(r"<BODY[^>]*>", body, re.I)
    if body_start:
        body = body[body_start.end():]
    events: list[Event] = []
    opens = list(_SPAN_OPEN_RE.finditer(body))
    line_break = False  # a <BR> or a blank span since the last segment's text
    for i, m in enumerate(opens):
        cls = m.group(1).lower()
        stop = opens[i + 1].start() if i + 1 < len(opens) else len(body)
        chunk = body[m.end():stop]
        if i == 0 and _BR_RE.search(body[:m.start()]):
            line_break = True
        if re.fullmatch(r"h\d+", cls):
            line_break = line_break or bool(_BR_RE.search(chunk))
            lm = _LEVEL_RE.search(chunk)
            if lm:
                events.append(Marker(
                    level=int(lm.group(2)),
                    label=_strip_tags(lm.group(3)).strip(),
                    value=_strip_tags(lm.group(4)).strip(),
                    extra=bool(lm.group(1)),
                    indent=_indent_after(chunk[lm.end():]),
                ))
            continue
        if cls in HEADER_CLASSES:
            line_break = line_break or bool(_BR_RE.search(chunk))
            continue
        close = re.search(r"</span>", chunk, re.I)
        text = _strip_tags(chunk[: close.start()] if close else chunk)
        if text.strip():
            events.append(Segment(cls=cls, text=text, space_before=line_break))
            line_break = False
            tail = chunk[close.end():] if close else ""
        else:
            tail = chunk
            line_break = line_break or bool(text)
        line_break = line_break or bool(_BR_RE.search(tail))
    return events


@dataclass(frozen=True)
class Located:
    """A segment with the location it is in."""

    loc: Mapping[str, str]   # regular levels: label → value ("Book" → "Mt.")
    xloc: Mapping[str, str]  # manuscript levels (XLevel)
    segment: Segment


def locate(events: Iterable[Event]) -> Iterator[Located]:
    """Carry the current location onto every segment.

    A marker at level *n* sets its label and clears every deeper level (of
    its own kind: regular or XLevel). Feed the events of all pages of a set
    in order, so a location carries over page breaks.
    """
    levels: dict[int, tuple[str, str]] = {}
    xlevels: dict[int, tuple[str, str]] = {}
    for ev in events:
        if isinstance(ev, Marker):
            target = xlevels if ev.extra else levels
            for lvl in [k for k in target if k >= ev.level]:
                del target[lvl]
            target[ev.level] = (ev.label, ev.value)
            continue
        yield Located(
            loc={lab: val for _, (lab, val) in sorted(levels.items())},
            xloc={lab: val for _, (lab, val) in sorted(xlevels.items())},
            segment=ev,
        )


def is_main_text(segment: Segment) -> bool:
    """Old Georgian text that is not a variant reading (the default unit filter)."""
    return segment.is_old_georgian and not segment.is_variant


@dataclass
class Unit:
    """The text of one location: what an ingestor writes as ``{ref, text, editorial}``."""

    key: tuple[str | None, ...]
    loc: Mapping[str, str]
    text: str
    editorial: list[list[int | str]] = field(default_factory=list)
    xloc: Mapping[str, str] = field(default_factory=dict)  # at the unit's start

    def raw(self, ref: str) -> dict[str, object]:
        """The raw-file record for this unit under *ref* (``editorial`` only when set)."""
        rec: dict[str, object] = {"ref": ref, "text": self.text}
        if self.editorial:
            rec["editorial"] = [list(s) for s in self.editorial]
        return rec


def collect_units(
    located: Iterable[Located],
    key: Sequence[str],
    *,
    include: Callable[[Segment], bool] = is_main_text,
    clean: Callable[[str], tuple[str, list[list[int | str]]]] | None = None,
) -> list[Unit]:
    """Join the included segments of each location into units.

    *key* names the location labels that make a unit (``("Book", "Chapter",
    "Verse")``); consecutive segments with the same values join with a space,
    and a unit starts afresh whenever the key changes (a key seen again later
    is a new unit: callers check for duplicates). Segments with none of the
    key's labels set are skipped. Each unit's text goes through *clean*
    (default :func:`clean_text`); units left empty are dropped.
    """
    clean = clean or clean_text
    units: list[Unit] = []
    cur_key: tuple[str | None, ...] | None = None
    parts: list[str] = []
    cur_loc: Mapping[str, str] = {}
    cur_xloc: Mapping[str, str] = {}

    def flush() -> None:
        if cur_key is None or not parts:
            return
        text, spans = clean(" ".join(parts))
        if text:
            units.append(Unit(key=cur_key, loc=cur_loc, text=text, editorial=spans, xloc=cur_xloc))

    for item in located:
        if not include(item.segment):
            continue
        k = tuple(item.loc.get(lab) for lab in key)
        if all(v is None for v in k):
            continue
        if k != cur_key:
            flush()
            cur_key, parts, cur_loc, cur_xloc = k, [], item.loc, item.xloc
        parts.append(item.segment.text)
    flush()
    return units


# ---------------------------------------------------------------------------
# Editorial signs
# ---------------------------------------------------------------------------

# Bracket pairs and the editorial kind of their content (#236). In TITUS's
# Old Georgian sets, [..] restores damaged or lost letters, (..) expands an
# abbreviation, <..> is an editor's addition: all supplements, kept in the
# source text without the brackets. {..} encloses letters the editor deletes
# (a scribal slip, "ლოც{ვ}აჲ"): a note, so they stay visible but are neither
# translated nor embedded.
BRACKET_KINDS: dict[str, tuple[str, str]] = {
    "[": ("]", "supplement"),
    "(": (")", "supplement"),
    "<": (">", "supplement"),
    "{": ("}", "note"),
}
# Formatting signs dropped from the text: "/" a manuscript line break inside a
# word, "\" a letter written above the line, "^" a superscript letter, "*" a
# pointer to the edition's apparatus.
DROPPED_CHARS = "/\\^*"

_LACUNA_CONTENT_RE = re.compile(r"^[\s.…\-–]*$")
_ELLIPSIS_RE = re.compile(r"\.{2,}|…+")
_SIC_RE = re.compile(r"^\s*[!?]+\s*$")


def clean_text(
    raw: str,
    *,
    brackets: Mapping[str, tuple[str, str]] = BRACKET_KINDS,
    dropped: str = DROPPED_CHARS,
) -> tuple[str, list[list[int | str]]]:
    """TITUS text to ``(text, editorial spans)``.

    Whitespace is collapsed and *dropped* characters removed; brackets stay
    in the text and each outermost bracketed group becomes a span covering it
    with its brackets: a group of only dots (``[...]``, ``<...>``) is a
    ``lacuna``, ``[!]`` a ``note``, any other the kind in *brackets*. A run of
    two or more dots (or ``…``) outside brackets is a ``lacuna``. An
    unmatched closing bracket opens its span at the text's start; an unclosed
    one runs to the end (a restoration across a page or unit break).
    """
    text = raw.translate({ord(c): None for c in dropped})
    text = re.sub(r"\s+", " ", text).strip()
    closers = {close: op for op, (close, _) in brackets.items()}
    spans: list[list[int | str]] = []
    stack: list[tuple[str, int]] = []

    def add(start: int, end: int, content: str, opener: str) -> None:
        if content.strip() and _LACUNA_CONTENT_RE.match(content):
            kind = "lacuna"
        elif _SIC_RE.match(content):
            kind = "note"
        else:
            kind = brackets[opener][1]
        spans.append([start, end, kind])

    for i, ch in enumerate(text):
        if ch in brackets:
            stack.append((ch, i))
        elif ch in closers:
            opener = closers[ch]
            if stack and stack[-1][0] == opener:
                _, start = stack.pop()
                if not stack:
                    add(start, i + 1, text[start + 1:i], opener)
            elif not stack and not spans:
                # closes a group opened before this unit (across a page break)
                add(0, i + 1, text[:i], opener)
    if stack:
        opener, start = stack[0]
        add(start, len(text), text[start + 1:], opener)

    covered = [(int(s[0]), int(s[1])) for s in spans]
    for m in _ELLIPSIS_RE.finditer(text):
        if not any(s <= m.start() < e for s, e in covered):
            spans.append([m.start(), m.end(), "lacuna"])
    spans.sort(key=lambda s: (s[0], s[1]))
    # merge overlaps (an unmatched closer's span and an earlier group)
    merged: list[list[int | str]] = []
    for s in spans:
        if merged and int(s[0]) < int(merged[-1][1]):
            merged[-1][1] = max(int(merged[-1][1]), int(s[1]))
            continue
        merged.append(s)
    return text, merged


# ---------------------------------------------------------------------------
# Set header and attribution
# ---------------------------------------------------------------------------

@dataclass
class SetHeader:
    """What a set's first part page says about the set."""

    title: str = ""
    subtitle: str = ""
    description: str = ""   # textdescr: "On the basis of …", "TITUS version by …"
    bibliography: str = ""  # bibliogr: the printed edition(s)
    version_by: list[str] = field(default_factory=list)  # "Jost Gippert"
    last_changed: str = ""  # ISO date of the page's copyright line ("2022-02-16")
    restricted: bool = False  # members only / private use

    @property
    def printed_edition(self) -> str:
        """The bibliography as one line, without TITUS's own credits (empty when none)."""
        return _one_line(_CREDITS_RE.split(self.bibliography, maxsplit=1)[0]).rstrip(" ,;")


def _one_line(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("\n", " ")).strip()


def _iso_date(dmy: str) -> str:
    d, m, y = (int(x) for x in dmy.split("."))
    return f"{y:04d}-{m:02d}-{d:02d}"


_COPYRIGHT_RE = re.compile(
    r"TITUS Project</A>,\s*Frankfurt a/M,\s*(\d{1,2}\.\d{1,2}\.\d{4})", re.I)
_VERSION_BY_RE = re.compile(r"(?:TITUS|ARMAZI) version by\s+(.+?),\s*\n", re.S)
_CREDITS_RE = re.compile(
    r"\b(?:electronically (?:prepared|edited)|(?:TITUS|ARMAZI) version)\b", re.I)
_RESTRICTED_RE = re.compile(r"members only|private use only|nur für mitglieder", re.I)


def page_date(page_html: str) -> str:
    """The ISO date of a page's copyright line ("Frankfurt a/M, 16.2.2022"), or ""."""
    dates = _COPYRIGHT_RE.findall(page_html)
    return _iso_date(dates[-1]) if dates else ""


def parse_header(page_html: str) -> SetHeader:
    """The header of a set's first part page (or any page: the date is on all)."""
    body = page_html
    texts: dict[str, list[str]] = {c: [] for c in ("title", "subtitle", "textdescr", "bibliogr")}
    opens = list(_SPAN_OPEN_RE.finditer(body))
    for i, m in enumerate(opens):
        cls = m.group(1).lower()
        if cls not in texts:
            continue
        stop = opens[i + 1].start() if i + 1 < len(opens) else len(body)
        chunk = body[m.end():stop]
        close = re.search(r"</span>", chunk, re.I)
        texts[cls].append(_strip_tags(chunk[: close.start()] if close else chunk).strip())
    header = SetHeader(
        title=_one_line(" ".join(texts["title"])),
        subtitle="\n".join(t for t in texts["subtitle"] if t),
        description="\n".join(t for t in texts["textdescr"] if t),
        bibliography="\n".join(t for t in texts["bibliogr"] if t),
    )
    header.version_by = [
        _one_line(name) for name in _VERSION_BY_RE.findall(_strip_tags(page_html))
    ]
    header.last_changed = page_date(page_html)
    header.restricted = bool(_RESTRICTED_RE.search(_strip_tags(page_html)))
    return header


def edition_line(
    printed_edition: str,
    *,
    editors: Sequence[str] = ("Jost Gippert",),
    last_changed: str = "",
) -> str:
    """The attribution TITUS asks for, for ``Work.edition``.

    ``"TITUS (ed. Jost Gippert), after {printed_edition}; last changed
    2022-02-16"``. Pass the set's :class:`SetHeader` fields:
    ``edition_line(h.printed_edition, editors=h.version_by, last_changed=h.last_changed)``.
    """
    ed = " and ".join(e for e in editors if e) or "Jost Gippert"
    line = f"TITUS (ed. {ed})"
    if printed_edition:
        line += f", after {_one_line(printed_edition)}"
    if last_changed:
        line += f"; last changed {last_changed}"
    return line
