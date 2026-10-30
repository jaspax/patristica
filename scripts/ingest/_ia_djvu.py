"""
Page layout of archive.org OCR (``{item}_djvu.xml``) for bilingual editions
whose pages print an oriental text above its English translation (#481).

archive.org's ``_djvu.xml`` is the item's OCR as DjVu hidden text: one
``OBJECT`` per scanned leaf, ``LINE``\\ s of ``WORD``\\ s, each word with its
box (``coords="x0,y_bottom,x1,y_top"``).  A *Patrologia Orientalis* page of
Evetts's *History of the Patriarchs* reads, top to bottom:

1. the running head (page number, title, fascicle page in brackets);
2. the Arabic text, which the Latin-script OCR turned into letter noise;
3. the apparatus of the Arabic (small type, sigla and noise);
4. the English translation, with its chapter and patriarch headings;
5. the English footnotes (small type), numbered per page.

Marginal notes (the manuscript's page numbers, ``* P. 45``) stand outside the
text column.  :func:`page_layout` splits one leaf into those parts from the
line boxes and the share of common English words in each line; nothing in a
line's text is corrected.

This module imports nothing from ``patristica``, so that editing it touches
only the ingestors that use it.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from lxml import etree

#: Frequent English function words: a line of English prose has many of them,
#: OCR noise of an Arabic line (read as French or Latin letters) almost none.
COMMON_WORDS = frozenset(
    "the and of to in he his was that him for with which they them a from by "
    "is it as not this were their had who be on at but all said when have her "
    "there into an one so we our you i me my me thou thee thy upon these those "
    "after before then until also are or no if what because shall will whose "
    "than more such other some its been would should could did came went made "
    "over out about any every only very even".split()
)
_TOKEN_RE = re.compile(r"[A-Za-z]+")


@dataclass
class Line:
    """One OCR line: its text and box (y grows downwards)."""
    text: str
    x0: int
    x1: int
    top: int
    bottom: int
    height: float   # median word height

    @property
    def tokens(self) -> list[str]:
        return _TOKEN_RE.findall(self.text)

    @property
    def english_hits(self) -> int:
        """How many of the line's words of three letters or more are common
        English words (shorter ones are too frequent in OCR noise)."""
        return sum(len(t) >= 3 and t.lower() in COMMON_WORDS for t in self.tokens)

    @property
    def english(self) -> float:
        """Share of the line's words of three letters or more that are common
        English words."""
        long = [t for t in self.tokens if len(t) >= 3]
        return self.english_hits / len(long) if long else 0.0


@dataclass
class Leaf:
    """One scanned leaf: its index in the item and its lines, top to bottom."""
    index: int
    width: int
    height: int
    lines: list[Line] = field(default_factory=list)


def read_leaves(path: Path) -> Iterator[Leaf]:
    """Every leaf of a ``_djvu.xml`` file, in order."""
    index = 0
    for _, obj in etree.iterparse(str(path), tag="OBJECT", huge_tree=True):
        leaf = Leaf(index, int(obj.get("width")), int(obj.get("height")))
        for ln in obj.iter("LINE"):
            words = []
            for w in ln.iter("WORD"):
                text = (w.text or "").strip()
                if not text:
                    continue
                x0, y1, x1, y0 = (int(v) for v in w.get("coords").split(",")[:4])
                words.append((x0, y0, x1, y1, text))
            if not words:
                continue
            leaf.lines.append(Line(
                text=" ".join(w[4] for w in words),
                x0=min(w[0] for w in words),
                x1=max(w[2] for w in words),
                top=min(w[1] for w in words),
                bottom=max(w[3] for w in words),
                height=statistics.median(w[3] - w[1] for w in words),
            ))
        leaf.lines.sort(key=lambda ln: (ln.top, ln.x0))
        yield leaf
        index += 1
        obj.clear()
        while obj.getprevious() is not None:
            del obj.getparent()[0]


def body_type(line: Line, body: float) -> bool:
    """Whether *line* is set in the English body type (*body*: its line height)."""
    return 0.92 * body <= line.height <= 1.25 * body


#: Marks of an apparatus or footnote line: "— 3. ", "om. ", "add. ", "Mss.".
_APPARATUS_RE = re.compile(r"[—-]\s*\d{1,2}\s*[.,]\s|\bom\.|\badd\.|\bMss?\.")


def is_prose(line: Line, body: float) -> bool:
    """A full line of English running text in body type."""
    return (body_type(line, body) and line.english_hits >= 2 and line.english >= 0.2
            and not _APPARATUS_RE.search(line.text))


def is_prose_end(line: Line, body: float) -> bool:
    """A short line of English (a paragraph's last words; the OCR's box of a
    short line is often lower than the body type's)."""
    return (0.6 * body <= line.height <= 1.2 * body and line.english_hits >= 1
            and len(line.tokens) <= 6 and not _APPARATUS_RE.search(line.text))


@dataclass
class Layout:
    """The parts of one leaf (see the module doc)."""
    head: Line | None
    english: list[Line]
    notes: list[Line]
    dropped: list[Line]      # Arabic text, apparatus, marginal notes, debris
    left: float = 0.0        # left edge of the text column


_FOOTNOTE_START_RE = re.compile(r"^\W{0,2}(?:\d{1,2}|[lI])\s?[.,]\s")


def page_layout(leaf: Leaf, body: float, spacing: float) -> Layout:
    """Split *leaf* into running head, English text, footnotes and the rest.

    *body* is the line height of the English body type in this item and
    *spacing* the distance between two of its lines (top to top).
    """
    lines = list(leaf.lines)
    dropped: list[Line] = []
    if not lines:
        return Layout(None, [], [], [], 0.0)

    # the text column: from the long lines
    long_lines = [ln for ln in lines if ln.x1 - ln.x0 > 0.5 * leaf.width]
    if long_lines:
        left = statistics.median(ln.x0 for ln in long_lines)
        right = statistics.median(ln.x1 for ln in long_lines)
    else:
        left, right = 0, leaf.width
    col = max(right - left, 1)
    kept = []
    for ln in lines:
        narrow = ln.x1 - ln.x0 < 0.15 * col
        if narrow and (ln.x0 > right - 0.1 * col or ln.x1 < left + 0.1 * col):
            dropped.append(ln)          # a marginal note
        else:
            kept.append(ln)
    lines = kept

    head = None
    if lines and lines[0].top < 0.12 * leaf.height and re.search(r"\d", lines[0].text) \
            and not is_prose(lines[0], body) and len(lines[0].tokens) <= 12:
        head = lines.pop(0)

    # where the English starts: the first run of two prose lines, together
    # with the headings just above it (CHAPTER …, a patriarch's heading)
    start = None
    for i, ln in enumerate(lines):
        if not is_prose(ln, body):
            continue
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        if nxt is None or is_prose(nxt, body) or is_prose_end(nxt, body) \
                or _is_note_start(nxt, ln, body, spacing):
            start = i
            break
    if start is None:
        return Layout(head, [], [], dropped + lines, left)
    while start > 0:
        prev, cur = lines[start - 1], lines[start]
        gap = cur.top - prev.top
        if is_heading_line(prev, body) and gap < 4 * spacing:
            start -= 1
        elif gap < 1.6 * spacing and prev.english_hits >= 1 and body_type(prev, body) \
                and not _APPARATUS_RE.search(prev.text) or \
                (is_prose_end(prev, body) and gap < 1.6 * spacing):
            start -= 1
        elif start >= 2 and gap < 1.6 * spacing and len(prev.tokens) <= 6 \
                and 0.5 * body <= prev.height <= 1.25 * body \
                and not _APPARATUS_RE.search(prev.text) \
                and is_prose(lines[start - 2], body) \
                and prev.top - lines[start - 2].top < 1.6 * spacing:
            start -= 2      # a paragraph's short last line, below its prose
        else:
            break
    dropped += lines[:start]
    rest = lines[start:]

    notes_at = len(rest)
    for j in range(1, len(rest)):
        if _is_note_start(rest[j], rest[j - 1], body, spacing):
            notes_at = j
            break
    english = []
    for ln in rest[:notes_at]:
        if _is_debris(ln, body):
            dropped.append(ln)
        else:
            english.append(ln)
    # footnote debris below the text that the layout did not recognise
    while english and english[-1].english_hits == 0 and len(english[-1].tokens) >= 3:
        dropped.append(english.pop())
    return Layout(head, english, rest[notes_at:], dropped, left)


#: A reference of a footnote: "Eus., H. E.", "S. Matth.", "Ps. cxv", "Ibid.".
_REFERENCE_RE = re.compile(r"\b(?:Eus\.|Ibid|S\. ?(?:Matth|Mark|Luke|John)|Ps\.|Sept\.|cf\.|Cf\.)")

#: The fascicle signature at a page foot, "PATR. OR. — T. I. 36".
_SIGNATURE_RE = re.compile(r"PATR[.,]?\s*O[RP][.,]")


def _is_debris(line: Line, body: float) -> bool:
    """A line inside the English that is not text: the fascicle signature,
    specks read as letters, a rule."""
    if _SIGNATURE_RE.search(line.text):
        return True
    if line.english_hits == 0 and (_APPARATUS_RE.search(line.text)
                                   or _FOOTNOTE_START_RE.match(line.text)
                                   or _REFERENCE_RE.search(line.text)):
        return True     # a footnote or apparatus line the layout let through
    if is_heading_line(line, body) or line.english_hits:
        return False
    return line.height < 0.6 * body or not any(len(t) >= 3 for t in line.tokens)


def is_heading_line(line: Line, body: float) -> bool:
    """A heading line of the English: capitals, no taller than body type."""
    letters = [c for c in line.text if c.isalpha()]
    if not letters or line.height > 1.4 * body:
        return False
    upper = sum(c.isupper() for c in letters) / len(letters)
    return upper > 0.7 and len(letters) >= 5


def _is_note_start(line: Line, prev: Line, body: float, spacing: float) -> bool:
    """Whether *line* starts the footnotes (below *prev*)."""
    gap = line.top - prev.top
    small = line.height < 0.93 * body
    numbered = bool(_FOOTNOTE_START_RE.match(line.text)) or (
        line.english_hits == 0 and bool(_APPARATUS_RE.search(line.text)))
    if numbered and (small or gap > 1.3 * spacing):
        return True
    return small and gap > 1.6 * spacing and not is_heading_line(line, body)
