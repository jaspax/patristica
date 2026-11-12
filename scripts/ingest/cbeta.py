"""
Ingest Church of the East (Jingjiao 景教) texts from CBETA's Taishō edition (#651, part of #228).

Source: CBETA, the Chinese Buddhist Electronic Text Association, TEI P5 files on
GitHub (``cbeta-org/xml-p5``, ``T/T{vol}/T{vol}n{no}.xml``), pinned to commit
:data:`COMMIT` and downloaded through ``_common.download_file`` into
``data/raw/_cache/cbeta/{commit}/``, so a ``--force --offline`` run regenerates
the raw data from the cache.

Texts (:data:`TEXTS`, by Taishō number; more CBETA texts can be added there):

- **T2142** 序聽迷詩所經 (Taishō 54, 1286b–1288a);
- **T2143** split into two works: the hymn 景教三威蒙度讚, which ends with its
  colophon 大秦景教三威蒙度讚一卷 (the file's first ``cb:div``), and 尊經 with the
  note on Jingjing's translations that follows it in the manuscript (the rest);
- **T2144** 大秦景教流行中國碑頌, the Xi'an stele (781), by Jingjing.

T2141A/B, the Manichaean texts of the same volume, are out of scope.

Licence: CBETA's copyright page (https://www.cbeta.org/copyright, checked
2026-11-12) releases its database, the Taishō included, under CC BY-NC-SA 4.0
International for non-profit use; the files' header says "Available for
non-commercial use when distributed with this header intact" (the cached XML
keeps it). The edition line credits the Taishō and CBETA.

Canonical references
--------------------
The Taishō is cited by page, register and line (``T54n2143_p1288b05``). Every
unit's ref is ``T{no}.p{line}``, the Taishō line it starts on
(``T2143.p1288b05``): a prose unit is CBETA's ``<p>`` (the edition's
paragraph), a hymn unit one ``<l>`` (a couplet, its two seven-character halves
joined by an ideographic space at the ``<caesura/>``). Works with an ``<lg>``
are written as ``verses`` (never cut into derived verses), the others as
``paragraphs``. Lines are joined with nothing between them, as Chinese is
written without spaces; the edition's own ideographic spaces (honorific gaps
before 聖上, list separators) are kept.

Text
----
- Rare characters ``<g ref="#CB…">`` are resolved from the header's
  ``charDecl``: the ``unicode`` mapping, else the ``normal_unicode`` one, else
  the ``normalized form``. A character with none is logged at ERROR and given
  as CBETA's composition (``[涺-十+(土/此/土)]``, as CBETA Online shows it),
  marked as an editorial ``note``, unless :data:`UNENCODED` records it as
  reviewed (logged at WARNING then).
- Small-print inline notes (``<note place="inline">``: 并序 in the stele's
  title, the note on Jingjing's translations after 尊經) are the manuscript's
  own text and kept. Every other ``<note>`` is apparatus and dropped: the
  Taishō's notes on its witness (recorded in the edition line instead), and
  CBETA's corrections, whose corrected reading (``<lem>``) is the text.
- Titles (``<cb:jhead>``, ``<head>``) are units of their own, wholly
  ``title``; the stele's byline (大秦寺僧景淨述) is wholly ``heading`` (#236).
- ``□`` (a character illegible on the stele) is a ``lacuna``.
- Paragraphs listed in a part's ``drop`` are left out, with the reason there
  (the stele's 1859 colophon).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from lxml import etree

from patristica.models import Work
from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

SOURCE_ID = "cbeta"

#: The cbeta-org/xml-p5 commit the files are taken from (master on 2026-10-30).
COMMIT = "8ebac86d00719479db5777dc6cd77ba111c3067a"
_RAW_URL = "https://raw.githubusercontent.com/cbeta-org/xml-p5/{commit}/T/T{vol}/T{vol}n{no}.xml"
_BLOB_URL = "https://github.com/cbeta-org/xml-p5/blob/{commit}/T/T{vol}/T{vol}n{no}.xml"

TEI = "http://www.tei-c.org/ns/1.0"
CB = "http://www.cbeta.org/ns/1.0"
_NS = {"tei": TEI, "cb": CB}

LICENSE = "cc-by-nc-sa-4.0"

#: CBETA characters with no Unicode form that have been reviewed: id → reason.
#: Each is kept as CBETA's composition, marked ``note``, and logged at WARNING.
UNENCODED: dict[str, str] = {
    # T2142 p1286c22 銀神像及銅像并[X]神像: a character not in Unicode (17.0)
    # nor in CBETA's gaiji table (cbeta_gaiji.csv: composition and PUA only).
    "CB07751": "not in Unicode; CBETA has only its composition",
}

_LACUNA = "□"
_IDEOGRAPHIC_SPACE = "　"


@dataclass(frozen=True)
class Part:
    """One work made from a Taishō file: its top-level ``cb:div``s ``divs[0]:divs[1]``."""

    slug: str
    title: str
    author: str
    date_range: tuple[int, int]
    date_confidence: str
    genre: str
    note: str  # the witness, for the edition line
    divs: tuple[int, int | None] = (0, None)
    date_composed: int | None = None
    drop: dict[str, str] = field(default_factory=dict)  # start line → reason


@dataclass(frozen=True)
class Text:
    """A Taishō text: its number, volume and pages, and the works it gives."""

    no: str
    vol: str
    pages: str
    parts: tuple[Part, ...]

    @property
    def file(self) -> str:
        return f"T{self.vol}n{self.no}.xml"


ANON = "Anonymous"

TEXTS: tuple[Text, ...] = (
    Text(
        no="2142",
        vol="54",
        pages="1286b–1288a",
        parts=(Part(
            slug="t2142-xuting-mishisuo-jing",
            title="序聽迷詩所經 (Xuting Mishisuo jing, the Sutra of Jesus the Messiah)",
            author=ANON,
            # Traditionally of Aluoben's mission (635) or soon after; the
            # manuscript (Haneda 459, "Takakusu manuscript") is Tang by its
            # owner's account, but its authenticity is debated (Lin Wushu).
            date_range=(635, 650),
            date_confidence="uncertain",
            genre="patristic",
            note="a Dunhuang manuscript of the Tang dynasty owned by Takakusu Junjirō, its end "
                 "lost (Taishō note: 唐代寫燉煌本高楠順次郎氏藏本尾缺)"
                 "; its authenticity is debated",
        ),),
    ),
    Text(
        no="2143",
        vol="54",
        pages="1288b–c",
        parts=(
            Part(
                slug="t2143-sanwei-mengdu-zan",
                title="景教三威蒙度讚 (Jingjiao Sanwei mengdu zan, Hymn to the Holy Trinity)",
                author=ANON,
                # A version of the Syriac Gloria in excelsis; of the Tang
                # mission, before the persecution of 845 (often ascribed to
                # Jingjing, fl. 781). Manuscript Pelliot chinois 3847.
                date_range=(720, 845),
                date_confidence="uncertain",
                genre="liturgical",
                note="the Dunhuang manuscript Pelliot chinois 3847",
                divs=(0, 1),
            ),
            Part(
                slug="t2143-zunjing",
                title="尊經 (Zunjing, the Book of the Honoured)",
                author=ANON,
                # Its closing note speaks of Jingjing (fl. 781) in the past;
                # the manuscript, P. 3847, is of the 10th century.
                date_range=(800, 1000),
                date_confidence="uncertain",
                genre="liturgical",
                note="the Dunhuang manuscript Pelliot chinois 3847, after the hymn 景教三威蒙度讚",
                divs=(1, None),
            ),
        ),
    ),
    Text(
        no="2144",
        vol="54",
        pages="1289a–1290b",
        parts=(Part(
            slug="t2144-jingjiao-stele",
            title="大秦景教流行中國碑頌 (The Xi'an Stele: Memorial of the Propagation in China "
                  "of the Luminous Religion from Daqin)",
            author="景淨",
            date_composed=781,
            date_range=(781, 781),
            date_confidence="established",
            genre="patristic",
            note="a rubbing owned by Ishida Mikinosuke (Taishō note: 拓本石田幹之助氏藏); the "
                 "stele's Syriac is not in the Taishō",
            drop={"1290b21": "Han Taihua's colophon of 1859 (咸豐己未), carved on the stele "
                             "when he rebuilt its pavilion: not part of the 781 text"},
        ),),
    ),
)


# ---------------------------------------------------------------------------
# Characters
# ---------------------------------------------------------------------------

def char_table(root: etree._Element) -> dict[str, tuple[str | None, str]]:
    """``charDecl``: CBETA id → (its Unicode character or None, its composition)."""
    table: dict[str, tuple[str | None, str]] = {}
    for char in root.iterfind(".//tei:charDecl/tei:char", _NS):
        cid = char.get("{http://www.w3.org/XML/1998/namespace}id")
        mappings = {m.get("type"): m.text for m in char.iterfind("tei:mapping", _NS)}
        props = {p.findtext("tei:localName", namespaces=_NS):
                 p.findtext("tei:value", namespaces=_NS)
                 for p in char.iterfind("tei:charProp", _NS)}
        resolved: str | None = None
        for kind in ("unicode", "normal_unicode"):
            code = mappings.get(kind)
            if code:
                if not code.startswith("U+"):
                    raise ValueError(f"{cid}: bad {kind} mapping {code!r}")
                resolved = chr(int(code[2:], 16))
                break
        if resolved is None and props.get("normalized form"):
            resolved = props["normalized form"]
        table[cid] = (resolved, props.get("composition") or f"[{cid}]")
    return table


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------

def _local(el: etree._Element) -> str:
    """The element's tag without its namespace, ``cb:`` kept for CBETA's own."""
    qname = etree.QName(el)
    return f"cb:{qname.localname}" if qname.namespace == CB else qname.localname


_SPACE = re.compile(r"[ \t\r\n]+")


@dataclass
class _Builder:
    """Text and editorial spans of one unit, built piece by piece."""

    chars: dict[str, tuple[str | None, str]]
    where: str
    text: str = ""
    spans: list[list[Any]] = field(default_factory=list)

    def add(self, s: str | None) -> None:
        if s:
            self.text += _SPACE.sub("", s)

    def add_g(self, el: etree._Element) -> None:
        cid = (el.get("ref") or "").lstrip("#")
        if cid not in self.chars:
            raise ValueError(f"{self.where}: <g ref={cid!r}> not in charDecl")
        resolved, composition = self.chars[cid]
        if resolved is not None:
            self.text += resolved
            return
        if cid in UNENCODED:
            log.warning("%s: %s %s kept as its composition (%s)", self.where, cid, composition,
                        UNENCODED[cid])
        else:
            log.error("%s: %s %s has no Unicode form; kept as its composition", self.where, cid,
                      composition)
        start = len(self.text)
        self.text += composition
        self.spans.append([start, len(self.text), "note"])


# Elements whose text is the text; their children are walked.
_INLINE = {"p", "l", "cb:jhead", "head", "byline", "lem", "app"}
# Elements that carry no text of the unit (their tails do).
_EMPTY = {"lb", "pb", "anchor", "milestone"}


def _walk(el: etree._Element, b: _Builder) -> None:
    """Add *el*'s content (not its tail) to *b*."""
    b.add(el.text)
    for child in el:
        tag = _local(child)
        if tag == "g":
            b.add_g(child)
        elif tag == "caesura":
            b.text += _IDEOGRAPHIC_SPACE
        elif tag == "note":
            if child.get("place") == "inline":
                _walk(child, b)
        elif tag == "rdg":
            pass  # another witness's reading
        elif tag in _INLINE:
            _walk(child, b)
        elif tag in _EMPTY or tag == "cb:mulu":
            pass
        else:
            raise ValueError(f"{b.where}: unexpected <{tag}> in a unit")
        b.add(child.tail)


@dataclass
class Unit:
    line: str  # Taishō line, e.g. "1288b05"
    kind: str  # title | heading | p | l
    text: str
    spans: list[list[Any]]
    div: int  # index of the top-level cb:div it is in (-1 before the first)


def _lacunae(text: str, spans: list[list[Any]]) -> list[list[Any]]:
    """*spans* plus a ``lacuna`` span for every run of □ outside them."""
    out = list(spans)
    for m in re.finditer(f"{_LACUNA}+", text):
        if not any(s <= m.start() < e for s, e, _ in spans):
            out.append([m.start(), m.end(), "lacuna"])
    return sorted(out)


def units(root: etree._Element, where: str) -> list[Unit]:
    """The body's units in document order, each with the Taishō line it starts on."""
    chars = char_table(root)
    body = root.find(".//tei:text/tei:body", _NS)
    if body is None:
        raise ValueError(f"{where}: no <body>")
    out: list[Unit] = []
    line = ""
    div = -1

    def unit(el: etree._Element, kind: str) -> None:
        if not line:
            raise ValueError(f"{where}: <{_local(el)}> before the first <lb>")
        b = _Builder(chars, f"{where} p{line}")
        _walk(el, b)
        text = b.text.strip(_IDEOGRAPHIC_SPACE)
        lead = len(b.text) - len(b.text.lstrip(_IDEOGRAPHIC_SPACE))
        spans = [[s - lead, e - lead, k] for s, e, k in b.spans]
        if not text:
            return
        if kind in ("title", "heading"):
            spans = [[0, len(text), kind]]
        out.append(Unit(line, kind, text, _lacunae(text, spans), div))

    def visit(el: etree._Element, depth_div: int) -> None:
        nonlocal line, div
        for child in el:
            tag = _local(child)
            if tag == "lb":
                if child.get("ed", "T") == "T":
                    line = child.get("n") or ""
            elif tag in ("pb", "milestone", "cb:docNumber", "cb:mulu", "anchor"):
                pass
            elif tag == "cb:div":
                if depth_div == 0:
                    div += 1
                visit(child, depth_div + 1)
            elif tag == "cb:juan":
                visit(child, depth_div)
            elif tag in ("cb:jhead", "head"):
                unit(child, "title")
            elif tag == "byline":
                unit(child, "heading")
            elif tag == "p":
                unit(child, "p")
                _last_lb(child)
            elif tag == "lg":
                visit(child, depth_div)
            elif tag == "l":
                unit(child, "l")
                _last_lb(child)
            else:
                raise ValueError(f"{where}: unexpected <{tag}> at p{line}")

    def _last_lb(el: etree._Element) -> None:
        nonlocal line
        for lb in el.iter(f"{{{TEI}}}lb"):
            if lb.get("ed", "T") == "T":
                line = lb.get("n") or line

    visit(body, 0)
    return out


def _selected(all_units: list[Unit], part: Part) -> list[Unit]:
    """The units in a part's divs (units before the first div go with div 0)."""
    lo, hi = part.divs
    return [u for u in all_units if max(u.div, 0) >= lo and (hi is None or max(u.div, 0) < hi)]


def part_units(all_units: list[Unit], part: Part, no: str) -> list[dict[str, Any]]:
    """The raw units of one part: its divs (units before the first div go to the first part)."""
    selected = _selected(all_units, part)
    raw: list[dict[str, Any]] = []
    seen: set[str] = set()
    dropped: set[str] = set()
    for u in selected:
        if u.line in part.drop:
            log.info("cbeta/%s: leaving out p%s: %s", part.slug, u.line, part.drop[u.line])
            dropped.add(u.line)
            continue
        ref = f"T{no}.p{u.line}"
        if ref in seen:
            raise ValueError(f"cbeta/{part.slug}: two units start on line {u.line}")
        seen.add(ref)
        entry: dict[str, Any] = {"ref": ref, "text": u.text}
        if u.spans:
            entry["editorial"] = u.spans
        raw.append(entry)
    missing = set(part.drop) - dropped
    if missing:
        raise ValueError(f"cbeta/{part.slug}: no unit starts on dropped line(s) {sorted(missing)}")
    return raw


def is_verse(all_units: list[Unit], part: Part) -> bool:
    """Whether a part is verse: all its text units are ``<l>`` lines."""
    return {u.kind for u in _selected(all_units, part)} - {"title", "heading"} == {"l"}


# ---------------------------------------------------------------------------
# Download and write
# ---------------------------------------------------------------------------

def _fetch(text: Text, output_dir: Path, force: bool) -> Path:
    url = _RAW_URL.format(commit=COMMIT, vol=text.vol, no=text.no)
    dest = output_dir / "_cache" / SOURCE_ID / COMMIT[:12] / text.file
    # A pinned commit never changes: no ETag round trip, and --force doesn't refetch.
    return download_file(url, dest, etag_cache=False)


def _work(text: Text, part: Part) -> Work:
    edition = (f"Taishō shinshū daizōkyō 大正新脩大藏經 vol. {text.vol}, no. {text.no}, "
               f"pp. {text.pages} (Tokyo 1924–1934), text of {part.note}; digital edition "
               f"of CBETA (Chinese Buddhist Electronic Text Association), XML P5 "
               f"(cbeta-org/xml-p5 @ {COMMIT[:12]}), CC BY-NC-SA 4.0")
    return Work(
        work_id=f"{SOURCE_ID}/{part.slug}",
        source_id=SOURCE_ID,
        author=part.author,
        title=part.title,
        date_composed=part.date_composed,
        date_range=part.date_range,
        date_confidence=part.date_confidence,  # type: ignore[arg-type]
        genre=part.genre,  # type: ignore[arg-type]
        language="lzh",
        tradition="syriac",
        license=LICENSE,
        provenance_url=_BLOB_URL.format(commit=COMMIT, vol=text.vol, no=text.no),
        edition=edition,
        translation_of=None,
        external_ids=[f"Taisho:T{text.no}"],
    )


def parse(path: Path, text: Text) -> list[tuple[Work, str, list[dict[str, Any]]]]:
    """The works of one Taishō file: (work, raw key, units)."""
    root = etree.parse(str(path)).getroot()
    all_units = units(root, f"T{text.no}")
    out = []
    for part in text.parts:
        raw = part_units(all_units, part, text.no)
        if not any(u.kind in ("p", "l") for u in _selected(all_units, part)):
            raise ValueError(f"cbeta/{part.slug}: no text")
        out.append((_work(text, part), "verses" if is_verse(all_units, part) else "paragraphs",
                    raw))
    return out


def iter_texts() -> Iterator[Text]:
    yield from TEXTS


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download the pinned Taishō files and write one raw JSON file per work."""
    works: list[Work] = []
    for text in iter_texts():
        out_paths = [output_dir / SOURCE_ID / f"{p.slug}.json" for p in text.parts]
        if not force and all(p.exists() for p in out_paths):
            works.extend(Work(**json.loads(p.read_text(encoding="utf-8"))["work"])
                         for p in out_paths)
            continue
        path = _fetch(text, output_dir, force)
        for (work, key, raw), out_path in zip(parse(path, text), out_paths):
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(json.dumps({"work": work.model_dump(), key: raw},
                                           ensure_ascii=False, indent=2), encoding="utf-8")
            works.append(work)
    log.info("CBETA (Taishō): %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
