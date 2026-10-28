"""
Ingestor for the Digital Syriac Corpus (#79).

Source: https://github.com/srophe/syriac-corpus (``data/tei/{id}.xml`` = https://syriaccorpus.org/{id})
Format: TEI P5, one file per text (a demonstration, a book of a history)
License: CC-BY 4.0 for the TEI ("The Syriac base text is in the public domain. The TEI XML
         edition is copyrighted by James E. Walters and is released under a Creative Commons
         Attribution 4.0 International Public License")

The works are :data:`WORKS` (the originals of English works in the corpus,
#79) and the rows of ``scripts/ingest/data/dsc_works.csv`` (the rest of the
corpus, #322: one row per work, grouped by DSC's series).  Left out: the
Peshitta New Testament (covered by ``pta-peshitta``) and the authors after the
collection period (Dionysius bar Salibi, Bar Hebraeus, Timothy II).  Most of the
#79 texts come from editions in the public domain (Parisot
1894–1907, Phillips 1876, Cureton 1855, Wright–McLean 1898).  Ephrem's hymns
and Bardaisan are transcribed from Beck's CSCO volumes (1959–63) and Drijvers
(1965); they, and the other modern editions in the CSV, are taken under the
corpus's CC BY 4.0, which states that the Syriac base text is in the public
domain (a decision recorded on #79).  Most
files are ``uncorrectedTranscription``.

A work may join several files: Aphrahat's 23 demonstrations and the letter
are one work, as the English *Select Demonstrations* is one work; the books of
the Syriac *Ecclesiastical History* are one work.

Text and refs
-------------
- ``div[@type='section'][@n]``: one unit, ``{prefix}.{n}`` (several ``<p>`` are
  joined); the Eusebius sections are numbered book.chapter (``1.13`` in
  the file with prefix ``EusHE.1`` → ``EusHE.1.13``).
- A file with no sections (Addai, Mara, the Hypomnemata) is cut at its page
  breaks: one unit per printed page, ``{prefix}.{page}``.
- The title div is the file's heading (``{prefix}``); a table of contents,
  rubric, melody, response or superscript outside the sections becomes
  ``{prefix}.{kind}.{k}`` (``Ephr.Nis.1.melody.1``).
- A book div identical to one before it is skipped (Books 8 and 9 of the
  *History* are in their files twice).
- Consecutive ``<l>`` lines are one unit, joined by " / ".  ``<head type="editorial">``
  (the section number again) and ``<note>`` are dropped.
"""

from __future__ import annotations

import csv
import json
import logging
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from patristica.models import Work
from scripts.ingest._common import require_network, slugify_ref

log = logging.getLogger(__name__)

SOURCE_ID = "dsc"

_REPO_URL = "https://github.com/srophe/syriac-corpus.git"
_TEI = "http://www.tei-c.org/ns/1.0"
_NS = {"t": _TEI}
_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_XML_PARSER = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False)
_SKIP = frozenset({"note", "head", "fw", "figure"})


# DSC file id → hymn number (Beck's numbering; Nisibene 8 and 22–24 are lost).
_NISIBENE: tuple[tuple[int, int], ...] = tuple(
    zip(range(259, 332), (h for h in range(1, 78) if h not in (8, 22, 23, 24))))
_NATIVITY: tuple[tuple[int, int], ...] = tuple((548 + h, h) for h in range(1, 29))


@dataclass(frozen=True)
class DscWork:
    slug: str
    files: tuple[tuple[int, str], ...]  # (DSC id, ref prefix)
    title: str
    author: str | None
    date_composed: int | None
    date_range: tuple[int, int] | None
    date_confidence: str
    edition: str
    genre: str = "patristic"


_WORKS_CSV = Path(__file__).parent / "data" / "dsc_works.csv"


def load_csv_works(path: Path = _WORKS_CSV) -> tuple[DscWork, ...]:
    """The works of ``data/dsc_works.csv`` (#322): the rest of the corpus, one row per work.

    A row's ``ids`` are its DSC files in order; with several, file *k* gets the
    ref prefix ``{prefix}.{k}``.  Blank dates leave the work to its author's.
    """
    with path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(line for line in f if not line.startswith("#")))
    works = []
    for r in rows:
        ids = [int(x) for x in r["ids"].split()]
        files = ((ids[0], r["prefix"]),) if len(ids) == 1 else \
            tuple((n, f"{r['prefix']}.{k}") for k, n in enumerate(ids, 1))
        start, end = r["date_start"].strip(), r["date_end"].strip()
        works.append(DscWork(
            r["slug"], files, r["title"], r["author"] or None,
            int(r["date_composed"]) if r["date_composed"].strip() else None,
            (int(start), int(end)) if start else None, r["date_confidence"], r["edition"],
            r["genre"]))
    return tuple(works)


WORKS: tuple[DscWork, ...] = (
    DscWork("aphrahat-demonstrations",
            tuple((n, f"Aphr.Dem.{n}") for n in range(1, 24)) + ((24, "Aphr.Ep"),),
            "Taḥwyātā (Demonstrations)", "Aphrahat", 340, (337, 345), "established",
            "J. Parisot, Patrologia Syriaca I.1–2 (Paris 1894–1907)"),
    DscWork("doctrina-addai", ((475, "Addai"),),
            "Malponutā d-Addai šliḥā (Doctrine of Addai)", None, 400, (300, 450), "uncertain",
            "G. Phillips, The Doctrine of Addai, the Apostle (London 1876)"),
    DscWork("eusebius-historia-ecclesiastica",
            tuple(zip(range(476, 485), (f"EusHE.{b}" for b in (1, 2, 3, 4, 5, 7, 8, 9, 10)))),
            "Ecclesiastical History, Syriac version (Books 1–5, 7–10)", "Eusebius of Caesarea",
            420, (380, 462), "approximate",
            "W. Wright and N. McLean, The Ecclesiastical History of Eusebius in Syriac "
            "(Cambridge 1898); the translation is extant in a manuscript of 462"),
    DscWork("mara-bar-serapion", ((488, "Mara"),),
            "Letter of Mara bar Serapion", "Mara bar Serapion", 75, (73, 200), "uncertain",
            "W. Cureton, Spicilegium Syriacum (London 1855)"),
    DscWork("ephrem-carmina-nisibena",
            tuple((n, f"Ephr.Nis.{h}") for n, h in _NISIBENE),
            "Carmina Nisibena (Madrashe on Nisibis)", "Ephrem the Syrian", 363, (350, 373),
            "approximate", "E. Beck, CSCO 218/240 (Louvain 1961–63)"),
    DscWork("ephrem-de-nativitate",
            tuple((n, f"Ephr.Nat.{h}") for n, h in _NATIVITY),
            "Hymni de Nativitate (Madrashe on the Nativity)", "Ephrem the Syrian", 363, (350, 373),
            "approximate", "E. Beck, CSCO 186 (Louvain 1959)"),
    DscWork("bardaisan-laws-of-countries", ((186, "LegReg"),),
            "Book of the Laws of Countries", "Bardaisan of Edessa", 210, (196, 225), "approximate",
            "H. J. W. Drijvers, The Book of the Laws of Countries (Assen 1965)"),
    DscWork("hypomnemata", ((525, "Hypomn"),),
            "Hypomnemata (Against the Greeks; ascribed to Ambrose, a version of Ps.-Justin's "
            "Oratio ad Graecos)", None, 200, (150, 250), "uncertain",
            "W. Cureton, Spicilegium Syriacum (London 1855)"),
)


def _ensure_repo(repo_dir: Path, force: bool) -> None:
    """Sparse-clone the corpus's ``data/tei`` into *repo_dir*; pull on *force*."""
    if not repo_dir.exists():
        require_network(f"cloning {_REPO_URL}")
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth=1", "--filter=blob:none", "--sparse",
                        _REPO_URL, str(repo_dir)], check=True)
        subprocess.run(["git", "-C", str(repo_dir), "sparse-checkout", "set", "data/tei"],
                       check=True)
    elif force:
        subprocess.run(["git", "-C", str(repo_dir), "pull", "--ff-only"], check=True)


def _text(el: etree._Element) -> str:
    """*el*'s text without the skipped elements, whitespace collapsed."""
    parts = [el.text or ""]
    for child in el:
        if isinstance(child.tag, str) and etree.QName(child).localname not in _SKIP:
            parts.append(_text(child))
        parts.append(child.tail or "")
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _section_ref(prefix: str, n: str) -> str:
    """``Aphr.Dem.1`` + ``3`` → ``Aphr.Dem.1.3``; ``EusHE.1`` + ``1.13`` → ``EusHE.1.13``."""
    book = prefix.rsplit(".", 1)[-1]
    return f"{prefix}.{n[len(book) + 1:]}" if n.startswith(f"{book}.") else f"{prefix}.{n}"


def _is_l(el: etree._Element | None) -> bool:
    return el is not None and isinstance(el.tag, str) and etree.QName(el).localname == "l"


def _pages(p: etree._Element, page: str) -> tuple[list[tuple[str, str]], str]:
    """Split paragraph *p* at its ``<pb n>``: ``[(page, text)]`` and the page it ends on."""
    out: list[tuple[str, list[str]]] = [(page, [p.text or ""])]
    for child in p:
        if isinstance(child.tag, str) and etree.QName(child).localname == "pb":
            page = child.get("n") or page
            out.append((page, []))
        elif isinstance(child.tag, str) and etree.QName(child).localname not in _SKIP:
            out[-1][1].append(_text(child))
        out[-1][1].append(child.tail or "")
    return [(pg, re.sub(r"\s+", " ", "".join(t)).strip()) for pg, t in out], page


def parse_file(path: Path, prefix: str) -> list[dict[str, str]]:
    """The units of one DSC file (see the module docstring)."""
    body = etree.parse(str(path), _XML_PARSER).getroot().find(".//t:text/t:body", _NS)
    if body is None:
        raise ValueError(f"{path.name}: no body")
    has_sections = body.find(".//t:div[@type='section']", _NS) is not None
    # Several titles: parts (Titus's four books, Balai's poems) whose sections restart.
    in_parts = len(body.findall(".//t:div[@type='title']", _NS)) > 1
    part = 0
    records: list[dict[str, str]] = []
    counters: dict[str, int] = {}
    books_seen: set[str] = set()
    page = "0"

    def add(ref: str, text: str) -> None:
        if text:
            records.append({"ref": slugify_ref(ref), "text": text})

    def numbered(kind: str) -> str:
        counters[kind] = counters.get(kind, 0) + 1
        return f"{prefix}.{kind}.{counters[kind]}"

    def walk(el: etree._Element, section: str | None, kind: str | None) -> None:
        nonlocal page, part
        for child in el:
            if not isinstance(child.tag, str):
                continue
            tag = etree.QName(child).localname
            if (child.get(_XML_LANG) or "").startswith("en") and not (
                    tag == "div" and child.get("type") == "title"):
                continue  # an English translation, note or apparatus in the file
            if "footnote" in (child.get("rend") or ""):
                continue
            if tag == "pb":
                page = child.get("n") or page
            elif tag == "div":
                dtype = child.get("type", "")
                if dtype == "book":
                    whole = "".join(child.itertext())
                    if whole in books_seen:  # Books 8 and 9 are transcribed twice, identically
                        log.info("%s: book %s repeats an earlier copy; skipped", path.name,
                                 child.get("n"))
                        continue
                    books_seen.add(whole)
                base = f"{prefix}.{part}" if in_parts and part else prefix
                if dtype == "section" and child.get("n"):
                    walk(child, _section_ref(base, child.get("n")), None)
                elif dtype == "title" and in_parts:  # each title starts a part
                    part += 1
                    add(f"{prefix}.{part}", " ".join(_text(x) for x in child
                                                     if isinstance(x.tag, str)))
                elif dtype == "title":
                    add(prefix, " ".join(_text(x) for x in child if isinstance(x.tag, str)))
                elif dtype in ("toc", "rubric", "melody", "response", "superscript"):
                    walk(child, None, dtype)
                else:
                    walk(child, section, kind)
            elif tag in ("p", "ab", "lg", "l"):
                if tag == "l" and _is_l(child.getprevious()):
                    continue  # part of the unit its run's first line started
                if tag == "l":
                    lines, nxt = [child], child.getnext()
                    while _is_l(nxt):
                        lines.append(nxt)
                        nxt = nxt.getnext()
                    text = " / ".join(t for t in (_text(x) for x in lines) if t)
                else:
                    text = _text(child)
                if section is not None:
                    add(section, text)
                elif kind is not None:
                    add(numbered(kind), text)
                elif not has_sections and tag in ("p", "ab"):
                    pieces, page = _pages(child, page)
                    for pg, piece in pieces:
                        add(f"{prefix}.{pg}", piece)
                else:
                    add(numbered("text"), text)
            elif tag not in _SKIP:
                walk(child, section, kind)

    walk(body, None, None)
    return _number_repeats(records)


def _number_repeats(records: list[dict[str, str]]) -> list[dict[str, str]]:
    """Join units that share a ref in a row (a page, a section); letter later repeats (184b)."""
    merged: list[dict[str, str]] = []
    for r in records:
        if merged and merged[-1]["ref"] == r["ref"]:
            merged[-1] = {"ref": r["ref"], "text": f"{merged[-1]['text']} {r['text']}"}
        else:
            merged.append(r)
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for r in merged:  # a number used again later (a second series of sections): 184b, 184c
        ref, letter = r["ref"], ord("b")
        while ref in seen:
            ref = f"{r['ref']}{chr(letter)}"
            letter += 1
        if ref != r["ref"]:
            log.info("ref %s repeats; renamed %s", r["ref"], ref)
        seen.add(ref)
        out.append({**r, "ref": ref})
    return out


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Clone the Digital Syriac Corpus and write one raw JSON file per work in :data:`WORKS`."""
    repo_dir = output_dir / "_repos" / "syriac-corpus"
    _ensure_repo(repo_dir, force)
    tei = repo_dir / "data" / "tei"
    works: list[Work] = []
    for spec in WORKS + load_csv_works():
        out_path = output_dir / SOURCE_ID / f"{spec.slug}.json"
        if out_path.exists() and not force:
            works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
            continue
        paragraphs: list[dict[str, str]] = []
        for dsc_id, prefix in spec.files:
            paragraphs.extend(parse_file(tei / f"{dsc_id}.xml", prefix))
        ids = [f"https://syriaccorpus.org/{n}" for n, _ in spec.files]
        work = Work(
            work_id=f"{SOURCE_ID}/{spec.slug}",
            source_id=SOURCE_ID,
            author=spec.author,
            title=spec.title,
            date_composed=spec.date_composed,
            date_range=spec.date_range,
            date_confidence=spec.date_confidence,  # type: ignore[arg-type]
            genre=spec.genre,  # type: ignore[arg-type]
            language="syc",
            tradition="syriac",
            license="cc-by-4.0",
            provenance_url=ids[0] if len(ids) == 1 else f"{ids[0]} … {ids[-1]}",
            edition=f"{spec.edition}; TEI by J. E. Walters, Digital Syriac Corpus "
                    f"(syriaccorpus.org {', '.join(str(n) for n, _ in spec.files)})",
            translation_of=None,
        )
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"work": work.model_dump(), "paragraphs": paragraphs},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
        works.append(work)
    log.info("Digital Syriac Corpus: %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
