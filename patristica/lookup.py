"""
Library for looking up texts by canonical reference.

Provides an index-backed query API over the normalized data in data/normalized/.
The index maps canonical_ref first-components to WorkEntry metadata.  It is
built in memory on each call from ``_works.jsonl`` (the work manifest that
``scripts.normalize`` maintains) plus the first chunk of each normalized file,
so it can never go stale and nothing is written to disk.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

log = logging.getLogger(__name__)

WORKS_MANIFEST = "_works.jsonl"
_PEEK_BYTES = 1 << 16


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


@dataclass
class SectionEntry:
    section_key: str       # the next canonical_ref component after the query
    title: str | None      # WorkEntry title when section = a distinct sub-work
    work_id: str | None    # work_id when section = a distinct sub-work
    chunk_count: int


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _normalized_dir(data_dir: Path) -> Path:
    return data_dir / "normalized"


# ---------------------------------------------------------------------------
# Index building
# ---------------------------------------------------------------------------

class LookupIndexError(Exception):
    """Raised when ``_works.jsonl`` is missing or malformed."""


def _read_manifest(norm_dir: Path) -> list[tuple[str, dict]]:
    """Return ``(relative_path, work_dict)`` for every line of ``_works.jsonl``."""
    manifest = norm_dir / WORKS_MANIFEST
    if not manifest.exists():
        raise LookupIndexError(f"{manifest} not found; run scripts.normalize to build it")
    entries: list[tuple[str, dict]] = []
    with manifest.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                entries.append((rec["path"], rec["work"]))
            except (json.JSONDecodeError, KeyError, TypeError) as exc:
                raise LookupIndexError(
                    f"{manifest}:{lineno}: malformed manifest line ({exc!r})"
                ) from exc
    return entries


def _first_chunk(path: Path) -> dict | None:
    """Decode only the first element of a normalized chunk file (a JSON list).

    Reads the file in growing blocks until the first object parses, so large
    works are not loaded in full.  Returns None for an empty list.
    """
    decoder = json.JSONDecoder()
    with path.open(encoding="utf-8") as f:
        buf = ""
        while True:
            block = f.read(_PEEK_BYTES)
            buf += block
            head = buf.lstrip()
            if not head.startswith("["):
                if not block:
                    raise ValueError(f"{path}: not a JSON list")
                continue
            body = head[1:].lstrip()
            if body.startswith("]"):
                return None
            try:
                obj, _ = decoder.raw_decode(body)
            except json.JSONDecodeError:
                if not block:
                    raise
                continue
            if not isinstance(obj, dict):
                raise ValueError(f"{path}: first element is not an object")
            return obj


def build_index(data_dir: Path) -> dict:
    """
    Build the lookup index from ``_works.jsonl`` and each work's first chunk.
    Returns {"entries": {canonical_prefix: [WorkEntry, ...]}}, deterministic
    for given data (manifest order, which is sorted by path).
    """
    norm_dir = _normalized_dir(data_dir)
    entries: dict[str, list[WorkEntry]] = {}
    skipped = 0

    for rel_path, work in _read_manifest(norm_dir):
        norm_file = norm_dir / rel_path
        try:
            first = _first_chunk(norm_file)
        except (OSError, ValueError) as exc:
            log.warning("Skipping %s: %s", norm_file, exc)
            skipped += 1
            continue
        if first is None:
            continue

        canonical_ref: str = first.get("canonical_ref", "")
        if not canonical_ref:
            skipped += 1
            continue

        canonical_prefix = canonical_ref.split(".")[0]
        work_id: str = work.get("work_id") or first.get("work_id", "")
        entry: WorkEntry = {
            "work_id": work_id,
            "path": rel_path,
            "canonical_prefix": canonical_prefix,
            "language": first.get("language") or work.get("language", ""),
            "title": work.get("title") or work_id.split("/")[-1],
            "author": work.get("author"),
            "source_id": work.get("source_id") or _source_id_from_work_id(work_id),
            "translation_of": work.get("translation_of"),
        }
        entries.setdefault(canonical_prefix, []).append(entry)

    if skipped:
        log.warning("Skipped %d files during index build", skipped)

    return {"entries": entries}


def _source_id_from_work_id(work_id: str) -> str:
    """Derive a best-effort source_id from work_id by dropping the last component."""
    parts = work_id.split("/")
    if len(parts) > 1:
        return "/".join(parts[:-1])
    return work_id


def load_index(data_dir: Path) -> dict:
    """Build the lookup index for *data_dir* (see ``build_index``)."""
    return build_index(data_dir)


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
) -> list[WorkResult]:
    """
    Look up works by canonical reference query.

    Returns a list of WorkResult objects sorted by (language, source_id).
    Returns [] if no works match.
    """
    index = load_index(data_dir)
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
) -> list[WorkEntry]:
    """Return all WorkEntries for a query's canonical prefix, unfiltered by language."""
    index = load_index(data_dir)
    canonical_prefix, _ = parse_query(query)
    return list(index.get("entries", {}).get(canonical_prefix, []))


def list_sections(
    query: str,
    data_dir: Path,
    *,
    lang: str | None = None,
    source_id: str | None = None,
) -> list[SectionEntry]:
    """
    List the sections at the level immediately below *query*.

    Each returned SectionEntry represents one distinct value of the next
    canonical_ref component.  When every section key maps to a different
    underlying work file (e.g. OGPG volumes, ByzLit liturgies), the
    WorkEntry title is included.  When all sections share the same work
    file (e.g. Gen chapters), only the key is returned.

    Results are sorted in the order the sections first appear in the data.
    """
    index = load_index(data_dir)
    canonical_prefix, query_ref = parse_query(query)

    candidates: list[WorkEntry] = index.get("entries", {}).get(canonical_prefix, [])
    if not candidates:
        return []

    if source_id is not None:
        candidates = [e for e in candidates if e["source_id"] == source_id]

    selected = select_entries(candidates, lang=lang)

    # group_index: which dot-component to group by (0-based)
    group_index = len(query_ref.split("."))

    # key → (list of chunks, set of work_ids encountered, last entry seen)
    groups: dict[str, tuple[list[dict], set[str], WorkEntry]] = {}

    for entry in selected:
        chunks = _load_chunks_for_entry(entry, data_dir)
        filtered = filter_chunks(chunks, query_ref)
        for chunk in filtered:
            parts = chunk.get("canonical_ref", "").split(".")
            key = parts[group_index] if len(parts) > group_index else parts[-1]
            if key not in groups:
                groups[key] = ([], set(), entry)
            group_chunks, work_ids, _ = groups[key]
            group_chunks.append(chunk)
            work_ids.add(entry["work_id"])

    if not groups:
        return []

    # If the number of distinct section keys equals the number of distinct
    # work_ids, each section corresponds to a distinct sub-work → show titles.
    all_work_ids: set[str] = set()
    for _, (_, wids, _) in groups.items():
        all_work_ids.update(wids)
    show_titles = len(groups) == len(all_work_ids)

    sections: list[SectionEntry] = []
    for key, (chunk_list, wids, entry) in groups.items():
        if show_titles:
            title = entry["title"]
            work_id = entry["work_id"]
        else:
            title = None
            work_id = None
        sections.append(SectionEntry(
            section_key=key,
            title=title,
            work_id=work_id,
            chunk_count=len(chunk_list),
        ))

    return sections


def list_works(
    data_dir: Path,
    *,
    lang: str | None = None,
    source_id: str | None = None,
) -> list[WorkEntry]:
    """
    Return all WorkEntries from the index, optionally filtered by language and/or source_id.
    Sorted by (source_id, canonical_prefix).
    """
    index = load_index(data_dir)
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
