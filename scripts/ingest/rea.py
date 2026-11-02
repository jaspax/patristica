"""
Ingestor for the Referenzkorpus Altdeutsch (ReA) 1.2: Old High German and Old Saxon (#567, part of #224).

Source:  Deutsch Diachron Digital – Referenzkorpus Altdeutsch (DDD-AD), version 1.2
         (Humboldt-Universität zu Berlin and partners, 2022), in the LAUDATIO repository:
         https://www.laudatio-repository.org/browse/corpus/MiXVDnMB7CArCQ9CABmW/corpora
Format:  relANNIS 3.3 (one directory of tab-separated ``.annis`` tables per sub-corpus)
License: CC BY-NC-SA 3.0 ("Open Source Projekt, CC-BY-NC-SA 3.0.", the corpus header's
         ``<availability>``, ``<licence target="https://creativecommons.org/licenses/by-nc-sa/3.0/">``)

ReA covers all Old High German and Old Saxon texts from c. 750 to c. 1050 (about 650,000
words), each from the printed edition closest to the manuscript, with linguistic
annotation. The relANNIS export is downloaded once (``download_file``, cached under
``data/raw/_zips/``) and read from the zip: the outer zip holds one inner zip, which
holds ``corpora/{sub-corpus}/{table}.annis``.

What is ingested (:data:`TEXTS`)
--------------------------------
One work per text, with the language ReA tags it with (``goh`` for ``ahd.``, ``osx`` for
``as.``, ``lat`` for the Latin sides), checked against ReA's document metadata. Christian
texts are kept and secular ones left out (the survey on #224): Tatian (with its Latin
side), Otfrid, the *Heliand* and the Old Saxon *Genesis*, the Isidor and the Monsee
fragments, the Murbach Hymns (with the Latin hymns), Notker's Psalter, *Cantica* and
Boethius, and the religious minor texts. :data:`DROPPED` lists what is left out and why.

The text layer
--------------
ReA has two segmentations of the same timeline: ``edition``, the edition's own word
division, and ``text``, a tokenization for the linguistic layers (clitics and compounds
split, words broken across lines joined). The ``edition`` layer is stored, except for the
Isidor, whose edition layer runs words together and glues the section numbers to them
(``inansuntot7``), so its ``text`` layer is used. Tokens are joined with spaces, with no
space before closing punctuation or after opening brackets and quotes. Notation:

- a run of ``*`` tokens, or of two or more ``.`` tokens, is the edition's mark for lost
  letters or words: it becomes ``[…]``, marked ``lacuna`` (#236);
- ``<…>`` and ``(…)`` inside a word are letters the editor supplied: kept, marked
  ``supplement`` (so search and the embedder read the word whole);
- ``{…}`` (expanded abbreviations) keep their letters, without the braces;
- ``_`` (Notker's editions: words the manuscript writes together) becomes a space;
- a line-final hyphen in the Notker and Tatian editions (``SÂ-`` ``lig``) is joined;
- page and line numbers printed in the text (``( 84 )``, ``[ 227 ]``), stray ``[``,
  ``]`` and ``/`` (line breaks in titles) and ``°`` are layout and are dropped, as is
  a section number printed at the start of a unit (``5 .``).

Notker's Latin lemmata stay in the text as he wrote it: they are the text he translates
and comments on, not editorial material, so they are not marked.

Units and references
--------------------
Refs follow the editions' numbering, each work with its own prefix:

- verse-numbered texts are ingested as ``verses`` (no derived verses): Tatian by
  Sievers's chapter and verse (``Tat.12.3``; the prologue is chapter 0) and the
  Murbach Hymns by hymn and strophe (both sides of a bilingual pair, kept as units);
- the poems are ingested as ``paragraphs``, their lines grouped (#586) into units at the
  edition's number of the unit's first line, which normalize cuts into derived verses
  where they are long. ReA's lines are the editions' long lines, so a scholar's line
  number falls in the unit whose first line is the last one at or before it:

  - alliterative and unrhymed verse by the ASPR rule (``scripts/ingest/aspr.py``, #572;
    :func:`sentence_units`): a unit runs from a line to the next line that *ends* a
    sentence, since sentences often end at the caesura. The *Heliand* by fitt and first
    line (``Hel.{fitt}.{line}``; Behaghel's lines run on through the poem, 1–5983, and a
    fitt may start mid-line, so such a line ends one fitt and opens the next one's first
    unit), the *Genesis* by fragment and line (``AsGen.{fragment}.{line}``), *Muspilli*,
    the *Wessobrunn Prayer*, the *Augsburg Prayer* (its Latin collect, then the rhymed
    German) and the *Carmen ad Deum* (an interlinear gloss);
  - Otfrid by couplet (:func:`couplet_units`): one unit per strophe of two long lines,
    ``Otfr.{book}.{chapter}.{odd line}``, and so the dedications (``Otfr.L``/``S``/``H.{line}``,
    whose acrostic and telestich run by these strophes); each book's Latin capitula stay
    one unit each (``Otfr.{book}.0.{n}``), and the chapter titles units of their own;
  - the other rhymed poems by strophe (:func:`strophe_units`): a unit is at least a
    couplet and runs on to the next line that ends a sentence, so that their three-line
    strophes stay whole, and a refrain closes its strophe (the *Petruslied*'s Kyrie, the
    *Georgslied*'s "Daz giteta selbo … Gorio"); a strophe number the edition prints
    (Tschirch's *Georgslied*) always starts a unit. The *Ludwigslied*, *Georgslied*,
    *Petruslied*, *Christus und die Samariterin* and *Psalm 138*;
- prose is ingested as ``paragraphs`` (split into derived verses by normalize): the
  Isidor by chapter and section, Notker's Psalter by psalm and page of Tax's edition
  (``NPs.1.9``), the *Cantica* by canticle and page, the Boethius by book and ReA's
  section, the Monsee fragments by Hench's fragment number, the Latin Tatian by chapter,
  and each minor prose text as one paragraph (or one per section where ReA has them).

Words before a text's first numbered unit (a chapter title) become a heading unit at the
section's ref; words a unit layer leaves uncovered after that go with the preceding unit.
Otfrid I,2 has misaligned verse spans in ReA, so its lines are rebuilt from the rhyme
marks (every second rhyme word, and its punctuation, ends a long line).
"""

from __future__ import annotations

import io
import json
import logging
import re
import zipfile
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from patristica.models import Work
from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

SOURCE_ID = "rea"

CORPUS_URL = "https://www.laudatio-repository.org/download/format/1/53/1.2"
RECORD_URL = "https://www.laudatio-repository.org/browse/corpus/MiXVDnMB7CArCQ9CABmW/corpora"
ZIP_NAME = "rea-relannis-1.2.zip"
LICENSE = "cc-by-nc-sa-3.0"

REA = ("Referenzkorpus Altdeutsch (DDD-AD) 1.2, Humboldt-Universität zu Berlin et al. (2022), "
       "LAUDATIO repository")

_STEINMEYER = ("Elias von Steinmeyer, Die kleineren althochdeutschen Sprachdenkmäler "
               "(Berlin 1916; repr. Dublin/Zürich 1971)")
_WADSTEIN = "Elis Wadstein, Kleinere altsächsische Sprachdenkmäler (Norden/Leipzig 1899)"
_BRAUNE = "Wilhelm Braune and Ernst A. Ebbinghaus, Althochdeutsches Lesebuch (Tübingen 1994)"

#: ReA ``language`` metadata → our code (checked against each work's config).
REA_LANGUAGES = {"ahd.": "goh", "spätahd.": "goh", "ahd.lat": "goh", "as.": "osx",
                 "as.ags": "osx", "as.lat": "osx", "lat.": "lat"}

#: Annotation names read from ``node_annotation.annis``.
_SPAN_NAMES = frozenset({"chapter", "subchapter", "verse", "page", "line", "rhyme"})

LACUNA = "[…]"


class ReAError(ValueError):
    """The relANNIS data is not structured as this ingestor expects."""


# ---------------------------------------------------------------------------
# relANNIS reading
# ---------------------------------------------------------------------------

@dataclass
class Document:
    """One ReA document: its tokens on one segmentation and its annotation spans."""

    name: str
    meta: dict[str, str]
    #: (left, right, value) of the segmentation's tokens, by position.
    tokens: list[tuple[int, int, str]] = field(default_factory=list)
    #: name → [(left, right, value)], sorted.
    spans: dict[str, list[tuple[int, int, str]]] = field(default_factory=dict)


def _rows(text: str) -> Iterator[list[str]]:
    for line in text.splitlines():
        if line:
            yield line.split("\t")


def read_subcorpus(tables: dict[str, str], layer: str = "edition") -> dict[str, Document]:
    """The documents of one relANNIS sub-corpus, from its tables' text by table name.

    Uses ``corpus``, ``corpus_annotation``, ``node`` and ``node_annotation``. Node rows
    are relANNIS 3.3: ``id, text_ref, corpus_ref, layer, name, left, right, token_index,
    left_token, right_token, seg_index, seg_name, span, is_token``; a segmentation token
    has ``seg_name`` set (``edition`` or ``text``) and its value in ``span``.
    """
    corpus: dict[str, tuple[str, str]] = {}
    for f in _rows(tables["corpus"]):
        corpus[f[0]] = (f[1], f[2])
    corpus_meta: dict[str, dict[str, str]] = defaultdict(dict)
    for f in _rows(tables["corpus_annotation"]):
        corpus_meta[f[0]][f[2]] = f[3]
    top = [cid for cid, (_, kind) in corpus.items() if kind == "CORPUS"]
    top_meta = corpus_meta.get(top[0], {}) if top else {}
    docs: dict[str, Document] = {}
    for cid, (name, kind) in corpus.items():
        if kind == "DOCUMENT":
            docs[cid] = Document(name=name, meta={**top_meta, **corpus_meta.get(cid, {})})
    wanted: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for f in _rows(tables["node_annotation"]):
        if f[2] in _SPAN_NAMES:
            wanted[f[0]].append((f[2], f[3]))
    spans: dict[str, dict[str, list[tuple[int, int, str]]]] = defaultdict(lambda: defaultdict(list))
    for f in _rows(tables["node"]):
        doc = docs.get(f[2])
        if doc is None:
            continue
        left, right = int(f[8]), int(f[9])
        if f[11] == layer:
            doc.tokens.append((left, right, f[12]))
        for name, value in wanted.get(f[0], ()):
            spans[f[2]][name].append((left, right, value))
    for cid, doc in docs.items():
        doc.tokens.sort()
        doc.spans = {k: sorted(v) for k, v in spans[cid].items()}
    return {doc.name: doc for doc in docs.values()}


class Corpus:
    """The relANNIS export: sub-corpora read on demand from the (nested) zip."""

    _TABLES = ("corpus", "corpus_annotation", "node", "node_annotation")

    def __init__(self, zip_path: Path) -> None:
        outer = zipfile.ZipFile(zip_path)
        inner_names = [n for n in outer.namelist() if n.endswith(".zip")]
        if len(inner_names) != 1:
            raise ReAError(f"{zip_path}: expected one inner zip, found {inner_names}")
        self._zip = zipfile.ZipFile(io.BytesIO(outer.read(inner_names[0])))
        self._cache: dict[tuple[str, str], dict[str, Document]] = {}

    def subcorpus(self, name: str, layer: str = "edition") -> dict[str, Document]:
        key = (name, layer)
        if key not in self._cache:
            tables = {t: self._zip.read(f"corpora/{name}/{t}.annis").decode("utf-8")
                      for t in self._TABLES}
            self._cache[key] = read_subcorpus(tables, layer)
        return self._cache[key]


# ---------------------------------------------------------------------------
# Text assembly
# ---------------------------------------------------------------------------

_CLOSING = frozenset({",", ".", ";", ":", "!", "?", ")", "]", "«"})
_OPENING = frozenset({"(", "[", "»"})
_DROP_TOKENS = frozenset({"[", "]", "#"})
_INNER_SUPPLEMENT = re.compile(r"<[^<>\s]+>|\([^()\s]+\)")
_NUMBER = re.compile(r"\d+")


def _clean_token(tok: str) -> str:
    """One token without layout signs: ``/`` and ``|`` (line and page breaks in titles
    and in Wadstein's Old Saxon texts, also inside a word: ``gi|deda``), ``(-)`` (the
    editor's hyphen at such a break), ``°``, the braces of an expansion; ``_`` (two
    words the manuscript writes together) becomes a space."""
    tok = tok.replace("(-)", "")
    for ch in "/|°{}#":
        tok = tok.replace(ch, "")
    return tok.replace("_", " ").strip()


def _is_gap_token(tok: str) -> bool:
    return bool(tok) and set(tok) <= {".", "*"}


def _drop_printed_numbers(toks: list[str]) -> list[str]:
    """Drop page and line numbers the edition prints in brackets: ``( 84 )``, ``[ 227 ]``."""
    out: list[str] = []
    i = 0
    while i < len(toks):
        if (toks[i] in ("(", "[") and i + 2 < len(toks) and _NUMBER.fullmatch(toks[i + 1])
                and toks[i + 2] == {"(": ")", "[": "]"}[toks[i]]):
            i += 3
            continue
        out.append(toks[i])
        i += 1
    return out


def _join_hyphens(toks: list[str]) -> list[str]:
    """Join a word broken at a line end with a hyphen (``SÂ-`` ``lig`` → ``SÂlig``)."""
    out: list[str] = []
    for tok in toks:
        if out and re.search(r"\w-$", out[-1]) and tok[:1].isalpha():
            out[-1] = out[-1][:-1] + tok
        else:
            out.append(tok)
    return out


def assemble(tokens: Iterable[str], *, join_hyphens: bool = False,
             drop_leading_number: bool = True) -> tuple[str, list[list[Any]]]:
    """A unit's text from its edition tokens, and its editorial spans."""
    toks = [t for t in (_clean_token(t) for t in tokens) if t]
    toks = _drop_printed_numbers(toks)
    toks = [t for t in toks if t not in _DROP_TOKENS]
    if join_hyphens:
        toks = _join_hyphens(toks)
    if drop_leading_number and len(toks) > 2 and _NUMBER.fullmatch(toks[0]) and toks[1] == ".":
        toks = toks[2:]
    # Gap runs: any run of '*' tokens, or of two or more '.' tokens.
    pieces: list[tuple[str, str | None]] = []  # (text, editorial kind)
    i = 0
    while i < len(toks):
        if _is_gap_token(toks[i]):
            j = i
            while j < len(toks) and _is_gap_token(toks[j]):
                j += 1
            run = toks[i:j]
            if len(run) >= 2 and run[0] == "." and run[1] != ".":
                # A full stop before a lacuna: punctuation, not part of the gap.
                pieces.append((".", None))
                i += 1
                run = run[1:]
            if "*" in "".join(run) or len(run) >= 2 or len(run[0]) >= 2:
                if not (pieces and pieces[-1][1] == "lacuna"):
                    pieces.append((LACUNA, "lacuna"))
                i = j
                continue
        pieces.append((toks[i], None))
        i += 1
    text = ""
    spans: list[list[Any]] = []
    quote_open = False
    prev = ""
    for tok, kind in pieces:
        sep = " "
        if not text:
            sep = ""
        elif tok in _CLOSING and kind is None:
            sep = ""
        elif prev in _OPENING:
            sep = ""
        elif tok == '"':
            sep = "" if quote_open else " "
        elif prev == '"' and quote_open:
            sep = ""
        if tok == '"':
            quote_open = not quote_open
        text += sep
        start = len(text)
        text += tok
        if kind:
            spans.append([start, len(text), kind])
        else:
            for m in _INNER_SUPPLEMENT.finditer(tok):
                spans.append([start + m.start(), start + m.end(), "supplement"])
        prev = tok
    return text, spans


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

@dataclass
class Unit:
    ref: str
    tokens: list[str] = field(default_factory=list)
    #: The edition's line (or verse) number of a numbered unit (``"4517b"``); None for a
    #: heading or a unit whose label is not a number.
    line: str | None = None
    #: The tokens of each line of a unit grouped from lines (#586), else None.
    lines: list[list[str]] | None = None


class _SpanIndex:
    """Which span of a sorted, non-overlapping list covers a token position."""

    def __init__(self, spans: list[tuple[int, int, str]]) -> None:
        self.spans = spans
        self.starts = [s[0] for s in spans]

    def value(self, pos: int) -> str | None:
        i = bisect_right(self.starts, pos) - 1
        if i >= 0 and self.spans[i][0] <= pos <= self.spans[i][1]:
            return self.spans[i][2]
        return None


#: Labels of spans that carry no number: ``n/a``, and ``NA`` on the titles of Otfrid
#: I,17 and III,25 (which are their chapters' titles, like every other chapter's).
_UNNUMBERED = frozenset({"n/a", "NA"})


def _numbered(spans: list[tuple[int, int, str]]) -> list[tuple[int, int, str]]:
    return [s for s in spans if s[2] not in _UNNUMBERED]


def rhyme_lines(doc: Document) -> list[tuple[int, int, str]]:
    """Otfrid's long lines rebuilt from the rhyme marks: a line ends after every second
    rhyme word and the punctuation that follows it. The words before the first line
    (the chapter title) are left out; numbering starts at 1."""
    rhymes = {r for _, r, _ in doc.spans.get("rhyme", [])}
    # The title: up to the first numbered verse span's start (or the first rhyme's line).
    first = min((s[0] for s in _numbered(doc.spans.get("verse", []))), default=0)
    title_end = first - 1
    # Otfrid I,2's spans are one token late: the title ends one token earlier.
    positions = [left for left, _, _ in doc.tokens]
    if title_end >= 0 and positions:
        idx = positions.index(first) if first in positions else 0
        title_end = positions[idx - 1] - 1 if idx > 0 else -1
    lines: list[tuple[int, int, str]] = []
    start = None
    count = 0
    n = 0
    toks = doc.tokens
    i = 0
    while i < len(toks):
        left, right, value = toks[i]
        if left <= title_end:
            i += 1
            continue
        if start is None:
            start = left
        if right in rhymes:
            count += 1
            if count % 2 == 0:
                j = i + 1
                while j < len(toks) and toks[j][2] in _CLOSING | {'"'}:
                    j += 1
                n += 1
                lines.append((start, toks[j - 1][1], str(n)))
                start = None
                i = j
                continue
        i += 1
    if start is not None:
        n += 1
        lines.append((start, toks[-1][1], str(n)))
    return lines


def numbered_units(doc: Document, prefix: str, layer: str, *,
                   spans: list[tuple[int, int, str]] | None = None,
                   heading_ref: str | None = None) -> list[Unit]:
    """Units of one document by the numbered spans of *layer* (``n/a`` spans left out):
    ``{prefix}.{value}``. Words before the first unit form a heading at *heading_ref*
    (default *prefix*); uncovered words after it go with the preceding unit."""
    index = _SpanIndex(_numbered(spans if spans is not None else doc.spans.get(layer, [])))
    units: list[Unit] = []
    by_value: dict[str, Unit] = {}
    heading = Unit(heading_ref or prefix)
    current: Unit | None = None
    stray = 0
    for left, _, tok in doc.tokens:
        value = index.value(left)
        if value is None:
            if current is None:
                heading.tokens.append(tok)
            else:
                current.tokens.append(tok)
                if re.search(r"\w", tok):
                    stray += 1
            continue
        unit = by_value.get(value)
        if unit is None:
            unit = Unit(f"{prefix}.{_ref_part(value)}",
                        line=value if _LINE_NUMBER.fullmatch(value) else None)
            by_value[value] = unit
            units.append(unit)
        elif unit is not current:
            raise ReAError(f"{doc.name}: {layer} {value!r} is not contiguous")
        current = unit
        unit.tokens.append(tok)
    if stray:
        log.debug("%s: %d words outside a numbered %s span, kept with the preceding unit",
                  doc.name, stray, layer)
    if heading.tokens:
        if all(_is_gap_token(t) for t in heading.tokens) and units:
            units[0].tokens[:0] = heading.tokens
        else:
            units.insert(0, heading)
    return units


def block_units(doc: Document, ref_of: Callable[[str | None], str], key_layer: str | None) -> list[Unit]:
    """Units of one document as blocks: one per value of *key_layer* (a page, a section),
    or the whole document with ``key_layer=None``; *ref_of* maps the value to a ref.
    Words before the first key go with the first block."""
    index = _SpanIndex(_numbered(doc.spans.get(key_layer, [])) if key_layer else [])
    units: list[Unit] = []
    by_ref: dict[str, Unit] = {}
    pending: list[str] = []
    current: Unit | None = None
    for left, _, tok in doc.tokens:
        value = index.value(left) if key_layer else None
        if key_layer and value is None:
            (current.tokens if current else pending).append(tok)
            continue
        ref = ref_of(value)
        unit = by_ref.get(ref)
        if unit is None:
            unit = Unit(ref)
            by_ref[ref] = unit
            units.append(unit)
        unit.tokens.extend(pending)
        pending = []
        current = unit
        unit.tokens.append(tok)
    if pending and not units:
        units.append(Unit(ref_of(None), pending))
    return units


def _ref_part(value: str) -> str:
    """A ReA label as a ref segment: ``4,8`` (psalm and verse) → ``4.8``, other
    punctuation dropped (``Reg.I`` → ``RegI``)."""
    value = value.strip()
    if re.fullmatch(r"\d+,\d+", value):
        return value.replace(",", ".")
    return re.sub(r"[^\w]+", "", value)


# ---------------------------------------------------------------------------
# Verse units: lines grouped into sentences, couplets or strophes (#586)
# ---------------------------------------------------------------------------

_LINE_NUMBER = re.compile(r"\d+[a-z]?")
#: A line that ends a sentence: ``.``, ``!`` or ``?``, closing quotes and brackets aside
#: (the ASPR rule, ``scripts/ingest/aspr.py``; ReA's text may space a closing quote).
_SENTENCE_END = re.compile(r"[.!?][\s\"'”’)\]»«]*$")


def _ends_sentence(line: Unit) -> bool:
    return bool(_SENTENCE_END.search(assemble(line.tokens)[0]))


def _numbered_strophe(line: Unit) -> bool:
    """The line starts with a strophe number the edition prints (``1 .`` in Tschirch's
    *Georgslied*), which ``assemble`` drops at the start of a unit."""
    return assemble(line.tokens)[0] != assemble(line.tokens, drop_leading_number=False)[0]


def _joined(lines: list[Unit]) -> Unit:
    """One unit of consecutive lines, at the first line's ref."""
    parts = [part for line in lines for part in (line.lines or [line.tokens])]
    return Unit(lines[0].ref, [t for part in parts for t in part], lines[0].line, parts)


def assemble_unit(unit: Unit, *, join_hyphens: bool = False) -> tuple[str, list[list[Any]]]:
    """A unit's text and editorial spans. A unit grouped from lines is each line's text
    (assembled on its own, exactly as when every line was a unit) joined with a space,
    and its spans moved with it; a line that is only a lacuna stays, as ``[…]``. A stray
    quote mark (ReA's editions don't always close one) then can't upset the spacing of
    the lines after it."""
    if unit.lines is None:
        return assemble(unit.tokens, join_hyphens=join_hyphens)
    text = ""
    spans: list[list[Any]] = []
    for tokens in unit.lines:
        body, body_spans = assemble(tokens, join_hyphens=join_hyphens)
        if not body:
            continue
        if text:
            text += " "
        spans += [[s + len(text), e + len(text), k] for s, e, k in body_spans]
        text += body
    return text, spans


def _grouped(units: list[Unit], close: Callable[[list[Unit], Unit], bool],
             attach: Callable[[Unit], bool] = lambda _u: False) -> list[Unit]:
    """Numbered lines gathered into groups, each closed after a line for which
    ``close(group, line)`` holds; a unit that is not a numbered line (a heading) stands
    alone, and unclosed lines at the end of the section are a group of their own. A line
    that starts with a printed strophe number always starts a group, so the number is
    dropped as before and no group crosses the edition's strophes. A line for which
    ``attach(line)`` holds (a refrain) closes the open group, or joins the group just
    closed when none is open."""
    out: list[Unit] = []
    cur: list[Unit] = []
    closed = False  # out[-1] is a group of lines that a refrain may join

    def flush() -> None:
        nonlocal cur, closed
        if cur:
            out.append(_joined(cur))
            cur = []
            closed = True

    for unit in units:
        if unit.line is None:
            flush()
            out.append(unit)
            closed = False
            continue
        if _numbered_strophe(unit):
            flush()
            closed = False
        if attach(unit):
            if cur or not closed:
                cur.append(unit)
                flush()
            else:
                out[-1] = _joined([out[-1], unit])
            continue
        cur.append(unit)
        if close(cur, unit):
            flush()
    flush()
    return out


def sentence_units(units: list[Unit]) -> list[Unit]:
    """The ASPR rule (``scripts/ingest/aspr.py``, #572): a unit runs from a line to the
    next line that ends a sentence. For alliterative verse, whose sentences often end at
    the caesura; normalize cuts long units into derived verses."""
    return _grouped(units, lambda _group, line: _ends_sentence(line))


def couplet_units(units: list[Unit], where: str) -> list[Unit]:
    """One unit per couplet of long lines, (1, 2), (3, 4), …: Otfrid's strophes, which
    the acrostics of his dedications confirm. Every chapter has an even number of
    lines, numbered from 1 without gaps; anything else is an error."""
    lines = [u for u in units if u.line is not None]
    numbers = [u.line for u in lines]
    if numbers != [str(n) for n in range(1, len(lines) + 1)] or len(lines) % 2:
        raise ReAError(f"{where}: lines {numbers[:3]}…{numbers[-3:]} ({len(lines)}) are not "
                       "couplets numbered from 1")
    return _grouped(units, lambda group, _line: len(group) == 2)


def strophe_units(refrain: str | None = None) -> Callable[[list[Unit]], list[Unit]]:
    """Rhymed couplet verse whose strophes are of two or three long lines: a unit is at
    least a couplet and runs on to the next line that ends a sentence (so a three-line
    strophe stays whole), and a refrain line matching *refrain* closes its strophe."""
    rx = re.compile(refrain) if refrain else None

    def build(units: list[Unit]) -> list[Unit]:
        return _grouped(units, lambda group, line: len(group) >= 2 and _ends_sentence(line),
                        (lambda u: bool(rx.search(assemble(u.tokens)[0]))) if rx else (lambda _u: False))
    return build


def roman_to_int(s: str) -> int:
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    for i, ch in enumerate(s):
        v = vals[ch]
        total += -v if i + 1 < len(s) and vals[s[i + 1]] > v else v
    return total


# ---------------------------------------------------------------------------
# Works
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Text:
    slug: str
    title: str
    subcorpus: str
    language: str
    genre: str
    author: str | None
    date_range: tuple[int, int] | None
    date_composed: int | None
    date_confidence: str
    edition: str
    #: Builds the work's units from its sub-corpus documents.
    build: Callable[[dict[str, Document]], list[Unit]]
    as_verses: bool
    layer: str = "edition"
    join_hyphens: bool = False
    #: ReA document names of the work (None: built by ``build`` itself).
    docs: tuple[str, ...] | None = None


def _num(name: str) -> int:
    return int(re.findall(r"\d+", name)[-1])


def _sorted_docs(docs: dict[str, Document], pattern: str,
                 key: Callable[[str], Any] = _num) -> list[Document]:
    rx = re.compile(pattern)
    return [docs[n] for n in sorted((n for n in docs if rx.fullmatch(n)), key=key)]


def _tatian(docs: dict[str, Document]) -> list[Unit]:
    units: list[Unit] = []
    for doc in _sorted_docs(docs, r"T_Tat\d+"):
        chapters = _numbered(doc.spans.get("chapter", []))
        chapter = chapters[0][2] if chapters else "0"
        units += numbered_units(doc, f"Tat.{chapter}", "subchapter")
    return units


def _tatian_latin(docs: dict[str, Document]) -> list[Unit]:
    """The Latin chapters. ReA gives five chapters' Latin twice under the next document
    (40, 90, 95, 131 and 145 repeat 39, 89, 94, 130 and 144): the copy is skipped, so
    those five chapters have no Latin here."""
    units: list[Unit] = []
    seen: dict[str, list[str]] = {}
    for doc in _sorted_docs(docs, r"T_Tatian[Ll]atein_\(\d+\)"):
        chapters = _numbered(doc.spans.get("chapter", []))
        chapter = chapters[0][2] if chapters else "0"
        words = [t for _, _, t in doc.tokens]
        if f"Tat.{chapter}" in seen:
            if seen[f"Tat.{chapter}"] != words:
                raise ReAError(f"{doc.name}: a second, different Latin chapter {chapter}")
            log.warning("%s repeats the Latin of chapter %s; skipped (ReA has no Latin for "
                        "chapter %d)", doc.name, chapter, _num(doc.name))
            continue
        seen[f"Tat.{chapter}"] = words
        units += block_units(doc, lambda _v, c=chapter: f"Tat.{c}", None)
    return units


_OTFRID_RHYME_LINES = frozenset({"O_Otfr.Ev.1.2"})


def _otfrid_order(docs: dict[str, Document]) -> list[tuple[Document, str]]:
    """Otfrid's documents in Erdmann's order, each with its ref prefix."""
    out: list[tuple[Document, str]] = [(docs["O_Otfr.Ludw"], "Otfr.L"), (docs["O_Otfr.Salom"], "Otfr.S")]
    for book in range(1, 6):
        for suffix in ("_", "_.a", "_.b"):
            name = f"O_Otfr.Ev.{book}.{suffix}"
            if name in docs:
                out.append((docs[name], f"Otfr.{book}.0"))
        chapters = sorted((n for n in docs if re.fullmatch(rf"O_Otfr\.Ev\.{book}\.\d+", n)), key=_num)
        out += [(docs[n], f"Otfr.{book}.{_num(n)}") for n in chapters]
    out.append((docs["O_Otfr.Hartm"], "Otfr.H"))
    return out


def _otfrid(docs: dict[str, Document]) -> list[Unit]:
    units: list[Unit] = []
    for doc, prefix in _otfrid_order(docs):
        spans = rhyme_lines(doc) if doc.name in _OTFRID_RHYME_LINES else None
        lines = numbered_units(doc, prefix, "verse", spans=spans)
        # The Latin capitula stay one unit each; every chapter and dedication is couplets.
        units += lines if prefix.endswith(".0") else couplet_units(lines, doc.name)
    return _merge_same_ref(units)


def _merge_same_ref(units: list[Unit]) -> list[Unit]:
    """Join consecutive units with one ref (a book's heading split over two documents)."""
    out: list[Unit] = []
    for unit in units:
        if out and out[-1].ref == unit.ref:
            out[-1].tokens += unit.tokens
        else:
            out.append(unit)
    return out


def _otfrid_liutbert(docs: dict[str, Document]) -> list[Unit]:
    return block_units(docs["O_Otfr.Liutb"], lambda _v: "OtfrLiutb.1", None)


def _heliand(docs: dict[str, Document]) -> list[Unit]:
    units: list[Unit] = []
    for doc in _sorted_docs(docs, r"Hel_\d+"):
        label = _numbered(doc.spans["chapter"])[0][2].rstrip("*")  # XXXIII*: number not in M
        fitt = roman_to_int(label)
        if fitt != _num(doc.name):
            raise ReAError(f"{doc.name}: fitt {label}")
        units += sentence_units(numbered_units(doc, f"Hel.{fitt}", "verse"))
    return units


def _genesis(docs: dict[str, Document]) -> list[Unit]:
    units: list[Unit] = []
    for doc in _sorted_docs(docs, r"Gen_\d+"):
        units += sentence_units(numbered_units(doc, f"AsGen.{_num(doc.name)}", "verse"))
    return units


def _without_section_numbers(doc: Document) -> Document:
    """*doc* without the section numbers its edition prints (a number token and its
    ``.``): in the Isidor they fall on either side of a section boundary."""
    toks = doc.tokens
    keep: list[tuple[int, int, str]] = []
    i = 0
    while i < len(toks):
        if _NUMBER.fullmatch(toks[i][2]) and i + 1 < len(toks) and toks[i + 1][2] == ".":
            i += 2
            continue
        keep.append(toks[i])
        i += 1
    return Document(doc.name, doc.meta, keep, doc.spans)


def _isidor(docs: dict[str, Document]) -> list[Unit]:
    units: list[Unit] = []
    for doc in _sorted_docs(docs, r"I_DeFide_\d+"):
        chapter = _numbered(doc.spans["chapter"])[0][2]
        units += numbered_units(_without_section_numbers(doc), f"Isid.{chapter}", "subchapter")
    return units


def _monsee(code: str) -> Callable[[dict[str, Document]], list[Unit]]:
    def build(docs: dict[str, Document]) -> list[Unit]:
        rx = re.compile(rf"MF[-_]\d_{code}\.([IVXL]+)")
        names = sorted((n for n in docs if rx.fullmatch(n)), key=lambda n: roman_to_int(rx.fullmatch(n).group(1)))
        return [u for n in names
                for u in block_units(docs[n], lambda _v, n=n: f"Mons.{roman_to_int(rx.fullmatch(n).group(1))}", None)]
    return build


def _murbach(pattern: str) -> Callable[[dict[str, Document]], list[Unit]]:
    def build(docs: dict[str, Document]) -> list[Unit]:
        rx = re.compile(pattern)
        names = sorted((n for n in docs if rx.fullmatch(n)), key=lambda n: roman_to_int(rx.fullmatch(n).group(1)))
        return [u for n in names
                for u in numbered_units(docs[n], f"MH.{roman_to_int(rx.fullmatch(n).group(1))}", "chapter")]
    return build


def _benedict(docs: dict[str, Document]) -> list[Unit]:
    """The Rule by chapter (``RB.{chapter}``, the prologue ``RB.0``), in both columns of
    St. Gall 916 (``B_{n}``; the Latin ``B_{n}_lat``, two ``B_{n}_J``). ReA has chapters
    0-49 and 53-67."""
    rx = re.compile(r"B_(\d+)(?:_lat|_J)?")
    names = sorted((n for n in docs if rx.fullmatch(n)), key=lambda n: int(rx.fullmatch(n).group(1)))
    units: list[Unit] = []
    for name in names:
        n = int(rx.fullmatch(name).group(1))
        units += block_units(docs[name], lambda _v, n=n: f"RB.{n}", None)
    return units


def _notker_psalter(docs: dict[str, Document]) -> list[Unit]:
    units: list[Unit] = []
    for doc in _sorted_docs(docs, r"N_Ps_\d+"):
        psalm = _num(doc.name)
        units += block_units(doc, lambda v, p=psalm: f"NPs.{p}.{_ref_part(v or '0')}", "page")
    return units


def _notker_cantica(docs: dict[str, Document]) -> list[Unit]:
    units: list[Unit] = []
    for doc in _sorted_docs(docs, r"N_Cant_\d+(_\w+)?", key=lambda n: int(n.split("_")[2])):
        n = int(doc.name.split("_")[2])
        units += block_units(doc, lambda v, n=n: f"NCant.{n}.{_ref_part(v or '0')}", "page")
    return units


def _notker_boethius(docs: dict[str, Document]) -> list[Unit]:
    def key(name: str) -> tuple[int, int]:
        m = re.fullmatch(r"N_Decon(\d)_(\d+)", name)
        return int(m.group(1)), int(m.group(2))
    units: list[Unit] = []
    for doc in _sorted_docs(docs, r"N_Decon\d_\d+", key=key):
        book, n = key(doc.name)
        units += block_units(doc, lambda _v, b=book, n=n: f"NBo.{b}.{n}", None)
    return units


def _minor_verse(doc_name: str, prefix: str,
                 group: Callable[[list[Unit]], list[Unit]] | None) -> Callable[[dict[str, Document]], list[Unit]]:
    """A short poem by Steinmeyer's (or Tschirch's) lines, grouped by *group* (or one
    unit per line): ``{prefix}.{first line}``, a title before line 1 at ``{prefix}.0``."""
    def build(docs: dict[str, Document]) -> list[Unit]:
        lines = numbered_units(docs[doc_name], prefix, "line", heading_ref=f"{prefix}.0")
        return group(lines) if group else lines
    return build


def _minor_prose(doc_name: str, prefix: str) -> Callable[[dict[str, Document]], list[Unit]]:
    """A short prose text: one paragraph ``{prefix}.1``, or one per section where ReA
    divides it (``{prefix}.{section}``)."""
    def build(docs: dict[str, Document]) -> list[Unit]:
        doc = docs[doc_name]
        sections = {v for _, _, v in _numbered(doc.spans.get("chapter", []))}
        if len(sections) > 1:
            return block_units(doc, lambda v: f"{prefix}.{_ref_part(v or '0')}", "chapter")
        return block_units(doc, lambda _v: f"{prefix}.1", None)
    return build


_KAD = "DDD-AD-Kleinere_Althochdeutsche_Denkmäler"
_KAS = "DDD-AD-Kleinere_Altsächsische_Denkmäler"


def _minor(slug: str, doc: str, prefix: str, title: str, *, verse: bool = False,
           group: Callable[[list[Unit]], list[Unit]] | None = None, genre: str = "liturgical", language: str = "goh", author: str | None = None,
           date_range: tuple[int, int] | None = None, date_composed: int | None = None,
           confidence: str = "approximate", edition: str = _STEINMEYER,
           subcorpus: str = _KAD) -> Text:
    return Text(slug=slug, title=title, subcorpus=subcorpus, language=language, genre=genre,
                author=author, date_range=date_range, date_composed=date_composed,
                date_confidence=confidence, edition=edition,
                build=_minor_verse(doc, prefix, group) if verse else _minor_prose(doc, prefix),
                as_verses=verse and group is None, docs=(doc,))


#: Refrains that close a strophe: the *Georgslied*'s "Daz giteta selbo … Gorio" lines and
#: "die heidenon man giskanta Gorio … fram", the *Petruslied*'s Kyrie.
_GEORG_REFRAIN = r"^(Daz (giteta|zeichan|kunta|irdigita) |die heidenon man giskanta)"
_PETR_REFRAIN = r"^K[iy]r[iy]e"

TEXTS: tuple[Text, ...] = (
    # --- The major Old High German texts -----------------------------------------------
    Text("tatian", "Tatian (Old High German Gospel Harmony)", "DDD-AD-Tatian", "goh", "patristic",
         "Tatian", (825, 835), 830, "approximate",
         "Eduard Sievers, Tatian. Lateinisch und altdeutsch mit ausführlichem Glossar "
         "(Paderborn 1872): St. Gallen, Stiftsbibliothek, Cod. 56 (Fulda)",
         _tatian, as_verses=True, join_hyphens=True),
    Text("tatian-lat", "Tatian (Latin Gospel Harmony of the St. Gallen bilingual)",
         "DDD-AD-Tatian_Latein", "lat", "patristic", "Tatian", (541, 546), None, "approximate",
         "Eduard Sievers, Tatian. Lateinisch und altdeutsch mit ausführlichem Glossar "
         "(Paderborn 1872): the Latin column of St. Gallen, Stiftsbibliothek, Cod. 56, "
         "the harmony of Victor of Capua's Codex Fuldensis",
         _tatian_latin, as_verses=False),
    Text("otfrid", "Evangelienbuch (Liber evangeliorum)", "DDD-AD-Otfrid", "goh", "patristic",
         "Otfrid von Weißenburg", (863, 871), 868, "approximate",
         "Oskar Erdmann, Otfrids Evangelienbuch, 6th ed. by Ludwig Wolff (Tübingen 1973): "
         "Vienna, Österreichische Nationalbibliothek, Cod. 2687",
         _otfrid, as_verses=False),
    Text("otfrid-ad-liutbertum", "Ad Liutbertum (Otfrid's Latin letter to Archbishop Liutbert)",
         "DDD-AD-Otfrid", "lat", "patristic", "Otfrid von Weißenburg", (863, 871), None,
         "approximate",
         "Oskar Erdmann, Otfrids Evangelienbuch, 6th ed. by Ludwig Wolff (Tübingen 1973)",
         _otfrid_liutbert, as_verses=False),
    Text("isidor", "Isidor (Old High German translation of Isidore, De fide catholica)",
         "DDD-AD-Isidor", "goh", "patristic", "Isidorus Hispalensis", (790, 810), None,
         "approximate",
         "Hans Eggers, Der althochdeutsche Isidor (Tübingen 1964): Paris, Bibliothèque "
         "nationale, Ms. lat. 2326",
         _isidor, as_verses=False, layer="text"),
    Text("monsee-matthew", "Monsee Fragments: Gospel of Matthew", "DDD-AD-Monsee", "goh",
         "patristic", None, (790, 810), None, "approximate",
         "George A. Hench, The Monsee Fragments (Strassburg 1890), fragments I–XXV: Vienna, "
         "Österreichische Nationalbibliothek, Cod. 3093*",
         _monsee("M"), as_verses=False),
    Text("monsee-de-vocatione-gentium", "Monsee Fragments: De vocatione gentium", "DDD-AD-Monsee",
         "goh", "patristic", None, (790, 810), None, "approximate",
         "George A. Hench, The Monsee Fragments (Strassburg 1890), fragments XXVI–XXXI",
         _monsee("VG"), as_verses=False),
    Text("monsee-isidor", "Monsee Fragments: Isidore, De fide catholica", "DDD-AD-Monsee", "goh",
         "patristic", "Isidorus Hispalensis", (790, 810), None, "approximate",
         "George A. Hench, The Monsee Fragments (Strassburg 1890), fragments XXXII–XXXVI",
         _monsee("FC"), as_verses=False),
    Text("monsee-augustine-sermo-76", "Monsee Fragments: Augustine, Sermo 76", "DDD-AD-Monsee",
         "goh", "patristic", "Augustinus", (790, 810), None, "approximate",
         "George A. Hench, The Monsee Fragments (Strassburg 1890), fragments XXXVII–XL",
         _monsee("AS"), as_verses=False),
    Text("monsee-homily", "Monsee Fragments: Fragment of a Homily", "DDD-AD-Monsee", "goh",
         "patristic", None, (790, 810), None, "approximate",
         "George A. Hench, The Monsee Fragments (Strassburg 1890), fragment XLI",
         _monsee("FH"), as_verses=False),
    Text("murbach-hymns", "Murbach Hymns (Murbacher Hymnen)", "DDD-AD-Murbacher_Hymnen", "goh",
         "liturgical", None, (800, 825), None, "approximate",
         "Eduard Sievers, Die Murbacher Hymnen (Halle 1874): Oxford, Bodleian Library, "
         "MS Junius 25",
         _murbach(r"MH_Murb\.H\.([IVXL]+)"), as_verses=True),
    Text("murbach-hymns-lat", "Murbach Hymns (the Latin hymns)", "DDD-AD-Murbacher_Hymnen_Latein",
         "lat", "liturgical", None, (400, 800), None, "uncertain",
         "Eduard Sievers, Die Murbacher Hymnen (Halle 1874): the Latin text of Oxford, "
         "Bodleian Library, MS Junius 25",
         _murbach(r"MH_Murb\.H\.([IVXL]+)GK"), as_verses=True),
    Text("benedictine-rule", "Benedictine Rule (Old High German interlinear version of St. Gall 916)",
         "DDD-AD-Benediktiner_Regel", "goh", "patristic", "Benedictus Nursinus", (790, 830), None,
         "approximate",
         f"{_STEINMEYER}, no. 35 (Benediktinerregel): St. Gallen, Stiftsbibliothek, Cod. 916; the "
         "German glosses only part of the Latin, and the edition's dots for the unglossed words are "
         "marked as lacunae",
         _benedict, as_verses=False),
    Text("benedictine-rule-lat", "Regula Benedicti (the Latin text of St. Gall 916)",
         "DDD-AD-Benediktiner_Regel_Latein", "lat", "patristic", "Benedictus Nursinus", (530, 560), None,
         "approximate",
         "the Latin column of St. Gallen, Stiftsbibliothek, Cod. 916, as in ReA (chapters 0–49 and 53–67)",
         _benedict, as_verses=False),
    # --- Notker -----------------------------------------------------------------------
    Text("notker-psalter", "Der Psalter (Notker's Psalter with commentary)", "DDD-AD-Z-Notker-Psalmen",
         "goh", "patristic", "Notker Labeo", (1000, 1022), None, "approximate",
         "Petrus W. Tax, Notker der Deutsche, Der Psalter (Die Werke Notkers des Deutschen "
         "8–10, Tübingen 1979–1983)",
         _notker_psalter, as_verses=False, join_hyphens=True),
    Text("notker-cantica", "Cantica und katechetische Texte (Notker's Canticles, Lord's Prayer and Creeds)",
         "DDD-AD-Z-Notker_Cantica", "goh", "patristic", "Notker Labeo", (1000, 1022), None,
         "approximate",
         "Petrus W. Tax, Notker der Deutsche, Psalm 101–150, die Cantica und die katechetischen "
         "Texte (Die Werke Notkers des Deutschen 10, Tübingen 1983)",
         _notker_cantica, as_verses=False, join_hyphens=True),
    Text("notker-boethius", "Boethius, De consolatione Philosophiae (Notker's translation and commentary)",
         "DDD-AD-Z-Notker_Boethius-De_Consolatione_philosophiae", "goh", "patristic", "Notker Labeo",
         (1000, 1022), None, "approximate",
         "Petrus W. Tax, Notker der Deutsche, Boethius, De consolatione Philosophiae (Die Werke "
         "Notkers des Deutschen 1–3, Tübingen 1986–1990): St. Gallen, Stiftsbibliothek, Cod. 825",
         _notker_boethius, as_verses=False, join_hyphens=True),
    # --- Old Saxon ----------------------------------------------------------------------
    Text("heliand", "Heliand", "DDD-AD-Heliand", "osx", "patristic", None, (830, 850), None,
         "approximate",
         "Otto Behaghel, Heliand und Genesis, 10th ed. by Burkhard Taeger (Tübingen 1996, "
         "after 1984): Munich, Cgm 25 (M) and London, BL Cotton Caligula A. VII (C)",
         _heliand, as_verses=False),
    Text("genesis", "Old Saxon Genesis", "DDD-AD-Genesis", "osx", "patristic", None, (830, 860),
         None, "approximate",
         "Otto Behaghel, Heliand und Genesis, ed. Burkhard Taeger (Tübingen 1984): Rome, "
         "Biblioteca Apostolica Vaticana, Cod. Pal. lat. 1447",
         _genesis, as_verses=False),
    _minor("gernrode-psalm-commentary", "GPr_Gernroder_Predigt", "GPr",
           "Gernrode Psalm Commentary (Altsächsische Psalmenauslegung, Psalms 4–5)",
           genre="patristic", language="osx", date_range=(950, 1000), edition=_WADSTEIN, subcorpus=_KAS),
    _minor("beda-homily", "BH_Homilie_Bedas", "BH", "Old Saxon Homily of Bede (All Saints)",
           genre="patristic", language="osx", author="Beda", date_range=(950, 1000),
           edition=_WADSTEIN, subcorpus=_KAS),
    _minor("old-saxon-confession", "ASB_Altsaechsische_Beichte", "ASB", "Old Saxon Confession (Altsächsische Beichte)",
           language="osx", date_range=(900, 1000), edition=_WADSTEIN, subcorpus=_KAS),
    _minor("old-saxon-creed", "GB_Glaubensbekenntnis", "GB", "Old Saxon Creed (Glaubensbekenntnis)",
           language="osx", date_range=(900, 1050), confidence="uncertain",
           edition="Ferdinand Holthausen, Altsächsisches Elementarbuch (Heidelberg 1921)", subcorpus=_KAS),
    _minor("cologne-baptismal-vow", "KT_Westfaelisches_Taufgeloebnis", "KT",
           "Cologne Baptismal Vow (Kölner Taufgelöbnis)", language="osx", date_range=(950, 1000),
           edition=_BRAUNE, subcorpus=_KAS),
    _minor("saxon-baptismal-vow", "ST_Saechsisches_Taufgeloebnis", "ST",
           "Saxon Baptismal Vow (Sächsisches Taufgelöbnis)", language="osx", date_range=(772, 800),
           edition=_WADSTEIN, subcorpus=_KAS),
    # --- Old High German minor texts (Steinmeyer) ---------------------------------------
    # Verse units (#586): sentence groups for alliterative and unrhymed verse, strophes
    # (couplets run on to the sentence end) for rhymed couplet verse.
    _minor("muspilli", "M_Muspilli", "Musp", "Muspilli", verse=True, group=sentence_units, genre="patristic",
           date_range=(810, 870), confidence="uncertain"),
    _minor("wessobrunn-prayer", "W_Wess", "Wess", "Wessobrunn Prayer (Wessobrunner Gebet)", verse=True,
           group=sentence_units,
           date_range=(770, 814)),
    _minor("ludwigslied", "L_Ludwigslied", "Ludw", "Ludwigslied", verse=True, group=strophe_units(),
           genre="patristic",
           date_range=(881, 882), confidence="established"),
    _minor("georgslied", "G_Georgslied_Tschirch", "Georg", "Georgslied (Song of St George)", verse=True,
           group=strophe_units(_GEORG_REFRAIN),
           genre="patristic", date_range=(880, 900), confidence="uncertain",
           edition="Fritz Tschirch, Frühmittelalterliches Deutsch (Halle 1955): Heidelberg, cpl 52"),
    _minor("petruslied", "P_Petruslied", "Petr", "Petruslied (Song of St Peter)", verse=True,
           group=strophe_units(_PETR_REFRAIN),
           date_range=(850, 900)),
    _minor("christus-und-die-samariterin", "CH_ChristusundSamariterin", "ChrSam",
           "Christus und die Samariterin (Christ and the Samaritan Woman)", verse=True, group=strophe_units(),
           genre="patristic",
           date_range=(900, 950), confidence="uncertain"),
    _minor("psalm-138", "Ps138_Psalm138", "Ps138", "Psalm 138 (Old High German verse paraphrase)", verse=True,
           group=strophe_units(),
           genre="patristic", date_range=(880, 930), confidence="uncertain"),
    _minor("augsburg-prayer", "AG_AugsburgerGebet", "AG", "Augsburg Prayer (Augsburger Gebet)", verse=True,
           group=sentence_units,
           date_range=(850, 900)),
    _minor("carmen-ad-deum", "C_CarmenAdDeum", "CarmD", "Carmen ad Deum (Old High German interlinear version)",
           verse=True, group=sentence_units, date_range=(850, 900)),
    _minor("exhortatio-ad-plebem-christianam", "E_Exhortatio", "Exh", "Exhortatio ad plebem christianam",
           genre="patristic", date_range=(800, 817)),
    _minor("weissenburg-catechism", "WK_Weissenburger_Katechismus", "WK", "Weissenburg Catechism (Weißenburger Katechismus)",
           date_range=(790, 830)),
    _minor("st-gall-paternoster", "GP_SangallerPaterNoster", "GP", "St. Gall Lord's Prayer (St. Galler Paternoster)",
           date_range=(770, 800)),
    _minor("st-gall-credo", "GC_SangalerCredo", "GC", "St. Gall Creed (St. Galler Credo)", date_range=(770, 800)),
    _minor("freising-paternoster-a", "FP1_FreisingerPaternoster1", "FPA",
           "Freising Lord's Prayer A (Freisinger Paternoster), with exposition", genre="patristic",
           date_range=(800, 830)),
    _minor("freising-paternoster-b", "FP2_FreisingerPaternoster2", "FPB",
           "Freising Lord's Prayer B (Freisinger Paternoster), with exposition", genre="patristic",
           date_range=(800, 830)),
    _minor("frankish-baptismal-vow", "FT_Fraenkisches_Taufgeloebnis", "FT",
           "Frankish Baptismal Vow (Fränkisches Taufgelöbnis)", date_range=(790, 810)),
    _minor("old-bavarian-confession", "AB_AltbairischeBeichte", "AB", "Old Bavarian Confession (Altbairische Beichte)",
           date_range=(800, 850)),
    _minor("lorsch-confession", "LB_LorscherBeichte", "LB", "Lorsch Confession (Lorscher Beichte)",
           date_range=(850, 900)),
    _minor("wurzburg-confession", "WB_Wzb.Beichte", "WB", "Würzburg Confession (Würzburger Beichte)",
           date_range=(850, 900)),
    _minor("fulda-confession", "FB_Fuldaer_Beichte", "FB", "Fulda Confession (Fuldaer Beichte)",
           date_range=(950, 1000)),
    _minor("mainz-confession", "MB_MainzerBeichte", "MB", "Mainz Confession (Mainzer Beichte)",
           date_range=(950, 1000)),
    _minor("reichenau-confession", "RB_ReichenauerBeichte", "RB", "Reichenau Confession (Reichenauer Beichte)",
           date_range=(950, 1000)),
    _minor("palatine-confession", "PfB_PfälzerBeichte", "PfB", "Palatine Confession (Pfälzer Beichte)",
           date_range=(900, 1000)),
    _minor("vorau-confession", "BB_BruchstueckeinerBeichte", "BB",
           "Fragment of a Confession (Vorauer Beichte)", date_range=(900, 1000)),
    _minor("younger-bavarian-confession", "JB_JuengereBairischeBeichte", "JB",
           "Younger Bavarian Confession (Jüngere Bairische Beichte)", date_range=(950, 1050),
           confidence="uncertain"),
    _minor("st-emmeram-prayer-a", "BGa_St.Emmeraner_Gebet_A", "BGA",
           "St. Emmeram Prayer A (Altbairisches Gebet A)", date_range=(800, 850)),
    _minor("st-emmeram-prayer-b", "BGb_St.Emmerander_Gebet_B", "BGB",
           "St. Emmeram Prayer B (Altbairisches Gebet B)", date_range=(800, 850)),
    _minor("frankish-prayer", "FG_FraenkischesGebet", "FG", "Frankish Prayer (Fränkisches Gebet)",
           date_range=(800, 850)),
    _minor("prayer-fragment", "GBr_Gebetbruchstueck", "GBr", "Fragment of a Prayer (Gebetbruchstück)",
           date_range=(900, 1000)),
    _minor("sigiharts-prayers", "SG_Sigharts_Gebet", "SG", "Sigihart's Prayers (Sigiharts Gebete)",
           date_range=(902, 906)),
    _minor("othlohs-prayer", "OG_Otlohs_Gebet", "OG", "Othloh's Prayer (Othlohs Gebet), Latin and German",
           author="Othlonus", date_range=(1050, 1070), confidence="uncertain"),
    # A priest's oath of obedience to his bishop: canon law, so filed with the councils.
    _minor("priests-oath", "PE_Priestereid", "PE", "Priests' Oath (Priestereid)", genre="council",
           date_range=(950, 1000)),
    _minor("alemannic-psalms", "APs_Altalemannische_Psalmen", "APs",
           "Old Alemannic Psalms (Altalemannische Psalmenübersetzung, interlinear fragments)",
           date_range=(800, 850)),
    _minor("rhenish-franconian-cantica", "RhC_Rheinfränkische_Cantica", "RhC",
           "Rhenish Franconian Canticles (Rheinfränkische Cantica, fragments)", date_range=(900, 950)),
)

#: What ReA has and Patristica leaves out (the survey's scope rule, #224), for the record.
DROPPED: dict[str, str] = {
    "DDD-AD-Isidor_Latein": "the Paris Isidor's Latin column; De fide catholica is in the corpus (PL 83)",
    "DDD-AD-Physiologus": "Älterer Physiologus, composed c. 1070 (after the period)",
    "DDD-AD-Z-Notker-Martianus_Capella": "Notker's school text",
    "DDD-AD-Z-Notker-Psalmen-Glossen": "glosses to Notker's Psalter",
    "DDD-AD-Z-Notker_Boethius-Categoriae": "Notker's school text (Aristotle)",
    "DDD-AD-Z-Notker_Boethius-De_Interpretatione": "Notker's school text (Aristotle)",
    "DDD-AD-Z-Notker_Kleinere-Ars_Rhetorica": "Notker's school text",
    "DDD-AD-Z-Notker_Kleinere-De_Musica": "Notker's school text",
    "DDD-AD-Z-Notker_Kleinere-De_Partibus_logice": "Notker's school text",
    "DDD-AD-Z-Notker_Kleinere-Syllogismus": "Notker's school text",
    "minor: secular": "Hildebrandslied, De Heinrico, Straßburger Eide, Lex Salica, Trierer "
                      "Capitulare, boundary descriptions, recipes, inscriptions, pen trials, "
                      "proverbs, mocking verses, Einhard's month and wind names, school "
                      "exercises, De definitione, Hirsch und Hinde, Kicila-Vers, Reimspruch; "
                      "Old Saxon rent rolls (Freckenhorst, Essen, Werden), Abecedarium "
                      "Nordmannicum, Leo of Vercelli's letter, coin inscription",
    "minor: charms": "Merseburg charms and the blessings and charms against illness, worms, "
                     "bleeding, for horses, bees, dogs and the house (Christian or not): "
                     "folk magic, not church texts",
    "minor: after 1050": "Memento Mori (Noker, c. 1070), Himmel und Hölle (c. 1070), "
                         "Bamberger, Wessobrunner, Benediktbeurer and Alemannischer Glaube und "
                         "Beichte, St. Galler Glaube und Beichte II, Predigtsammlung B "
                         "(12th-century manuscripts and language)",
    "minor: undated, 11th-century manuscripts": "St. Galler Glaube und Beichte I and III, the "
                                                "Klosterneuburger Gebet and the Geistliche Ratschläge: "
                                                "no date but their manuscripts', which may be after 1050 "
                                                "(owner, #576)",
    "minor: other language": "Altniederfränkische Psalmen (Old Low Franconian, not goh/osx)",
}


def _check_language(text: Text, docs: list[Document]) -> None:
    for doc in docs:
        tag = doc.meta.get("language")
        code = REA_LANGUAGES.get(tag or "")
        if code is None:
            raise ReAError(f"{text.slug}: {doc.name} has an unknown ReA language {tag!r}")
        if code != text.language:
            raise ReAError(f"{text.slug}: {doc.name} is {tag!r} in ReA, configured {text.language!r}")


_ROMAN_HEADING = re.compile(r"[IVXLC]+\.?")

#: Works whose language differs from their sub-corpus's (Otfrid's Latin letter).
_LANGUAGE_EXEMPT = frozenset({"otfrid-ad-liutbertum"})


def build_units(text: Text, docs: dict[str, Document]) -> list[dict[str, Any]]:
    """The raw units of one work: ``{"ref", "text"[, "editorial"]}``."""
    if text.docs:
        _check_language(text, [docs[d] for d in text.docs])
    elif text.slug not in _LANGUAGE_EXEMPT and docs:
        _check_language(text, [next(iter(docs.values()))])
    units = text.build(docs)
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for unit in units:
        body, spans = assemble_unit(unit, join_hyphens=text.join_hyphens)
        if not body or set(body.split()) == {LACUNA}:
            if body:
                log.debug("%s %s: only a lacuna, dropped", text.slug, unit.ref)
            continue
        if unit.ref in seen:
            raise ReAError(f"{text.slug}: duplicate ref {unit.ref}")
        seen.add(unit.ref)
        record: dict[str, Any] = {"ref": unit.ref, "text": body}
        if _ROMAN_HEADING.fullmatch(body) and not spans:
            # The editor's fragment or section numeral (Genesis "I").
            spans = [[0, len(body), "heading"]]
        if spans:
            record["editorial"] = spans
        out.append(record)
    return out


def _work(text: Text) -> Work:
    return Work(
        work_id=f"{SOURCE_ID}/{text.slug}",
        source_id=SOURCE_ID,
        author=text.author,
        title=text.title,
        date_composed=text.date_composed,
        date_range=text.date_range,
        date_confidence=text.date_confidence,  # type: ignore[arg-type]
        genre=text.genre,  # type: ignore[arg-type]
        language=text.language,  # type: ignore[arg-type]
        tradition="latin",
        license=LICENSE,
        provenance_url=RECORD_URL,
        edition=f"{REA} ({text.subcorpus}), from {text.edition}",
        translation_of=None,
    )


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download the relANNIS export once and write one raw JSON file per work."""
    out_dir = output_dir / SOURCE_ID
    corpus: Corpus | None = None
    works: list[Work] = []
    for text in TEXTS:
        out_path = out_dir / f"{text.slug}.json"
        if out_path.exists() and not force:
            works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
            continue
        if corpus is None:
            zip_path = download_file(CORPUS_URL, output_dir / "_zips" / ZIP_NAME,
                                     etag_cache=False, force=False)
            corpus = Corpus(zip_path)
        docs = corpus.subcorpus(text.subcorpus, text.layer)
        units = build_units(text, docs)
        if not units:
            raise ReAError(f"{text.slug}: no units")
        work = _work(text)
        key = "verses" if text.as_verses else "paragraphs"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"work": work.model_dump(), key: units},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
        log.info("%s: %d units", work.work_id, len(units))
        works.append(work)
    log.info("ReA: %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
