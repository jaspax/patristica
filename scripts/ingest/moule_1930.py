"""
Ingestor for A. C. Moule's English translations of the Tang-dynasty Christian
(Jingjiao) texts in *Christians in China before the Year 1550* (#654, part of
#228).

Source: A. C. Moule, *Christians in China before the Year 1550* (London: SPCK;
New York and Toronto: Macmillan, 1930), chapter II "The T'ang Dynasty",
archive.org item ``christiansinchin00moul`` (Princeton Theological Seminary
Library scan).  Published 1930, so public domain in the United States since
2026-01-01, where Patristica is hosted; Moule died in 1957, so the book is in
copyright in the United Kingdom until the end of 2027 (``DATA_LICENSE.md``).
Language: eng  Tradition: syriac (the Church of the East)  License: public_domain

We read archive.org's OCR of the scans (``{item}_djvu.xml``, lines with word
boxes; nothing is re-OCRed), keep the translation and drop the rest of each
page: the running head, the footnotes (set in smaller type at the foot of the
page: :func:`body_lines`), the plates, and Moule's own discussion before and
after each text.  Every unit was checked against the page images.  The OCR's
errors, the footnote numbers glued to words, the lost diacritics of the
romanizations (``A-lo-hê``, ``Alāhā``, ``ssŭ``) and the pencil marks in the
scan's margins are corrected as data, never in the output: the replacements in
:data:`CORRECTIONS` (each must match a stated number of times, so a changed
OCR fails loudly), the letters in :data:`LETTERS` and the line-end hyphens in
:data:`KEPT_HYPHENS`.

Works (each the translation of a Literary Chinese work of ``wikisource-lzh``,
#650):

- ``moule-1930/xian-stele``: the Xi'an stele of 781 (pp. 34-52): the title,
  Jingjing's text and eulogy, the date and the names, with the Syriac of the
  stone (Moule translates it too, in italics; in ``wikisource-lzh`` it is the
  separate work ``xian-stele-syriac``).  Moule's bracketed notes on where each
  part stands on the stone (``[On the left edge of the stone; top row.]``) are
  units marked ``heading``.  The inscription of 1859 cut into the left edge
  (p. 50) is left out, as in ``wikisource-lzh``: it is not part of the
  monument of 781.
- ``moule-1930/sanwei-mengdu-zan``: the hymn to the Trinity of Pelliot chinois
  3847 (pp. 53-55): its title, one unit per stanza of four lines (the 44 lines
  of seven characters) and its closing title.
- ``moule-1930/zunjing``: the rest of the same manuscript (pp. 55-57): the
  honoured persons and books and the closing note.

Moule's numbering of the three parts of the manuscript (``1.``, ``2.``,
``3.``) is marked ``heading``.  Refs: ``{n}``, one per paragraph, stanza or
line of names, in Moule's order.

Not ingested (reported on #654): the partial paraphrase of the *Xuting Mishisuo
jing* (pp. 60-64, from column 114 to the end, with Moule's summary before it)
and the shorter in-period texts of section (4), pp. 65-72 (the edict of 638 in
the *Tang huiyao*, the edict of 745, Liu Ze's memorial, the passage on Prajña
and Jingjing, ...), which are not works of the corpus.
"""

from __future__ import annotations

import json
import logging
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path

from patristica.models import Work
from scripts.ingest import _ia_djvu
from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

SOURCE_ID = "moule-1930"
LICENSE = "public_domain"

_ITEM = "christiansinchin00moul"
_DETAILS = f"https://archive.org/details/{_ITEM}"
_XML_URL = f"https://archive.org/download/{_ITEM}/{_ITEM}_djvu.xml"

EDITION = (
    "A. C. Moule (trans.), Christians in China before the Year 1550 "
    "(London: SPCK, 1930), pp. {pages}; Internet Archive scan "
    f"{_ITEM} (Princeton Theological Seminary Library), OCR corrected from "
    "the page images"
)

#: The work ids of the Literary Chinese originals (wikisource-lzh, #650).
#: Not yet set as ``translation_of``: a link to a work that is not in the
#: corpus fails ``test_translation_of``.  Once #650's works are on this
#: branch's base, set ``ORIGINALS_IN_CORPUS = True`` and re-ingest (#654).
ORIGINALS_IN_CORPUS = True
STELE_ORIGINAL = "wikisource-lzh/xian-stele"
HYMN_ORIGINAL = "wikisource-lzh/sanwei-mengdu-zan"
ZUNJING_ORIGINAL = "wikisource-lzh/zunjing"

#: Leaves (1-based, as in the item's page_numbers.json) that are plates.
PLATES = frozenset({61, 62, 77, 78})

#: A unit's mode: how its lines are joined into units.
#: ``prose``: a new unit at an indented line (a paragraph); ``verse``: a new
#: unit at a line listed in ``Part.stanzas``; ``list``: a new unit at every
#: line that does not continue the one before (a name, :func:`_continues`);
#: ``heading``: a bracketed note by Moule, one unit, editorial; ``skip``: left
#: out.  A mode starts with a unit of its own.


@dataclass(frozen=True)
class Part:
    """One work: where it is in the book and how its lines are cut."""
    slug: str
    title: str
    author: str | None          # Moule's spelling; None: anonymous
    pages: str
    first_leaf: int
    last_leaf: int
    start: str                      # the OCR of its first line starts with this
    end: str                        # … and of its last line
    modes: tuple[tuple[str, str], ...]  # (OCR line prefix, mode from that line on)
    date_composed: int | None
    date_range: tuple[int, int]
    date_confidence: str
    genre: str
    translation_of: str
    #: Prefixes of units' raw text (before corrections) marked ``heading``:
    #: Moule's numbering of the parts.
    numbered: tuple[str, ...] = field(default=())
    #: OCR line prefixes that start a unit in ``verse`` mode (a stanza), or
    #: in ``list`` mode where the layout does not show it.
    stanzas: tuple[str, ...] = field(default=())


PARTS: tuple[Part, ...] = (
    Part(
        slug="xian-stele",
        title="The Christian Monument at Hsi-an (Xi'an stele)",
        author="Ching-ching",
        pages="34-52",
        first_leaf=56, last_leaf=76,
        start="A Monument of the diffusion",
        end="Iohanan monk Té-chien",
        modes=(
            ("A Monument of the diffusion", "prose"),
            ("The true Lord without origin", "verse"),
            ("Set up in the great T’ang", "prose"),
            ("[At the foot of the front face", "heading"),
            ("In the year thousand and ninety", "prose"),
            ("Monk Ling-pao Adam", "list"),
            ("[On the left edge of the stone", "heading"),
            ("My lord Iohanan Bishop", "list"),
            ("[Second row", "heading"),
            ("Bacchus priest monk", "list"),
            ("[Third row", "heading"),
            ("Aaron monk", "list"),
            ("[Fourth row", "heading"),
            ("Izdsafas monk", "list"),
            ("[Through and below the third", "skip"),
            ("[On the right edge of the stone", "heading"),
            ("Jacob priest venerable", "list"),
            ("[Second row", "heading"),
            ("Jacob sacristan", "list"),
            ("[Third row", "heading"),
            ("Gabriel monk Kuang", "list"),
        ),
        date_composed=781, date_range=(781, 781), date_confidence="established",
        genre="patristic",
        translation_of=STELE_ORIGINAL,
        stanzas=(
            "The most majestic and cultured", "Kao Tsung, following", "Hstian Tsung opened",
            "Su Tsung came to restore", "Tai Tsung was pious", "The Chien-chung [Emperor]",
            "The Way is broad",
            # names on the foot of the stone, set like paragraphs (p. 48)
            "Mar Sargis priest and country-bishop", "Gabriel priest and archdeacon",
        ),
    ),
    Part(
        slug="sanwei-mengdu-zan",
        title="A Hymn of the Brilliant Teaching to the Three Majesties for obtaining salvation",
        author=None,
        pages="53-55",
        first_leaf=79, last_leaf=81,
        start="1. A Hymn of the Brilliant Teaching",
        end="Majesties for obtaining salvation.",
        modes=(
            ("1. A Hymn of the Brilliant Teaching", "prose"),
            ("[If] the highest heavens", "verse"),
            ("A Hymn of the Brilliant Teaching of Ta-ch’in", "verse"),
        ),
        date_composed=None, date_range=(720, 845), date_confidence="approximate",
        genre="liturgical",
        translation_of=HYMN_ORIGINAL,
        numbered=("1. ",),
        stanzas=(
            "All the congregation of the good", "Hard to find, impossible",
            "[Your] eternal existence",
            "Alone completely perfect", "We now all recite", "Merciful joyful Lamb",
            "The holy Son justly", "The great Master is our merciful", "The great Master with wise",
            "Most holy universally honoured",
        ),
    ),
    Part(
        slug="zunjing",
        title="Honoured Persons and Sacred Books (Zunjing)",
        author=None,
        pages="55-57",
        first_leaf=81, last_leaf=83,
        start="2. Honoured Persons and Sacred Books",
        end="translated.",
        modes=(("2. Honoured Persons and Sacred Books", "prose"),),
        date_composed=None, date_range=(781, 1000), date_confidence="approximate",
        genre="liturgical",
        translation_of=ZUNJING_ORIGINAL,
        numbered=("2. ", "3. "),
    ),
)


#: Letters the OCR reads wrongly wherever they occur in these pages, applied
#: after :data:`CORRECTIONS`: Moule's Wade-Giles ê (A-lo-pên, Chêng-kuan) is
#: read é, and ü (Hsüan, Yüan) is read ii.  Neither é nor ii occurs in the
#: English of these pages (checked against the page images).
LETTERS: tuple[tuple[str, str], ...] = (("é", "ê"), ("ii", "ü"))

#: Corrections of the OCR, read from the page images: per work, (OCR text,
#: printed text) or (OCR text, printed text, count).  Each OCR text must occur
#: exactly once (or *count* times) in the work's units after line joining, so
#: a change in the OCR fails instead of passing silently.  Footnote numbers
#: glued to words and marks in the scan's margins are removed here too.
CORRECTIONS: dict[str, tuple[tuple, ...]] = {
    "xian-stele": (
        # p. 35
        ("Zinistan.™", "Zinistan."),
        ("A-lo-hé (Alaha)?", "A-lo-hé (Alāhā)?"),
        ("figure of ten !* to", "figure of ten to"),
        ("Darkness _. and", "Darkness and"),
        # p. 36
        ("resulted.?®", "resulted."),
        ("zeal.’ They", "zeal. They"),
        ("happiness.!8", "happiness."),
        # p. 37
        ("hung upa brilliant", "hung up a brilliant"),
        ("sphere.*°", "sphere."),
        ("glory.24_ They", "glory. They"),
        # p. 38 (pencil marks in the margin)
        ("blue /clouds,” carried", "blue clouds, carried"),
        ("In \\the ninth", "In the ninth"),
        # p. 39
        ("transmission.”*", "transmission."),
        ("capital.** If", "capital. If"),
        ("east.*5", "east."),
        # p. 40
        ("the Hz yii t’u chi", "the Hsi yii t’u chi"),
        ("enlightened.”®", "enlightened."),
        ("Hao.2” There", "Hao. There"),
        # p. 41
        ("Chi-lieh 28 of", "Chi-lieh of"),
        ("princes? to", "princes to"),
        ("diffuse ight", "diffuse light"),
        ("reverendone.", "reverend one."),
        ("writing.®°. The", "writing. The"),
        # p. 42
        ("Ling-wu 31 and", "Ling-wu and"),
        ("heart.%?", "heart."),
        # p. 43
        ("arise,** this", "arise, this"),
        ("Chin-tztt", "Chin-tzŭ"),
        ("kashaya", "kashāya", 2),
        ("the monk I-sst,", "the monk I-ssŭ,"),
        ("Chung-hsia.34 The", "Chung-hsia. The"),
        # p. 44
        ("Kuo Tzi-i", "Kuo Tzŭ-i"),
        ("expedition.?® Though", "expedition. Though"),
        ("Hewas", "He was"),
        ("rest.2® He", "rest. He"),
        ("monasteries 3” together", "monasteries together"),
        # p. 45
        ("them ;#8 he", "them; he"),
        ("(tavsd)", "(tarsā)"),
        ("man.®9", "man."),
        ("came* to", "came to"),
        # p. 46
        ("cere\" moniously", "ceremoniously"),
        ("Hstian Tsung", "Hsiian Tsung"),
        ("together.*!", "together."),
        # p. 47
        ("day.”", "day."),
        ("Patriarch.®", "Patriarch."),
        ("Sst-shih", "Ssŭ-shih"),
        ("writer.“", "writer."),
        # p. 48
        ("Hsing-tung", "Hsing-t’ung"),
        ("Sarag ®", "Sarag"),
        # p. 49
        ("Ho-chi *®", "Ho-chi"),
        ("Mshthadad *\" priest", "Mshihadad priest"),
        ("Fu-lin 48", "Fu-lin"),
        ("Abt priest", "Abi priest"),
        ("[Second row. ]", "[Second row.]", 2),
        ("\"Abadishw’ priest", "’Abadishu’ priest"),
        ("Iohanis mimster and monk * monk", "Iohanis minister and monk monk"),
        # p. 50
        ("Petey monk", "Peter monk"),
        ("Ishwameh", "Ishu’ameh"),
        ("Lohanan", "Iohanan"),
        ("Sabrishw monk", "Sabrishu’ monk"),
        ("Ishwdad monk", "Ishu’dad monk"),
        ("[Fourth row.", "[Fourth row.]"),
        ("Tohanan", "Iohanan"),
        ("Pusat monk", "Pusai monk"),
        # p. 51
        ("shiangtsua © monk", "shiangtsua monk"),
        ("Gigot priest", "Gigoi priest"),
        ("\"A badishu’ monk", "’Abadishu’ monk"),
        ("Ishw dad monk", "Ishu’dad monk"),
        ("Shubha Ilmaran", "Shubha lmaran"),
        ("Cyritacus", "Cyriacus"),
        # p. 52
        ("Ch’ti-shén", "Ch’ii-shén"),
        ("Té-chien *1", "Té-chien"),
    ),
    "sanwei-mengdu-zan": (
        ("finite,®", "finite,"),
        ("all living, :", "all living,"),
        ("high,*® ,", "high,"),
        ("fire.*’", "fire."),
        ("sweet — dew", "sweet dew"),
        ("dispute.*8", "dispute."),
    ),
    "zunjing": (
        # p. 55
        ("ning-chii-sha.*?", "ning-chii-sha."),
        ("Mo-chii-sst. spiritual", "Mo-chii-ssŭ spiritual"),
        ("To-huispiritual", "To-hui spiritual"),
        ("Mo-sa-chi-sst spiritual", "Mo-sa-chi-ssŭ spiritual"),
        ("I-ho-chi-ssti", "I-ho-chi-ssŭ"),
        ("Mo-mu-chi-sst.", "Mo-mu-chi-ssŭ"),
        ("Nien-sst. shéng ®® spiritual", "Nien-ssŭ shéng spiritual"),
        ("MHo-sa-yeh", "Ho-sa-yeh"),
        ("Chi-lu spiritual", "Chii-lu spiritual"),
        ("king.®?", "king."),
        # p. 56
        ("veach root", "reach root"),
        ("Chih hstian an lo", "Chih hsiian an lo"),
        ("Iidden", "hidden"),
        ("Tien pao tsang", "T’ien pao tsang"),
        ("A ssi chi li yung book.®?.", "A ssŭ chii li yung book."),
        ("Ching 1 (Complete", "Ch’ing i (Complete"),
        ("Sanchi (Three moments) book.®", "San chi (Three moments) book."),
        ("Ning ssti", "Ning ssŭ"),
        ("MHsiian i", "Hsiian i"),
        ("yiieh sst book", "yiieh ssŭ book"),
        ("P’iéch’ibook", "P’i é ch’i book"),
        ("San weitsan", "San wei tsan"),
        ("book.®* Mu", "book. Mu"),
        ("Ili yeh", "I li yeh"),
        ("E fu lin", "Ê fu lin"),
        ("hé tzu tsai tien ti", "hé tzŭ tsai t’ien ti"),
        ("Sst mén", "Ssŭ mén"),
        ("chi sst (Mar", "chi ssŭ (Mar"),
        ("Tzt li po", "Tz’ŭ li po"),
        # p. 57
        ("faiva leaves", "patra leaves"),
        ("(1.e. Syriac", "(i.e. Syriac"),
        ("translation®> the", "translation the"),
        ("translated.®®", "translated."),
    ),
}

#: Line ends (the OCR of the last word, with its hyphen) whose hyphen is part
#: of the word, read from the page images: a compound or a romanized name
#: split at its hyphen.  Every other line-end hyphen breaks a word and is
#: dropped.
KEPT_HYPHENS: frozenset[str] = frozenset({
    "Hsiian-", "country-", "Hsing-", "Mo-", "Mo-sa-", "Mo-mu-", "Ching-",
})


# ---------------------------------------------------------------------------
# Leaves → body lines
# ---------------------------------------------------------------------------

_HEAD_RE = re.compile(r"CHRISTIANS IN CHINA|DYNASTY")
#: A footnote line: set in smaller type than the body (about 44 px against 55).
_NOTE_HEIGHT = 50.0
#: … and set closer: about 61 px from line to line against 86.
_NOTE_PITCH = 72.0


def body_lines(leaf: _ia_djvu.Leaf) -> list[_ia_djvu.Line]:
    """The lines of *leaf* in the body type: without the running head and the
    footnotes, which run from the first small or closely set line to the foot
    of the page, most of the lines from there on small (a note's line can be
    read taller, a body line seldom shorter)."""
    lines = list(leaf.lines)
    if lines and _HEAD_RE.search(lines[0].text):
        lines = lines[1:]
    for i, ln in enumerate(lines):
        if statistics.median(x.height for x in lines[i:]) >= _NOTE_HEIGHT:
            continue
        tight = (i + 1 < len(lines) and lines[i + 1].top - ln.top < _NOTE_PITCH
                 and lines[i + 1].height < _NOTE_HEIGHT)
        if ln.height < _NOTE_HEIGHT or tight:
            return lines[:i]
    return lines


@dataclass
class Row:
    """A body line with its layout relative to the page."""
    text: str
    indent: float     # x0 minus the page's left margin
    leaf: int


def page_rows(leaf: _ia_djvu.Leaf) -> list[Row]:
    lines = body_lines(leaf)
    if not lines:
        return []
    xs = sorted(ln.x0 for ln in lines)
    margin = xs[len(xs) // 4]
    return [Row(ln.text.strip(), ln.x0 - margin, leaf.index) for ln in lines]


# ---------------------------------------------------------------------------
# Rows → units
# ---------------------------------------------------------------------------

def _join(a: str, b: str) -> str:
    """Join two lines of one unit, mending a word broken at the line end."""
    if not a:
        return b
    if a.endswith("-") and not a.endswith("--"):
        if re.search(r"(\S+)$", a).group(1) in KEPT_HYPHENS:
            return a + b
        return a[:-1] + b
    return f"{a} {b}"


def _continues(prev: str, text: str, indented: bool) -> bool:
    """Whether *text* continues the name on the line before (in a list of
    names one line is one name; a long one runs on to the next line, which
    starts in lower case, follows a hyphen or ``of``, or is indented)."""
    return (indented or text[:1].islower() or prev.endswith("-")
            or re.search(r"\bof$", prev) is not None)


_STRAY_RE = re.compile(r"^[_~|\\/]\s+|\s+[_~|\\/]$")


def part_units(part: Part, rows: list[Row]) -> list[tuple[str, str]]:
    """(mode, raw text) per unit of *part*, from its rows in reading order."""
    modes = list(part.modes)
    units: list[list[str]] = []          # [mode, text]
    started = False
    mode = "prose"
    last: Row | None = None
    for row in rows:
        text = _STRAY_RE.sub("", row.text).strip()
        if not started:
            if not text.startswith(part.start):
                continue
            started = True
        new = False
        for prefix, m in modes:
            if text.startswith(prefix):
                modes.remove((prefix, m))
                mode, new = m, True
                break
        if not new and units:
            if mode == "prose":
                new = row.indent > 40
            elif mode == "verse":
                new = text.startswith(part.stanzas)
            elif mode == "list":
                indented = (last is not None and last.leaf == row.leaf
                            and row.indent > last.indent + 40)
                new = (text.startswith(part.stanzas)
                       or not _continues(units[-1][1], text, indented))
        last = row
        if new or not units:
            units.append([mode, text])
        else:
            units[-1][1] = _join(units[-1][1], text)
        if part.end in text:
            break
    else:
        raise ValueError(f"{part.slug}: end line {part.end!r} not found")
    if modes:
        raise ValueError(f"{part.slug}: mode anchors not found: {modes}")
    return [(m, re.sub(r"\s+", " ", t).strip()) for m, t in units if m != "skip"]


def apply_corrections(slug: str, texts: list[str]) -> list[str]:
    """*texts* with :data:`CORRECTIONS` and then :data:`LETTERS` applied."""
    out = list(texts)
    for old, new, *count in CORRECTIONS[slug]:
        want = count[0] if count else 1
        found = sum(t.count(old) for t in out)
        if found != want:
            raise ValueError(f"{slug}: correction {old!r} must match {want} time(s), "
                             f"matched {found}")
        out = [t.replace(old, new) for t in out]
    for old, new in LETTERS:
        out = [t.replace(old, new) for t in out]
    # The book sets a thin space before ; : ? and ! (``sing ;``), which the OCR
    # reads as a space only sometimes.
    return [re.sub(r"\s+([;:?!])", r"\1", t) for t in out]


def build_units(part: Part, rows: list[Row]) -> list[dict]:
    raw = part_units(part, rows)
    texts = apply_corrections(part.slug, [t for _, t in raw])
    units = []
    for n, ((mode, raw_text), text) in enumerate(zip(raw, texts), start=1):
        unit: dict = {"ref": str(n), "text": text}
        if mode == "heading":
            unit["editorial"] = [[0, len(text), "heading"]]
        else:
            for prefix in part.numbered:
                if text.startswith(prefix):
                    unit["editorial"] = [[0, len(prefix.rstrip()), "heading"]]
        units.append(unit)
    return units


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def fetch(output_dir: Path, force: bool = False) -> Path:
    """The item's ``_djvu.xml`` (downloaded once into ``data/raw/_cache``)."""
    dest = output_dir / "_cache" / SOURCE_ID / f"{_ITEM}_djvu.xml"
    return download_file(_XML_URL, dest, etag_cache=False, force=force)


def make_work(part: Part) -> Work:
    return Work(
        work_id=f"{SOURCE_ID}/{part.slug}",
        source_id=SOURCE_ID,
        author=part.author,
        title=part.title,
        date_composed=part.date_composed,
        date_range=part.date_range,
        date_confidence=part.date_confidence,
        genre=part.genre,
        language="eng",
        tradition="syriac",
        license=LICENSE,
        provenance_url=_DETAILS,
        edition=EDITION.format(pages=part.pages),
        translation_of=part.translation_of if ORIGINALS_IN_CORPUS else None,
    )


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    out_dir = output_dir / SOURCE_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {p.slug: out_dir / f"{p.slug}.json" for p in PARTS}
    if not force and all(path.exists() for path in paths.values()):
        return [Work(**json.loads(path.read_text(encoding="utf-8"))["work"])
                for path in paths.values()]

    xml = fetch(output_dir, force)
    lo = min(p.first_leaf for p in PARTS)
    hi = max(p.last_leaf for p in PARTS)
    leaves: dict[int, _ia_djvu.Leaf] = {}
    for leaf in _ia_djvu.read_leaves(xml):
        number = leaf.index + 1
        if number > hi:
            break
        if number >= lo and number not in PLATES:
            leaves[number] = leaf

    works = []
    for part in PARTS:
        rows = [r for n in range(part.first_leaf, part.last_leaf + 1) if n in leaves
                for r in page_rows(leaves[n])]
        units = build_units(part, rows)
        work = make_work(part)
        record = {"work": work.model_dump(), "paragraphs": units}
        paths[part.slug].write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        log.info("%s: %d units", work.work_id, len(units))
        works.append(work)
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
