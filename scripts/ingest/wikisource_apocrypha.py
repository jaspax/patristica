"""
Ingestor for Greek apocrypha on Greek Wikisource (#78).

Source: https://el.wikisource.org (category Απόκρυφα)
Format: MediaWiki wikitext: chapter headings (``=== I ===``, ``;I``,
        ``===ΚΕΦΑΛΑΙΟ 1===``) and numbered verses (``'''1'''&nbsp;…`` or ``1. …``)
License: CC-BY-SA 4.0 (Wikisource); the printed editions are public domain

Each page names the edition it transcribes (:data:`PAGES`) and is pinned to a
revision id, cached in ``data/raw/_cache/wikisource-apocrypha/``.  Only pages
whose source is stated are taken; the Acts of Paul and Thecla and the
Apocalypse of Peter name none (#317).

Refs are ``{prefix}.{chapter}.{verse}``; the *Testaments* add the patriarch:
``T12P.Reub.1.1``.  A line without a verse number is joined to the verse
before it.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import httpx

from patristica.models import Work
from scripts.ingest._common import require_network

log = logging.getLogger(__name__)

SOURCE_ID = "wikisource-apocrypha"

_API = "https://el.wikisource.org/w/api.php"
_USER_AGENT = "Patristica/0.1 (https://patristica.app; corpus ingest)"

# Patriarchs of the Testaments, in order, by the heading's first word after ΔΙΑΘΗΚΗ.
_PATRIARCHS: dict[str, str] = {
    "ΡΟΥΒΗΜ": "Reub", "ΣΥΜΕΩΝ": "Sim", "ΛΕΥΙ": "Levi", "ΙΟΥΔΑ": "Jud", "ΙΣΑΧΑΡ": "Iss",
    "ΖΑΒΟΥΛΩΝ": "Zeb", "ΔΑΝ": "Dan", "ΝΕΦΘΑΛΕΙΜ": "Naph", "ΓΑΔ": "Gad", "ΑΣΗΡ": "Ash",
    "ΙΩΣΗΦ": "Jos", "ΒΕΝΙΑΜΙΝ": "Benj",
}


@dataclass(frozen=True)
class Page:
    slug: str
    title: str
    revid: int
    prefix: str
    work_title: str
    edition: str
    date_composed: int
    date_range: tuple[int, int]


PAGES: tuple[Page, ...] = (
    Page("apocalypsis-esdrae", "Αποκάλυψις Εσδράμ", 135159, "ApEsdr",
         "Ἀποκάλυψις Ἐσδρὰμ (Apocalypse of Esdras)",
         "C. von Tischendorf, Apocalypses apocryphae (Leipzig 1866), 24–33", 600, (150, 850)),
    Page("apocalypsis-sedrach", "Αποκάλυψις Σεδράχ", 93317, "ApSedr",
         "Λόγος τοῦ ἁγίου Σεδράχ (Apocalypse of Sedrach)",
         "M. R. James, Apocrypha anecdota (Cambridge 1893), 127–137", 500, (200, 1000)),
    Page("testamenta-xii-patriarcharum", "Διαθήκαι των ΙΒ' Πατριαρχών", 126715, "T12P",
         "Διαθῆκαι τῶν δώδεκα πατριαρχῶν (Testaments of the Twelve Patriarchs)",
         "the text of R. H. Charles, The Greek Versions of the Testaments of the Twelve Patriarchs "
         "(Oxford 1908), per the Online Critical Pseudepigrapha", 150, (-100, 200)),
)

_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50}


def roman(s: str) -> int:
    """``XIV`` → 14."""
    total = 0
    for a, b in zip(s, s[1:] + " "):
        v = _ROMAN[a]
        total += -v if b in _ROMAN and _ROMAN[b] > v else v
    return total


def clean(line: str) -> str:
    """Wikitext → plain text."""
    line = re.sub(r"\{\{[^{}]*\}\}|\[\[(?:Κατηγορία|Category):[^\]]*\]\]|<[^>]+>", "", line)
    line = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]*)\]\]", r"\1", line)
    line = line.replace("'''", "").replace("''", "").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", line).strip()


def parse(page: Page, wikitext: str) -> list[dict[str, str]]:
    """The page's verses as raw records."""
    records: list[dict[str, str]] = []
    patriarch: str | None = None
    chapter: int | None = None
    for raw in wikitext.split("\n"):
        line = raw.strip()
        if not line or line.startswith(("{{", "}}", "|", "__", "[[Κατηγορία", "Source=")):
            continue
        head = re.fullmatch(r"(=+)\s*(.*?)\s*=+", line) or re.fullmatch(r";\s*(\S+)()", line)
        if head:
            text = head.group(2) if head.re.pattern.startswith("(=+") else head.group(1)
            m = re.fullmatch(r"ΔΙΑΘΗΚΗ\s+(\S+).*", text)
            if m:
                patriarch, chapter = _PATRIARCHS[m.group(1)], None
            elif re.fullmatch(r"[IVXL]+", text):
                chapter = roman(text)
            elif (m := re.fullmatch(r"ΚΕΦΑΛΑΙΟ\s+(\d+)", text)):
                chapter = int(m.group(1))
            else:
                raise ValueError(f"{page.slug}: unknown heading {line!r}")
            continue
        m = re.match(r"^'''(\d+)'''|^(\d+)\.\s*", line)
        text = clean(line[m.end():] if m else line)
        if not text:
            continue
        if m is None:
            if not records:  # the incipit before chapter 1
                records.append({"ref": f"{page.prefix}.0", "text": text})
            else:
                records[-1] = {**records[-1], "text": f"{records[-1]['text']} {text}"}
            continue
        verse = m.group(1) or m.group(2)
        path = [page.prefix, *([patriarch] if patriarch else []), str(chapter or 1), verse]
        records.append({"ref": ".".join(path), "text": text})
    refs = [r["ref"] for r in records]
    if len(refs) != len(set(refs)):
        dup = sorted({r for r in refs if refs.count(r) > 1})[:5]
        raise ValueError(f"{page.slug}: repeated refs {dup}")
    return records


def _fetch(page: Page, cache_dir: Path) -> str:
    """The page's wikitext at its pinned revision (cached)."""
    path = cache_dir / f"{page.slug}-{page.revid}.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["wikitext"]
    require_network(f"fetching {page.title} from Greek Wikisource")
    params = {"action": "query", "prop": "revisions", "revids": str(page.revid),
              "rvprop": "content|ids|timestamp", "rvslots": "main",
              "format": "json", "formatversion": "2"}
    for attempt in range(4):  # the API answers 503 now and then
        resp = httpx.get(_API, params=params, headers={"User-Agent": _USER_AGENT}, timeout=60)
        if resp.status_code < 500 or attempt == 3:
            break
        log.info("%s: HTTP %d, retrying", page.slug, resp.status_code)
        time.sleep(10 * (attempt + 1))
    if resp.status_code >= 500:  # large pages: the raw text of the revision instead
        log.info("%s: API unavailable, fetching the raw revision", page.slug)
        raw = httpx.get(_API.replace("api.php", "index.php"),
                        params={"action": "raw", "oldid": str(page.revid)},
                        headers={"User-Agent": _USER_AGENT}, timeout=120)
        raw.raise_for_status()
        wikitext, timestamp = raw.text, None
    else:
        resp.raise_for_status()
        found = resp.json()["query"]["pages"][0]
        revision = found["revisions"][0]
        if found["title"] != page.title or revision["revid"] != page.revid:
            raise ValueError(f"{page.slug}: revision {page.revid} is not of {page.title!r}")
        wikitext, timestamp = revision["slots"]["main"]["content"], revision["timestamp"]
    path.parent.mkdir(parents=True, exist_ok=True)
    cached = {"title": page.title, "revid": page.revid, "timestamp": timestamp,
              "wikitext": wikitext}
    path.write_text(json.dumps(cached, ensure_ascii=False, indent=1), encoding="utf-8")
    return wikitext


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Fetch the pinned pages and write one raw JSON file per work."""
    works: list[Work] = []
    for page in PAGES:
        out_path = output_dir / SOURCE_ID / f"{page.slug}.json"
        if out_path.exists() and not force:
            works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
            continue
        work = Work(
            work_id=f"{SOURCE_ID}/{page.slug}",
            source_id=SOURCE_ID,
            author=None,
            title=page.work_title,
            date_composed=page.date_composed,
            date_range=page.date_range,
            date_confidence="uncertain",
            genre="apocrypha",
            language="grc",
            tradition="greek",
            license="cc-by-sa-4.0",
            provenance_url=f"https://el.wikisource.org/w/index.php?title={quote(page.title)}"
                           f"&oldid={page.revid}",
            edition=f"Greek Wikisource, «{page.title}», revision {page.revid}; {page.edition}",
            translation_of=None,
        )
        paragraphs = parse(page, _fetch(page, output_dir / "_cache" / SOURCE_ID))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"work": work.model_dump(), "paragraphs": paragraphs},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
        works.append(work)
    log.info("Greek Wikisource apocrypha: %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
