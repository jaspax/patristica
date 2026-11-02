"""
Ingestor for the Patristic Text Archive (PTA).

Source: https://github.com/PatristicTextArchive/pta_data
Format: TEI P5 XML, organised by CTS URN (pta{NNNN}/pta{NNN}/)
License: per file, from the URL in <availability>/<licence @target> (mostly
         CC BY-SA 4.0 or CC BY 4.0; one CC BY-NC-SA 3.0, #366)

Acquisition
-----------
The PTA GitHub zip archive (archive/refs/heads/main.zip) returns 404.
Instead we shallow-clone the repo into ``data/raw/pta/`` using the
git credentials available in the environment.  On ``force=True`` we pull the
latest changes.

File filtering
--------------
We process only "edition" files (``pta-grcN``, ``pta-sycN``, ``pta-latN``,
``pta-xcl1``, ``pta-chu1``, ``pta-eng1``, etc.) and skip:

- ``__cts__.xml``  — CTS catalog metadata (not text)
- ``pta9999/``     — Bible textgroup (already have dedicated scripture ingestors)
- ``*Bibex*``      — biblical-excerpt versions (thin wrappers around scripture)
- ``*.pta-Ms*``    — transcriptions of individual manuscript witnesses (not
                     critical text)
- ``*deu*``        — German translations (not in our language set)

Text
----
Each ``<p>``/``<ab>`` is one unit (``_flatten``): the apparatus readings,
witness details, inline notes and XML comments are kept as ``note`` editorial
spans (#236, #415), a ``<choice>`` keeps one alternative, ``<del>`` is dropped
and ``<lb break="no"/>`` joins a word.

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
from collections.abc import Callable
from pathlib import Path

from lxml import etree
from tqdm import tqdm

from patristica.models import DateConfidence, Language, License, Tradition, Work
from patristica.period import work_in_period
from scripts.ingest._clone import ensure_clone
from scripts.ingest._common import dedupe_refs, slugify_ref
from scripts.ingest._slavonic import glagolitic_to_cyrillic

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
    "chu": "chu",   # Church Slavonic (#335); PTA's one text is pta0001.pta028.pta-chu1
    "cu": "chu",    # ISO 639-1 form, should PTA ever use it
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
    "chu": "slavonic",
    "hbo": None,
}

# Editions named in ``Work.edition`` instead of the bare version id, keyed by
# the CTS version (#335). PTA's Slavonic text is a 16th-century translation
# printed in 1910; its version id alone would not say so.
_EDITIONS: dict[str, str] = {
    "pta0001.pta028.pta-chu1": (
        "Slavonic translation (attributed there to John Chrysostom) in the Velikie "
        "Minei Chetii of Metropolitan Makarii, January, fasc. 15, part 1, days 1–6 "
        "(Moscow: Imperial Archaeographic Commission, 1910), cols. 298–310; "
        "digitised by Daria Coșcodan, PTA pta-chu1"
    ),
}


# File name patterns to skip. ``.pta-Ms…`` are diplomatic transcriptions of
# single manuscript witnesses (``pta-MsA``, ``pta-Ms44``, ``pta-Msb2``): the
# critical edition is the work. The old pattern caught only ``Ms[A-Z]``, so
# 38 transcriptions of Athanasius's Contra gentes and De incarnatione were
# ingested until #415 dropped them (their ids redirect to the editions).
# ``pta-Mss`` is a Slavonic transcription of the Ljubljana leaves of Codex
# Suprasliensis, which the Suprasliensis ingest covers (#333, #335).
_SKIP_PATTERNS = re.compile(r"Bibex|\.pta-Ms|deu")


# How a ``<p>``/``<ab>`` is flattened to text (``_flatten``, #376, #415).
# The apparatus (``<rdg>`` readings next to their ``<lem>``, ``<witDetail>``),
# inline ``<note>``s and the editors' XML comments (``<!--TODO …-->``, Migne
# column references, "sic?") are editorial material (#236): kept and marked
# ``note``, so readers see them and translation and embedding get the lemma
# text. In the Greek Vita Cononis the readings are the Slavonic witness's
# (``<rdg wit="#s">паулъ</rdg>``, #376).
_APPARATUS_TAGS = frozenset({"rdg", "witDetail", "note"})
# ``<choice>`` holds alternative encodings of one point of the text (an
# abbreviation and its expansion, an error and its correction): one is kept, in
# this order of preference, else its first child. The diplomatic manuscript
# transcriptions (``pta-Ms*``) write every nomen sacrum as one.
_CHOICE_PREFERENCE = ("expan", "corr", "reg")
# Deleted text (``<del>``: words an editor athetizes, or letters a scribe struck
# out, usually in a ``<subst>`` with the ``<add>`` that replaced them) is not
# the text of the edition or witness. It is marked ``note`` like the apparatus,
# but without spaces around it, and a deletion inside a word (letters on both
# sides) is dropped instead: removing a span leaves a space in the source
# text (``editorial.strip``), which would split the word.
_DELETION_TAGS = frozenset({"del"})
# Containers whose whitespace-only text between children is layout (the
# transcriptions are pretty-printed: ``<subst>⏎  <del>ἀ</del>⏎  <add>ε</add>``).
_LAYOUT_TAGS = frozenset({"subst", "app", "choice"})


# Creative Commons licence URL: terms, version and an optional jurisdiction
# port (``by-nc/3.0/de/``); a ``deed.de`` suffix is only the deed's language.
_CC_URL_RE = re.compile(r"creativecommons\.org/licenses/([a-z-]+)/(\d\.\d)/?([a-z]{2}(?=/|$))?")
# The CC licences the corpus can record (unported/international only).
_CC_LICENSES: dict[tuple[str, str], License] = {
    ("by", "4.0"): "cc-by-4.0",
    ("by-sa", "4.0"): "cc-by-sa-4.0",
    ("by-nc", "4.0"): "cc-by-nc-4.0",
    ("by-nc-sa", "4.0"): "cc-by-nc-sa-4.0",
    ("by-sa", "3.0"): "cc-by-sa-3.0",
    ("by-nc-sa", "3.0"): "cc-by-nc-sa-3.0",
}


def _licence_target(root: etree._Element) -> str:
    """The ``@target`` of a PTA file's ``<availability>/<licence>``, or ""."""
    lic = root.find(".//{%s}availability/{%s}licence" % (_TEI, _TEI))
    return (lic.get("target") or "").strip() if lic is not None else ""


def _license_from_target(root: etree._Element) -> License | None:
    """Licence of a PTA file from ``<licence @target>`` (the prose varies, #366),
    or None when the target is missing or names a licence we can't record (a
    jurisdiction port such as ``by-nc/3.0/de``). Shared with ``pta_eng``."""
    target = _licence_target(root)
    if "creativecommons.org/publicdomain/" in target:
        return "public_domain"
    m = _CC_URL_RE.search(target)
    if m is None or m.group(3):
        return None
    return _CC_LICENSES.get((m.group(1), m.group(2)))


def _license_from_prose(avail_el: etree._Element | None) -> License:
    """Fallback for a file without ``@target``: the licence from the prose."""
    text = ""
    if avail_el is not None:
        lic_el = avail_el.find(f"{{{_TEI}}}licence")
        text = " ".join((lic_el if lic_el is not None else avail_el).itertext()).lower()
    if re.search(r"by-sa|sharealike|share alike", text):
        return "cc-by-sa-4.0"
    return "cc-by-4.0"  # PTA default


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


def _flatten(el: etree._Element) -> tuple[str, list[list[int | str]]]:
    """An element's text, whitespace collapsed, with its apparatus marked.

    The text of every descendant is kept, except that ``<rdg>``,
    ``<witDetail>`` and ``<note>`` elements and comments become ``note``
    spans ``[start, end, "note"]`` (#236, #415), set off from the text around
    them by a space (a space between two pieces of apparatus belongs to the
    span, so adjacent readings make one span); ``<del>`` is marked the same
    way without the spaces, or dropped inside a word (``_DELETION_TAGS``); a
    ``<choice>`` keeps one of its alternatives (``_CHOICE_PREFERENCE``); and
    ``<lb break="no"/>`` joins the two halves of a word across the whitespace
    around it.
    """
    # Per character: False (text), True (apparatus) or "del" (deleted text).
    chars: list[tuple[str, bool | str]] = []
    join = False  # after <lb break="no"/>: drop leading whitespace

    def add(text: str | None, editorial: bool | str) -> None:
        nonlocal join
        if not text:
            return
        if join:
            text = text.lstrip()
            if not text:
                return
            join = False
        chars.extend((c, editorial) for c in text)

    def boundary() -> None:
        # Apparatus stays apart from the text and from other apparatus.
        if chars and not chars[-1][0].isspace():
            chars.append((" ", False))

    def apparatus(emit: Callable[[], None]) -> None:
        # Set off by spaces only if it has text: an empty reading that marks
        # where a witness starts (``<rdg><witStart/></rdg>``) leaves no trace.
        mark = len(chars)
        boundary()
        emit()
        if all(c.isspace() for c, _ in chars[mark:]):
            del chars[mark:]
        else:
            boundary()

    def walk(node: etree._Element, editorial: bool | str) -> None:
        nonlocal join
        layout = etree.QName(node).localname in _LAYOUT_TAGS

        def text_of(t: str | None) -> str | None:
            return None if layout and t is not None and not t.strip() else t

        add(text_of(node.text), editorial)
        for child in node:
            if child.tag is etree.Comment:
                apparatus(lambda: add(child.text, True))
            elif isinstance(child.tag, str):
                name = etree.QName(child).localname
                if name in _APPARATUS_TAGS:
                    apparatus(lambda: walk(child, True))
                elif name == "choice":
                    options = [c for c in child if isinstance(c.tag, str)]
                    kept = next((c for n in _CHOICE_PREFERENCE for c in options
                                 if etree.QName(c).localname == n),
                                options[0] if options else None)
                    if kept is not None:
                        walk(kept, editorial)
                elif name == "lb" and child.get("break") == "no":
                    while chars and chars[-1][0].isspace():
                        chars.pop()
                    join = True
                elif name in _DELETION_TAGS:
                    walk(child, editorial or "del")
                else:
                    walk(child, editorial)
            add(text_of(child.tail), editorial)

    walk(el, False)
    # A deletion inside a word goes; every other one is marked.
    i = 0
    while i < len(chars):
        if chars[i][1] != "del":
            i += 1
            continue
        j = i
        while j < len(chars) and chars[j][1] == "del":
            j += 1
        if 0 < i and j < len(chars) and not chars[i - 1][0].isspace() \
                and not chars[j][0].isspace():
            del chars[i:j]
        else:
            chars[i:j] = [(c, True) for c, _ in chars[i:j]]
            i = j
    # Collapse whitespace; a kept space is editorial only between two
    # editorial characters.
    kept: list[tuple[str, bool | str]] = []
    for i, (c, ed) in enumerate(chars):
        if not c.isspace():
            kept.append((c, ed))
            continue
        if not kept or kept[-1][0] == " ":
            continue
        nxt = next((e for ch, e in chars[i + 1:] if not ch.isspace()), None)
        kept.append((" ", kept[-1][1] and bool(nxt)))
    while kept and kept[-1][0] == " ":
        kept.pop()
    text = "".join(c for c, _ in kept)
    spans: list[list[int | str]] = []
    for i, (_, ed) in enumerate(kept):
        if ed and spans and spans[-1][1] == i:
            spans[-1][1] = i + 1
        elif ed:
            spans.append([i, i + 1, "note"])
    return text, spans


def _convert(text: str, spans: list[list[int | str]],
             fn: Callable[[str], str]) -> tuple[str, list[list[int | str]]]:
    """Apply *fn* to *text* piece by piece, moving *spans* with it.

    For a conversion that may change the length (``glagolitic_to_cyrillic``
    turns yer + i into ꙑ): each stretch between span boundaries is converted
    on its own.
    """
    if not spans:
        return fn(text), spans
    cuts = sorted({0, len(text), *(int(b) for s in spans for b in s[:2])})
    new_pos: dict[int, int] = {0: 0}
    out = ""
    for a, b in zip(cuts, cuts[1:]):
        out += fn(text[a:b])
        new_pos[b] = len(out)
    return out, [[new_pos[int(s)], new_pos[int(e)], k] for s, e, k in spans]


def _extract_paragraphs(
    body_div: etree._Element,
    work_cts_id: str,
    ns: dict[str, str],
) -> list[dict]:
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
    List of ``{"ref": "...", "text": "..."}`` dicts, with ``"editorial"``
    spans on a paragraph with apparatus (``_flatten``).
    """
    records: list[dict[str, str]] = []

    def _walk(element: etree._Element, path_parts: list[str]) -> None:
        tag = etree.QName(element.tag).localname if element.tag != etree.Comment else ""

        if tag in ("p", "ab"):
            text, spans = _flatten(element)
            if text:
                ref = slugify_ref(".".join([work_cts_id] + path_parts))
                record: dict = {"ref": ref, "text": text}
                if spans:
                    record["editorial"] = spans
                records.append(record)
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

    # --- License: the URL in <licence @target> first, the prose only without one (#366) ---
    license_val = _license_from_target(root)
    if license_val is None:
        target = _licence_target(root)
        if target:
            log.error("Licence %s of %s is not one we can record — skipping", target, xml_path)
            return None
        avail_el = root.find(
            ".//tei:teiHeader/tei:fileDesc/tei:publicationStmt/tei:availability", ns)
        license_val = _license_from_prose(avail_el)

    # --- Author ---
    author_el = root.find(".//tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author/tei:persName", ns)
    if author_el is None:
        author_el = root.find(".//tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author", ns)
    author_from_file = (author_el.text or "").strip() if author_el is not None else None
    author = author_name or author_from_file

    # --- Edition note ---
    edition_note = _EDITIONS.get(f"{work_cts_id}.{version}") or version or None

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
    if language == "chu":
        for p in paragraphs:
            p["text"], spans = _convert(p["text"], p.get("editorial", []),
                                        glagolitic_to_cyrillic)
            if spans:
                p["editorial"] = spans
    n_spans = sum(len(p.get("editorial", ())) for p in paragraphs)
    if n_spans:
        log.debug("%s: apparatus, notes and comments marked as editorial notes "
                  "(%d spans in %d paragraphs; #415)", work_id, n_spans,
                  sum(1 for p in paragraphs if p.get("editorial")))
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
