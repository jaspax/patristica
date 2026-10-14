"""
Normalize raw ingest output → Chunk JSON records.

Reads raw work files from ``data/raw/`` (one JSON file per book/work, each with
``{"work": {...}, "verses": [{"ref": "...", "text": "..."}]}``).

Writes one normalized JSON file per work to ``data/normalized/{source_id}/``.
Each normalized file is a JSON array of ``Chunk`` objects (without context
overlap — that is added by ``chunk.py``).  Long prose chunks are split into
verse-sized derived verses (``patristica.versify``, #2); Scripture keeps its
own verses.

Usage::

    python -m scripts.normalize [--raw-dir data/raw] [--output-dir data/normalized] [--force]
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from tqdm import tqdm

from patristica.genres import apply_genre_override
from patristica.models import Chunk, Work
from patristica.period import is_out_of_period
from patristica.section_numbers import strip_section_number
from patristica.versify import versify_chunks

log = logging.getLogger(__name__)


def _prose_text(raw_text: str, ref: str, work: Work) -> str:
    """Clean a prose/liturgical/council paragraph's text for its chunk.

    Strips surrounding whitespace and a leading section number that repeats
    the ref's last segment ("3. …" at ``….3``, see #30).  Scripture is not
    passed through here: a verse may legitimately start with a numeral.
    """
    return strip_section_number(raw_text.strip(), ref, work.language, work.source_id)


def _units(raw_record: dict) -> list[dict]:
    """The raw record's text units: ``"verses"`` or ``"paragraphs"``.

    Ingestors pick the key from the genre they assign, and a curated genre
    (``patristica.genres``) may differ from it, so either key is accepted.
    """
    return raw_record.get("verses") or raw_record.get("paragraphs") or []


def normalize_scripture_work(
    raw_record: dict,
) -> tuple[Work, list[Chunk]]:
    """Convert a raw scripture record into a ``Work`` + list of ``Chunk`` objects.

    For scripture, each verse is an atomic chunk.  Context overlap
    (``context_before`` / ``context_after``) is left ``None`` here and filled
    in by ``chunk.py``.
    """
    work = Work(**raw_record["work"])
    raw_verses: list[dict] = _units(raw_record)
    # Canonical books are all in period; computed rather than assumed so a
    # late extra-canonical book (e.g. Ethiopic) is flagged by its date.
    out_of_period = is_out_of_period(work.date_composed, work.date_range)

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
            out_of_period=out_of_period,
            translation_group_id=None,
        )
        chunks.append(chunk)

    return work, chunks


def normalize_liturgical_work(
    raw_record: dict,
) -> tuple[Work, list[Chunk]]:
    """Convert a raw liturgical record into a ``Work`` + list of ``Chunk`` objects.

    Liturgical texts use the ``"paragraphs"`` key (same layout as patristic).
    ``out_of_period`` is always ``False``: even when the manuscript is late, the
    underlying chant/prayer tradition is first-millennium in origin.
    """
    work = Work(**raw_record["work"])
    raw_paragraphs: list[dict] = _units(raw_record)

    chunks: list[Chunk] = []
    for idx, para in enumerate(raw_paragraphs):
        ref = para.get("ref", "")
        text = _prose_text(para.get("text", ""), ref, work)
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
            out_of_period=False,
            translation_group_id=None,
        )
        chunks.append(chunk)

    return work, chunks


def normalize_patristic_work(
    raw_record: dict,
) -> tuple[Work, list[Chunk]]:
    """Convert a raw patristic or apocrypha record into a ``Work`` + ``Chunk`` list.

    For patristic prose, each paragraph is a chunk.  Context overlap
    (``context_before`` / ``context_after``) is left ``None`` here and filled
    in by ``chunk.py``.
    """
    work = Work(**raw_record["work"])
    raw_paragraphs: list[dict] = _units(raw_record)

    out_of_period = is_out_of_period(work.date_composed, work.date_range)

    chunks: list[Chunk] = []
    for idx, para in enumerate(raw_paragraphs):
        ref = para.get("ref", "")
        text = _prose_text(para.get("text", ""), ref, work)
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
            out_of_period=out_of_period,
            translation_group_id=None,
        )
        chunks.append(chunk)

    return work, chunks


def normalize_council_work(
    raw_record: dict,
) -> tuple[Work, list[Chunk]]:
    """Convert a raw council record into a Work + list of Chunk objects.

    All council texts are first-millennium (out_of_period=False).
    """
    work = Work(**raw_record["work"])
    raw_paragraphs: list[dict] = _units(raw_record)

    chunks: list[Chunk] = []
    for idx, para in enumerate(raw_paragraphs):
        ref = para.get("ref", "")
        text = _prose_text(para.get("text", ""), ref, work)
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
            out_of_period=False,
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

    work_dict = apply_genre_override(work_dict)
    raw_record = {**raw_record, "work": work_dict}
    genre = work_dict.get("genre", "")
    if genre == "scripture":
        work, chunks = normalize_scripture_work(raw_record)
    elif genre in ("patristic", "apocrypha"):
        work, chunks = normalize_patristic_work(raw_record)
    elif genre == "liturgical":
        work, chunks = normalize_liturgical_work(raw_record)
    elif genre == "council":
        work, chunks = normalize_council_work(raw_record)
    else:
        log.debug("Skipping %s: genre %r not yet supported by normalize.py", raw_path, genre)
        return 0

    if not chunks:
        log.warning("No chunks produced from %s", raw_path)
        return 0
    chunks = versify_chunks(chunks, work.genre)

    # Mirror the raw path structure under output_dir
    # raw:  data/raw/oshb/Gen.json
    # norm: data/normalized/oshb/Gen.json
    # The path below the "raw" component starts with the source_id.
    rel_parts = raw_path.parts
    try:
        raw_idx = next(i for i, p in enumerate(rel_parts) if p == "raw")
        sub_parts = rel_parts[raw_idx + 1:]
    except StopIteration:
        sub_parts = (raw_path.name,)

    out_path = output_dir.joinpath(*sub_parts)

    if (
        not force
        and out_path.exists()
        and out_path.stat().st_mtime >= raw_path.stat().st_mtime
    ):
        log.debug("Skipping %s (up to date)", out_path)
        return 0

    content = json.dumps([chunk.model_dump() for chunk in chunks], ensure_ascii=False, indent=2)
    if out_path.exists() and out_path.read_text(encoding="utf-8") == content:
        out_path.touch()  # mark up to date without changing content
        return 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    log.debug("Normalized %d chunks → %s", len(chunks), out_path)
    return len(chunks)


def normalize_all(
    raw_dir: Path,
    output_dir: Path,
    force: bool = False,
) -> int:
    """Walk *raw_dir* recursively and normalize every raw work JSON file.

    Outputs are rebuilt when their raw file is newer.  Normalized files whose
    raw file is gone are deleted — but only inside sources whose raw directory
    exists (``data/raw`` is gitignored, so on a fresh clone without raw data
    nothing is pruned).

    Returns the total number of chunks written.
    """
    # Files and directories starting with "_" are caches and indexes
    # (``_zips``, ``_repos``, ``_volumes.json``, ``ogpg/_extract``), not works.
    json_files = [
        p for p in raw_dir.rglob("*.json")
        if not any(part.startswith("_") for part in p.relative_to(raw_dir).parts)
    ]

    if not json_files:
        log.warning("No raw JSON files found under %s", raw_dir)
        _prune_orphans(raw_dir, output_dir)  # a source emptied by its ingestor
        write_works_manifest(output_dir)
        return 0

    log.info("Normalizing %d raw files…", len(json_files))
    total = 0
    for path in tqdm(json_files, desc="normalize"):
        total += normalize_file(path, output_dir, force=force)

    log.info("Normalization complete: %d total chunks written", total)
    _prune_orphans(raw_dir, output_dir)
    write_works_manifest(output_dir)
    return total


WORKS_MANIFEST = "_works.jsonl"


def write_works_manifest(output_dir: Path) -> None:
    """Maintain ``{output_dir}/_works.jsonl``: the full ``Work`` record for every
    normalized file, one JSON object per line (``{"path": ..., "work": {...}}``).

    Normalized files hold only chunks, and ``data/raw`` is gitignored, so this
    is the tracked copy of work metadata (title, author, dates, translation_of,
    license, provenance) for Phase 2.  Entries are refreshed from the raw file
    when it exists; when it does not (fresh clone) the previous entry is kept.
    Either way the curated genre from ``patristica.genres`` is applied.
    Entries for normalized files that no longer exist are dropped.  The file is
    rewritten only when its content changes.
    """
    manifest_path = output_dir / WORKS_MANIFEST
    previous: dict[str, dict] = {}
    if manifest_path.exists():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                previous[rec["path"]] = rec["work"]

    raw_root = output_dir.resolve().parent / "raw"
    entries: dict[str, dict] = {}
    for norm_path in sorted(output_dir.rglob("*.json")):
        if norm_path.name.startswith("_"):
            continue
        rel = norm_path.relative_to(output_dir).as_posix()
        raw_path = raw_root / rel
        work: dict | None = None
        if raw_path.exists():
            with raw_path.open(encoding="utf-8") as f:
                work = json.load(f).get("work")
        if work is None:
            work = previous.get(rel)
        if work is None:
            log.warning("No work metadata for %s (no raw file, not in manifest)", rel)
            continue
        entries[rel] = apply_genre_override(work)

    content = "".join(
        json.dumps({"path": rel, "work": work}, ensure_ascii=False, sort_keys=True) + "\n"
        for rel, work in sorted(entries.items())
    )
    if not manifest_path.exists() or manifest_path.read_text(encoding="utf-8") != content:
        manifest_path.write_text(content, encoding="utf-8")
        log.info("Wrote %s (%d works)", manifest_path, len(entries))

def _prune_orphans(raw_dir: Path, output_dir: Path) -> None:
    """Delete normalized files under *raw_dir*'s mirror whose raw file is gone."""
    parts = raw_dir.resolve().parts
    if "raw" not in parts:
        return
    raw_root = Path(*parts[: len(parts) - parts[::-1].index("raw")])
    sub = raw_dir.resolve().relative_to(raw_root)
    removed = 0
    for norm_path in (output_dir / sub).rglob("*.json"):
        rel = norm_path.relative_to(output_dir)
        if norm_path.name.startswith("_") or len(rel.parts) < 2:
            continue
        source_dir = raw_root / rel.parts[0]
        if source_dir.is_dir() and not (raw_root / rel).exists():
            norm_path.unlink()
            removed += 1
    if removed:
        log.info("Removed %d normalized files whose raw source is gone", removed)


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
