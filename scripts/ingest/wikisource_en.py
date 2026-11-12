"""
Ingestor for English translations on English Wikisource (#653).

Source: https://en.wikisource.org
Format: the rendered HTML of a page (``action=parse``), since the text is
        transcluded from proofread ``Page:`` scans and the page's own wikitext
        holds only ``<pages … />`` tags
License: CC-BY-SA 4.0 (Wikisource); the printed editions are public domain

Each page is listed in :data:`PAGES` with the revision it is parsed at; the
response is cached in ``data/raw/_cache/wikisource-en/`` with the revisions of
the ``Page:`` pages it transcludes, so the source regenerates offline.  The
existing Greek and Georgian Wikisource ingestors read wikitext and their
pages' own markup, so none of their parsing applies here.

So far one page: Alexander Wylie's translation (1855) of the Xi'an stele
(781), as reprinted in Paul Carus (ed.), *The Nestorian Monument* (Open Court
1909).  Only the translation is taken; the book's essays are modern secondary
material, and its "Original Text" subpage is the Chinese inscription
(``wikisource-lzh`` has the stele from zh.wikisource).

Units and editorial material (#236)
-----------------------------------
- ``Stele``: the page heading ("Translation of the Nestorian Inscription. By
  A. Wylie."), wholly ``title``;
- ``Stele.1``: the stele's own title (景教流行中國碑頌并序 …), then
  ``Stele.2`` … one unit per paragraph of the preface;
- ``Ode``: "Ode." (the stele's 詞曰), then ``Ode.1`` … one unit per stanza,
  its lines joined by spaces;
- ``Colophon.1`` …: the date, the scribe, and Wylie's renderings of the
  Syriac and Chinese subscriptions; each of his bracketed remarks ("[The two
  lines of Syriac …]") is a ``note`` span starting the unit it introduces;
- Wylie's footnotes stay where their markers are, in brackets, as ``note``
  spans.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx
from bs4 import BeautifulSoup, NavigableString, Tag

from patristica.models import Work
from scripts.ingest._common import require_network

log = logging.getLogger(__name__)

SOURCE_ID = "wikisource-en"

_API = "https://en.wikisource.org/w/api.php"
_USER_AGENT = "Patristica/0.1 (https://patristica.app; corpus ingest)"
_THROTTLE_S = 2.0
_last_request = 0.0


@dataclass(frozen=True)
class Page:
    slug: str
    title: str
    revid: int
    work_title: str
    author: str
    edition: str
    translation_of: str | None
    date_composed: int
    date_range: tuple[int, int]
    date_confidence: str
    tradition: str
    units: int  # expected unit count, a check on the parse


NESTORIAN_STELE = Page(
    slug="nestorian-monument-wylie",
    title=("The Nestorian Monument: An Ancient Record of Christianity in China/"
           "Translation of the Nestorian Inscription"),
    revid=11724320,
    work_title=("Tablet Eulogizing the Propagation of the Illustrious Religion in China "
                "(Xi'an Stele)"),
    author="Jingjing",
    edition=("Translated by Alexander Wylie (1855), as reprinted in Paul Carus (ed.), "
             "The Nestorian Monument: An Ancient Record of Christianity in China "
             "(Chicago: Open Court, 1909), 11–20; English Wikisource transcription"),
    # The Chinese stele on zh.wikisource (#650).
    translation_of=None,  # wikisource-lzh/xian-stele once its anchor cut is decided
    date_composed=781,
    date_range=(781, 781),
    date_confidence="established",
    tradition="syriac",
    units=40,
)

PAGES: tuple[Page, ...] = (NESTORIAN_STELE,)


# ---------------------------------------------------------------------------
# HTML → text
# ---------------------------------------------------------------------------

class _Text:
    """A unit's text under construction: whitespace collapsed, editorial spans tracked."""

    def __init__(self) -> None:
        self.chars: list[str] = []
        self.spans: list[list] = []
        self._space = False

    def space(self) -> None:
        self._space = True

    def add(self, text: str, kind: str | None = None) -> None:
        start: int | None = None
        for ch in text:
            if ch.isspace() or ch == "​":
                self._space = self._space or ch != "​"
                continue
            if self._space and self.chars:
                self.chars.append(" ")
            self._space = False
            if start is None:
                start = len(self.chars)
            self.chars.append(ch)
        if kind is not None and start is not None:
            self.spans.append([start, len(self.chars), kind])

    def extend(self, other: _Text, kind: str | None = None) -> None:
        """Append *other*'s text (and its spans), all of it marked *kind* if given."""
        if not other.chars:
            return
        if self.chars:
            self.chars.append(" ")
        offset = len(self.chars)
        self.chars.extend(other.chars)
        if kind is not None:
            self.spans.append([offset, len(self.chars), kind])
        else:
            self.spans.extend([s + offset, e + offset, k] for s, e, k in other.spans)
        self._space = False

    @property
    def text(self) -> str:
        return "".join(self.chars)

    def unit(self, ref: str) -> dict:
        rec: dict = {"ref": ref, "text": self.text}
        if self.spans:
            rec["editorial"] = self.spans
        return rec


def _classes(el: Tag) -> list[str]:
    return list(el.get("class") or [])


def _render(node: Tag, out: _Text, notes: dict[str, str]) -> None:
    """*node*'s text into *out*: page numbers and styles dropped, footnotes as notes."""
    for child in node.children:
        if isinstance(child, NavigableString):
            if type(child) is NavigableString:  # not a Comment
                out.add(str(child))
            continue
        if not isinstance(child, Tag) or child.name in ("style", "link"):
            continue
        if "ws-pagenum" in _classes(child):
            continue
        if child.name == "br":
            out.space()
        elif child.name == "sup" and "reference" in _classes(child):
            target = child.a["href"].lstrip("#") if child.a else ""
            if target not in notes:
                raise ValueError(f"footnote marker {target!r} has no note")
            out.space()
            out.add(f"[{notes[target]}]", "note")
            out.space()
        else:
            _render(child, out, notes)


def _footnotes(soup: BeautifulSoup) -> dict[str, str]:
    """``cite_note-N`` → the note's text."""
    notes: dict[str, str] = {}
    for li in soup.select("ol.references > li"):
        text = _Text()
        _render(li.select_one(".reference-text"), text, {})
        notes[li["id"]] = text.text
    return notes


def _stanzas(poem: Tag, notes: dict[str, str]) -> list[_Text]:
    """A ``div.poem``'s stanzas, split at blank lines.

    Wylie's ode is in quatrains (one of six lines), and the transcription's
    page breaks fall between them, so a stanza never runs from one
    ``div.poem`` into the next.
    """
    stanzas: list[_Text] = []
    for p in poem.find_all("p"):
        lines: list[_Text] = [_Text()]
        for child in p.children:
            if isinstance(child, Tag) and child.name == "br":
                lines.append(_Text())
            elif isinstance(child, Tag):
                _render(child, lines[-1], notes)
            elif type(child) is NavigableString:
                lines[-1].add(str(child))
        current = _Text()
        for line in lines:
            if line.chars:
                current.extend(line)
            elif current.chars:
                stanzas.append(current)
                current = _Text()
        if current.chars:
            stanzas.append(current)
    return stanzas


def _blocks(soup: BeautifulSoup, notes: dict[str, str]) -> list[tuple[str, _Text]]:
    """The text's blocks in order, each ("p", text) or ("stanza", text)."""
    body = soup.select_one("div.prp-pages-output")
    if body is None:
        raise ValueError("no transcluded pages in the parsed page")
    blocks: list[tuple[str, _Text]] = []
    for el in body.find_all(["p", "div"]):
        if el.find_parent("div", class_="poem"):
            continue
        if el.name == "div" and "poem" in _classes(el):
            blocks.extend(("stanza", text) for text in _stanzas(el, notes))
            continue
        if el.name == "div" and (el.find(["p", "div"]) or "tiInherit" not in _classes(el)
                                 or "wst-center" in _classes(el)):
            continue
        text = _Text()
        _render(el, text, notes)
        if text.chars:
            blocks.append(("p", text))
    return blocks


def _is_remark(text: _Text) -> bool:
    """A bracketed remark of Wylie's or the editor's: "[Then follows:]"."""
    return text.text.startswith("[") and text.text.endswith("]")


def parse_stele(html: str, page: Page) -> list[dict]:
    """Wylie's translation of the Xi'an stele as raw units."""
    soup = BeautifulSoup(html, "html.parser")
    notes = _footnotes(soup)
    blocks = _blocks(soup, notes)

    def take_p(expect: str | None = None) -> _Text:
        kind, text = blocks.pop(0)
        if kind != "p" or (expect is not None and text.text != expect):
            raise ValueError(f"{page.slug}: expected {expect or 'a paragraph'}, "
                             f"found {kind} {text.text[:60]!r}")
        return text

    units: list[dict] = []
    heading = take_p("TRANSLATION OF THE NESTORIAN INSCRIPTION.")
    heading.extend(take_p("BY A. WYLIE."))
    units.append({"ref": "Stele", "text": heading.text,
                  "editorial": [[0, len(heading.text), "title"]]})

    n = 0
    while blocks and not (blocks[0][0] == "p" and blocks[0][1].text == "ODE."):
        n += 1
        units.append(take_p().unit(f"Stele.{n}"))
    units.append(take_p("ODE.").unit("Ode"))

    n = 0
    while blocks and blocks[0][0] == "stanza":
        n += 1
        units.append(blocks.pop(0)[1].unit(f"Ode.{n}"))

    # The colophon: a plain line stands alone; a bracketed remark starts a unit
    # that takes the lines it introduces.
    n = 0
    current: _Text | None = None
    for kind, text in blocks:
        if kind != "p":
            raise ValueError(f"{page.slug}: a stanza after the ode: {text.text[:60]!r}")
        if current is not None and not _is_remark(text):
            current.extend(text)
            continue
        if current is not None:
            n += 1
            units.append(current.unit(f"Colophon.{n}"))
            current = None
        if _is_remark(text):
            current = _Text()
            current.extend(text, "note")
        else:
            n += 1
            units.append(text.unit(f"Colophon.{n}"))
    if current is not None:
        n += 1
        units.append(current.unit(f"Colophon.{n}"))

    if len(units) != page.units:
        raise ValueError(f"{page.slug}: {len(units)} units, expected {page.units}")
    return units


_PARSERS = {NESTORIAN_STELE.slug: parse_stele}


# ---------------------------------------------------------------------------
# Fetch and write
# ---------------------------------------------------------------------------

def _get(params: dict[str, str]) -> dict:
    global _last_request
    for attempt in range(5):
        time.sleep(max(0.0, _last_request + _THROTTLE_S - time.monotonic()))
        _last_request = time.monotonic()
        resp = httpx.get(_API, params={**params, "format": "json", "formatversion": "2"},
                         headers={"User-Agent": _USER_AGENT}, timeout=60)
        if resp.status_code == 429 or "too many requests" in resp.text[:500].lower():
            time.sleep(30 * (attempt + 1))
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(f"English Wikisource kept refusing {params}")


def _fetch(page: Page, cache_dir: Path) -> str:
    """The page's rendered HTML at its pinned revision (cached)."""
    path = cache_dir / f"{page.slug}-{page.revid}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["html"]
    require_network(f"fetching {page.title} from English Wikisource")
    parsed = _get({"action": "parse", "oldid": str(page.revid), "prop": "text|templates"})["parse"]
    if parsed["title"] != page.title or parsed["revid"] != page.revid:
        raise ValueError(f"{page.slug}: revision {page.revid} is not of {page.title!r}")
    scans = sorted(t["title"] for t in parsed.get("templates", [])
                   if t["title"].startswith("Page:"))
    revisions: dict[str, int] = {}
    if scans:
        found = _get({"action": "query", "prop": "revisions", "rvprop": "ids",
                      "titles": "|".join(scans)})["query"]["pages"]
        revisions = {p["title"]: p["revisions"][0]["revid"] for p in found}
    path.parent.mkdir(parents=True, exist_ok=True)
    cached = {"title": page.title, "revid": page.revid, "page_revisions": revisions,
              "html": parsed["text"]}
    path.write_text(json.dumps(cached, ensure_ascii=False, indent=1), encoding="utf-8")
    return parsed["text"]


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
        language="eng",
        tradition=page.tradition,  # type: ignore[arg-type]
        license="cc-by-sa-4.0",
        provenance_url=(f"https://en.wikisource.org/w/index.php?title="
                        f"{quote(page.title.replace(' ', '_'))}&oldid={page.revid}"),
        edition=page.edition,
        translation_of=page.translation_of,
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
    log.info("English Wikisource: %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
