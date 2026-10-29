"""
Ingestion module for TOROT's Old Church Slavonic texts that CCMH lacks (#334).

Source:  Syntacticus treebank release 20230428,
         https://github.com/syntacticus/syntacticus-treebank-data (``torot/*.xml``)
Format:  PROIEL XML: ``<source>`` → ``<div>`` → ``<sentence>`` → ``<token>``
License: CC BY-NC-SA 4.0 (the ``<license>`` of every file)

Works, all ``language="chu"`` in Cyrillic (TOROT's transcription of the
Glagolitic witnesses, passed through ``glagolitic_to_cyrillic`` like every
Slavonic ingestor, #330):

- ``psal-sin`` → ``torot/ps``: the Psalterium Sinaiticum (Sinai, Sin. slav. 38;
  Sever'janov 1922, Psalms 138–151 from Mareš 1997). One unit per verse from
  each token's ``citation-part`` (``N.V``), the superscription as ``Ps.N.0``
  (#239). Versification ``lxx`` (``patristica/versification.py``).
- ``kiev-mis`` → ``torot/kievmis``: the Kiev Missal (Kiev Folia).
- ``euch`` → ``torot/euch``: the eight prayers of the Euchologium Sinaiticum
  that TOROT has (a selection).
- ``chrabr`` → ``torot/chrabr``: Chrabr the Monk, *On the Letters*.

The prose works have no citation parts: each ``<div>`` is a section whose
first unit, ``{Prefix}.{n}``, is its rubric or title (the first sentence; in
the Kiev Missal every all-caps rubric sentence starts a new unit) and whose
other units are ``{Prefix}.{n}.{m}``, so the reader shows the rubrics as
section headings. The English ``<title>`` TOROT gives each div is its
annotators', not the manuscript's, and is left out. Since ``torot`` holds a
Scripture book, every one of its works is keyed like a book
(``patristica/versions.py``): a work's local id is its refs' first segment in
lower case (``KievMis.1`` → ``torot/kievmis``).

Text is each token's ``presentation-before`` + ``form`` + ``presentation-after``,
as TOROT has it (the editions' diplomatic punctuation included). A space is put
back after a stop that lacks one (``оубо.образомъ``), since derived verses
break only between words (#340), and sentences are joined with a space. Latin
look-alike letters in Cyrillic words (``Xрабъра``, ``cр҃це``; Chrabr's ``s`` for
the numeral ѕ) become Cyrillic; U+FFFC placeholders are dropped.

Editorial material (#236), marked on each unit, never stripped:

- ``lacuna``: dots standing for lost letters: any dots inside a word form
  (``тъщет.нъімъ``), two or more before a word (``......ашѩ``), three or more
  after one (``ст҃ъіѩ.... своеѩ``). Two dots after a word are the Psalter's
  punctuation (``-..``, 321 times) and stay text.
- ``supplement``: letters an editor restored, in square brackets in the Kiev
  Missal (``живот[ѣ]``) and in round brackets in the Psalter (``оукл(о)ни``).
  A bracket TOROT left unpaired (the Kiev Missal's ``тог]о``) is marked alone,
  so the source text drops it.
- ``note``: square brackets in the Psalter (Mareš's part), which mark a
  scribe's dittography the editor rejects (``[тъ] тъі``, ``въдо[во]вѫ``), and
  a sentence with Arabic digits: Archimandrite Porfirij Uspenskij's 1850
  reader's note after Ps 137.8.

The Psalter's unpaired ``)`` after many half-verses (``г҃ѣ.)``) is in the
edition's punctuation and stays text.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable
from pathlib import Path

from lxml import etree

from patristica.models import Work
from scripts.ingest._common import download_file
from scripts.ingest._slavonic import glagolitic_to_cyrillic

log = logging.getLogger(__name__)

SOURCE_ID = "torot"

#: Syntacticus treebank data, tag 20230428.
COMMIT = "525cee4fb40590d7d514376c11acaed1bdd91c15"
REPO_URL = "https://github.com/syntacticus/syntacticus-treebank-data"
RAW_URL = "https://raw.githubusercontent.com/syntacticus/syntacticus-treebank-data/{commit}/torot/{name}.xml"

LICENSE_TEXT = "CC BY-NC-SA 4.0"

#: TOROT text id → (local id, metadata). Dates are of the translation or
#: composition, not the manuscript.
WORKS: dict[str, dict] = {
    "psal-sin": {
        "local_id": "ps",
        "title": "Psalms",
        "genre": "scripture",
        "author": None,
        "date_composed": 885,
        "date_range": (863, 950),
        "date_confidence": "approximate",
        "edition": ("Psalterium Sinaiticum (Sinai, Sin. slav. 38, Glagolitic, 11th c.), "
                    "after S. N. Sever'janov, Sinajskaja psaltyr' (Petrograd 1922), "
                    "Psalms 138–151 after Mareš 1997; TOROT (Tromsø Old Russian and OCS "
                    "Treebank), Syntacticus release 20230428, Cyrillic transcription. "
                    "Psalm 1 is lost."),
    },
    "kiev-mis": {
        "local_id": "kievmis",
        "prefix": "KievMis",
        "title": "Kiev Missal",
        "genre": "liturgical",
        "author": None,
        "date_composed": 950,
        "date_range": (900, 1000),
        "date_confidence": "approximate",
        "edition": ("Kiev Missal (Kiev Folia, Glagolitic, 10th c.): masses of a Latin-rite "
                    "sacramentary in Slavonic; TOROT (Tromsø Old Russian and OCS Treebank), "
                    "Syntacticus release 20230428, Cyrillic transcription."),
    },
    "euch": {
        "local_id": "euch",
        "prefix": "Euch",
        "title": "Euchologium Sinaiticum (selection)",
        "genre": "liturgical",
        "author": None,
        "date_composed": 950,
        "date_range": (885, 1050),
        "date_confidence": "uncertain",
        "edition": ("Euchologium Sinaiticum (Sinai, Sin. slav. 37, Glagolitic, 11th c.): a "
                    "selection of eight prayers (for a vineyard, the grape harvest, new wine, "
                    "a house, a herd, at bedtime, and the confessional prayer), not the whole "
                    "euchologion; TOROT (Tromsø Old Russian and OCS Treebank), Syntacticus "
                    "release 20230428, Cyrillic transcription."),
    },
    "chrabr": {
        "local_id": "chrabr",
        "prefix": "Chrabr",
        "title": "On the Letters",
        "genre": "patristic",
        "author": "Chrabr",
        "date_composed": 900,
        "date_range": (893, 927),
        "date_confidence": "approximate",
        "edition": ("Chrabr the Monk, O pismenech (On the Letters), from the Lavrent'evskij "
                    "sbornik (1348), diacritics removed and superscripts taken down; TOROT "
                    "(Tromsø Old Russian and OCS Treebank), Syntacticus release 20230428."),
    },
}

# Latin letters TOROT typed for Cyrillic look-alikes (``Xрабъра``, ``cр҃це``);
# Chrabr's ``s`` is the numeral ѕ (six).
_LOOKALIKES = str.maketrans({"C": "С", "c": "с", "X": "Х", "x": "х", "s": "ѕ"})
_CYRILLIC_RE = re.compile("[Ѐ-ԯⷠ-ⷿꙀ-ꚟ]")
# A stop with no space after it: a space goes back (not after a dot run, which
# is a lacuna, nor after a bare hyphen, which joins a split word).
_STOP_END_RE = re.compile(r"[.:;·](-*)$")
_DOTS_RE = re.compile(r"\.+")
_SUPPLEMENT_RE = {"[": re.compile(r"\[[^\[\]]*\]"), "(": re.compile(r"\([^()]{1,40}\)")}
_PSALTER_NOTE_BRACKET_RE = re.compile(r"\[[^\[\]]{1,10}\]")
_DIGIT_RE = re.compile(r"[0-9]")

Span = tuple[int, int, str]
Segment = tuple[str, "str | None"]
#: The kind of a segment that separates sentences: a space, unless the text
#: already ends in one.
SEP = "sep"


class TorotFormatError(ValueError):
    """A TOROT file that doesn't have the structure this ingestor expects."""


def xml_path(output_dir: Path, name: str) -> Path:
    return output_dir / "_cache" / "torot" / COMMIT[:10] / f"{name}.xml"


def fetch(output_dir: Path, name: str, force: bool = False) -> Path:
    """The TOROT file *name* at the pinned commit (downloaded once)."""
    url = RAW_URL.format(commit=COMMIT, name=name)
    return download_file(url, xml_path(output_dir, name), etag_cache=False, force=force)


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

def clean(text: str) -> str:
    """Unicode clean-up of a TOROT string: Glagolitic → Cyrillic, paerok, U+FFFC."""
    return glagolitic_to_cyrillic(text.replace("￼", "").replace("ʼ", "ꙿ"))


def clean_form(form: str) -> str:
    """A token's form, cleaned, with Latin look-alikes in Cyrillic words made Cyrillic."""
    form = clean(form)
    if _CYRILLIC_RE.search(form):  # titlo-only tokens (``҃s``) count: U+0483 is Cyrillic
        form = form.translate(_LOOKALIKES)
    return form


def _dot_segments(text: str, min_run: int) -> list[Segment]:
    """*text* cut into segments, runs of at least *min_run* dots marked ``lacuna``."""
    out: list[Segment] = []
    pos = 0
    for m in _DOTS_RE.finditer(text):
        if len(m.group()) < min_run:
            continue
        if m.start() > pos:
            out.append((text[pos:m.start()], None))
        out.append((m.group(), "lacuna"))
        pos = m.end()
    if pos < len(text):
        out.append((text[pos:], None))
    return out


def token_segments(tokens: list[etree._Element]) -> list[tuple[str, list[Segment]]]:
    """The segments of a run of tokens, as ``(citation part, segments)`` per token."""
    out: list[tuple[str, list[Segment]]] = []
    for i, tok in enumerate(tokens):
        before = clean(tok.get("presentation-before") or "")
        form = clean_form(tok.get("form") or "")
        after = clean(tok.get("presentation-after") or "")
        if i + 1 < len(tokens) and after and not after[-1].isspace():
            nxt = tokens[i + 1].get("presentation-before") or ""
            if _STOP_END_RE.search(after) and not re.fullmatch(r"\.{2,}", after) \
                    and not nxt[:1].isspace():
                after += " "
        segs = _dot_segments(before, 2) + _dot_segments(form, 1) + _dot_segments(after, 3)
        cp = (tok.get("citation-part") or "").lstrip("﻿").strip()
        out.append((cp, segs))
    return out


def assemble(segments: Iterable[Segment]) -> tuple[str, list[Span]]:
    """Join segments into a unit text with its spans, stripped, adjacent spans merged."""
    text = ""
    spans: list[Span] = []
    for seg, kind in segments:
        if kind == SEP:
            if text and not text[-1].isspace():
                text += " "
            continue
        if kind is not None and seg:
            if spans and spans[-1][1] == len(text) and spans[-1][2] == kind:
                spans[-1] = (spans[-1][0], len(text) + len(seg), kind)
            else:
                spans.append((len(text), len(text) + len(seg), kind))
        text += seg
    # TOROT's spacing is kept as written; only the ends of the unit are
    # trimmed, and each span is trimmed to start and end on a non-space.
    lead = len(text) - len(text.lstrip())
    stripped = text.strip()
    out: list[Span] = []
    for s, e, k in spans:
        s, e = max(s - lead, 0), min(e - lead, len(stripped))
        while s < e and stripped[s].isspace():
            s += 1
        while e > s and stripped[e - 1].isspace():
            e -= 1
        if s < e:
            out.append((s, e, k))
    return stripped, out


def _overlaps(spans: list[Span], start: int, end: int) -> bool:
    return any(s < end and start < e for s, e, _ in spans)


def bracket_spans(text: str, spans: list[Span], opener: str, kind: str,
                  pattern: re.Pattern[str] | None = None) -> list[Span]:
    """*spans* plus a *kind* span per bracket pair of *opener*, and each unpaired bracket.

    A pair around a lacuna marks its two brackets alone, so the lacuna keeps
    its own span.
    """
    closer = {"[": "]", "(": ")"}[opener]
    added: list[Span] = []
    paired: set[int] = set()
    for m in (pattern or _SUPPLEMENT_RE[opener]).finditer(text):
        paired.update((m.start(), m.end() - 1))
        if _overlaps(spans, m.start(), m.end()):
            added += [(m.start(), m.start() + 1, kind), (m.end() - 1, m.end(), kind)]
        else:
            added.append((m.start(), m.end(), kind))
    if opener == "[":  # round brackets: an unpaired ")" is the Psalter's punctuation
        for i, ch in enumerate(text):
            if ch in (opener, closer) and i not in paired and not _overlaps(spans, i, i + 1):
                added.append((i, i + 1, kind))
    return sorted(spans + [s for s in added if not _overlaps(spans, s[0], s[1])])


def unit_record(ref: str, segments: list[Segment], *, psalter: bool) -> dict | None:
    """A raw unit ``{"ref", "text"[, "editorial"]}``, or None if it has no text."""
    text, spans = assemble(segments)
    if not text:
        return None
    if psalter:
        spans = bracket_spans(text, spans, "(", "supplement")
        spans = bracket_spans(text, spans, "[", "note", _PSALTER_NOTE_BRACKET_RE)
    else:
        spans = bracket_spans(text, spans, "[", "supplement")
    record: dict = {"ref": ref, "text": text}
    if spans:
        record["editorial"] = [[s, e, k] for s, e, k in spans]
    return record


# ---------------------------------------------------------------------------
# Works
# ---------------------------------------------------------------------------

def _sentences(div: etree._Element) -> list[list[etree._Element]]:
    """The div's sentences as lists of tokens with a form (empty tokens dropped)."""
    out = []
    for sent in div.iter("sentence"):
        toks = [t for t in sent.iter("token") if t.get("form") is not None]
        if toks:
            out.append(toks)
    return out


def _sentence_segments(tokens: list[etree._Element]) -> list[Segment]:
    """A sentence's segments, followed by the space that separates it from the next."""
    return [s for _, ss in token_segments(tokens) for s in ss] + [(" ", SEP)]


def psalter_verses(root: etree._Element) -> list[dict]:
    """The Psalter's verses, ``Ps.N.V`` in document order."""
    order: list[str] = []
    verses: dict[str, list[Segment]] = {}
    for div in root.iter("div"):
        for toks in _sentences(div):
            per_token = token_segments(toks)
            text = "".join(s for _, ss in per_token for s, _ in ss)
            note = _DIGIT_RE.search(text) is not None
            for cp, segs in per_token:
                if not re.fullmatch(r"\d+\.\d+", cp):
                    raise TorotFormatError(f"psal-sin: bad citation-part {cp!r}")
                if cp not in verses:
                    if order and order[-1] != cp and cp in order:
                        log.warning("psal-sin: verse %s is not contiguous", cp)
                    order.append(cp)
                    verses[cp] = []
                if note:
                    segs = [(s, "note") for s, _ in segs]
                verses[cp].extend(segs)
            last = per_token[-1][0]
            verses[last].append((" ", SEP))
    out = []
    for cp in order:
        rec = unit_record(f"Ps.{cp}", verses[cp], psalter=True)
        if rec:
            out.append(rec)
    return out


def _is_rubric(tokens: list[etree._Element]) -> bool:
    """A Kiev Missal rubric: every letter of the sentence is a capital."""
    letters = [c for t in tokens for c in clean_form(t.get("form") or "") if c.isalpha()]
    return bool(letters) and all(c.isupper() for c in letters)


def prose_units(root: etree._Element, prefix: str, *, split_rubrics: bool) -> list[dict]:
    """Units of a prose text: per div ``{prefix}.{n}`` (its rubric or title) and
    ``{prefix}.{n}.{m}``.

    The first sentence of a div is its heading; with *split_rubrics* (the Kiev
    Missal) every run of all-caps rubric sentences is a unit of its own, and
    the heading is the div's leading rubrics.
    """
    out: list[dict] = []
    for n, div in enumerate(root.iter("div"), start=1):
        sents = _sentences(div)
        if not sents:
            log.error("%s: div %s has no text", prefix, div.get("id"))
            continue
        groups: list[list[list[etree._Element]]] = []
        if split_rubrics:
            prev = None
            for toks in sents:
                rubric = _is_rubric(toks)
                if prev is None or rubric != prev:
                    groups.append([])
                groups[-1].append(toks)
                prev = rubric
            if not _is_rubric(groups[0][0]):
                groups.insert(0, [])  # no heading: the units start at .1
        else:
            groups = [[sents[0]], sents[1:]]
        for m, group in enumerate(groups):
            if not group:
                continue
            ref = f"{prefix}.{n}" if m == 0 else f"{prefix}.{n}.{m}"
            segs = [s for toks in group for s in _sentence_segments(toks)]
            rec = unit_record(ref, segs, psalter=False)
            if rec:
                out.append(rec)
    return out


def _check_license(root: etree._Element, name: str) -> None:
    lic = (root.findtext(".//source/license") or "").strip()
    if lic != LICENSE_TEXT:
        raise TorotFormatError(f"{name}: licence {lic!r}, expected {LICENSE_TEXT!r}")


def parse(name: str, xml: Path) -> tuple[str, list[dict]]:
    """``(units key, units)`` of the TOROT text *name* from its XML file."""
    root = etree.parse(str(xml), etree.XMLParser(resolve_entities=False, no_network=True)).getroot()
    _check_license(root, name)
    lang = root.find(".//source").get("language")
    if lang != "chu":
        raise TorotFormatError(f"{name}: language {lang!r}, expected 'chu'")
    if name == "psal-sin":
        return "verses", psalter_verses(root)
    meta = WORKS[name]
    return "paragraphs", prose_units(root, meta["prefix"], split_rubrics=name == "kiev-mis")


def make_work(name: str) -> Work:
    meta = WORKS[name]
    return Work(
        work_id=f"{SOURCE_ID}/{meta['local_id']}",
        source_id=SOURCE_ID,
        title=meta["title"],
        author=meta["author"],
        date_composed=meta["date_composed"],
        date_range=meta["date_range"],
        date_confidence=meta["date_confidence"],
        genre=meta["genre"],
        language="chu",
        tradition="slavonic",
        license="cc-by-nc-sa-4.0",
        provenance_url=f"{REPO_URL}/blob/{COMMIT}/torot/{name}.xml",
        edition=meta["edition"],
    )


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download the four TOROT texts at the pinned commit and write one raw file each."""
    source_dir = output_dir / SOURCE_ID
    source_dir.mkdir(parents=True, exist_ok=True)
    works: list[Work] = []
    for name, meta in WORKS.items():
        out_file = source_dir / f"{meta['local_id']}.json"
        if out_file.exists() and not force:
            data = json.loads(out_file.read_text(encoding="utf-8"))
            works.append(Work(**data["work"]))
            continue
        xml = fetch(output_dir, name, force=force)
        key, units = parse(name, xml)
        if not units:
            log.error("torot %s: no units parsed from %s", name, xml)
            continue
        work = make_work(name)
        record = {"work": work.model_dump(), key: units}
        out_file.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        marked = sum(1 for u in units if "editorial" in u)
        log.info("torot %s: %d units (%d with editorial spans) → %s",
                 name, len(units), marked, out_file)
        works.append(work)
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
