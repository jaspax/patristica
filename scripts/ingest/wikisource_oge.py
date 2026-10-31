"""
Ingestor for the Old Georgian texts on Georgian Wikisource (#513, part of #222).

Source: https://ka.wikisource.org
Format: MediaWiki wikitext, one page per work
License: CC-BY-SA 4.0 (Wikisource); see each page's base edition below

The two in-period Old Georgian works the survey of #222 found on ka.wikisource:

- **შუშანიკის წამება**, the *Martyrdom of Shushanik* by Iakob Tsurtaveli
  (written 475/484). The page names no edition. It was created on the
  multilingual Wikisource by George Mel in June 2009 and imported to
  ka.wikisource in 2024. Its division into twenty chapters (the page's
  ``პუნქტი`` 1–20, with Roman numerals VIII–XX in ``კრიტერიუმი``) and its
  text are those of Ts. Kurtsikidze's edition: *Monuments of Old Georgian
  Hagiographic Literature* I (Tbilisi 1963), itself after I. Abuladze's of
  1938, reprinted with small corrections in 1978 (its "ტექსტისათვის" note).
  The page lacks the 1978 reprint's opening sentence and keeps some later
  spellings (ქვეყანა beside ქუეყანა), so it is not that reprint itself.
- **მოქცევაჲ ქართლისაჲ**, the *Conversion of Kartli* in the Shatberdi codex
  (compiled in the 9th–10th century; codex copied 973/976). The page lists
  Takaishvili's 1890 edition and an amsi.ge PDF as its publications, but its
  text is the amsi.ge one, not Takaishvili's (Takaishvili prints ოძრახე,
  ციხჱ-დიდი, სარკინისაჲ, a lacuna after შეშჭამდეს; the page ოძრაჴე, ციხჱ დიდი
  სარკინისაჲ, none), with bracketed editorial chapter numbers ``[თავი ა]``:
  a modern edition, probably the 1963 volume above.

Both pages are pinned to a revision (:data:`PAGES`), fetched by revision id
and cached in ``data/raw/_cache/wikisource-oge/``. (``_common.download_file``
sends no User-Agent, which Wikimedia refuses with 403.)

Text
----
Only the text itself is kept: the page's frame (Wikisource's modern-Georgian
note, images, the list of publications, categories, HTML and wiki markup) is
dropped. A source paragraph is a run of lines between blank lines; the
Conversion's lines keep the print's line breaks, which are joined with a space.
Old Georgian letters (ჱ, ჲ, ჳ, ჴ, ჵ) are kept as given.

Editorial material (#236) is marked, not stripped:

- chapter headings are units of their own, wholly ``heading``; Shushanik's
  carry the edition's Roman numeral, the Conversion's the page's heading
  (``[თავი ა]``, ``თავი დ აღწერილი მის[ი]ვე სალომე უჟარმელისაჲ``);
- in the Conversion, the editor's restorations ``[…]`` and expansions
  ``(…)`` (``არს(ოკ)``, ``(სიტყუაჲ)``) are ``supplement``s, and runs of dots
  (``მგა....:``, ``დღესა ... შაფათსა``) are ``lacuna``s. An unbalanced
  bracket or parenthesis stays plain text. Shushanik has no such marks; its
  one ``…`` (``„მტკი...“ და დადუმნა``) is the speaker breaking off, so text.

Canonical references
--------------------
``Shushanik.{chapter}.{n}`` and ``MoktsKartl.{chapter}.{n}``, with the chapter
heading at ``{prefix}.{chapter}``. Shushanik's chapters are the edition's
(1–20). The Conversion's take the heading's Georgian numeral (``თავი ვ`` → 6)
and an unnumbered section the next number after the previous one: the page
numbers ა–დ, ვ–ჱ and იგ, and its four unnumbered sections between ჱ and იგ
become 9–12, so the numbering runs to 15 with no 5 (there is no თავი ე).
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from patristica.models import Work
from scripts.ingest._common import require_network

log = logging.getLogger(__name__)

SOURCE_ID = "wikisource-oge"

_API = "https://ka.wikisource.org/w/api.php"
_USER_AGENT = "Patristica/0.1 (https://patristica.app; corpus ingest)"
_THROTTLE_S = 6.0  # between requests: the API rate-limits hard
_last_request = 0.0


@dataclass(frozen=True)
class Page:
    slug: str
    title: str  # the Wikisource page
    revid: int  # the revision ingested
    prefix: str  # ref prefix
    chapters: int  # expected number of chapters (Shushanik) or sections (Conversion)
    work_title: str
    author: str | None
    date_composed: int
    date_range: tuple[int, int]
    date_confidence: str
    edition: str


SHUSHANIK = Page(
    slug="shushanik",
    title="შუშანიკის წამება",
    revid=78408,
    prefix="Shushanik",
    chapters=20,
    work_title="წამებაჲ წმიდისა შუშანიკისი დედოფლისაჲ (Martyrdom of Shushanik)",
    author="იაკობ ცურტაველი",
    date_composed=480,
    date_range=(475, 484),
    date_confidence="approximate",
    edition=("Georgian Wikisource, «შუშანიკის წამება», revision 78408 (2026-09-28); the page "
             "names no edition: its text and twenty chapters are those of Ts. Kurtsikidze's in "
             "ძველი ქართული აგიოგრაფიული ლიტერატურის ძეგლები I (Tbilisi 1963), after "
             "I. Abuladze (1938)"),
)

CONVERSION = Page(
    slug="moktsevay-kartlisay-shatberdi",
    title='"მოქცევაჲ ქართლისაჲ" (შატბერდისეული ვერსია)',
    revid=69216,
    prefix="MoktsKartl",
    chapters=15,
    work_title="მოქცევაჲ ქართლისაჲ, შატბერდის ვერსია (Conversion of Kartli, Shatberdi version)",
    author=None,
    date_composed=900,
    date_range=(800, 976),
    date_confidence="approximate",
    edition=("Georgian Wikisource, «\"მოქცევაჲ ქართლისაჲ\" (შატბერდისეული ვერსია)», revision "
             "69216 (2025-02-12); text of the Shatberdi codex (973/976) as on amsi.ge, a modern "
             "edition (not Takaishvili's of 1890), probably ძველი ქართული აგიოგრაფიული "
             "ლიტერატურის ძეგლები I (Tbilisi 1963)"),
)

PAGES: tuple[Page, ...] = (SHUSHANIK, CONVERSION)

ROMAN = ("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII", "XIII",
         "XIV", "XV", "XVI", "XVII", "XVIII", "XIX", "XX")

# Georgian letter numerals (the old alphabetic values) up to 99.
_GEO_UNITS = "აბგდევზჱთ"
_GEO_TENS = "იკლმნჲოპჟ"


def georgian_numeral(numeral: str) -> int:
    """"ა" → 1, "ვ" → 6, "ჱ" → 8, "იგ" → 13, "კ" → 20 (up to 99)."""
    value = 0
    rest = numeral
    if rest and rest[0] in _GEO_TENS:
        value += 10 * (_GEO_TENS.index(rest[0]) + 1)
        rest = rest[1:]
    if rest and rest[0] in _GEO_UNITS:
        value += _GEO_UNITS.index(rest[0]) + 1
        rest = rest[1:]
    if rest or not value:
        raise ValueError(f"not a Georgian numeral: {numeral!r}")
    return value


# ---------------------------------------------------------------------------
# Wikitext → plain text
# ---------------------------------------------------------------------------

def clean_markup(text: str) -> str:
    """Wikitext without links to files and categories, HTML tags and bold/italic quotes.

    Line breaks are kept; ``<br>`` becomes a space. A backslash is typing noise
    (the Conversion's ``მიზეზი\\სათჳს``) and is dropped.
    """
    text = text.replace("\\", "")
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"\[\[(?:File|Image|ფაილი|კატეგორია|Category):[^\]]*\]\]", "", text)
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("'''", "").replace("''", "")
    return text


def paragraphs(text: str) -> list[str]:
    """Blank-line separated paragraphs, each with its lines joined and spaces collapsed."""
    out: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        line = re.sub(r"\s+", " ", block).strip()
        if line and not re.fullmatch(r"-{3,}", line):
            out.append(line)
    return out


_SUPPLEMENT = re.compile(r"\[[^\[\]]+\]|\([^()]{1,40}\)")
_LACUNA = re.compile(r"\.{3,}")


def mark_conversion(text: str) -> list[list[Any]]:
    """Editorial spans of a Conversion paragraph: supplements and lacunae."""
    spans = [[m.start(), m.end(), "supplement"] for m in _SUPPLEMENT.finditer(text)]
    for m in _LACUNA.finditer(text):
        if not any(s <= m.start() < e for s, e, _ in spans):
            spans.append([m.start(), m.end(), "lacuna"])
    return sorted(spans)


def _unit(ref: str, text: str, spans: list[list[Any]] | None = None) -> dict[str, Any]:
    unit: dict[str, Any] = {"ref": ref, "text": text}
    if spans:
        unit["editorial"] = spans
    return unit


def _heading(ref: str, text: str) -> dict[str, Any]:
    return _unit(ref, text, [[0, len(text), "heading"]])


# ---------------------------------------------------------------------------
# Shushanik: one {{ბლოკი|პუნქტი=N|…|ტექსტი=…}} template per chapter
# ---------------------------------------------------------------------------

_BLOCK = re.compile(r"\{\{ბლოკი\s*\|(.*?)\}\}", re.S)


def _template_params(body: str) -> dict[str, str]:
    """Named parameters of a template body (no nested templates)."""
    params: dict[str, str] = {}
    for part in re.split(r"\n?\|(?=[^\s=|]+\s*=)", "|" + body):
        if "=" not in part:
            continue
        name, _, value = part.partition("=")
        params[name.strip().lstrip("|")] = value
    return params


def parse_shushanik(wikitext: str, page: Page = SHUSHANIK) -> list[dict[str, Any]]:
    """The Martyrdom's chapters: a Roman-numeral heading each, then its paragraphs."""
    units: list[dict[str, Any]] = []
    blocks = _BLOCK.findall(wikitext)
    for expected, body in enumerate(blocks, 1):
        params = _template_params(body)
        chapter = int(params.get("პუნქტი", "0").strip() or 0)
        if chapter != expected:
            raise ValueError(f"{page.slug}: block {expected} is numbered {chapter}")
        paras = paragraphs(clean_markup(params.get("ტექსტი", "")))
        if not paras:
            raise ValueError(f"{page.slug}: chapter {chapter} has no text")
        ref = f"{page.prefix}.{chapter}"
        units.append(_heading(ref, ROMAN[chapter - 1]))
        units.extend(_unit(f"{ref}.{n}", p) for n, p in enumerate(paras, 1))
    if len(blocks) != page.chapters:
        raise ValueError(f"{page.slug}: {len(blocks)} chapters, expected {page.chapters}")
    return units


# ---------------------------------------------------------------------------
# Conversion of Kartli: ====<center>'''[თავი ა]<br>title'''</center>==== sections
# ---------------------------------------------------------------------------

_SECTION = re.compile(r"^====(.*?)====\s*$", re.M)
_CHAPTER_NO = re.compile(r"^\[?თავი ([ა-ჰ]+)\]?")


def parse_conversion(wikitext: str, page: Page = CONVERSION) -> list[dict[str, Any]]:
    """The Conversion's sections: the page's heading, then the section's paragraphs."""
    _, sep, text = wikitext.partition("==ტექსტი==")
    if not sep:
        raise ValueError(f"{page.slug}: no ==ტექსტი== section")
    text = re.sub(r"\[\[(?:კატეგორია|Category):[^\]]*\]\]", "", text)
    parts = _SECTION.split(text)
    if paragraphs(clean_markup(parts[0])):
        raise ValueError(f"{page.slug}: text before the first chapter heading")
    units: list[dict[str, Any]] = []
    chapter = 0
    for heading_raw, body in zip(parts[1::2], parts[2::2]):
        heading = re.sub(r"\s+", " ", clean_markup(heading_raw)).strip()
        m = _CHAPTER_NO.match(heading)
        number = georgian_numeral(m.group(1)) if m else chapter + 1
        if number <= chapter:
            raise ValueError(f"{page.slug}: chapter {heading!r} ({number}) after {chapter}")
        chapter = number
        paras = paragraphs(clean_markup(body))
        if not paras:
            raise ValueError(f"{page.slug}: section {heading!r} has no text")
        ref = f"{page.prefix}.{chapter}"
        units.append(_heading(ref, heading))
        units.extend(_unit(f"{ref}.{n}", p, mark_conversion(p)) for n, p in enumerate(paras, 1))
    if chapter != page.chapters:
        raise ValueError(f"{page.slug}: last chapter {chapter}, expected {page.chapters}")
    return units


_PARSERS = {SHUSHANIK.slug: parse_shushanik, CONVERSION.slug: parse_conversion}


# ---------------------------------------------------------------------------
# Fetch and write
# ---------------------------------------------------------------------------

def _fetch(page: Page, cache_dir: Path) -> str:
    """The page's wikitext at its pinned revision (cached)."""
    path = cache_dir / f"{page.slug}-{page.revid}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["wikitext"]
    require_network(f"fetching {page.title} from Georgian Wikisource")
    global _last_request
    time.sleep(max(0.0, _last_request + _THROTTLE_S - time.monotonic()))
    _last_request = time.monotonic()
    resp = httpx.get(_API, params={
        "action": "query", "prop": "revisions", "revids": str(page.revid),
        "rvprop": "content|ids|timestamp", "rvslots": "main",
        "format": "json", "formatversion": "2",
    }, headers={"User-Agent": _USER_AGENT}, timeout=60)
    resp.raise_for_status()
    found = resp.json()["query"]["pages"][0]
    revision = found["revisions"][0]
    if found["title"] != page.title or revision["revid"] != page.revid:
        raise ValueError(f"{page.slug}: revision {page.revid} is not of {page.title!r}")
    wikitext = revision["slots"]["main"]["content"]
    path.parent.mkdir(parents=True, exist_ok=True)
    cached = {"title": page.title, "revid": page.revid, "timestamp": revision["timestamp"],
              "wikitext": wikitext}
    path.write_text(json.dumps(cached, ensure_ascii=False, indent=1), encoding="utf-8")
    return wikitext


def _work(page: Page) -> Work:
    return Work(
        work_id=f"{SOURCE_ID}/{page.slug}",
        source_id=SOURCE_ID,
        author=page.author,
        title=page.work_title,
        date_composed=page.date_composed,
        date_range=page.date_range,
        date_confidence=page.date_confidence,  # type: ignore[arg-type]
        genre="patristic",
        language="oge",
        tradition="georgian",
        license="cc-by-sa-4.0",
        provenance_url=f"https://ka.wikisource.org/w/index.php?title={quote(page.title)}&oldid={page.revid}",
        edition=page.edition,
        translation_of=None,
    )


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Fetch the pinned pages and write one raw JSON file per work."""
    cache_dir = output_dir / "_cache" / SOURCE_ID
    works: list[Work] = []
    for page in PAGES:
        out_path = output_dir / SOURCE_ID / f"{page.slug}.json"
        if out_path.exists() and not force:
            works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
            continue
        work = _work(page)
        units = _PARSERS[page.slug](_fetch(page, cache_dir), page)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"work": work.model_dump(), "paragraphs": units},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
        works.append(work)
    log.info("Georgian Wikisource (Old Georgian): %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
