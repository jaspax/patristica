"""
Re-chunk paragraphs at the verse numbers an edition prints inline (#122).

Some CCEL texts keep the edition's verse numbers inside the paragraph text
(``1. There are two ways … 2. The way of life …``), several per paragraph,
while the paragraph's ref numbers the paragraph or chapter. ``rechunk`` cuts
such paragraphs at the numbers, so each printed verse becomes its own unit
``{section}.{verse}`` and the numbers leave the text.

A number counts as a verse marker only when it continues the run: it must be
greater than the previous verse number by at most ``max_gap`` (an edition can
skip a verse it doesn't have: the Akhmim *Apocalypse of Peter* goes 1, 3).
Anything else (citations such as ``p. 379.``, numbers in the prose) stays
text. A marker is ``N.`` or ``N,`` after the start of the text, whitespace or
a dash, and before whitespace.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable

log = logging.getLogger(__name__)

_MARKER_RE = re.compile(r"(?:^|(?<=[\s—–-]))(\d{1,3})[.,](?=\s)")


def split_verses(text: str, last: int = 0, max_gap: int = 1) -> tuple[str, list[tuple[int, str]]]:
    """Split *text* at the printed verse numbers that continue a run after *last*.

    Returns ``(lead, verses)``: the text before the first marker (``""`` when
    the text starts with one) and ``(number, text)`` per verse.
    """
    cuts: list[tuple[int, int, int]] = []  # (number, marker start, text start)
    for m in _MARKER_RE.finditer(text):
        n = int(m.group(1))
        if last < n <= last + max_gap:
            cuts.append((n, m.start(), m.end()))
            last = n
    if not cuts:
        return text.strip(), []
    lead = text[: cuts[0][1]].strip()
    verses = []
    for i, (n, _, start) in enumerate(cuts):
        end = cuts[i + 1][1] if i + 1 < len(cuts) else len(text)
        verses.append((n, text[start:end].strip()))
    return lead, verses


def rechunk(
    paragraphs: list[dict[str, str]],
    section_of: Callable[[str], str | None],
    *,
    restart: bool,
    max_gap: int = 1,
) -> list[dict[str, str]]:
    """Cut the paragraphs that *section_of* maps to a section at their printed verses.

    *section_of* returns the section ref a paragraph's verses go under (the
    verse ref is ``{section}.{n}``), or None to keep the paragraph as it is.
    With *restart*, every paragraph numbers its verses from 1 (a chapter);
    otherwise numbering runs on across the section's paragraphs, and text
    before a paragraph's first marker continues the previous verse.

    Raises ``ValueError`` when a section paragraph yields no verse, or starts
    with unnumbered text that has no verse to continue.
    """
    out: list[dict[str, str]] = []
    last: dict[str, int] = {}
    current: dict[str, dict[str, str]] = {}  # section → its last verse record
    for para in paragraphs:
        section = section_of(para["ref"])
        if section is None:
            out.append(para)
            continue
        start = 0 if restart else last.get(section, 0)
        lead, verses = split_verses(para["text"], start, max_gap)
        if not verses and not lead:
            continue
        if lead:
            prev = current.get(section)
            if prev is None or restart:
                raise ValueError(
                    f"{para['ref']}: text before the first printed verse number: {lead[:80]!r}"
                )
            prev["text"] = f"{prev['text']} {lead}"
        for n, text in verses:
            if n != start + 1:
                log.info("%s: printed verse %d follows %d", para["ref"], n, start)
            record = {"ref": f"{section}.{n}", "text": text}
            out.append(record)
            current[section] = record
            start = n
        last[section] = start
    return out
