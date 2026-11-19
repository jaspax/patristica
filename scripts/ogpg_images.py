"""
Page images for the OGPG pages that need new OCR (#719, #710, step 2 of #705).

The OGPG text is OCR of Google scans of Migne's PG.  The Internet Archive
mirrors many of those scans and holds other copies (Toronto's own scans and
others), each with its own Tesseract OCR per page.  Instead of tracing each
OGL scan to its Google id, every Internet Archive copy is mapped onto Migne's
columns the way the ingestor maps its own scans: the column numbers in the
running heads of the copy's OCR, through ``_ogpg_columns.map_columns``.  The
copy's volume is then identified, and the map checked, by matching its text
against our OGPG text at the same columns.  So any copy of a volume serves,
not only the one OGL's OCR came from, and a leaf our scan lacks (an
``unmapped`` page) can come from another copy::

    uv run python -m scripts.ogpg_images discover      # candidates, from IA search
    uv run python -m scripts.ogpg_images identify      # -> scripts/ingest/data/ogpg_images.csv
    uv run python -m scripts.ogpg_images locate --pages PAGES.jsonl   # -> a leaf per page
    uv run python -m scripts.ogpg_images fetch [--volume vol-075] [--limit N]

``PAGES.jsonl`` is ``scripts.ogpg_coverage --scans --pages``: every missing
page, with ``needs_ocr``.  ``locate`` picks one leaf for each page that needs
OCR (``data/cache/ogpg_images/pages.jsonl``), ``fetch`` downloads them into
``data/raw/_images/ogpg/{volume}/`` (gitignored, like the clones), one JPEG
2000 file per page named by its first column, with ``manifest.jsonl``
recording each page's source URL.  Every step is idempotent: the copies' OCR
and the search result are cached in ``data/cache/ogpg_images/``, and fetched
images are kept.  Requests to the Internet Archive are throttled.

The table is tracked: one row per copy that matched a volume, with how well
its map agrees with our text overall (``agree``: the share of matched
passages whose columns are where the copy's map puts them; ``ok`` when that
is high, with no shift).  ``locate`` judges each leaf on its own instead
(``trust``): a hole has no text of ours, so a leaf in it is trusted when our
text confirms the copy's map at both edges, or at one edge and the leaf's own
running head prints its column.  Rows with a ``shift`` are for a person to
check: the copy, or our column map, is off there.  Reads ``data/raw/ogpg``
(the work files), so it runs where the data is.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import logging
import re
import time
import unicodedata
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import httpx

from patristica.console import setup_logging

log = logging.getLogger(__name__)

RAW_DIR = Path("data/raw/ogpg")
CACHE_DIR = Path("data/cache/ogpg_images")
IMAGES_DIR = Path("data/raw/_images/ogpg")
TABLE = Path(__file__).resolve().parent / "ingest" / "data" / "ogpg_images.csv"

IA = "https://archive.org"
SEARCH_QUERY = 'title:(patrologiae cursus) AND mediatype:texts'
# Seconds between requests to the Internet Archive.
THROTTLE = 0.5
USER_AGENT = "patristica-ogpg-images/1.0 (research; throttled)"

# Identification: word 3-grams of folded Greek, sampled by hash (1 in SAMPLE)
# to keep the index of the whole OGPG small.
SAMPLE = 4
MIN_WORD = 3
# A copy is ``ok`` when at least this share of its matched passages sit at
# the columns its map gives (± NEAR pages), on at least MIN_HITS passages.
OK_AGREE = 0.85
MIN_HITS = 40
NEAR = 1
# A page "has Greek" in a copy's OCR when it has this many Greek letters.
GREEK_LETTERS = 300
# Trust is judged per leaf, not per copy (a copy whose heads mislead its map in
# one stretch is still right elsewhere), from the matched passages nearest to
# it on each side, within REACH leaves (``_side``).  A hole has no text of
# ours, so its leaves are judged by the passages at its edges.
SIDE_HITS = 5
REACH = 600

_COL_REF = re.compile(r"\.c(\d+)\.\d+$")


def page_of(col: int) -> int:
    return col if col % 2 else col - 1


# ---------------------------------------------------------------------------
# Internet Archive
# ---------------------------------------------------------------------------


class Archive:
    """Throttled, retrying GETs from the Internet Archive."""

    def __init__(self, throttle: float = THROTTLE) -> None:
        self.client = httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=120,
                                   follow_redirects=True)
        self.throttle, self._last = throttle, 0.0

    def get(self, url: str, **params) -> httpx.Response:
        for attempt in range(5):
            wait = self._last + self.throttle - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                r = self.client.get(url, params=params or None)
            except httpx.TransportError as e:
                log.debug("%s: %s, retrying", url, e)
            else:
                if r.status_code < 500 and r.status_code != 429:
                    return r
                log.debug("%s: HTTP %d, retrying", url, r.status_code)
            time.sleep(2 ** attempt * 2)
        r.raise_for_status()
        return r


def _greek_item(doc: dict) -> bool:
    """Whether a search hit may be a volume of the Greek series."""
    def as_list(v) -> list:
        return v if isinstance(v, list) else ([v] if v else [])
    title = str(doc.get("title", "")).lower()
    if "latina" in title:
        return False
    langs = {str(x).lower() for x in as_list(doc.get("language"))}
    return ("el" in as_list(doc.get("ocr_detected_lang")) or bool(langs & {"gre", "grc", "greek"})
            or "graec" in title or "græc" in title)


def discover(ia: Archive, cache_dir: Path = CACHE_DIR) -> list[dict]:
    """Internet Archive items that may be PG volumes -> ``candidates.json``."""
    fields = ["identifier", "title", "volume", "imagecount", "language", "ocr_detected_lang",
              "source", "contributor", "date", "ppi"]
    r = ia.get(f"{IA}/advancedsearch.php", q=SEARCH_QUERY, **{"fl[]": fields},
               rows=10000, output="json")
    r.raise_for_status()
    docs = [d for d in r.json()["response"]["docs"] if _greek_item(d)]
    docs.sort(key=lambda d: d["identifier"])
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / "candidates.json").write_text(json.dumps(docs, indent=0), encoding="utf-8")
    log.info("%d candidate items", len(docs))
    return docs


def item_pages(ia: Archive, item: str, cache_dir: Path = CACHE_DIR) -> list[str] | None:
    """The OCR text of every page (leaf) of an item, in leaf order; None if it has none.

    From the item's ``_hocr_searchtext.txt.gz`` and ``_hocr_pageindex.json.gz``
    (Tesseract), cached in ``cache_dir/ia/``.
    """
    d = cache_dir / "ia"
    d.mkdir(parents=True, exist_ok=True)
    out = d / f"{item}.json.gz"
    if out.exists():
        data = json.loads(gzip.decompress(out.read_bytes()))
        return data["pages"]
    files = {}
    for suffix in ("hocr_searchtext.txt.gz", "hocr_pageindex.json.gz"):
        r = ia.get(f"{IA}/download/{item}/{item}_{suffix}")
        if r.status_code in (401, 403, 404):    # no OCR, or a lending-library item
            out.write_bytes(gzip.compress(json.dumps({"pages": None}).encode()))
            return None
        r.raise_for_status()
        files[suffix] = gzip.decompress(r.content)
    text = files["hocr_searchtext.txt.gz"].decode("utf-8", errors="replace")
    index = json.loads(files["hocr_pageindex.json.gz"])
    pages = [text[a:b] for a, b, *_ in index]
    out.write_bytes(gzip.compress(json.dumps({"pages": pages}, ensure_ascii=False).encode()))
    return pages


# ---------------------------------------------------------------------------
# Matching text
# ---------------------------------------------------------------------------


def fold_words(text: str) -> list[str]:
    """Greek words, folded (no marks, lower case, final sigma), of MIN_WORD+ letters."""
    s = unicodedata.normalize("NFD", text.lower()).replace("ς", "σ")
    s = "".join(c if ("α" <= c <= "ω") else " " for c in s
                if not unicodedata.combining(c))
    return [w for w in s.split() if len(w) >= MIN_WORD]


def shingles(text: str) -> set[int]:
    """Sampled word 3-grams of a text, as stable hashes."""
    w = fold_words(text)
    out = set()
    for i in range(len(w) - 2):
        h = zlib.crc32(" ".join(w[i:i + 3]).encode())
        if h % SAMPLE == 0:
            out.add(h)
    return out


def greek_letters(text: str) -> int:
    return sum(1 for c in text if "Ͱ" <= c <= "Ͽ" or "ἀ" <= c <= "῿")


class OurText:
    """Where each sampled 3-gram of the OGPG work files is: (volume, page)."""

    def __init__(self, raw_dir: Path = RAW_DIR) -> None:
        self.volumes: list[str] = []
        self.where: dict[int, int] = {}    # shingle -> volume index * 10000 + page; -1 if ambiguous
        vdirs = sorted(p for p in raw_dir.iterdir() if p.is_dir() and p.name.startswith("vol-"))
        for vdir in vdirs:
            v = len(self.volumes)
            self.volumes.append(vdir.name)
            for f in sorted(vdir.glob("*.json")):
                for unit in json.loads(f.read_text(encoding="utf-8")).get("paragraphs") or []:
                    m = _COL_REF.search(unit["ref"])
                    if not m:
                        continue
                    key = v * 10000 + page_of(int(m.group(1)))
                    for h in shingles(unit["text"]):
                        old = self.where.get(h)
                        self.where[h] = key if old is None or old == key else -1
        log.info("indexed %d volumes, %d sampled 3-grams", len(self.volumes), len(self.where))

    def hits(self, text: str) -> list[tuple[str, int]]:
        out = []
        for h in shingles(text):
            k = self.where.get(h, -1)
            if k >= 0:
                out.append((self.volumes[k // 10000], k % 10000))
        return out


# ---------------------------------------------------------------------------
# A copy's column map, and its volume
# ---------------------------------------------------------------------------


@dataclass
class Copy:
    item: str
    volume: str
    leaves: int
    mapped: int             # leaves with a column
    first_col: int | None
    last_col: int | None
    hits: int               # matched passages in its volume
    agree: float            # share of them at the mapped columns (± NEAR pages)
    shift: int              # the most common (our page - mapped page), in columns
    other_hits: int         # matched passages in other volumes
    source: str = ""
    contributor: str = ""
    # Leaf -> (our page - the page the copy's map gives it) of each matched passage.
    diffs: dict[int, list[int]] | None = None

    @property
    def ok(self) -> bool:
        return self.hits >= MIN_HITS and self.agree >= OK_AGREE and self.shift == 0

    def row(self) -> dict:
        return {"volume": self.volume, "ia_id": self.item, "leaves": self.leaves,
                "mapped": self.mapped, "first_col": self.first_col or "",
                "last_col": self.last_col or "", "hits": self.hits,
                "agree": f"{self.agree:.3f}", "shift": self.shift,
                "other_hits": self.other_hits, "ok": "y" if self.ok else "n",
                "google_id": _google_id(self.source), "contributor": self.contributor}


TABLE_FIELDS = ["volume", "ia_id", "leaves", "mapped", "first_col", "last_col", "hits",
                "agree", "shift", "other_hits", "ok", "google_id", "contributor"]


def _google_id(source: str | list) -> str:
    src = " ".join(source) if isinstance(source, list) else str(source or "")
    m = re.search(r"books\?id=([A-Za-z0-9_-]{12})", src)
    return m.group(1) if m else ""


def column_map(pages: list[str]) -> dict[int, tuple[int, int]]:
    """Leaf index -> its two Migne columns, from the running heads of its OCR."""
    from scripts.ingest import _ogpg_columns as cols

    heads = [(f"{i:04d}", sorted(cols.head_numbers(t))) for i, t in enumerate(pages)]
    cmap = cols.map_columns(heads)
    return {int(s): span for s, span in cmap.columns.items() if span is not None}


def identify_copy(item: str, pages: list[str], ours: OurText, meta: dict) -> Copy | None:
    """The volume a copy is of, and how well its column map agrees with our text."""
    cmap = column_map(pages)
    by_vol: dict[str, list[tuple[int, int]]] = defaultdict(list)   # (leaf, our page)
    for leaf, text in enumerate(pages):
        for vol, page in ours.hits(text):
            by_vol[vol].append((leaf, page))
    if not by_vol:
        return None
    vol = max(by_vol, key=lambda v: (len(by_vol[v]), v))
    hits = by_vol[vol]
    diffs = Counter()
    per_leaf: dict[int, list[int]] = defaultdict(list)
    agree = 0
    for leaf, page in hits:
        span = cmap.get(leaf)
        if span is None:
            continue
        d = page - page_of(span[0])
        diffs[d] += 1
        per_leaf[leaf].append(d)
        # One column per page (PG 47-64): a page and its facing page share columns.
        if abs(d) <= 2 * NEAR:
            agree += 1
    with_col = sum(diffs.values())
    shift = diffs.most_common(1)[0][0] if diffs else 0
    spans = list(cmap.values())
    return Copy(item, vol, len(pages), len(cmap),
                min((s[0] for s in spans), default=None), max((s[1] for s in spans), default=None),
                with_col, agree / with_col if with_col else 0.0, shift,
                sum(len(h) for v, h in by_vol.items() if v != vol),
                meta.get("source", ""), str(meta.get("contributor", "")), dict(per_leaf))


def _side(diffs: dict[int, list[int]], leaf: int, step: int) -> bool:
    """Whether our text confirms the copy's map on the nearest leaves one way.

    Each leaf with matched passages votes once, for its most common offset.
    Walking away from ``leaf``, the map is confirmed once SIDE_HITS leaves vote
    for its columns, before SIDE_HITS vote for any one other offset (a map
    that is wrong there).  Leaves at scattered offsets match phrases our text
    has elsewhere too, and are ignored.
    """
    agree = 0
    wrong: Counter[int] = Counter()
    k = leaf
    while abs(k - leaf) <= REACH:
        if k in diffs and diffs[k]:
            d = Counter(diffs[k]).most_common(1)[0][0]
            if abs(d) <= 2 * NEAR:
                agree += 1
                if agree >= SIDE_HITS:
                    return True
            else:
                wrong[d] += 1
                if wrong[d] >= SIDE_HITS:
                    return False
        k += step
    return False


def trust(diffs: dict[int, list[int]], leaf: int, supported: bool) -> tuple[bool, bool]:
    """Whether the copy's map is confirmed by our text (before, after) a leaf.

    A leaf is trusted when both sides confirm it, or when its own running head
    prints its column and one side does (``Leaf.trusted``).
    """
    return _side(diffs, leaf, -1), _side(diffs, leaf, 1)


def save_diffs(c: Copy, cache_dir: Path = CACHE_DIR) -> None:
    d = cache_dir / "maps"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{c.item}.json").write_text(json.dumps({"volume": c.volume, "diffs": c.diffs}))


def load_diffs(item: str, cache_dir: Path = CACHE_DIR) -> dict[int, list[int]]:
    f = cache_dir / "maps" / f"{item}.json"
    if not f.exists():
        return {}
    return {int(k): v for k, v in json.loads(f.read_text())["diffs"].items()}


def identify(ia: Archive, raw_dir: Path = RAW_DIR, cache_dir: Path = CACHE_DIR,
             table: Path = TABLE) -> list[Copy]:
    """Identify every candidate's volume -> ``table`` (one row per matched copy)."""
    cands = json.loads((cache_dir / "candidates.json").read_text(encoding="utf-8"))
    ours = OurText(raw_dir)
    copies: list[Copy] = []
    for n, meta in enumerate(cands, 1):
        item = meta["identifier"]
        try:
            pages = item_pages(ia, item, cache_dir)
        except httpx.HTTPError as e:
            log.error("%s: OCR not fetched (%s); left out", item, e)
            continue
        if not pages:
            log.debug("%s: no page OCR", item)
            continue
        c = identify_copy(item, pages, ours, meta)
        if c is None or c.hits < 5:
            log.debug("%s: no PG volume matched", item)
            continue
        copies.append(c)
        save_diffs(c, cache_dir)
        log.info("[%d/%d] %s -> %s hits %d agree %.2f shift %d", n, len(cands), item,
                  c.volume, c.hits, c.agree, c.shift)
    copies.sort(key=lambda c: (c.volume, not c.ok, -c.hits, c.item))
    write_table(copies, table)
    log.info("%d copies matched %d volumes (%d ok) -> %s", len(copies),
             len({c.volume for c in copies}), sum(c.ok for c in copies), table)
    return copies


def write_table(copies: list[Copy], table: Path = TABLE) -> None:
    with table.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, TABLE_FIELDS, lineterminator="\n")
        w.writeheader()
        for c in copies:
            w.writerow(c.row())


def read_table(table: Path = TABLE) -> list[dict]:
    with table.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# A leaf for every page that needs OCR
# ---------------------------------------------------------------------------


@dataclass
class Leaf:
    item: str
    leaf: int
    cols: tuple[int, int]
    supported: bool         # its own running head prints one of its columns
    greek: int              # Greek letters in the copy's OCR of it
    before: bool            # our text confirms the copy's map before it (``trust``)
    after: bool             # and after it

    @property
    def trusted(self) -> bool:
        return (self.before and self.after) or (self.supported and (self.before or self.after))

    def rank(self) -> tuple:
        return (self.trusted, self.greek >= GREEK_LETTERS, self.supported,
                self.before + self.after, self.greek)


def leaves_of(item: str, pages: list[str], diffs: dict[int, list[int]]
              ) -> dict[int, list[Leaf]]:
    """Every mapped leaf of a copy, by the page (first column) it prints."""
    from scripts.ingest import _ogpg_columns as cols

    out: dict[int, list[Leaf]] = defaultdict(list)
    for leaf, span in column_map(pages).items():
        supported = bool(cols.head_numbers(pages[leaf]) & set(span))
        out[page_of(span[0])].append(Leaf(item, leaf, span, supported, greek_letters(pages[leaf]),
                                          *trust(diffs, leaf, supported)))
    return out


def locate(ia: Archive, pages_file: Path, cache_dir: Path = CACHE_DIR,
           table: Path = TABLE) -> list[dict]:
    """Choose a leaf for every page that needs OCR -> ``cache_dir/pages.jsonl``.

    Every copy of the volume is considered, but only its trusted leaves
    (``trust``).  Among those, a leaf with Greek in its OCR, then one whose
    head prints its column, then the best agreement wins.  A page with no
    trusted leaf is listed with no leaf, and the number of untrusted ones.
    """
    copies = defaultdict(list)
    for row in read_table(table):
        copies[row["volume"]].append(row)
    wanted = [json.loads(line) for line in pages_file.read_text(encoding="utf-8").splitlines()]
    wanted = [r for r in wanted if r["needs_ocr"]]
    by_vol: dict[str, dict[int, list[Leaf]]] = {}
    out = []
    for r in wanted:
        vol = r["volume"]
        if vol not in by_vol:
            found: dict[int, list[Leaf]] = defaultdict(list)
            for row in copies.get(vol, []):
                item = row["ia_id"]
                pages = item_pages(ia, item, cache_dir)
                for page, ls in leaves_of(item, pages or [], load_diffs(item, cache_dir)).items():
                    found[page].extend(ls)
            by_vol[vol] = found
        options = by_vol[vol].get(r["cols"][0], [])
        trusted = [lf for lf in options if lf.trusted]
        best = max(trusted, key=Leaf.rank, default=None)
        rec = {**{k: r[k] for k in ("volume", "work", "cols", "cause")}, "ia_id": None}
        if best is not None:
            rec.update(ia_id=best.item, leaf=best.leaf, supported=best.supported,
                       ia_greek=best.greek, both_sides=best.before and best.after,
                       options=len(trusted))
        else:
            rec["untrusted"] = len(options)
        out.append(rec)
    (cache_dir / "pages.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")
    placed = [r for r in out if r["ia_id"]]
    log.info("%d pages need OCR: %d have a leaf (%d with Greek in its OCR, %d head-checked), "
             "%d none -> %s", len(out), len(placed),
             sum(r["ia_greek"] >= GREEK_LETTERS for r in placed),
             sum(r["supported"] for r in placed), len(out) - len(placed),
             cache_dir / "pages.jsonl")
    return out


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def _jp2_names(ia: Archive, item: str, cache_dir: Path = CACHE_DIR) -> list[str]:
    """The JPEG 2000 files of an item's ``_jp2.zip``, in leaf order (cached)."""
    d = cache_dir / "jp2"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{item}.json"
    if f.exists():
        return json.loads(f.read_text())
    r = ia.get(f"{IA}/download/{item}/{item}_jp2.zip/")
    names = sorted(set(re.findall(r'href="[^"]*?([^"/]+\.jp2)"', r.text))) if r.is_success else []
    f.write_text(json.dumps(names))
    return names


def _leaf_numbers(ia: Archive, item: str, cache_dir: Path = CACHE_DIR) -> list[int]:
    """The leaf number of each page of an item's OCR, in order (cached).

    From ``_scandata.xml``: its pages in order, without those left out of the
    access formats.  The OCR's page index, the JPEG 2000 file names and IIIF
    (``$n``) all follow it, but an item's leaves may start at 0 or at 1.
    """
    d = cache_dir / "leafnums"
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{item}.json"
    if f.exists():
        return json.loads(f.read_text())
    r = ia.get(f"{IA}/download/{item}/{item}_scandata.xml")
    nums = []
    if r.is_success:
        for m in re.finditer(r'<page leafNum="(\d+)"(.*?)</page>', r.text, re.S):
            if "<addToAccessFormats>false" not in m.group(2):
                nums.append(int(m.group(1)))
    f.write_text(json.dumps(nums))
    return nums


def image_url(ia: Archive, item: str, position: int, pages: int,
              cache_dir: Path = CACHE_DIR) -> tuple[str, int] | None:
    """(URL, leaf number) of the image of the page at ``position`` in the
    item's OCR (``pages`` long): its JPEG 2000 from the item's zip, else IIIF's
    JPEG.  None when the leaf can't be told for certain."""
    nums = _leaf_numbers(ia, item, cache_dir)
    names = _jp2_names(ia, item, cache_dir)
    if len(nums) == pages:
        leaf = nums[position]
        by_num = {int(m.group(1)): n for n in names if (m := re.search(r"_(\d+)\.jp2$", n))}
        if leaf in by_num:
            return f"{IA}/download/{item}/{item}_jp2.zip/{item}_jp2%2F{by_num[leaf]}", leaf
        return f"https://iiif.archive.org/iiif/{item}${leaf}/full/max/0/default.jpg", leaf
    if len(names) == pages:      # no usable scandata: the zip's files in order
        return f"{IA}/download/{item}/{item}_jp2.zip/{item}_jp2%2F{names[position]}", position
    return None


def fetch(ia: Archive, cache_dir: Path = CACHE_DIR, images_dir: Path = IMAGES_DIR,
          volumes: set[str] | None = None, limit: int | None = None) -> int:
    """Download the chosen leaf of every located page (idempotent)."""
    recs = [json.loads(line) for line in
            (cache_dir / "pages.jsonl").read_text(encoding="utf-8").splitlines()]
    recs = [r for r in recs if r["ia_id"] and (not volumes or r["volume"] in volumes)]
    leaves = {}
    done = 0
    for r in recs:
        if limit is not None and done >= limit:
            break
        vdir = images_dir / r["volume"]
        vdir.mkdir(parents=True, exist_ok=True)
        stem = f"c{r['cols'][0]:04d}"
        if any(vdir.glob(f"{stem}.*")):
            continue
        item = r["ia_id"]
        if item not in leaves:
            leaves[item] = len(item_pages(ia, item, cache_dir) or [])
        found = image_url(ia, item, r["leaf"], leaves[item], cache_dir)
        if found is None:
            log.error("%s %s: can't tell which image of %s is page %d of its OCR; skipped",
                      r["volume"], stem, item, r["leaf"])
            continue
        url, leaf_num = found
        resp = ia.get(url)
        if not resp.is_success:
            log.error("%s %s: HTTP %d from %s", r["volume"], stem, resp.status_code, url)
            continue
        ext = ".jp2" if url.endswith(".jp2") else ".jpg"
        tmp = vdir / f"{stem}{ext}.part"
        tmp.write_bytes(resp.content)
        tmp.rename(vdir / f"{stem}{ext}")
        with (vdir / "manifest.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"file": f"{stem}{ext}", "cols": r["cols"], "work": r["work"],
                                "ia_id": item, "page": r["leaf"], "leaf": leaf_num,
                                "url": url}) + "\n")
        done += 1
        if done % 100 == 0:
            log.info("fetched %d pages", done)
    log.info("fetched %d pages into %s", done, images_dir)
    return done


# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m scripts.ogpg_images",
                                description=__doc__.split("\n\n")[0])
    p.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    p.add_argument("--cache-dir", type=Path, default=CACHE_DIR)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("discover", help="find candidate items")
    sub.add_parser("identify", help="identify the candidates' volumes -> the table")
    lo = sub.add_parser("locate", help="choose a leaf for every page that needs OCR")
    lo.add_argument("--pages", type=Path, required=True,
                    help="scripts.ogpg_coverage --scans --pages output")
    fe = sub.add_parser("fetch", help="download the located pages' images")
    fe.add_argument("--images-dir", type=Path, default=IMAGES_DIR)
    fe.add_argument("--volume", action="append", help="only these volumes (vol-075)")
    fe.add_argument("--limit", type=int, help="at most this many pages")
    args = p.parse_args(argv)
    setup_logging()
    ia = Archive()
    if args.cmd == "discover":
        discover(ia, args.cache_dir)
    elif args.cmd == "identify":
        identify(ia, args.raw_dir, args.cache_dir)
    elif args.cmd == "locate":
        locate(ia, args.pages, args.cache_dir)
    elif args.cmd == "fetch":
        fetch(ia, args.cache_dir, args.images_dir,
              set(args.volume) if args.volume else None, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
