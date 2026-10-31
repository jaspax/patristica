"""
Shared ingestor for the TITUS Old Georgian Bible sets (#515).

Each Scripture witness or recension on TITUS is its own source (a Scripture
work id is ``{source}/{osis book}``, so two recensions of Matthew need two
sources); the per-source modules (``titus_adishi.py``, …) are thin
:class:`BibleSet` specs over :func:`ingest_bible`.

A Bible set's part pages carry ``Book: Mt.`` / ``Chapter: 1`` / ``Verse: 1``
markers (the khanmeti palimpsest numbers verses as ``Paragraph``); a verse
is the Old Georgian main text at that location (:func:`_titus.is_main_text`,
or a set's own filter). Left out, and why:

* variant readings (``Verse: 1V`` lines, ``…v…`` classes): the apparatus,
  not the text;
* the manuscripts' book titles (``სახარებაჲ მათჱსი``, before chapter 1):
  they have no verse ref, and Scripture refs are ``Book.chapter.verse``;
* sigla, manuscript page markers and editors' notes (Latin-script spans).

Brackets become editorial spans (``_titus.clean_text``, #236). A fragmentary
witness keeps only the verses it has.

Licence: :data:`_titus.TITUS_LICENSE` (``unknown`` until TITUS grants
permission, #514), so these works are never translated, embedded, indexed or
published.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from tqdm import tqdm

from patristica.models import Work
from scripts.ingest import _titus
from scripts.ingest._scripture_meta import BOOK_TITLE

log = logging.getLogger(__name__)

#: TITUS book labels → OSIS, keyed by :func:`book_key` (TITUS writes "1Petr.",
#: "1.Petr." and "Ap.Jo." in different sets).
TITUS_BOOKS: dict[str, str] = {
    # New Testament
    "mt": "Matt", "mk": "Mark", "lk": "Luke", "jo": "John", "act": "Acts",
    "rom": "Rom", "1cor": "1Cor", "2cor": "2Cor", "1kor": "1Cor", "2kor": "2Cor",
    "gal": "Gal", "eph": "Eph", "phil": "Phil", "col": "Col", "kol": "Col", "phile": "Phlm",
    "1thess": "1Thess", "2thess": "2Thess",
    "1tim": "1Tim", "2tim": "2Tim", "tit": "Titus", "philem": "Phlm", "hebr": "Heb",
    "heb": "Heb", "jac": "Jas", "iac": "Jas", "1petr": "1Pet", "2petr": "2Pet",
    "1jo": "1John", "2jo": "2John", "3jo": "3John", "jud": "Jude", "iud": "Jude",
    "apjo": "Rev",
    # Old Testament
    "gen": "Gen", "ex": "Exod", "lev": "Lev", "num": "Num", "deut": "Deut",
    "ju": "Judg", "ru": "Ruth", "regi": "1Sam", "regii": "2Sam", "regiii": "1Kgs",
    "regiv": "2Kgs", "esri": "1Esd", "esriiesr": "Ezra", "esriineh": "Neh", "esriv": "4Esr",
    "esth": "Esth", "tob": "Tob", "hiob": "Job", "ps": "Ps", "od": "Odes", "prov": "Prov",
    "eccl": "Eccl", "cant": "Song", "sapsal": "Wis", "sir": "Sir", "hos": "Hos", "joel": "Joel",
    "am": "Amos", "jon": "Jonah", "abd": "Obad", "mich": "Mic", "nah": "Nah", "hab": "Hab",
    "soph": "Zeph", "agg": "Hag", "zach": "Zech", "mal": "Mal", "is": "Isa",
}


def book_key(label: str, *, keep_alternative: bool = False) -> str:
    """A TITUS book label as a :data:`TITUS_BOOKS` key: ``"1.Petr."`` → ``"1petr"``.

    A parenthesized alternative name goes (``"Reg.III_(Reg.I)"`` → ``"regiii"``)
    unless *keep_alternative*: TITUS's Esdras II is two books,
    ``"Esr.II_(Esr.)"`` and ``"Esr.II_(Neh.)"`` (``"esriiesr"``, ``"esriineh"``).
    """
    if not keep_alternative:
        label = re.sub(r"\(.*?\)", "", label)
    return re.sub(r"[.\s_()]", "", label).lower()


def osis_book(label: str, books: dict[str, str]) -> str | None:
    """The OSIS book of a TITUS label in *books*, or None."""
    return books.get(book_key(label, keep_alternative=True)) or books.get(book_key(label))


@dataclass(frozen=True)
class BibleSet:
    """One TITUS Bible set ingested as one source."""

    source_id: str
    set_path: str            # under /texte/: "etca/cauc/ageo/nt/adisnt/adisn.htm"
    witness: str             # "the Adishi Gospels (897)": for the edition line
    date_range: tuple[int, int]
    date_composed: int | None = None
    date_confidence: str = "approximate"
    author: str | None = None
    printed_edition: str | None = None   # when the set's header names none
    book_label: str = "Book"   # the khanmeti palimpsest names books "Text"
    verse_label: str = "Verse"
    # TITUS_BOOKS plus the set's own readings of a label ("Jud." is Judith in
    # the Old Testament, Jude in the New)
    books: dict[str, str] = field(default_factory=lambda: dict(TITUS_BOOKS))
    include: Callable[[_titus.Segment], bool] = _titus.is_main_text
    genre: str = "scripture"

    @property
    def url(self) -> str:
        return _titus.BASE_URL + self.set_path


# A line beside a verse, not the verse: variant readings ("14V", "30-31V",
# "8.V", once "16Ⴅ" with a Georgian letter for V), in the Adishi set the
# khanmeti codex's text of the verse ("22X", ingested as its own source), and
# in the Pauline sets the manuscripts' headings and chapter titles ("h1",
# "h2"), colophons ("col"), the editors' notes ("h2-1N", "3a-1N") and
# quotation notes ("7-1Q"), each with their variants.
_VARIANT_RE = re.compile(r"^(?:h.*|col.*|[\d.,a-z-]+(?:V+|Ⴅ|X|N|Q)\d*)$")
_NUMBER_RE = re.compile(r"^(\d+)(?:[,.*]|[ab]?_\(.*\))?$")
# A verse TITUS splits ("12:16a" after 16, as NA's second half of 16): joined
# to the verse.
_HALF_VERSE_RE = re.compile(r"^(\d+)[a-z]$")


def _number(value: str, *, chapter: bool = False) -> int | None:
    """A chapter or verse marker's number.

    ``"7,"`` (a stray comma) and ``"9*"`` are 7 and 9; an Ode's chapter ``"1_(Ex._15)"`` (with the
    canticle's source) is 1, and the two halves of the ninth Ode, ``"9a_(Lk._1)"``
    (Magnificat) and ``"9b_(Lk._1)"`` (Benedictus), are both 9: their verses keep
    Luke's numbers (46-55, 68-79), so they don't collide; the chapter ``"_"``
    of a one-chapter book (2 John, Jude) is 1. Anything else (``"1V"``, a variant line) is None.
    """
    if chapter and value == "_":
        return 1
    value = value.strip()
    m = _NUMBER_RE.match(value) or (None if chapter else _HALF_VERSE_RE.match(value))
    return int(m.group(1)) if m else None


def chapter_verse(chapter: str, verse: str) -> tuple[int, int] | None:
    """A Bible location's chapter and verse numbers, or None for a variant line."""
    ch, vs = _number(chapter, chapter=True), _number(verse)
    return None if ch is None or vs is None else (ch, vs)


def join_unit(record: dict[str, object], unit: _titus.Unit) -> None:
    """Append *unit*'s text (and editorial spans, shifted) to a raw *record*."""
    offset = len(str(record["text"])) + 1
    record["text"] = f"{record['text']} {unit.text}"
    if unit.editorial:
        spans = list(record.get("editorial", []))  # type: ignore[call-overload]
        spans += [[int(s) + offset, int(e) + offset, k] for s, e, k in unit.editorial]
        record["editorial"] = spans


def _book_slug(osis: str) -> str:
    return osis.lower()


def ingest_bible(spec: BibleSet, output_dir: Path, force: bool = False) -> list[Work]:
    """Ingest *spec*: one raw file per book under ``output_dir/{source_id}/``.

    A restricted set (members only / private use) is logged at ERROR and
    yields nothing. Unknown book labels raise. A verse number TITUS prints
    twice (``Mark 14:5`` for 14:4 and 14:5 in the Athonite set) keeps both
    texts, the second joined to the first, with a warning: the text is all
    there, under the later number.
    """
    out_dir = output_dir / spec.source_id
    raw_dir = output_dir
    pages: list[tuple[str, str]] = []
    try:
        for url, page in tqdm(_titus.iter_pages(spec.url, raw_dir, force=force),
                              desc=spec.source_id, unit="page", leave=False):
            pages.append((url, page))
    except _titus.TitusRestricted as exc:
        log.error("%s: skipped, %s", spec.source_id, exc)
        return []
    if not pages:
        raise _titus.TitusError(f"{spec.source_id}: no pages in {spec.url}")

    header = _titus.parse_header(pages[0][1])
    if header.restricted:
        log.error("%s: skipped, the set is marked members-only / private use", spec.source_id)
        return []
    last_changed = max(_titus.page_date(p) for _, p in pages)
    printed = spec.printed_edition or header.printed_edition
    edition = _titus.edition_line(
        f"{printed} ({spec.witness})" if spec.witness else printed,
        editors=header.version_by or ("Jost Gippert",),
        last_changed=last_changed,
    )

    events: list[_titus.Event] = []
    for _, page in pages:
        events.extend(_titus.parse_page(page))
    units = _titus.collect_units(
        _titus.locate(events), (spec.book_label, "Chapter", spec.verse_label), include=spec.include,
    )

    books: dict[str, list[dict[str, object]]] = {}
    seen: set[str] = set()
    for unit in units:
        label, chapter, verse = unit.key
        if chapter is None or verse is None or label is None:
            continue  # a manuscript's book title, before chapter 1
        osis = osis_book(label, spec.books)
        if osis is None:
            raise _titus.TitusError(f"{spec.source_id}: unknown TITUS book label {label!r}")
        if _VARIANT_RE.match(verse):
            continue  # a variant or parallel-witness line: the apparatus
        cv = chapter_verse(chapter, verse)
        if cv is None:
            raise _titus.TitusError(
                f"{spec.source_id}: unexpected location {label} {chapter}:{verse}")
        ref = f"{osis}.{cv[0]}.{cv[1]}"
        if ref in seen:
            log.warning("%s: %s printed twice; the texts are joined", spec.source_id, ref)
            prev = next(r for r in books[osis] if r["ref"] == ref)
            join_unit(prev, unit)
            continue
        seen.add(ref)
        books.setdefault(osis, []).append(unit.raw(ref))

    works: list[Work] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for osis, verses in books.items():
        slug = _book_slug(osis)
        work = Work(
            work_id=f"{spec.source_id}/{slug}",
            source_id=spec.source_id,
            author=spec.author,
            title=BOOK_TITLE[osis],
            date_composed=spec.date_composed,
            date_range=spec.date_range,
            date_confidence=spec.date_confidence,  # type: ignore[arg-type]
            genre=spec.genre,  # type: ignore[arg-type]
            language="oge",
            tradition="georgian",
            license=_titus.TITUS_LICENSE,  # type: ignore[arg-type]
            provenance_url=spec.url,
            edition=edition,
        )
        dest = out_dir / f"{slug}.json"
        payload = {"work": work.model_dump(mode="json"), "verses": verses}
        text = json.dumps(payload, ensure_ascii=False, indent=1) + "\n"
        if force or not dest.exists():
            dest.write_text(text, encoding="utf-8")
        works.append(work)
    log.info("%s: %d books, %d verses", spec.source_id, len(works), len(seen))
    return works
