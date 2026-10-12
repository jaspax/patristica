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
7. Cross-reference integrity — work_ids exist (in _index.json and _works.jsonl),
   translation_of targets exist, groups ≥2
8. Metadata completeness — author, title, license, provenance_url
9. Scripture coverage — books present/missing per translation
10. Chunk count report — totals by Work.genre (from _works.jsonl) and language
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tqdm import tqdm

from patristica.period import COMPOSED_BY
from patristica.section_numbers import leading_section_number

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

def _load_works(data_dir: Path) -> tuple[list[dict], dict[str, dict]]:
    """Returns (works_list, work_id_to_entry) from _index.json."""
    index_path = data_dir / "normalized" / "_index.json"
    if not index_path.exists():
        log.warning("_index.json not found at %s", index_path)
        return [], {}
    with index_path.open() as f:
        idx = json.load(f)
    works: list[dict] = []
    by_id: dict[str, dict] = {}
    for prefix_works in idx.get("entries", {}).values():
        for entry in prefix_works:
            works.append(entry)
            wid = entry.get("work_id", "")
            if wid:
                by_id[wid] = entry
    return works, by_id


class ValidationInputError(Exception):
    """Raised when an input validate.py needs (e.g. ``_works.jsonl``) is missing or malformed."""


WORKS_MANIFEST = "_works.jsonl"
UNKNOWN_GENRE = "unknown"


def _load_work_records(data_dir: Path) -> dict[str, dict]:
    """Return ``work_id → Work record`` from ``normalized/_works.jsonl``.

    This manifest is the authoritative source of ``Work.genre`` and
    ``Work.source_id``; the path prefix of a normalized file is a source-id
    namespace and need not match the genre of the works in it.
    """
    manifest_path = data_dir / "normalized" / WORKS_MANIFEST
    if not manifest_path.exists():
        raise ValidationInputError(
            f"{manifest_path} not found; run scripts.normalize to build it"
        )
    records: dict[str, dict] = {}
    with manifest_path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                work = json.loads(line)["work"]
                wid = work["work_id"]
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise ValidationInputError(
                    f"{manifest_path}:{lineno}: malformed manifest line ({exc!r})"
                ) from exc
            records[wid] = work
    return records


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
        p for p in normalized_dir.rglob("*.json") if p.name != "_index.json"
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
    empty, short, html, replacement, low_alpha = [], [], [], [], []
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
        if text and text.strip() and _alpha_ratio(text) < MIN_ALPHA_RATIO:
            low_alpha.append(cid)
    return {
        "text_empty": _result("error", empty),
        "text_too_short": _result("warning", short, f"< {MIN_TEXT_LEN} chars"),
        "text_has_html_tags": _result("warning", html, "many are OCR artifacts in OGLT PL/OGPG/Gallican"),
        "text_has_replacement_char": _result("warning", replacement, "U+FFFD indicates encoding failure"),
        "text_low_alpha_ratio": _result("warning", low_alpha, f"< {MIN_ALPHA_RATIO:.0%} alphabetic chars"),
    }


def _check_section_numbers(
    chunks: list[dict], work_id_to_entry: dict[str, dict]
) -> dict[str, CheckResult]:
    """Prose chunks whose text still starts with the ref's own section number.

    ``normalize.py`` strips these (#30), so a hit means the normalized data
    predates that step or the text reached the corpus some other way.
    Scripture is skipped: a verse may start with a numeral.
    """
    dup_number: list[str] = []
    for c in chunks:
        entry = work_id_to_entry.get(c.get("work_id", ""), {})
        source_id = entry.get("source_id", "")
        if source_id.startswith("scripture/"):
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

def _check_date_plausibility(chunks: list[dict]) -> dict[str, CheckResult]:
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

        if dc is not None:
            if not (DATE_MIN <= dc <= DATE_MAX):
                out_of_range.append(f"{cid} (date_composed={dc})")
            if flagged and dc <= COMPOSED_BY:
                period_flag_conflict.append(f"{cid} (out_of_period=True, date_composed={dc})")
            if not flagged and dc > COMPOSED_BY:
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
    works: list[dict], chunks: list[dict], work_id_to_entry: dict[str, dict]
) -> dict[str, CheckResult]:
    work_id_set = set(work_id_to_entry.keys())

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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Validate normalized and chunk data.")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--output", default="data/validation_report.json")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)

    log.info("Loading index…")
    works, work_id_to_entry = _load_works(data_dir)
    log.info("Loaded %d works from index", len(works))

    work_records = _load_work_records(data_dir)
    log.info("Loaded %d work records from %s", len(work_records), WORKS_MANIFEST)

    log.info("Loading chunks…")
    chunks, parse_errors = _load_chunks(data_dir)
    log.info("Loaded %d chunks (%d parse errors)", len(chunks), len(parse_errors))

    log.info("Running checks…")
    checks: dict[str, dict[str, CheckResult]] = {
        "schema_integrity": _check_schema(parse_errors),
        "text_quality": {
            **_check_text_quality(chunks),
            **_check_section_numbers(chunks, work_id_to_entry),
        },
        "language_script": _check_language_script(chunks),
        "canonical_refs": _check_canonical_refs(chunks, work_records),
        "id_uniqueness": _check_id_uniqueness(works, chunks),
        "date_plausibility": _check_date_plausibility(chunks),
        "cross_references": {
            **_check_cross_references(works, chunks, work_id_to_entry),
            **_check_works_manifest(chunks, work_records),
        },
        "metadata_completeness": _check_metadata_completeness(works),
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
    sys.exit(0 if total_errors == 0 else 1)


if __name__ == "__main__":
    main()
