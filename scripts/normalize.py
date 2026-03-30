"""
Normalize raw ingest output → Chunk JSON records.

Reads raw work files from ``data/raw/`` (one JSON file per book/work, each with
``{"work": {...}, "verses": [{"ref": "...", "text": "..."}]}``).

Writes one normalized JSON file per work to ``data/normalized/{source_id}/``.
Each normalized file is a JSON array of ``Chunk`` objects (without context
overlap — that is added by ``chunk.py``).

Usage::

    python -m scripts.normalize [--raw-dir data/raw] [--output-dir data/normalized] [--force]
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from tqdm import tqdm

from patristica.models import Chunk, Work

log = logging.getLogger(__name__)


def normalize_scripture_work(
    raw_record: dict,
) -> tuple[Work, list[Chunk]]:
    """Convert a raw scripture record into a ``Work`` + list of ``Chunk`` objects.

    For scripture, each verse is an atomic chunk.  Context overlap
    (``context_before`` / ``context_after``) is left ``None`` here and filled
    in by ``chunk.py``.
    """
    work = Work(**raw_record["work"])
    raw_verses: list[dict] = raw_record.get("verses", [])

    chunks: list[Chunk] = []
    for idx, verse in enumerate(raw_verses):
        ref = verse.get("ref", "")
        text = verse.get("text", "").strip()
        if not text:
            continue

        chunk = Chunk(
            chunk_id=f"{work.work_id}#{ref}",
            work_id=work.work_id,
            canonical_ref=ref,
            language=work.language,
            text=text,
            chunk_index=idx,
            context_before=None,
            context_after=None,
            date_composed=work.date_composed,
            date_range=work.date_range,
            date_confidence=work.date_confidence,
            post_schism=False,  # all canonical scripture is pre-schism
            translation_group_id=None,
        )
        chunks.append(chunk)

    return work, chunks


def normalize_file(
    raw_path: Path,
    output_dir: Path,
    force: bool = False,
) -> int:
    """Normalize a single raw JSON file and write the result.

    Returns the number of chunks written (0 if skipped).
    """
    with raw_path.open(encoding="utf-8") as f:
        try:
            raw_record = json.load(f)
        except json.JSONDecodeError as exc:
            log.warning("Skipping %s: JSON error: %s", raw_path, exc)
            return 0

    work_dict = raw_record.get("work")
    if not work_dict:
        log.debug("Skipping %s: no 'work' key", raw_path)
        return 0

    genre = work_dict.get("genre", "")
    if genre == "scripture":
        work, chunks = normalize_scripture_work(raw_record)
    else:
        # Patristic/liturgical/council normalization: implemented in M3+
        log.debug("Skipping %s: genre %r not yet supported by normalize.py", raw_path, genre)
        return 0

    if not chunks:
        log.warning("No chunks produced from %s", raw_path)
        return 0

    # Mirror the raw path structure under output_dir
    # raw:  data/raw/scripture/oshb/Gen.json
    # norm: data/normalized/scripture/oshb/Gen.json
    try:
        rel = raw_path.relative_to(raw_path.parents[3])  # strip data/raw prefix
        # rel is now something like "scripture/oshb/Gen.json" or deeper
    except ValueError:
        rel = raw_path.name

    # Determine source_id sub-path: strip the leading "raw/" component
    rel_parts = raw_path.parts
    try:
        raw_idx = next(i for i, p in enumerate(rel_parts) if p == "raw")
        sub_parts = rel_parts[raw_idx + 1:]
    except StopIteration:
        sub_parts = (raw_path.name,)

    out_path = output_dir.joinpath(*sub_parts)

    if out_path.exists() and not force:
        log.debug("Skipping %s (already normalized)", out_path)
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = [chunk.model_dump() for chunk in chunks]
    out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    log.debug("Normalized %d chunks → %s", len(chunks), out_path)
    return len(chunks)


def normalize_all(
    raw_dir: Path,
    output_dir: Path,
    force: bool = False,
) -> int:
    """Walk *raw_dir* recursively and normalize every raw work JSON file.

    Returns the total number of chunks written.
    """
    json_files = [
        p for p in raw_dir.rglob("*.json")
        if "_zips" not in p.parts and "_csvs" not in p.parts
    ]

    if not json_files:
        log.warning("No raw JSON files found under %s", raw_dir)
        return 0

    log.info("Normalizing %d raw files…", len(json_files))
    total = 0
    for path in tqdm(json_files, desc="normalize"):
        total += normalize_file(path, output_dir, force=force)

    log.info("Normalization complete: %d total chunks written", total)
    return total


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description="Normalize raw ingested data.")
    parser.add_argument("--raw-dir", default="data/raw")
    parser.add_argument("--output-dir", default="data/normalized")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    normalize_all(
        raw_dir=Path(args.raw_dir),
        output_dir=Path(args.output_dir),
        force=args.force,
    )


if __name__ == "__main__":
    main()
