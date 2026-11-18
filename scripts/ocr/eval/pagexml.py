"""Minimal PAGE-XML reader for OCR ground truth (#718).

Reads any PAGE namespace version (2013, 2019, …): text regions in reading
order with their label and their lines' text. A region's label is its
``@type`` or, as eScriptorium and Calfa write it, the ``type`` in
``@custom="structure {type:…;}"``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

_STRUCTURE_TYPE = re.compile(r"structure\s*\{[^}]*?type:\s*([^;}]+)")


@dataclass(frozen=True)
class Line:
    id: str
    text: str
    label: str | None = None


@dataclass(frozen=True)
class Region:
    id: str
    label: str | None
    lines: tuple[Line, ...]
    # Bounding box of the region's polygon: (x0, y0, x1, y1).
    box: tuple[int, int, int, int] | None = None

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)


@dataclass(frozen=True)
class Page:
    image: str
    width: int
    height: int
    regions: tuple[Region, ...]


def _local(tag: object) -> str:
    return etree.QName(tag).localname if isinstance(tag, str) else ""


def _label(el: etree._Element) -> str | None:
    custom = el.get("custom") or ""
    m = _STRUCTURE_TYPE.search(custom)
    if m:
        return m.group(1).strip()
    return el.get("type")


def _child(el: etree._Element, name: str) -> etree._Element | None:
    for c in el:
        if _local(c.tag) == name:
            return c
    return None


def _text_of(el: etree._Element) -> str:
    """The first TextEquiv/Unicode directly under ``el`` ('' if none)."""
    equivs = [c for c in el if _local(c.tag) == "TextEquiv"]
    if not equivs:
        return ""
    # Prefer index="0" or the first one, as PAGE's convention.
    equivs.sort(key=lambda e: int(e.get("index", "0") or 0))
    uni = _child(equivs[0], "Unicode")
    return (uni.text or "") if uni is not None else ""


def _box(el: etree._Element) -> tuple[int, int, int, int] | None:
    coords = _child(el, "Coords")
    if coords is None or not coords.get("points"):
        return None
    pts = [tuple(int(float(v)) for v in p.split(",")) for p in coords.get("points").split()]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _reading_order(page: etree._Element) -> list[str]:
    ro = _child(page, "ReadingOrder")
    if ro is None:
        return []
    refs = [el for el in ro.iter() if _local(el.tag) in ("RegionRefIndexed", "RegionRef")]
    refs.sort(key=lambda e: int(e.get("index", "0")))
    return [e.get("regionRef") for e in refs]


def read_page(path: Path) -> Page:
    """Parse one PAGE-XML file."""
    root = etree.parse(str(path)).getroot()
    page = next(el for el in root.iter() if _local(el.tag) == "Page")
    regions: list[Region] = []
    for el in page.iter():
        if _local(el.tag) != "TextRegion":
            continue
        lines = tuple(
            Line(id=ln.get("id", ""), text=_text_of(ln), label=_label(ln))
            for ln in el
            if _local(ln.tag) == "TextLine"
        )
        regions.append(Region(id=el.get("id", ""), label=_label(el), lines=lines, box=_box(el)))
    order = _reading_order(page)
    if order:
        rank = {rid: i for i, rid in enumerate(order)}
        regions.sort(key=lambda r: rank.get(r.id, len(rank)))
    return Page(
        image=page.get("imageFilename", ""),
        width=int(page.get("imageWidth", "0")),
        height=int(page.get("imageHeight", "0")),
        regions=tuple(regions),
    )
