"""
Ingestor for the Coptic Scriptorium corpus.

Source: https://github.com/CopticScriptorium/corpora
Format: TEI P5 XML ({corpus}/{corpus}_TEI/*.xml), with linguistic annotation
License: per corpus, the most restrictive in its documents' TT headers (#382):
         mostly CC BY 4.0; some CC BY-NC-SA 4.0, CC BY-SA 4.0 or CC BY-SA 3.0

Scope
-----
Ingests Coptic patristic texts: homilies, saints' lives, Shenoute, letters,
monastic texts and apocrypha.  The ingestor gives every work genre
``patristic`` (#40); ``patristica/data/genre_overrides.csv`` then makes the
apocrypha ``apocrypha`` and the Lament of the Virgin ``liturgical`` (#103).

Excludes:
  - Biblical NT/OT books (already in ``coptic_nt.py``)
  - Treebank/duplicate corpora (``coptic-treebank``, ``bohairic-treebank``)
  - Gnostic/apocryphal texts (Thomas, Pistis Sophia, Book of Bartholomew)
  - Documentary and magical papyri

One Work is written per qualifying corpus.  All TEI XML files in
``{corpus}/{corpus}_TEI/`` are concatenated into a single paragraph list.

Text layers (#57)
-----------------
Coptic Scriptorium transcribes every text in two layers: the *diplomatic*
form of the manuscript (case as printed, supralinear strokes, diaereses,
abbreviations and nomina sacra such as ``Ⲓ̅Ⲥ̅``, the edition's brackets) and a
*normalized* form (lower case, no strokes, abbreviations and nomina sacra
written out: ``ⲓⲏⲥⲟⲩⲥ``, editorial brackets around supplied letters
removed, standard spelling).  Search, translation and the reader use the
normalized form for every work, so the same word is spelled the same way in
all of them; the diplomatic form is kept in each paragraph's ``orig`` key,
which ``scripts.normalize`` ignores.

The ``*_TEI`` directories hold two formats:

- Standard TEI P5 (most corpora), which has only the diplomatic layer.  Each
  ``<w>`` is a *morpheme* (article, preposition, verb prefix, …) and each
  ``<phr>`` is a *bound group*, the unit Coptic writes as one word.  The
  paragraphs (``<ab>``/``<p>``/…) come from the TEI; the text of each
  ``<phr>`` is the ``norm_group`` at the same position in the corpus's TreeTagger
  export (``*_TT/{same file name}.tt``), which has exactly one ``norm_group``
  per ``<phr>``: a missing TT file or a different count is an error
  (``CopticLayerError``).  ``orig`` joins the ``<w>`` texts of a ``<phr>``
  without spaces ("Ⲡ" + "ⲈⲠⲒⲤⲔⲞⲠⲞⲤ" → "ⲠⲈⲠⲒⲤⲔⲞⲠⲞⲤ"); whitespace inside a
  ``<w>`` is manuscript line breaks and markup layout, so it is dropped.
- The TreeTagger export itself, ``<meta>``-rooted (``life-aphou``,
  ``besa-letters``, …): the text is the ``norm_group`` attributes of a
  paragraph's ``<norm_group>`` elements, ``orig`` its ``orig_group``s.

Both join bound groups with spaces within each paragraph container, skipping
scholarly apparatus (``<note>``, ``<gap>``, ``<unclear>``, ``<supplied>``).

Malformed documents (#491)
--------------------------
Some documents are not well-formed XML, and a parser's recovery mangles them
(``helias``, ``mercurius``, ``shenoute-eagerness``, …): it nests paragraphs in
one another, so their text came out twice, and left the rest of a word that a
paragraph break splits as a paragraph of its own.  So nothing is read from a
recovered tree:

- The TreeTagger format is spans that cross by design (an ``<entity>`` or a
  ``<translation>`` across a ``norm_group``), so it is always read as a stream
  of tags (``_units_tt``): a bound group belongs to the paragraph open where
  it starts.  The old reading also lost the bound groups of ``<p>`` spans
  whose ``p`` value isn't exactly ``"p"``.
- A TEI document whose structure is broken is repaired as a stream of tags
  first (``_repair_tei``): only the paragraph container's tags and the tags
  inside it are kept, and a paragraph break inside a word (``ⲙ̄ </p><p n="3">
  Ⲡⲉ``, the second half written as the manuscript's enlarged initial) waits
  for the word to close, so the word stays whole in the paragraph where it
  starts.  The repaired document must parse with no structural error, or the
  work is skipped and logged at ERROR.  An ``xml:id`` that is no name or is
  used twice leaves the structure intact and is ignored (``_HARMLESS_ERRORS``).
Layout placeholders (``▢``) and the printed editions' footnote markers
(``⁽²⁾``, ``¹``) are dropped (``_paragraph_text``).

Lacunae: the normalized layer marks lost text with brackets holding only dots
or ellipses (``[....]``, ``[…]``, ``[]``).  They stay in the text for readers
and are marked as editorial material of kind ``lacuna`` (the paragraph's
``editorial`` key, ``patristica.editorial``, #236), so they are not translated
or embedded.  Brackets around letters (``[ⲉ]``, ``[ⲥⲟ]``, a handful) are the
editor's restoration of a word and stay unmarked.

Canonical references
--------------------
``CopScr.{corpus_slug}.{file_n:03d}.{para_n:04d}``

  corpus_slug  corpus name with ``-`` replaced by ``_``
  file_n       0-based index of the TEI file within the corpus
  para_n       sequential paragraph counter (0-based) within that file

Example: ``CopScr.shenoute_considering.000.0012``
"""

from __future__ import annotations

import html
import json
import logging
import re
from pathlib import Path

from lxml import etree
from tqdm import tqdm

from patristica.models import License, Work
from scripts.ingest._common import ensure_repo, slugify_ref

log = logging.getLogger(__name__)

SOURCE_ID = "coptic-scriptorium"

_REPO_URL = "https://github.com/CopticScriptorium/corpora"

# TEI namespace used by Coptic Scriptorium
_TEI_NS = "http://www.tei-c.org/ns/1.0"
_TEI = f"{{{_TEI_NS}}}"

# Coptic Unicode block (U+2C80–U+2CFF) + Greek letters used in Coptic (U+0370–U+03FF)
_COPTIC_RE = re.compile(r"[Ⲁ-⳿Ͱ-Ͽ]")

_WS_RE = re.compile(r"\s+")

# Noise in the transcriptions that carries no text (#28, #125):
# - ``▢`` (U+25A2): the Marcion transcriptions of Budge's editions (MERC.*
#   manuscripts: pseudo-timothy, mysteries-john, life-john-kalybites) tag it
#   PUNCT and use it for blank layout space: the spacing between the letters of
#   a decorated title (Budge prints "ⲁ   ⲱ̅    ⲓ̅ⲥ̅ ✠ ⲭ̅ⲥ̅" where the source has
#   "▢▢▢ Ⲁ ▢▢▢ Ⲱ̅ ▢▢▢▢ Ⲓ̅Ⲥ̅ ▢✠▢ Ⲭ̅Ⲥ̅") and the indent at a section's start.  It
#   is not a lacuna (those are ``[....]``/``<gap>``) and stands for no glyph.
# - Superscript digits, bare or parenthesised (``⁽²⁾``, ``¹``): footnote
#   markers of the printed edition, whose notes the source doesn't carry.
_NOISE_RE = re.compile(r"[▢⁽⁾⁰¹²³⁴-⁹]")

# A lacuna marker of the normalized layer: brackets around nothing but dots,
# ellipses and spaces.  Marked as editorial material (#236).
_LACUNA_RE = re.compile(r"\[[.…\s]*\]")

# Tags whose text content we skip during extraction (scholarly apparatus)
_SKIP_TAGS = frozenset({
    f"{_TEI}note",
    f"{_TEI}gap",
    f"{_TEI}unclear",
    f"{_TEI}supplied",
    f"{_TEI}app",
    f"{_TEI}orig",   # inside <choice>: use <reg> instead
})

# ---------------------------------------------------------------------------
# Corpus definitions
# ---------------------------------------------------------------------------

# Explicit metadata for each qualifying corpus.
# Keys: genre, author, title, date_composed, date_range, date_confidence
_CORPUS_META: dict[str, dict] = {
    "AP": {
        "genre": "patristic",
        "author": "Various Desert Fathers",
        "title": "Apophthegmata Patrum",
        "date_composed": 425,
        "date_range": (350, 500),
        "date_confidence": "approximate",
    },
    "besa-letters": {
        "genre": "patristic",
        "author": "Besa",
        "title": "Letters of Besa",
        "date_composed": 475,
        "date_range": (450, 500),
        "date_confidence": "approximate",
    },
    "pachomius-instructions": {
        "genre": "patristic",
        "author": "Pachomius",
        "title": "Instructions of Pachomius",
        "date_composed": 330,
        "date_range": (320, 346),
        "date_confidence": "established",
    },
    "proclus-homilies": {
        "genre": "patristic",
        "author": "Proclus of Constantinople",
        "title": "Homilies of Proclus (Coptic translation)",
        "date_composed": 420,
        "date_range": (390, 446),
        "date_confidence": "established",
    },
    # Three discourses of Budge's Coptic Homilies (BL Or. 5001), ascribed to
    # Athanasius in the codex.  Coptic Scriptorium credits "On the Soul and
    # Body" to Melito (the Syriac gives it to Alexander of Alexandria, CPG
    # 2004); the attribution and a split are open (#398).
    "pseudo-athanasius-discourses": {
        "genre": "patristic",
        "author": "Pseudo-Athanasius",
        "title": "Discourses Attributed to Athanasius (Coptic)",
        "date_composed": None,
        "date_range": (300, 500),
        "date_confidence": "uncertain",
    },
    "pseudo-basil": {
        "genre": "patristic",
        "author": "Pseudo-Basil",
        "title": "Works Attributed to Basil the Great (Coptic)",
        "date_composed": None,
        "date_range": (300, 500),
        "date_confidence": "uncertain",
    },
    "pseudo-chrysostom": {
        "genre": "patristic",
        "author": "Pseudo-Chrysostom",
        "title": "Works Attributed to John Chrysostom (Coptic)",
        "date_composed": None,
        "date_range": (380, 500),
        "date_confidence": "uncertain",
    },
    "pseudo-ephrem": {
        "genre": "patristic",
        "author": "Pseudo-Ephrem",
        "title": "Works Attributed to Ephrem the Syrian (Coptic)",
        "date_composed": None,
        "date_range": (306, 373),
        "date_confidence": "uncertain",
    },
    "pseudo-flavianus": {
        "genre": "patristic",
        "author": "Pseudo-Flavianus",
        "title": "Encomium on Demetrius of Alexandria (Coptic)",
        "date_composed": None,
        "date_range": (400, 500),
        "date_confidence": "uncertain",
    },
    "pseudo-timothy": {
        "genre": "patristic",
        "author": "Pseudo-Timothy",
        "title": "Discourse on Abbaton (Coptic)",
        "date_composed": None,
        "date_range": (400, 550),
        "date_confidence": "uncertain",
    },
    "pseudo-celestinus": {
        "genre": "patristic",
        "author": "Pseudo-Celestinus",
        "title": "Encomium on Victor (Coptic)",
        "date_composed": None,
        "date_range": (400, 432),
        "date_confidence": "uncertain",
    },
    # Hagiographies
    "life-aphou": {
        "genre": "patristic",
        "author": None,
        "title": "Life of Aphou",
        "date_composed": None,
        "date_range": (300, 600),
        "date_confidence": "uncertain",
    },
    "life-cyrus": {
        "genre": "patristic",
        "author": None,
        "title": "Life of Cyrus",
        "date_composed": None,
        "date_range": (300, 700),
        "date_confidence": "uncertain",
    },
    "life-eustathius-theopiste": {
        "genre": "patristic",
        "author": None,
        "title": "Life of Eustathius and Theopiste",
        "date_composed": None,
        "date_range": (300, 700),
        "date_confidence": "uncertain",
    },
    "life-john-kalybites": {
        "genre": "patristic",
        "author": None,
        "title": "Life of John the Dweller in the Hovel",
        "date_composed": None,
        "date_range": (400, 600),
        "date_confidence": "uncertain",
    },
    "life-longinus-lucius": {
        "genre": "patristic",
        "author": None,
        "title": "Life of Longinus and Lucius",
        "date_composed": None,
        "date_range": (300, 600),
        "date_confidence": "uncertain",
    },
    "life-onnophrius": {
        "genre": "patristic",
        "author": None,
        "title": "Life of Onnophrius",
        "date_composed": None,
        "date_range": (300, 600),
        "date_confidence": "uncertain",
    },
    "life-paul-tamma": {
        "genre": "patristic",
        "author": None,
        "title": "Life of Paul of Tamma",
        "date_composed": None,
        "date_range": (300, 500),
        "date_confidence": "uncertain",
    },
    "life-phib": {
        "genre": "patristic",
        "author": None,
        "title": "Life of Phib",
        "date_composed": None,
        "date_range": (300, 600),
        "date_confidence": "uncertain",
    },
    "life-pisentius": {
        "genre": "patristic",
        "author": None,
        "title": "Life of Bishop Pisentius",
        "date_composed": 600,
        "date_range": (569, 632),
        "date_confidence": "approximate",
    },
    # Apocrypha.  None of these is a liturgy, so they are ``patristic`` like
    # the NT apocrypha in anf_works.py (#40).  The Lament of the Virgin
    # (Pseudo-Gamaliel) is read in Holy Week, but it is a narrative homily,
    # not a liturgical text.
    "dormition-john": {
        "genre": "patristic",
        "author": None,
        "title": "Dormition of John the Apostle (Coptic)",
        "date_composed": None,
        "date_range": (100, 400),
        "date_confidence": "uncertain",
    },
    "lament-mary": {
        "genre": "patristic",
        "author": None,
        "title": "Lament of the Virgin Mary (Coptic)",
        "date_composed": None,
        "date_range": (100, 600),
        "date_confidence": "uncertain",
    },
    "mysteries-john": {
        "genre": "patristic",
        "author": None,
        "title": "Mysteries of John (Coptic)",
        "date_composed": None,
        "date_range": (100, 600),
        "date_confidence": "uncertain",
    },
    # Other patristic/hagiographic
    "acts-pilate": {
        "genre": "patristic",
        "author": None,
        "title": "Acts of Pilate (Coptic)",
        "date_composed": None,
        "date_range": (100, 400),
        "date_confidence": "uncertain",
    },
    # Two works (#365, split: #398): Stephen of Hnes's Encomium and the
    # anonymous Martyrdom (Sobhy's edition of Hamuli MS 2703).
    "helias": {
        "genre": "patristic",
        "author": "Stephen of Hnes; Anonymous",
        "title": "Encomium and Martyrdom of Helias (Coptic)",
        "date_composed": None,
        "date_range": (300, 600),
        "date_confidence": "uncertain",
    },
    # Three anonymous works (#365, split: #398), from Budge, Miscellaneous Coptic Texts.
    "mercurius": {
        "genre": "patristic",
        "author": None,
        "title": "Encomium, Martyrdom and Miracles of Mercurius (Coptic)",
        "date_composed": None,
        "date_range": (300, 600),
        "date_confidence": "uncertain",
    },
    # By Theodosius, not about him (#365); two manuscripts (MERC.AL, MERC.AI).
    "theodosius-alexandria": {
        "genre": "patristic",
        "author": "Theodosius of Alexandria",
        "title": "Encomium on Michael the Archangel (Coptic)",
        "date_composed": None,
        "date_range": (400, 600),
        "date_confidence": "uncertain",
    },
    # Shenoute's Abraham Our Father (YA 518-554, XL 93-94, ZH), not a Life (#365).
    "abraham": {
        "genre": "patristic",
        "author": "Shenoute of Atripe",
        "title": "Abraham Our Father (Coptic)",
        "date_composed": None,
        "date_range": (300, 600),
        "date_confidence": "uncertain",
    },
    "johannes-canons": {
        "genre": "patristic",
        "author": "Johannes the Archimandrite",
        "title": "Canons of Apa Johannes (Coptic)",
        "date_composed": None,
        "date_range": (300, 600),
        "date_confidence": "uncertain",
    },
    # By John IV the Faster, not a Life of him (#365).
    "john-constantinople": {
        "genre": "patristic",
        "author": "John IV of Constantinople",
        "title": "On Penitence and Abstinence (Coptic)",
        "date_composed": None,
        "date_range": (300, 600),
        "date_confidence": "uncertain",
    },
}

# Shenoute of Atripe corpora (prefix-matched below)
_SHENOUTE_META = {
    "genre": "patristic",
    "author": "Shenoute of Atripe",
    "date_composed": 420,
    "date_range": (385, 465),
    "date_confidence": "established",
}

# Corpora to exclude entirely
_EXCLUDED: frozenset[str] = frozenset({
    # Biblical (already in coptic_nt.py or out of scope)
    "bohairic.nt", "bohairic.ot", "sahidica.nt", "sahidic.ot",
    "sahidic.ruth", "sahidic.jonah",
    "sahidica.mark", "sahidica.1corinthians",
    "bohairic.1corinthians", "bohairic.mark",
    # Duplicate treebanks
    "coptic-treebank", "bohairic-treebank",
    # Gnostic / apocryphal
    "thomas-gospel", "pistis-sophia", "book-bartholomew",
    # Documentary
    "doc-papyri", "magical-papyri",
})


def _corpus_meta(corpus: str) -> dict | None:
    """Return metadata dict for a corpus name, or None if excluded/unknown."""
    if corpus in _EXCLUDED:
        return None
    if corpus in _CORPUS_META:
        return _CORPUS_META[corpus]
    if corpus.startswith("shenoute-"):
        title = corpus.replace("shenoute-", "").replace("-", " ").title()
        return {**_SHENOUTE_META, "title": f"Shenoute: {title}"}
    return None


# ---------------------------------------------------------------------------
# Repo management
# ---------------------------------------------------------------------------

def _ensure_repo(repo_dir: Path, force: bool) -> None:
    """Clone the repo if absent; pull latest on force (not offline, #215)."""
    ensure_repo(_REPO_URL, repo_dir, "Coptic Scriptorium", force)


# ---------------------------------------------------------------------------
# TEI text extraction
# ---------------------------------------------------------------------------

class CopticLayerError(ValueError):
    """A TEI file's normalized layer (its TreeTagger export) is missing or
    doesn't match the TEI's bound groups."""


# Normalized text of each <phr> of one TEI document, keyed by element.
NormMap = dict[etree._Element, str]

_PARSER_KW = {"recover": True, "no_network": True, "load_dtd": False}

# Parser errors that leave a document's structure intact: an xml:id that is no
# XML name ("53", "MERC.AG[1]") or one used twice.  Any other error means the
# recovered tree can't be trusted (#491).
_HARMLESS_ERRORS = frozenset({"DTD_XMLID_VALUE", "DTD_ID_REDEFINED"})

# Every tag of a document, for reading it as a stream (#491): close mark, name,
# attributes, self-closing mark.  The XML declaration and comments don't match.
_TAG_RE = re.compile(r"<(/?)([A-Za-z_][\w.:-]*)([^>]*?)(/?)>")

# The paragraph containers of a TEI document, in the order they are tried.
_CONTAINERS = ("ab", "p", "s", "l")


class CopticStructureError(ValueError):
    """A malformed document that ``_repair_tei`` can't make well-formed."""


def _parse(xml: bytes) -> tuple[etree._Element, list[str]]:
    """Parse *xml* with recovery; the root and the structural errors, if any."""
    parser = etree.XMLParser(**_PARSER_KW)
    root = etree.fromstring(xml, parser)
    errors = [
        f"line {e.line}: {e.message}" for e in parser.error_log
        if e.type_name not in _HARMLESS_ERRORS
    ]
    return root, errors


def _local(name: str) -> str:
    """A tag name without its prefix (``tei:p`` → ``p``)."""
    return name.rsplit(":", 1)[-1]


def _repair_tei(text: str) -> str:
    """A malformed TEI document made well-formed, as a stream of tags (#491).

    The body keeps the tags of its paragraph container (the first of
    ``_CONTAINERS`` it has) and the tags inside a paragraph; the other
    containers and the divisions (which cross paragraphs and words) are
    dropped, as nothing is read from them.  A paragraph break inside an open
    element (a word) is moved to where that element closes.  Raises
    ``CopticStructureError`` for any other crossing.
    """
    start = re.search(r"<body\b[^>]*>", text)
    end = text.rfind("</body>")
    if start is None or end < start.end():
        raise CopticStructureError("no <body>")
    body = text[start.end():end]
    present = {_local(m.group(2)) for m in _TAG_RE.finditer(body) if not m.group(1)}
    container = next((c for c in _CONTAINERS if c in present), None)
    if container is None:
        raise CopticStructureError("no paragraph container in <body>")
    dropped = {c for c in _CONTAINERS if c != container}

    out: list[str] = []
    stack: list[str] = []
    deferred: list[str] = []   # a paragraph break waiting for a word to close
    pos = 0
    for m in _TAG_RE.finditer(body):
        out.append(body[pos:m.start()])
        pos = m.end()
        closing, name, self_closing = m.group(1), _local(m.group(2)), m.group(4)
        tag = m.group(0)
        if name in dropped or name.startswith("div"):
            continue
        if self_closing:
            out.append(tag)
        elif name == container and not closing:
            if deferred:
                deferred.append(tag)
            else:
                stack.append(name)
                out.append(tag)
        elif name == container:
            if stack and stack[-1] == container:
                stack.pop()
                out.append(tag)
            elif container in stack:
                deferred.append(tag)
            # else: a close with no open paragraph; drop it
        elif not closing:
            stack.append(name)
            out.append(tag)
        elif stack and stack[-1] == name:
            stack.pop()
            out.append(tag)
            if deferred and stack and stack[-1] == container:
                for d in deferred:
                    if d.startswith("</"):
                        stack.pop()
                    else:
                        stack.append(container)
                    out.append(d)
                deferred = []
        else:
            raise CopticStructureError(
                f"</{name}> closes <{stack[-1] if stack else '(nothing)'}>"
            )
    out.append(body[pos:])
    if stack or deferred:
        raise CopticStructureError(f"unclosed at the end of <body>: {stack}")
    return text[:start.end()] + "".join(out) + text[end:]


def _elem_words(el: etree._Element, norms: NormMap | None = None) -> list[str]:
    """Collect word-level text from an element, skipping apparatus tags.

    With *norms*, a ``<phr>`` contributes its normalized text; without, its
    diplomatic ``<w>`` text.
    """
    words: list[str] = []
    _collect_words(el, words, norms)
    return words


def _collect_words(el: etree._Element, out: list[str], norms: NormMap | None) -> None:
    """Recursively collect text, preferring <w> and <reg> over raw PCDATA."""
    if not isinstance(el.tag, str):
        return
    tag = etree.QName(el.tag).localname
    ns_tag = el.tag

    # Skip scholarly apparatus entirely
    if ns_tag in _SKIP_TAGS:
        return

    # Normalized layer: the bound group's norm_group from the TT export.
    if tag == "phr" and norms is not None:
        word = _WS_RE.sub("", norms[el])
        if word:
            out.append(word)
        return

    # Inside <choice>, use <reg> (normalized) not <orig> (manuscript)
    if tag == "choice":
        reg = el.find(f"{_TEI}reg")
        if reg is not None:
            _collect_words(reg, out, norms)
        else:
            # No <reg>; fall back to <corr> then first child
            corr = el.find(f"{_TEI}corr")
            target = corr if corr is not None else (el[0] if len(el) else None)
            if target is not None:
                _collect_words(target, out, norms)
        return

    # Bound group (<phr>) and morpheme (<w>): written together as one word.
    # Whitespace inside them is only markup layout (newlines between <w> and
    # <m> elements, manuscript line breaks with or without <lb/>), so drop it
    # rather than splitting the word.  Recursing (rather than itertext) keeps
    # the <choice> and apparatus handling inside words.
    if tag in ("phr", "w"):
        parts: list[str] = []
        _collect_children(el, parts, norms)
        word = _WS_RE.sub("", "".join(parts))
        if word:
            out.append(word)
        return

    # For any other element, recurse into children; also pick up direct PCDATA
    _collect_children(el, out, norms)


def _collect_children(el: etree._Element, out: list[str], norms: NormMap | None) -> None:
    """Collect an element's own text, its children's words, and their tails."""
    if el.text and el.text.strip():
        out.append(el.text.strip())
    for child in el:
        _collect_words(child, out, norms)
        if child.tail and child.tail.strip() and child.tag not in _SKIP_TAGS:
            out.append(child.tail.strip())


def _paragraph_text(words: list[str]) -> str:
    """Join a paragraph's bound groups, dropping placeholder and footnote noise."""
    return _WS_RE.sub(" ", _NOISE_RE.sub("", " ".join(words))).strip()


def _tt_path(tei_path: Path) -> Path | None:
    """The TreeTagger export of *tei_path*: ``{corpus}/*_TT/{same name}.tt``.

    File names are matched without case: AP's TEI files are ``ap.*.xml`` and
    its TT files ``AP.*.tt``.
    """
    stem = tei_path.stem.lower()
    for tt_dir in sorted(tei_path.parent.parent.glob("*_TT")):
        for tt in sorted(tt_dir.glob("*.tt")):
            if tt.stem.lower() == stem:
                return tt
    return None


def _norm_map(root: etree._Element, tei_path: Path) -> NormMap:
    """Map every ``<phr>`` of a TEI document to its normalized form.

    The TT export of the same document has one ``norm_group`` per ``<phr>``, in
    the same order; anything else raises ``CopticLayerError``.  The export's
    spans cross, so it is read as a stream of tags (#491).
    """
    tt_path = _tt_path(tei_path)
    if tt_path is None:
        raise CopticLayerError(f"{tei_path}: no TreeTagger export (*_TT/{tei_path.stem}.tt)")
    norms = [
        _attr(m, "norm_group")
        for m in _TAG_RE.finditer(tt_path.read_text(encoding="utf-8"))
        if m.group(2) == "norm_group" and not m.group(1)
    ]
    phrs = [
        el for el in root.iter()
        if isinstance(el.tag, str) and etree.QName(el.tag).localname == "phr"
    ]
    if len(phrs) != len(norms):
        raise CopticLayerError(
            f"{tei_path}: {len(phrs)} bound groups (<phr>) but {tt_path.name} has "
            f"{len(norms)} norm_group"
        )
    return dict(zip(phrs, norms))


# ---------------------------------------------------------------------------
# Licences (#382): from each document's TT header, shared with coptic_scriptorium_eng
# ---------------------------------------------------------------------------

# The tags of a TT export that matter to its readers, in document order.  TT
# spans may cross (a <translation> can open inside an <entity> and close
# outside it), so the export is read as a stream of tags, not as a tree.
_TT_TAG_RE = re.compile(r"<(/?)(translation|norm_group|meta)\b([^>]*)>")
_TT_ATTR_RE = re.compile(r'([\w.-]+)="([^"]*)"')

# The CC licences the corpus can record, by terms and version.
_CC_LICENSES: dict[tuple[str, str], License] = {
    ("by", "4.0"): "cc-by-4.0",
    ("by-sa", "4.0"): "cc-by-sa-4.0",
    ("by-nc", "4.0"): "cc-by-nc-4.0",
    ("by-nc-sa", "4.0"): "cc-by-nc-sa-4.0",
    ("by-sa", "3.0"): "cc-by-sa-3.0",
    ("by-nc-sa", "3.0"): "cc-by-nc-sa-3.0",
}
# Terms, least restrictive first.
_CC_TERMS = ("by", "by-sa", "by-nc", "by-nc-sa")
_CC_URL_RE = re.compile(r"creativecommons\.org/licenses/([a-z-]+)/(\d\.\d)")
_CC_LABEL_RE = re.compile(r"\bcc[- ](by(?:[- ]nc)?(?:[- ]sa)?)\b\D*(\d\.\d)")


class CopticLicenseError(ValueError):
    """A document's licence is not one we can record."""


def _read_header(path: Path) -> dict[str, str]:
    """The attributes of a TT export's ``<meta>`` header."""
    m = _TT_TAG_RE.search(path.read_text(encoding="utf-8"))
    if m is None or m.group(2) != "meta":
        return {}
    return {k: html.unescape(v) for k, v in _TT_ATTR_RE.findall(m.group(3))}


def _license(text: str) -> License:
    """The ``License`` value of a TT header's ``license`` attribute
    (``<a href='…/by-nc-sa/4.0/'>CC BY-NC-SA 4.0</a>``, ``CC-BY 4.0 -``).

    The link and the label are read separately; where they disagree
    (``mercurius`` links BY-SA 4.0 but reads "CC-BY 4.0") the more restrictive
    wins.  ``CopticLicenseError`` if neither names a licence we can record."""
    found: set[tuple[str, str]] = {(t, v) for t, v in _CC_URL_RE.findall(text)}
    plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).lower()
    found |= {(re.sub(r"[- ]", "-", t), v) for t, v in _CC_LABEL_RE.findall(plain)}
    values = set()
    for terms, version in found:
        if (terms, version) not in _CC_LICENSES:
            raise CopticLicenseError(f"unrecognised licence {text!r}")
        values.add(_CC_LICENSES[terms, version])
    if not values:
        raise CopticLicenseError(f"unrecognised licence {text!r}")
    return _most_restrictive(values)


def _most_restrictive(licenses: set[License]) -> License:
    """The most restrictive of *licenses* (BY < BY-SA < BY-NC < BY-NC-SA);
    ``CopticLicenseError`` for two versions of the same terms."""
    def terms(value: str) -> str:
        return value.removeprefix("cc-").rsplit("-", 1)[0]
    by_terms = {terms(v) for v in licenses}
    if len(by_terms) != len(licenses):
        raise CopticLicenseError(f"licences {sorted(licenses)} differ only in version")
    return max(licenses, key=lambda v: _CC_TERMS.index(terms(v)))


def _corpus_license(tei_files: list[Path]) -> License:
    """A corpus's licence: the most restrictive in its documents' TT headers
    (the TEI's ``<licence>`` is boilerplate CC BY everywhere, #382)."""
    licenses: set[License] = set()
    for tei_path in tei_files:
        tt_path = _tt_path(tei_path)
        header = _read_header(tt_path) if tt_path is not None else {}
        if "license" not in header:
            raise CopticLicenseError(f"{tei_path}: no licence in its TT header")
        licenses.add(_license(header["license"]))
    return _most_restrictive(licenses)


def _paragraph(corpus_name: str, file_n: int, para_n: int, text: str, orig: str) -> dict:
    """A raw paragraph record: normalized ``text`` and diplomatic ``orig``, and its
    lacunae as ``editorial`` spans (``[start, end, "lacuna"]``) when it has any."""
    ref = slugify_ref(f"CopScr.{corpus_name}.{file_n:03d}.{para_n:04d}")
    record: dict = {"ref": ref, "text": text, "orig": orig}
    lacunae = [[m.start(), m.end(), "lacuna"] for m in _LACUNA_RE.finditer(text)]
    if lacunae:
        record["editorial"] = lacunae
    return record


# A paragraph record and the positions (in document order) of the bound groups
# it holds: the ``<phr>``s of a TEI document, the ``norm_group``s of a TT
# export.  ``coptic_scriptorium_eng`` puts the English sentences on the units
# by these positions.
Unit = tuple[dict, list[int]]


def _units_tei(
    root: etree._Element, file_n: int, corpus_name: str, norms: NormMap
) -> list[Unit]:
    """Extract paragraphs from a standard TEI P5 document.

    Tries candidate container element types in priority order, using the first
    type that yields results.  This prevents double-counting when both ``<p>``
    and ``<s>`` exist in the same document.
    """
    position = {el: i for i, el in enumerate(norms)}
    body = root.find(f".//{_TEI}body")
    if body is None:
        body = root.find(".//body")
    if body is None:
        return []

    # Try container types in priority order; stop at first type that yields text
    for container in _CONTAINERS:
        elements = [
            el for el in body.iter()
            if isinstance(el.tag, str) and etree.QName(el.tag).localname == container
        ]
        units: list[Unit] = []
        for el in elements:
            text = _paragraph_text(_elem_words(el, norms))
            if not _COPTIC_RE.search(text):
                continue
            orig = _paragraph_text(_elem_words(el))
            groups = [position[p] for p in el.iter() if p in position]
            units.append((_paragraph(corpus_name, file_n, len(units), text, orig), groups))
        if units:
            return units
    return []


def _units_tt(text: str, file_n: int, corpus_name: str) -> list[Unit]:
    """Extract paragraphs from the TreeTagger ``<meta>`` export, read as a
    stream of tags (its spans cross, #491).

    This format stores bound groups in ``<orig_group orig_group="…">`` /
    ``<norm_group norm_group="…">`` elements, inside ``<p_n>`` or ``<p>``
    paragraph spans; a group belongs to the paragraph open where it starts.
    Every ``<p>`` is a paragraph, whatever its ``p`` value (``p="s"`` and
    ``p="p   "`` hold text too, in ``shenoute-eagerness``).  A group that
    starts outside every paragraph (the end of a word begun on the previous
    leaf, whose ``<p>`` opens inside it) belongs to the next one, or the last.
    """
    tags = list(_TAG_RE.finditer(text))
    if any(m.group(2) == "p_n" for m in tags):
        def is_para(m: re.Match) -> bool:
            return m.group(2) == "p_n"
    elif any(m.group(2) == "p" for m in tags):
        def is_para(m: re.Match) -> bool:
            return m.group(2) == "p"
    else:
        # No paragraph spans: the whole document is one paragraph
        def is_para(m: re.Match) -> bool:
            return m.group(2) == "meta"

    def new_para() -> dict[str, list]:
        return {"norm_group": [], "orig_group": [], "groups": []}

    paras: list[dict[str, list]] = []
    open_para: dict[str, list] | None = None
    stray = new_para()   # groups outside every paragraph, for the next one
    n_groups = 0
    for m in tags:
        if is_para(m):
            if m.group(1):
                open_para = None
            elif not m.group(4):
                open_para = new_para()
                for key, values in stray.items():
                    open_para[key].extend(values)
                stray = new_para()
                paras.append(open_para)
            continue
        group = m.group(2)
        if group not in ("norm_group", "orig_group") or m.group(1):
            continue
        target = open_para if open_para is not None else stray
        if group == "norm_group":
            target["groups"].append(n_groups)
            n_groups += 1
        word = _attr(m, group).strip()
        if word:
            target[group].append(word)
    if stray["groups"]:
        if not paras:
            raise CopticStructureError("bound groups but no paragraph")
        for key, values in stray.items():
            paras[-1][key].extend(values)

    units: list[Unit] = []
    for para in paras:
        if not para["norm_group"]:
            continue
        para_text = _paragraph_text(para["norm_group"])
        if not _COPTIC_RE.search(para_text):
            continue
        orig = _paragraph_text(para["orig_group"])
        record = _paragraph(corpus_name, file_n, len(units), para_text, orig)
        units.append((record, para["groups"]))
    return units


def _attr(m: re.Match, name: str) -> str:
    """Attribute *name* of the tag matched by *m* (``""`` when absent)."""
    for key, value in _TT_ATTR_RE.findall(m.group(3)):
        if key == name:
            return html.unescape(value)
    return ""


def _is_tt(xml_path: Path) -> bool:
    """Whether *xml_path* is a TreeTagger export (``<meta>`` root)."""
    with open(xml_path, "rb") as f:
        return re.match(rb"\s*(<\?xml[^>]*>\s*)?<meta\b", f.read(512)) is not None


def _units(xml_path: Path, file_n: int, corpus_name: str) -> list[Unit]:
    """Parse a single Coptic Scriptorium XML file into units.

    Dispatches on the root element:
    - TreeTagger export (``<meta>`` root) → ``_units_tt``
    - Standard TEI P5 → ``_units_tei``, with the normalized text from the TT
      export; raises ``CopticLayerError`` when that is missing or differs.  A
      document whose structure is broken is repaired first (``_repair_tei``);
      raises ``CopticStructureError`` when it can't be.
    """
    if _is_tt(xml_path):
        return _units_tt(xml_path.read_text(encoding="utf-8"), file_n, corpus_name)
    xml = xml_path.read_bytes()
    root, errors = _parse(xml)
    if errors:
        log.info("  %s is malformed (%s); repairing it", xml_path.name, errors[0])
        root, errors = _parse(_repair_tei(xml.decode("utf-8")).encode("utf-8"))
        if errors:
            raise CopticStructureError(f"{xml_path}: still malformed after repair: {errors[0]}")
    if etree.QName(root.tag).localname != "TEI":
        log.debug("  Unknown root element <%s> in %s; trying TEI parser", root.tag, xml_path.name)
    return _units_tei(root, file_n, corpus_name, _norm_map(root, xml_path))


def _extract_paragraphs_from_tei(xml_path: Path, file_n: int, corpus_name: str) -> list[dict]:
    """The paragraph records of one XML file (``_units`` without positions)."""
    return [record for record, _ in _units(xml_path, file_n, corpus_name)]


# ---------------------------------------------------------------------------
# Ingestor
# ---------------------------------------------------------------------------

def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Clone Coptic Scriptorium repo and write per-corpus JSON output files."""
    repo_dir = Path(output_dir) / "_repos" / "coptic-scriptorium"
    _ensure_repo(repo_dir, force)

    out_root = Path(output_dir) / SOURCE_ID
    out_root.mkdir(parents=True, exist_ok=True)

    # Discover all corpus directories
    corpus_dirs = sorted(
        d for d in repo_dir.iterdir()
        if d.is_dir() and not d.name.startswith(".")
    )
    log.info("Found %d corpus directories", len(corpus_dirs))

    works: list[Work] = []

    for corpus_dir in tqdm(corpus_dirs, desc="Coptic Scriptorium corpora"):
        corpus_name = corpus_dir.name
        meta = _corpus_meta(corpus_name)
        if meta is None:
            log.debug("  Skipping corpus: %s", corpus_name)
            continue

        corpus_slug = corpus_name.replace("-", "_")
        out_path = out_root / f"{corpus_slug}.json"

        if out_path.exists() and not force:
            log.debug("  Skipping %s (already exists)", out_path.name)
            with open(out_path) as f:
                saved = json.load(f)
            works.append(Work(**saved["work"]))
            continue

        # Find TEI XML files
        tei_dir = corpus_dir / f"{corpus_name}_TEI"
        if not tei_dir.exists():
            # Try alternative capitalization
            candidates = list(corpus_dir.glob("*_TEI"))
            tei_dir = candidates[0] if candidates else None

        if tei_dir is None or not tei_dir.exists():
            log.warning("  No TEI directory for %s", corpus_name)
            continue

        tei_files = sorted(tei_dir.glob("*.xml"))
        if not tei_files:
            log.warning("  No TEI XML files in %s", tei_dir)
            continue

        # Extract paragraphs from all TEI files in this corpus
        all_paragraphs: list[dict] = []
        try:
            for file_n, xml_path in enumerate(tei_files):
                paras = _extract_paragraphs_from_tei(xml_path, file_n, corpus_name)
                all_paragraphs.extend(paras)
        except (CopticLayerError, CopticStructureError) as exc:
            # Without the normalized layer the work would be spelled
            # differently from the others (#57), and a document we can't
            # read whole would lose or repeat text (#491): leave it out, loudly.
            log.error("  Skipping %s: %s", corpus_name, exc)
            continue
        try:
            license_val = _corpus_license(tei_files)
        except CopticLicenseError as exc:
            log.error("  Skipping %s: %s", corpus_name, exc)
            continue

        if not all_paragraphs:
            log.warning("  No text extracted from %s (%d files)", corpus_name, len(tei_files))
            continue

        work = Work(
            work_id=f"{SOURCE_ID}/{corpus_slug}",
            source_id=SOURCE_ID,
            author=meta["author"],
            title=meta["title"],
            date_composed=meta["date_composed"],
            date_range=meta["date_range"],
            date_confidence=meta["date_confidence"],
            genre=meta["genre"],
            language="cop",
            tradition="coptic",
            license=license_val,
            provenance_url=f"{_REPO_URL}/tree/master/{corpus_name}",
            edition=f"Coptic Scriptorium, {corpus_name}",
        )

        out_path.write_text(
            json.dumps(
                {"work": work.model_dump(), "paragraphs": all_paragraphs},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        log.info(
            "  Wrote %s (%d paragraphs from %d files)",
            out_path.name, len(all_paragraphs), len(tei_files),
        )
        works.append(work)

    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
