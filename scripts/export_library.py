"""
Export the normalized corpus as a static library for the web browser.

Reads ``data/normalized/_works.jsonl`` and each work's normalized chunk file and
writes ``data/library/`` (gitignored):

- ``index.json`` — one row per work (author, title, language, genre, dates,
  collection, edition, licence, provenance, chunk count, file path), a
  ``source_id → label`` map (``patristica.sources``), and ``version``, a hash
  of the index and every work file. Unchanged data gives a byte-identical
  index, so re-exports and uploads are no-ops.  The library browser
  loads this once and searches/sorts it client-side.
- ``authors.json`` — the author index (``patristica.authors``, #82): one
  record per person (id, name, aliases, birth/death/floruit, tradition,
  external ids, pseudo_of), sorted by id.  Index rows carry ``author_ids``
  that point into it.
- ``works/{path}`` — a slim per-work file, ``{"work_id", "ref_prefix",
  "chunks": [[ref_suffix, text], ...]}``, where ``path`` mirrors the work's
  path under ``data/normalized/``.  The common dot-separated ref prefix is
  stripped from every ref (``Gen.1.1`` → prefix ``Gen``, suffix ``1.1``);
  out-of-period chunks carry a third element, ``1``.

Work files are rebuilt when their normalized source is newer (or with
``--force``); files whose source is gone are deleted.  ``index.json`` is always
rewritten.

Usage::

    python -m scripts.export_library [--input-dir data/normalized] [--output-dir data/library] [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from tqdm import tqdm

from patristica.authors import author_index
from patristica.models import Chunk, Work
from patristica.sources import SOURCE_LABELS, source_label

log = logging.getLogger(__name__)

WORKS_SUBDIR = "works"
INDEX_NAME = "index.json"
AUTHORS_NAME = "authors.json"


class ExportError(Exception):
    """Raised when the normalized input is missing or malformed."""


def common_ref_prefix(refs: list[str]) -> str:
    """Return the longest dot-segment prefix shared by all *refs*.

    The prefix never swallows a whole ref: every ref keeps at least one
    segment as its suffix.
    """
    if not refs:
        return ""
    split = [r.split(".") for r in refs]
    max_len = min(len(s) for s in split) - 1
    n = 0
    while n < max_len and all(s[n] == split[0][n] for s in split):
        n += 1
    return ".".join(split[0][:n])


def strip_prefix(ref: str, prefix: str) -> str:
    """Remove *prefix* (and its trailing dot) from *ref*."""
    return ref[len(prefix) + 1:] if prefix else ref


def read_works_manifest(input_dir: Path) -> list[tuple[str, Work]]:
    """Return ``(relative_path, Work)`` for every line of ``_works.jsonl``."""
    manifest = input_dir / "_works.jsonl"
    if not manifest.exists():
        raise ExportError(f"Works manifest not found: {manifest} (run scripts.normalize first)")
    entries: list[tuple[str, Work]] = []
    with manifest.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                entries.append((rec["path"], Work(**rec["work"])))
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                raise ExportError(f"{manifest}:{lineno}: invalid manifest entry: {exc}") from exc
    return entries


def load_chunks(path: Path) -> list[Chunk]:
    """Load and validate a normalized chunk file, ordered by ``chunk_index``."""
    if not path.exists():
        raise ExportError(f"Normalized file listed in _works.jsonl is missing: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        chunks = [Chunk(**c) for c in raw]
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ExportError(f"Invalid normalized file {path}: {exc}") from exc
    return sorted(chunks, key=lambda c: c.chunk_index)


def slim_work(work: Work, chunks: list[Chunk]) -> dict[str, Any]:
    """Build the per-work library record from its chunks."""
    prefix = common_ref_prefix([c.canonical_ref for c in chunks])
    rows: list[list[Any]] = []
    for c in chunks:
        row: list[Any] = [strip_prefix(c.canonical_ref, prefix), c.text]
        if c.out_of_period:
            row.append(1)
        rows.append(row)
    return {"work_id": work.work_id, "ref_prefix": prefix, "chunks": rows}


def index_row(work: Work, file: str, n_chunks: int) -> dict[str, Any]:
    """Build the ``index.json`` row for *work*."""
    return {
        "id": work.work_id,
        "author": work.author,
        "author_ids": work.author_ids,
        "title": work.title,
        "language": work.language,
        "genre": work.genre,
        "tradition": work.tradition,
        "date": work.date_composed,
        "date_range": list(work.date_range) if work.date_range else None,
        "date_confidence": work.date_confidence,
        "source_id": work.source_id,
        "edition": work.edition,
        "license": work.license,
        "provenance_url": work.provenance_url,
        "translation_of": work.translation_of,
        "chunks": n_chunks,
        "file": file,
    }


def authors_export() -> list[dict[str, Any]]:
    """Every author in the index, as exported to ``authors.json``, sorted by id."""
    authors = author_index().authors
    return [authors[aid].to_json() for aid in sorted(authors)]


def library_version(
    sources: dict[str, str],
    rows: list[dict[str, Any]],
    works_dir: Path,
    authors: list[dict[str, Any]],
) -> str:
    """Content hash of the export: the index rows, labels, authors, and every work file."""
    h = hashlib.sha256()
    h.update(
        json.dumps([sources, rows, authors], ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    for row in rows:
        h.update(hashlib.sha256((works_dir.parent / row["file"]).read_bytes()).digest())
    return h.hexdigest()[:16]


def _previous_counts(index_path: Path) -> dict[str, int]:
    """Chunk counts from an earlier ``index.json``, so up-to-date works need not be re-read."""
    if not index_path.exists():
        return {}
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
        return {row["id"]: row["chunks"] for row in data["works"]}
    except (json.JSONDecodeError, KeyError, TypeError):
        log.warning("Ignoring unreadable previous index %s", index_path)
        return {}


def export_library(input_dir: Path, output_dir: Path, force: bool = False) -> dict[str, int]:
    """Export every work in *input_dir* to *output_dir*.

    Returns counts: ``works`` (index rows), ``written`` (work files rebuilt)
    and ``removed`` (stale work files deleted).
    """
    entries = read_works_manifest(input_dir)
    works_dir = output_dir / WORKS_SUBDIR
    index_path = output_dir / INDEX_NAME
    prev_counts = {} if force else _previous_counts(index_path)

    expected = {works_dir / rel for rel, _ in entries}
    removed = 0
    if works_dir.exists():
        for p in works_dir.rglob("*.json"):
            if p not in expected:
                p.unlink()
                removed += 1
    if removed:
        log.info("Removed %d library files with no normalized source", removed)

    rows: list[dict[str, Any]] = []
    written = 0
    for rel, work in tqdm(entries, desc="export"):
        src = input_dir / rel
        dst = works_dir / rel
        file = f"{WORKS_SUBDIR}/{rel}"
        if not src.exists():
            raise ExportError(f"Normalized file listed in _works.jsonl is missing: {src}")
        up_to_date = (
            not force
            and dst.exists()
            and dst.stat().st_mtime >= src.stat().st_mtime
            and work.work_id in prev_counts
        )
        if up_to_date:
            rows.append(index_row(work, file, prev_counts[work.work_id]))
            continue
        chunks = load_chunks(src)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(
            json.dumps(slim_work(work, chunks), ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        written += 1
        rows.append(index_row(work, file, len(chunks)))

    used_sources = sorted({row["source_id"] for row in rows})
    unlabelled = [s for s in used_sources if s not in SOURCE_LABELS]
    if unlabelled:
        log.warning("No label in patristica.sources for: %s", ", ".join(unlabelled))

    sources = {s: source_label(s) for s in used_sources}
    authors = authors_export()
    known = {a["id"] for a in authors}
    unknown = sorted({a for row in rows for a in row["author_ids"]} - known)
    if unknown:
        raise ExportError(
            f"author_ids not in the author index (re-run scripts.normalize): {unknown}"
        )
    index = {
        "version": library_version(sources, rows, works_dir, authors),
        "sources": sources,
        "works": rows,
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / AUTHORS_NAME).write_text(
        json.dumps({"authors": authors}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    index_path.write_text(
        json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    log.info(
        "Library export complete: %d works in index, %d work files written, %d removed",
        len(rows), written, removed,
    )
    return {"works": len(rows), "written": written, "removed": removed}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Export the normalized corpus for the library browser.")
    parser.add_argument("--input-dir", default="data/normalized")
    parser.add_argument("--output-dir", default="data/library")
    parser.add_argument("--force", action="store_true", help="rebuild every work file")
    args = parser.parse_args()

    export_library(Path(args.input_dir), Path(args.output_dir), force=args.force)


if __name__ == "__main__":
    main()
