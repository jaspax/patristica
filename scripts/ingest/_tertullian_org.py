"""
Shared scraper for the pages of Roger Pearse's *Early Church Fathers –
Additional Texts* (https://www.tertullian.org/fathers/, #347).

The pages are hand-made or Word-exported HTML transcriptions of printed
translations (Library of the Fathers, SPCK, Bohn, Hakluyt, Wright's
*Apocryphal Acts*, …) and of translations Pearse commissioned, each ending
"All material on this page is in the public domain - copy freely".  They share
a frame:

- a navigation bar (images) and the page's title, then an ``<hr>``;
- the text, sometimes after a table of contents and an ``<hr>``;
- the footnotes, after another ``<hr>`` (or on a page of their own,
  ``…_fn.htm``), linked from short markers in the text (``<a href="#12">12</a>``,
  Word's ``<a href="#_ftn1">[1]</a>``);
- the navigation bar again and the public-domain statement.

So a page is cut into *segments* at its ``<hr>`` rules and into *blocks*
(``p``, headings, ``li``, ``pre``, and ``div``/``blockquote``/``td`` that hold
no blocks of their own).  The text is the page's largest segment unless the
work's configuration names others (:class:`PageSpec`).  Every block is one
unit; the scraper never joins or splits paragraphs.

Editorial material (#236), marked rather than deleted:

- a footnote is put in place of its marker, in brackets, marked ``note``; a
  footnote the text never calls (a page's margin summaries, Pearse's notes on
  the transcription) is not carried, nor are the marker-less notes of a
  segment outside the text;
- headings (``h1``–``h6``, a short centred or wholly bold paragraph, an entry
  of a table of contents) are whole-unit ``heading`` spans;
- a translator's introduction to a letter or chapter set in small type
  (``p.smallish``) is a whole-unit ``note``.

Page numbers (``<span class="pb">|88</span>``), images and the navigation and
licence lines are layout and are dropped.

``_pearse_arabic`` (the Christian Arabic pages, #479) shares the cache
directory and the download helper, not this parser: its pages hold two
languages and Word footnotes of their own.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

from bs4 import Comment, NavigableString, Tag

from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

BASE_URL = "https://www.tertullian.org/fathers/"
#: The same cache as ``_pearse_arabic`` (relative to ``data/raw``).
CACHE_DIR = Path("_cache") / "tertullian-org"


class TertullianParseError(RuntimeError):
    pass


def page_url(file: str) -> str:
    return BASE_URL + file


def fetch(file: str, raw_dir: Path, force: bool = False) -> Path:
    """The cached page ``data/raw/_cache/tertullian-org/{file}`` (downloaded once)."""
    return download_file(page_url(file), raw_dir / CACHE_DIR / file, force=force)


def decode(raw: bytes) -> str:
    """The page's text: UTF-8, or Windows-1252 for the older Word exports."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp1252")


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

_WS_RE = re.compile(r"\s+")


@dataclass
class Unit:
    text: str
    spans: list[list] = field(default_factory=list)

    def record(self, ref: str) -> dict:
        rec: dict = {"ref": ref, "text": self.text}
        if self.spans:
            rec["editorial"] = self.spans
        return rec

    @property
    def editorial_only(self) -> bool:
        return bool(self.spans) and self.spans[0][0] == 0 and self.spans[0][1] == len(self.text)


class _Builder:
    """Text with editorial spans, whitespace collapsed as it is built."""

    def __init__(self) -> None:
        self.text = ""
        self.spans: list[list] = []

    def add(self, piece: str, kind: str | None = None) -> None:
        piece = _WS_RE.sub(" ", piece.replace("\xa0", " "))
        if not piece:
            return
        if not self.text or self.text.endswith(" "):
            piece = piece.lstrip()
            if not piece:
                return
        if kind is None:
            self.text += piece
            return
        piece = piece.strip()
        if not piece:
            return
        if self.text and not self.text.endswith(" "):
            self.text += " "
        self.spans.append([len(self.text), len(self.text) + len(piece), kind])
        self.text += piece + " "

    def unit(self, whole: str | None = None) -> Unit:
        text = self.text.strip()
        lead = len(self.text) - len(self.text.lstrip())
        spans = [[s - lead, min(e - lead, len(text)), k] for s, e, k in self.spans]
        spans = [s for s in spans if s[0] < s[1]]
        if whole and text:
            spans = [[0, len(text), whole]]
        return Unit(text, spans)


# ---------------------------------------------------------------------------
# Blocks and segments
# ---------------------------------------------------------------------------

_LEAF_BLOCKS = frozenset({"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "pre", "dt", "dd"})
_CONTAINERS = frozenset({"div", "blockquote", "center", "td", "th", "body", "table", "tbody",
                         "thead", "tr", "ul", "ol", "dl", "font", "span", "form", "section",
                         "address", "i", "b", "em", "strong", "small", "big", "a", "sup"})
_SKIP = frozenset({"script", "style", "img", "head", "map", "area", "noscript", "iframe"})
_BLOCKISH = _LEAF_BLOCKS | {"div", "blockquote", "center", "table", "tr", "td", "ul", "ol",
                            "dl", "hr"}


@dataclass
class Block:
    """One paragraph-level element (or a run of loose inline content)."""

    nodes: list            # the element, or the loose nodes of a run
    segment: int
    page: str              # the page's file name
    index: int = 0         # position in the page

    @property
    def element(self) -> Tag | None:
        return self.nodes[0] if len(self.nodes) == 1 and isinstance(self.nodes[0], Tag) else None

    def plain(self) -> str:
        parts = []
        for n in self.nodes:
            parts.append(n.get_text(" ") if isinstance(n, Tag) else str(n))
        return _WS_RE.sub(" ", " ".join(parts).replace("\xa0", " ")).strip()


def _has_block(tag: Tag) -> bool:
    return tag.find(_BLOCKISH) is not None


def blocks(body: Tag, page: str) -> list[Block]:
    """The page's blocks in order, each with its ``<hr>`` segment number."""
    out: list[Block] = []
    seg = 0
    run: list = []

    def flush() -> None:
        nonlocal run
        if any((isinstance(n, Tag) and n.get_text(strip=True)) or
               (isinstance(n, NavigableString) and str(n).strip()) for n in run):
            out.append(Block(run, seg, page))
        run = []

    def walk(el: Tag) -> None:
        nonlocal seg
        for child in el.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                run.append(child)
                continue
            if not isinstance(child, Tag) or child.name in _SKIP:
                continue
            if child.name == "hr":
                flush()
                seg += 1
                continue
            if child.name == "br":
                run.append(child)
                continue
            if _has_block(child):
                flush()
                walk(child)
                flush()
            elif child.name in _LEAF_BLOCKS or child.name in {"div", "blockquote", "center",
                                                              "td", "th", "table"}:
                flush()
                out.append(Block([child], seg, page))
            else:
                run.append(child)

    walk(body)
    flush()
    for i, b in enumerate(out):
        b.index = i
    return out


def segment_words(bs: list[Block]) -> dict[int, int]:
    words: dict[int, int] = {}
    for b in bs:
        words[b.segment] = words.get(b.segment, 0) + len(b.plain().split())
    return words


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------

_MARKER_TEXT_RE = re.compile(r"^[\[(]?\s*(?:\d{1,4}[a-z]?|[a-zA-Z]|[*†‡§¶]{1,3})\s*[\])]?\.?$")
# A note's own number or letter: "12.", "[3]", "(a)", "*", and LF's "1. a" (number, then
# the printed page's letter).
_NOTE_LEAD_RE = re.compile(
    r"^\s*(?:[\[(]\s*(?:\d{1,4}|[a-z]|[*†‡§¶]{1,3})\s*[\])]\.?"
    r"|\d{1,4}\.(?=\s)|[*†‡§¶]{1,3}(?=\s)"
    r"|[a-z](?=\s))"
    r"(?:\s+(?:[a-z]|[*†‡§¶])(?=\s))?\s*")


def _anchor_name(a: Tag) -> str | None:
    name = a.get("name") or a.get("id")
    if not name:
        return None
    return unquote(name).lstrip("#")


def _marker_target(a: Tag, page: str) -> tuple[str, str] | None:
    """``(page, name)`` a short footnote marker links to, else None."""
    href = a.get("href")
    if not href or "#" not in href:
        return None
    text = _WS_RE.sub(" ", a.get_text(" ").replace("\xa0", " ")).strip()
    if not text or not _MARKER_TEXT_RE.match(text):
        return None
    file, _, frag = href.partition("#")
    file = unquote(file).rsplit("/", 1)[-1] or page
    frag = unquote(frag).lstrip("#")
    return (file, frag) if frag else None


@dataclass
class Notes:
    """The note blocks of a work's pages, by ``(page, anchor name)``."""

    blocks: dict[tuple[str, str], Block] = field(default_factory=dict)
    used: set[int] = field(default_factory=set)   # id() of note blocks taken

    def add_page(self, bs: list[Block]) -> None:
        for b in bs:
            for n in b.nodes:
                if not isinstance(n, Tag):
                    continue
                anchors = [n] if n.name == "a" else []
                anchors += n.find_all("a")
                for a in anchors:
                    name = _anchor_name(a)
                    if name and _leads(b, a):
                        self.blocks.setdefault((b.page, name), b)


def _leads(b: Block, a: Tag) -> bool:
    """Whether anchor *a* starts block *b* (only a number or a symbol before it)."""
    before = []
    for n in b.nodes:
        nodes = ([n] if isinstance(n, NavigableString)
                 else n.descendants if isinstance(n, Tag) else [])
        for d in nodes:
            if d is a:
                text = "".join(before).replace("\xa0", " ").strip()
                return len(text) <= 4
            if isinstance(d, NavigableString) and not isinstance(d, Comment):
                before.append(str(d))
        if n is a:
            text = "".join(before).replace("\xa0", " ").strip()
            return len(text) <= 4
    return False


# ---------------------------------------------------------------------------
# Block → unit
# ---------------------------------------------------------------------------

_PAGE_NO_RE = re.compile(r"\s*\|\s*\d+[a-z]?\s*")
_SUP_NOTE_RE = re.compile(r"^\s*[\[(]?(?:[a-z]|\d{1,3}|[*†‡§¶]{1,3})[\])]?\s*$")


def _is_page_break(tag: Tag) -> bool:
    cls = tag.get("class") or []
    if "pb" in cls:
        return True
    if tag.name == "a" and tag.find("span", class_="pb") is not None:
        return True
    return False


class Renderer:
    """Turns blocks into units, footnotes in place."""

    def __init__(self, notes: Notes, strip: tuple[str, ...] = ()) -> None:
        self.notes = notes
        self.strip = re.compile("|".join(f"(?:{p})" for p in strip)) if strip else None
        self.missing: list[str] = []

    def note_text(self, b: Block) -> str:
        out = _Builder()
        self._render(b, out, in_note=True)
        text = out.unit().text
        return _NOTE_LEAD_RE.sub("", text, count=1).strip()

    def _render(self, b: Block, out: _Builder, in_note: bool) -> None:
        skip: set[int] = set()
        for n in b.nodes:
            nodes = [n] if not isinstance(n, Tag) else [n, *n.descendants]
            for d in nodes:
                if any(id(p) in skip for p in _parents(d, n)):
                    continue
                if isinstance(d, Comment):
                    continue
                if isinstance(d, Tag):
                    if d.name in _SKIP or _is_page_break(d):
                        skip.add(id(d))
                    elif d.name == "br":
                        out.add(" ")
                    elif d.name == "a" and (target := _marker_target(d, b.page)):
                        skip.add(id(d))
                        if in_note:
                            continue   # a back-link, or a note's own cross-reference
                        note = self.notes.blocks.get(target)
                        if note is None or (note.page == b.page and note.index <= b.index):
                            self.missing.append(f"{b.page}#{target[1]}")
                            continue
                        self.notes.used.add(id(note))
                        text = self.note_text(note)
                        if text:
                            out.add(f"[{text}]", "note")
                    elif d.name == "sup" and _SUP_NOTE_RE.match(d.get_text()):
                        skip.add(id(d))   # an unlinked note call
                    continue
                piece = str(d)
                if _PAGE_NO_RE.fullmatch(piece):
                    continue
                if self.strip is not None:
                    piece = self.strip.sub(" ", piece)
                out.add(piece)

    def unit(self, b: Block, whole: str | None = None) -> Unit:
        out = _Builder()
        self._render(b, out, in_note=False)
        return out.unit(whole)


def _parents(d, top) -> list:
    out = []
    p = d.parent if d is not top else None
    while p is not None:
        out.append(p)
        if p is top:
            break
        p = p.parent
    return out


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

_NOISE_RE = re.compile(
    r"public domain|copy freely|Early Church Fathers - Additional Texts|"
    r"rendered using (?:unicode|the)|^This text was transcribed|Previous Page|Table Of Contents|"
    r"^\[\s*Translated by [^\]]*\]$",
    re.IGNORECASE)


_PAGE_REF_RE = re.compile(
    r"(?:\[?\s*p(?:age|\.)?\s*\d+\s*[a-d]?\s*\]?|\[\s*\d+\s*(?:/\s*\d+)?\s*\])")
_HEADING_RE = re.compile(
    r"^(?:CHAPTER|CHAP\.|BOOK|LETTER|SECTION|DISCOURSE|SERMON|HOMILY|PART|ORATION|EPISTLE)"
    r"\s+[IVXLCDM\d]+\b")


def is_noise(b: Block) -> bool:
    text = b.plain()
    if not text or re.fullmatch(r"[\s|\d.]*", text) or _PAGE_REF_RE.fullmatch(text):
        return True
    return len(text) < 600 and bool(_NOISE_RE.search(text))


def heading_kind(b: Block, unit: Unit) -> str | None:
    """``heading`` or ``note`` when the whole block is editorial, else None."""
    el = b.element
    if el is None:
        return None
    if el.name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
        return "heading"
    cls = el.get("class") or []
    if "smallish" in cls or "small" in cls:
        return "note"
    fonts = [f for f in el.find_all("font") if f.get("size") in {"1", "-1", "-2"}]
    if fonts and all(_within_any(s, fonts) for s in el.find_all(string=True) if s.strip()):
        return "heading"   # a margin summary, set in small type
    text = unit.text
    if not text:
        return None
    letters = sum(c.isalpha() for c in text)
    if len(text) > 20 and letters < 0.4 * len(text):
        return "heading"   # a diagram or a table drawn in characters
    if text.startswith("[") and text.endswith("]") and text.count("[") == 1:
        return "note"   # an editor's remark on a line of its own
    if re.match(r"^[*†‡]\s", text):
        return "note"   # a footnote set after its paragraph
    if len(text) < 150 and (_HEADING_RE.match(text) or
                            (not re.search(r"[a-z]", text) and re.search(r"[A-Z]{3}", text))):
        return "heading"
    if el.get("align", "").lower() == "center" and len(text) < 300:
        return "heading"
    if len(text) < 250:
        plain_bits = [s for s in el.find_all(string=True)
                      if s.strip() and not any(p.name in {"b", "strong", "a"} for p in s.parents
                                               if p is not el and isinstance(p, Tag)
                                               and _within(p, el))]
        if not plain_bits and (el.find(["b", "strong"]) is not None):
            return "heading"
        links = el.find_all("a", href=re.compile(r"^#"))
        if links and not plain_bits:
            return "heading"
    return None


def _within(p: Tag, el: Tag) -> bool:
    while p is not None:
        if p is el:
            return True
        p = p.parent
    return False


def _within_any(s, tags: list[Tag]) -> bool:
    return any(_within(s.parent, t) for t in tags)
