"""
Shared utilities for CCEL ANF/NPNF ingestion.

CCEL (Christian Classics Ethereal Library) hosts the Ante-Nicene Fathers and
Nicene & Post-Nicene Fathers translation series in ThML format — an XML-based
theological markup language.

ThML structure overview
-----------------------
- ``<ThML.body>`` (or ``<body>``) — top-level text container
- ``<div1 type="Book">`` — typically one treatise or author section per volume
- ``<div2 type="Chapter">`` / ``<div3 type="Section">`` — hierarchy within a work
- ``<head>`` — section title (first child of each div)
- ``<p>`` — text paragraphs
- ``<scripRef>`` — inline Scripture citation (strip element, keep surrounding text)
- ``<note>`` / ``<pb>`` — footnotes / page breaks (discard entirely)

Each volume XML file contains multiple works separated by ``<div1>`` boundaries.
One Work record is produced per ``<div1>``.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from lxml import etree
from tqdm import tqdm

from patristica.models import DateConfidence, License, Tradition, Work
from scripts.ingest._common import download_file, slugify_ref
from scripts.ingest._patristic_meta import AUTHORS, AuthorMeta

log = logging.getLogger(__name__)

_CCEL_BASE_URL = "https://ccel.org/ccel/s/schaff"

# ThML elements to skip entirely (discard text content and children)
_SKIP_LOCAL_NAMES = frozenset({
    "note", "pb", "lb", "cb", "fw", "figure", "table",
    "speaker", "stage", "milestone", "bibl", "index",
    "teiHeader", "header",
})

# ThML elements whose tags should be stripped but whose text content is kept
_INLINE_LOCAL_NAMES = frozenset({
    "scripRef", "scripture", "a", "abbr", "span", "i", "b", "em", "strong",
    "hi", "term", "name", "persName", "placeName", "q", "foreign", "title",
    "author", "publisher", "date",
})


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

def download_volume(volume_id: str, cache_dir: Path, force: bool = False) -> Path:
    """Download a CCEL ThML XML file, using ETag caching.

    Parameters
    ----------
    volume_id:  Volume identifier, e.g. ``"anf01"`` or ``"npnf101"``.
    cache_dir:  Directory to cache downloaded files.
    force:      Re-download even if the file already exists.

    Returns
    -------
    Path to the downloaded XML file.
    """
    url = f"{_CCEL_BASE_URL}/{volume_id}.xml"
    dest = cache_dir / f"{volume_id}.xml"
    if dest.exists() and not force:
        # No ETag revalidation: ccel.org answers 200 rather than 304, which
        # would rewrite the shared cache (and hit the network) on every run.
        return dest
    return download_file(url, dest, force=force)


# ---------------------------------------------------------------------------
# Text extraction helpers
# ---------------------------------------------------------------------------

def _element_inner_text(el: etree._Element) -> str:
    """Extract text from a ThML element, stripping markup but keeping prose.

    Elements in ``_SKIP_LOCAL_NAMES`` are discarded entirely.
    Elements in ``_INLINE_LOCAL_NAMES`` (and all others) have their tags
    stripped but text content retained.
    """
    parts: list[str] = []

    def _collect(node: etree._Element) -> None:
        if node.text:
            parts.append(node.text)
        for child in node:
            if child.tag is etree.Comment:
                if child.tail:
                    parts.append(child.tail)
                continue
            local = etree.QName(child.tag).localname
            if local in _SKIP_LOCAL_NAMES:
                # Discard entirely; keep tail text (belongs to parent)
                if child.tail:
                    parts.append(child.tail)
                continue
            _collect(child)
            if child.tail:
                parts.append(child.tail)

    _collect(el)
    return re.sub(r"\s+", " ", "".join(parts)).strip()


def _get_head_text(div: etree._Element) -> str | None:
    """Return the title text for a ``<div1>`` element.

    Checks heading elements first (``<head>``, ``<h1>``–``<h4>``), then falls
    back to the first non-empty ``<p>`` child.  ANF volumes use ``<h1>``; NPNF
    volumes use ``<p>`` for all headings.
    """
    first_p: str | None = None
    for child in div:
        if child.tag is etree.Comment:
            continue
        local = etree.QName(child.tag).localname
        if local in ("head", "h1", "h2", "h3", "h4"):
            text = _element_inner_text(child).strip()
            return text or None
        if local == "p" and first_p is None:
            text = _element_inner_text(child).strip()
            if text:
                first_p = text
    return first_p


def _get_identification_text(div: etree._Element, max_paras: int = 2) -> str:
    """Return a text blob suitable for author identification.

    Collects only the PRIMARY heading element (``<head>`` or ``<h1>``; not
    ``<h2>``/``<h3>`` sub-headings which often list multiple authors) plus the
    first ``max_paras`` non-empty ``<p>`` children.  This wider context helps
    match authors in NPNF volumes where headings like "St. Aurelius Augustin /
    Bishop of Hippo" are spread across multiple ``<p>`` elements.
    """
    parts: list[str] = []
    p_count = 0
    primary_heading_done = False
    for child in div:
        if child.tag is etree.Comment:
            continue
        local = etree.QName(child.tag).localname
        if local in ("head", "h1") and not primary_heading_done:
            text = _element_inner_text(child).strip()
            if text:
                parts.append(text)
            primary_heading_done = True
        elif local == "p" and p_count < max_paras:
            text = _element_inner_text(child).strip()
            if text:
                parts.append(text)
                p_count += 1
    return " ".join(parts)


def _find_body(root: etree._Element) -> etree._Element | None:
    """Locate the ThML body element, handling namespaced and unnamespaced variants."""
    for el in root.iter():
        if el.tag is etree.Comment:
            continue
        local = etree.QName(el.tag).localname
        # Accept "body" and the ThML-specific "ThML.body"
        if local in ("body", "ThML.body"):
            return el
    return None


# ---------------------------------------------------------------------------
# Author/work identification
# ---------------------------------------------------------------------------

_COMMON_WORDS = frozenset({
    "saint", "st", "blessed", "pseudo", "the", "and", "of", "to",
    "bishop", "pope", "father", "abbot", "monk",
    # Generic name words shared by multiple authors — too ambiguous alone
    "gregory", "john", "peter", "james", "paul", "clement",
    # Generic theological/structural words
    "epistle", "letter", "homily", "sermon", "works",
    # Titles/epithets shared across multiple people
    "martyr",
})

# Titles indicating non-author sections (index, preface, etc.) — skip author matching
_NON_AUTHOR_TITLE_WORDS = frozenset({
    "index", "indexes", "indices", "contents", "preface", "appendix",
    "foreword", "introduction", "dedication", "prolegomena",
    "bibliography", "chronological", "general", "introductory",
    "volume", "select", "library", "fathers", "ancient",
})


def _find_author_meta(head_text: str | None) -> AuthorMeta | None:
    """Try to match the div1 head text to a known author in _patristic_meta.

    Three-pass strategy (most specific first):

    1. Full name is contained in the head text (e.g., "Clement of Rome").
    2. Single-word head text exactly matches a word in the full name
       (e.g., "Polycarp" matches "Polycarp of Smyrna").
    3. Scored word overlap: sum of lengths of significant name words (>4 chars,
       not common prepositions) found in the head text; highest score wins.
       This handles multi-word heads like "Justin Martyr" or "John Chrysostom".
    """
    if not head_text:
        return None
    head_lower = re.sub(r"\s+", " ", head_text.lower().strip())

    # Pass 1: full name substring match
    for meta in AUTHORS.values():
        if meta.full_name.lower() in head_lower:
            return meta

    # Pass 2: single-word head matches a word in the full name
    if " " not in head_lower and len(head_lower) > 3:
        for meta in AUTHORS.values():
            if head_lower in [w.lower() for w in meta.full_name.split()]:
                return meta

    # Pass 3: scored significant-word overlap.
    # Only applied to short texts (≤ 20 words) that look like headings or
    # bylines, not long body text like index entries or prefaces.
    if len(head_lower.split()) > 20:
        return None

    best_score = 0
    best_meta: AuthorMeta | None = None
    for meta in AUTHORS.values():
        score = 0
        for word in meta.full_name.lower().split():
            if word in _COMMON_WORDS or len(word) <= 4:
                continue
            if re.search(r"\b" + re.escape(word) + r"\b", head_lower):
                score += len(word)
        if score > best_score:
            best_score = score
            best_meta = meta
    return best_meta if best_score > 0 else None


def _slugify_title(title: str) -> str:
    """Convert a title to a filesystem-safe slug (max 60 chars)."""
    slug = title.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:60]


# ---------------------------------------------------------------------------
# ThML paragraph extractor
# ---------------------------------------------------------------------------

def _extract_paragraphs_from_div1(
    div1: etree._Element,
    ref_prefix: str,
    skip_ids: frozenset[str] = frozenset(),
) -> list[dict[str, str]]:
    """Extract paragraphs from a ``<div1>`` element with canonical refs.

    Canonical refs follow the pattern::

        {ref_prefix}.{div2_n}.{div3_n}[.counter]

    where ``div2_n`` / ``div3_n`` come from ``@n`` attributes (falling back
    to sequential numbering) and a dot-counter is appended on duplicate refs.

    Parameters
    ----------
    div1:       The ``<div1>`` element to process.
    ref_prefix: Author abbreviation or title slug to prefix all refs.
    skip_ids:   ``@id`` values of nested divs to leave out (see ``EXCLUDED_DIVS``).
                Skipped divs still advance the positional counters, so refs of
                the remaining divs are unchanged.
    """
    records: list[dict[str, str]] = []
    seen: dict[str, int] = {}

    def _unique_ref(parts: list[str]) -> str:
        base = slugify_ref(".".join([ref_prefix] + [p for p in parts if p]))
        if base not in seen:
            seen[base] = 0
            return base
        while True:
            seen[base] += 1
            candidate = f"{base}.{seen[base]}"
            if candidate not in seen:
                seen[candidate] = 0  # reserve so structural paths can't collide
                return candidate

    div2_counter = 0
    div3_counter = 0

    def _walk(el: etree._Element, path: list[str]) -> None:
        nonlocal div2_counter, div3_counter

        if el.tag is etree.Comment:
            return

        local = etree.QName(el.tag).localname

        if local == "p":
            text = _element_inner_text(el)
            if text:
                records.append({"ref": _unique_ref(path), "text": text})
            return

        if local in _SKIP_LOCAL_NAMES or local in ("head", "h1", "h2", "h3", "h4"):
            return

        if local == "div2":
            div3_counter = 0
            n = el.get("n", "")
            n_clean = re.sub(r"[^A-Za-z0-9]", "", n)[:20] if n else ""
            if not n_clean:
                div2_counter += 1
                n_clean = str(div2_counter)
            if el.get("id") in skip_ids:
                return
            new_path = path + [n_clean]
            for child in el:
                _walk(child, new_path)
            return

        if local == "div3":
            n = el.get("n", "")
            n_clean = re.sub(r"[^A-Za-z0-9]", "", n)[:20] if n else ""
            if not n_clean:
                div3_counter += 1
                n_clean = str(div3_counter)
            if el.get("id") in skip_ids:
                return
            new_path = path + [n_clean]
            for child in el:
                _walk(child, new_path)
            return

        if local in ("div4", "div5", "div6"):
            if el.get("id") in skip_ids:
                return
            n = el.get("n", "")
            n_clean = re.sub(r"[^A-Za-z0-9]", "", n)[:20] if n else ""
            new_path = path + [n_clean] if n_clean else path
            for child in el:
                _walk(child, new_path)
            return

        for child in el:
            _walk(child, path)

    for child in div1:
        _walk(child, [])

    return records


# ---------------------------------------------------------------------------
# Excluded divs
# ---------------------------------------------------------------------------

#: ThML ``@id``s, per volume, that the generic series ingestors (ccel_anf,
#: ccel_npnf1, ccel_npnf2) must leave out.  The value says why: the source_id of
#: the dedicated ingestor that owns the text (so it is not in the corpus twice),
#: or ``"non-text: …"`` for editorial matter such as indexes.  An excluded div1
#: produces no Work (its positional work_id is simply unused); an excluded
#: nested div is cut out of its parent div1's Work.
EXCLUDED_DIVS: dict[str, dict[str, str]] = {
    "anf07": {
        "viii.iii": "patristic/didache",
        **{f"ix.{n}": "patristic/apostolic-constitutions"
           for n in ("ii", "iii", "iv", "v", "vi", "vii", "viii", "ix")},
        "xii.ii": "liturgical/syriac-james",
        "xii.iii": "liturgical/mark-liturgy",
        "xii.iv": "liturgical/adai-mari",
    },
    "anf08": {
        # ANF08/009 Memoirs of Edessa — Syriac documents (dedicated ingestors)
        **{d: "patristic/syriac-documents"
           for d in ("ix.iii", "ix.iv", "ix.v", "ix.vi.i", "ix.vii", "ix.viii",
                     "ix.ix", "ix.xi", "ix.xii", "ix.xiii", "ix.xiv",
                     "ix.xvi", "ix.xvii", "ix.xviii")},
        **{d: "non-text: editorial"
           for d in ("ix.i", "ix.ii", "ix.vi.ii", "ix.x", "ix.xv", "ix.xix")},
    },
    "npnf214": {
        **{d: "councils/ecumenical"
           for d in ("vii", "ix", "x", "xi", "xii", "xiii", "xiv", "xvi",
                     "viii.iii", "viii.iv", "viii.v", "viii.vi", "viii.vii",
                     "xv.iii", "xv.iv", "xv.v", "xv.vi")},
    },
}


#: ANF QA pass (Milestone 7).  Kept as separate literals merged into
#: ``EXCLUDED_DIVS`` below so the per-volume blocks above stay untouched.
#: Space-separated ThML ``@id`` lists.
_ANF_WORKS_DIVS: dict[str, str] = {
    "anf01": """
        iii.ii iv.iv v.xiv v.xv v.xvi v.xvii v.xviii v.xix v.xx v.xxi v.xxii v.xxiii
        v.xxv vi.ii vii.ii viii.v viii.vi viii.vii viii.xi ix.ii ix.iii ix.iv ix.vi
        ix.vii ix.viii ii.ii iv.ii v.ii v.iii v.iv v.v v.vi v.vii v.viii v.x v.xi
        v.xii viii.ii viii.iii viii.iv viii.viii viii.ix
    """,
    "anf02": """
        ii.ii ii.iii ii.iv iii.ii iii.iii iv.ii v.ii v.iii vi.ii vi.iii vi.iv vi.v
    """,
    "anf03": """
        iv.iii iv.iv iv.v iv.vi iv.vii iv.viii iv.ix iv.x iv.xi v.iii v.iv v.v v.vi
        v.vii v.viii v.ix v.x v.xi vi.ii vi.iii vi.iv vi.v vi.vi vi.vii
    """,
    "anf04": """
        iii.ii iii.iii iii.iv iii.v iii.vi iii.vii iii.viii iii.ix iii.x iii.xi.i
        iii.xi.ii iii.xi.iii iii.xi.iv iii.xi.v iv.iii v.ii vi.iv vi.v vi.vi vi.vii
        vi.viii vi.ix
    """,
    "anf05": """
        iii.iii iii.iv.i iii.iv.ii iii.v.i iii.v.ii iii.v.iii iii.v.iv iii.v.v
        iv.iii iv.iv iv.v.i iv.v.ii iv.v.iii iv.v.iv iv.v.v iv.v.vi iv.v.vii
        iv.v.viii iv.v.ix iv.v.x iv.v.xi iv.v.xii iv.vi iv.vii.ii iv.vii.iii
        iv.vii.iv iv.vii.v v.iii.i v.iii.ii v.iii.iii vi.iii vi.iv vii.iii.ii
        vii.iv.ii vii.ii
    """,
    "anf06": """
        iii.iii.i iii.iii.ii iii.iii.iii iii.iii.iv iii.iv iv.iii iv.iv v.iii v.iv
        v.v v.vi vi.iii.ii vi.iii.iii vi.iv.ii vi.v.ii vi.vi.ii vi.vi.iii vi.vii.ii
        vi.viii.ii vi.viii.iii vi.ix.ii vi.x.ii vi.x.iii vi.x.iv vi.x.v vii.iii
        vii.iv viii.iii ix.iii ix.iv ix.vi x.iii xi.iii xi.iv xi.v xi.vi xi.x xi.xi
        xi.xii xi.viii xi.ix xii.iii
    """,
    "anf07": """
        iv.i v.ii vi.i vi.ii vii.ii x.iii xi iii.ii iii.iii iii.iv iii.v iii.vi
    """,
    "anf08": """
        iii.iii iii.iv iii.v iii.vi iii.vii iii.viii iii.ix iii.x iii.xi iii.xii
        iii.xiii iii.xiv iv.iii v.iii v.iv vi.iii vi.iv vii.iv vii.v vii.vi vii.vii
        vii.viii vii.ix vii.x vii.xi vii.xii vii.xiii vii.xiv vii.xv vii.xvi
        vii.xvii vii.xviii vii.xix vii.xx vii.xxi vii.xxii vii.xxiii vii.xxiv
        vii.xxv vii.xxvi vii.xxvii vii.xxviii vii.xxix vii.xxx vii.xxxi vii.xxxii
        vii.xxxiii vii.xxxiv vii.xxxv vii.xxxvi vii.xxxvii vii.xxxviii vii.xxxix
        vii.xl vii.xli vii.xlii vii.xliii vii.xliv viii.iii viii.iv viii.v viii.vi
        viii.vii viii.viii viii.ix x.iii x.iv x.v.ii x.v.iii x.v.iv x.v.v x.v.vi
        x.v.vii x.v.viii x.v.ix x.v.x x.v.xi x.v.xii x.v.xiii x.v.xiv x.v.xv x.v.xvi
        x.vi.ii x.vii x.viii x.ix x.x x.xi x.xii x.xiii x.xiv x.xv x.xvi
    """,
    "anf09": """
        iii.ii v.ii v.iii vi.ii vii.ii viii.ii ix.iii x.ii xi.ii xii.iv xii.vi
        xiii.iii xiii.iv xiv.iii xv.ii xv.iii xvi.ii iv.iii
    """,
}
_ANF_NON_TEXT: dict[str, dict[str, str]] = {
    # Title-page div1s (printed title, editors, imprint) and nested
    # "Title Page." div2s that only repeat the author's name.
    "title page": {
        "anf02": "i",
        "anf03": "i ii iv.i v.i vi.i",
        "anf04": "i iii.i iv.i v.i vi.i",
        "anf05": "i iii.i iv.i v.i vi.i vii.i",
        "anf06": "i iii.i iv.i v.i vi.i vii.i viii.i ix.i x.i xi.i xii.i",
        "anf07": "i",
        "anf08": "i iii.i iv.i v.i vi.i vii.i viii.i x.i",
        "anf09": "i iii iv v xv xvi ix.i xii.i xiii.i xiv.i",  # iii–xvi: div1-level title lines
    },
    # Subject / Scripture / page indexes.
    "index": {
        "anf02": "vii viii", "anf03": "vii", "anf04": "vii", "anf05": "viii",
        "anf06": "xiii", "anf07": "xiii", "anf08": "xi", "anf09": "xvii",
        "anf10": "x",
    },
    # ANF10 (Bibliographic Synopsis; General Index) is page images only.
    "page images only (ANF10 front matter, synopsis and indexes)": {
        "anf10": "i ii iii iv v vi vii viii ix",
    },
    # Parallel table of the four canonical Gospels' Passion narratives.
    "editorial synoptic table (canonical Gospel text)": {"anf09": "iii.iii"},
    # Scribal colophons of the Arabic Diatessaron manuscripts.
    "manuscript colophons": {"anf09": "iv.iv"},
    # The 1885–97 editors' and translators' apparatus: volume prefaces,
    # introductory notices, elucidations, "Note by the American Editor",
    # translator's biographical notices.  (Nested ones inside divs taken by
    # anf_works are also dropped there by title.)
    "editorial": {
            "anf01": "i.i i.ii ii.i iii.i iv.i iv.iii v.i v.ix v.xiii v.xxiv vi.i vii.i viii.i viii.x ix.i ix.v",
            "anf02": "ii.i ii.v iii.i iv.i v.i vi.i vi.iii.iv vi.iv.i.xxx vi.iv.ii.xxiv vi.iv.iii.i vi.iv.iv.xxii vi.iv.v.xv vi.iv.vi.xix vi.iv.vii.xix vi.iv.viii.x vi.v.i",
            "anf03": "iii iv.ii v.ii",
            "anf04": "ii iii.xi.vi iii.xi.vii iv.ii vi.ii vi.iii",
            "anf05": "ii iii.ii iii.v.vi iv.ii iv.v.xiii iv.vii.i iv.vii.vi v.ii v.iii.iv vi.ii vii.iii.i vii.iv.i vii.iv.iii",
            "anf06": "ii iii.ii iv.ii iv.v v.ii v.vii vi.ii vi.iii.i vi.iv.i vi.iv.iii vi.v.i vi.vi.i vi.vii.i vi.viii.i vi.ix.i vi.x.i vi.x.vi vii.ii vii.v vii.vi viii.ii viii.iv ix.ii ix.v ix.vii x.ii x.iv xi.ii xi.vii xi.xiii xii.ii",
            "anf07": "ii iii.i iii.ii.viii.lxx iii.iv.xxi iii.v.liii iii.vi.iii v.i vii.i viii.i viii.ii ix.i x.i x.ii xii.i xii.v",
            "anf08": "ii iii.ii iii.xv iv.ii v.ii vi.ii vii.ii vii.iii viii.ii viii.x x.ii x.v.i x.vi.i x.xvii x.xviii x.xix",
            "anf09": "ii iii.i iv.i iv.ii v.i vi.i vii.i viii.i ix.ii x.i xi.i xii.ii xii.iii xii.v xiii.ii xiv.ii xv.i xvi.i",
    },
}
for _vol, _ids in _ANF_WORKS_DIVS.items():
    EXCLUDED_DIVS.setdefault(_vol, {}).update(dict.fromkeys(_ids.split(), "anf-works"))
for _reason, _per_vol in _ANF_NON_TEXT.items():
    for _vol, _ids in _per_vol.items():
        EXCLUDED_DIVS.setdefault(_vol, {}).update(dict.fromkeys(_ids.split(), f"non-text: {_reason}"))


#: NPNF QA pass (M8 title/author audit).  Divs carved into properly
#: attributed Works by ``npnf_works`` (space-separated ``@id``s per volume) ...
_NPNF_WORKS_DIVS: dict[str, str] = {
    "npnf101": """
        vi vii
    """,
    "npnf102": """
        iv v
    """,
    "npnf103": """
        iv.i iv.ii iv.iii iv.iv iv.v iv.vi iv.vii v.i v.ii v.iii v.iv v.v v.vi
        v.vii v.viii v.ix
    """,
    "npnf104": """
        iv.iv iv.v iv.vi iv.vii iv.viii iv.ix iv.x v.iv v.v v.vi
    """,
    "npnf105": """
        x xi xii xiii xiv xv xvi xvii xviii xix xx xxi.ii xxi.iii
    """,
    "npnf106": """
        v vi vii
    """,
    "npnf107": """
        iii iv v
    """,
    "npnf108": """
        ii
    """,
    "npnf109": """
        iv v vi vii viii ix x xi xii xiii xiv xv xvi xvii xviii xix
    """,
    "npnf110": """
        iii
    """,
    "npnf111": """
        vi vii
    """,
    "npnf112": """
        iv v
    """,
    "npnf113": """
        iii.iii iii.iv iv.iii iv.iv iv.v iv.vi v.iii v.iv v.v v.vi
    """,
    "npnf114": """
        iv v
    """,
    "npnf201": """
        iii.vi iii.vii iii.viii iii.ix iii.x iii.xi iii.xii iii.xiii iii.xv
        iii.xvi iii.xiv iv.vi iv.vii iv.viii
    """,
    "npnf202": """
        ii.iv ii.v ii.vi ii.vii ii.viii ii.ix ii.x iii.v iii.vi iii.vii
        iii.viii iii.ix iii.x iii.xi iii.xii iii.xiii iii.xiv
    """,
    "npnf203": """
        iv.vi iv.vii iv.viii iv.ix iv.x v.iii v.iv vi.iii vi.iv vi.v vi.vii
        vi.viii vi.xiv vi.xv vi.xvi vi.xvii vi.xviii vi.xix vi.xx vi.vi vi.ix
        vi.x vi.xi vi.xii vi.xiii
    """,
    "npnf204": """
        vi vii viii ix x xi xii xiii xiv xv xvi xvii xviii xix xx xxi xxii
        xxiii xxiv xxv.ii xxv.iii.ii xxv.iii.iii xxv.iii.iv
    """,
    "npnf205": """
        viii.i viii.ii viii.iii viii.iv viii.v viii.vi ix.ii ix.iii ix.iv x.ii
        x.iii xi.ii xii.ii xii.iii xiii
    """,
    "npnf206": """
        v vi.i vi.ii vi.iii vi.iv vi.v vi.vi vi.vii vi.viii vi.ix vii
    """,
    "npnf207": """
        ii.iv ii.v ii.vi ii.vii ii.viii ii.ix ii.x ii.xi ii.xii ii.xiii ii.xiv
        ii.xv ii.xvi ii.xvii ii.xviii ii.xix ii.xx ii.xxi ii.xxii ii.xxiii
        ii.xxiv ii.xxv ii.xxvi ii.xxvii iii.iii iii.iv iii.v iii.vi iii.vii
        iii.viii iii.ix iii.x iii.xi iii.xiii iii.xiv iii.xv iii.xvi iii.xvii
        iii.xviii iii.xix iii.xx iii.xxi iii.xxii iii.xxiii iii.xxiv iii.xxv
        iii.xxvi iii.xxvii iv.ii iv.iii iv.iv
    """,
    "npnf208": """
        vii viii ix
    """,
    "npnf209": """
        ii.iv ii.v ii.vi iii.iv
    """,
    "npnf210": """
        iv.i iv.ii iv.iii iv.iv iv.v iv.vi iv.vii iv.viii v.i v.iii v.ii v.iv
        v.v v.vi v.viii v.ix v.x v.xi v.xii v.xiii v.xiv v.xv v.vii
    """,
    "npnf211": """
        ii.ii ii.iii ii.iv ii.v ii.vi iii iv.ii iv.iii iv.iv iv.v iv.vi iv.vii
    """,
    "npnf212": """
        ii.iv ii.v iii.iv iii.v
    """,
    "npnf213": """
        ii.v ii.vi ii.vii ii.viii ii.ix ii.x iii.iv iii.v iii.vi iii.vii
        iii.viii iii.ix
    """,
    "npnf214": """
        xvii.iv xvii.v xvii.vi xvii.vii xvii.viii xvii.ix xvii.x xvii.xi
        xvii.xii xvii.xiii xvii.xiv xvii.xv xvii.xvi xvii.xvii xvii.xviii
        xvii.xix xvii.xx xvii.xxi xvii.xxii xvii.xxiii xvii.xxiv xvii.xxv
        xvii.xxvi xvii.xxvii xvii.xxviii xvii.xxix xvii.xxx xvii.xxxi
        xvii.xxxii
    """,
}
#: ... and the NPNF apparatus: title pages, contents, indexes, and the
#: editors' / translators' prefaces, prolegomena, introductions, notes and
#: excursuses.  Authorial prefaces and introductions (Augustine's, Eusebius',
#: Socrates', Cassian's, Rufinus' ...) are deliberately not listed.
_NPNF_NON_TEXT: dict[str, dict[str, str]] = {
    "title page": {
        "npnf101": "i",
        "npnf102": "i",
        "npnf103": "i",
        "npnf104": (
            "i iv.i iv.iv.i iv.v.i iv.vi.i iv.vii.i iv.viii.i iv.ix.i iv.x.i "
            "v.i v.iv.i v.v.i v.vi.i "
        ),
        "npnf105": (
            "i x.i xi.i xii.i xiii.i xiv.i xv.i xvi.i xvii.i xviii.i xix.i xx.i "
            "xxi.i xxi.iii.i "
        ),
        "npnf106": "i v.i vi.i vii.i",
        "npnf107": "i iii.i iv.i v.i",
        "npnf108": "i ii.i",
        "npnf109": (
            "i iv.i v.i vi.i vii.i viii.i ix.i x.i xi.i xii.i xiii.i xiv.i xv.i "
            "xvi.i xvii.i xviii.i xix.i "
        ),
        "npnf110": "i iii.i",
        "npnf111": "i iii",
        "npnf112": "i ii",
        "npnf113": "i iii.i iv.i v.i",
        "npnf114": "i iv.i v.i",
        "npnf201": "i iii.i iv.i iv.v",
        "npnf202": "i ii.i iii.i",
        "npnf203": "i iv.i v.i vi.i",
        "npnf204": "i iii",
        "npnf205": "i iii ix.i x.i xi.i xii.i xiii.i",
        "npnf206": "i ii",
        "npnf207": "i ii.i iii.i iv.i",
        "npnf208": "i ii",
        "npnf209": "i iii.i ii.i",
        "npnf210": "i",
        "npnf211": "i",
        "npnf212": "i ii.i iii.i",
        "npnf213": (
            "i ii.i iii.i iii.iv.i iii.v.i iii.vi.i iii.vii.i iii.viii.i "
            "iii.ix.i "
        ),
        "npnf214": "i viii.i xv.i xvii.i",
    },
    "table of contents": {
        "npnf101": "iii",
        "npnf102": "ii v.ii",
        "npnf103": "iii",
        "npnf104": "iii",
        "npnf105": "iii",
        "npnf106": "ii",
    },
    "index": {
        "npnf101": "x viii ix",
        "npnf102": "vi vii",
        "npnf103": "vi vii",
        "npnf104": "vi vii",
        "npnf105": "xxii xxiii",
        "npnf106": "viii ix",
        "npnf107": "vi",
        "npnf108": "iii iv",
        "npnf109": "xx xxi",
        "npnf110": "iv v",
        "npnf111": "viii ix",
        "npnf112": "vi vii",
        "npnf113": "vi vii",
        "npnf114": "vi vii",
        "npnf201": "v vi",
        "npnf202": "iv v",
        "npnf203": "vii",
        "npnf204": "xxvi",
        "npnf205": "xiv",
        "npnf206": "viii",
        "npnf207": "v",
        "npnf208": "x",
        "npnf209": "iv",
        "npnf210": "vi",
        "npnf211": "v",
        "npnf212": "iv",
        "npnf213": "iv",
        "npnf214": "xviii",
    },
    "editorial": {
        "npnf101": "ii iv v vi.i vii.i",
        "npnf102": "iii iv.i v.i",
        "npnf103": (
            "ii iv.i.i iv.i.ii iv.ii.i iv.iii.i iv.iv.i iv.vi.i v.ii.i v.iii.i "
            "v.iv.i v.v.i v.vi.i v.vii.i v.viii.i v.ix.i "
        ),
        "npnf104": "ii iv.ii iv.iii iv.ix.ii iv.x.ii v.ii v.iii v.iv.ii v.v.ii",
        "npnf105": (
            "ii iv v vi vii viii ix xii.iii xiii.ii xiv.iii xvi.iii xvii.iii "
            "xxi.iii.ii "
        ),
        "npnf106": "iii iv vi.ii vii.ii vi.iii",
        "npnf107": "ii iv.ii v.ii",
        "npnf108": "ii.ii ii.iii",
        "npnf109": (
            "ii iii iv.ii v.ii vi.ii vii.ii viii.ii x.ii xv.ii xvi.ii xvii.ii "
            "xviii.ii xix.ii "
        ),
        "npnf110": "ii iii.ii iii.iii",
        "npnf111": "ii iv v vii.i",
        "npnf112": "iii",
        "npnf113": "ii iii.ii iv.ii v.ii",
        "npnf114": "ii iii iv.ii v.ii v.iii",
        "npnf201": "ii iii.ii iii.iii iii.iv iii.v iii.xvii iv.ii iv.iii iv.iv",
        "npnf202": "ii.ii ii.iii iii.ii iii.iii iii.iv",
        "npnf203": "iii iv.ii iv.iii iv.iv iv.v v.ii vi.ii",
        "npnf204": (
            "ii iv v vi.i vii.i viii.i ix.i ix.iii x.i xi.i xii.i xiii.i "
            "xiii.iii xiv.i xv.i xvi.i xvii.i xviii.i xix.i xx.i xxi.i "
            "xxi.ii.ii xxi.ii.v xxii.i xxiii.i xxiv.i xxv.i xxv.ii.i xxv.iii.i "
        ),
        "npnf205": "ii iv v vi vii viii.ii.i ix.ii.i x.ii.i",
        "npnf206": "iii iv vii.i vii.iii.i vii.iv.i",
        "npnf207": "ii.ii ii.iii iii.ii iii.xii iv.ii.i",
        "npnf208": "iii v vi vii.i viii.i ix.i",
        "npnf209": "iii.ii ii.ii ii.iii ii.iv.i ii.v.i ii.vi.i iii.iii",
        "npnf210": (
            "ii iii v iv.i.i iv.ii.i iv.iii.i iv.iv.i iv.iv.ii iv.v.i iv.vi.i "
            "iv.vii.i iv.viii.i "
        ),
        "npnf211": "ii.i iii.i iii.xxxv iii.xxxvi iii.xxxvii iv.i",
        "npnf212": "ii.ii ii.iii iii.ii iii.iii iii.iv.i",
        "npnf213": "ii.ii ii.iii ii.iv iii.ii iii.iii",
        "npnf214": "ii iii.i iii.ii iii.iii iv v vi viii.ii xv.ii xvii.ii xvii.iii",
    },
}
for _vol, _ids in _NPNF_WORKS_DIVS.items():
    EXCLUDED_DIVS.setdefault(_vol, {}).update(dict.fromkeys(_ids.split(), "npnf-works"))
for _reason, _per_vol in _NPNF_NON_TEXT.items():
    for _vol, _ids in _per_vol.items():
        for _id in _ids.split():
            # Never override a div already owned by another ingestor (npnf214 councils).
            EXCLUDED_DIVS.setdefault(_vol, {}).setdefault(_id, f"non-text: {_reason}")


# ---------------------------------------------------------------------------
# Volume parser
# ---------------------------------------------------------------------------

def parse_thml_volume(
    xml_path: Path,
    source_id: str,
    volume_id: str,
    volume_label: str,
) -> list[tuple[Work, list[dict[str, str]]]]:
    """Parse a CCEL ThML volume and return one ``(Work, paragraphs)`` pair per ``<div1>``.

    Parameters
    ----------
    xml_path:     Path to the downloaded ThML XML file.
    source_id:    Source ID string, e.g. ``"patristic/ccel-anf"``.
    volume_id:    Volume code, e.g. ``"anf01"``.
    volume_label: Human-readable label, e.g. ``"ANF Vol. 1"``.
    """
    try:
        tree = etree.parse(str(xml_path))
    except etree.XMLSyntaxError as exc:
        log.warning("XML parse error in %s: %s", xml_path, exc)
        return []
    except Exception as exc:
        log.error("Failed to parse %s: %s", xml_path, exc)
        return []

    root = tree.getroot()
    body = _find_body(root)
    if body is None:
        log.warning("No body element found in %s", xml_path)
        return []

    results: list[tuple[Work, list[dict[str, str]]]] = []
    excluded = EXCLUDED_DIVS.get(volume_id, {})
    skip_ids = frozenset(excluded)
    div1_counter = 0
    series_prefix = source_id.split("/")[-1].upper().replace("-", "")  # e.g. "CCELANF"

    for child in body:
        if child.tag is etree.Comment:
            continue
        local = etree.QName(child.tag).localname
        if local != "div1":
            continue

        div1_counter += 1
        if child.get("id") in excluded:
            div_id = child.get("id")
            log.debug("Skipping %s div1 %s (%s)", volume_id, div_id, excluded[div_id])
            continue
        head_text = _get_head_text(child)
        title_words = set((head_text or "").lower().split())
        is_non_author = bool(title_words & _NON_AUTHOR_TITLE_WORDS)
        ident_text = _get_identification_text(child, max_paras=2)
        author_meta = None if is_non_author else _find_author_meta(ident_text)

        title = head_text or f"{volume_label} Part {div1_counter}"
        author_name = author_meta.full_name if author_meta else None

        # work_id uses the positional div1 counter so it is stable across re-runs
        # even when the title changes (e.g. after improving author detection).
        series_key = source_id.split("/")[-1]  # e.g. "ccel-anf"
        work_id = f"{series_key}/{volume_id}/{div1_counter:03d}"

        # Date info from author meta; fall back to uncertain
        if author_meta:
            birth, death = author_meta.dates
            date_composed: int | None = (birth + death) // 2
            date_range: tuple[int, int] | None = (birth, death)
            date_confidence: DateConfidence = "approximate"
            tradition: Tradition | None = author_meta.tradition
        else:
            date_composed = None
            date_range = None
            date_confidence = "uncertain"
            tradition = None

        # Canonical ref prefix: author abbreviation when identified, else vol+div slug
        if author_meta:
            ref_prefix = author_meta.abbrev
        else:
            n_attr = child.get("n", "")
            n_clean = re.sub(r"[^A-Za-z0-9]", "", n_attr)[:8] if n_attr else str(div1_counter)
            ref_prefix = f"{series_prefix}{volume_id[-2:]}{n_clean}"

        paragraphs = _extract_paragraphs_from_div1(child, ref_prefix, skip_ids)

        if not paragraphs:
            log.debug("No paragraphs in div1 %d (%r) of %s", div1_counter, title, xml_path.name)
            continue

        work = Work(
            work_id=work_id,
            source_id=source_id,
            author=author_name,
            title=title,
            date_composed=date_composed,
            date_range=date_range,
            date_confidence=date_confidence,
            genre="patristic",
            language="eng",
            tradition=tradition,
            license="public_domain",
            provenance_url=f"https://ccel.org/ccel/s/schaff/{volume_id}.xml",
            edition=volume_label,
            translation_of=None,
        )

        results.append((work, paragraphs))

    log.debug("Parsed %d works from %s", len(results), xml_path.name)
    return results


def ingest_ccel_series(
    output_dir: Path,
    source_id: str,
    volumes: list[tuple[str, str]],
    force: bool = False,
) -> list[Work]:
    """Ingest a CCEL series (one Work per div1) for ``ccel_anf`` / ``ccel_npnf1/2``.

    *volumes* is a list of ``(volume_id, volume_label)``.  Every run re-parses
    the cached volumes (cheap) and keeps the output in sync with the parser:
    files are written only when their content changed (so downstream mtimes
    stay put), and outputs no longer produced — e.g. a div newly added to
    ``EXCLUDED_DIVS`` — are deleted.  *force* only re-downloads the XML.
    """
    cache_dir = output_dir / source_id
    cache_dir.mkdir(parents=True, exist_ok=True)
    works: list[Work] = []

    for volume_id, volume_label in tqdm(volumes, desc=source_id):
        xml_path = download_volume(volume_id, cache_dir, force=force)
        vol_dir = cache_dir / volume_id
        produced: set[Path] = set()

        for work, paragraphs in parse_thml_volume(
            xml_path, source_id=source_id, volume_id=volume_id, volume_label=volume_label,
        ):
            out_path = vol_dir / f"{work.work_id.split('/')[-1]}.json"
            produced.add(out_path)
            content = json.dumps(
                {"work": work.model_dump(), "paragraphs": paragraphs},
                ensure_ascii=False, indent=2,
            )
            if not out_path.exists() or out_path.read_text(encoding="utf-8") != content:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(content, encoding="utf-8")
            works.append(work)

        for stale in sorted(vol_dir.glob("[0-9][0-9][0-9].json")):
            if stale not in produced:
                log.info("Removing %s (no longer produced; see EXCLUDED_DIVS)", stale)
                stale.unlink()

    log.info("%s ingestion complete: %d works", source_id, len(works))
    return works
