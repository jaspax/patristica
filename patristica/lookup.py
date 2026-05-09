"""
Library for looking up texts by canonical reference.

Provides an index-backed query API over the normalized data in data/normalized/.
The index (data/normalized/_index.json) is built automatically on first use and
maps canonical_ref first-components to WorkEntry metadata.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

log = logging.getLogger(__name__)

INDEX_FILENAME = "_index.json"


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class WorkEntry(TypedDict):
    work_id: str
    path: str              # relative to normalized_dir, e.g. "scripture/sblgnt/1Cor.json"
    canonical_prefix: str  # first dot-component of canonical_ref
    language: str
    title: str
    author: str | None
    source_id: str
    translation_of: str | None


@dataclass
class WorkResult:
    entry: WorkEntry
    chunks: list[dict]     # filtered Chunk dicts, in chunk_index order


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _normalized_dir(data_dir: Path) -> Path:
    return data_dir / "normalized"


def _raw_dir(data_dir: Path) -> Path:
    return data_dir / "raw"


def _index_path(data_dir: Path) -> Path:
    return _normalized_dir(data_dir) / INDEX_FILENAME


# ---------------------------------------------------------------------------
# Index building
# ---------------------------------------------------------------------------

def _read_raw_work(raw_file: Path) -> dict | None:
    """Return the 'work' dict from a raw JSON file, or None on failure."""
    try:
        data = json.loads(raw_file.read_text(encoding="utf-8"))
        return data.get("work")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _title_for_entry(
    raw_work: dict | None,
    canonical_prefix: str,
    work_id: str,
) -> str:
    """Resolve title via three-tier fallback."""
    if raw_work and raw_work.get("title"):
        return raw_work["title"]
    # Lazy import to avoid circular deps; _scripture_meta is scripts-only
    try:
        from scripts.ingest._scripture_meta import BOOK_TITLE  # type: ignore[import]
        if canonical_prefix in BOOK_TITLE:
            return BOOK_TITLE[canonical_prefix]
    except ImportError:
        pass
    return work_id.split("/")[-1]


def build_index(data_dir: Path) -> dict:
    """
    Scan all normalized files and build the index dict.
    Returns {"built_at": ..., "entries": {canonical_prefix: [WorkEntry, ...]}}.
    """
    norm_dir = _normalized_dir(data_dir)
    raw_base = _raw_dir(data_dir)
    entries: dict[str, list[WorkEntry]] = {}
    skipped = 0

    json_files = [
        p for p in norm_dir.rglob("*.json")
        if not p.name.startswith("_")
    ]
    log.info("Building index from %d normalized files...", len(json_files))

    for norm_file in sorted(json_files):
        try:
            chunks = json.loads(norm_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Skipping %s: %s", norm_file, exc)
            skipped += 1
            continue

        if not chunks:
            continue

        first = chunks[0]
        canonical_ref: str = first.get("canonical_ref", "")
        if not canonical_ref:
            skipped += 1
            continue

        canonical_prefix = canonical_ref.split(".")[0]
        work_id: str = first.get("work_id", "")
        language: str = first.get("language", "")

        rel_path = norm_file.relative_to(norm_dir)
        raw_file = raw_base / rel_path
        raw_work = _read_raw_work(raw_file)

        entry: WorkEntry = {
            "work_id": work_id,
            "path": str(rel_path),
            "canonical_prefix": canonical_prefix,
            "language": language,
            "title": _title_for_entry(raw_work, canonical_prefix, work_id),
            "author": raw_work.get("author") if raw_work else None,
            "source_id": (raw_work.get("source_id") or _source_id_from_work_id(work_id)),
            "translation_of": raw_work.get("translation_of") if raw_work else None,
        }
        entries.setdefault(canonical_prefix, []).append(entry)

    if skipped:
        log.warning("Skipped %d files during index build", skipped)

    return {
        "built_at": datetime.now(timezone.utc).isoformat(),
        "entries": entries,
    }


def _source_id_from_work_id(work_id: str) -> str:
    """Derive a best-effort source_id from work_id by dropping the last component."""
    parts = work_id.split("/")
    if len(parts) > 1:
        return "/".join(parts[:-1])
    return work_id


def save_index(index: dict, data_dir: Path) -> None:
    """Write index to data/normalized/_index.json."""
    path = _index_path(data_dir)
    path.write_text(
        json.dumps(index, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("Index saved to %s (%d prefixes)", path, len(index.get("entries", {})))


def load_index(data_dir: Path, rebuild: bool = False) -> dict:
    """
    Load the index from disk, building it first if it doesn't exist or rebuild=True.
    """
    path = _index_path(data_dir)
    if rebuild or not path.exists():
        log.info("Building lookup index (this may take a moment)...")
        index = build_index(data_dir)
        save_index(index, data_dir)
        return index
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Query parsing and filtering
# ---------------------------------------------------------------------------

def parse_query(query: str) -> tuple[str, str]:
    """
    Split a dot-separated query into (canonical_prefix, full_query).
    canonical_prefix is the first dot-component.
    """
    canonical_prefix = query.split(".")[0]
    return canonical_prefix, query


def filter_chunks(chunks: list[dict], query_ref: str) -> list[dict]:
    """
    Return chunks whose canonical_ref equals query_ref or starts with query_ref + ".".
    Preserves original order.
    """
    prefix = query_ref + "."
    return [
        c for c in chunks
        if c.get("canonical_ref") == query_ref
        or (c.get("canonical_ref") or "").startswith(prefix)
    ]


def select_entries(
    entries: list[WorkEntry],
    *,
    lang: str | None = None,
) -> list[WorkEntry]:
    """
    Filter entries by language preference.
    - lang=None: prefer entries where translation_of is None (originals).
      If all have translation_of set, return all.
    - lang="eng": return only entries with language == "eng".
    """
    if lang is not None:
        return [e for e in entries if e["language"] == lang]
    originals = [e for e in entries if e["translation_of"] is None]
    return originals if originals else entries


def _query_depth(query_ref: str, canonical_prefix: str) -> int:
    """Number of dot-components in query_ref beyond canonical_prefix."""
    return len(query_ref.split(".")) - len(canonical_prefix.split("."))


# ---------------------------------------------------------------------------
# Chunk loading
# ---------------------------------------------------------------------------

def _load_chunks_for_entry(entry: WorkEntry, data_dir: Path) -> list[dict]:
    """Load all chunks from the normalized file for this entry."""
    path = _normalized_dir(data_dir) / entry["path"]
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
        log.warning("Could not load %s: %s", path, exc)
        return []


# ---------------------------------------------------------------------------
# Main lookup API
# ---------------------------------------------------------------------------

def lookup(
    query: str,
    data_dir: Path,
    *,
    lang: str | None = None,
    source_id: str | None = None,
    rebuild_index: bool = False,
) -> list[WorkResult]:
    """
    Look up works by canonical reference query.

    Returns a list of WorkResult objects sorted by (language, source_id).
    Returns [] if no works match.
    """
    index = load_index(data_dir, rebuild=rebuild_index)
    canonical_prefix, query_ref = parse_query(query)

    candidates: list[WorkEntry] = index.get("entries", {}).get(canonical_prefix, [])
    if not candidates:
        return []

    if source_id is not None:
        candidates = [e for e in candidates if e["source_id"] == source_id]

    selected = select_entries(candidates, lang=lang)

    results: list[WorkResult] = []
    for entry in selected:
        chunks = _load_chunks_for_entry(entry, data_dir)
        filtered = filter_chunks(chunks, query_ref)
        if filtered:
            results.append(WorkResult(entry=entry, chunks=filtered))

    results.sort(key=lambda r: (r.entry["language"], r.entry["source_id"]))
    return results


def list_translations(
    query: str,
    data_dir: Path,
    rebuild_index: bool = False,
) -> list[WorkEntry]:
    """Return all WorkEntries for a query's canonical prefix, unfiltered by language."""
    index = load_index(data_dir, rebuild=rebuild_index)
    canonical_prefix, _ = parse_query(query)
    return list(index.get("entries", {}).get(canonical_prefix, []))


def list_works(
    data_dir: Path,
    *,
    lang: str | None = None,
    source_id: str | None = None,
    rebuild_index: bool = False,
) -> list[WorkEntry]:
    """
    Return all WorkEntries from the index, optionally filtered by language and/or source_id.
    Sorted by (source_id, canonical_prefix).
    """
    index = load_index(data_dir, rebuild=rebuild_index)
    all_entries: list[WorkEntry] = []
    for entry_list in index.get("entries", {}).values():
        all_entries.extend(entry_list)

    if lang is not None:
        all_entries = [e for e in all_entries if e["language"] == lang]
    if source_id is not None:
        all_entries = [e for e in all_entries if e["source_id"] == source_id]

    all_entries.sort(key=lambda e: (e["source_id"], e["canonical_prefix"]))
    return all_entries


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def _format_header(entry: WorkEntry) -> str:
    title = entry["title"]
    author = entry.get("author")
    source = entry["source_id"]
    lang = entry["language"]
    if author:
        return f"{title} by {author} ({source}, {lang})"
    return f"{title} ({source}, {lang})"


def format_result(result: WorkResult, query_ref: str) -> str:
    """Format a single WorkResult as a printable string with header."""
    header = _format_header(result.entry)
    depth = _query_depth(query_ref, result.entry["canonical_prefix"])

    if depth == 0:
        # Whole-work query: group by second canonical_ref component
        groups: dict[str, list[str]] = {}
        for chunk in result.chunks:
            ref = chunk.get("canonical_ref", "")
            parts = ref.split(".")
            key = parts[1] if len(parts) > 1 else parts[0]
            groups.setdefault(key, []).append(chunk.get("text", ""))
        body = "\n\n".join(
            " ".join(texts) for texts in groups.values()
        )
    else:
        # Section or specific query: concatenate
        body = " ".join(chunk.get("text", "") for chunk in result.chunks)

    return header + "\n" + body


def format_results(results: list[WorkResult], query_ref: str) -> str:
    """Format multiple results separated by a horizontal rule."""
    if not results:
        return f"No results found for: {query_ref}"
    separator = "\n\n---\n\n"
    return separator.join(format_result(r, query_ref) for r in results)
