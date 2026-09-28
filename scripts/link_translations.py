"""
Assign ``translation_group_id`` across parallel chunks in different languages.

For Scripture this is deterministic: each chunk's native ``canonical_ref`` is
mapped onto one reference versification ("org": BHS / Nestle-Aland) by
``patristica.versification``, and chunks sharing the mapped ref form a group.
The group ID is the mapped ref (e.g. KJV ``Ps.23.1`` and LXX ``Ps.22.1`` both
get ``"Ps.23.1"``).

For Patristics (implemented in M3+), alignment requires a manual mapping table
or a section-level heuristic.

Reads and rewrites the JSON files under ``data/chunks/scripture/`` in-place
(only Scripture is linked; patristic/liturgical refs are work-specific and
must never be grouped by ref).  Singletons are reset to ``None`` so stale
groups are cleared, and only files whose group IDs changed are rewritten.

Usage::

    python -m scripts.link_translations [--chunks-dir data/chunks] [--force]
"""

from __future__ import annotations

import argparse
import json
import logging
from collections import defaultdict
from pathlib import Path

from tqdm import tqdm

from patristica.models import Chunk
from patristica.versification import to_org_ref

log = logging.getLogger(__name__)


def _load_chunks(chunks_dir: Path) -> tuple[list[Chunk], list[Path]]:
    """Load all chunk JSON files from *chunks_dir*.

    Returns (all_chunks, list_of_source_paths_per_chunk) so we can rewrite
    files efficiently.
    """
    all_chunks: list[Chunk] = []
    chunk_paths: list[Path] = []  # parallel to all_chunks

    json_files = sorted(chunks_dir.rglob("*.json"))
    for json_path in tqdm(json_files, desc="load chunks"):
        with json_path.open(encoding="utf-8") as f:
            try:
                records = json.load(f)
            except json.JSONDecodeError as exc:
                log.warning("Skipping %s: %s", json_path, exc)
                continue
        if not isinstance(records, list):
            continue
        for rec in records:
            chunk = Chunk(**rec)
            all_chunks.append(chunk)
            chunk_paths.append(json_path)

    return all_chunks, chunk_paths


def link_scripture_translations(
    chunks: list[Chunk],
) -> list[Chunk]:
    """Assign ``translation_group_id`` to scripture chunks by versification-mapped ref.

    Groups are only created when ≥2 chunks map to the same org ref (across
    different work_ids / languages).  Singletons are left with
    ``translation_group_id=None``.  The source is the first two components of
    ``work_id`` (``scripture/kjv/gen`` → ``scripture/kjv``); an unregistered
    source raises ``VersificationError``.
    """
    ref_to_indices: dict[str, list[int]] = defaultdict(list)
    for i, chunk in enumerate(chunks):
        if chunk.canonical_ref:
            source_id = "/".join(chunk.work_id.split("/")[:2])
            ref_to_indices[to_org_ref(source_id, chunk.canonical_ref)].append(i)

    updated: list[Chunk] = list(chunks)  # shallow copy; we'll replace items

    for ref, indices in ref_to_indices.items():
        # Singletons get None explicitly, clearing any stale group from a
        # previous run; otherwise the mapped org ref is the group ID.
        group_id = ref if len(indices) >= 2 else None
        for i in indices:
            updated[i] = updated[i].model_copy(
                update={"translation_group_id": group_id}
            )

    return updated


def rewrite_files(
    updated_chunks: list[Chunk],
    chunk_paths: list[Path],
    changed_paths: set[Path],
    force: bool = False,
) -> None:
    """Rewrite chunk JSON files whose ``translation_group_id`` values changed.

    Groups chunks by file path and overwrites each changed file once.
    """
    # Group updated chunks by their source file
    file_chunks: dict[Path, list[Chunk]] = defaultdict(list)
    for chunk, path in zip(updated_chunks, chunk_paths):
        file_chunks[path].append(chunk)

    changed = {
        path: chunks for path, chunks in file_chunks.items()
        if force or path in changed_paths
    }
    log.info("Rewriting %d of %d chunk files", len(changed), len(file_chunks))
    for path, chunks in tqdm(changed.items(), desc="rewrite"):
        # Sort by chunk_index to preserve order
        chunks.sort(key=lambda c: c.chunk_index)
        data = [c.model_dump() for c in chunks]
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def link_all(chunks_dir: Path, force: bool = False) -> int:
    """Load all chunks, assign translation groups, and rewrite files.

    Returns the number of chunks assigned a translation_group_id.
    """
    scripture_dir = chunks_dir / "scripture"
    log.info("Loading chunks from %s…", scripture_dir)
    all_chunks, chunk_paths = _load_chunks(scripture_dir)

    if not all_chunks:
        log.warning("No chunks found in %s", scripture_dir)
        return 0

    log.info("Linking translation groups across %d chunks…", len(all_chunks))
    updated = link_scripture_translations(all_chunks)

    n_linked = sum(1 for c in updated if c.translation_group_id is not None)
    log.info("%d chunks assigned a translation_group_id", n_linked)

    changed_paths = {
        path for old, new, path in zip(all_chunks, updated, chunk_paths)
        if old.translation_group_id != new.translation_group_id
    }
    rewrite_files(updated, chunk_paths, changed_paths, force=force)
    log.info("Translation linking complete")
    return n_linked


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="Assign translation_group_id across parallel chunks."
    )
    parser.add_argument("--chunks-dir", default="data/chunks")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    link_all(chunks_dir=Path(args.chunks_dir), force=args.force)


if __name__ == "__main__":
    main()
