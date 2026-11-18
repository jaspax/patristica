"""Calfa's Patrologia Graeca ground truth → the tracked eval set (#718).

Calfa (Vidal-Gorène et al.) publishes hand-transcribed PG pages as PAGE-XML
with their images, CC BY 4.0, on Zenodo (record 20008699, ``data-v2.zip``).
Only pages with transcribed lines are taken; of each, the regions of Greek
text (not a Latin column, not empty layout-only regions), in reading order,
line by line, exactly as transcribed.
"""

from __future__ import annotations

import logging
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from scripts.ingest._common import download_file

from .pagexml import read_page

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


def greek_lines(xml_path: Path) -> list[str]:
    """The transcribed lines of a page's Greek text regions, in reading order."""
    page = read_page(xml_path)
    out: list[str] = []
    for region in page.regions:
        if (region.label or "").lower() in _SKIP_LABELS:
            continue
        lines = [ln.text.strip() for ln in region.lines if ln.text.strip()]
        if lines and _greek_share("\n".join(lines)) >= _GREEK_MIN:
            out.extend(lines)
    return out


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
            image = _image_member(names, member, read_page(xml_tmp).image)
            if image:
                dest = image_dir / f"{pid}{Path(image).suffix.lower()}"
                if not dest.exists():
                    dest.write_bytes(z.read(image))
            else:
                log.warning("%s: no image in %s", member, zip_path.name)
            rows.append({
                "page_id": pid, "set": source.set, "pg_volume": volume_of(member),
                "source": f"{ZENODO_RECORD} {source.file}:{member}",
                "image": image or "", "lines": str(len(lines)),
                "chars": str(sum(len(ln) for ln in lines)), "status": "checked",
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
