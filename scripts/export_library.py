"""
Export the normalized corpus as a static library for the web browser.

Reads ``data/normalized/_works.jsonl`` and each work's normalized chunk file and
writes ``data/library/`` (gitignored):

- ``index.json`` — one row per work (author, title, language, genre, dates,
  collection, edition, licence, provenance, ``translation_of``, ``version_group``,
  chunk count, file path), a
  ``source_id → label`` map (``patristica.sources``), and ``version``, a hash
  of the index and every work file. Unchanged data gives a byte-identical
  index, so re-exports and uploads are no-ops.  The library browser
  loads this once and searches/sorts it client-side.  ``version_group``
  (``patristica.versions``, #178) is the id of the work's version group, the
  same text in other languages and editions, or null for a work with no
  other version; a group's members are the rows with the same id.
- ``authors.json`` — the author index (``patristica.authors``, #82): one
  record per person (id, name, aliases, birth/death/floruit, tradition,
  external ids, pseudo_of), sorted by id.  Index rows carry ``author_ids``
  that point into it.
- ``alignments/{group}.json`` — the passage alignment of a version group
  (``data/alignments/``, #179), for keeping the reader's place when it
  switches versions: ``{"group", "pivot", "groups", "members": {work_id:
  {"units", "spans", "conf"}}}`` with ``spans`` and ``conf`` as in
  ``patristica.alignment_store`` (one token per chunk, one confidence digit
  per group). ``book:gen`` is ``alignments/book/gen.json``, any other group
  ``alignments/{group}.json``. ``index.json`` lists the groups that have one
  under ``alignments``. A member whose chunk count no longer matches is left
  out until ``scripts.align`` runs again.
- ``works/{path}`` — a slim per-work file, ``{"work_id", "ref_prefix",
  "chunks": [[ref_suffix, text], ...]}``, where ``path`` mirrors the work's
  path under ``data/normalized/``.  The common dot-separated ref prefix is
  stripped from every ref (``Gen.1.1`` → prefix ``Gen``, suffix ``1.1``);
  out-of-period chunks carry a third element, ``1``.  A Scripture book
  (``patristica.versions.scripture_book``) also carries ``org_refs``,
  ``{ref_suffix: org_ref}`` for every chunk whose ref in org versification
  (``patristica.versification.to_org_ref``, BHS / Nestle-Aland: the
  ``translation_group_id`` key) differs from its native ref, so the reader can
  keep its place when it switches to another version of the book (#144).
  It is ``{}`` when every ref is already in org numbering. A work with
  editorial material (``patristica.editorial``, #236) also carries
  ``editorial``, ``{ref_suffix: [[start, end, kind], …]}`` for its marked
  chunks, with offsets into the chunk text in UTF-16 code units (JavaScript
  string indices); works without any have no such key.

Work files are rebuilt when their normalized source is newer (or with
``--force``); files whose source is gone are deleted.  Scripture books are
re-derived on every run, because ``org_refs`` also depends on
``patristica.versification``, and written only when they change.
``index.json`` is always rewritten.

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

from patristica import alignment_store, editorial
from patristica.authors import author_index, work_author_date_range
from patristica.models import Chunk, Work
from patristica.sources import SOURCE_LABELS, source_label
from patristica.versification import to_org_ref
from patristica.versions import derive_version_groups, scripture_book

log = logging.getLogger(__name__)

WORKS_SUBDIR = "works"
ALIGNMENTS_SUBDIR = "alignments"
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


def load_chunks(path: Path) -> tuple[list[Chunk], dict[str, list[editorial.Span]]]:
    """Load and validate a normalized chunk file, ordered by ``chunk_index``, and
    the editorial spans of its marked chunks (chunk_id → spans, #236)."""
    if not path.exists():
        raise ExportError(f"Normalized file listed in _works.jsonl is missing: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        chunks = [Chunk(**c) for c in raw]
        marks = {c["chunk_id"]: editorial.check(c["text"], c[editorial.KEY], c["chunk_id"])
                 for c in raw if c.get(editorial.KEY)}
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ExportError(f"Invalid normalized file {path}: {exc}") from exc
    return sorted(chunks, key=lambda c: c.chunk_index), marks


def org_refs(work: Work, chunks: list[Chunk], prefix: str) -> dict[str, str]:
    """``{ref_suffix: org_ref}`` for the chunks whose org ref differs from their native ref."""
    mapped: dict[str, str] = {}
    for c in chunks:
        org = to_org_ref(work.source_id, c.canonical_ref)
        if org != c.canonical_ref:
            mapped[strip_prefix(c.canonical_ref, prefix)] = org
    return mapped


def slim_work(work: Work, chunks: list[Chunk],
              marks: dict[str, list[editorial.Span]] | None = None) -> dict[str, Any]:
    """Build the per-work library record from its chunks and their editorial spans."""
    prefix = common_ref_prefix([c.canonical_ref for c in chunks])
    rows: list[list[Any]] = []
    spans: dict[str, list[list[Any]]] = {}
    for c in chunks:
        suffix = strip_prefix(c.canonical_ref, prefix)
        row: list[Any] = [suffix, c.text]
        if c.out_of_period:
            row.append(1)
        rows.append(row)
        if marks and c.chunk_id in marks:
            spans[suffix] = editorial.utf16_spans(c.text, marks[c.chunk_id])
    record: dict[str, Any] = {"work_id": work.work_id, "ref_prefix": prefix}
    if scripture_book(work.work_id) is not None:
        record["org_refs"] = org_refs(work, chunks, prefix)
    if spans:
        record["editorial"] = spans
    record["chunks"] = rows
    return record


def index_row(
    work: Work, file: str, n_chunks: int, version_group: str | None = None
) -> dict[str, Any]:
    """Build the ``index.json`` row for *work*."""
    # Approximate, for undated works only: their authors' activity (#151). The
    # same value normalize writes to _works.jsonl (a test checks it is current).
    author_dates = work_author_date_range(work.model_dump())
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
        "author_date_range": list(author_dates) if author_dates else None,
        "source_id": work.source_id,
        "edition": work.edition,
        "license": work.license,
        "provenance_url": work.provenance_url,
        "translation_of": work.translation_of,
        "version_group": version_group,
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
    alignment_files: tuple[str, ...] = (),
) -> str:
    """Content hash of the export: index rows, labels, authors, work and alignment files."""
    h = hashlib.sha256()
    h.update(
        json.dumps([sources, rows, authors], ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    for row in rows:
        h.update(hashlib.sha256((works_dir.parent / row["file"]).read_bytes()).digest())
    for file in alignment_files:
        h.update(file.encode("utf-8"))
        h.update(hashlib.sha256((works_dir.parent / file).read_bytes()).digest())
    return h.hexdigest()[:16]


def alignment_file(group: str) -> str:
    """The library path of a version group's alignment (``alignments/book/gen.json``)."""
    return alignment_store.path_for(Path(ALIGNMENTS_SUBDIR), group).as_posix()


def export_alignments(align_dir: Path, output_dir: Path, units: dict[str, int]
                      ) -> list[str]:
    """Write the reader's copy of every alignment in *align_dir*; return the groups written.

    *units* maps each exported work to its chunk count. Members not in it, or
    whose count differs (re-normalized since they were aligned), are left out,
    and so is a group left with fewer than two members. Files of groups that
    are gone are deleted. The output depends only on the tracked files.
    """
    written: list[str] = []
    expected: set[Path] = set()

    def exported(work_ids: list[str]) -> bool:
        return sum(w in units for w in work_ids) >= 2

    for _, a in alignment_store.iter_store(align_dir, exported):
        members = {}
        for wid, m in sorted(a.members.items()):
            if units.get(wid) != m.units:
                log.warning("alignment %s: leaving out %s (%s chunks, aligned %d)",
                            a.group, wid, units.get(wid), m.units)
                continue
            order = alignment_store.group_order(m.group_of)
            members[wid] = {"units": m.units, "spans": alignment_store.encode_spans(m.group_of),
                            "conf": "".join(str(min(9, m.conf.get(g, 0))) for g in order)}
        if len(members) < 2:
            continue
        rel = alignment_file(a.group)
        dst = output_dir / rel
        expected.add(dst)
        text = json.dumps({"group": a.group, "pivot": a.pivot, "groups": a.groups,
                           "members": members}, ensure_ascii=False, separators=(",", ":"))
        if not dst.exists() or dst.read_text(encoding="utf-8") != text:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text, encoding="utf-8")
        written.append(a.group)
    root = output_dir / ALIGNMENTS_SUBDIR
    if root.exists():
        for p in root.rglob("*.json"):
            if p not in expected:
                p.unlink()
    return sorted(written)


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


def export_library(input_dir: Path, output_dir: Path, force: bool = False,
                   align_dir: Path = alignment_store.DEFAULT_DIR) -> dict[str, int]:
    """Export every work in *input_dir* to *output_dir*.

    Returns counts: ``works`` (index rows), ``written`` (work files rebuilt),
    ``removed`` (stale work files deleted) and ``alignments`` (alignment files
    in the export).
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

    groups = derive_version_groups({w.work_id: w.translation_of for _, w in entries},
                                   external_ids={w.work_id: w.external_ids for _, w in entries})
    if groups.dangling:
        log.warning("Version links to works not in the corpus, ignored: %s", groups.dangling)
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
        # A Scripture book's org_refs also depend on the versification tables,
        # so it is rebuilt every time and written only if it changed.
        if up_to_date and scripture_book(work.work_id) is None:
            rows.append(
                index_row(work, file, prev_counts[work.work_id], groups.group(work.work_id)))
            continue
        chunks, marks = load_chunks(src)
        text = json.dumps(slim_work(work, chunks, marks), ensure_ascii=False,
                          separators=(",", ":"))
        if not (up_to_date and dst.read_text(encoding="utf-8") == text):
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(text, encoding="utf-8")
            written += 1
        rows.append(index_row(work, file, len(chunks), groups.group(work.work_id)))

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
    alignments = export_alignments(align_dir, output_dir, {r["id"]: r["chunks"] for r in rows})
    index = {
        "version": library_version(sources, rows, works_dir, authors,
                                   tuple(alignment_file(g) for g in alignments)),
        "sources": sources,
        "works": rows,
        "alignments": alignments,
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
    return {"works": len(rows), "written": written, "removed": removed,
            "alignments": len(alignments)}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Export the normalized corpus for the library browser.")
    parser.add_argument("--input-dir", default="data/normalized")
    parser.add_argument("--output-dir", default="data/library")
    parser.add_argument("--force", action="store_true", help="rebuild every work file")
    parser.add_argument("--alignments-dir", default=str(alignment_store.DEFAULT_DIR))
    args = parser.parse_args()

    export_library(Path(args.input_dir), Path(args.output_dir), force=args.force,
                   align_dir=Path(args.alignments_dir))


if __name__ == "__main__":
    main()
