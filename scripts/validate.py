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
from typing import Any

from tqdm import tqdm

from patristica import fingerprint
from patristica.authors import UnknownAuthorError, resolve_author, work_author_birth_year
from patristica.period import AUTHOR_BORN_BEFORE, COMPOSED_BY
from patristica.mojibake import mojibake_runs
from patristica.section_numbers import STRAY_SCRIPT_DIGIT_RE, leading_section_number

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_LANGUAGES = {"grc", "lat", "hbo", "syc", "cop", "gez", "hye", "got", "eng"}

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

def _in_script_range(cp: int, ranges: list[tuple[int, int]]) -> bool:
    return any(lo <= cp <= hi for lo, hi in ranges)


def _script_ratio(text: str, ranges: list[tuple[int, int]]) -> float:
    if not text:
        return 0.0
    return sum(1 for ch in text if _in_script_range(ord(ch), ranges)) / len(text)


def _alpha_ratio(text: str) -> float:
    if not text:
        return 0.0
    return sum(1 for ch in text if ch.isalpha()) / len(text)


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


def _load_chunks(data_dir: Path) -> tuple[list[dict], list[str]]:
    """Returns (chunks, parse_error_paths)."""
    normalized_dir = data_dir / "normalized"
    json_files = sorted(
        p for p in normalized_dir.rglob("*.json") if not p.name.startswith("_")
    )
    chunks: list[dict] = []
    parse_errors: list[str] = []
    for path in tqdm(json_files, desc="Loading chunks", unit="file"):
        try:
            with path.open() as f:
                data = json.load(f)
            if isinstance(data, list):
                chunks.extend(data)
            else:
                parse_errors.append(str(path))
                log.warning("Expected list in %s, got %s", path, type(data).__name__)
        except json.JSONDecodeError as exc:
            parse_errors.append(str(path))
            log.error("JSON parse error in %s: %s", path, exc)
    return chunks, parse_errors


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

def _check_text_quality(chunks: list[dict]) -> dict[str, CheckResult]:
    empty, short, html, replacement, low_alpha, mojibake = [], [], [], [], [], []
    for c in chunks:
        cid = c.get("chunk_id", "?")
        text = c.get("text", "")
        if not text or not text.strip():
            empty.append(cid)
        elif len(text) < MIN_TEXT_LEN:
            short.append(cid)
        if text and _HTML_TAG_RE.search(text):
            html.append(cid)
        if text and _REPLACEMENT_CHAR in text:
            replacement.append(cid)
        runs = mojibake_runs(text) if text else []
        if runs:
            mojibake.append(f"{cid} ({runs[0]!r})")
        if text and text.strip() and _alpha_ratio(text) < MIN_ALPHA_RATIO:
            low_alpha.append(cid)
    return {
        "text_empty": _result("error", empty),
        "text_too_short": _result("warning", short, f"< {MIN_TEXT_LEN} chars"),
        "text_has_html_tags": _result("warning", html, "many are OCR artifacts in OGLT PL/OGPG/Gallican"),
        "text_has_replacement_char": _result("warning", replacement, "U+FFFD indicates encoding failure"),
        "text_low_alpha_ratio": _result("warning", low_alpha, f"< {MIN_ALPHA_RATIO:.0%} alphabetic chars"),
        "text_has_mojibake": _result(
            "warning", mojibake,
            "double-encoded UTF-8 (\"Î»á½¹Î³Î¿Î½\" for \"λόγον\"): repair at ingest with "
            "patristica.mojibake.repair_double_utf8 (#124)",
        ),
    }


def _check_section_numbers(
    chunks: list[dict], work_records: dict[str, dict]
) -> dict[str, CheckResult]:
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
    dup_number: list[str] = []
    stray: list[str] = []
    for c in chunks:
        text = c.get("text", "")
        m = STRAY_SCRIPT_DIGIT_RE.search(text)
        if m:
            snippet = text[max(0, m.start() - 15) : m.end() + 15]
            stray.append(f"{c.get('chunk_id', '?')} ({snippet!r})")
        entry = work_records.get(c.get("work_id", ""), {})
        source_id = entry.get("source_id", "")
        if entry.get("genre") == "scripture":
            continue
        prefix = leading_section_number(
            c.get("text", ""), c.get("canonical_ref", ""), c.get("language"), source_id
        )
        if prefix:
            dup_number.append(f"{c.get('chunk_id', '?')} ({prefix.strip()!r})")
    return {
        "text_starts_with_section_number": _result(
            "warning", dup_number, "leading number repeats the ref's last segment; re-run normalize"
        ),
        "text_has_superscript_digits": _result(
            "warning",
            stray,
            "superscript/subscript digits left in the text: footnote markers, OCR noise, "
            "mojibake, or a damaged verse number that does not equal the ref (#121)",
        ),
    }


# ---------------------------------------------------------------------------
# Check group 3: Language/script consistency
# ---------------------------------------------------------------------------

def _check_language_script(chunks: list[dict]) -> dict[str, CheckResult]:
    invalid_lang: list[str] = []
    wrong_script: list[str] = []
    ascii_for_non_latin: list[str] = []
    for c in chunks:
        cid = c.get("chunk_id", "?")
        lang = c.get("language", "")
        text = c.get("text", "")
        if lang not in VALID_LANGUAGES:
            invalid_lang.append(f"{cid} (lang={lang!r})")
        if lang in SCRIPT_RANGES and text:
            ratio = _script_ratio(text, SCRIPT_RANGES[lang])
            if ratio < MIN_SCRIPT_RATIO:
                label = f"{cid} (lang={lang}, script_ratio={ratio:.2f})"
                if text.isascii():
                    ascii_for_non_latin.append(label)
                else:
                    wrong_script.append(label)
    return {
        "invalid_language_code": _result("error", invalid_lang),
        "wrong_script_for_language": _result("warning", wrong_script),
        "non_latin_lang_but_ascii_text": _result("warning", ascii_for_non_latin),
    }


# ---------------------------------------------------------------------------
# Check group 4: Canonical reference integrity
# ---------------------------------------------------------------------------

def _check_canonical_refs(
    chunks: list[dict], work_records: dict[str, dict]
) -> dict[str, CheckResult]:
    from scripts.ingest._scripture_meta import ALL_BOOKS as all_books
    scripture_work_ids = {
        wid for wid in work_records if _genre_of(wid, work_records) == "scripture"
    }

    empty_ref: list[str] = []
    bad_scripture: list[str] = []
    bad_prose: list[str] = []

    # Group by work_id for within-work checks
    by_work: defaultdict[str, list[dict]] = defaultdict(list)
    for c in chunks:
        by_work[c.get("work_id", "")].append(c)

    for c in chunks:
        cid = c.get("chunk_id", "?")
        ref = c.get("canonical_ref", "")
        wid = c.get("work_id", "")
        if not ref or not ref.strip():
            empty_ref.append(cid)
            continue
        parts = ref.split(".")
        if wid in scripture_work_ids:
            if len(parts) != 3 or parts[0] not in all_books:
                bad_scripture.append(f"{cid} ({ref!r})")
        else:
            if len(parts) < 2:
                bad_prose.append(f"{cid} ({ref!r})")

    dup_refs: list[str] = []
    bad_index: list[str] = []
    for wid, work_chunks in by_work.items():
        refs = [c.get("canonical_ref", "") for c in work_chunks]
        for ref, cnt in Counter(refs).items():
            if cnt > 1:
                dup_refs.append(f"{wid}: {ref!r} ×{cnt}")

        indices = sorted(c.get("chunk_index", -1) for c in work_chunks)
        if indices != list(range(len(indices))):
            bad_index.append(f"{wid} (got {indices[:5]}…)")

    return {
        "canonical_ref_empty": _result("error", empty_ref),
        "scripture_ref_malformed": _result("error", bad_scripture),
        "prose_ref_malformed": _result("warning", bad_prose),
        "duplicate_canonical_ref_within_work": _result("error", dup_refs),
        "non_sequential_chunk_index": _result("warning", bad_index),
    }


# ---------------------------------------------------------------------------
# Check group 5: ID uniqueness
# ---------------------------------------------------------------------------

def _check_id_uniqueness(
    works: list[dict], chunks: list[dict]
) -> dict[str, CheckResult]:
    work_id_counts = Counter(w.get("work_id", "") for w in works)
    dup_works = [f"{wid} ×{cnt}" for wid, cnt in work_id_counts.items() if cnt > 1]

    chunk_id_counts = Counter(c.get("chunk_id", "") for c in chunks)
    dup_chunks = [f"{cid} ×{cnt}" for cid, cnt in chunk_id_counts.items() if cnt > 1]

    return {
        "duplicate_work_ids": _result("error", dup_works),
        "duplicate_chunk_ids": _result("error", dup_chunks),
    }


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


def _check_date_plausibility(
    chunks: list[dict], work_records: dict[str, dict] | None = None
) -> dict[str, CheckResult]:
    """Date checks on chunks.

    When a chunk's work has authors with a known birth year (author index,
    #82), that year decides ``out_of_period`` (``patristica.period``), so the
    flag is checked against it instead of the composition date.
    """
    births = _author_birth_years(work_records or {})
    out_of_range: list[str] = []
    period_flag_conflict: list[str] = []
    period_flag_mismatch: list[str] = []
    range_inverted: list[str] = []
    date_outside_range: list[str] = []

    for c in chunks:
        cid = c.get("chunk_id", "?")
        dc = c.get("date_composed")
        dr = c.get("date_range")
        flagged = c.get("out_of_period", False)
        birth = births.get(c.get("work_id", ""))

        if birth is not None and flagged != (birth >= AUTHOR_BORN_BEFORE):
            period_flag_mismatch.append(f"{cid} (out_of_period={flagged}, author born {birth})")

        if dc is not None:
            if not (DATE_MIN <= dc <= DATE_MAX):
                out_of_range.append(f"{cid} (date_composed={dc})")
            # With a known author birth year, the flag was checked against it above.
            if birth is None and flagged and dc <= COMPOSED_BY:
                period_flag_conflict.append(f"{cid} (out_of_period=True, date_composed={dc})")
            if birth is None and not flagged and dc > COMPOSED_BY:
                period_flag_mismatch.append(f"{cid} (out_of_period=False, date_composed={dc})")

        if dr is not None and len(dr) == 2:
            if dr[0] > dr[1]:
                range_inverted.append(f"{cid} (date_range={list(dr)})")
            if dc is not None and (dc < dr[0] - 50 or dc > dr[1] + 50):
                date_outside_range.append(
                    f"{cid} (date_composed={dc}, date_range={list(dr)})"
                )

    return {
        "date_out_of_range": _result("warning", out_of_range, f"expected {DATE_MIN}–{DATE_MAX} CE"),
        "period_flag_date_conflict": _result("error", period_flag_conflict),
        "period_flag_mismatch": _result("warning", period_flag_mismatch),
        "date_range_inverted": _result("error", range_inverted),
        "date_outside_stated_range": _result("warning", date_outside_range),
    }


# ---------------------------------------------------------------------------
# Check group 7: Cross-reference integrity
# ---------------------------------------------------------------------------

def _check_cross_references(
    works: list[dict], chunks: list[dict], work_records: dict[str, dict]
) -> dict[str, CheckResult]:
    work_id_set = set(work_records.keys())

    orphan_chunks = [
        c.get("chunk_id", "?")
        for c in chunks
        if c.get("work_id") not in work_id_set
    ]

    bad_translation_of = [
        f"{w.get('work_id')} → {w.get('translation_of')}"
        for w in works
        if w.get("translation_of") and w.get("translation_of") not in work_id_set
    ]

    group_counts: Counter[str] = Counter(
        c["translation_group_id"]
        for c in chunks
        if c.get("translation_group_id")
    )
    singleton_groups = [gid for gid, cnt in group_counts.items() if cnt < 2]

    return {
        "orphan_chunks": _result(
            "error", orphan_chunks, "chunk work_id has no matching Work record"
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


def _check_works_manifest(
    chunks: list[dict], work_records: dict[str, dict]
) -> dict[str, CheckResult]:
    """Every chunk's work must have a ``_works.jsonl`` record with a genre."""
    missing_ids = sorted({
        c.get("work_id", "") for c in chunks if c.get("work_id", "") not in work_records
    })
    no_genre = sorted(wid for wid, w in work_records.items() if not w.get("genre"))
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

def _check_scripture_coverage(
    work_records: dict[str, dict], chunks: list[dict]
) -> dict[str, Any]:
    from scripts.ingest._scripture_meta import PROTESTANT_BOOKS
    protestant_set = set(PROTESTANT_BOOKS)

    # Book counts per scripture source_id
    source_book_counts: defaultdict[str, Counter] = defaultdict(Counter)
    for c in chunks:
        wid = c.get("work_id", "")
        if _genre_of(wid, work_records) != "scripture":
            continue
        ref = c.get("canonical_ref", "")
        book = ref.split(".")[0] if "." in ref else ""
        if book:
            sid = work_records[wid].get("source_id", "unknown")
            source_book_counts[sid][book] += 1

    coverage: dict[str, dict] = {}
    for sid, book_counts in sorted(source_book_counts.items()):
        present = sorted(book_counts.keys())
        missing_protestant = sorted(protestant_set - book_counts.keys())
        coverage[sid] = {
            "books_present": len(present),
            "missing_from_protestant_canon": missing_protestant,
        }

    # Scripture sources with zero chunks
    all_scripture_source_ids = {
        work.get("source_id")
        for wid, work in work_records.items()
        if _genre_of(wid, work_records) == "scripture"
    }
    zero_chunk_sources = sorted(all_scripture_source_ids - set(source_book_counts.keys()))

    return {
        "coverage_by_source": coverage,
        "sources_with_zero_chunks": zero_chunk_sources,
    }


# ---------------------------------------------------------------------------
# Group 10: Chunk count report
# ---------------------------------------------------------------------------

def _chunk_count_report(
    chunks: list[dict], work_records: dict[str, dict]
) -> dict[str, Any]:
    """Count chunks by ``Work.genre`` (from ``_works.jsonl``) and by chunk language.

    Chunks whose work has no manifest record are counted under
    ``UNKNOWN_GENRE``; ``_check_works_manifest`` reports them as errors.
    """
    by_genre: Counter = Counter()
    by_language: Counter = Counter()

    for c in chunks:
        by_genre[_genre_of(c.get("work_id", ""), work_records)] += 1
        by_language[c.get("language", "unknown")] += 1

    return {
        "by_genre": dict(by_genre.most_common()),
        "by_language": dict(by_language.most_common()),
    }


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
    are bookkeeping, not data validate checks.
    """
    code = input_files()
    return [p for p in changed
            if p in code
            or (p.startswith(INPUT_PREFIXES) and not Path(p).name.startswith("_fingerprint"))]


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
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
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
    log.info("Loaded %d work records from %s", len(works), WORKS_MANIFEST)

    log.info("Loading chunks…")
    chunks, parse_errors = _load_chunks(data_dir)
    log.info("Loaded %d chunks (%d parse errors)", len(chunks), len(parse_errors))

    log.info("Running checks…")
    checks: dict[str, dict[str, CheckResult]] = {
        "schema_integrity": _check_schema(parse_errors),
        "text_quality": {
            **_check_text_quality(chunks),
            **_check_section_numbers(chunks, work_records),
        },
        "language_script": _check_language_script(chunks),
        "canonical_refs": _check_canonical_refs(chunks, work_records),
        "id_uniqueness": _check_id_uniqueness(works, chunks),
        "date_plausibility": _check_date_plausibility(chunks, work_records),
        "cross_references": {
            **_check_cross_references(works, chunks, work_records),
            **_check_works_manifest(chunks, work_records),
        },
        "metadata_completeness": {
            **_check_metadata_completeness(works),
            **_check_authors(works),
        },
    }

    coverage = _check_scripture_coverage(work_records, chunks)
    counts = _chunk_count_report(chunks, work_records)
    total_errors, total_warnings = _tally(checks)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_works": len(works),
            "total_chunks": len(chunks),
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
    log.info("Report written to %s", output_path)

    _print_summary(report)
    if args.summary:
        write_summary(report, args.summary)
    sys.exit(0 if total_errors == 0 else 1)


if __name__ == "__main__":
    main()
