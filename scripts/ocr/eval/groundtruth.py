"""Calfa's Patrologia Graeca ground truth → the tracked eval set (#718).

Calfa (Vidal-Gorène et al.) publishes hand-transcribed PG pages as PAGE-XML
with their images, CC BY 4.0, on Zenodo (record 20008699, ``data-v2.zip``).
Only pages with transcribed lines are taken; of each, the regions of Greek
text (not a Latin column, not empty layout-only regions), in reading order,
line by line, exactly as transcribed.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from scripts.ingest._common import download_file

from .pagexml import Line, Page, Region, read_page

log = logging.getLogger(__name__)

ZENODO_RECORD = "https://zenodo.org/records/20008699"


@dataclass(frozen=True)
class Source:
    set: str
    file: str

    @property
    def url(self) -> str:
        return f"{ZENODO_RECORD}/files/{self.file}?download=1"


# data-v2.zip repeats every transcribed page of v1's data.zip (whose task1 is
# layout only), so v2 alone is the ground truth.
SOURCES = (Source("calfa-v2", "data-v2.zip"),)

MANIFEST_FIELDS = (
    "page_id", "set", "pg_volume", "source", "image", "lines", "chars",
    "columns", "status", "ogl_scan", "ogl_stem", "ogl_containment", "note",
)

# Region labels that are never Greek running text.
_SKIP_LABELS = {"col_latin", "latin", "notes", "note", "header", "running_head",
                "page_number", "column_number", "footnote"}
_GREEK_MIN = 0.5
_VOLUME = re.compile(r"PG[_-]?(\d+(?:\.\d+)?)", re.IGNORECASE)
# Files named by work, not volume: Gregory Nazianzen's orations 1–4, Migne
# columns 396–719, are all PG 35.
_VOLUME_BY_PREFIX = {"grc_grna_or": "35"}


def _greek_share(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    greek = sum(1 for c in letters if 0x0370 <= ord(c) <= 0x03FF or 0x1F00 <= ord(c) <= 0x1FFF)
    return greek / len(letters)


def _greek_regions(page: Page) -> list[Region]:
    """The page's Greek text regions, top to bottom.

    Calfa's text pages are single-column crops without a reading order, and
    a few list their regions bottom first, so position decides the order.
    """
    out = []
    for region in page.regions:
        if (region.label or "").lower() in _SKIP_LABELS:
            continue
        text = "\n".join(ln.text for ln in region.lines if ln.text.strip())
        if text and _greek_share(text) >= _GREEK_MIN:
            out.append(region)
    return sorted(out, key=lambda r: r.box[1] if r.box else 0)


def _line_top(line: Line) -> int:
    return min((y for _, y in line.points), default=0)


def greek_lines(xml_path: Path) -> list[str]:
    """The transcribed lines of a page's Greek text regions, top to bottom.

    Lines are ordered by position inside each region too: a few pages list a
    line out of place (PG 145 col. 342 has its line at y 1917 last).
    """
    out = []
    for region in _greek_regions(read_page(xml_path)):
        lines = [ln for ln in region.lines if ln.text.strip()]
        if all(ln.points for ln in lines):
            lines.sort(key=_line_top)
        out.extend(ln.text.strip() for ln in lines)
    return out


def untranscribed(page: Page) -> list[Line]:
    """Lines the transcriber segmented but left empty, in any region."""
    return [ln for region in page.regions for ln in region.lines
            if not ln.text.strip() and len(ln.points) >= 3]


def masked_image(data: bytes, lines: list[Line], suffix: str) -> bytes:
    """The image with every line in ``lines`` painted white.

    Calfa left some segmented lines untranscribed (a heading, a note mark, or
    most of a column on a few pages). Erasing them makes the image show
    exactly what the ground truth transcribes, so an engine that reads them
    isn't charged with insertions.
    """
    from PIL import Image, ImageDraw

    img = Image.open(io.BytesIO(data))
    img.load()
    draw = ImageDraw.Draw(img)
    white = 255 if img.mode in ("L", "1") else (255,) * len(img.getbands())
    for ln in lines:
        draw.polygon(list(ln.points), fill=white)
    out = io.BytesIO()
    fmt = {".jpg": "JPEG", ".jpeg": "JPEG", ".png": "PNG", ".tif": "TIFF"}.get(suffix, "PNG")
    img.save(out, format=fmt, **({"quality": 95} if fmt == "JPEG" else {}))
    return out.getvalue()


def page_id(set_name: str, member: str) -> str:
    stem = Path(member).stem
    return f"{set_name}-{re.sub(r'[^A-Za-z0-9._-]+', '_', stem)}"


def volume_of(member: str) -> str:
    stem = Path(member).stem
    for prefix, volume in _VOLUME_BY_PREFIX.items():
        if stem.startswith(prefix):
            return volume
    m = _VOLUME.search(stem)
    if not m:
        raise ValueError(f"no PG volume in {member!r}")
    return m.group(1)


def _image_member(names: set[str], xml_member: str, image_file: str) -> str | None:
    folder = xml_member.rsplit("/", 1)[0] + "/" if "/" in xml_member else ""
    exts = (".jpg", ".jpeg", ".png", ".tif")
    for cand in (folder + image_file, *(xml_member[:-4] + ext for ext in exts)):
        if cand in names:
            return cand
    return None


def extract(zip_path: Path, source: Source, gt_dir: Path, image_dir: Path,
            tmp_dir: Path) -> list[dict[str, str]]:
    """Write one source's pages to ``gt_dir`` and ``image_dir``; their manifest rows."""
    rows: list[dict[str, str]] = []
    with zipfile.ZipFile(zip_path) as z:
        names = {n for n in z.namelist() if not n.startswith("__MACOSX/")}
        for member in sorted(n for n in names if n.endswith(".xml")):
            xml_tmp = tmp_dir / "page.xml"
            xml_tmp.write_bytes(z.read(member))
            lines = greek_lines(xml_tmp)
            if not lines:
                continue
            pid = page_id(source.set, member)
            (gt_dir / f"{pid}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
            page = read_page(xml_tmp)
            blank = untranscribed(page)
            image = _image_member(names, member, page.image)
            if image:
                suffix = Path(image).suffix.lower()
                data = z.read(image)
                if blank:
                    data = masked_image(data, blank, suffix)
                (image_dir / f"{pid}{suffix}").write_bytes(data)
            else:
                log.warning("%s: no image in %s", member, zip_path.name)
            rows.append({
                "page_id": pid, "set": source.set, "pg_volume": volume_of(member),
                "source": f"{ZENODO_RECORD} {source.file}:{member}",
                "image": image or "", "lines": str(len(lines)),
                "chars": str(sum(len(ln) for ln in lines)), "status": "checked",
                "note": f"image: {len(blank)} untranscribed lines masked" if blank else "",
            })
    return rows


def build(gt_dir: Path, download_dir: Path, image_dir: Path) -> list[dict[str, str]]:
    """Download every source (cached) and rewrite the Calfa ground truth."""
    gt_dir.mkdir(parents=True, exist_ok=True)
    image_dir.mkdir(parents=True, exist_ok=True)
    download_dir.mkdir(parents=True, exist_ok=True)
    for old in gt_dir.glob("calfa-*.txt"):
        old.unlink()
    rows: list[dict[str, str]] = []
    for source in SOURCES:
        zip_path = download_file(source.url, download_dir / source.file, etag_cache=False)
        got = extract(zip_path, source, gt_dir, image_dir, download_dir)
        log.info("%s: %d pages with Greek text", source.set, len(got))
        rows.extend(got)
    return rows
