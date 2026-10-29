"""
Ingestor for the Patristic Text Archive's own English translations (#345).

Source: the PTA clone that ``scripts.ingest.pta`` maintains (``data/raw/pta/data``;
run that ingestor first). This module never pulls it.
License: per file, from ``<licence @target>`` (CC BY 4.0 / CC BY-SA 4.0).

PTA files whose text is a ``<div type="translation">`` are modern translations;
``scripts.ingest.pta`` reads only edition divs and skips them. They are a source
of their own, ``pta-eng``, so that it can be enrolled for anchored derived
verses (#304) without re-cutting the PTA editions that translate one another
(``pta-xcl1``, ``pta-lat1``); compare ``first1k-eng`` and ``perseus-eng``.

The English ones become English works with ``translation_of`` set to the work id
of the PTA edition they render, named by the div's ``@corresp``. When that
edition is not in the corpus (a Church Slavonic intermediary, a witness outside
the collection period), the translation is linked to the original named in
:data:`_ORIGINAL_FALLBACK`, and its ``edition`` says which version it was made
from; without a fallback it is skipped. Translations into other languages are
skipped (#367). A work is dated as its original.

A translator's material is marked as editorial (#236), not dropped: headings
(``<head>``) become units of their own, wholly ``title``/``heading``; notes
(``<note>``, ``type="commentary"``) are kept in square brackets as ``note``
spans, as are manuscript variants written into the text ("(P: judgement)");
words the translator or editor supplied for the sense (``<note
type="explanation">``, ``<supplied>``) stay in the text as ``supplement``
spans. A heading's ref is its div's ref, so the div's paragraphs are numbered
below it (``….3.1.3`` heading, ``….3.1.3.1`` paragraph).

Work ids are ``pta-eng/{textgroup}/{work}/{version}``
(``pta-eng/pta0200/pta001/pta-eng1``); refs use the PTA CTS work id as in
``scripts.ingest.pta``.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from lxml import etree
from tqdm import tqdm

from patristica.models import Language, Work
from scripts.ingest._common import dedupe_refs, slugify_ref
from scripts.ingest.pta import (
    _CTS_NS,
    _LANG_MAP,
    _SKIP_PATTERNS,
    _TEI,
    _extract_dates,
    _license_from_target,
    _parse_pta_file,
    _read_author_name,
    read_work_ids,
)

log = logging.getLogger(__name__)

SOURCE_ID = "pta-eng"

# Translation div language → ISO 639-3. Only English translations are ingested
# (#345); PTA writes both ``eng`` and ``en``.
_TRANSLATION_LANGS: dict[str, Language] = {"eng": "eng", "en": "eng"}

# Language names for a translation's ``edition`` ("from the Syriac edition …").
_LANG_NAMES: dict[str, str] = {
    "grc": "Greek", "lat": "Latin", "syc": "Syriac", "xcl": "Classical Armenian",
    "cop": "Coptic", "gez": "Ge'ez", "chu": "Church Slavonic", "got": "Gothic",
}

#: Translations whose ``@corresp`` names a version not in the corpus: the
#: edition of the original they are linked to instead (CTS version id of the
#: same work). A translation of a translation keeps its intermediary in
#: ``edition``.
_ORIGINAL_FALLBACK: dict[str, str] = {
    # Coșcodan's English is made from the Slavonic of the Velikie Minei Chetii
    # (pta-chu1, not in the corpus yet: #335); the Greek it renders is the
    # PTA text of PG 65 (pta-grc2, same sections).
    "pta0001.pta028.pta-eng2": "pta-grc2",
}

# Editorial span kinds of a translation (patristica.editorial.KINDS; ingestors
# don't import it, #130).
_SUPPLEMENT_NOTES = frozenset({"explanation"})

# --- Translations (#345) -----------------------------------------------------

# Sentinels that mark editorial spans while whitespace is collapsed: an opener
# per kind and one closer (Unicode private use, never in PTA text).
_OPEN = {"supplement": "", "note": ""}
_KIND_OF = {v: k for k, v in _OPEN.items()}
_CLOSE = ""
_VARIANT_NOTE = re.compile(r"\([A-Z]{1,2}(?: has an addition)?: [^()-]*\)")


def _is_element(node: etree._Element) -> bool:
    return isinstance(node.tag, str)


def _plain_text(el: etree._Element) -> str:
    """All element text under *el* (comments and processing instructions left out)."""
    parts: list[str] = [el.text or ""]
    for child in el:
        if _is_element(child):
            parts.append(_plain_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _marked_text(el: etree._Element) -> str:
    """Text of a translation paragraph, with sentinels around editorial material."""
    parts: list[str] = [el.text or ""]
    for child in el:
        if _is_element(child):
            tag = etree.QName(child).localname
            if tag == "note" and child.get("type") not in _SUPPLEMENT_NOTES:
                parts.append(f" {_OPEN['note']}[{_plain_text(child).strip()}]{_CLOSE} ")
            elif tag in ("note", "supplied"):
                parts.append(f"{_OPEN['supplement']}{_plain_text(child)}{_CLOSE}")
            else:
                parts.append(_marked_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _spans_from_marked(marked: str) -> tuple[str, list[list[int | str]]]:
    """Collapse whitespace in *marked* and turn its sentinels into spans."""
    s = re.sub(r"\s+", " ", marked).strip()
    # No space before punctuation (left by markup such as an empty <ref/>
    # before </quote>, or by a note, which goes after the word it glosses).
    s = re.sub(rf" (?={_CLOSE}?[.,;:!?)])", "", s)
    # A manuscript variant written into the running text: "(P: judgement)",
    # "(P has an addition: …)".
    s = re.sub(_VARIANT_NOTE, lambda m: f"{_OPEN['note']}{m.group(0)}{_CLOSE}", s)
    text: list[str] = []
    spans: list[list[int | str]] = []
    pos = 0
    kind: str | None = None
    start = 0
    for ch in s:
        if ch in _KIND_OF:
            kind, start = _KIND_OF[ch], pos
        elif ch == _CLOSE:
            if kind is not None:
                spans.append([start, pos, kind])
            kind = None
        else:
            text.append(ch)
            pos += 1
    out = "".join(text)
    # The text was stripped, so trim each span to its non-blank part.
    trimmed: list[list[int | str]] = []
    for s0, e0, k in spans:
        assert isinstance(s0, int) and isinstance(e0, int)
        while s0 < e0 and out[s0] == " ":
            s0 += 1
        while e0 > s0 and out[e0 - 1] == " ":
            e0 -= 1
        if s0 < e0:
            trimmed.append([s0, e0, k])
    return out, trimmed


def _translation_units(div: etree._Element, work_cts_id: str) -> list[dict]:
    """Units of a ``<div type="translation">``: headings and paragraphs, marked."""
    records: list[dict] = []

    def _ref(path_parts: list[str]) -> str:
        return slugify_ref(".".join([work_cts_id] + path_parts))

    def _walk(element: etree._Element, path_parts: list[str]) -> None:
        if not _is_element(element):
            return
        tag = etree.QName(element).localname
        if tag == "head":
            text = re.sub(r"\s+", " ", _plain_text(element)).strip()
            if text:
                kind = "heading" if records else "title"
                records.append({"ref": _ref(path_parts), "text": text,
                                "editorial": [[0, len(text), kind]]})
            return
        if tag in ("p", "ab"):
            text, spans = _spans_from_marked(_marked_text(element))
            if text:
                rec: dict = {"ref": _ref(path_parts), "text": text}
                if spans:
                    rec["editorial"] = spans
                records.append(rec)
            return
        if tag == "div" and element.get("type") == "textpart":
            n = element.get("n", "")
            new_parts = path_parts + [n] if n and re.match(r"^[\w\-]+$", n) else path_parts
            for child in element:
                _walk(child, new_parts)
            return
        if tag not in ("note", "pb", "lb", "cb", "fw", "figure", "table"):
            for child in element:
                _walk(child, path_parts)

    for child in div:
        _walk(child, [])
    return dedupe_refs(records)


def _cts_translation_year(cts_path: Path, urn: str) -> str | None:
    """``dct:dateCopyrighted`` of the translation *urn* in its ``__cts__.xml``."""
    if not cts_path.exists():
        return None
    root = etree.parse(str(cts_path)).getroot()
    for el in root.iter(f"{{{_CTS_NS}}}translation"):
        if el.get("urn") == urn:
            date = el.find(".//{http://purl.org/dc/terms/}dateCopyrighted")
            if date is not None and (date.text or "").strip():
                return date.text.strip()
    return None


def _edition_language(xml_path: Path) -> str | None:
    """The ``xml:lang`` of a PTA file's edition div, or None."""
    if not xml_path.exists():
        return None
    root = etree.parse(str(xml_path)).getroot()
    div = root.find(".//{%s}text/{%s}body/{%s}div[@type='edition']" % (_TEI, _TEI, _TEI))
    if div is None:
        return None
    return div.get("{http://www.w3.org/XML/1998/namespace}lang")


def _in_corpus(xml_path: Path) -> bool:
    """Whether this ingestor writes *xml_path* as a work (an edition in period, with text)."""
    if not xml_path.exists() or _SKIP_PATTERNS.search(xml_path.name):
        return False
    if _edition_language(xml_path) not in _LANG_MAP:
        return False
    result = _parse_pta_file(xml_path, None)
    return result is not None and bool(result[1])


def _parse_translation(
    xml_path: Path,
    root: etree._Element,
    div: etree._Element,
    author_name: str | None,
    external_ids: list[str] | None,
) -> tuple[Work, list[dict]] | None:
    """Parse an English ``<div type="translation">`` file (#345)."""
    ns = {"tei": _TEI}
    xml_lang = div.get("{http://www.w3.org/XML/1998/namespace}lang", "")
    language = _TRANSLATION_LANGS.get(xml_lang)
    if language is None:
        log.debug("Translation into %r in %s — skipping (#367)", xml_lang, xml_path)
        return None

    urn = div.get("n", "")
    cts_parts = urn.rsplit(":", 1)[-1].split(".")
    if len(cts_parts) != 3:
        log.error("Translation %s has no CTS version URN (%r) — skipping", xml_path, urn)
        return None
    author_id, work_id_short, version = cts_parts
    work_cts_id = f"{author_id}.{work_id_short}"
    work_dir = xml_path.parent

    # --- The edition it renders, and the original it is linked to ---
    corresp = div.get("corresp", "").rsplit(":", 1)[-1]
    source_version = corresp.split(".")[-1] if corresp.startswith(work_cts_id + ".") else ""
    source_path = work_dir / f"{work_cts_id}.{source_version}.xml"
    original_version: str | None = None
    if source_version and _in_corpus(source_path):
        original_version = source_version
    elif f"{work_cts_id}.{version}" in _ORIGINAL_FALLBACK:
        original_version = _ORIGINAL_FALLBACK[f"{work_cts_id}.{version}"]
        if not _in_corpus(work_dir / f"{work_cts_id}.{original_version}.xml"):
            log.error("Fallback original %s of %s is not in the corpus — skipping",
                      original_version, xml_path)
            return None
    else:
        log.info("Original %r of translation %s is not in the corpus — skipping",
                 corresp, xml_path.name)
        return None

    # --- Licence ---
    license_val = _license_from_target(root)
    if license_val is None:
        log.error("No usable licence in %s — skipping", xml_path)
        return None

    # --- Title: the translation's own, without a leading "Author: " ---
    title_el = root.find(".//tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", ns)
    title = re.sub(r"\s+", " ", _plain_text(title_el)).strip() if title_el is not None else ""
    if title_el is not None and title_el.find("tei:persName", ns) is not None and ": " in title:
        title = title.split(": ", 1)[1]
    title = title or xml_path.stem

    # --- Edition: translator, year, and what it was made from ---
    translators: list[str] = []
    for resp in root.findall(".//tei:teiHeader/tei:fileDesc/tei:titleStmt/*", ns):
        role = resp.find("tei:roleName", ns)
        name = resp.find("tei:persName", ns)
        if role is not None and (role.text or "").strip() == "Translator" and name is not None:
            translators.append(re.sub(r"\s+", " ", _plain_text(name)).strip())
    year = _cts_translation_year(work_dir / "__cts__.xml", urn)
    if year is None:
        date_el = root.find(".//tei:publicationStmt/tei:date", ns)
        year = (date_el.text or "").strip() if date_el is not None else None
    by = f" by {' and '.join(translators)}" if translators else ""
    published = f"Patristic Text Archive, {year}" if year else "Patristic Text Archive"
    original_path = work_dir / f"{work_cts_id}.{original_version}.xml"
    original_lang = _LANG_NAMES.get(_edition_language(original_path) or "", "")
    edition = (f"{version}: English translation{by} ({published}) "
               f"of the {original_lang} text {original_version}").replace("  ", " ")
    if source_version and source_version != original_version:
        source_lang = _LANG_NAMES.get(_edition_language(source_path) or "", "")
        edition += f", made from the {source_lang} version {source_version}".replace("  ", " ")

    # The original's composition date (a translation's header may give a wider
    # range than its original's: 30–1500 against 30–800). The original is in
    # the corpus, so it is in period.
    original_root = etree.parse(str(work_dir / f"{work_cts_id}.{original_version}.xml")).getroot()
    date_composed, date_range, date_confidence = _extract_dates(original_root)

    work = Work(
        work_id=f"{SOURCE_ID}/{author_id}/{work_id_short}/{version}",
        source_id=SOURCE_ID,
        author=author_name,
        title=title,
        date_composed=date_composed,
        date_range=date_range,
        date_confidence=date_confidence,
        genre="patristic",
        language=language,
        tradition=None,
        license=license_val,
        provenance_url=f"https://github.com/PatristicTextArchive/pta_data/blob/main/data/{author_id}/{work_id_short}/{xml_path.name}",
        edition=edition,
        translation_of=f"pta/{author_id}/{work_id_short}/{original_version}",
        external_ids=external_ids or [],
    )
    return work, _translation_units(div, work_cts_id)


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Ingest PTA's English translations from the PTA clone in ``output_dir/pta``.

    Parameters
    ----------
    output_dir: Root raw output directory (``data/raw``).
    force:      If True, re-parse files already written.
    """
    pta_data_dir = output_dir / "pta" / "data"
    if not pta_data_dir.exists():
        raise FileNotFoundError(
            f"Expected the PTA clone at {pta_data_dir}: run scripts.ingest.pta first")

    xml_files = [
        p for p in sorted(pta_data_dir.rglob("*.xml"))
        if p.name != "__cts__.xml"
        and "pta9999" not in p.parts
        and not _SKIP_PATTERNS.search(p.name)
    ]
    works: list[Work] = []
    for xml_path in tqdm(xml_files, desc="PTA translations"):
        rel = xml_path.relative_to(pta_data_dir)
        out_path = output_dir / SOURCE_ID / rel.with_suffix(".json")
        if out_path.exists() and not force:
            saved = json.loads(out_path.read_text(encoding="utf-8"))
            works.append(Work(**saved["work"]))
            continue
        try:
            root = etree.parse(str(xml_path)).getroot()
        except etree.XMLSyntaxError as exc:
            log.error("XML parse error in %s: %s", xml_path, exc)
            continue
        div = root.find(".//{%s}text/{%s}body/{%s}div[@type='translation']" % (_TEI, _TEI, _TEI))
        if div is None:
            continue
        author_cts = xml_path.parents[1] / "__cts__.xml"
        author_name = _read_author_name(author_cts) if author_cts.exists() else None
        result = _parse_translation(
            xml_path, root, div, author_name, read_work_ids(xml_path.parent / "__cts__.xml"))
        if result is None:
            continue
        work, units = result
        if not units:
            log.error("No text in translation %s — skipping", xml_path)
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps({"work": work.model_dump(), "paragraphs": units},
                       ensure_ascii=False, indent=2),
            encoding="utf-8")
        works.append(work)

    log.info("PTA translations: %d works written", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
