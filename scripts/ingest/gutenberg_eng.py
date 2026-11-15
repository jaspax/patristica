"""
Ingestor for public-domain English translations from Project Gutenberg (#349,
wave 3 of #341).

Source: the HTML editions of Project Gutenberg, downloaded once each and cached
at ``data/raw/_cache/gutenberg-{N}/pg{N}-images.html``, so a re-ingest runs
offline. Every book is US public domain (published before 1931); Gutenberg's
trademark terms apply only to redistribution under its name, and its header,
footer and licence boilerplate are not ingested (``strip_boilerplate``).
Output: ``data/raw/gutenberg-eng/{work}.json``
Language: eng  License: public_domain

Works (one per original text; the English is attributed to the original
author, the translator is in ``edition``):

- ``procopius-wars``: Procopius, *History of the Wars* I–VI.15, tr. H. B. Dewing
  (Loeb, 1914, 1916, 1919), eBooks #16764, #16765, #20298; ``translation_of``
  ``perseus/tlg4029/tlg001/perseus-grc2`` (a partial translation: books
  VI.16–VIII are in Loeb vols 4–5, not on Gutenberg).
- ``procopius-secret-history``: the *Secret History*, anonymous translation
  "literally and completely translated from the Greek for the first time"
  (Athens [London]: privately printed for the Athenian Society, 1896), #12916;
  ``translation_of`` ``perseus/tlg4029/tlg002/perseus-grc2``.
- ``barlaam-and-ioasaph``: *Barlaam and Ioasaph*, tr. G. R. Woodward and
  H. Mattingly (Loeb, 1914), #749; ``translation_of`` the Perseus text
  ``perseus/tlg2934/tlg066/perseus-grc2`` (the Loeb Greek text itself, the
  critical edition ``patristica/anchor_rule.py`` prefers over OCR'd Migne).
- ``john-of-damascus-on-holy-images`` and ``john-of-damascus-dormition-{1,2,3}``:
  Mary H. Allies, *St John Damascene on Holy Images, followed by Three Sermons
  on the Assumption* (London: Thomas Baker, 1898), #49917. **Unlinked**:
  ``ogpg/vol-094/de-imaginibus`` also holds the works after the orations in
  PG 94 (De recta sententia, Contra Jacobitas, Contra Manichaeos, De draconibus,
  …), and the Dormition sermons are inside ``ogpg/vol-096/homiliae``; a
  container is never linked to one of its works (#341).
- ``prudentius-cathemerinon``: Prudentius, *Cathemerinon*, tr. R. Martin Pope
  (London: J. M. Dent, 1905), #14959, English verse. **Unlinked**:
  ``oglt-pl/prudentius/pl59_33_m.`` holds the Praefatio, the Cathemerinon, the
  Apotheosis and the Hamartigenia together.

Not ingested: Hodgkin's *Letters of Cassiodorus* (1886, #18590), which by its
own preface is "an abstract, not a full translation" of the *Variae*.

Editorial material (#236): the translators' introductions and prefaces are
whole-unit ``note`` units (section ``TrPref``); titles and headings the
translator added are ``title``/``heading`` units; footnote markers, the
footnotes (appended to the end of the paragraph that cites them) and the
Loeb's marginal dates are ``note`` spans. Page numbers are dropped.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from patristica.models import Work
from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

SOURCE_ID = "gutenberg-eng"

Span = tuple[int, int, str]


class GutenbergFormatError(ValueError):
    """The HTML has a structure this parser doesn't know."""


def cache_path(ebook: int) -> Path:
    return Path("_cache") / f"gutenberg-{ebook}" / f"pg{ebook}-images.html"


def download_url(ebook: int) -> str:
    return f"https://www.gutenberg.org/cache/epub/{ebook}/pg{ebook}-images.html"


def ebook_url(ebook: int) -> str:
    return f"https://www.gutenberg.org/ebooks/{ebook}"


# ---------------------------------------------------------------------------
# Boilerplate
# ---------------------------------------------------------------------------

_START_RE = re.compile(r"\*\*\*\s*START OF (THE|THIS) PROJECT GUTENBERG", re.I)
_END_RE = re.compile(r"\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG", re.I)


def strip_boilerplate(soup: BeautifulSoup) -> BeautifulSoup:
    """Remove Project Gutenberg's header, footer and licence from *soup*.

    Current Gutenberg HTML wraps them in ``#pg-header`` and ``#pg-footer``;
    anything still marked with the ``*** START/END OF THE PROJECT GUTENBERG``
    lines outside those (older files) raises, so a format change is noticed.
    """
    for sel in ("#pg-header", "#pg-footer", "section.pg-boilerplate", ".pg-boilerplate"):
        for el in soup.select(sel):
            el.decompose()
    body = soup.body or soup
    text = body.get_text(" ")
    if _START_RE.search(text) or _END_RE.search(text) or "Project Gutenberg License" in text:
        raise GutenbergFormatError("Gutenberg boilerplate outside #pg-header/#pg-footer")
    return soup


def load(html: str) -> BeautifulSoup:
    return strip_boilerplate(BeautifulSoup(html, "lxml"))


# ---------------------------------------------------------------------------
# Text with editorial spans
# ---------------------------------------------------------------------------

class TextBuilder:
    """Text pieces, each plain or of an editorial kind, joined with whitespace
    collapsed; ``build`` returns the text and its editorial spans."""

    def __init__(self) -> None:
        self.parts: list[tuple[str, str | None]] = []

    def add(self, text: str, kind: str | None = None) -> None:
        if text:
            self.parts.append((text, kind))

    def build(self) -> tuple[str, list[Span]]:
        # Each character carries its kind and the piece it came from, so two
        # adjacent pieces of one kind (a marker and the note after it) stay
        # two spans.
        chars: list[tuple[str, tuple[str | None, int]]] = []
        for pid, (text, kind) in enumerate(self.parts):
            tag = (kind, pid if kind else -1)
            chars.extend((c, tag) for c in text)
        plain_tag: tuple[str | None, int] = (None, -1)
        out: list[tuple[str, tuple[str | None, int]]] = []
        i = 0
        while i < len(chars):
            c, tag = chars[i]
            if c.isspace():
                j = i
                while j < len(chars) and chars[j][0].isspace():
                    j += 1
                prev = out[-1][1] if out else plain_tag
                nxt = chars[j][1] if j < len(chars) else plain_tag
                out.append((" ", prev if prev == nxt else plain_tag))
                i = j
            else:
                out.append((c, tag))
                i += 1
        while out and out[0][0] == " ":
            out.pop(0)
        while out and out[-1][0] == " ":
            out.pop()
        text = "".join(c for c, _ in out)
        spans: list[Span] = []
        k = 0
        while k < len(out):
            tag = out[k][1]
            j = k
            while j < len(out) and out[j][1] == tag:
                j += 1
            if tag[0] is not None:
                spans.append((k, j, tag[0]))
            k = j
        return text, spans


_BLOCK_TAGS = frozenset({"div", "p", "li", "blockquote", "td", "tr", "h2", "h3", "h4"})

NoteRef = str  # a footnote's key, resolved by the book's note lookup


@dataclass
class Inline:
    """How a book marks footnote references and marginalia inline."""

    is_anchor: Callable[[Tag], NoteRef | None] = lambda t: None
    text_marker: re.Pattern[str] | None = None   # footnote markers in plain text ("[8]")
    drop_classes: frozenset[str] = frozenset({"pagenum", "pageno", "toc-pageref"})


def render(node: Tag, inline: Inline, tb: TextBuilder, notes: list[NoteRef]) -> None:
    """Add *node*'s text to *tb*: page numbers dropped, footnote markers and the
    Loeb's marginal dates as ``note`` spans, footnote keys appended to *notes*."""
    for child in node.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            s = str(child)
            if inline.text_marker is None:
                tb.add(s)
                continue
            pos = 0
            for m in inline.text_marker.finditer(s):
                tb.add(s[pos:m.start()])
                tb.add(m.group(0), "note")
                notes.append(m.group(1))
                pos = m.end()
            tb.add(s[pos:])
            continue
        if not isinstance(child, Tag):
            continue
        classes = set(child.get("class") or [])
        if classes & inline.drop_classes or child.name in ("script", "style"):
            continue
        if child.name == "br":
            tb.add(" ")
            continue
        if child.name in _BLOCK_TAGS:
            tb.add(" ")
            render(child, inline, tb, notes)
            tb.add(" ")
            continue
        if "sidenote" in classes:
            tb.add(" [" + " ".join(child.get_text(" ").split()) + "] ", "note")
            continue
        key = inline.is_anchor(child)
        if key is not None:
            marker = " ".join(child.get_text().split())
            if not marker.startswith("["):
                marker = f"[{marker}]"
            tb.add(marker, "note")
            notes.append(key)
            continue
        render(child, inline, tb, notes)


def plain(node: Tag) -> str:
    """An element's text, whitespace collapsed, page numbers dropped."""
    tb = TextBuilder()
    render(node, Inline(), tb, [])
    return tb.build()[0]


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

@dataclass
class Book:
    """Units of one work, with refs ``{prefix}.{section}.{k}``."""

    prefix: str
    units: list[dict] = field(default_factory=list)
    _counts: dict[str, int] = field(default_factory=dict)

    def add(self, section: str, text: str, spans: list[Span]) -> None:
        if not text:
            return
        k = self._counts.get(section, 0) + 1
        self._counts[section] = k
        unit: dict = {"ref": f"{self.prefix}.{section}.{k}", "text": text}
        if spans:
            unit["editorial"] = [list(s) for s in spans]
        self.units.append(unit)

    def add_whole(self, section: str, text: str, kind: str) -> None:
        text = " ".join(text.split())
        if text:
            self.add(section, text, [(0, len(text), kind)])

    def add_element(self, section: str, el: Tag, inline: Inline,
                    notes: Callable[[NoteRef], str]) -> None:
        tb = TextBuilder()
        keys: list[NoteRef] = []
        render(el, inline, tb, keys)
        for key in keys:
            tb.add(" " + notes(key) + " ", "note")
        self.add(section, *tb.build())


_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
_ROMAN_RE = re.compile(r"^[IVXLC]+$")


def roman(s: str) -> int:
    s = s.strip().rstrip(".").strip()
    if not _ROMAN_RE.match(s):
        raise GutenbergFormatError(f"not a Roman numeral: {s!r}")
    total = 0
    for i, ch in enumerate(s):
        v = _ROMAN[ch]
        total += -v if i + 1 < len(s) and _ROMAN[s[i + 1]] > v else v
    return total


def _blocks(root: Tag, names: tuple[str, ...]) -> Iterator[Tag]:
    """Block elements in document order, not nested in one another."""
    for el in root.find_all(names):
        if el.find_parent(names) is None:
            yield el


def _in(el: Tag, cls: str) -> bool:
    return any(cls in (p.get("class") or []) for p in [el, *el.parents] if isinstance(p, Tag))


# ---------------------------------------------------------------------------
# Procopius, History of the Wars (Dewing)
# ---------------------------------------------------------------------------

def _fn_anchor(tag: Tag) -> NoteRef | None:
    if tag.name == "a" and "fnanchor" in (tag.get("class") or []):
        href = tag.get("href", "")
        if href.startswith("#"):
            return href[1:]
    return None


_FOOTNOTE_ID = re.compile(r"^Footnote_")


def _note_continuation(p: Tag) -> list[Tag]:
    """The paragraphs after a footnote's label paragraph that continue it."""
    out = []
    for sib in p.find_next_siblings():
        if sib.name != "p" or sib.find("a", id=_FOOTNOTE_ID):
            break
        out.append(sib)
    return out


def _note_paragraphs(soup: BeautifulSoup) -> set[int]:
    """``id()`` of every paragraph that belongs to a footnote (label paragraph
    and continuation), so the text loop skips them wherever they stand."""
    found: set[int] = set()
    for a in soup.find_all("a", id=_FOOTNOTE_ID):
        p = a.find_parent("p")
        if p is not None:
            found.add(id(p))
            found.update(id(s) for s in _note_continuation(p))
    return found


def _loeb_notes(soup: BeautifulSoup) -> Callable[[NoteRef], str]:
    """Footnote text by anchor id. Notes are either a ``div.footnote`` or a
    paragraph holding only the label, followed by the paragraphs of the note."""
    cache: dict[str, str] = {}

    def lookup(key: NoteRef) -> str:
        if key in cache:
            return cache[key]
        target = soup.find(id=key)
        if target is None:
            raise GutenbergFormatError(f"footnote {key} not found")
        label = " ".join(target.find_next("a").get_text().split()) if target.find_next("a") else ""
        div = target.find_parent("div", class_="footnote")
        if div is not None:
            body = BeautifulSoup(str(div), "lxml")
            for a in body.find_all("a", href=True):
                if a.get("href", "").startswith("#FNanchor"):
                    a.decompose()
            text = plain(body)
        else:
            p = target.find_parent("p")
            if p is None:
                raise GutenbergFormatError(f"footnote {key}: no paragraph")
            parts = []
            own = BeautifulSoup(str(p), "lxml")
            for a in own.find_all("a"):
                if a.get("id", "").startswith("Footnote_") or a.get("href", "").startswith("#FNanchor"):
                    a.decompose()
            if plain(own):
                parts.append(plain(own))
            for sib in _note_continuation(p):
                parts.append(plain(sib))
            text = " ".join(parts)
        if not text:
            raise GutenbergFormatError(f"footnote {key} is empty")
        cache[key] = f"{label} {text}".strip()
        return cache[key]

    return lookup


LOEB_INLINE = Inline(is_anchor=_fn_anchor)

_BOOK_ID_RE = re.compile(r"^BOOK_([IVX]+)$")
_WARS_BOOK_RE = re.compile(r"BOOK\s+([IVX]+)\s*$")


def parse_wars_volume(soup: BeautifulSoup, book: Book, *, intro: bool = False) -> None:
    """Add one Gutenberg volume of Dewing's *Wars* to *book*.

    Volumes 1–2 (#16764, #16765) mark books with ``<a id="BOOK_N">``, chapters
    with a paragraph holding only a Roman numeral, and close each book with a
    "FOOTNOTES:" paragraph; volume 3 (#20298) marks books with an ``h2``
    "BOOK N" and chapters with ``h2`` numerals, its footnotes in
    ``div.footnotes`` after each chapter, and ends at the index.
    """
    notes = _loeb_notes(soup)
    note_paras = _note_paragraphs(soup)
    bookno: int | None = None
    chapter: int | None = None
    mode = "skip"  # "intro", "text" or "skip"
    for el in _blocks(soup.body, ("p", "h2", "h3", "h4")):
        if (_in(el, "footnotes") or _in(el, "footnote") or _in(el, "tnote")
                or el.find_parent(["ul", "table"]) is not None or id(el) in note_paras):
            continue
        txt = plain(el)
        up = txt.upper().rstrip(":").strip()
        if el.name != "p":
            anchor = el.find("a", id=_BOOK_ID_RE)
            m = _WARS_BOOK_RE.search(up)
            if anchor is not None or m is not None:
                bookno = roman(_BOOK_ID_RE.match(anchor["id"]).group(1) if anchor else m.group(1))
                chapter, mode = None, "text"
            elif el.find("a", id="INTRODUCTION") is not None:
                mode = "intro" if intro else "skip"
            elif up.startswith(("FOOTNOTE", "INDEX", "BIBLIOGRAPHY", "CONTENTS")):
                mode = "skip"
            elif mode == "text" and _ROMAN_RE.match(up.rstrip(".")):
                chapter = roman(up)
            continue
        if up in ("FOOTNOTES", "FOOTNOTE"):
            mode = "skip"
            continue
        if not txt or mode == "skip":
            continue
        if mode == "intro":
            book.add_whole("TrPref", plain_with_notes(el, notes), "note")
            continue
        if _ROMAN_RE.match(up.rstrip(".")):
            chapter = roman(up)
            continue
        if el.find("a", id=_FOOTNOTE_ID) is not None:
            raise GutenbergFormatError(f"Book {bookno}: footnote in the text: {txt[:60]!r}")
        if chapter is None:
            raise GutenbergFormatError(f"Book {bookno}: text before the first chapter: {txt[:60]!r}")
        book.add_element(f"{bookno}.{chapter}", el, LOEB_INLINE, notes)


def plain_with_notes(el: Tag, notes: Callable[[NoteRef], str]) -> str:
    tb = TextBuilder()
    keys: list[NoteRef] = []
    render(el, LOEB_INLINE, tb, keys)
    text = tb.build()[0]
    return " ".join([text, *(notes(k) for k in keys)])


# ---------------------------------------------------------------------------
# Procopius, Secret History (Athenian Society, 1896)
# ---------------------------------------------------------------------------

_SH_MARKER = re.compile(r"\[(\d+)\]")
_SH_MACRON = re.compile(r"\[=([A-Za-z])\]")


def secret_history_macrons(html: str) -> str:
    """The transcription writes a macron as ``[=e]``; restore ``ē``."""
    return _SH_MACRON.sub(lambda m: unicodedata.normalize("NFC", m.group(1) + "\u0304"), html)
_SH_NOTE = re.compile(r"^\[(\d+):\s*(.*)\]$", re.S)


def parse_secret_history(soup: BeautifulSoup) -> Book:
    """The translator's preface (``TrPref``), each chapter's argument from the
    contents as a ``heading`` unit, Procopius's introduction (``Intro``) and
    chapters 1–30; numbered notes ``[N: …]`` at the end are appended to the
    paragraph citing them."""
    body = soup.body
    notes_h = body.find("h4", string=re.compile(r"^\s*NOTES\s*$"))
    if notes_h is None:
        raise GutenbergFormatError("Secret History: no NOTES section")
    note_text: dict[str, str] = {}
    for p in notes_h.find_all_next("p"):
        m = _SH_NOTE.match(plain(p))
        if not m:
            raise GutenbergFormatError(f"Secret History: unexpected note {plain(p)[:60]!r}")
        note_text[m.group(1)] = f"[{m.group(1)}] {m.group(2)}"

    def notes(key: NoteRef) -> str:
        if key not in note_text:
            raise GutenbergFormatError(f"Secret History: note {key} missing")
        return note_text[key]

    inline = Inline(text_marker=_SH_MARKER)
    book = Book("ProcAnec")
    arguments: dict[str, str] = {}
    mode = "start"
    section = ""
    for el in _blocks(body, ("p", "h2", "h3", "h4", "h5")):
        if el is notes_h:
            break
        txt = plain(el)
        if el.name in ("h2", "h3"):
            up = txt.upper()
            if up == "PREFACE":
                mode, section = "preface", "TrPref"
            elif up == "CONTENTS":
                mode = "contents"
            elif up == "INTRODUCTION" or up.startswith("CHAPTER "):
                section = "Intro" if up == "INTRODUCTION" else str(roman(up.split()[1]))
                if section in arguments:  # the second time: the text itself
                    mode = "text"
                    book.add_whole(section, arguments.pop(section), "heading")
            else:
                raise GutenbergFormatError(f"Secret History: unexpected heading {txt!r}")
            continue
        if el.name != "p" or not txt:
            continue
        if mode == "preface":
            tb = TextBuilder()
            keys: list[NoteRef] = []
            render(el, inline, tb, keys)
            text = " ".join([tb.build()[0], *(notes(k) for k in keys)])
            book.add_whole("TrPref", text, "note")
        elif mode == "contents":
            if section in arguments:
                arguments[section] += " " + txt
            else:
                arguments[section] = txt
        elif mode == "text":
            book.add_element(section, el, inline, notes)
    if arguments:
        raise GutenbergFormatError(f"Secret History: arguments without a chapter: {sorted(arguments)}")
    return book


# ---------------------------------------------------------------------------
# Barlaam and Ioasaph (Woodward & Mattingly)
# ---------------------------------------------------------------------------

def parse_barlaam(soup: BeautifulSoup) -> Book:
    """The title (``p.intro``) and the author's prologue (``Praef``), then the
    forty chapters. Killings's 1996 preparer's note and bibliography, before
    the title, are not part of the book and are left out."""
    body = soup.body
    heads = body.find_all("h1", string=re.compile(r"BARLAAM AND IOASAPH"))
    if len(heads) != 1:
        raise GutenbergFormatError(f"Barlaam: expected 1 title heading, found {len(heads)}")
    title_h = heads[0]
    book = Book("BarlIoas")
    section = "Praef"
    started = False
    for el in title_h.find_all_next(["p", "h2", "h3"]):
        if el.find_parent("table") is not None:
            continue
        txt = plain(el)
        if el.name == "p" and "intro" in (el.get("class") or []):
            book.add_whole("Praef", txt, "title")
            continue
        if el.name in ("h2", "h3"):
            if txt.upper() == "INTRODUCTION":
                section, started = "Praef", True
            elif txt.upper() == "CONTENTS":
                started = False
            else:
                section, started = str(roman(txt)), True
            continue
        if started and txt:
            book.add_element(section, el, Inline(), _no_notes)
    return book


def _no_notes(key: NoteRef) -> str:
    raise GutenbergFormatError(f"unexpected footnote {key}")


# ---------------------------------------------------------------------------
# John of Damascus, On Holy Images, and three sermons on the Dormition (Allies)
# ---------------------------------------------------------------------------

def _docutils_anchor(tag: Tag) -> NoteRef | None:
    if tag.name == "a" and "footnote-reference" in (tag.get("class") or []):
        return tag.get("href", "")[1:]
    return None


def _docutils_notes(soup: BeautifulSoup) -> Callable[[NoteRef], str]:
    def lookup(key: NoteRef) -> str:
        table = soup.find("table", id=key)
        if table is None:
            raise GutenbergFormatError(f"footnote {key} not found")
        cells = table.find_all("td")
        label = " ".join(cells[0].get_text().split())
        text = " ".join(plain(c) for c in cells[1:])
        return f"{label} {text}".strip()
    return lookup


ALLIES_SECTIONS = {
    "part-i-nl-apologia-of-st-john-damascene-against-those-who-decry-holy-images": ("images", "1"),
    "part-ii": ("images", "2"),
    "part-iii-20": ("images", "3"),
    "sermon-i-nl-on-the-assumption": ("dormition-1", "1"),
    "sermon-ii-nl-on-the-assumption": ("dormition-2", "1"),
    "sermon-iii-nl-on-the-assumption": ("dormition-3", "1"),
}


def parse_allies(soup: BeautifulSoup) -> dict[str, Book]:
    """The three parts (orations) of *On Holy Images* as one work, with Allies's
    preface (``TrPref``), and each Dormition sermon as a work of its own."""
    notes = _docutils_notes(soup)
    inline = Inline(is_anchor=_docutils_anchor)
    books = {
        "images": Book("JDImag"),
        "dormition-1": Book("JDDorm1"),
        "dormition-2": Book("JDDorm2"),
        "dormition-3": Book("JDDorm3"),
    }
    pref = soup.find("div", id="translators-preface")
    if pref is None:
        raise GutenbergFormatError("Allies: no translator's preface")
    for p in pref.find_all("p"):
        tb = TextBuilder()
        keys: list[NoteRef] = []
        render(p, inline, tb, keys)
        books["images"].add_whole("TrPref", " ".join([tb.build()[0], *(notes(k) for k in keys)]), "note")
    for sec_id, (key, section) in ALLIES_SECTIONS.items():
        div = soup.find("div", id=sec_id)
        if div is None:
            raise GutenbergFormatError(f"Allies: section {sec_id} missing")
        book = books[key]
        for el in _blocks(div, ("p", "h2", "h3", "h4", "blockquote")):
            if el.find_parent("table") is not None:
                continue
            if el.name in ("h2", "h3", "h4"):
                tb = TextBuilder()
                keys = []
                render(el, inline, tb, keys)
                text, _ = tb.build()
                kind = "title" if el.name == "h2" else "heading"
                for k in keys:
                    text += " " + notes(k)
                book.add_whole(section, text, kind)
                continue
            book.add_element(section, el, inline, notes)
    return books


# ---------------------------------------------------------------------------
# Prudentius, Cathemerinon (Pope)
# ---------------------------------------------------------------------------

def parse_cathemerinon(soup: BeautifulSoup) -> Book:
    """Pope's English (the ``p{NN}t`` poems; the facing Latin ``p{NN}o`` is
    left out): one unit per stanza, lines joined with spaces, each poem's
    title a ``title`` unit. Sections ``Praef``, ``1``–``12``, ``Epil``. The
    translator's note is ``TrPref``; Pope's endnotes comment on the Latin
    lines and are left out."""
    book = Book("PrudCath")
    note_h = soup.find("a", id="trn")
    if note_h is None:
        raise GutenbergFormatError("Cathemerinon: no translator's note")
    for el in note_h.find_parent("h3").find_all_next(["p", "h1", "h2", "h3"]):
        if el.name != "p":
            break
        book.add_whole("TrPref", plain(el), "note")
    for n in range(0, 14):
        a = soup.find("a", id=f"p{n:02d}t")
        if a is None:
            raise GutenbergFormatError(f"Cathemerinon: poem p{n:02d}t missing")
        section = {0: "Praef", 13: "Epil"}.get(n, str(n))
        h3 = a.find_parent("h3")
        book.add_whole(section, plain(h3), "title")
        table = h3.find_next_sibling("table")
        if table is None or "poem" not in (table.get("class") or []):
            raise GutenbergFormatError(f"Cathemerinon: no poem table after {plain(h3)!r}")
        stanza: list[str] = []
        for p in table.find_all("p"):
            line = plain(p)
            if line:
                stanza.append(line)
            elif stanza:
                book.add(section, " ".join(stanza), [])
                stanza = []
        if stanza:
            book.add(section, " ".join(stanza), [])
    return book


# ---------------------------------------------------------------------------
# Works
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Meta:
    local_id: str
    title: str
    author: str
    ebooks: tuple[int, ...]
    edition: str
    translation_of: str | None
    tradition: str
    genre: str
    date_composed: int | None
    date_range: tuple[int, int] | None
    date_confidence: str


DEWING = ("tr. H. B. Dewing, Procopius, History of the Wars, Loeb Classical Library, "
          "vols. 1–3 (London: Heinemann; New York: Macmillan, 1914, 1916, 1919): "
          "Books I–VI.15 only; Project Gutenberg eBooks #16764, #16765, #20298")
ALLIES = ("tr. Mary H. Allies, St John Damascene on Holy Images, followed by Three Sermons "
          "on the Assumption (London: Thomas Baker, 1898); Project Gutenberg eBook #49917")

METAS: dict[str, Meta] = {
    "wars": Meta(
        "procopius-wars", "History of the Wars, Books I–VI.15", "Procopius of Caesarea",
        (16764, 16765, 20298), DEWING, "perseus/tlg4029/tlg001/perseus-grc2",
        "greek", "patristic", 551, (545, 554), "approximate"),
    "secret-history": Meta(
        "procopius-secret-history", "The Secret History", "Procopius of Caesarea", (12916,),
        "anonymous translation, The Secret History of the Court of Justinian, "
        "'literally and completely translated from the Greek for the first time' "
        "(Athens: privately printed for the Athenian Society, 1896); "
        "Project Gutenberg eBook #12916",
        "perseus/tlg4029/tlg002/perseus-grc2", "greek", "patristic", 550, (550, 558),
        "approximate"),
    "barlaam": Meta(
        "barlaam-and-ioasaph", "Barlaam and Ioasaph", "Euthymius the Athonite", (749,),
        "tr. G. R. Woodward and H. Mattingly, St. John Damascene: Barlaam and Ioasaph, "
        "Loeb Classical Library (London: Heinemann; New York: Macmillan, 1914), printed "
        "as John of Damascus's; Project Gutenberg eBook #749",
        "perseus/tlg2934/tlg066/perseus-grc2", "greek", "patristic", 1000, (980, 1028),
        "uncertain"),
    "images": Meta(
        "john-of-damascus-on-holy-images", "On Holy Images (Three Apologies against "
        "Those Who Decry Holy Images)", "John of Damascus", (49917,), ALLIES, None,
        "greek", "patristic", 730, (726, 741), "approximate"),
    "dormition-1": Meta(
        "john-of-damascus-dormition-1", "Sermon I on the Assumption (Dormition)",
        "John of Damascus", (49917,), ALLIES, None, "greek", "patristic", None, (730, 749),
        "uncertain"),
    "dormition-2": Meta(
        "john-of-damascus-dormition-2", "Sermon II on the Assumption (Dormition)",
        "John of Damascus", (49917,), ALLIES, None, "greek", "patristic", None, (730, 749),
        "uncertain"),
    "dormition-3": Meta(
        "john-of-damascus-dormition-3", "Sermon III on the Assumption (Dormition)",
        "John of Damascus", (49917,), ALLIES, None, "greek", "patristic", None, (730, 749),
        "uncertain"),
    "cathemerinon": Meta(
        "prudentius-cathemerinon", "Cathemerinon (Hymns for the Christian's Day)",
        "Prudentius", (14959,),
        "tr. R. Martin Pope, The Hymns of Prudentius (London: J. M. Dent, 1905), English "
        "verse; Project Gutenberg eBook #14959",
        None, "latin", "patristic", 405, (400, 405), "approximate"),
}


def make_work(meta: Meta) -> Work:
    return Work(
        work_id=f"{SOURCE_ID}/{meta.local_id}",
        source_id=SOURCE_ID,
        author=meta.author,
        title=meta.title,
        date_composed=meta.date_composed,
        date_range=meta.date_range,
        date_confidence=meta.date_confidence,
        genre=meta.genre,
        language="eng",
        tradition=meta.tradition,
        license="public_domain",
        provenance_url=ebook_url(meta.ebooks[0]),
        edition=meta.edition,
        translation_of=meta.translation_of,
    )


EBOOKS = (16764, 16765, 20298, 12916, 749, 49917, 14959)


def parse_all(read: Callable[[int], str]) -> dict[str, Book]:
    """Every work's units, from the HTML of each eBook (``read(N)``)."""
    books: dict[str, Book] = {}
    wars = Book("ProcWars")
    parse_wars_volume(load(read(16764)), wars, intro=True)
    parse_wars_volume(load(read(16765)), wars)
    parse_wars_volume(load(read(20298)), wars)
    books["wars"] = wars
    books["secret-history"] = parse_secret_history(load(secret_history_macrons(read(12916))))
    books["barlaam"] = parse_barlaam(load(read(749)))
    books.update(parse_allies(load(read(49917))))
    books["cathemerinon"] = parse_cathemerinon(load(read(14959)))
    for key, book in books.items():
        refs = [u["ref"] for u in book.units]
        if len(set(refs)) != len(refs):
            raise GutenbergFormatError(f"{key}: duplicate refs")
        if not book.units:
            raise GutenbergFormatError(f"{key}: no units")
    return books


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    out_dir = output_dir / SOURCE_ID
    out_dir.mkdir(parents=True, exist_ok=True)

    def read(ebook: int) -> str:
        path = download_file(download_url(ebook), output_dir / cache_path(ebook), force=force)
        return path.read_text(encoding="utf-8")

    books = parse_all(read)
    works: list[Work] = []
    for key, meta in METAS.items():
        work = make_work(meta)
        works.append(work)
        out_path = out_dir / f"{meta.local_id}.json"
        if out_path.exists() and not force:
            continue
        out_path.write_text(
            json.dumps({"work": work.model_dump(), "paragraphs": books[key].units},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.debug("%s: %d units", work.work_id, len(books[key].units))
    log.info("%s: %d works, %d units", SOURCE_ID, len(works),
             sum(len(b.units) for b in books.values()))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
