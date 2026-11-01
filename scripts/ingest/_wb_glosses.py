"""
Shared parser for the Würzburg glosses on the Pauline epistles (#539, #225).

Source: Adrian Doyle's digital text of *Thesaurus Palaeohibernicus* I 499–712
(Stokes & Strachan 1901), made in 2018 with NUI Galway funding and the
permission of the Dublin Institute for Advanced Studies, published on Zenodo
(record 5508250, ``Wb_Content_1_0.json``, CC BY 4.0).

The file is a list of the 14 epistles, each a list of folios, each a list of
glosses. A gloss carries its *Thesaurus* page, folio and gloss number, the
Latin verse (``latLine``, ``latin``), the Latin word it glosses (``lemma``),
the hand, the gloss in tagged form (``glossFullTags``) and as HTML
(``glossText``), the editors' footnotes and Stokes and Strachan's English
translation (``glossTrans``).

Two sources are made from it, one work per epistle each:

- ``wb-glosses`` (``scripts.ingest.wb_glosses``): the Old Irish glosses
  (``sga``), with the Latin words in them as the manuscript has them.
- ``wb-glosses-eng`` (``scripts.ingest.wb_glosses_eng``): the 1901 English
  translation, ``translation_of`` the Irish work.

**Units.** Each gloss is one unit, ingested as ``verses`` (a numbered source
unit: no derived verses), with the *Thesaurus* citation as its ref:
``Wb. 1a 8`` → ``Wb.1a.8``, ``Wb. 1b 10, 11`` → ``Wb.1b.10-11``; inserted
glosses keep their letter (``Wb.2a.8a``). Both works use the same refs, so the
English aligns 1:1. Glosses with no Irish in them (wholly Latin, about 135)
are left out of both works.

**Text.** Built from ``glossFullTags``: Latin words, ``.i.``, ``ɫ.``, ``rl.``
and the editors' expansions of abbreviations (``[Con]``) stay as text;
footnote letters are dropped (the footnotes aren't carried). Material the
editors added is marked as editorial spans (#236) and so is not embedded or
translated: the gloss's lemma, put before it as ``Rom. 1:8 meo]`` (kind
``note``), and the editors' comments such as ``[in marg.]`` (``note``). Letters
the editors restored, printed ``(as)`` (``[Res]``), and supplied, printed
``in[termisione]`` (``[Sup]``), are ``supplement`` spans: their text stays in
the source text, without the brackets. The English gets the same lemma
prefix; its footnote letters (``<sup>``) are dropped.

**Folios.** In the file, the last two glosses of f. 2a (Wb. 2a 22, 23, on
Rom. 3:14) open the list of f. 2b. A folio whose numbering restarts is fixed
by moving the glosses before the restart to the previous folio, when they
continue its numbering; anything else raises.
"""

from __future__ import annotations

import html
import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from patristica.models import Work
from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

IRISH_SOURCE = "wb-glosses"
ENGLISH_SOURCE = "wb-glosses-eng"

ZENODO_RECORD = "https://zenodo.org/records/5508250"
DOWNLOAD_URL = "https://zenodo.org/api/records/5508250/files/Wb_Content_1_0.json/content"
CACHE_PATH = Path("_cache") / "zenodo-wb" / "Wb_Content_1_0.json"

REF_PREFIX = "Wb"

#: Epistle heading in the file → (local work id, English name, abbreviation).
EPISTLES: dict[str, tuple[str, str, str]] = {
    "EPISTOLA AD ROMANOS.": ("rom", "Romans", "Rom."),
    "EPISTOLA AD CORINTHIOS I.": ("1cor", "1 Corinthians", "1 Cor."),
    "EPISTOLA II. AD CORINTHIOS.": ("2cor", "2 Corinthians", "2 Cor."),
    "EPISTOLA AD GALATAS.": ("gal", "Galatians", "Gal."),
    "EPISTOLA AD EPHESIOS.": ("eph", "Ephesians", "Eph."),
    "EPISTOLA AD PHILIPPENSES.": ("phil", "Philippians", "Phil."),
    "EPISTOLA I. AD THESSALONICENSES.": ("1thess", "1 Thessalonians", "1 Thes."),
    "EPISTOLA II. AD THESSALONICENSES.": ("2thess", "2 Thessalonians", "2 Thes."),
    "EPISTOLA AD COLOSSENSES.": ("col", "Colossians", "Col."),
    "EPISTOLA I. AD TIMOTHEUM.": ("1tim", "1 Timothy", "1 Tim."),
    "EPISTOLA II. AD TIMOTHEUM.": ("2tim", "2 Timothy", "2 Tim."),
    "EPISTOLA AD TITUM.": ("titus", "Titus", "Tit."),
    "EPISTOLA AD PHILEMONEM.": ("phlm", "Philemon", "Philem."),
    "EPISTOLA AD HEBRAEOS.": ("heb", "Hebrews", "Heb."),
}

# The main hand is dated to about the middle of the 8th century (Thurneysen,
# A Grammar of Old Irish §6), the prima manus somewhat earlier and the third
# hand somewhat later; most scholars put the glosses c. 750–800.
DATE_COMPOSED = 750
DATE_RANGE = (700, 800)

EDITION = (
    "Würzburg, Universitätsbibliothek, M.p.th.f.12. Text of Whitley Stokes and John "
    "Strachan, Thesaurus Palaeohibernicus I (Cambridge 1901), pp. 499–712; digital "
    "edition by Adrian Doyle (NUI Galway, 2018), Zenodo, doi:10.5281/zenodo.5508250, "
    "CC BY 4.0"
)
ENGLISH_EDITION = (
    "English translation of Whitley Stokes and John Strachan, Thesaurus Palaeohibernicus I "
    "(Cambridge 1901), pp. 499–712; digital edition by Adrian Doyle (NUI Galway, 2018), "
    "Zenodo, doi:10.5281/zenodo.5508250, CC BY 4.0"
)

Span = tuple[int, int, str]

# Tags of glossFullTags whose content is text as it stands.
_PLAIN_TAGS = frozenset({"ie", "GLat", "Con", "vel", "etc"})
# Tags whose content an editor added: (open bracket, close bracket, span kind).
_MARKED_TAGS: dict[str, tuple[str, str, str]] = {
    "Com": ("[", "]", "note"),        # editors' comment: [in marg.]
    "Res": ("(", ")", "supplement"),  # restored letters: (as)ṁbeir
    "Sup": ("[", "]", "supplement"),  # supplied letters: in[termisione]
}
# Tags whose content is not Irish, for telling an Irish gloss from a Latin one.
_NOT_IRISH_TAGS = ("GLat", "Com", "ie", "vel", "etc")
_TAG_RE = re.compile(r"\[(/?)([A-Za-z]+)\]")
_FOOTNOTE_TAG_RE = re.compile(r"[a-z]")
# An Armenian hyphen (U+058A) once stands for a hyphen (".i. kal֊").
_CHAR_FIXES = str.maketrans({"֊": "-"})
_ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50}


class WbFormatError(ValueError):
    """The file has a structure this parser doesn't know."""


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

@dataclass
class _Builder:
    """Text with editorial spans, squeezed to single spaces at the end."""

    text: str = ""
    spans: list[Span] = field(default_factory=list)

    def add(self, piece: str) -> None:
        self.text += piece

    def mark(self, start: int, kind: str) -> None:
        if start < len(self.text):
            self.spans.append((start, len(self.text), kind))

    def result(self) -> tuple[str, list[Span]]:
        return squeeze(self.text, self.spans)


def squeeze(text: str, spans: list[Span]) -> tuple[str, list[Span]]:
    """*text* with whitespace runs collapsed to one space and stripped, and
    *spans* moved onto it (a span's edge whitespace is left out of it)."""
    out: list[str] = []
    new_pos: list[int] = []  # new_pos[i]: index in the output of text[i] (or where it would be)
    for ch in text:
        new_pos.append(len(out))
        if ch.isspace():
            if out and out[-1] != " ":
                out.append(" ")
        else:
            out.append(ch)
    new_pos.append(len(out))
    squeezed = "".join(out)
    lead = len(squeezed) - len(squeezed.lstrip())
    stripped = squeezed.strip()
    moved: list[Span] = []
    for start, end, kind in spans:
        s, e = new_pos[start] - lead, new_pos[end] - lead
        s, e = max(s, 0), min(e, len(stripped))
        while s < e and stripped[s] == " ":
            s += 1
        while e > s and stripped[e - 1] == " ":
            e -= 1
        if s < e:
            moved.append((s, e, kind))
    return stripped, moved


def _tokens(tagged: str) -> Iterator[tuple[str, bool, str]]:
    """(text, is_tag, tag) pieces of a tagged string; a tag piece's text is
    ``/`` for a closing tag."""
    pos = 0
    for m in _TAG_RE.finditer(tagged):
        if m.start() > pos:
            yield tagged[pos:m.start()], False, ""
        yield m.group(1), True, m.group(2)
        pos = m.end()
    if pos < len(tagged):
        yield tagged[pos:], False, ""


def _is_footnote_tag(tag: str) -> bool:
    return bool(_FOOTNOTE_TAG_RE.fullmatch(tag))


def irish_text(tagged: str) -> tuple[str, list[Span]]:
    """The gloss's text from ``glossFullTags``, with its editorial spans."""
    b = _Builder()
    open_marks: list[tuple[str, int]] = []  # (tag, start) of open editorial tags
    for piece, is_tag, tag in _tokens(tagged.translate(_CHAR_FIXES)):
        if not is_tag:
            b.add(piece)
        elif _is_footnote_tag(tag) or tag in _PLAIN_TAGS:
            continue
        elif tag in _MARKED_TAGS:
            opener, closer, kind = _MARKED_TAGS[tag]
            if piece != "/":
                b.add(opener)
                open_marks.append((tag, len(b.text) - len(opener)))
            else:
                if not open_marks or open_marks[-1][0] != tag:
                    raise WbFormatError(f"unbalanced [/{tag}] in {tagged!r}")
                _, start = open_marks.pop()
                b.add(closer)
                if not open_marks:  # an inner mark is covered by its outer one
                    b.mark(start, kind)
        else:
            raise WbFormatError(f"unknown tag [{piece}{tag}] in {tagged!r}")
    if open_marks:
        raise WbFormatError(f"unclosed [{open_marks[-1][0]}] in {tagged!r}")
    return b.result()


def has_irish(tagged: str) -> bool:
    """Whether a gloss has any Irish: letters outside its Latin words, the
    editors' comments and the ``.i.``/``ɫ.``/``rl.`` signs."""
    rest = tagged
    for tag in _NOT_IRISH_TAGS:
        rest = re.sub(rf"\[{tag}\].*?\[/{tag}\]", " ", rest, flags=re.S)
    rest = _TAG_RE.sub(" ", rest)
    return any(ch.isalpha() for ch in rest)


def english_text(trans: str) -> str:
    """The English translation as plain text: footnote letters (``<sup>``)
    and markup dropped."""
    text = re.sub(r"<sup>.*?</sup>", "", trans, flags=re.S)
    text = re.sub(r"<[^>]+>", "", text)
    return " ".join(html.unescape(text).split())


def _roman(numeral: str) -> int:
    values = [_ROMAN[c] for c in numeral]
    return sum(-v if i + 1 < len(values) and v < values[i + 1] else v
               for i, v in enumerate(values))


def verse_label(lat_line: str, abbrev: str) -> str | None:
    """``Rom. I. 8`` → ``Rom. 1:8``, ``1 Cor. IX. 20, 21`` → ``1 Cor. 9:20–21``;
    None when the file has no verse for the gloss."""
    m = re.fullmatch(r"(.+?\.) ([IVXL]+)\. (\d+)(?:, (\d+))?", lat_line.strip())
    if not m:
        if "No Chapter or Verse" in lat_line:
            return None
        raise WbFormatError(f"unexpected latLine {lat_line!r}")
    if m.group(1) != abbrev:
        raise WbFormatError(f"latLine {lat_line!r} is not in {abbrev}")
    verse = m.group(3) + (f"–{m.group(4)}" if m.group(4) else "")
    return f"{abbrev} {_roman(m.group(2))}:{verse}"


def lemma_prefix(gloss: dict, abbrev: str) -> str:
    """What the gloss glosses, put before it: ``Rom. 1:8 meo]``."""
    lemma = " ".join(gloss["lemma"].split())
    verse = verse_label(gloss["latLine"], abbrev)
    return f"{verse} {lemma}]" if verse else f"{lemma}]"


def with_prefix(prefix: str, text: str, spans: list[Span]) -> tuple[str, list[Span]]:
    """*text* after the editorial *prefix* (kind ``note``)."""
    shift = len(prefix) + 1
    return (f"{prefix} {text}",
            [(0, len(prefix), "note")] + [(s + shift, e + shift, k) for s, e, k in spans])


# ---------------------------------------------------------------------------
# Refs
# ---------------------------------------------------------------------------

def _folio(label: str) -> str:
    m = re.fullmatch(r"f\. (\d+[a-d])", label.strip())
    if not m:
        raise WbFormatError(f"unexpected folio {label!r}")
    return m.group(1)


def _number(gloss_no: str) -> str:
    """``10`` → ``10``, ``8a`` → ``8a``, ``10, 11`` → ``10-11``."""
    no = gloss_no.strip()
    if re.fullmatch(r"\d+[a-e]?", no):
        return no
    m = re.fullmatch(r"(\d+), (\d+)", no)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    raise WbFormatError(f"unexpected gloss number {gloss_no!r}")


def _leading_int(no: str) -> int:
    return int(re.match(r"\d+", no).group(0))


def placed_glosses(epistle: dict) -> list[tuple[str, str, dict]]:
    """(folio, number, gloss) for every gloss of an epistle, in order, with
    glosses filed under the wrong folio moved back (see the module doc)."""
    placed: list[tuple[str, str, dict]] = []
    for folio_rec in epistle["folios"]:
        folio = _folio(folio_rec["folio"])
        items = [(folio, _number(g["glossNo"]), g) for g in folio_rec["glosses"]]
        nums = [_leading_int(no) for _, no, _ in items]
        restarts = [i for i in range(1, len(nums)) if nums[i] < nums[i - 1]]
        if len(restarts) > 1:
            raise WbFormatError(f"f. {folio}: numbering restarts more than once")
        if restarts:
            cut = restarts[0]
            prev = [no for f, no, _ in placed if placed and f == placed[-1][0]]
            if not prev or nums[0] != _leading_int(prev[-1]) + 1:
                raise WbFormatError(f"f. {folio}: numbering restarts at gloss {cut + 1}, "
                                    "and the glosses before don't continue the previous folio")
            prev_folio = placed[-1][0]
            log.info("%s: glosses %s of f. %s belong to f. %s",
                     epistle["epistle"], ", ".join(no for _, no, _ in items[:cut]),
                     folio, prev_folio)
            items = [(prev_folio, no, g) for _, no, g in items[:cut]] + items[cut:]
        placed.extend(items)
    return placed


# ---------------------------------------------------------------------------
# Works
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Epistle:
    local_id: str
    name: str
    abbrev: str
    irish: list[dict]    # raw verse records
    english: list[dict]


def parse(data: list[dict]) -> tuple[list[Epistle], int]:
    """The epistles' raw units, and how many glosses had no Irish."""
    epistles: list[Epistle] = []
    skipped = 0
    for ep in data:
        title = ep["epistle"].strip()
        if title not in EPISTLES:
            raise WbFormatError(f"unknown epistle {title!r}")
        local_id, name, abbrev = EPISTLES[title]
        irish: list[dict] = []
        english: list[dict] = []
        seen: set[str] = set()
        for folio, no, gloss in placed_glosses(ep):
            ref = f"{REF_PREFIX}.{folio}.{no}"
            if ref in seen:
                raise WbFormatError(f"{name}: duplicate gloss {ref}")
            seen.add(ref)
            tagged = gloss["glossFullTags"]
            if not has_irish(tagged):
                log.debug("%s %s: no Irish, left out: %s", name, ref, gloss["glossText"])
                skipped += 1
                continue
            prefix = lemma_prefix(gloss, abbrev)
            text, spans = with_prefix(prefix, *irish_text(tagged))
            irish.append({"ref": ref, "text": text, "editorial": [list(s) for s in spans]})
            eng = english_text(gloss["glossTrans"])
            if eng:
                etext, espans = with_prefix(prefix, eng, [])
                english.append({"ref": ref, "text": etext,
                                "editorial": [list(s) for s in espans]})
            else:
                log.warning("%s %s: no English translation", name, ref)
        epistles.append(Epistle(local_id, name, abbrev, irish, english))
    return epistles, skipped


def work_id(source_id: str, local_id: str) -> str:
    return f"{source_id}/{local_id}"


def make_work(epistle: Epistle, english: bool) -> Work:
    source_id = ENGLISH_SOURCE if english else IRISH_SOURCE
    return Work(
        work_id=work_id(source_id, epistle.local_id),
        source_id=source_id,
        author=AUTHOR,
        title=f"Würzburg Glosses on {epistle.name}",
        date_composed=DATE_COMPOSED,
        date_range=DATE_RANGE,
        date_confidence="approximate",
        genre="patristic",
        language="eng" if english else "sga",
        tradition="latin",
        # The 1901 translation is in the public domain; the digital text is
        # Doyle's, under CC BY 4.0.
        license="cc-by-4.0",
        provenance_url=ZENODO_RECORD,
        edition=ENGLISH_EDITION if english else EDITION,
        translation_of=work_id(IRISH_SOURCE, epistle.local_id) if english else None,
    )


AUTHOR = "Anonymous (Würzburg glossators)"


def fetch(output_dir: Path, force: bool = False) -> Path:
    """The cached JSON file (downloaded once, shared by both ingestors)."""
    return download_file(DOWNLOAD_URL, output_dir / CACHE_PATH, force=force)


def ingest_source(output_dir: Path, force: bool, english: bool) -> list[Work]:
    """Write one raw file per epistle for the Irish (or the English) works."""
    source_id = ENGLISH_SOURCE if english else IRISH_SOURCE
    out_dir = output_dir / source_id
    out_dir.mkdir(parents=True, exist_ok=True)
    expected = [out_dir / f"{local_id}.json" for local_id, _, _ in EPISTLES.values()]
    if not force and all(p.exists() for p in expected):
        return [Work(**json.loads(p.read_text(encoding="utf-8"))["work"]) for p in expected]
    data = json.loads(fetch(output_dir, force=force).read_text(encoding="utf-8"))
    epistles, skipped = parse(data)
    log.info("%d glosses with no Irish left out", skipped)
    works: list[Work] = []
    for epistle in epistles:
        out_path = out_dir / f"{epistle.local_id}.json"
        work = make_work(epistle, english)
        if out_path.exists() and not force:
            works.append(work)
            continue
        units = epistle.english if english else epistle.irish
        out_path.write_text(
            json.dumps({"work": work.model_dump(), "verses": units}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("%s: %d glosses", work.work_id, len(units))
        works.append(work)
    return works
