"""
Ingestor for the Patristic Text Archive (PTA).

Source: https://github.com/PatristicTextArchive/pta_data
Format: TEI P5 XML, organised by CTS URN (pta{NNNN}/pta{NNN}/)
License: CC-BY / CC-BY-SA per file (stated in <availability>)

Acquisition
-----------
The PTA GitHub zip archive (archive/refs/heads/main.zip) returns 404.
Instead we shallow-clone the repo into ``data/raw/pta/`` using the
git credentials available in the environment.  On ``force=True`` we pull the
latest changes.

File filtering
--------------
We process only "edition" files (``pta-grcN``, ``pta-sycN``, ``pta-latN``,
``pta-xcl1``, ``pta-eng1``, etc.) and skip:

- ``__cts__.xml``  — CTS catalog metadata (not text)
- ``pta9999/``     — Bible textgroup (already have dedicated scripture ingestors)
- ``*Bibex*``      — biblical-excerpt versions (thin wrappers around scripture)
- ``*Ms*``         — individual manuscript witnesses (not critical text)
- ``*deu*``        — German translations (not in our language set)

English translations (#345)
---------------------------
A file whose text is a ``<div type="translation">`` rather than an edition
is a modern translation. The English ones become English works with
``translation_of`` set to the work id of the edition they render, named by
the div's ``@corresp``. When that edition is not in the corpus (a Church
Slavonic intermediary, a witness outside the collection period), the
translation is linked to the original named in :data:`_ORIGINAL_FALLBACK`, and
its ``edition`` says which version it was made from; without a fallback it is
skipped. Translations into other languages are still skipped (#367).

A translator's material is marked as editorial (#236), not dropped: headings
(``<head>``) become units of their own, wholly ``title``/``heading``; notes
(``<note>``, ``type="commentary"``) are kept in square brackets as ``note``
spans, as are manuscript variants written into the text ("(P: judgement)"); words the translator or editor supplied for the sense (``<note
type="explanation">``, ``<supplied>``) stay in the text as ``supplement``
spans. A heading's ref is its div's ref, so the div's paragraphs are numbered
below it (``….3.1.3`` heading, ``….3.1.3.1`` paragraph).

Canonical references
--------------------
Each work's ``canonical_ref`` uses the PTA CTS work ID plus the ``@n``
attributes of every enclosing ``<div type="textpart">`` and a per-paragraph
counter::

    pta0001.pta001.1.3   # author_id.work_id.section_n.paragraph_n

The ``work_id`` in the ``Work`` model follows our slug convention::

    pta/pta0001/pta001   # pta/{author_id}/{work_id_without_author}
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from lxml import etree
from tqdm import tqdm

from patristica.models import DateConfidence, Language, License, Tradition, Work
from patristica.period import work_in_period
from scripts.ingest._clone import ensure_clone
from scripts.ingest._common import dedupe_refs, slugify_ref

log = logging.getLogger(__name__)

SOURCE_ID = "pta"

_REPO_URL = "https://github.com/PatristicTextArchive/pta_data.git"

# TEI namespace
_TEI = "http://www.tei-c.org/ns/1.0"
_CTS_NS = "http://chs.harvard.edu/xmlns/cts"

# Language code mapping: PTA lang tag → ISO 639-3 used in our models
_LANG_MAP: dict[str, Language] = {
    "grc": "grc",
    "lat": "lat",
    "syc": "syc",
    "xcl": "hye",   # Classical Armenian → hye
    "cop": "cop",
    "gez": "gez",
    "eng": "eng",
    "got": "got",
}

# Language → Tradition
_LANG_TRADITION: dict[Language, Tradition | None] = {
    "grc": "greek",
    "lat": "latin",
    "syc": "syriac",
    "hye": "armenian",
    "cop": "coptic",
    "gez": "ethiopic",
    "eng": None,
    "got": "gothic",
    "hbo": None,
}


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

# File name patterns to skip
_SKIP_PATTERNS = re.compile(r"Bibex|MsA|MsB|MsC|MsD|MsE|MsF|MsG|MsH|MsI|MsJ|MsK|MsL|MsM|MsN|MsO|MsP|MsQ|MsR|MsS|MsT|MsU|MsV|MsW|MsX|MsY|MsZ|Ms[A-Z]|deu")


def _ensure_repo(repo_dir: Path, force: bool) -> None:
    """Clone the repo if absent; pull latest on force (not offline, #215). Its git
    dir lives in ``_gitdirs/`` so the tree can be tracked (#244)."""
    ensure_clone(_REPO_URL, repo_dir, "PTA", force)


def _read_author_name(cts_path: Path) -> str | None:
    """Extract the English author name from a ``__cts__.xml`` file."""
    try:
        tree = etree.parse(str(cts_path))
        root = tree.getroot()
        ns = {"ti": _CTS_NS}
        for el in root.findall(".//ti:groupname", ns):
            if el.get("{http://www.w3.org/XML/1998/namespace}lang") == "eng":
                return (el.text or "").strip() or None
        # Fallback: first groupname
        el = root.find(".//ti:groupname", ns)
        if el is not None:
            return (el.text or "").strip() or None
    except Exception as exc:
        log.debug("Could not read %s: %s", cts_path, exc)
    return None


_DC_NS = "http://purl.org/dc/elements/1.1/"


def read_work_ids(cts_path: Path) -> list[str]:
    """Catalogue identifiers of a PTA work, from its ``__cts__.xml`` (#178).

    PTA records ``<dc:identifier>KIND:value</dc:identifier>`` per work (TLG,
    CPG, BHG, Pinakes-Oeuvre, Aldama, GND, …).  Returns them as
    ``"KIND:value"`` in catalogue order, without the redundant ``PTA:`` id;
    a value listing several numbers (``CPG:3243; 8596``) becomes one id each.
    """
    if not cts_path.exists():
        return []
    root = etree.parse(str(cts_path)).getroot()
    ids: list[str] = []
    for el in root.iter(f"{{{_DC_NS}}}identifier"):
        kind, sep, value = (el.text or "").strip().partition(":")
        if not sep or not value.strip() or kind == "PTA":
            continue
        for part in re.split(r"\s*[;,]\s*", value.strip()):
            ident = f"{kind}:{part}"
            if part and ident not in ids:
                ids.append(ident)
    return ids


def _extract_dates(root: etree._Element) -> tuple[int | None, tuple[int, int] | None, DateConfidence]:
    """Extract composition date info from teiHeader/profileDesc/creation/date."""
    ns = {"tei": _TEI}
    date_el = root.find(".//tei:profileDesc/tei:creation/tei:date", ns)
    if date_el is None:
        return None, None, "uncertain"

    when = date_el.get("when") or date_el.get("notBefore") or date_el.get("notAfter")

    not_before_s = date_el.get("notBefore") or date_el.get("when")
    not_after_s = date_el.get("notAfter") or date_el.get("when")

    def _parse_year(s: str | None) -> int | None:
        if not s:
            return None
        m = re.search(r"-?(\d{3,4})", s)
        if m:
            year = int(m.group(1))
            return -year if s.startswith("-") else year
        return None

    y_before = _parse_year(not_before_s)
    y_after = _parse_year(not_after_s)

    if y_before is None and y_after is None:
        return None, None, "uncertain"

    if y_before == y_after:
        return y_before, None, "established"

    date_range: tuple[int, int] | None = None
    date_composed: int | None = None
    if y_before is not None and y_after is not None:
        date_range = (y_before, y_after)
        date_composed = (y_before + y_after) // 2
    elif y_before is not None:
        date_composed = y_before
    elif y_after is not None:
        date_composed = y_after

    return date_composed, date_range, "approximate"


def _element_inner_text(el: etree._Element) -> str:
    """Collect all text inside an element, stripping child element tags but keeping their text."""
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        parts.append(_element_inner_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _extract_paragraphs(
    body_div: etree._Element,
    work_cts_id: str,
    ns: dict[str, str],
) -> list[dict[str, str]]:
    """Recursively extract paragraphs from a TEI body div.

    Traverses ``<div type="textpart">`` elements, building a dotted path from
    their ``@n`` attributes.  ``<p>`` and ``<ab>`` elements become individual
    paragraph records.

    Parameters
    ----------
    body_div:    The ``<div type="edition">`` element.
    work_cts_id: E.g. ``"pta0001.pta001"`` — prepended to all refs.
    ns:          Namespace map.

    Returns
    -------
    List of ``{"ref": "...", "text": "..."}`` dicts.
    """
    records: list[dict[str, str]] = []

    def _walk(element: etree._Element, path_parts: list[str]) -> None:
        tag = etree.QName(element.tag).localname if element.tag != etree.Comment else ""

        if tag in ("p", "ab"):
            text = _element_inner_text(element).strip()
            # Collapse whitespace
            text = re.sub(r"\s+", " ", text)
            if text:
                ref = slugify_ref(".".join([work_cts_id] + path_parts))
                records.append({"ref": ref, "text": text})
            return

        if tag == "div" and element.get("type") == "textpart":
            n = element.get("n", "")
            # Skip non-numeric n values like "Index" or "Titulus" (front matter)
            new_parts = path_parts + [n] if n and re.match(r"^[\w\-]+$", n) else path_parts
            for child in element:
                _walk(child, new_parts)
            return

        # For other elements (head, note, pb, etc.) recurse without adding to path
        if tag not in ("head", "note", "pb", "lb", "cb", "fw", "figure", "table"):
            for child in element:
                _walk(child, path_parts)

    for child in body_div:
        _walk(child, [])

    return dedupe_refs(records)


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


def _license_from_target(root: etree._Element) -> License | None:
    """Licence of a PTA file from ``<licence @target>`` (the prose varies, #366)."""
    lic = root.find(".//{%s}availability/{%s}licence" % (_TEI, _TEI))
    target = (lic.get("target") or "") if lic is not None else ""
    for pattern, value in (("/by-nc-sa/4.0", "cc-by-nc-sa-4.0"), ("/by-sa/4.0", "cc-by-sa-4.0"),
                           ("/by-nc/4.0", "cc-by-nc-4.0"), ("/by/4.0", "cc-by-4.0"),
                           ("/publicdomain/", "public_domain")):
        if pattern in target:
            return value  # type: ignore[return-value]
    return None


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
    original_lang = _LANG_NAMES.get(_edition_language(work_dir / f"{work_cts_id}.{original_version}.xml") or "", "")
    edition = f"{version}: English translation{by} ({published}) of the {original_lang} text {original_version}".replace("  ", " ")
    if source_version and source_version != original_version:
        source_lang = _LANG_NAMES.get(_edition_language(source_path) or "", "")
        edition += f", made from the {source_lang} version {source_version}".replace("  ", " ")

    # The original's composition date (a translation's header may give a wider
    # range than its original's: 30–1500 against 30–800). The original is in
    # the corpus, so it is in period.
    original_root = etree.parse(str(work_dir / f"{work_cts_id}.{original_version}.xml")).getroot()
    date_composed, date_range, date_confidence = _extract_dates(original_root)

    work = Work(
        work_id=f"pta/{author_id}/{work_id_short}/{version}",
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


def _parse_pta_file(
    xml_path: Path,
    author_name: str | None,
    external_ids: list[str] | None = None,
) -> tuple[Work, list[dict[str, str]]] | None:
    """Parse a single PTA TEI file.

    Returns ``(Work, paragraphs)`` or ``None`` if the file should be skipped.
    """
    try:
        tree = etree.parse(str(xml_path))
    except etree.XMLSyntaxError as exc:
        log.warning("XML parse error in %s: %s", xml_path, exc)
        return None

    root = tree.getroot()
    ns = {"tei": _TEI}

    # --- Title ---
    title_el = root.find(".//tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", ns)
    title = (title_el.text or "").strip() if title_el is not None else xml_path.stem

    # --- Edition div → language ---
    edition_div = root.find(".//tei:text/tei:body/tei:div[@type='edition']", ns)
    if edition_div is None:
        translation_div = root.find(".//tei:text/tei:body/tei:div[@type='translation']", ns)
        if translation_div is not None:
            return _parse_translation(xml_path, root, translation_div, author_name, external_ids)
        log.debug("No edition div in %s — skipping", xml_path)
        return None

    xml_lang = edition_div.get("{http://www.w3.org/XML/1998/namespace}lang", "")
    language = _LANG_MAP.get(xml_lang)
    if language is None:
        log.debug("Unsupported language %r in %s — skipping", xml_lang, xml_path)
        return None

    tradition = _LANG_TRADITION.get(language)

    # --- CTS URN → work identifiers ---
    cts_urn = edition_div.get("n", "")
    # e.g. "urn:cts:pta:pta0001.pta001.pta-grc1"
    cts_parts = cts_urn.rsplit(":", 1)[-1].split(".")
    # cts_parts = ["pta0001", "pta001", "pta-grc1"]
    if len(cts_parts) >= 2:
        author_id = cts_parts[0]   # "pta0001"
        work_id_short = cts_parts[1]  # "pta001"
        version = cts_parts[2] if len(cts_parts) > 2 else ""  # "pta-grc1"
    else:
        # Fallback: derive from file path
        author_id = xml_path.parts[-3]  # e.g. "pta0001"
        work_id_short = xml_path.parts[-2]  # e.g. "pta001"
        version = ""

    work_cts_id = f"{author_id}.{work_id_short}"  # "pta0001.pta001"
    work_id = f"pta/{author_id}/{work_id_short}"
    if version:
        work_id = f"{work_id}/{version}"

    # --- Dates ---
    date_composed, date_range, date_confidence = _extract_dates(root)

    # Skip only on positive evidence of composition after the collection period
    if not work_in_period(date_range):
        log.debug("Skipping work after the collection period %s (date_range=%s)",
                  work_cts_id, date_range)
        return None

    # --- License ---
    avail_el = root.find(".//tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability", ns)
    avail_text = ""
    if avail_el is not None:
        # Try to get text from <licence> child
        lic_el = avail_el.find("tei:licence", ns)
        if lic_el is not None:
            avail_text = (lic_el.text or "").lower()
        else:
            avail_text = (avail_el.text or "").lower()
    if "cc-by-sa" in avail_text or "by-sa" in avail_text:
        license_val: License = "cc-by-sa-4.0"
    elif "cc-by" in avail_text or "by 4.0" in avail_text:
        license_val = "cc-by-4.0"
    else:
        license_val = "cc-by-4.0"  # PTA default

    # --- Author ---
    author_el = root.find(".//tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author/tei:persName", ns)
    if author_el is None:
        author_el = root.find(".//tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author", ns)
    author_from_file = (author_el.text or "").strip() if author_el is not None else None
    author = author_name or author_from_file

    # --- Edition note ---
    edition_note = version or None

    work = Work(
        work_id=work_id,
        source_id=SOURCE_ID,
        author=author,
        title=title,
        date_composed=date_composed,
        date_range=date_range,
        date_confidence=date_confidence,
        genre="patristic",
        language=language,
        tradition=tradition,
        license=license_val,
        provenance_url=f"https://github.com/PatristicTextArchive/pta_data/blob/main/data/{author_id}/{work_id_short}/{xml_path.name}",
        edition=edition_note,
        translation_of=None,
        external_ids=external_ids or [],
    )

    paragraphs = _extract_paragraphs(edition_div, work_cts_id, ns)
    return work, paragraphs


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Clone/pull the PTA repo and ingest all text editions.

    Parameters
    ----------
    output_dir: Root raw output directory (``data/raw``).
    force:      If True, pull latest git changes before processing.

    Returns
    -------
    List of ``Work`` records written.
    """
    repo_dir = output_dir / "pta"
    _ensure_repo(repo_dir, force)

    pta_data_dir = repo_dir / "data"
    if not pta_data_dir.exists():
        raise FileNotFoundError(f"Expected PTA data directory at {pta_data_dir}")

    # Collect all XML files to process
    xml_files = [
        p for p in sorted(pta_data_dir.rglob("*.xml"))
        if p.name != "__cts__.xml"
        and "pta9999" not in p.parts  # skip Bible group
        and not _SKIP_PATTERNS.search(p.name)
    ]

    log.info("Found %d PTA text files to process", len(xml_files))

    works: list[Work] = []
    skipped = 0

    for xml_path in tqdm(xml_files, desc="PTA ingest"):
        # Derive output path: data/raw/pta/{author_id}/{work_id}/{file}.json
        # Use relative path within pta_data_dir
        rel = xml_path.relative_to(pta_data_dir)  # e.g. pta0001/pta001/pta0001.pta001.pta-grc1.xml
        out_path = output_dir / "pta" / rel.with_suffix(".json")

        work_ids = read_work_ids(xml_path.parent / "__cts__.xml")
        if out_path.exists() and not force:
            # Still need to return the work metadata; read it from the saved file
            import json
            try:
                saved = json.loads(out_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                log.warning("Unreadable %s (%s); re-run with --force", out_path, exc)
                continue
            if saved["work"].get("external_ids", []) != work_ids:
                # Catalogue ids are metadata only: refresh them in place, no re-parse.
                saved["work"]["external_ids"] = work_ids
                out_path.write_text(
                    json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
            works.append(Work(**saved["work"]))
            continue

        # Read author name from __cts__.xml in the author directory
        author_cts = xml_path.parents[1] / "__cts__.xml"
        author_name = _read_author_name(author_cts) if author_cts.exists() else None

        result = _parse_pta_file(xml_path, author_name, work_ids)
        if result is None:
            skipped += 1
            continue

        work, paragraphs = result

        if not paragraphs:
            log.debug("No paragraphs extracted from %s — skipping", xml_path)
            skipped += 1
            continue

        out_path.parent.mkdir(parents=True, exist_ok=True)
        import json
        payload = {"work": work.model_dump(), "paragraphs": paragraphs}
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        works.append(work)

    log.info(
        "PTA ingestion complete: %d works written, %d skipped",
        len(works),
        skipped,
    )
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
