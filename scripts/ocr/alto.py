"""Kraken's ALTO output: lines of words with confidences and line boxes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from scripts.ocr.text import norm


@dataclass(frozen=True)
class Word:
    text: str
    conf: float  # Kraken's word confidence (ALTO WC), 0..1


@dataclass(frozen=True)
class Line:
    words: tuple[Word, ...]
    box: tuple[int, int, int, int]  # x0, y0, x1, y1 in image pixels

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)


def _local(el: etree._Element) -> str:
    return etree.QName(el).localname


def read_alto(path: Path) -> list[Line]:
    """The page's lines in reading order (top to bottom), empty lines dropped."""
    root = etree.parse(str(path)).getroot()
    lines = []
    for tl in root.iter():
        if not isinstance(tl.tag, str) or _local(tl) != "TextLine":
            continue
        x, y = int(float(tl.get("HPOS"))), int(float(tl.get("VPOS")))
        box = (x, y, x + int(float(tl.get("WIDTH"))), y + int(float(tl.get("HEIGHT"))))
        words = tuple(
            Word(t, float(el.get("WC") or 1))
            for el in tl if isinstance(el.tag, str) and _local(el) == "String"
            if (t := norm(el.get("CONTENT", "")))
        )
        if words:
            lines.append(Line(words, box))
    lines.sort(key=lambda ln: (ln.box[1], ln.box[0]))
    return lines
