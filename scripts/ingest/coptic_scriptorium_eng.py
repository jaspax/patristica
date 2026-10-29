"""
Ingestor for Coptic Scriptorium's English translation layer (#346).

Source: https://github.com/CopticScriptorium/corpora (the clone that
``coptic_scriptorium.py`` uses, ``data/raw/_repos/coptic-scriptorium``)
Output: ``data/raw/coptic-scriptorium-eng/{corpus_slug}.json``

Every document's TreeTagger export carries a sentence-aligned English
``<translation translation="…">`` span around the bound groups it renders.
Many documents have only placeholders there (``...``, ``…``, ``---``). The
rest are Budge's public-domain translations (1910–1914), which Coptic
Scriptorium has slightly revised and re-segmented, or the project's own. Each
Coptic work of ``coptic_scriptorium.py`` that has any real translation gets an
English work here:

- ``work_id`` ``coptic-scriptorium-eng/{corpus_slug}``, ``translation_of`` the
  Coptic work ``coptic-scriptorium/{corpus_slug}``.  The English is its own
  source so that it can be enrolled for anchored derived verses (#304)
  without enrolling the published Coptic works.
- **Refs are the Coptic units' refs** (``CopScr.{corpus}.{file}.{para}``): a
  sentence goes to the Coptic paragraph that holds its first bound group, so
  the English is cut where the Coptic is.  A paragraph without a translated
  sentence has no English unit, so a partially translated corpus gives a
  partial English work.  The Coptic paragraphs are those of
  ``coptic_scriptorium``; this module recomputes them with the position of
  each bound group and checks that they agree (``CopticLayerError`` if not).
- The licence is the documents' own (``license`` in the TT header), the most
  restrictive one when the translated documents differ.  Budge's text is
  public domain, but Coptic Scriptorium's revision is published under the
  file's licence, so that is what the work records; ``edition`` names the
  translators and Budge's volume.
- Editorial material (#236): the translators' insertions in brackets or (in
  Budge) parentheses are ``supplement`` spans, kept in the embedded text
  without the brackets; ``(?)``, ``(sic)``, ``(i. e., …)`` and ``(pl.)`` are
  ``note``s; brackets of dots are ``lacuna``e.

This module never pulls the clone: it reads the revision the Coptic works were
ingested from (it clones only when the clone is missing).
"""

from __future__ import annotations

import html
import json
import logging
import re
from pathlib import Path
from typing import NamedTuple

from lxml import etree
from tqdm import tqdm

from patristica.models import Work
from scripts.ingest import coptic_scriptorium as cs
from scripts.ingest._common import ensure_repo

log = logging.getLogger(__name__)

SOURCE_ID = "coptic-scriptorium-eng"

# A Coptic paragraph record and the positions (in document order) of the bound
# groups it holds.
Unit = tuple[dict, list[int]]


# ---------------------------------------------------------------------------
# The Coptic units, with bound-group positions
# ---------------------------------------------------------------------------

def _units_tei(root: etree._Element, file_n: int, corpus_name: str,
               norms: cs.NormMap) -> list[Unit]:
    """``cs._extract_paragraphs_tei`` with each paragraph's ``<phr>`` positions."""
    position = {el: i for i, el in enumerate(norms)}
    body = root.find(f".//{cs._TEI}body")
    if body is None:
        body = root.find(".//body")
    if body is None:
        return []
    for tag_variants in ([f"{cs._TEI}ab", "ab"], [f"{cs._TEI}p", "p"],
                         [f"{cs._TEI}s", "s"], [f"{cs._TEI}l", "l"]):
        elements = [
            el for el in body.iter()
            if isinstance(el.tag, str) and etree.QName(el.tag).localname in tag_variants
        ]
        units: list[Unit] = []
        for el in elements:
            text = cs._paragraph_text(cs._elem_words(el, norms))
            if not cs._COPTIC_RE.search(text):
                continue
            orig = cs._paragraph_text(cs._elem_words(el))
            groups = [position[p] for p in el.iter() if p in position]
            units.append((cs._paragraph(corpus_name, file_n, len(units), text, orig), groups))
        if units:
            return units
    return []


def _units_meta(root: etree._Element, file_n: int, corpus_name: str) -> list[Unit]:
    """``cs._extract_paragraphs_custom`` with each paragraph's ``<norm_group>``
    positions."""
    position = {el: i for i, el in enumerate(root.iter("norm_group"))}
    para_elems = root.findall(".//p_n")
    if not para_elems:
        para_elems = [el for el in root.iter("p") if el.get("p") == "p"]
    if not para_elems:
        para_elems = [root]
    units: list[Unit] = []
    for para_el in para_elems:
        words = cs._groups(para_el, "norm_group")
        if not words:
            continue
        text = cs._paragraph_text(words)
        if not cs._COPTIC_RE.search(text):
            continue
        orig = cs._paragraph_text(cs._groups(para_el, "orig_group"))
        groups = [position[g] for g in para_el.iter("norm_group")]
        units.append((cs._paragraph(corpus_name, file_n, len(units), text, orig), groups))
    return units


class Document(NamedTuple):
    """One XML document of a corpus: its Coptic units, the file that holds its
    English sentences, numbered as the units' bound groups are, and the file
    whose ``<meta>`` header describes it."""

    units: list[Unit]
    tt_path: Path | None
    header_path: Path | None


def _document(xml_path: Path, file_n: int, corpus_name: str) -> Document:
    """Parse one document as ``cs._extract_paragraphs_from_tei`` does.

    A TT-format document (``<meta>`` root) holds its own English sentences,
    but the copy in ``*_TEI`` has an empty ``<meta>``, so its header comes
    from the ``*_TT`` copy.  A TEI document's sentences and header are in its
    TT export, whose ``norm_group``s are its ``<phr>``s in order.
    """
    root = etree.parse(str(xml_path), etree.XMLParser(**cs._PARSER_KW)).getroot()
    if isinstance(root.tag, str) and etree.QName(root.tag).localname == "meta":
        return Document(_units_meta(root, file_n, corpus_name), xml_path,
                        cs._tt_path(xml_path) or xml_path)
    units = _units_tei(root, file_n, corpus_name, cs._norm_map(root, xml_path))
    tt_path = cs._tt_path(xml_path)
    return Document(units, tt_path, tt_path)


# ---------------------------------------------------------------------------
# The English sentences
# ---------------------------------------------------------------------------

# The tags of a TT export that matter here, in document order.  TT spans may
# cross (a <translation> can open inside an <entity> and close outside it),
# so the export is read as a stream of tags, not as a tree.
_TT_TAG_RE = re.compile(r"<(/?)(translation|norm_group|meta)\b([^>]*)>")
_TT_ATTR_RE = re.compile(r'([\w.-]+)="([^"]*)"')

# A translation that is only a placeholder for an untranslated sentence.
_PLACEHOLDER_RE = re.compile(r"[\s.…\-–—_]*")

# Translators' insertions, [word] or (word), and the notes and lacunae among them.
_INSERTION_RE = re.compile(r"\[[^\[\]]*\]|\([^()]*\)")
_DOTS_RE = re.compile(r".[\s.…]*.")
_NOTE_RE = re.compile(r"[(\[]\s*(?:\?|sic\.?|pl\.|i\.\s*e\..*)\s*[)\]]", re.IGNORECASE | re.DOTALL)

# Translator values of a document header that name nobody.
_NO_TRANSLATOR = frozenset({"", "none", "?", "checked", "unknown"})

_BUDGE = "E. A. Wallis Budge"
_BUDGE_RE = re.compile(r"Budge,?\s+(\d{4})")
# Budge's volumes of Sahidic texts (London: British Museum), all public
# domain; Coptic Scriptorium's documents cite them by year.
_BUDGE_BOOKS: dict[int, str] = {
    1910: "Coptic Homilies in the Dialect of Upper Egypt",
    1913: "Coptic Apocrypha in the Dialect of Upper Egypt",
    1914: "Coptic Martyrdoms, etc., in the Dialect of Upper Egypt",
    1915: "Miscellaneous Coptic Texts in the Dialect of Upper Egypt",
}

# Licences of translated documents, least restrictive first.
_LICENSE_ORDER = ("cc-by-4.0", "cc-by-sa-4.0", "cc-by-nc-4.0", "cc-by-nc-sa-4.0")


class CopticLicenseError(ValueError):
    """A translated document's licence is not one we can record."""


def _license(text: str) -> str:
    """The ``License`` value of a TT header's ``license`` attribute
    (``<a href='…/by-nc-sa/4.0/'>CC BY-NC-SA 4.0</a>``, ``CC-BY 4.0 -``)."""
    plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).lower()
    if "4.0" in plain:
        if re.search(r"by[- ]nc[- ]sa", plain):
            return "cc-by-nc-sa-4.0"
        if re.search(r"by[- ]nc", plain):
            return "cc-by-nc-4.0"
        if re.search(r"by[- ]sa", plain):
            return "cc-by-sa-4.0"
        if re.search(r"cc[- ]by", plain):
            return "cc-by-4.0"
    raise CopticLicenseError(f"unrecognised licence {text!r}")


class Translation(NamedTuple):
    """The English layer of one TT export."""

    header: dict[str, str]
    # Per sentence: its text ("" for a placeholder), the positions of the
    # bound groups it covers, and the number of bound groups before it.
    sentences: list[tuple[str, list[int], int]]
    groups: int


def _read_header(path: Path) -> dict[str, str]:
    """The attributes of a TT export's ``<meta>`` header."""
    m = _TT_TAG_RE.search(path.read_text(encoding="utf-8"))
    if m is None or m.group(2) != "meta":
        return {}
    return {k: html.unescape(v) for k, v in _TT_ATTR_RE.findall(m.group(3))}


def _read_translation(tt_path: Path) -> Translation:
    """The header and the English sentences of a TT export."""
    header: dict[str, str] = {}
    sentences: list[tuple[str, list[int], int]] = []
    current: list[int] | None = None
    groups = 0
    for m in _TT_TAG_RE.finditer(tt_path.read_text(encoding="utf-8")):
        closing, tag, attrs = m.groups()
        if closing:
            if tag == "translation":
                current = None
        elif tag == "meta":
            if not header:
                header = {k: html.unescape(v) for k, v in _TT_ATTR_RE.findall(attrs)}
        elif tag == "norm_group":
            if current is not None:
                current.append(groups)
            groups += 1
        else:
            values = dict(_TT_ATTR_RE.findall(attrs))
            text = cs._WS_RE.sub(" ", html.unescape(values.get("translation", ""))).strip()
            if _PLACEHOLDER_RE.fullmatch(text):
                text = ""
            current = []
            sentences.append((text, current, groups))
    return Translation(header, sentences, groups)


def _english_editorial(text: str, budge: bool) -> list[list]:
    """Editorial spans of an English unit (#236): dots in brackets are a
    lacuna; a query, *sic*, *i.e.* or *pl.* a note; any other insertion a
    supplement.  Parentheses are insertions only in Budge's translations, which
    use them for words he supplied; in the project's own translations they may
    be the author's, so only their lacunae and notes are marked."""
    spans: list[list] = []
    for m in _INSERTION_RE.finditer(text):
        span = m.group(0)
        if _DOTS_RE.fullmatch(span):
            kind = "lacuna"
        elif _NOTE_RE.fullmatch(span):
            kind = "note"
        elif span.startswith("[") or budge:
            kind = "supplement"
        else:
            continue
        spans.append([m.start(), m.end(), kind])
    return spans


def _english_units(units: list[Unit], tr: Translation, budge: bool) -> list[dict]:
    """The English units of one document, on its Coptic units' refs.

    A sentence goes to the unit holding the first of its bound groups that a
    unit holds; a sentence over no unit's bound groups goes to the unit before
    it, or the first unit.
    """
    owner: dict[int, int] = {}
    for n, (_, groups) in enumerate(units):
        for g in groups:
            owner.setdefault(g, n)
    texts: dict[int, list[str]] = {}
    for text, groups, start in tr.sentences:
        if not text or not units:
            continue
        n = next((owner[g] for g in groups if g in owner), None)
        if n is None:
            n = max((u for g, u in owner.items() if g < start), default=0)
        texts.setdefault(n, []).append(text)
    out: list[dict] = []
    for n in sorted(texts):
        text = " ".join(texts[n])
        record: dict = {"ref": units[n][0]["ref"], "text": text}
        spans = _english_editorial(text, budge)
        if spans:
            record["editorial"] = spans
        out.append(record)
    return out


def _translators(header: dict[str, str]) -> list[str]:
    """The translators a TT header names."""
    value = header.get("translation", "").strip()
    if value.lower() in _NO_TRANSLATOR:
        return []
    return [name.strip() for name in value.split(",") if name.strip()]


def _english_title(title: str) -> str:
    """The English work's title: the Coptic work's, without "(Coptic …)"."""
    return re.sub(r"\s*\(Coptic[^)]*\)$", "", title)


def _english_work(corpus_name: str, corpus_slug: str, meta: dict,
                  headers: list[dict[str, str]]) -> Work:
    """The English work of a corpus, from the headers of its translated documents.

    Its licence is the most restrictive of theirs (they agree in every corpus
    so far)."""
    licenses = {_license(h.get("license", "")) for h in headers}
    license = max(licenses, key=_LICENSE_ORDER.index)
    if len(licenses) > 1:
        log.warning("  %s: translated documents have licences %s; recording %s",
                    corpus_name, sorted(licenses), license)
    names: list[str] = []
    for h in headers:
        for name in _translators(h):
            if name not in names:
                names.append(name)
    budge_years = sorted({
        int(y) for h in headers if _BUDGE in h.get("translation", "")
        for y in _BUDGE_RE.findall(re.sub(r"<[^>]+>", " ", h.get("Coptic_edition", "")))
    })
    edition = f"Coptic Scriptorium, {corpus_name}: English translation"
    if names:
        edition += " by " + ", ".join(names)
    if budge_years:
        books = "; ".join(f"{_BUDGE_BOOKS[y]} ({y})" for y in budge_years)
        edition += (f", from Budge, {books} (public domain), "
                    "slightly revised and segmented by Coptic Scriptorium")
    return Work(
        work_id=f"{SOURCE_ID}/{corpus_slug}",
        source_id=SOURCE_ID,
        author=meta["author"],
        title=_english_title(meta["title"]),
        date_composed=meta["date_composed"],
        date_range=meta["date_range"],
        date_confidence=meta["date_confidence"],
        genre=meta["genre"],
        language="eng",
        tradition="coptic",
        license=license,
        provenance_url=f"{cs._REPO_URL}/tree/master/{corpus_name}",
        edition=edition,
        translation_of=f"{cs.SOURCE_ID}/{corpus_slug}",
    )


def _english(corpus_name: str, corpus_slug: str, meta: dict,
             docs: list[Document]) -> tuple[Work, list[dict]] | None:
    """The English work and units of a corpus, or None when it has no translation."""
    headers: list[dict[str, str]] = []
    units: list[dict] = []
    for doc in docs:
        if doc.tt_path is None:
            continue
        tr = _read_translation(doc.tt_path)
        last = max((g for _, gs in doc.units for g in gs), default=-1)
        if last >= tr.groups:
            raise cs.CopticLayerError(
                f"{doc.tt_path}: {tr.groups} norm_group, but the text has bound group {last}")
        if not any(text for text, _, _ in tr.sentences):
            continue
        header = tr.header
        if doc.header_path is not None and doc.header_path != doc.tt_path:
            header = _read_header(doc.header_path)
        headers.append(header)
        units.extend(_english_units(doc.units, tr, _BUDGE in header.get("translation", "")))
    if not units:
        return None
    return _english_work(corpus_name, corpus_slug, meta, headers), units


def _corpus_documents(corpus_dir: Path) -> list[Document]:
    """The documents of a corpus, with the same paragraphs (refs and text) as
    ``coptic_scriptorium`` writes for it; ``CopticLayerError`` if they differ."""
    tei_dir = corpus_dir / f"{corpus_dir.name}_TEI"
    if not tei_dir.exists():
        candidates = list(corpus_dir.glob("*_TEI"))
        tei_dir = candidates[0] if candidates else tei_dir
    docs: list[Document] = []
    for file_n, xml_path in enumerate(sorted(tei_dir.glob("*.xml"))):
        doc = _document(xml_path, file_n, corpus_dir.name)
        coptic = cs._extract_paragraphs_from_tei(xml_path, file_n, corpus_dir.name)
        if [p for p, _ in doc.units] != coptic:
            raise cs.CopticLayerError(
                f"{xml_path}: paragraphs differ from coptic_scriptorium's")
        docs.append(doc)
    return docs


# ---------------------------------------------------------------------------
# Ingestor
# ---------------------------------------------------------------------------

def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Write one English work per translated Coptic Scriptorium corpus."""
    repo_dir = Path(output_dir) / "_repos" / "coptic-scriptorium"
    # Never pull: the English must come from the revision the Coptic was
    # ingested from (coptic_scriptorium.py pulls on --force).
    ensure_repo(cs._REPO_URL, repo_dir, "Coptic Scriptorium", False)

    out_root = Path(output_dir) / SOURCE_ID
    out_root.mkdir(parents=True, exist_ok=True)

    works: list[Work] = []
    corpus_dirs = sorted(d for d in repo_dir.iterdir() if d.is_dir() and not d.name.startswith("."))
    for corpus_dir in tqdm(corpus_dirs, desc="Coptic Scriptorium English"):
        corpus_name = corpus_dir.name
        meta = cs._corpus_meta(corpus_name)
        if meta is None:
            continue
        corpus_slug = corpus_name.replace("-", "_")
        out_path = out_root / f"{corpus_slug}.json"
        if out_path.exists() and not force:
            works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
            continue
        try:
            english = _english(corpus_name, corpus_slug, meta, _corpus_documents(corpus_dir))
        except (cs.CopticLayerError, CopticLicenseError, etree.XMLSyntaxError) as exc:
            log.error("  Skipping %s: %s", corpus_name, exc)
            continue
        if english is None:
            out_path.unlink(missing_ok=True)
            continue
        work, units = english
        out_path.write_text(
            json.dumps({"work": work.model_dump(), "paragraphs": units},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("  Wrote %s (%d paragraphs)", out_path.name, len(units))
        works.append(work)
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
