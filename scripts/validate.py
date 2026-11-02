"""
QC validation checks on normalized and chunk data.

Outputs data/validation_report.json.

Checks (10 groups):
1. Schema integrity — files parse cleanly as JSON lists of Chunk objects
2. Text quality — no empty/short/HTML/mojibake/low-alpha text, no duplicated
   leading section number
3. Language/script consistency — valid ISO 639-3 codes, correct Unicode blocks
4. Canonical reference integrity — format, no duplicates, sequential chunk_index
5. ID uniqueness — no duplicate work_ids or chunk_ids globally
6. Date plausibility — date range, out_of_period consistency
7. Cross-reference integrity — work_ids exist in _works.jsonl,
   translation_of targets exist, groups ≥2
8. Metadata completeness — author, title, license, provenance_url; every
   author string resolves in the author index and author_ids is up to date
9. Scripture coverage — books present/missing per translation
10. Chunk count report — totals by Work.genre (from _works.jsonl) and language

The corpus is read one work file at a time, so memory is one work plus small
aggregates (#374); the report is the same as from one pass over all chunks.

Exits 1 when any check fails (errors); warnings don't fail.  CI and the
pre-push hook run it with ``--if-changed REF`` (#130): it then runs only when
a file it reads changed since *REF*, i.e. ``data/normalized/``, the curated
data in ``patristica/data/``, or its own code (its import closure, from
``patristica.fingerprint``).  ``--summary FILE`` appends the error and warning
counts as Markdown (CI passes ``$GITHUB_STEP_SUMMARY``).
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from tqdm import tqdm

from patristica import console, editorial, fingerprint
from patristica.authors import UnknownAuthorError, resolve_author, work_author_birth_year
from patristica.mojibake import mojibake_runs
from patristica.period import AUTHOR_BORN_BEFORE, COMPOSED_BY
from patristica.section_numbers import STRAY_SCRIPT_DIGIT_RE, leading_section_number

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_LANGUAGES = {
    "grc", "lat", "hbo", "syc", "cop", "gez", "hye", "got", "chu", "arb", "oge", "sga", "ang", "goh", "osx", "eng",
}

# Unicode ranges (start, end inclusive) for non-Latin scripts
SCRIPT_RANGES: dict[str, list[tuple[int, int]]] = {
    "grc": [(0x0370, 0x03FF), (0x1F00, 0x1FFF)],
    "hbo": [(0x0590, 0x05FF)],
    "syc": [(0x0700, 0x074F)],
    "hye": [(0x0530, 0x058F)],
    "gez": [(0x1200, 0x137F)],
    # Coptic may use Coptic block or Greek-script; accept either
    "cop": [(0x2C80, 0x2CFF), (0x0370, 0x03FF)],
    "got": [(0x10330, 0x1034F)],
    # Church Slavonic is stored in Cyrillic (Glagolitic is converted at ingest,
    # #330), so Glagolitic text counts as the wrong script here. Cyrillic,
    # Cyrillic Supplement and Extended-A/B/C, plus combining marks (titla are
    # U+0483–0487 in the Cyrillic block; generic accents U+0300–036F).
    "chu": [
        (0x0400, 0x052F),
        (0x1C80, 0x1C8F),
        (0x2DE0, 0x2DFF),
        (0xA640, 0xA69F),
        (0x0300, 0x036F),
    ],
    # Arabic (#83): the Arabic block, Supplement, Extended-A and the
    # presentation forms (folded to base letters, but some sources keep them).
    "arb": [(0x0600, 0x06FF), (0x0750, 0x077F), (0x08A0, 0x08FF), (0xFB50, 0xFDFF), (0xFE70, 0xFEFF)],
    # Old Irish (#225): Latin letters with length marks (Latin-1, Extended-A/B),
    # the dotted letters of the editions (ḟ ṡ ṁ ṅ, Latin Extended Additional),
    # combining marks and the scribal abbreviations ⁊ (ocus) and ↄ (con).
    "sga": [
        (0x0041, 0x005A),
        (0x0061, 0x007A),
        (0x00C0, 0x024F),
        (0x1E00, 0x1EFF),
        (0x0300, 0x036F),
        (0x204A, 0x204A),
        (0x2184, 0x2184),
    ],
    # Old Georgian (#222): stored in Mkhedruli as the sources have it, with its
    # archaic letters (U+10F1–10F6, in the Georgian block). Asomtavruli
    # (U+10A0–10C5) and Nuskhuri (Georgian Supplement) are the same alphabet
    # in the older scripts, and Mtavruli its capitals; fold() maps them all
    # onto Mkhedruli, so they count as Georgian too.
    "oge": [(0x10A0, 0x10FF), (0x2D00, 0x2D2F), (0x1C90, 0x1CBF)],
}

_COLLECTION_TITLE_RE = re.compile(
    r"ANTE-NICENE|NICENE AND POST-NICENE|PATROLOGIA LATINA|PATROLOGIA GRAECA"
    r"|First Thousand Years|POST-NICENE FATHERS",
    re.IGNORECASE,
)
_HTML_TAG_RE = re.compile(r"<[a-zA-Z/]")
_REPLACEMENT_CHAR = "�"

DATE_MIN = -800
DATE_MAX = 1200
MIN_TEXT_LEN = 10
MIN_ALPHA_RATIO = 0.25
MIN_SCRIPT_RATIO = 0.10
MAX_EXAMPLES = 5

CheckResult = dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _script_class(ranges: list[tuple[int, int]]) -> re.Pattern[str]:
    """A regex matching runs of characters in *ranges*."""
    return re.compile("[" + "".join(f"{chr(lo)}-{chr(hi)}" for lo, hi in ranges) + "]+")


#: ``SCRIPT_RANGES`` as regexes: counting matches is ~25× faster than a loop
#: over code points (#374).
_SCRIPT_RES = {lang: _script_class(ranges) for lang, ranges in SCRIPT_RANGES.items()}


def _script_ratio(text: str, script: re.Pattern[str]) -> float:
    """The share of *text* in *script* (a ``_SCRIPT_RES`` value)."""
    if not text:
        return 0.0
    return sum(map(len, script.findall(text))) / len(text)


def _alpha_ratio(text: str) -> float:
    if not text:
        return 0.0
    return sum(map(str.isalpha, text)) / len(text)


def _result(severity: str, violations: list[str], note: str = "") -> CheckResult:
    status = "pass" if not violations else ("fail" if severity == "error" else "warn")
    r: CheckResult = {
        "status": status,
        "severity": severity,
        "violation_count": len(violations),
        "examples": violations[:MAX_EXAMPLES],
    }
    if note:
        r["note"] = note
    return r


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

class ValidationInputError(Exception):
    """Raised when an input validate.py needs (e.g. ``_works.jsonl``) is missing or malformed."""


WORKS_MANIFEST = "_works.jsonl"
UNKNOWN_GENRE = "unknown"


def _load_works(data_dir: Path) -> list[dict]:
    """Return every ``Work`` record in ``normalized/_works.jsonl``, one per line.

    The manifest is keyed by normalized file path, so a work_id that appears
    under two paths shows up twice here (see the duplicate_work_ids check).
    """
    manifest_path = data_dir / "normalized" / WORKS_MANIFEST
    if not manifest_path.exists():
        raise ValidationInputError(
            f"{manifest_path} not found; run scripts.normalize to build it"
        )
    works: list[dict] = []
    with manifest_path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                work = json.loads(line)["work"]
                work["work_id"]
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise ValidationInputError(
                    f"{manifest_path}:{lineno}: malformed manifest line ({exc!r})"
                ) from exc
            works.append(work)
    return works


def _load_work_records(data_dir: Path) -> dict[str, dict]:
    """Return ``work_id → Work record`` from ``normalized/_works.jsonl``.

    This manifest is the authoritative source of ``Work.genre`` and
    ``Work.source_id``; the path prefix of a normalized file is a source-id
    namespace and need not match the genre of the works in it.
    """
    return _records_by_id(_load_works(data_dir))


def _records_by_id(works: list[dict]) -> dict[str, dict]:
    return {w["work_id"]: w for w in works}


def _genre_of(work_id: str, work_records: dict[str, dict]) -> str:
    """``Work.genre`` for *work_id*, or ``UNKNOWN_GENRE`` if it has no manifest record."""
    work = work_records.get(work_id)
    if work is None:
        return UNKNOWN_GENRE
    return work.get("genre") or UNKNOWN_GENRE


def _chunk_files(data_dir: Path) -> list[Path]:
    """The normalized work files, in the order validate reads them."""
    normalized_dir = data_dir / "normalized"
    return sorted(p for p in normalized_dir.rglob("*.json") if not p.name.startswith("_"))


def _read_chunk_file(path: Path) -> list[dict] | None:
    """The chunks in one normalized work file, or ``None`` if it doesn't parse."""
    try:
        with path.open() as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        log.error("JSON parse error in %s: %s", path, exc)
        return None
    if not isinstance(data, list):
        log.warning("Expected list in %s, got %s", path, type(data).__name__)
        return None
    return data


def _load_chunks(data_dir: Path) -> tuple[list[dict], list[str]]:
    """Returns (chunks, parse_error_paths) for the whole corpus at once.

    ``main`` reads one file at a time instead (#374); this is for small trees.
    """
    chunks: list[dict] = []
    parse_errors: list[str] = []
    for path in _chunk_files(data_dir):
        data = _read_chunk_file(path)
        if data is None:
            parse_errors.append(str(path))
        else:
            chunks.extend(data)
    return chunks, parse_errors


# ---------------------------------------------------------------------------
# Streaming (#374)
#
# Each check group below is a class that sees the corpus one work file at a
# time (``add``) and builds its result at the end (``result``), so validate
# holds one work in memory, not the corpus.  The ``_check_*`` functions run a
# group on one list of chunks.
# ---------------------------------------------------------------------------

class _Check:
    """A group of checks, fed the chunks of one work file at a time."""

    def add(self, chunks: list[dict]) -> None:
        raise NotImplementedError

    def result(self) -> dict[str, Any]:
        raise NotImplementedError

    def run(self, chunks: list[dict]) -> dict[str, Any]:
        self.add(chunks)
        return self.result()


#: A violation with its sort key: the corpus positions of the chunks it is
#: first reported for, which restore the order of one pass over the corpus.
_Ordered = tuple[tuple[int, ...], str]
#: Reads file number *i* of the run (in ``add`` order) back.
Reload = Callable[[int], list[dict]]


class _PerKey:
    """Violations that need every chunk sharing a key at once.

    The key is a work id (refs within a work) or a chunk-id prefix (chunk-id
    uniqueness).  Each normalized file is one work, so a file's keys are
    checked when it is added and only their violations are kept.  A key found
    again in a later file is checked again in ``violations`` from all its
    files, read back with *reload*.  ``check(key, items)`` gets the key's
    ``(position, chunk)`` items in corpus order and returns ordered
    violations by check name.
    """

    def __init__(
        self,
        key: Callable[[dict], str],
        check: Callable[[str, list[tuple[int, dict]]], dict[str, list[_Ordered]]],
        names: tuple[str, ...],
        reload: Reload | None,
    ) -> None:
        self._key, self._check, self._names, self._reload = key, check, names, reload
        self._seen = 0
        self._starts: list[int] = []
        self._files: dict[str, list[int]] = {}
        self._found: dict[str, dict[str, list[_Ordered]]] = {}

    def _group(self, chunks: list[dict], start: int, keys: set[str] | None = None
               ) -> dict[str, list[tuple[int, dict]]]:
        groups: defaultdict[str, list[tuple[int, dict]]] = defaultdict(list)
        for i, c in enumerate(chunks):
            k = self._key(c)
            if keys is None or k in keys:
                groups[k].append((start + i, c))
        return groups

    def add(self, chunks: list[dict]) -> None:
        file_no = len(self._starts)
        self._starts.append(self._seen)
        for k, items in self._group(chunks, self._seen).items():
            files = self._files.setdefault(k, [])
            files.append(file_no)
            if len(files) == 1:
                self._found[k] = self._check(k, items)
        self._seen += len(chunks)

    def violations(self) -> dict[str, list[str]]:
        split = {k for k, files in self._files.items() if len(files) > 1}
        if split:
            if self._reload is None:
                raise ValueError("a key spans several adds but there is no reload")
            log.debug("%d keys span several files; re-checking them", len(split))
            items: defaultdict[str, list[tuple[int, dict]]] = defaultdict(list)
            for file_no in sorted({n for k in split for n in self._files[k]}):
                chunks = self._reload(file_no)
                for k, its in self._group(chunks, self._starts[file_no], split).items():
                    items[k].extend(its)
            for k, its in items.items():
                self._found[k] = self._check(k, its)
        return {
            name: [msg for _, msg in sorted(
                v for found in self._found.values() for v in found.get(name, []))]
            for name in self._names
        }


# ---------------------------------------------------------------------------
# Check group 1: Schema integrity (parse errors already collected in load)
# ---------------------------------------------------------------------------

def _check_schema(parse_errors: list[str]) -> dict[str, CheckResult]:
    return {
        "files_unparseable": _result("error", parse_errors),
    }


# ---------------------------------------------------------------------------
# Check group 2: Text quality
# ---------------------------------------------------------------------------

class _TextQuality(_Check):
    def __init__(self) -> None:
        self.empty: list[str] = []
        self.short: list[str] = []
        self.html: list[str] = []
        self.replacement: list[str] = []
        self.low_alpha: list[str] = []
        self.mojibake: list[str] = []
        self.bad_spans: list[str] = []

    def add(self, chunks: list[dict]) -> None:
        for c in chunks:
            cid = c.get("chunk_id", "?")
            text = c.get("text", "")
            if c.get(editorial.KEY):
                try:
                    editorial.check(text, c[editorial.KEY], cid)
                except editorial.EditorialError as exc:
                    self.bad_spans.append(str(exc))
            if not text or not text.strip():
                self.empty.append(cid)
            elif len(text) < MIN_TEXT_LEN:
                self.short.append(cid)
            if text and _HTML_TAG_RE.search(text):
                self.html.append(cid)
            if text and _REPLACEMENT_CHAR in text:
                self.replacement.append(cid)
            runs = mojibake_runs(text) if text else []
            if runs:
                self.mojibake.append(f"{cid} ({runs[0]!r})")
            if text and text.strip() and _alpha_ratio(text) < MIN_ALPHA_RATIO:
                self.low_alpha.append(cid)

    def result(self) -> dict[str, CheckResult]:
        return {
            "text_empty": _result("error", self.empty),
            "text_too_short": _result("warning", self.short, f"< {MIN_TEXT_LEN} chars"),
            "text_has_html_tags": _result(
                "warning", self.html, "many are OCR artifacts in OGLT PL/OGPG/Gallican"),
            "text_has_replacement_char": _result(
                "warning", self.replacement, "U+FFFD indicates encoding failure"),
            "editorial_spans_invalid": _result(
                "error", self.bad_spans,
                "editorial spans (#236) must fit the chunk text: re-run normalize"),
            "text_low_alpha_ratio": _result(
                "warning", self.low_alpha, f"< {MIN_ALPHA_RATIO:.0%} alphabetic chars"),
            "text_has_mojibake": _result(
                "warning", self.mojibake,
                "double-encoded UTF-8 (\"Î»á½¹Î³Î¿Î½\" for \"λόγον\"): repair at ingest with "
                "patristica.mojibake.repair_double_utf8 (#124)",
            ),
        }


def _check_text_quality(chunks: list[dict]) -> dict[str, CheckResult]:
    return _TextQuality().run(chunks)


class _SectionNumbers(_Check):
    """Section numbers and superscript digits left in chunk text.

    ``text_starts_with_section_number``: prose chunks whose text still starts
    with the ref's own section number, in any form ``leading_section_number``
    knows (plain, glued, superscript; #30, #121).
    ``text_has_superscript_digits``: any chunk (scripture included) with a
    superscript or subscript digit anywhere.  Normalize strips only a leading
    one that equals the ref, so the rest need a person to look at them.

    ``normalize.py`` strips leading section numbers, so a hit in the first
    check means the normalized data predates that step or the text reached the
    corpus some other way.  It skips scripture: a verse may start with a numeral.
    """

    def __init__(self, work_records: dict[str, dict]) -> None:
        self.work_records = work_records
        self.dup_number: list[str] = []
        self.stray: list[str] = []

    def add(self, chunks: list[dict]) -> None:
        for c in chunks:
            text = c.get("text", "")
            m = STRAY_SCRIPT_DIGIT_RE.search(text)
            if m:
                snippet = text[max(0, m.start() - 15) : m.end() + 15]
                self.stray.append(f"{c.get('chunk_id', '?')} ({snippet!r})")
            entry = self.work_records.get(c.get("work_id", ""), {})
            source_id = entry.get("source_id", "")
            if entry.get("genre") == "scripture":
                continue
            prefix = leading_section_number(
                c.get("text", ""), c.get("canonical_ref", ""), c.get("language"), source_id
            )
            if prefix:
                self.dup_number.append(f"{c.get('chunk_id', '?')} ({prefix.strip()!r})")

    def result(self) -> dict[str, CheckResult]:
        return {
            "text_starts_with_section_number": _result(
                "warning", self.dup_number,
                "leading number repeats the ref's last segment; re-run normalize"
            ),
            "text_has_superscript_digits": _result(
                "warning",
                self.stray,
                "superscript/subscript digits left in the text: footnote markers, OCR noise, "
                "mojibake, or a damaged verse number that does not equal the ref (#121)",
            ),
        }


def _check_section_numbers(
    chunks: list[dict], work_records: dict[str, dict]
) -> dict[str, CheckResult]:
    return _SectionNumbers(work_records).run(chunks)


# ---------------------------------------------------------------------------
# Check group 3: Language/script consistency
# ---------------------------------------------------------------------------

class _LanguageScript(_Check):
    def __init__(self) -> None:
        self.invalid_lang: list[str] = []
        self.wrong_script: list[str] = []
        self.ascii_for_non_latin: list[str] = []

    def add(self, chunks: list[dict]) -> None:
        for c in chunks:
            cid = c.get("chunk_id", "?")
            lang = c.get("language", "")
            text = c.get("text", "")
            if lang not in VALID_LANGUAGES:
                self.invalid_lang.append(f"{cid} (lang={lang!r})")
            if lang in SCRIPT_RANGES and text:
                ratio = _script_ratio(text, _SCRIPT_RES[lang])
                if ratio < MIN_SCRIPT_RATIO:
                    label = f"{cid} (lang={lang}, script_ratio={ratio:.2f})"
                    if text.isascii():
                        self.ascii_for_non_latin.append(label)
                    else:
                        self.wrong_script.append(label)

    def result(self) -> dict[str, CheckResult]:
        return {
            "invalid_language_code": _result("error", self.invalid_lang),
            "wrong_script_for_language": _result("warning", self.wrong_script),
            "non_latin_lang_but_ascii_text": _result("warning", self.ascii_for_non_latin),
        }


def _check_language_script(chunks: list[dict]) -> dict[str, CheckResult]:
    return _LanguageScript().run(chunks)


# ---------------------------------------------------------------------------
# Check group 4: Canonical reference integrity
# ---------------------------------------------------------------------------

def _refs_within_work(wid: str, items: list[tuple[int, dict]]) -> dict[str, list[_Ordered]]:
    """Duplicate refs and a non-sequential chunk_index in one work."""
    first = items[0][0]
    refs: dict[str, list[int]] = {}  # ref → [position of its first chunk, count]
    for pos, c in items:
        entry = refs.setdefault(c.get("canonical_ref", ""), [pos, 0])
        entry[1] += 1
    dup_refs = [((first, pos), f"{wid}: {ref!r} ×{cnt}")
                for ref, (pos, cnt) in refs.items() if cnt > 1]
    indices = sorted(c.get("chunk_index", -1) for _, c in items)
    bad_index = ([] if indices == list(range(len(indices)))
                 else [((first,), f"{wid} (got {indices[:5]}…)")])
    return {"dup_refs": dup_refs, "bad_index": bad_index}


class _CanonicalRefs(_Check):
    def __init__(self, work_records: dict[str, dict], reload: Reload | None = None) -> None:
        from patristica.versify import is_derived_ref
        from scripts.ingest._scripture_meta import ALL_BOOKS
        self.is_derived_ref = is_derived_ref
        self.all_books = ALL_BOOKS
        self.scripture_work_ids = {
            wid for wid in work_records if _genre_of(wid, work_records) == "scripture"
        }
        self.empty_ref: list[str] = []
        self.bad_scripture: list[str] = []
        self.bad_prose: list[str] = []
        self.within_work = _PerKey(
            lambda c: c.get("work_id", ""), _refs_within_work, ("dup_refs", "bad_index"), reload
        )

    def add(self, chunks: list[dict]) -> None:
        self.within_work.add(chunks)
        for c in chunks:
            cid = c.get("chunk_id", "?")
            ref = c.get("canonical_ref", "")
            wid = c.get("work_id", "")
            if not ref or not ref.strip():
                self.empty_ref.append(cid)
                continue
            parts = ref.split(".")
            if wid in self.scripture_work_ids and self.is_derived_ref(ref):
                # A unit split into derived verses (UNVERSIFIED_UNITS, #129): the
                # ref is a verse ref plus ``.sN``.
                parts = parts[:-1]
            if wid in self.scripture_work_ids:
                if len(parts) != 3 or parts[0] not in self.all_books:
                    self.bad_scripture.append(f"{cid} ({ref!r})")
            else:
                if len(parts) < 2:
                    self.bad_prose.append(f"{cid} ({ref!r})")

    def result(self) -> dict[str, CheckResult]:
        within = self.within_work.violations()
        return {
            "canonical_ref_empty": _result("error", self.empty_ref),
            "scripture_ref_malformed": _result("error", self.bad_scripture),
            "prose_ref_malformed": _result("warning", self.bad_prose),
            "duplicate_canonical_ref_within_work": _result("error", within["dup_refs"]),
            "non_sequential_chunk_index": _result("warning", within["bad_index"]),
        }


def _check_canonical_refs(
    chunks: list[dict], work_records: dict[str, dict]
) -> dict[str, CheckResult]:
    return _CanonicalRefs(work_records).run(chunks)


# ---------------------------------------------------------------------------
# Check group 5: ID uniqueness
# ---------------------------------------------------------------------------

def _chunk_id_prefix(chunk: dict) -> str:
    """The part of a chunk id before ``#``: equal ids have equal prefixes."""
    return chunk.get("chunk_id", "").split("#", 1)[0]


def _duplicate_chunk_ids(prefix: str, items: list[tuple[int, dict]]) -> dict[str, list[_Ordered]]:
    ids: dict[str, list[int]] = {}  # chunk id → [position of its first chunk, count]
    for pos, c in items:
        entry = ids.setdefault(c.get("chunk_id", ""), [pos, 0])
        entry[1] += 1
    return {"dup_chunks": [((pos,), f"{cid} ×{cnt}") for cid, (pos, cnt) in ids.items() if cnt > 1]}


class _IdUniqueness(_Check):
    def __init__(self, works: list[dict], reload: Reload | None = None) -> None:
        self.works = works
        self.chunk_ids = _PerKey(_chunk_id_prefix, _duplicate_chunk_ids, ("dup_chunks",), reload)

    def add(self, chunks: list[dict]) -> None:
        self.chunk_ids.add(chunks)

    def result(self) -> dict[str, CheckResult]:
        work_id_counts = Counter(w.get("work_id", "") for w in self.works)
        dup_works = [f"{wid} ×{cnt}" for wid, cnt in work_id_counts.items() if cnt > 1]
        return {
            "duplicate_work_ids": _result("error", dup_works),
            "duplicate_chunk_ids": _result("error", self.chunk_ids.violations()["dup_chunks"]),
        }


def _check_id_uniqueness(
    works: list[dict], chunks: list[dict]
) -> dict[str, CheckResult]:
    return _IdUniqueness(works).run(chunks)


# ---------------------------------------------------------------------------
# Check group 6: Date plausibility (checked on chunks, which carry date fields)
# ---------------------------------------------------------------------------

def _author_birth_years(work_records: dict[str, dict]) -> dict[str, int | None]:
    """``work_id → period birth year`` of its authors (``None`` if unknown)."""
    births: dict[str, int | None] = {}
    for wid, w in work_records.items():
        try:
            births[wid] = work_author_birth_year(w.get("author_ids") or [])
        except KeyError:  # an id not in the index; reported by _check_authors
            births[wid] = None
    return births


class _DatePlausibility(_Check):
    """Date checks on chunks.

    When a chunk's work has authors with a known birth year (author index,
    #82), that year decides ``out_of_period`` (``patristica.period``), so the
    flag is checked against it instead of the composition date.
    """

    def __init__(self, work_records: dict[str, dict] | None = None) -> None:
        self.births = _author_birth_years(work_records or {})
        self.out_of_range: list[str] = []
        self.period_flag_conflict: list[str] = []
        self.period_flag_mismatch: list[str] = []
        self.range_inverted: list[str] = []
        self.date_outside_range: list[str] = []

    def add(self, chunks: list[dict]) -> None:
        for c in chunks:
            cid = c.get("chunk_id", "?")
            dc = c.get("date_composed")
            dr = c.get("date_range")
            flagged = c.get("out_of_period", False)
            birth = self.births.get(c.get("work_id", ""))

            if birth is not None and flagged != (birth >= AUTHOR_BORN_BEFORE):
                self.period_flag_mismatch.append(
                    f"{cid} (out_of_period={flagged}, author born {birth})")

            if dc is not None:
                if not (DATE_MIN <= dc <= DATE_MAX):
                    self.out_of_range.append(f"{cid} (date_composed={dc})")
                # With a known author birth year, the flag was checked against it above.
                if birth is None and flagged and dc <= COMPOSED_BY:
                    self.period_flag_conflict.append(
                        f"{cid} (out_of_period=True, date_composed={dc})")
                if birth is None and not flagged and dc > COMPOSED_BY:
                    self.period_flag_mismatch.append(
                        f"{cid} (out_of_period=False, date_composed={dc})")

            if dr is not None and len(dr) == 2:
                if dr[0] > dr[1]:
                    self.range_inverted.append(f"{cid} (date_range={list(dr)})")
                if dc is not None and (dc < dr[0] - 50 or dc > dr[1] + 50):
                    self.date_outside_range.append(
                        f"{cid} (date_composed={dc}, date_range={list(dr)})"
                    )

    def result(self) -> dict[str, CheckResult]:
        return {
            "date_out_of_range": _result(
                "warning", self.out_of_range, f"expected {DATE_MIN}–{DATE_MAX} CE"),
            "period_flag_date_conflict": _result("error", self.period_flag_conflict),
            "period_flag_mismatch": _result("warning", self.period_flag_mismatch),
            "date_range_inverted": _result("error", self.range_inverted),
            "date_outside_stated_range": _result("warning", self.date_outside_range),
        }


def _check_date_plausibility(
    chunks: list[dict], work_records: dict[str, dict] | None = None
) -> dict[str, CheckResult]:
    return _DatePlausibility(work_records).run(chunks)


# ---------------------------------------------------------------------------
# Check group 7: Cross-reference integrity
# ---------------------------------------------------------------------------

class _CrossReferences(_Check):
    def __init__(self, works: list[dict], work_records: dict[str, dict]) -> None:
        self.works = works
        self.work_id_set = set(work_records.keys())
        self.orphan_chunks: list[str] = []
        self.group_counts: Counter[str] = Counter()

    def add(self, chunks: list[dict]) -> None:
        for c in chunks:
            if c.get("work_id") not in self.work_id_set:
                self.orphan_chunks.append(c.get("chunk_id", "?"))
            if c.get("translation_group_id"):
                self.group_counts[c["translation_group_id"]] += 1

    def result(self) -> dict[str, CheckResult]:
        bad_translation_of = [
            f"{w.get('work_id')} → {w.get('translation_of')}"
            for w in self.works
            if w.get("translation_of") and w.get("translation_of") not in self.work_id_set
        ]
        singleton_groups = [gid for gid, cnt in self.group_counts.items() if cnt < 2]
        return {
            "orphan_chunks": _result(
                "error", self.orphan_chunks, "chunk work_id has no matching Work record"
            ),
            "bad_translation_of": _result(
                "warning", bad_translation_of, "translation_of references unknown work_id"
            ),
            "singleton_translation_groups": _result(
                "warning",
                singleton_groups[:MAX_EXAMPLES],
                f"{len(singleton_groups)} translation_group_ids have only 1 member",
            ),
        }


def _check_cross_references(
    works: list[dict], chunks: list[dict], work_records: dict[str, dict]
) -> dict[str, CheckResult]:
    return _CrossReferences(works, work_records).run(chunks)


class _WorksManifest(_Check):
    """Every chunk's work must have a ``_works.jsonl`` record with a genre."""

    def __init__(self, work_records: dict[str, dict]) -> None:
        self.work_records = work_records
        self.missing_ids: set[str] = set()

    def add(self, chunks: list[dict]) -> None:
        for c in chunks:
            if c.get("work_id", "") not in self.work_records:
                self.missing_ids.add(c.get("work_id", ""))

    def result(self) -> dict[str, CheckResult]:
        missing_ids = sorted(self.missing_ids)
        no_genre = sorted(wid for wid, w in self.work_records.items() if not w.get("genre"))
        if missing_ids:
            log.warning(
                "%d work_ids have chunks but no %s record (counted as genre %r)",
                len(missing_ids), WORKS_MANIFEST, UNKNOWN_GENRE,
            )
        return {
            "work_missing_from_manifest": _result(
                "error", missing_ids,
                f"chunk work_id has no {WORKS_MANIFEST} record; genre counted as {UNKNOWN_GENRE!r}",
            ),
            "work_missing_genre": _result("error", no_genre),
        }


def _check_works_manifest(
    chunks: list[dict], work_records: dict[str, dict]
) -> dict[str, CheckResult]:
    return _WorksManifest(work_records).run(chunks)


# ---------------------------------------------------------------------------
# Check group 8: Metadata completeness
# ---------------------------------------------------------------------------

def _check_metadata_completeness(works: list[dict]) -> dict[str, CheckResult]:
    no_author: list[str] = []
    collection_title: list[str] = []

    for w in works:
        wid = w.get("work_id", "?")
        if not w.get("author"):
            no_author.append(wid)
        title = w.get("title", "")
        if _COLLECTION_TITLE_RE.search(title):
            collection_title.append(f"{wid}: {title!r}")

    return {
        "missing_author": _result(
            "warning", no_author[:MAX_EXAMPLES],
            f"{len(no_author)} works have no author"
        ),
        "collection_name_as_title": _result(
            "warning", collection_title,
            "title is a collection name; individual work title needed"
        ),
    }


def _check_authors(works: list[dict]) -> dict[str, CheckResult]:
    """Every ``Work.author`` resolves in the author index (#82), and the
    manifest's ``author_ids`` matches it (else re-run ``scripts.normalize``)."""
    unresolved: dict[str, list[str]] = defaultdict(list)
    stale: list[str] = []
    for w in works:
        wid = w.get("work_id", "?")
        try:
            ids = resolve_author(w.get("author"))
        except UnknownAuthorError:
            unresolved[w.get("author") or ""].append(wid)
            continue
        if (w.get("author_ids") or []) != ids:
            stale.append(f"{wid}: {w.get('author_ids')} != {ids}")
    return {
        "unresolved_authors": _result(
            "error",
            [
                f"{a!r} ({len(wids)} works, e.g. {wids[0]})"
                for a, wids in sorted(unresolved.items())
            ],
            "add the spelling to patristica/data/authors.csv (aliases) or author_strings.csv",
        ),
        "stale_author_ids": _result(
            "error", stale, "author_ids out of date; re-run scripts.normalize"
        ),
    }


# ---------------------------------------------------------------------------
# Check group 9: Scripture coverage
# ---------------------------------------------------------------------------

class _ScriptureCoverage(_Check):
    def __init__(self, work_records: dict[str, dict]) -> None:
        self.work_records = work_records
        # Book counts per scripture source_id
        self.source_book_counts: defaultdict[str, Counter] = defaultdict(Counter)

    def add(self, chunks: list[dict]) -> None:
        for c in chunks:
            wid = c.get("work_id", "")
            if _genre_of(wid, self.work_records) != "scripture":
                continue
            ref = c.get("canonical_ref", "")
            book = ref.split(".")[0] if "." in ref else ""
            if book:
                sid = self.work_records[wid].get("source_id", "unknown")
                self.source_book_counts[sid][book] += 1

    def result(self) -> dict[str, Any]:
        from scripts.ingest._scripture_meta import PROTESTANT_BOOKS
        protestant_set = set(PROTESTANT_BOOKS)

        coverage: dict[str, dict] = {}
        for sid, book_counts in sorted(self.source_book_counts.items()):
            present = sorted(book_counts.keys())
            missing_protestant = sorted(protestant_set - book_counts.keys())
            coverage[sid] = {
                "books_present": len(present),
                "missing_from_protestant_canon": missing_protestant,
            }

        # Scripture sources with zero chunks
        all_scripture_source_ids = {
            work.get("source_id")
            for wid, work in self.work_records.items()
            if _genre_of(wid, self.work_records) == "scripture"
        }
        zero_chunk_sources = sorted(
            all_scripture_source_ids - set(self.source_book_counts.keys()))

        return {
            "coverage_by_source": coverage,
            "sources_with_zero_chunks": zero_chunk_sources,
        }


def _check_scripture_coverage(
    work_records: dict[str, dict], chunks: list[dict]
) -> dict[str, Any]:
    return _ScriptureCoverage(work_records).run(chunks)


# ---------------------------------------------------------------------------
# Group 10: Chunk count report
# ---------------------------------------------------------------------------

class _ChunkCounts(_Check):
    """Count chunks by ``Work.genre`` (from ``_works.jsonl``) and by chunk language.

    Chunks whose work has no manifest record are counted under
    ``UNKNOWN_GENRE``; ``_check_works_manifest`` reports them as errors.
    """

    def __init__(self, work_records: dict[str, dict]) -> None:
        self.work_records = work_records
        self.by_genre: Counter = Counter()
        self.by_language: Counter = Counter()

    def add(self, chunks: list[dict]) -> None:
        for c in chunks:
            self.by_genre[_genre_of(c.get("work_id", ""), self.work_records)] += 1
            self.by_language[c.get("language", "unknown")] += 1

    def result(self) -> dict[str, Any]:
        return {
            "by_genre": dict(self.by_genre.most_common()),
            "by_language": dict(self.by_language.most_common()),
        }


def _chunk_count_report(
    chunks: list[dict], work_records: dict[str, dict]
) -> dict[str, Any]:
    return _ChunkCounts(work_records).run(chunks)


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _tally(checks_map: dict[str, dict[str, CheckResult]]) -> tuple[int, int]:
    errors = warnings = 0
    for section in checks_map.values():
        for r in section.values():
            if isinstance(r, dict) and "status" in r:
                if r["status"] == "fail":
                    errors += r.get("violation_count", 0)
                elif r["status"] == "warn":
                    warnings += r.get("violation_count", 0)
    return errors, warnings


def _print_brief(report: dict, output_path: Path) -> None:
    """The result in a line or two (``--brief``, for scripts.pipeline): every
    error with its examples, the warnings as a count only."""
    s = report["summary"]
    results: dict[str, CheckResult] = {}
    for section in report["checks"].values():
        results.update(section)
    fails = [(n, r) for n, r in results.items() if r.get("status") == "fail"]
    warns = [n for n, r in results.items() if r.get("status") == "warn"]
    for name, r in fails:
        print(f"FAIL {name}: {r['violation_count']:,} violations")
        for ex in r.get("examples", [])[:3]:
            print(f"     {ex}")
    print(f"{'FAIL' if fails else 'PASS'}: {s['total_works']:,} works, "
          f"{s['total_chunks']:,} chunks; {s['errors']:,} errors in {len(fails)} checks, "
          f"{s['warnings']:,} warnings in {len(warns)} of {len(results)} checks "
          f"(report: {output_path})")


def _print_summary(report: dict) -> None:
    summary = report["summary"]
    counts = report["chunk_counts"]
    checks_map = report["checks"]

    all_results: dict[str, CheckResult] = {}
    for section in checks_map.values():
        all_results.update(section)

    fails = [(n, r) for n, r in all_results.items() if r.get("status") == "fail"]
    warns = [(n, r) for n, r in all_results.items() if r.get("status") == "warn"]
    passes = [n for n, r in all_results.items() if r.get("status") == "pass"]

    sep = "=" * 62
    print(f"\n{sep}")
    print("Patristica Validation Report")
    print(f"Generated: {report['generated_at']}")
    print(sep)
    print(f"  Total works:   {summary['total_works']:>8,}")
    print(f"  Total chunks:  {summary['total_chunks']:>8,}")
    print(f"  Errors:        {summary['errors']:>8,}")
    print(f"  Warnings:      {summary['warnings']:>8,}")

    print("\nChunks by genre:")
    for genre, count in sorted(counts["by_genre"].items()):
        print(f"  {genre:<22} {count:>8,}")

    print("\nChunks by language:")
    for lang, count in sorted(counts["by_language"].items()):
        print(f"  {lang:<22} {count:>8,}")

    if fails:
        print("\nERRORS (must fix):")
        for name, r in fails:
            print(f"  [FAIL] {name}: {r['violation_count']} violations")
            for ex in r.get("examples", [])[:3]:
                print(f"         {ex}")

    if warns:
        print("\nWARNINGS (review):")
        for name, r in warns:
            cnt = r["violation_count"]
            note = f" — {r['note']}" if r.get("note") else ""
            print(f"  [WARN] {name}: {cnt}{note}")

    n_all = len(all_results)
    print(f"\nChecks passed: {len(passes)}/{n_all}")
    overall = "PASS" if not fails else "FAIL"
    print(f"Overall result: {overall}")
    print(f"{sep}\n")


#: Data validate reads besides its code: the corpus and the curated tables.
INPUT_PREFIXES = ("data/normalized/", "patristica/data/")
#: Curated tables under patristica/data that validate never reads: the nightly
#: machine-translation curation (#425), pushed from a worktree without the corpus.
NOT_INPUTS = {"patristica/data/mt_exceptions.csv", "patristica/data/mt_blocked.csv"}


def input_files() -> set[str]:
    """Repo-relative paths of validate's code (its import closure)."""
    root = fingerprint.REPO_ROOT
    return {
        fingerprint.module_path(m).relative_to(root).as_posix()
        for m in fingerprint.module_closure("scripts.validate")
    }


def inputs_changed(changed: list[str]) -> list[str]:
    """The paths in *changed* (repo-relative) that validate reads.

    normalize's fingerprint files (``_fingerprint.json``, ``_fingerprints.jsonl``)
    are bookkeeping, not data validate checks, and ``NOT_INPUTS`` aren't read.
    """
    code = input_files()
    return [p for p in changed
            if p in code
            or (p.startswith(INPUT_PREFIXES) and p not in NOT_INPUTS
                and not Path(p).name.startswith("_fingerprint"))]


def changed_since(ref: str, rev: str = "HEAD") -> list[str]:
    """Repo-relative paths that differ between commits *ref* and *rev*."""
    out = subprocess.run(
        ["git", "diff", "--name-only", ref, rev], cwd=fingerprint.REPO_ROOT,
        capture_output=True, text=True, check=True,
    )
    return [line for line in out.stdout.splitlines() if line]


def write_summary(report: dict, path: Path) -> None:
    """Append the result as Markdown (a CI job summary)."""
    results = {n: r for section in report["checks"].values() for n, r in section.items()}
    s = report["summary"]
    lines = [
        "## Validation", "",
        f"{s['total_works']:,} works, {s['total_chunks']:,} chunks: "
        f"**{s['errors']:,} errors**, {s['warnings']:,} warnings.", "",
        "| check | status | violations |", "|---|---|---:|",
    ]
    for name, r in sorted(results.items(), key=lambda kv: (kv[1].get("status") != "fail", kv[0])):
        if r.get("status") in ("fail", "warn"):
            lines.append(f"| {name} | {r['status']} | {r['violation_count']:,} |")
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    console.setup_logging()
    parser = argparse.ArgumentParser(description="Validate normalized and chunk data.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output", default="data/validation_report.json")
    parser.add_argument("--if-changed", metavar="REF",
                        help="run only if a file validate reads changed since this git ref")
    parser.add_argument("--inputs-changed", nargs=2, metavar=("BASE", "REV"),
                        help="only print the files validate reads that differ between two "
                             "commits (one per line), without validating; for the pre-push hook")
    parser.add_argument("--summary", type=Path, metavar="FILE",
                        help="append the result as Markdown (e.g. $GITHUB_STEP_SUMMARY)")
    parser.add_argument("--brief", action="store_true",
                        help="print the result in a line (errors in full), not the whole report")
    args = parser.parse_args()

    if args.inputs_changed:
        for path in inputs_changed(changed_since(*args.inputs_changed)):
            print(path)
        return
    if args.if_changed:
        relevant = inputs_changed(changed_since(args.if_changed))
        if not relevant:
            log.info("Nothing validate reads changed since %s: skipping", args.if_changed)
            return
        log.info("%d files validate reads changed since %s (e.g. %s)",
                 len(relevant), args.if_changed, relevant[0])

    data_dir = Path(args.data_dir)

    try:
        works = _load_works(data_dir)
    except ValidationInputError as exc:
        log.error("%s", exc)
        sys.exit(2)
    work_records = _records_by_id(works)
    log.debug("Loaded %d work records from %s", len(works), WORKS_MANIFEST)

    paths = _chunk_files(data_dir)
    read: list[Path] = []  # the files fed to the checks, by file number

    def reload(file_no: int) -> list[dict]:
        chunks = _read_chunk_file(read[file_no])
        if chunks is None:
            raise ValidationInputError(f"{read[file_no]} changed while validating")
        return chunks

    text_quality = _TextQuality()
    section_numbers = _SectionNumbers(work_records)
    language_script = _LanguageScript()
    canonical_refs = _CanonicalRefs(work_records, reload)
    id_uniqueness = _IdUniqueness(works, reload)
    dates = _DatePlausibility(work_records)
    cross_references = _CrossReferences(works, work_records)
    works_manifest = _WorksManifest(work_records)
    coverage_check = _ScriptureCoverage(work_records)
    chunk_counts = _ChunkCounts(work_records)
    streamed: list[_Check] = [
        text_quality, section_numbers, language_script, canonical_refs, id_uniqueness,
        dates, cross_references, works_manifest, coverage_check, chunk_counts,
    ]

    # One work file at a time (#374): the corpus is ~4M chunks.
    parse_errors: list[str] = []
    total_chunks = 0
    for path in tqdm(paths, desc="Validating", unit="file"):
        chunks = _read_chunk_file(path)
        if chunks is None:
            parse_errors.append(str(path))
            continue
        read.append(path)
        total_chunks += len(chunks)
        for check in streamed:
            check.add(chunks)
    log.debug("Checked %d chunks (%d parse errors)", total_chunks, len(parse_errors))

    try:
        checks: dict[str, dict[str, CheckResult]] = {
            "schema_integrity": _check_schema(parse_errors),
            "text_quality": {
                **text_quality.result(),
                **section_numbers.result(),
            },
            "language_script": language_script.result(),
            "canonical_refs": canonical_refs.result(),
            "id_uniqueness": id_uniqueness.result(),
            "date_plausibility": dates.result(),
            "cross_references": {
                **cross_references.result(),
                **works_manifest.result(),
            },
            "metadata_completeness": {
                **_check_metadata_completeness(works),
                **_check_authors(works),
            },
        }
    except ValidationInputError as exc:
        log.error("%s", exc)
        sys.exit(2)

    coverage = coverage_check.result()
    counts = chunk_counts.result()
    total_errors, total_warnings = _tally(checks)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_works": len(works),
            "total_chunks": total_chunks,
            "errors": total_errors,
            "warnings": total_warnings,
        },
        "checks": checks,
        "coverage": coverage,
        "chunk_counts": counts,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w") as f:
        json.dump(report, f, indent=2, default=str)
    log.debug("Report written to %s", output_path)

    if args.brief:
        _print_brief(report, output_path)
    else:
        _print_summary(report)
    if args.summary:
        write_summary(report, args.summary)
    sys.exit(0 if total_errors == 0 else 1)


if __name__ == "__main__":
    main()
