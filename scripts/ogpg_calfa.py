"""
Calfa's OCR of the Patrologia Graeca for the OGPG holes (#719 step 4, #710).

Vidal-Gorène & Kindt (Calfa) re-OCR'd 33 PG volumes (arXiv 2603.09470;
Zenodo 19915273, CC BY 4.0), 18 of them in our period.  Their text is the
Greek only, word by word, located by the page of their Google PDFs and the
line on it; it has no Migne columns.  So each PDF page is placed the way
``scripts.ogpg_images`` places an Internet Archive copy's leaves: by matching
its text against our OGPG text, here through ``_ogpg_columns.map_columns``
with the matched columns standing in for running-head numbers.  A page in
one of our holes is taken when our text confirms the map on both sides of it
(``ogpg_images.trust``), or when its text matches the Internet Archive leaf
that ``scripts.ogpg_images locate`` put at the same columns (an independent
placement, through that copy's running heads): Calfa's text of a volume may
stop inside a hole, leaving no text after it to confirm the map.

Only pages that need OCR get Calfa's text (owner, 2026-11-16: fill the holes,
never replace OGPG text, which would renumber refs)::

    uv run python -m scripts.ogpg_calfa [--pages PAGES.jsonl]

``PAGES.jsonl`` is ``scripts.ogpg_coverage --scans --pages``.  The result is
tracked, one file per volume, ``data/ocr/ogpg/{volume}.jsonl``: a line per
page, ``{"cols", "lines", "source", "pdf_page", "confirmed_by"}``, and the
source's credit in ``data/ocr/ogpg/_sources.json``.  The ingestor reads it
(``scripts/ingest/ogpg.py``, ``ocr_pages``) and adds each page where the
volume has no text of its own.  Reads ``data/raw/ogpg``, so it runs where the
data is.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import httpx

from patristica.console import setup_logging
from scripts import ogpg_images as oi

log = logging.getLogger(__name__)

RAW_DIR = Path("data/raw/ogpg")
CACHE_DIR = Path("data/cache/calfa_pg")
OCR_DIR = Path("data/ocr/ogpg")
RECORD = "19915273"
ZIP_URL = f"https://zenodo.org/records/{RECORD}/files/PG.zip"
SOURCE = f"calfa-pg-zenodo-{RECORD}"
CREDIT = ("pages missing from the OGL OCR filled from Calfa's OCR (Vidal-Gorène & Kindt, "
          f"Patrologia Graeca, Zenodo {RECORD}, CC BY 4.0)")

_FILE = re.compile(r"PG(\d{3})(?:_(\d))?_tagged_text\.(?:vert|txt)$")
_WORD = re.compile(r'<w id="PDF Page (\d+), Line (\d+)[^"]*">\s*([^\t\r\n]*)')
# A Calfa page gives its text only with at least this many Greek letters.
MIN_GREEK = 300
# Matches a PDF page needs to vote for its column.
MIN_VOTES = 3
# Sampled 3-grams a Calfa page must share with the located Internet Archive
# leaf of its columns to confirm it.
MIN_SHARED = 5


def volume_of(name: str) -> str | None:
    """Our volume id of a Calfa file (``PG/PG087_1_tagged_text.vert`` -> ``vol-087-pt1``)."""
    m = _FILE.search(name)
    if not m:
        return None
    return f"vol-{m.group(1)}" + (f"-pt{m.group(2)}" if m.group(2) else "")


def read_pages(data: str) -> dict[int, list[str]]:
    """A Calfa file's text: PDF page -> its lines, in order."""
    words: dict[int, dict[int, list[str]]] = defaultdict(lambda: defaultdict(list))
    for m in _WORD.finditer(data):
        words[int(m.group(1))][int(m.group(2))].append(m.group(3))
    return {p: [" ".join(ws) for _, ws in sorted(lines.items())]
            for p, lines in sorted(words.items())}


def download(cache_dir: Path = CACHE_DIR) -> Path:
    path = cache_dir / f"PG-{RECORD}.zip"
    if not path.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        log.info("downloading %s", ZIP_URL)
        with httpx.stream("GET", ZIP_URL, follow_redirects=True, timeout=600) as r:
            r.raise_for_status()
            tmp = path.with_suffix(".part")
            with tmp.open("wb") as f:
                for chunk in r.iter_bytes():
                    f.write(chunk)
            tmp.rename(path)
    return path


@dataclass
class Placed:
    """A Calfa volume's PDF pages placed on our columns."""

    volume: str
    cols: dict[int, tuple[int, int]]        # PDF page -> its two columns
    diffs: dict[int, list[int]]             # PDF page -> (our page - mapped page) of matches
    matched: int                            # pages with matches in this volume
    agree: float                            # share of them at their mapped columns


def place(volume: str, pages: dict[int, list[str]], ours: oi.OurText) -> Placed:
    """Map PDF pages to columns from where their text matches ours."""
    from scripts.ingest import _ogpg_columns as cols

    hits: dict[int, list[int]] = {}
    heads = []
    for p, lines in pages.items():
        own = [page for vol, page in ours.hits("\n".join(lines)) if vol == volume]
        hits[p] = own
        top = Counter(own).most_common(1)
        heads.append((f"{p:04d}", [top[0][0]] if top and top[0][1] >= MIN_VOTES else []))
    cmap = cols.map_columns(heads)
    placed = {int(s): span for s, span in cmap.columns.items() if span is not None}
    diffs = {p: [h - oi.page_of(placed[p][0]) for h in hs] for p, hs in hits.items()
             if hs and p in placed}
    votes = [Counter(d).most_common(1)[0][0] for d in diffs.values()]
    agree = sum(abs(v) <= 2 for v in votes) / len(votes) if votes else 0.0
    return Placed(volume, placed, diffs, len(votes), agree)


def leaf_texts(images_cache: Path) -> dict[tuple[str, int], str]:
    """(volume, page) -> the OCR text of the Internet Archive leaf located for it."""
    out: dict[tuple[str, int], str] = {}
    f = images_cache / "pages.jsonl"
    if not f.exists():
        log.warning("no %s: Calfa pages are confirmed by our text alone", f)
        return out
    items: dict[str, list[str] | None] = {}
    for line in f.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("ia_id"):
            if r["ia_id"] not in items:     # cached by locate: no request
                items[r["ia_id"]] = oi.item_pages(None, r["ia_id"], images_cache)
            pages = items[r["ia_id"]]
            if pages and r["leaf"] < len(pages):
                out[r["volume"], r["cols"][0]] = pages[r["leaf"]]
    return out


def fill(pages_file: Path, raw_dir: Path = RAW_DIR, cache_dir: Path = CACHE_DIR,
         out_dir: Path = OCR_DIR, images_cache: Path = oi.CACHE_DIR) -> dict[str, int]:
    """Calfa's text for every page that needs OCR and that it has -> ``out_dir``."""
    wanted: dict[str, set[int]] = defaultdict(set)
    for line in pages_file.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r["needs_ocr"]:
            wanted[r["volume"]].add(r["cols"][0])
    leaves = leaf_texts(images_cache)
    ours = oi.OurText(raw_dir)
    filled: dict[str, int] = {}
    with zipfile.ZipFile(download(cache_dir)) as z:
        for name in sorted(z.namelist()):
            vol = volume_of(name)
            if vol is None or vol not in ours.volumes:
                continue                    # after the period: not in our corpus
            pages = read_pages(z.read(name).decode("utf-8"))
            pl = place(vol, pages, ours)
            by_page: dict[int, list[int]] = defaultdict(list)
            for p, span in pl.cols.items():
                by_page[oi.page_of(span[0])].append(p)
            recs = []
            for page in sorted(wanted.get(vol, ())):
                options = []
                for p in by_page.get(page, ()):
                    text = "\n".join(pages[p])
                    if oi.greek_letters(text) < MIN_GREEK:
                        continue
                    if all(oi.trust(pl.diffs, p, False)):
                        options.append((p, "text"))
                    elif (vol, page) in leaves and len(
                            oi.shingles(text) & oi.shingles(leaves[vol, page])) >= MIN_SHARED:
                        options.append((p, "leaf"))
                if len(options) != 1:
                    continue                # none, or two PDF pages on one column: not guessed
                p, how = options[0]
                recs.append({"cols": [page, page + 1], "lines": pages[p], "source": SOURCE,
                             "pdf_page": p, "confirmed_by": how})
            log.info("%s (%s): %d PDF pages, %d placed, agree %.3f; %d of %d pages that need "
                     "OCR filled", vol, name.rsplit("/", 1)[-1], len(pages), len(pl.cols),
                     pl.agree, len(recs), len(wanted.get(vol, ())))
            path = out_dir / f"{vol}.jsonl"
            if recs:
                out_dir.mkdir(parents=True, exist_ok=True)
                path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs),
                                encoding="utf-8")
            elif path.exists():
                path.unlink()
            filled[vol] = len(recs)
    sources = out_dir / "_sources.json"
    known = json.loads(sources.read_text(encoding="utf-8")) if sources.exists() else {}
    if any(filled.values()) and known.get(SOURCE) != CREDIT:
        out_dir.mkdir(parents=True, exist_ok=True)
        sources.write_text(json.dumps({**known, SOURCE: CREDIT}, ensure_ascii=False, indent=1)
                           + "\n", encoding="utf-8")
    log.info("Calfa filled %d pages in %d volumes -> %s", sum(filled.values()),
             sum(1 for n in filled.values() if n), out_dir)
    return filled


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m scripts.ogpg_calfa",
                                description=__doc__.split("\n\n")[0])
    p.add_argument("--pages", type=Path, required=True,
                   help="scripts.ogpg_coverage --scans --pages output")
    p.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    p.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    p.add_argument("--out-dir", type=Path, default=OCR_DIR)
    p.add_argument("--images-cache", type=Path, default=oi.CACHE_DIR,
                   help="scripts.ogpg_images' cache, with its located leaves")
    args = p.parse_args(argv)
    setup_logging()
    fill(args.pages, args.raw_dir, args.cache_dir, args.out_dir, args.images_cache)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
