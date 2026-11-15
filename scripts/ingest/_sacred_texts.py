"""
Shared page parser for the Internet Sacred Text Archive (sacred-texts.com, #353).

The archive's static pages (``archive.sacred-texts.com``, John Bruno Hare's
transcriptions; the main site now renders the same texts with scripts) are one
HTML file per chapter or section: an ``<h3>`` heading, the text in ``<p>``s
cut by print page markers (``p. 47``), and the page's footnotes after a
``<H3>Footnotes</H3>``, referenced from the text as ``#fn_N``.  ``charles_eng``
and ``sacred_texts_eng`` read the same cache (``data/raw/_cache/sacred-texts/``).

``page_text`` turns a page into text with sentinels for what is editorial:
footnote references (``\\x05F{n}\\x06``) and marginal notes (``\\x05M{text}\\x06``,
Charles's Anno Mundi dates in a floating table).  ``Builder`` turns sentinels
into bracketed text marked ``note`` (#236).  Page markers and the archive's
"[paragraph continues]" are layout and are dropped.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

BASE_URL = "https://archive.sacred-texts.com/"
CACHE_DIR = Path("_cache") / "sacred-texts"

OPEN, CLOSE = "\x05", "\x06"
_SENTINEL_RE = re.compile(OPEN + r"([FM])(.*?)" + CLOSE, re.S)
_WS_RE = re.compile(r"\s+")


class SacredTextsParseError(RuntimeError):
    pass


def fetch(path: str, output_dir: Path, force: bool = False) -> Path:
    """A cached archive page (``bib/jub/jub15.htm``)."""
    return download_file(BASE_URL + path, output_dir / CACHE_DIR / path, force=force)


def _unescape(text: str) -> str:
    text = html.unescape(text)
    # The pages are windows-1252 with entities such as &#146; for ’.
    return re.sub("[\x80-\x9f]", lambda m: m.group(0).encode("latin-1").decode("cp1252", "replace"),
                  text).replace("\xa0", " ")


_PAGE_MARK_RE = re.compile(r'(?is)<a name="page_[^"]*">.*?</a>')
_CONTINUES_RE = re.compile(r"(?is)<font[^>]*>\s*\[paragraph continues\]\s*</font>")
_FNREF_RE = re.compile(r'(?is)<a name="fr_\d+">\s*</a>\s*<a href="[^"#]*#fn_(\d+)">(.*?)</a>')
_TABLE_RE = re.compile(r"(?is)<table\b.*?</table>")
_TAG_RE = re.compile(r"<[^>]+>")


def _plain(fragment: str) -> str:
    return _WS_RE.sub(" ", _unescape(_TAG_RE.sub(" ", fragment))).strip()


@dataclass
class Page:
    heading: str                       # the first heading's text
    items: list[tuple[str, str]]       # ("H", heading) | ("P", paragraph) | ("N", small-print note block)
    notes: dict[str, str]              # footnote id → text

    @property
    def text(self) -> str:
        """The paragraphs joined, line breaks as spaces (headings and notes left out)."""
        return " ".join(t.replace("\n", " ") for k, t in self.items if k == "P")


_HEADING_RE = re.compile(r"(?is)<h([1-3])\b[^>]*>(.*?)</h\1>")
_BRACE_PAGE_RE = re.compile(r"\{p\. [^}]*\}")


def _paragraph(fragment: str) -> str:
    """A paragraph's text with sentinels; ``<br>`` is a line break."""
    fragment = re.sub(r"(?i)<br\s*/?>", "\n", fragment)
    text = _unescape(_TAG_RE.sub("", fragment))
    text = _BRACE_PAGE_RE.sub(" ", text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r" *\n[ \n]*", "\n", text).strip()


_CELL_RE = re.compile(r"(?is)<td\b[^>]*>(.*?)</td>")
_LABEL_RE = re.compile(r"(?is)^\s*(?:<b>\s*)?<p[^>]*>(.*?)</p>")


def _table(m: re.Match) -> str:
    """A table in the text: a marginal note (one cell), or Charles's parallel
    columns of 1 Enoch, the Ethiopic (``E``) and a Greek version (``Gg``, ``Gs``),
    row by row: the Ethiopic column is the text, the Greek one a note after it."""
    rows = [_CELL_RE.findall(r) for r in re.findall(r"(?is)<tr\b.*?</tr>", m.group(0))]
    first = rows[0] if rows else []
    labels = [_plain(lm.group(1)) if (lm := _LABEL_RE.match(c)) else "" for c in first]
    if len(first) == 2 and labels[0] == "E" and labels[1].replace(" ", "").startswith("G"):
        out = []
        label = labels[1].replace(" ", "")
        for cells in rows:
            if len(cells) != 2:
                raise SacredTextsParseError("a parallel E/G table row without two cells")
            eth, greek = cells
            if (lm := _LABEL_RE.match(eth)) and _plain(lm.group(1)) == "E":
                eth = _LABEL_RE.sub("", eth, count=1)
            if (lm := _LABEL_RE.match(greek)) and _plain(lm.group(1)).replace(" ", "").startswith("G"):
                label = _plain(lm.group(1)).replace(" ", "")
                greek = _LABEL_RE.sub("", greek, count=1)
            out.append(f" <p>{eth}</p> ")
            greek_text = _plain(_PAGE_MARK_RE.sub(" ", greek))
            if greek_text:
                out.append(f" <p>{OPEN}M{label}: {greek_text}{CLOSE}</p> ")
        return "".join(out)
    cells = [c for row in rows for c in row]
    if len(cells) >= 2 and any(re.match(r"\d+\.", _plain(c)) for c in cells):
        # Columns of text side by side (Enoch 90.13-18, two doublets): each
        # cell is text, row by row, left to right.
        return "".join(f" <p>{c}</p> " for c in cells)
    return f" {OPEN}M{_plain(m.group(0))}{CLOSE} "


def page_text(src: str) -> Page:
    """The page's headings, paragraphs and footnotes, in order."""
    first = _HEADING_RE.search(src)
    if not first:
        raise SacredTextsParseError("no heading")
    start = first.start()
    # A centred line just before the first heading belongs to it (Enoch's
    # "XCI. 12-17. The Last Three Weeks." above "CHAPTER XCI.").
    while True:
        before = re.search(r'(?is)<p align="?center"?>((?:(?!</?p\b|<a href|<img).)*)</p>\s*$', src[:start])
        if not before or not _plain(before.group(1)):
            break
        start = before.start()
    rest = src[start:]
    foot = re.search(r"(?is)<h3[^>]*>\s*Footnotes\s*</h3>", rest)
    body = rest[:foot.start()] if foot else rest
    notes: dict[str, str] = {}
    if foot:
        for n_id, note in re.findall(r'(?is)<a name="fn_(\d+)">\s*</a>\s*<a href="[^"]*">.*?</a>(.*?)</p>',
                                     rest[foot.end():]):
            notes[n_id] = _plain(_PAGE_MARK_RE.sub(" ", note))
    nav = re.search(r'(?is)<div class="filenav">|<nav\b', body)
    if nav:
        body = body[:nav.start()]
    body = _PAGE_MARK_RE.sub(" ", body)
    body = _CONTINUES_RE.sub(" ", body)
    body = _FNREF_RE.sub(lambda m: f"{OPEN}F{m.group(1)}|{_plain(m.group(2))}{CLOSE}", body)
    body = _TABLE_RE.sub(_table, body)
    # Small print (Terry's notes) is a block of its own.
    body = re.sub(r"(?is)<font size=\"?2\"?>(.*?)</font>",
                  lambda m: "\x07" + re.sub(r"(?is)</?p\b[^>]*>", "\n\n", m.group(1)) + "\x08", body)
    items: list[tuple[str, str]] = []
    pos = 0
    for m in list(_HEADING_RE.finditer(body)) + [None]:
        chunk = body[pos:m.start() if m else len(body)]
        for small, para in re.findall(r"(?s)\x07(.*?)\x08|((?:(?!\x07).)+)", chunk):
            if small:
                text = _plain(small.replace("\n\n", " "))
                if text:
                    items.append(("N", text))
                continue
            for frag in re.split(r"(?is)<p\b[^>]*>|</p>|<dir>|</dir>|<blockquote>|</blockquote>", para):
                text = _paragraph(frag)
                # The archive's own "Next: Book II." link is navigation.
                text = "\n".join(ln for ln in text.split("\n") if not ln.startswith("Next:")).strip()
                if text:
                    items.append(("P", text))
        if m:
            items.append(("H", _plain(m.group(2))))
            pos = m.end()
    return Page(_plain(first.group(2)), items, notes)


def mask(text: str) -> str:
    """*text* with the inside of every sentinel blanked, so a number in a note
    or a marginal date never looks like a verse number."""
    return _SENTINEL_RE.sub(lambda m: OPEN + "x" * (len(m.group(0)) - 2) + CLOSE, text)


@dataclass
class Builder:
    """Text with editorial spans; sentinels become bracketed notes."""

    text: str = ""
    spans: list[list] = field(default_factory=list)

    def add(self, piece: str, kind: str | None = None) -> None:
        piece = _WS_RE.sub(" ", piece)
        if not piece.strip():
            if self.text and not self.text.endswith(" "):
                self.text += " "
            return
        if not self.text or self.text.endswith(" "):
            piece = piece.lstrip()
        if kind is None:
            self.text += piece
            return
        piece = piece.strip()
        if self.text and not self.text.endswith(" "):
            self.text += " "
        self.spans.append([len(self.text), len(self.text) + len(piece), kind])
        self.text += piece

    def add_marked(self, text: str, notes: dict[str, str]) -> None:
        """Text with sentinels: footnotes and marginal notes as ``note`` spans."""
        pos = 0
        for m in _SENTINEL_RE.finditer(text):
            self.add(text[pos:m.start()])
            if m.group(1) == "F":
                note = notes.get(m.group(2).split("|")[0], "")
                if not note:
                    # The transcription dropped some pages' footnotes (Jubilees 50).
                    log.warning("footnote %s has no text on its page: marker dropped", m.group(2))
            else:
                note = m.group(2)
            if note:
                self.add(f"[{note}]", "note")
            pos = m.end()
        self.add(text[pos:])

    def record(self, ref: str) -> dict:
        text = self.text.rstrip()
        lead = len(text) - len(text.lstrip())
        text = text.strip()
        spans = [[s - lead, min(e - lead, len(text)), k] for s, e, k in self.spans]
        rec: dict = {"ref": ref, "text": text}
        spans = [sp for sp in spans if sp[0] < sp[1]]
        if spans:
            rec["editorial"] = spans
        return rec


def unit(ref: str, text: str, notes: dict[str, str], heading: str | None = None) -> dict:
    """One unit: an optional section heading (``heading`` span) and the text."""
    b = Builder()
    if heading:
        b.add(heading, "heading")
        b.add(" ")
    b.add_marked(text, notes)
    return b.record(ref)


_ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}


def roman(s: str) -> int:
    s = s.upper()
    total = 0
    for a, b in zip(s, s[1:] + " "):
        v = _ROMAN_VALUES[a]
        total += -v if _ROMAN_VALUES.get(b, 0) > v else v
    return total
