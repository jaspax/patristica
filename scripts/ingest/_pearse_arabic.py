"""
Shared parser for the Christian Arabic pages of Roger Pearse's *Early Church
Fathers – Additional Texts* (tertullian.org, #479).

Each page carries an English translation and the Arabic it translates, one
after the other, as Word-exported HTML (Arabic as ``&#NNNN;`` entities in
``<p dir=RTL>``), with Word footnotes (``<a href="#_ftnN">[N]</a>`` markers and
``<a name="_ftnN">`` notes at the foot).  ``pearse_arabic`` writes the Arabic
works and ``pearse_arabic_eng`` the English ones; both read the same cached
pages (``data/raw/_cache/tertullian-org/``).  The footers say "This file and all
material on this page is in the public domain - copy freely".

Units are the page's paragraphs, numbered in order (``{prefix}.{n}``); the
Arabic and the English are numbered on their own, so their refs need not
agree (alignment and anchoring pair them).

Editorial material (#236):

- The page's notes are carried: each marker is replaced by its note, in
  brackets, marked ``note`` (Sbath's apparatus in Arabic, Noble's and
  Youssef's notes in English, the A/B variants of al-Majdalus).
- Sbath's page numbers (``<26>``) and Youssef's folio marker (``[fol. 268v]``)
  are layout placeholders and are dropped as noise.
- The title (Noble's ``<h3>`` headings in English; the treatise's own title,
  the first Arabic paragraph of a Sbath page) is one unit marked ``title``.
- In the Severus fragment, words in brackets in the Arabic are the scribe's
  marginal additions (the translator's notes say "in the margin"): marked
  ``supplement``, so they stay in the embedded text without the brackets.
  An unclosed bracket is left as it is.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from bs4 import BeautifulSoup, Comment, Tag

from patristica.models import Tradition, Work
from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

BASE_URL = "https://www.tertullian.org/fathers/"
CACHE_DIR = Path("_cache") / "tertullian-org"

ARABIC_SOURCE = "pearse-arabic"
ENGLISH_SOURCE = "pearse-arabic-eng"


@dataclass(frozen=True)
class Page:
    """One tertullian.org page and the work it holds."""

    file: str
    slug: str            # local work id, shared by the Arabic and English works
    prefix: str          # ref prefix
    author: str          # as the page gives it
    title: str           # English title
    arabic_title: str    # transliterated title, for the Arabic work
    arabic_edition: str
    translator: str
    sbath_title: bool    # the first Arabic paragraph is the treatise's title
    split_lines: bool    # the Arabic is one manuscript line per paragraph
    # The author's community (Arabic is a language, not a tradition, #484);
    # the English translations carry it too.
    tradition: Tradition | None
    date_range: tuple[int, int] | None = None


_SBATH = "Paul Sbath, Vingt traités philosophiques et théologiques (Cairo, 1929)"

PAGES: tuple[Page, ...] = (
    Page(
        "sbath_15_yahya_ibn_adi_01.htm", "yahya-ibn-adi-truth-of-the-gospel", "Sbath15",
        "Yahya ibn Adi",
        "On the Truth of the Gospel by Way of Reasoning from Proofs",
        "Maqāla fī ithbāt ṣidq al-Injīl",
        f"{_SBATH}, no. 15; transcribed for Roger Pearse (tertullian.org, 2009)",
        "Sam Noble", True, False, "syriac",
    ),
    Page(
        "sbath_16_yahya_ibn_adi_02.htm", "yahya-ibn-adi-differences-in-the-gospels", "Sbath16",
        "Yahya ibn Adi",
        "On the Differences in the Expressions in the Gospels and their Meanings",
        "Fī ikhtilāf lafẓ al-anājīl wa-maʿānīhā",
        f"{_SBATH}, no. 16, pp. 171f.; transcribed for Roger Pearse (tertullian.org, 2009)",
        "Sam Noble", True, False, "syriac",
    ),
    Page(
        "sbath_17_yahya_ibn_adi_03.htm", "yahya-ibn-adi-incarnate-of-the-holy-spirit", "Sbath17",
        "Yahya ibn Adi",
        'On our saying "and became incarnate of the Holy Spirit and the Virgin Mary"',
        "Fī qawlinā wa-tajassada min al-rūḥ al-qudus wa-min Maryam al-ʿadhrāʾ",
        f"{_SBATH}, no. 17; transcribed for Roger Pearse (tertullian.org, 2009)",
        "Sam Noble", True, False, "syriac",
    ),
    Page(
        "sbath_19_Abu_al-Faraj_Abdallah_ibn_al-Tayyib.htm", "ibn-al-tayyib-knowledge-and-miracles",
        "Sbath19",
        "Abu al-Faraj Abdallah ibn al-Tayyib",
        "On Knowledge and Miracles",
        "Fī al-ʿilm wa-al-muʿjiz",
        f"{_SBATH}, no. 19; transcribed for Roger Pearse (tertullian.org, 2009)",
        "Sam Noble", True, False, "syriac",
    ),
    Page(
        "severus_hermopolis_book_of_councils_cairo.htm", "severus-book-of-the-councils-cairo-fragment",
        "SevCouncils",
        "Severus ibn al-Muqaffa",
        'Book of the Councils (Cairo fragment)',
        "Kitāb al-majāmiʿ",
        "Unpublished portion (not in Patrologia Orientalis 3.2), Cairo, Coptic Museum "
        "Theol. 196 (Graf: Cairo 111, 1544 AD), ff. 268v–270v; Youhanna Youssef's "
        "transcription, published by Roger Pearse (tertullian.org, 2008)",
        "Youhanna Youssef", False, True, "coptic",
    ),
    Page(
        "al-majdalus_01_translation.htm", "al-majdalus-commentary-on-the-creed", "MajdCreed",
        "Al-Majdalus",
        "Commentary on the Nicene Creed",
        "Tafsīr al-amāna",
        "Unpublished; Beirut, Université Saint-Joseph, Bibliothèque orientale MSS 569a (1425, "
        "'A') and 569b (1897, 'B'), with their variants; transcribed for Roger Pearse "
        "(tertullian.org, 2009)",
        "Samuel Noble", False, False, None,
    ),
)


def page_url(page: Page) -> str:
    return BASE_URL + page.file


def fetch(page: Page, output_dir: Path, force: bool = False) -> Path:
    """The cached page (downloaded once, shared by both ingestors)."""
    dest = output_dir / CACHE_DIR / page.file
    return download_file(page_url(page), dest, force=force)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_ARABIC_RE = re.compile(r"[؀-ۿ]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_WS_RE = re.compile(r"\s+")
_PAGE_MARK_RE = re.compile(r"\s*<\d+>\s*")
_FOLIO_RE = re.compile(r"\s*\[fol\. \d+[rv]\]\s*")
_NOTE_N_RE = re.compile(r"_ftn(\d+)$")
_MARGIN_RE = re.compile(r"\[[^\[\]]+\]")
# A speaker begins a new paragraph of the Severus Arabic ("and X said").
_SPEAKER_RE = re.compile(r"(?<=\s)(?=وقال(?:ت)?\s)")


class PearseParseError(RuntimeError):
    pass


@dataclass
class Unit:
    text: str
    spans: list[list]

    def record(self, ref: str) -> dict:
        rec: dict = {"ref": ref, "text": self.text}
        if self.spans:
            rec["editorial"] = self.spans
        return rec


class _Builder:
    """Text with editorial spans, whitespace collapsed as it is built."""

    def __init__(self) -> None:
        self.text = ""
        self.spans: list[list] = []

    def add(self, piece: str, kind: str | None = None) -> None:
        piece = _WS_RE.sub(" ", piece)
        if not piece:
            return
        if self.text.endswith(" ") or not self.text:
            piece = piece.lstrip()
            if not piece:
                return
        if kind is not None:
            if self.text and not self.text.endswith(" "):
                self.text += " "
            piece = piece.strip()
            self.spans.append([len(self.text), len(self.text) + len(piece), kind])
            self.text += piece + " "
        else:
            self.text += piece

    def unit(self) -> Unit:
        text = self.text.rstrip()
        return Unit(text, [[s, min(e, len(text)), k] for s, e, k in self.spans])


def _note_n(a: Tag, attr: str) -> int | None:
    m = _NOTE_N_RE.search(a.get(attr, "") or "")
    return int(m.group(1)) if m else None


def _notes(soup: BeautifulSoup) -> dict[int, str]:
    """Footnote number → note text, from the ``<a name="_ftnN">`` paragraphs."""
    notes: dict[int, str] = {}
    for a in soup.find_all("a", attrs={"name": _NOTE_N_RE}):
        n = _note_n(a, "name")
        p = a.find_parent("p")
        if n is None or p is None:
            continue
        a.extract()
        text = _WS_RE.sub(" ", p.get_text(" ")).strip()
        if n in notes:
            raise PearseParseError(f"note {n} appears twice")
        notes[n] = text
        p["data-note"] = "1"
    return notes


def _strip_layout(text: str) -> str:
    text = _PAGE_MARK_RE.sub(" ", text)
    return _FOLIO_RE.sub(" ", text)


def _paragraph(p: Tag, notes: dict[int, str], used: set[int]) -> Unit:
    out = _Builder()
    for node in p.descendants:
        if isinstance(node, Tag):
            if node.name == "a" and _note_n(node, "href") is not None:
                n = _note_n(node, "href")
                assert n is not None
                if n not in notes:
                    raise PearseParseError(f"note marker [{n}] has no note")
                used.add(n)
                out.add(f"[{notes[n]}]", "note")
            continue
        if isinstance(node, Comment):
            continue
        if any(par.name == "a" and _note_n(par, "href") is not None
               for par in node.parents if isinstance(par, Tag)):
            continue  # the marker's own text
        out.add(_strip_layout(str(node)))
    return out.unit()


def _is_arabic(text: str) -> bool:
    return len(_ARABIC_RE.findall(text)) > len(_LATIN_RE.findall(text))


def _title_unit(texts: list[str]) -> Unit:
    text = " — ".join(t for t in texts if t)
    return Unit(text, [[0, len(text), "title"]])


def _severus_arabic(lines: list[Unit]) -> list[Unit]:
    """The manuscript lines joined, then split where a new speaker begins."""
    joined = " ".join(u.text for u in lines if u.text)
    if any(u.spans for u in lines):
        raise PearseParseError("Severus Arabic lines carry notes; join them by hand")
    units: list[Unit] = []
    for part in _SPEAKER_RE.split(joined):
        part = part.strip()
        if not part:
            continue
        spans = [[m.start(), m.end(), "supplement"] for m in _MARGIN_RE.finditer(part)]
        units.append(Unit(part, spans))
    return units


def parse(page: Page, html_text: str) -> tuple[list[Unit], list[Unit]]:
    """(English units, Arabic units) of one page."""
    soup = BeautifulSoup(html_text, "lxml")
    body = soup.body
    if body is None:
        raise PearseParseError(f"{page.file}: no <body>")
    for table in body.find_all("table"):
        table.decompose()
    notes = _notes(soup)
    used: set[int] = set()

    english: list[Unit] = []
    arabic: list[Unit] = []
    eng_titles: list[str] = []
    for el in body.find_all(["p", "h3"]):
        if el.get("data-note"):
            continue
        plain = _WS_RE.sub(" ", el.get_text(" ")).strip()
        if not plain:
            continue
        if el.name == "h3":
            eng_titles.append(_paragraph(el, notes, used).text)
            continue
        if el.get("align") in ("center", "left") or el.get("class"):
            continue  # the page heading, translator line, Pearse's preface, footer
        if el.find("a", href=re.compile(r"^#(English|Arabic)")):
            continue  # Severus's links to the two halves
        unit = _paragraph(el, notes, used)
        if not unit.text:
            continue
        (arabic if _is_arabic(unit.text) else english).append(unit)

    if eng_titles:
        english.insert(0, _title_unit(eng_titles))
    if page.sbath_title and arabic:
        arabic[0] = _title_unit([arabic[0].text])
    if page.split_lines:
        arabic = _severus_arabic(arabic)

    unused = set(notes) - used
    if unused:
        raise PearseParseError(f"{page.file}: notes never referenced: {sorted(unused)}")
    if not english or not arabic:
        raise PearseParseError(f"{page.file}: {len(english)} English, {len(arabic)} Arabic units")
    return english, arabic


def records(page: Page, units: list[Unit]) -> list[dict]:
    return [u.record(f"{page.prefix}.{n}") for n, u in enumerate(units, 1)]


# ---------------------------------------------------------------------------
# Works
# ---------------------------------------------------------------------------

def work_id(source_id: str, page: Page) -> str:
    return f"{source_id}/{page.slug}"


def _work(page: Page, english: bool) -> Work:
    source_id = ENGLISH_SOURCE if english else ARABIC_SOURCE
    if english:
        title = page.title
        edition = (f"English translation by {page.translator} for Roger Pearse "
                   f"(tertullian.org), in the public domain; of: {page.arabic_edition}")
    else:
        title = f"{page.title} ({page.arabic_title})"
        edition = page.arabic_edition
    return Work(
        work_id=work_id(source_id, page),
        source_id=source_id,
        author=page.author,
        title=title,
        date_composed=None,
        date_range=page.date_range,
        date_confidence="uncertain",
        genre="patristic",
        language="eng" if english else "arb",
        tradition=page.tradition,
        license="public_domain",
        provenance_url=page_url(page),
        edition=edition,
        translation_of=work_id(ARABIC_SOURCE, page) if english else None,
    )


def ingest_pages(output_dir: Path, force: bool, english: bool) -> list[Work]:
    """Write one raw file per page for the Arabic (or the English) works."""
    source_id = ENGLISH_SOURCE if english else ARABIC_SOURCE
    out_dir = output_dir / source_id
    out_dir.mkdir(parents=True, exist_ok=True)
    works: list[Work] = []
    for page in PAGES:
        out_path = out_dir / f"{page.slug}.json"
        if out_path.exists() and not force:
            works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
            continue
        html_path = fetch(page, output_dir, force=force)
        eng_units, arb_units = parse(page, html_path.read_text(encoding="utf-8"))
        units = eng_units if english else arb_units
        work = _work(page, english)
        out_path.write_text(
            json.dumps({"work": work.model_dump(), "paragraphs": records(page, units)},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("%s: %d paragraphs", work.work_id, len(units))
        works.append(work)
    return works
