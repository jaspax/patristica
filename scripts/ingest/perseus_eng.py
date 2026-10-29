"""
Ingestor for the English translations in the Perseus canonical repositories
whose originals are in the corpus (#344).

Sources
-------
The same clones as ``perseus.py`` (``data/raw/_repos/perseus-greeklit`` and
``perseus-latinlit``), which keeps only the Greek and Latin editions. This
source takes a curated list of the English editions next to them (``EDITIONS``):

- Josephus, tr. William Whiston (``tlg0526.tlg001–004.perseus-eng2``), EpiDoc
  TEI P5 with book and section divs keyed to Niese's sections.
- Boethius, *Consolation* and theological tractates (``stoa0058.stoa…
  .perseus-eng1``), the Loeb of Stewart and Rand (1918), TEI P4.

The English is its own source rather than more editions of ``perseus``: the
``perseus`` ingest stamp, work ids and pruning of non-Greek/Latin files stay as
they were.

Licence
-------
The translations are public domain (Whiston 1737, Loeb 1918); Perseus' TEI
markup is CC BY-SA 4.0 (the file's ``<licence>``, else the repository's), so
the works are ``cc-by-sa-4.0``.

Editorial material (#236)
-------------------------
Whiston's notes (``<note resp="editor">``) stay at their place in the text,
in brackets, marked ``note``. Headings (Whiston's chapter summaries, a book's
heading, a tractate's chapter number) are marked ``heading``, a tractate's
title ``title``. Page breaks are dropped.

Canonical references
--------------------
``{textgroup}.{work}.{path}``, as in ``perseus``:

- Josephus: ``tlg0526.tlg001.{book}.{section}``, the section a chunk of the
  English starts at (the Greek has one unit per section); a book's heading is
  ``tlg0526.tlg001.{book}``.
- *Consolation*: ``stoa0058.stoa001.{book}.M{n}`` / ``.P{n}`` for a metre or a
  prose; the TEI numbers both ``n``, so a chapter whose text is verse is a
  metre (the first chapter of book 1, ``praef``, is metre 1).
- Tractates: ``stoa0058.stoa023.{chapter}.{paragraph}`` (``pr`` before the
  first chapter), the chapter number ``stoa0058.stoa023.{chapter}`` a heading;
  a tractate without chapters numbers its paragraphs.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from patristica.models import Language, Tradition, Work
from scripts.ingest._common import dedupe_refs, ensure_repo, slugify_ref

log = logging.getLogger(__name__)

SOURCE_ID = "perseus-eng"

_REPOS: dict[str, tuple[str, str]] = {
    # repo dir under _repos/ → (URL, label)
    "perseus-greeklit": ("https://github.com/PerseusDL/canonical-greekLit.git",
                         "Perseus canonical-greekLit"),
    "perseus-latinlit": ("https://github.com/PerseusDL/canonical-latinLit.git",
                         "Perseus canonical-latinLit"),
}

_TEI = "http://www.tei-c.org/ns/1.0"

# Perseus files reference remote DTDs: never fetch them.
_XML_PARSER = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False)

_WHISTON = (
    "Translated by William Whiston (1737), from The Works of Flavius Josephus "
    "(Auburn and Rochester, NY: Alden and Beardsley, 1856); Perseus perseus-eng2"
)
_LOEB = (
    "Boethius, The Theological Tractates and The Consolation of Philosophy, "
    "Loeb Classical Library (London: Heinemann; Cambridge, MA: Harvard, 1918)"
)


@dataclass(frozen=True)
class Edition:
    """One English file: where it is, what it translates, how it was made."""

    repo: str              # clone dir under data/raw/_repos/
    path: str              # file under the clone's data/
    translation_of: str    # the original's work id
    tradition: Tradition   # the original's
    edition: str


EDITIONS: tuple[Edition, ...] = (
    Edition("perseus-greeklit", "tlg0526/tlg001/tlg0526.tlg001.perseus-eng2.xml",
            "perseus/tlg0526/tlg001/perseus-grc2", "greek", _WHISTON),
    Edition("perseus-greeklit", "tlg0526/tlg002/tlg0526.tlg002.perseus-eng2.xml",
            "perseus/tlg0526/tlg002/perseus-grc2", "greek", _WHISTON),
    Edition("perseus-greeklit", "tlg0526/tlg003/tlg0526.tlg003.perseus-eng2.xml",
            "perseus/tlg0526/tlg003/perseus-grc2", "greek", _WHISTON),
    Edition("perseus-greeklit", "tlg0526/tlg004/tlg0526.tlg004.perseus-eng2.xml",
            "perseus/tlg0526/tlg004/perseus-grc2", "greek", _WHISTON),
    Edition("perseus-latinlit", "stoa0058/stoa001/stoa0058.stoa001.perseus-eng1.xml",
            "perseus/stoa0058/stoa001/perseus-lat2", "latin",
            "Translation of 'I. T.' (1609), revised by H. F. Stewart, in " + _LOEB
            + "; Perseus perseus-eng1"),
    Edition("perseus-latinlit", "stoa0058/stoa003/stoa0058.stoa003.perseus-eng1.xml",
            "perseus/stoa0058/stoa003/perseus-lat1", "latin",
            "Translated by H. F. Stewart and E. K. Rand, in " + _LOEB + "; Perseus perseus-eng1"),
    Edition("perseus-latinlit", "stoa0058/stoa006/stoa0058.stoa006.perseus-eng1.xml",
            "perseus/stoa0058/stoa006/perseus-lat1", "latin",
            "Translated by H. F. Stewart and E. K. Rand, in " + _LOEB + "; Perseus perseus-eng1"),
    Edition("perseus-latinlit", "stoa0058/stoa023/stoa0058.stoa023.perseus-eng1.xml",
            "perseus/stoa0058/stoa023/perseus-lat1", "latin",
            "Translated by H. F. Stewart and E. K. Rand, in " + _LOEB + "; Perseus perseus-eng1"),
    Edition("perseus-latinlit", "stoa0058/stoa025/stoa0058.stoa025.perseus-eng1.xml",
            "perseus/stoa0058/stoa025/perseus-lat1", "latin",
            "Translated by H. F. Stewart and E. K. Rand, in " + _LOEB + "; Perseus perseus-eng1"),
    Edition("perseus-latinlit", "stoa0058/stoa028/stoa0058.stoa028.perseus-eng1.xml",
            "perseus/stoa0058/stoa028/perseus-lat1", "latin",
            "Translated by H. F. Stewart and E. K. Rand, in " + _LOEB + "; Perseus perseus-eng1"),
)

# Elements whose content is not text.
_DROP = frozenset({"pb", "milestone", "fw", "figure"})
# Elements that stand for a line or word break.
_BREAK = frozenset({"lb"})

# A running head the transcription carried into a paragraph (layout noise).
_RUNNING_HEAD = re.compile(r"^\s*DE TRINITATE\s*\n")

# A tractate's chapter number, alone in its paragraph ("IV.").
_CHAPTER_NUMBER = re.compile(r"^\s*([IVXL]+)\.\s*$")


# ---------------------------------------------------------------------------
# Text with editorial spans
# ---------------------------------------------------------------------------

Segment = tuple[str, str | None]  # (text, editorial kind or None)


def _local(el: etree._Element) -> str:
    return etree.QName(el).localname if isinstance(el.tag, str) else ""


def _segments(el: etree._Element, kind: str | None = None) -> list[Segment]:
    """The text of *el* as segments, each marked with the editorial kind it is in.

    A note becomes ``[note]`` marked ``note`` (inside a heading too).
    """
    out: list[Segment] = []
    if el.text:
        out.append((el.text, kind))
    for child in el:
        tag = _local(child)
        if not tag:  # comment, processing instruction
            pass
        elif tag in _DROP:
            pass
        elif tag in _BREAK:
            out.append((" ", kind))
        elif tag == "note":
            out.append((" ", kind))
            out.append(("[", "note"))
            out.extend(_segments(child, "note"))
            out.append(("]", "note"))
            out.append((" ", kind))
        elif tag == "head":
            out.extend(_segments(child, "heading"))
        elif tag == "q":
            # The markup stands for quotation marks the printed text has.
            nested = any(_local(a) == "q" for a in child.iterancestors())
            opening, closing = ("‘", "’") if nested else ("“", "”")
            out.append((opening, kind))
            out.extend(_segments(child, kind))
            out.append((closing, kind))
        else:
            out.extend(_segments(child, kind))
        if child.tail:
            out.append((child.tail, kind))
    return out


def _assemble(segments: list[Segment]) -> tuple[str, list[list]]:
    """Join *segments* with whitespace collapsed; return the text and its spans."""
    text = ""
    spans: list[list] = []
    for raw, kind in segments:
        piece = re.sub(r"\s+", " ", raw)
        if not text or text[-1] in " “‘[":
            piece = piece.lstrip(" ")
        if piece[:1] in ("”", "’", "]") and text.endswith(" "):
            text = text[:-1]
        if not piece:
            continue
        start = len(text)
        text += piece
        if kind is not None:
            # The span covers the piece without its edge spaces.
            s = start + (len(piece) - len(piece.lstrip(" ")))
            e = start + len(piece.rstrip(" "))
            if e > s:
                if spans and spans[-1][2] == kind and not text[spans[-1][1]:s].strip():
                    spans[-1][1] = e
                else:
                    spans.append([s, e, kind])
    stripped = text.rstrip(" ")
    spans = [[s, min(e, len(stripped)), k] for s, e, k in spans if s < len(stripped)]
    return stripped, spans


def _unit(ref: str, segments: list[Segment]) -> dict | None:
    text, spans = _assemble(segments)
    if not text:
        return None
    unit: dict = {"ref": slugify_ref(ref), "text": text}
    if spans:
        unit["editorial"] = spans
    return unit


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------

def _epidoc_units(body: etree._Element, cts: str) -> list[dict]:
    """Units of an EpiDoc translation: textpart divs, one unit per ``<p>``."""
    t = f"{{{_TEI}}}"
    top = body.find(f"{t}div[@type='translation']")
    if top is None:
        raise ValueError("no translation div")
    units: list[dict] = []

    def walk(div: etree._Element, path: list[str]) -> None:
        pending: list[Segment] = []
        for child in div:
            tag = _local(child)
            if tag == "div":
                n = child.get("n", "")
                walk(child, path + [n] if n else path)
            elif tag == "head":
                if div.find(f"{t}div") is not None:
                    # A book's heading: a unit of its own, the section's parent.
                    unit = _unit(".".join([cts, *path]), _segments(child, "heading"))
                    if unit:
                        units.append(unit)
                else:
                    pending += _segments(child, "heading") + [(" ", None)]
            elif tag == "p":
                unit = _unit(".".join([cts, *path]), pending + _segments(child))
                pending = []
                if unit:
                    units.append(unit)
        if pending:
            unit = _unit(".".join([cts, *path]), pending)
            if unit:
                units.append(unit)

    walk(top, [])
    return units


def _is_verse(div: etree._Element) -> bool:
    return any(_local(el) in ("lb", "quote", "l") for el in div.iter())


def _consolation_units(body: etree._Element, cts: str) -> list[dict]:
    """Units of the *Consolation*: books of metres and proses."""
    units: list[dict] = []
    for book in body.iter("div1"):
        b = book.get("n", "")
        seen: set[str] = set()
        last_prose = ""
        for chapter in book.iter("div2"):
            n = chapter.get("n", "")
            if n == "praef":  # book 1 metre 1, verse without verse markup
                label = "M1"
            elif _is_verse(chapter):
                label = "M" + n
                if label in seen and b != "1":
                    # Books 2–5 alternate prose n, metre n: the TEI numbers
                    # metre 3.8 as a second 7 (it follows prose 3.8).
                    log.info("%s %s: verse chapter numbered %s read as M%s",
                             cts, b, n, last_prose)
                    label = "M" + last_prose
            else:
                label = "P" + n
                last_prose = n
            if label in seen:
                raise ValueError(f"{cts} book {b}: two chapters read as {label}")
            seen.add(label)
            for p in chapter.iter("p"):
                unit = _unit(f"{cts}.{b}.{label}", _segments(p))
                if unit:
                    units.append(unit)
    return units


def _tractate_units(body: etree._Element, cts: str) -> list[dict]:
    """Units of a tractate: a title, then paragraphs under chapter numbers."""
    units: list[dict] = []
    head = body.find("head")
    if head is not None:
        unit = _unit(f"{cts}.title", _segments(head, "title"))
        if unit:
            units.append(unit)
    paragraphs = [p for p in body.iter("p")]
    has_chapters = any(_CHAPTER_NUMBER.match("".join(p.itertext())) for p in paragraphs)
    chapter = "pr" if has_chapters else ""
    count = 0
    pending: list[tuple[str, list[Segment]]] = []  # (ref, segments) in order
    for p in paragraphs:
        m = _CHAPTER_NUMBER.match("".join(p.itertext()))
        if m:
            chapter = str(_roman(m.group(1)))
            count = 0
            pending.append((f"{cts}.{chapter}", [(m.group(1) + ".", "heading")]))
            continue
        segments = _segments(p)
        if segments and segments[0][1] is None and _RUNNING_HEAD.match(segments[0][0]):
            # A page's running head opens a paragraph the transcription split
            # at the page break: drop the head, join the paragraph again.
            segments[0] = (_RUNNING_HEAD.sub("", segments[0][0]), None)
            if count:
                pending[-1][1].extend(segments)
                continue
        if not _assemble(segments)[0]:
            continue
        count += 1
        path = [cts, chapter, str(count)] if chapter else [cts, str(count)]
        pending.append((".".join(path), segments))
    for ref, segments in pending:
        unit = _unit(ref, segments)
        if unit:
            units.append(unit)
    return units


def _roman(s: str) -> int:
    values = {"I": 1, "V": 5, "X": 10, "L": 50}
    total = 0
    for i, c in enumerate(s):
        v = values[c]
        total += -v if i + 1 < len(s) and values[s[i + 1]] > v else v
    return total


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

def _license(root: etree._Element) -> str:
    """The file's licence, else the repository's (CC BY-SA 4.0)."""
    for lic in root.iter(f"{{{_TEI}}}licence", "licence"):
        target = lic.get("target", "")
        if "by-sa" in target:
            return "cc-by-sa-4.0"
        if target:
            raise ValueError(f"unexpected licence {target!r}")
    return "cc-by-sa-4.0"


def _header_text(root: etree._Element, path: str) -> str | None:
    for ns in (f"{{{_TEI}}}", ""):
        el = root.find(".//" + "/".join(f"{ns}{p}" for p in path.split("/")))
        if el is not None:
            return re.sub(r"\s+", " ", "".join(el.itertext())).strip() or None
    return None


def parse_edition(xml_path: Path, spec: Edition) -> tuple[Work, list[dict]]:
    """Parse one English file into its Work and units."""
    root = etree.parse(str(xml_path), _XML_PARSER).getroot()
    stem = xml_path.stem                       # tlg0526.tlg001.perseus-eng2
    textgroup, work, version = stem.split(".")
    cts = f"{textgroup}.{work}"

    body = root.find(f".//{{{_TEI}}}body")
    if body is not None:
        units = _epidoc_units(body, cts)
    else:
        body = root.find(".//body")
        if body is None:
            raise ValueError(f"{xml_path}: no body")
        if body.find(".//div1") is not None:
            units = _consolation_units(body, cts)
        else:
            units = _tractate_units(body, cts)
    units = dedupe_refs(units)
    if not units:
        raise ValueError(f"{xml_path}: no text")

    author = _header_text(root, "teiHeader/fileDesc/titleStmt/author")
    title = _header_text(root, "teiHeader/fileDesc/titleStmt/title") or stem
    language: Language = "eng"
    repo_name = "canonical-greekLit" if spec.repo == "perseus-greeklit" else "canonical-latinLit"
    w = Work(
        work_id=f"{SOURCE_ID}/{textgroup}/{work}/{version}",
        source_id=SOURCE_ID,
        author=author,
        title=title,
        date_composed=None,
        date_range=None,
        date_confidence="uncertain",
        genre="patristic",
        language=language,
        tradition=spec.tradition,
        license=_license(root),  # type: ignore[arg-type]
        provenance_url=f"https://github.com/PerseusDL/{repo_name}/blob/master/data/{spec.path}",
        edition=spec.edition,
        translation_of=spec.translation_of,
    )
    return w, units


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Parse the English editions in ``EDITIONS`` from the Perseus clones.

    Parameters
    ----------
    output_dir: Root raw output directory (``data/raw``).
    force:      Re-parse every file (and pull the clones unless offline).
    """
    for repo, (url, label) in _REPOS.items():
        ensure_repo(url, output_dir / "_repos" / repo, label, force)

    works: list[Work] = []
    for spec in EDITIONS:
        xml_path = output_dir / "_repos" / spec.repo / "data" / spec.path
        out_path = (output_dir / SOURCE_ID / spec.path).with_suffix(".json")
        if out_path.exists() and not force:
            works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
            continue
        work, units = parse_edition(xml_path, spec)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps({"work": work.model_dump(), "paragraphs": units},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("%s: %d units", work.work_id, len(units))
        works.append(work)
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
