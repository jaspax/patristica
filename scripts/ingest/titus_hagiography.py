"""
Ingestor for the Old Georgian hagiography on TITUS (#516, #514, #222).

TITUS (titus.uni-frankfurt.de, J. Gippert) has the original ("autochthonous")
Old Georgian hagiography in these sets, one work per text here, never one per
volume:

* *Collectanea hagiographica* I (``gh1``): Ʒveli kartuli agiograpiuli
  liṭeraṭuris ʒeglebi I (V–X ss.), ed. I. Abuladze et al., Tbilisi 1963.
  All 16 texts are in period.
* *Collectanea hagiographica* II (``gh2``): idem II (XI–XV ss.), Tbilisi
  1967. The older Life of Hilarion, George the Athonite's Life of John and
  Euthymius and Leonti Mroveli's Martyrdom of Archil are in period; the rest
  are out (:data:`SKIPPED`).
* Abuladze's synoptic edition of the old redactions of the Lives of the
  Syrian Fathers (Asurel moġvac̣eta cxovrebis c̣ignta ʒveli redakciebi,
  Tbilisi 1955), as TITUS/ARMAZI sets for the Life of John of Zedazeni,
  redactions A, B and G (``asureli/iozed{a,b,g}``). A and B are the texts of
  Coll. hag. I's two versions in another edition.

Volumes III (metaphrastic redactions, XI–XIII c.), IV (synaxarion redactions,
XI–XVIII c.), V (17th–18th c.) and VI (Catholicos Antoni I, 18th c.) are out of
period and not fetched. Which texts are taken, with their author and date, is
curated in ``scripts/ingest/data/titus_hagiography.csv``; a text on TITUS that
is neither there nor in :data:`SKIPPED` is logged at ERROR.

Licence: TITUS's pages forbid republication without permission, requested
(#514); until it is granted every work is ``unknown``
(``_titus.TITUS_LICENSE``), so nothing here is translated, embedded, indexed
or published. ``Work.edition`` carries TITUS's attribution
(``_titus.edition_line``) and the printed edition's pages.

**Units and refs.** TITUS locates every line by the printed edition's page and
line, and by the editors' chapters. The only paragraph mark is indentation:
the first line of a paragraph is indented by six spaces, others by three
(``_titus.Marker.indent``). A unit is one paragraph, ref
``{prefix}.{chapter}.{n}``: the editors' chapter (Roman numerals as Arabic,
``Shush.3.2``; text before the first chapter is chapter ``0``) and the
paragraph's number within it. The synoptic edition numbers its paragraphs
itself (one per part page, ``01``, ``1``, ``39-a``), so its units are those
paragraphs, ref ``{prefix}.{paragraph}``. Refs are reader URLs: don't change
the scheme.

**Editorial material (#236).** Text in the large type of a title
(``mxag22``) is a ``title``; rubrics (the ``b`` flag: "The first chapter",
"Answer to the letter") are ``rubric``; the chapter titles printed in the text
(``t``) are ``heading``; small type (``mxag12``: "Bless, father!", feast dates,
scribes' prayers, glosses) and the editor's modern-Georgian notes (``ng``) are
``note``; the editors' Arabic chapter and paragraph numbers (``1.``) are
``heading``. TITUS's brackets are spans per ``_titus.clean_text``:
restorations, expansions and additions are ``supplement``, ``[...]`` a
``lacuna``. Variant readings (``v``) and Latin-script sigla are left out.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from patristica.models import Work
from scripts.ingest import _titus as T

log = logging.getLogger(__name__)

SOURCE_ID = "titus-hagiography"

_INDEX_CSV = Path(__file__).parent / "data" / "titus_hagiography.csv"


@dataclass(frozen=True)
class TitusSet:
    key: str
    frame: str           # the set's frame page, relative to _titus.BASE_URL
    paragraphs: bool     # the set numbers its paragraphs (Paragraph level) itself


SETS: dict[str, TitusSet] = {s.key: s for s in (
    TitusSet("coll-hag-1", "etcs/cauc/ageo/gh/gh1/gh1.htm", paragraphs=False),
    TitusSet("coll-hag-2", "etcs/cauc/ageo/gh/gh2/gh2.htm", paragraphs=False),
    TitusSet("asureli-a", "etca/cauc/ageo/asureli/iozeda/iozed.htm", paragraphs=True),
    TitusSet("asureli-b", "etca/cauc/ageo/asureli/iozedb/iozed.htm", paragraphs=True),
    TitusSet("asureli-g", "etca/cauc/ageo/asureli/iozedg/iozed.htm", paragraphs=True),
)}

# Texts of the fetched sets that are left out, and why (logged, not errors).
SKIPPED: dict[tuple[str, str], str] = {
    ("coll-hag-2", "Vita_Gior.Mt."):
        "out of period: George the Lesser's Life of George the Athonite, written 1066 or later",
    ("coll-hag-2", "Vita_Petr.Iber._A"):
        "out of period: Makari Mesxi's 13th-century translation (its colophon names him)",
    ("coll-hag-2", "Vita_Petr.Iber._B"):
        "out of period: an abridgement of Makari Mesxi's 13th-century translation",
}

# Location labels.
_TEXT = "Text"
_CHAPTER = "Chapter"
_PARAGRAPH = "Paragraph"
_LINE_LABELS = frozenset({"Line of ed.", "Line of edition"})
_PAGE_LABELS = frozenset({"Page of ed.", "Page of edition"})

# A paragraph's first line is indented by 6 &nbsp;s, the others by 3.
_PARAGRAPH_INDENT = 5

_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
# The editors' numbers in the text: Arabic digits, which Old Georgian never
# uses (it writes numbers with letters): "1.", "12.", "7./XVI".
_EDITOR_NUMBER_RE = re.compile(r"(?<!\S)\d+[a-z]?\.(?:/[IVXLC]+\.?)?(?=\s|$)")


@dataclass(frozen=True)
class TextRow:
    set: str
    text: str
    slug: str
    prefix: str
    title: str
    author: str | None
    date_composed: int | None
    date_range: tuple[int, int]
    date_confidence: str

    @property
    def local_id(self) -> str:
        return f"{self.set}/{self.slug}"


def load_index(path: Path = _INDEX_CSV) -> list[TextRow]:
    """The curated rows: one per text ingested."""
    rows: list[TextRow] = []
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            lo, hi = (int(x) for x in r["date_range"].split("-"))
            rows.append(TextRow(
                set=r["set"], text=r["text"], slug=r["slug"], prefix=r["prefix"],
                title=r["title"], author=r["author"] or None,
                date_composed=int(r["date_composed"]) if r["date_composed"] else None,
                date_range=(lo, hi), date_confidence=r["date_confidence"],
            ))
    keys = [(r.set, r.text) for r in rows]
    if len(set(keys)) != len(keys) or len({r.local_id for r in rows}) != len(rows):
        raise ValueError(f"{path}: a text or slug comes twice")
    unknown = {r.set for r in rows} - set(SETS)
    if unknown:
        raise ValueError(f"{path}: unknown sets {sorted(unknown)}")
    return rows


# ---------------------------------------------------------------------------
# Segments → units
# ---------------------------------------------------------------------------

def segment_kind(seg: T.Segment) -> str | None:
    """The editorial kind of a segment's text, None for the text itself.

    Raises ``LookupError`` for a segment that is not Old Georgian text at all
    (Latin-script sigla, variant readings): those are left out.
    """
    if seg.lang == "ng":
        return "note"  # the editor's own note, in modern Georgian
    if not seg.is_old_georgian or seg.is_variant:
        raise LookupError(seg.cls)
    if seg.size >= 20:
        return "title"
    if "b" in seg.flags:
        return "rubric"
    if "t" in seg.flags:
        return "heading"
    if seg.size <= 12:
        return "note"
    return None


def chapter_key(value: str) -> str:
    """A chapter label as a ref segment: Roman numerals as Arabic (``XIV`` → ``14``)."""
    v = value.strip().rstrip(".")
    if re.fullmatch(r"\d+", v):
        return str(int(v))
    if v and re.fullmatch(r"[IVXLC]+", v):
        total = 0
        for i, ch in enumerate(v):
            n = _ROMAN[ch]
            total += -n if i + 1 < len(v) and _ROMAN[v[i + 1]] > n else n
        return str(total)
    slug = re.sub(r"[^A-Za-z0-9-]", "", v)
    if not slug:
        raise ValueError(f"chapter label {value!r} gives no ref segment")
    return slug


def paragraph_key(value: str) -> str:
    """A synoptic edition's paragraph number as a ref segment (``01``, ``39-a``)."""
    slug = re.sub(r"[^A-Za-z0-9-]", "", value.strip())
    if not slug:
        raise ValueError(f"paragraph label {value!r} gives no ref segment")
    return slug


_DROPPED = {ord(c): None for c in T.DROPPED_CHARS}
_NO_SPACE_BEFORE = frozenset(",.;:!?")
_NO_SPACE_AFTER = frozenset("[(<{")
# Segment flags of names: persons (p), places (o), peoples (q).
_NAME_FLAGS = frozenset("poq")


def _clean_piece(text: str) -> str:
    text = text.translate(_DROPPED)
    return "".join(" " if unicodedata.category(c) in ("Cc", "Zs") else c for c in text)


def build_unit(pieces: list[tuple[str, str | None]]) -> tuple[str, list[list[int | str]]]:
    """One unit's text and editorial spans from its pieces (``(text, kind)``).

    Pieces are concatenated as they stand (TITUS's spacing is in them; the
    caller adds a space between lines), whitespace is collapsed, and each run
    of editorial pieces of one kind becomes a span (whitespace between two
    runs of the same kind joins them). Then the editors' numbers in the text
    are ``heading`` spans and TITUS's brackets the spans
    ``_titus.clean_text`` gives, where they don't overlap the others.
    """
    chars: list[str] = []
    kinds: list[str | None] = []
    for text, kind in pieces:
        for c in _clean_piece(text):
            if c == " " and (not chars or chars[-1] == " "):
                continue
            chars.append(c)
            kinds.append(kind)
    while chars and chars[-1] == " ":
        chars.pop()
        kinds.pop()
    # No space before a comma or stop, or after an opening bracket (one is left
    # where a marker or a span boundary split the line).
    keep = [not (c == " " and ((i + 1 < len(chars) and chars[i + 1] in _NO_SPACE_BEFORE)
                               or (i > 0 and chars[i - 1] in _NO_SPACE_AFTER)))
            for i, c in enumerate(chars)]
    chars = [c for c, k in zip(chars, keep) if k]
    kinds = [c for c, k in zip(kinds, keep) if k]
    text = "".join(chars)

    # Runs of one kind; a space takes the kind of its neighbours when they agree.
    for i, c in enumerate(chars):
        if c == " " and 0 < i < len(chars) - 1 and kinds[i - 1] == kinds[i + 1]:
            kinds[i] = kinds[i - 1]
    spans: list[list[int | str]] = []
    i = 0
    while i < len(chars):
        k = kinds[i]
        j = i
        while j < len(chars) and kinds[j] == k:
            j += 1
        if k is not None:
            s, e = i, j
            while s < e and chars[s] == " ":
                s += 1
            while e > s and chars[e - 1] == " ":
                e -= 1
            if s < e:
                spans.append([s, e, k])
        i = j

    def free(s: int, e: int) -> bool:
        return all(e <= int(a) or s >= int(b) for a, b, _ in spans)

    extra: list[list[int | str]] = []
    for m in _EDITOR_NUMBER_RE.finditer(text):
        if all(kinds[p] is None for p in range(m.start(), m.end())):
            extra.append([m.start(), m.end(), "heading"])
    cleaned, bracket_spans = T.clean_text(text, dropped="")
    if cleaned != text:
        raise AssertionError(f"clean_text changed a cleaned unit: {text!r}")
    for s, e, k in bracket_spans:
        if free(int(s), int(e)) and all(int(e) <= int(a) or int(s) >= int(b) for a, b, _ in extra):
            extra.append([int(s), int(e), k])
    spans.extend(extra)
    spans.sort(key=lambda sp: (int(sp[0]), int(sp[1])))
    return text, spans


# The kind of a name segment (person, place, people) until its neighbours decide
# it: the synoptic edition sets a name in a title or rubric in the plain name
# class ("იოვანე" between two rubric segments).
_NAME = "?name"


def resolve_names(pieces: list[tuple[str, str | None]]) -> list[tuple[str, str | None]]:
    """Give each name piece the editorial kind of the text around it.

    A run of names between two pieces of one editorial kind (a title, a
    rubric), or after one at the unit's end, takes that kind; any other name
    is text.
    """
    out = list(pieces)
    solid = [i for i, (t, k) in enumerate(out) if t.strip() and k != _NAME]
    for i, (t, k) in enumerate(out):
        if k != _NAME:
            continue
        before = next((out[j][1] for j in reversed(solid) if j < i), None)
        after = next((out[j][1] for j in solid if j > i), _NAME)  # _NAME: none follows
        out[i] = (t, before if before is not None and after in (before, _NAME) else None)
    return out


@dataclass
class RawText:
    """One TITUS text as units, with the edition pages it covers."""

    name: str
    units: list[dict[str, object]]
    pages: list[str]
    first_url: str


def split_texts(
    pages: Iterable[tuple[str, str]], prefix_of: dict[str, str], *, numbered: bool,
) -> Iterator[RawText]:
    """The texts of one set's part pages, each as paragraph units.

    *prefix_of* maps a text's TITUS name to its ref prefix; texts not in it
    are read (so the next one starts right) but yield units under no prefix,
    which the caller drops. *numbered*: the set numbers its paragraphs
    (``Paragraph`` level), else a paragraph starts at an indented line.
    """
    cur: RawText | None = None
    chapter = "0"
    para = "0"  # numbered sets: the current Paragraph value
    counters: dict[str, int] = {}
    pieces: list[tuple[str, str | None]] = []
    new_line = False

    def flush() -> None:
        nonlocal pieces
        if cur is None or not pieces:
            pieces = []
            return
        text, spans = build_unit(resolve_names(pieces))
        pieces = []
        if not text:
            return
        if numbered:
            ref_tail = para
        else:
            counters[chapter] = counters.get(chapter, 0) + 1
            ref_tail = f"{chapter}.{counters[chapter]}"
        prefix = prefix_of.get(cur.name, "?")
        unit: dict[str, object] = {"ref": f"{prefix}.{ref_tail}", "text": text}
        if spans:
            unit["editorial"] = spans
        cur.units.append(unit)

    for url, html in pages:
        for ev in T.parse_page(html):
            if isinstance(ev, T.Marker):
                if ev.label == _TEXT and not ev.extra:
                    flush()
                    if cur is not None:
                        yield cur
                    cur = RawText(name=ev.value, units=[], pages=[], first_url=url)
                    chapter, para, counters, new_line = "0", "0", {}, False
                elif cur is None:
                    continue
                elif ev.label == _CHAPTER and not ev.extra:
                    if not numbered:
                        flush()
                        chapter = chapter_key(ev.value)
                elif ev.label == _PARAGRAPH and numbered and not ev.extra:
                    flush()
                    para = paragraph_key(ev.value)
                elif ev.label in _PAGE_LABELS:
                    cur.pages.append(ev.value)
                elif ev.label in _LINE_LABELS:
                    if not numbered and ev.indent >= _PARAGRAPH_INDENT:
                        flush()
                    new_line = True
                continue
            if cur is None:
                continue
            try:
                kind = segment_kind(ev)
            except LookupError:
                continue
            if kind is None and _NAME_FLAGS & set(ev.flags):
                kind = _NAME  # resolved at flush (resolve_names)
            starts_line = new_line or ev.space_before
            if (not numbered and new_line and kind in (None, _NAME) and pieces
                    and all(k not in (None, _NAME) for t, k in pieces if t.strip())):
                flush()  # a title block ends where the text starts, indented or not
            if starts_line and pieces:
                pieces.append((" ", kind))
            new_line = False
            pieces.append((ev.text, kind))
    flush()
    if cur is not None:
        yield cur


# ---------------------------------------------------------------------------
# Works
# ---------------------------------------------------------------------------

def _page_range(pages: list[str]) -> str:
    nums = [p for p in pages if p.strip()]
    if not nums:
        return ""
    return f"p. {nums[0]}" if nums[0] == nums[-1] else f"pp. {nums[0]}–{nums[-1]}"


def make_work(row: TextRow, raw: RawText, header: T.SetHeader) -> Work:
    edition = T.edition_line(header.printed_edition, editors=header.version_by,
                             last_changed=header.last_changed)
    pages = _page_range(raw.pages)
    if pages:
        edition += f"; {pages}"
    return Work(
        work_id=f"{SOURCE_ID}/{row.local_id}",
        source_id=SOURCE_ID,
        author=row.author,
        title=row.title,
        date_composed=row.date_composed,
        date_range=row.date_range,
        date_confidence=row.date_confidence,  # type: ignore[arg-type]
        genre="patristic",
        language="oge",
        tradition="georgian",
        license=T.TITUS_LICENSE,  # type: ignore[arg-type]
        provenance_url=raw.first_url,
        edition=edition,
    )


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Fetch the TITUS sets (cached under ``output_dir/_cache/titus``) and write
    one raw JSON file per text to ``output_dir/titus-hagiography/{set}/``."""
    rows = load_index()
    out_dir = output_dir / SOURCE_ID
    paths = {r.local_id: out_dir / f"{r.local_id}.json" for r in rows}
    if not force and all(p.exists() for p in paths.values()):
        return [Work(**json.loads(p.read_text(encoding="utf-8"))["work"]) for p in paths.values()]

    works: list[Work] = []
    for key, tset in SETS.items():
        wanted = {r.text: r for r in rows if r.set == key}
        pages = list(T.iter_pages(T.BASE_URL + tset.frame, output_dir, force=force))
        header = T.parse_header(pages[0][1])
        found: set[str] = set()
        prefix_of = {name: r.prefix for name, r in wanted.items()}
        for raw in split_texts(pages, prefix_of, numbered=tset.paragraphs):
            if raw.name in found:
                log.error("%s: text %s comes twice; left out", key, raw.name)
                continue
            found.add(raw.name)
            row = wanted.get(raw.name)
            if row is None:
                reason = SKIPPED.get((key, raw.name))
                if reason:
                    log.info("%s: skipping %s (%s)", key, raw.name, reason)
                else:
                    log.error("%s: text %s is neither curated nor skipped; left out", key, raw.name)
                continue
            refs = [u["ref"] for u in raw.units]
            if len(set(refs)) != len(refs):
                dupes = sorted({r for r in refs if refs.count(r) > 1})
                log.error("%s: %s has duplicate refs %s; left out", key, raw.name, dupes[:5])
                continue
            if not raw.units:
                log.error("%s: %s has no text; left out", key, raw.name)
                continue
            work = make_work(row, raw, header)
            path = paths[row.local_id]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"work": work.model_dump(), "paragraphs": raw.units},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
            works.append(work)
            log.info("%s: %s → %s (%d paragraphs)", key, raw.name, work.work_id, len(raw.units))
        for name in sorted(set(wanted) - found):
            log.error("%s: curated text %s not found on TITUS", key, name)
    log.info("TITUS hagiography: %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
