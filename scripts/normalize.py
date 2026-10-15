"""
Normalize raw ingest output → Chunk JSON records.

Reads raw work files from ``data/raw/`` (one JSON file per book/work, each with
``{"work": {...}, "verses": [{"ref": "...", "text": "..."}]}``).

Writes one normalized JSON file per work to ``data/normalized/{source_id}/``.
Each normalized file is a JSON array of ``Chunk`` objects (without context
overlap — that is added by ``chunk.py``).  Long prose chunks are split into
verse-sized derived verses (``patristica.versify``, #2); Scripture and other
works ingested as verses keep their own verses.

Staleness (#130) is decided by fingerprints, not file times.
``_fingerprint.json`` records the hash of this step's code
(``patristica.fingerprint.code_hash``), and each ``_works.jsonl`` entry records
the hash of its raw file and of its ``genre_overrides.csv`` row.  A work is
re-normalized when any of them changed, so a code change re-runs every work
without ``--force``.  The code hash is recorded only once every work in the
manifest has been normalized with that code; a run that couldn't (raw data
missing for some source, refused works) leaves it, and
``tests/test_normalize_fingerprint.py`` keeps failing until the data is
current.

A work whose raw file differs from the one it was last normalized from is
*refused*: its output and manifest entry are kept and the run exits with an
error, so a checkout with old raw data can't silently regress tracked output
(#114, #127).  Re-run with ``--accept-raw-change`` when the raw change is
intended (a re-ingest).  ``--force`` re-normalizes every work but doesn't
override the raw guard.

Usage::

    python -m scripts.normalize [--raw-dir data/raw] [--output-dir data/normalized] [--force]
        [--accept-raw-change]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Collection, Mapping
from pathlib import Path

from tqdm import tqdm

from patristica import fingerprint
from patristica.genres import apply_genre_override, override_for
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

    Always rebuilds the work; the file is rewritten only when its content
    changes.  (Whether a work needs rebuilding is decided by ``normalize_all``
    from fingerprints; *force* is accepted for compatibility.)

    Returns the number of chunks written (0 if skipped or unchanged).
    """
    with raw_path.open(encoding="utf-8") as f:
        try:
            raw_record = json.load(f)
        except json.JSONDecodeError as exc:
            log.warning("Skipping %s: JSON error: %s", raw_path, exc)
            return 0
    return _normalize_record(raw_record, raw_path, output_dir)


def _output_rel(raw_path: Path) -> Path:
    """The normalized path of *raw_path*, relative to the output directory.

    Mirrors the raw path below its ``raw`` component, which starts with the
    source_id (``data/raw/oshb/Gen.json`` → ``oshb/Gen.json``).
    """
    parts = raw_path.parts
    try:
        raw_idx = next(i for i, p in enumerate(parts) if p == "raw")
        return Path(*parts[raw_idx + 1:])
    except StopIteration:
        return Path(raw_path.name)


def _normalize_record(raw_record: dict, raw_path: Path, output_dir: Path) -> int:
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
    # Works with a standard versification keep it: Scripture, and anything an
    # ingestor delivered as verses whatever its curated genre (#103).
    standard = work.genre == "scripture" or bool(raw_record.get("verses"))
    chunks = versify_chunks(chunks, standard=standard)

    out_path = output_dir / _output_rel(raw_path)
    content = json.dumps([chunk.model_dump() for chunk in chunks], ensure_ascii=False, indent=2)
    if out_path.exists() and out_path.read_text(encoding="utf-8") == content:
        return 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    log.debug("Normalized %d chunks → %s", len(chunks), out_path)
    return len(chunks)


# ---------------------------------------------------------------------------
# Fingerprints (#130)
# ---------------------------------------------------------------------------

STEP = "normalize"
WORKS_MANIFEST = "_works.jsonl"
FINGERPRINT_FILE = "_fingerprint.json"


class RawChangedError(RuntimeError):
    """Raw files differ from the ones their works were last normalized from."""


def normalize_code_hash() -> str:
    """Hash of the code this step runs (see ``patristica.fingerprint``)."""
    return fingerprint.code_hash("scripts.normalize")


def work_fingerprint(raw_bytes: bytes, work_id: str) -> dict[str, str]:
    """The per-work inputs of a normalized work: raw file and genre override."""
    return {
        "raw": fingerprint.sha16(raw_bytes),
        "override": fingerprint.value_hash(override_for(work_id)),
    }


def read_step_fingerprints(output_dir: Path) -> dict[str, dict]:
    """``{step: {"code": hash}}`` from ``{output_dir}/_fingerprint.json``."""
    path = output_dir / FINGERPRINT_FILE
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_step_code(output_dir: Path, code: str) -> None:
    steps = read_step_fingerprints(output_dir)
    steps[STEP] = {"code": code}
    path = output_dir / FINGERPRINT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(steps, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log.info("Recorded %s code hash %s in %s", STEP, code, path)


def read_works_manifest(output_dir: Path) -> dict[str, dict]:
    """``{path: entry}`` for every line of ``{output_dir}/_works.jsonl``."""
    manifest_path = output_dir / WORKS_MANIFEST
    entries: dict[str, dict] = {}
    if manifest_path.exists():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                entries[rec["path"]] = rec
    return entries


def normalize_all(
    raw_dir: Path,
    output_dir: Path,
    force: bool = False,
    accept_raw_change: bool = False,
) -> int:
    """Walk *raw_dir* recursively and normalize every raw work JSON file.

    A work is rebuilt when this step's code, its raw file or its genre
    override changed since it was last normalized (or with *force*).  A work
    whose raw file changed is refused unless *accept_raw_change*: it keeps
    its output and manifest entry, and ``RawChangedError`` is raised once the
    rest of the run is done.  Normalized files whose raw file is gone are
    deleted — but only inside sources whose raw directory exists
    (``data/raw`` is gitignored, so on a fresh clone without raw data
    nothing is pruned).

    Returns the total number of chunks written.
    """
    # Files and directories starting with "_" are caches and indexes
    # (``_zips``, ``_repos``, ``_volumes.json``, ``ogpg/_extract``), not works.
    json_files = sorted(
        p for p in raw_dir.rglob("*.json")
        if not any(part.startswith("_") for part in p.relative_to(raw_dir).parts)
    )

    code = normalize_code_hash()
    code_current = read_step_fingerprints(output_dir).get(STEP, {}).get("code") == code
    if not code_current:
        log.info("Code changed since the last full run: re-normalizing every work")
    previous = read_works_manifest(output_dir)
    fingerprints: dict[str, dict[str, str]] = {}
    refused: list[str] = []

    if not json_files:
        log.warning("No raw JSON files found under %s", raw_dir)
    else:
        log.info("Normalizing %d raw files…", len(json_files))
    total = 0
    for path in tqdm(json_files, desc="normalize"):
        rel = _output_rel(path).as_posix()
        raw_bytes = path.read_bytes()
        prev = previous.get(rel, {})
        prev_fp = prev.get("fingerprint")
        if prev_fp and prev_fp["raw"] != fingerprint.sha16(raw_bytes) and not accept_raw_change:
            refused.append(rel)
            continue
        if (
            not force and code_current and prev_fp and (output_dir / rel).exists()
            and prev_fp == work_fingerprint(raw_bytes, prev["work"]["work_id"])
        ):
            fingerprints[rel] = prev_fp
            continue
        try:
            raw_record = json.loads(raw_bytes)
        except json.JSONDecodeError as exc:
            log.warning("Skipping %s: JSON error: %s", path, exc)
            continue
        total += _normalize_record(raw_record, path, output_dir)
        work_id = (raw_record.get("work") or {}).get("work_id", "")
        fingerprints[rel] = work_fingerprint(raw_bytes, work_id)

    log.info("Normalization complete: %d total chunks written", total)
    _prune_orphans(raw_dir, output_dir)
    write_works_manifest(output_dir, fingerprints=fingerprints, keep=refused)

    if not code_current:
        uncovered = sorted(set(read_works_manifest(output_dir)) - set(fingerprints))
        if uncovered:
            log.error(
                "Not recording the new %s code hash: %d works were not normalized with it "
                "(no raw file here, or refused), e.g. %s",
                STEP, len(uncovered), ", ".join(uncovered[:5]),
            )
        else:
            _write_step_code(output_dir, code)
    if refused:
        raise RawChangedError(
            f"{len(refused)} raw files differ from the ones their works were last normalized "
            f"from (old or re-ingested raw data?), e.g. {', '.join(refused[:5])}. Their "
            "normalized output was kept. If the raw change is intended, re-run with "
            "--accept-raw-change."
        )
    return total



def write_works_manifest(
    output_dir: Path,
    fingerprints: Mapping[str, dict[str, str]] | None = None,
    keep: Collection[str] = (),
) -> None:
    """Maintain ``{output_dir}/_works.jsonl``: the full ``Work`` record for every
    normalized file, one JSON object per line
    (``{"fingerprint": {...}, "path": ..., "work": {...}}``).

    Normalized files hold only chunks, and ``data/raw`` is gitignored, so this
    is the tracked copy of work metadata (title, author, dates, translation_of,
    license, provenance) for Phase 2.  Entries are refreshed from the raw file
    when it exists; when it does not (fresh clone) the previous entry is kept.
    Either way the curated genre from ``patristica.genres`` is applied.
    *fingerprints* (``{path: fingerprint}``) replace the recorded ones; other
    entries keep theirs.  Entries in *keep* (refused works) are left exactly
    as they were.  Entries for normalized files that no longer exist are
    dropped.  The file is rewritten only when its content changes.
    """
    fingerprints = fingerprints or {}
    manifest_path = output_dir / WORKS_MANIFEST
    previous = read_works_manifest(output_dir)

    raw_root = output_dir.resolve().parent / "raw"
    entries: dict[str, dict] = {}
    for norm_path in sorted(output_dir.rglob("*.json")):
        if norm_path.name.startswith("_"):
            continue
        rel = norm_path.relative_to(output_dir).as_posix()
        if rel in keep and rel in previous:
            entries[rel] = previous[rel]
            continue
        raw_path = raw_root / rel
        work: dict | None = None
        if raw_path.exists():
            with raw_path.open(encoding="utf-8") as f:
                work = json.load(f).get("work")
        if work is None:
            work = previous.get(rel, {}).get("work")
        if work is None:
            log.warning("No work metadata for %s (no raw file, not in manifest)", rel)
            continue
        entry = {"path": rel, "work": apply_genre_override(work)}
        fp = fingerprints.get(rel) or previous.get(rel, {}).get("fingerprint")
        if fp:
            entry["fingerprint"] = fp
        entries[rel] = entry

    content = "".join(
        json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
        for _, entry in sorted(entries.items())
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
    parser.add_argument("--force", action="store_true",
                        help="re-normalize every work (doesn't override the raw guard)")
    parser.add_argument("--accept-raw-change", action="store_true",
                        help="normalize works whose raw file changed since they were last "
                             "normalized (after an intended re-ingest)")
    args = parser.parse_args()

    try:
        normalize_all(
            raw_dir=Path(args.raw_dir),
            output_dir=Path(args.output_dir),
            force=args.force,
            accept_raw_change=args.accept_raw_change,
        )
    except RawChangedError as exc:
        log.error("%s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
