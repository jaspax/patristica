"""The OCR pipeline on the OGPG holes (#721): page images in, ingestible pages out.

    prepare  the located leaf of each page that needs OCR (scripts.ogpg_images)
             -> its Greek column, cropped with its half of the running head
    (run)    the pipeline's stages on the crops (scripts/ocr/stages.py)
    export   the final text of each page -> data/ocr/ogpg/{volume}.jsonl, the
             per-page text the OGPG ingestor adds to the holes (#719)

A Migne page prints the Greek and the Latin side by side, the Greek on the
left of some pages and the right of others, each column with its number in
the running head above it.  ``prepare`` finds the gutter from the ink of the
body, tells the Greek half by the letters Tesseract reads in a band of each
half (a page with no Greek half is skipped), and crops that half from the
top, so the page readers transcribe the column's number as their first line.
``export`` checks it: a page whose readers read another number there (the
leaf chosen is a page off, about 1 in 10 by eye, #754) is rejected; one
whose number nobody could read is kept and flagged.  The head line is then
dropped from the text.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[2]
IMAGES_DIR = REPO_ROOT / "data" / "raw" / "_images" / "ogpg"
LOCATED = REPO_ROOT / "data" / "cache" / "ogpg_images" / "pages.jsonl"
OCR_DIR = REPO_ROOT / "data" / "ocr" / "ogpg"

SOURCE = "patristica-ocr-v1"
CREDIT = ("pages missing from the OGL OCR newly OCR'd for Patristica from Internet Archive "
          "scans (Kraken CLLG, Gemini and Claude, #721)")
# Greek letters a page's text needs to be exported.
MIN_GREEK = 300
# Greek letters a half's sample band needs to count as the Greek column.
MIN_HALF_GREEK = 60


def page_id(volume: str, col: int) -> str:
    return f"{volume}-c{col:04d}"


def _greek(text: str) -> int:
    return sum(1 for c in text if "Ͱ" <= c <= "Ͽ" or "ἀ" <= c <= "῿")


def _latin(text: str) -> int:
    return sum(1 for c in text if c.isascii() and c.isalpha())


def gutter(img: Image.Image) -> int:
    """The x of the gutter between the two columns: the least inked vertical
    band in the middle fifth of the page body."""
    w, h = img.size
    small = np.asarray(img.convert("L").resize((w // 4, h // 4))) < 128
    body = small[int(small.shape[0] * 0.1):int(small.shape[0] * 0.85)]
    prof = np.convolve(body.sum(0), np.ones(5), "same")
    lo, hi = int(body.shape[1] * 0.4), int(body.shape[1] * 0.6)
    return 4 * (lo + int(np.argmin(prof[lo:hi])))


def tesseract(img: Image.Image) -> str:
    with tempfile.NamedTemporaryFile(suffix=".png") as f:
        img.save(f.name)
        return subprocess.run(["tesseract", f.name, "-", "-l", "grc+eng", "--psm", "6"],
                              capture_output=True, text=True, check=True).stdout


@dataclass
class Prepared:
    volume: str
    cols: list[int]
    page: str               # page id, the crop's file stem
    side: str | None        # "left" / "right": where the Greek column is; None: no Greek half
    gutter: int
    greek: list[int]        # Greek letters Tesseract read in the left and right bands
    latin: list[int]
    source: dict            # ia_id, leaf, url of the image


def greek_side(img: Image.Image, gx: int) -> tuple[str | None, list[int], list[int]]:
    """Which half is the Greek column, from a band of each half."""
    w, h = img.size
    y0, y1 = int(h * 0.3), int(h * 0.45)
    greek, latin = [], []
    for x0, x1 in ((0, gx), (gx, w)):
        band = img.crop((x0, y0, x1, y1))
        text = tesseract(band.resize((band.width // 2, band.height // 2)))
        greek.append(_greek(text))
        latin.append(_latin(text))
    best = int(np.argmax(greek))
    if greek[best] < MIN_HALF_GREEK or greek[best] < latin[best]:
        return None, greek, latin
    return ("left", "right")[best], greek, latin


def prepare(volume: str, out: Path, images_dir: Path = IMAGES_DIR,
            located: Path = LOCATED, limit: int | None = None) -> list[Prepared]:
    """Crop the Greek column of every located page of ``volume`` that needs OCR
    -> ``out/images/{page}.jpg``, ``out/pages.txt`` (the pages to run) and
    ``out/prepare.jsonl``.  Idempotent: a page already prepared is kept."""
    vdir = images_dir / volume
    manifest = {}
    if (vdir / "manifest.jsonl").exists():
        for line in (vdir / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
            e = json.loads(line)
            manifest[e["file"].split(".", 1)[0]] = e
    recs = [json.loads(line) for line in located.read_text(encoding="utf-8").splitlines()]
    recs = [r for r in recs if r["volume"] == volume and r.get("ia_id")]
    (out / "images").mkdir(parents=True, exist_ok=True)
    done_f = out / "prepare.jsonl"
    done = {}
    if done_f.exists():
        for line in done_f.read_text(encoding="utf-8").splitlines():
            p = Prepared(**json.loads(line))
            done[p.page] = p
    result = []
    for r in recs[:limit] if limit else recs:
        col = r["cols"][0]
        pid = page_id(volume, col)
        if pid in done:
            result.append(done[pid])
            continue
        stem = f"c{col:04d}"
        e = manifest.get(stem)
        files = [f for f in (vdir / f"{stem}.jp2", vdir / f"{stem}.jpg") if f.exists()]
        if not files or not e or (e["ia_id"], e["page"]) != (r["ia_id"], r["leaf"]):
            log.warning("%s: no image of the chosen leaf (run scripts.ogpg_images fetch)", pid)
            continue
        img = Image.open(files[0]).convert("L")
        gx = gutter(img)
        side, greek, latin = greek_side(img, gx)
        p = Prepared(volume, r["cols"], pid, side, gx, greek, latin,
                     {"ia_id": e["ia_id"], "leaf": e["leaf"], "url": e["url"]})
        if side is not None:
            margin = img.width // 100
            box = (0, 0, gx - margin, img.height) if side == "left" else \
                (gx + margin, 0, img.width, img.height)
            img.crop(box).save(out / "images" / f"{pid}.jpg", quality=90)
        with done_f.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(p)) + "\n")
        result.append(p)
    pages = [p.page for p in result if p.side]
    (out / "pages.txt").write_text("\n".join(pages) + "\n", encoding="utf-8")
    log.info("%s: %d pages prepared, %d with a Greek column -> %s", volume, len(result),
             len(pages), out)
    return result


# ---------------------------------------------------------------------------
# The running head
# ---------------------------------------------------------------------------

_NUM = re.compile(r"\d{1,4}")


def head_numbers(text: str) -> set[int]:
    """Column numbers in a reading's first non-empty line (the running head)."""
    for line in text.splitlines():
        if line.strip():
            return {int(n) for n in _NUM.findall(line) if int(n) >= 7}
    return set()


def head_check(readings: list[str], cols: list[int]) -> str:
    """``ok`` when a reader reads one of the page's columns in the head,
    ``off`` when readers read only other numbers (the leaf is another page),
    ``unread`` when none reads a number there."""
    nums = [head_numbers(t) for t in readings]
    if any(n & set(cols) for n in nums):
        return "ok"
    if any(nums):
        return "off"
    return "unread"


def _is_head_line(line: str) -> bool:
    """A line of the running head: one with a column number and few Greek
    letters, or a short one with none (the head's Latin title, maybe cut by
    the crop).  Greek capitals (ΑΛΛΟ., a work's title) are the text's own."""
    greek = _greek(line)
    return (bool(head_numbers(line)) and greek < 3) or (len(line) < 60 and greek == 0)


def drop_head(text: str, cols: list[int]) -> str:
    """The text without the running head: up to three head lines at its top
    (the readers write the number and the title on one line or on two)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    for _ in range(3):
        if lines and _is_head_line(lines[0]):
            lines.pop(0)
    return "\n".join(lines).strip()


_MARGIN_LETTER = re.compile(r"^[A-E]\s+(?=\S)")


def clean(text: str) -> str:
    """A page's text for the ingestor: Migne's margin letters (A-E, the
    section marks beside the column) dropped from line starts, and the lines
    after the text dropped: the notes of Scripture references and the scanner's
    stamp, mostly Latin letters and digits."""
    lines = [_MARGIN_LETTER.sub("", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    while lines and _greek(lines[-1]) < 0.5 * max(1, _greek(lines[-1]) + _latin(lines[-1])):
        lines.pop()
    return "\n".join(lines)


def export(run: Path, prep: Path, ocr_dir: Path = OCR_DIR) -> dict[str, int]:
    """Final text of every page of a run -> ``ocr_dir/{volume}.jsonl`` (merged
    with the file's other pages, never replacing another source's page)."""
    prepared = {}
    for line in (prep / "prepare.jsonl").read_text(encoding="utf-8").splitlines():
        p = Prepared(**json.loads(line))
        prepared[p.page] = p
    by_vol: dict[str, list[dict]] = {}
    counts = {"exported": 0, "off": 0, "unread": 0, "thin": 0, "missing": 0}
    for pid, p in prepared.items():
        if p.side is None:
            continue
        final = run / "final" / f"{pid}.txt"
        if not final.exists():
            counts["missing"] += 1
            continue
        readings = [(run / s / f"{pid}.txt").read_text(encoding="utf-8")
                    for s in ("gemini_page", "opus_page") if (run / s / f"{pid}.txt").exists()]
        check = head_check(readings + [final.read_text(encoding="utf-8")], p.cols)
        if check == "off":
            counts["off"] += 1
            log.info("%s: the head reads %s, not %s: rejected", pid,
                     sorted(set().union(*(head_numbers(t) for t in readings))), p.cols)
            continue
        text = clean(drop_head(final.read_text(encoding="utf-8"), p.cols))
        if _greek(text) < MIN_GREEK:
            counts["thin"] += 1
            continue
        counts["unread"] += check == "unread"
        counts["exported"] += 1
        by_vol.setdefault(p.volume, []).append(
            {"cols": p.cols, "lines": text.splitlines(), "source": SOURCE, "head": check,
             **p.source})
    for vol, recs in by_vol.items():
        path = ocr_dir / f"{vol}.jsonl"
        old = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()] \
            if path.exists() else []
        taken = {tuple(r["cols"]) for r in old if r["source"] != SOURCE}
        keep = [r for r in old if r["source"] != SOURCE]
        merged = keep + [r for r in recs if tuple(r["cols"]) not in taken]
        merged.sort(key=lambda r: r["cols"][0])
        ocr_dir.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in merged),
                        encoding="utf-8")
    sources = ocr_dir / "_sources.json"
    known = json.loads(sources.read_text(encoding="utf-8")) if sources.exists() else {}
    if by_vol and known.get(SOURCE) != CREDIT:
        sources.write_text(json.dumps({**known, SOURCE: CREDIT}, ensure_ascii=False, indent=1)
                           + "\n", encoding="utf-8")
    log.info("exported %(exported)d pages (%(unread)d with an unread head); rejected %(off)d "
             "whose head reads another column, %(thin)d with too little Greek; %(missing)d "
             "not run", counts)
    return counts
