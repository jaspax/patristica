"""
Ingestor for the Greek text of the holy canons on Greek Wikisource (#22).

Source: https://el.wikisource.org/wiki/Πύλη:Ιεροί_Κανόνες
Format: MediaWiki wikitext, one page per council, one ``==Κανὼν Α'==`` section per canon
License: CC-BY-SA 4.0 (Wikisource); the printed edition behind it is public domain

The Greek canons of the Apostles, the six councils that issued canons (Nicaea
I, Constantinople I, Ephesus, Chalcedon, Trullo, Nicaea II) and seven local
synods (Ancyra, Neocaesarea, Gangra, Antioch, Laodicea, Sardica, Carthage),
the councils whose English (NPNF 2.14) the corpus has as ``ecumenical/*``.

The text goes back to Rhalles–Potles, *Σύνταγμα τῶν θείων καὶ ἱερῶν κανόνων*
(Athens 1852–59), through the nektar site (the portal page's own account of
its provenance, which shares that edition's numbering and OCR-like typos).
In September 2012 the pages were given the prolegomena and some
interpretations of the *Pedalion* (1800), and some words of the canons were
changed without a source (Nicaea c. 20 lost ὁμοίως; Chalcedon c. 30 its
ending; Apostolic Canons 64–66 were put in the *Pedalion*'s order).  So each
page is pinned to its last revision before those edits (:data:`PAGES`), fetched
by revision id and cached in ``data/raw/_cache/wikisource-canons/``.

Text
----
Templates, categories, images, HTML and bold/italic quotes are stripped; a
section's first line is dropped when it repeats the heading.  A section that is
not a canon (Aristenus's epitome printed as Constantinople I "canon 8") is
listed in ``PAGES`` and left out, and a page's canon count is checked.  Should a
*Pedalion* "Ἑρμηνεία"/"Συμφωνία" ever appear, the section is cut there.

Canonical references
--------------------
The English works' prefixes, so the two read alike: ``Nicaea1.Canon.1`` is the
canon's heading ("Κανὼν Α'") and ``Nicaea1.Canon.1.1`` its first paragraph.
Canons are numbered by position (Rhalles–Potles numbering), and each heading
is written from that number: the headings of Trullo 90–99 are an image of the
koppa.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import httpx

from patristica.models import Work
from scripts.ingest._common import require_network

log = logging.getLogger(__name__)

SOURCE_ID = "wikisource-canons"

_API = "https://el.wikisource.org/w/api.php"
_USER_AGENT = "Patristica/0.1 (https://patristica.app; corpus ingest)"


@dataclass(frozen=True)
class Page:
    slug: str
    title: str  # the Wikisource page
    revid: int  # its last revision before the September 2012 edits
    prefix: str  # ref prefix, as in the English ecumenical/* work
    canons: int
    work_title: str
    date_composed: int
    date_range: tuple[int, int]
    date_confidence: str = "established"
    skip: dict[int, str] = field(default_factory=dict)  # section number → why it is not a canon


PAGES: tuple[Page, ...] = (
    Page("apostolic-canons", "Αποστολικοί Κανόνες", 24106, "CanApost", 85,
         "Κανόνες τῶν ἁγίων Ἀποστόλων (Apostolic Canons)", 380, (375, 400), "approximate"),
    Page("nicaea1", "Κανόνες Α΄ Οικουμενικής Συνόδου", 42676, "Nicaea1", 20,
         "Κανόνες τῆς ἐν Νικαίᾳ Α΄ Συνόδου (Canons of Nicaea I)", 325, (325, 325)),
    Page("const1", "Κανόνες Β΄ Οικουμενικής Συνόδου", 20607, "Const1", 7,
         "Κανόνες τῆς ἐν Κωνσταντινουπόλει Β΄ Συνόδου (Canons of Constantinople I)",
         381, (381, 382),
         skip={8: "Aristenus's epitome of canon 7 (12th c.), printed in Rhalles–Potles"}),
    Page("ephesus", "Κανόνες Γ΄ Οικουμενικής Συνόδου", 20608, "Ephesus", 8,
         "Κανόνες τῆς ἐν Ἐφέσῳ Γ΄ Συνόδου (Canons of Ephesus)", 431, (431, 431)),
    Page("chalcedon", "Κανόνες Δ΄ Οικουμενικής Συνόδου", 24548, "Chalcedon", 30,
         "Κανόνες τῆς ἐν Χαλκηδόνι Δ΄ Συνόδου (Canons of Chalcedon)", 451, (451, 451)),
    Page("trullo", "Κανόνες Πενθέκτης Οικουμενικής Συνόδου", 43911, "Trullo", 102,
         "Κανόνες τῆς ἐν Τρούλλῳ Πενθέκτης Συνόδου (Canons of the Council in Trullo)",
         692, (691, 692)),
    Page("nicaea2", "Κανόνες Ζ΄ Οικουμενικής Συνόδου", 43912, "Nicaea2", 22,
         "Κανόνες τῆς ἐν Νικαίᾳ Ζ΄ Συνόδου (Canons of Nicaea II)", 787, (787, 787)),
    Page("ancyra", "Κανόνες της εν Αγκύρα Συνόδου", 24550, "Ancyra", 25,
         "Κανόνες τῆς ἐν Ἀγκύρᾳ Συνόδου (Canons of Ancyra)", 314, (314, 314)),
    Page("neocaesarea", "Κανόνες της εν Νεοκαισαρεία Συνόδου", 29637, "Neocaesarea", 15,
         "Κανόνες τῆς ἐν Νεοκαισαρείᾳ Συνόδου (Canons of Neocaesarea)",
         315, (314, 320), "approximate"),
    Page("gangra", "Κανόνες της εν Γάγγρα Συνόδου", 24552, "Gangra", 21,
         "Κανόνες τῆς ἐν Γάγγρᾳ Συνόδου (Canons of Gangra)", 340, (340, 341), "approximate"),
    Page("antioch", "Κανόνες της εν Αντιοχεία Συνόδου", 29635, "Antioch", 25,
         "Κανόνες τῆς ἐν Ἀντιοχείᾳ Συνόδου (Canons of Antioch)", 341, (341, 341)),
    Page("laodicea", "Κανόνες της εν Λαοδικεία Συνόδου", 24554, "Laodicea", 60,
         "Κανόνες τῆς ἐν Λαοδικείᾳ Συνόδου (Canons of Laodicea)", 363, (343, 381), "approximate"),
    Page("sardica", "Κανόνες της εν Σαρδική Συνόδου", 29638, "Sardica", 21,
         "Κανόνες τῆς ἐν Σαρδικῇ Συνόδου (Canons of Sardica)", 343, (343, 344)),
    Page("carthage", "Κανόνες της εν Καρθαγένη Συνόδου", 29636, "Carthage", 133,
         "Κανόνες τῆς ἐν Καρθαγένῃ Συνόδου (Code of Canons of the African Church, Greek)",
         419, (393, 419)),
)

_SECTION = re.compile(r"^==\s*(.*?)\s*==\s*$", re.M)
_UNITS = ("", "Α", "Β", "Γ", "Δ", "Ε", "ΣΤ", "Ζ", "Η", "Θ")
_TENS = ("", "Ι", "Κ", "Λ", "Μ", "Ν", "Ξ", "Ο", "Π", "Ϟ")
_HUNDREDS = ("", "Ρ")
_COMMENTARY = frozenset({"ερμηνεια", "συμφωνια"})


def _bare(text: str) -> str:
    """Letters only, lower case, without accents: "Ἐ ρ μ η ν ε ί α." → "ερμηνεια"."""
    decomposed = unicodedata.normalize("NFD", text)
    return "".join(c for c in decomposed if c.isalpha() and not unicodedata.combining(c)).lower()


def greek_numeral(n: int) -> str:
    """1 → "Α'", 90 → "Ϟ'", 133 → "ΡΛΓ'" (up to 199)."""
    if not 0 < n < 200:
        raise ValueError(f"no Greek numeral for {n}")
    return f"{_HUNDREDS[n // 100]}{_TENS[n // 10 % 10]}{_UNITS[n % 10]}'"


def clean_line(line: str) -> str:
    """One wikitext line as plain text."""
    line = re.sub(r"\[\[(?:Κατηγορία|Εικόνα|File|Image):[^\]]*\]\]", "", line)
    line = re.sub(r"\{\{[^{}]*\}\}", "", line)
    line = re.sub(r"<[^>]+>", "", line)
    line = line.replace("'''", "").replace("''", "")
    line = re.sub(r"\s*\(\d+\)", "", line)  # footnote markers
    line = re.sub(r"^-{3,}$", "", line.strip())
    return re.sub(r"\s+", " ", line).strip()


def canon_paragraphs(heading: str, body: str) -> list[str]:
    """A canon section's paragraphs, without a repeated heading or later commentary."""
    paragraphs: list[str] = []
    for raw in body.split("\n"):
        line = clean_line(raw)
        if not line:
            continue
        if _bare(line) in _COMMENTARY:
            break
        if not paragraphs and _bare(line) == _bare(clean_line(heading)):
            continue
        paragraphs.append(line)
    return paragraphs


def parse_page(page: Page, wikitext: str) -> list[dict[str, str]]:
    """The page's canons as raw records: a heading per canon, then its paragraphs."""
    parts = _SECTION.split(wikitext)
    sections = list(zip(parts[1::2], parts[2::2]))
    records: list[dict[str, str]] = []
    n = 0
    for i, (heading, body) in enumerate(sections, 1):
        if i in page.skip:
            log.info("%s: section %d (%s) left out: %s", page.slug, i, heading, page.skip[i])
            continue
        n += 1
        paragraphs = canon_paragraphs(heading, body)
        if not paragraphs:
            raise ValueError(f"{page.slug}: canon {n} ({heading!r}) has no text")
        ref = f"{page.prefix}.Canon.{n}"
        records.append({"ref": ref, "text": f"Κανὼν {greek_numeral(n)}"})
        records.extend({"ref": f"{ref}.{k}", "text": p} for k, p in enumerate(paragraphs, 1))
    if n != page.canons:
        raise ValueError(
            f"{page.slug}: {n} canons at revision {page.revid}, expected {page.canons}")
    return records


def _fetch(page: Page, cache_dir: Path, force: bool) -> str:
    """The page's wikitext at its pinned revision (cached)."""
    path = cache_dir / f"{page.slug}-{page.revid}.json"
    if path.exists() and not force:
        return json.loads(path.read_text(encoding="utf-8"))["wikitext"]
    require_network(f"fetching {page.title} from Greek Wikisource")
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
        author=None,
        title=page.work_title,
        date_composed=page.date_composed,
        date_range=page.date_range,
        date_confidence=page.date_confidence,  # type: ignore[arg-type]
        genre="council",
        language="grc",
        tradition="greek",
        license="cc-by-sa-4.0",
        provenance_url=f"https://el.wikisource.org/w/index.php?title={quote(page.title)}&oldid={page.revid}",
        edition=(f"Greek Wikisource, «{page.title}», revision {page.revid}; text of "
                 "Rhalles–Potles, Σύνταγμα τῶν θείων καὶ ἱερῶν κανόνων (Athens 1852–59), "
                 "by way of the nektar site"),
        translation_of=None,
    )


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Fetch the pinned canon pages and write one raw JSON file per council."""
    cache_dir = output_dir / "_cache" / SOURCE_ID
    works: list[Work] = []
    for page in PAGES:
        out_path = output_dir / SOURCE_ID / f"{page.slug}.json"
        if out_path.exists() and not force:
            works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
            continue
        work = _work(page)
        paragraphs = parse_page(page, _fetch(page, cache_dir, force=False))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"work": work.model_dump(), "paragraphs": paragraphs},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
        works.append(work)
    log.info("Greek Wikisource canons: %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
