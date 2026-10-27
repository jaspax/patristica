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
(``patristica.fingerprint.code_hash``), and ``_fingerprints.jsonl`` records,
per work, the hash of its raw file and of its curation (genre override, author
ids, the authors' birth year and the curated ``translation_of``, #153), and for
a work of a source enrolled for anchored derived verses (``patristica.anchoring``,
#292) its anchor: the work it is cut on and a hash of that work's cuts.  Such
works are normalized after all others, anchors first.  A work is rebuilt when
any of these changed, so a code, curation or anchor change re-runs exactly the
affected works without ``--force``.  The code hash is recorded only once every work in the manifest
was rebuilt with that code; a run that couldn't (raw data missing for some
source, refused works) leaves it, and ``tests/test_normalize_fingerprint.py``
keeps failing until the data is current.  The fingerprints are kept out of
``_works.jsonl`` because ``build_index`` hashes its lines.  The ingest stamp
of each source (``scripts.ingest._stamp``) is copied into
``_fingerprint.json`` too, so ``scripts.status`` can tell when an ingestor
changed after its data was normalized.

A work whose raw file differs from the one it was last normalized from is
*refused*: its output, manifest entry and fingerprint are kept and the run
exits with an error, so a checkout with old raw data can't silently regress
tracked output (#114, #127).  Re-run with ``--accept-raw-change`` when the raw
change is intended (a re-ingest).  ``--force`` rebuilds every work but doesn't
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
from collections.abc import Collection
from pathlib import Path

from tqdm import tqdm

from patristica import anchoring, fingerprint
from patristica.authors import (
    apply_author_date_range,
    apply_author_ids,
    resolve_author,
    work_author_birth_year,
    work_author_date_range,
)
from patristica.genres import apply_genre_override, override_for
from patristica.models import Chunk, Work
from patristica.period import is_out_of_period, work_in_period
from patristica.section_numbers import strip_section_number
from patristica.translation_links import apply_translation_of, curated_translation_of
from patristica.versify import versify_chunks

log = logging.getLogger(__name__)


def _prose_text(raw_text: str, ref: str, work: Work) -> str:
    """Clean a prose/liturgical/council paragraph's text for its chunk.

    Strips surrounding whitespace and a leading section number that repeats
    the ref's last segment ("3. …" at ``….3``, see #30).  Scripture is not
    passed through here: a verse may legitimately start with a numeral.
    """
    return strip_section_number(raw_text.strip(), ref, work.language, work.source_id)


def _work_out_of_period(work: Work) -> bool:
    """``Chunk.out_of_period`` for a scripture/patristic/apocrypha work's chunks.

    The author's birth year (author index, #82) decides when known: a work by
    an author born before ``AUTHOR_BORN_BEFORE`` is in period whatever its
    date, and one by an author born after it is flagged throughout (and
    logged, since such a work should not have been ingested).  Otherwise the
    composition date decides.
    """
    birth = work_author_birth_year(work.author_ids)
    if not work_in_period(work.date_range, author_birth_year=birth):
        log.warning(
            "%s is out of period (author born %s); all its chunks are flagged",
            work.work_id, birth,
        )
    return is_out_of_period(work.date_composed, work.date_range, author_birth_year=birth)


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
    out_of_period = _work_out_of_period(work)

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

    out_of_period = _work_out_of_period(work)

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
    return _normalize_record(raw_record, raw_path, output_dir) or 0


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


def _normalize_record(raw_record: dict, raw_path: Path, output_dir: Path,
                      anchor: anchoring.Anchor | None = None) -> int | None:
    """Build and write one work: the number of chunks written (0 when the file
    was already identical), or None when the record produced no output (not a
    work, a genre normalize doesn't handle, or no chunks).

    With *anchor* (a work of an enrolled source, ``patristica.anchoring``,
    #292), its derived verses are cut on the anchor's."""
    work_dict = raw_record.get("work")
    if not work_dict:
        log.debug("Skipping %s: no 'work' key", raw_path)
        return None

    work_dict = apply_translation_of(apply_author_ids(apply_genre_override(work_dict)))
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
        return None

    if not chunks:
        log.warning("No chunks produced from %s", raw_path)
        return None
    # Works with a standard versification keep it: Scripture, and anything an
    # ingestor delivered as verses whatever its curated genre (#103).
    standard = work.genre == "scripture" or bool(raw_record.get("verses"))
    units_of = None
    if anchor is not None and not standard:
        units_of = anchoring.anchored_units(chunks, anchor)
        if units_of is None:
            log.info("%s: anchor %s is in its own language; cut as today (#199)",
                     work.work_id, anchor.work_id)
    chunks = versify_chunks(chunks, standard=standard, units_of=units_of)

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
FINGERPRINT_FILE = "_fingerprint.json"     # {step: {"code": hash}}
FINGERPRINTS_FILE = "_fingerprints.jsonl"  # one {"path", "raw", "curated"[, "anchor"]} per work


class RawChangedError(RuntimeError):
    """Raw files differ from the ones their works were last normalized from."""


class FailedWorksError(RuntimeError):
    """Works that were to be rebuilt produced no output (empty or unreadable raw)."""


def normalize_code_hash() -> str:
    """Hash of the code this step runs (see ``patristica.fingerprint``)."""
    return fingerprint.code_hash("scripts.normalize")


def curated_hash(work: dict) -> str:
    """Hash of the curation applied to *work* (a raw or manifest work record).

    Covers the curated genre (``genre_overrides.csv``), the author ids
    resolved from ``author``, the authors' birth year and, for an undated work,
    their activity range (``authors.csv``, ``author_strings.csv``), and a
    curated ``translation_of`` (``patristica.translation_links``): the inputs
    that change a work's chunks or manifest entry without changing its raw
    file.  It is computed from the override, the author string and the work's
    own dates, not from the curated record, so it can be checked from
    ``_works.jsonl`` without raw data.
    """
    ids = resolve_author(work.get("author"))
    curation = {
        "genre": override_for(work.get("work_id", "")),
        "author_ids": ids,
        "birth_year": work_author_birth_year(ids),
    }
    # Only works that get one (#151), so the others keep their hash.
    derived = work_author_date_range({**work, "author_ids": ids})
    if derived is not None:
        curation["author_date_range"] = list(derived)
    # Likewise only works with a curated link (#153).
    translation_of = curated_translation_of(work.get("work_id", ""))
    if translation_of is not None:
        curation["translation_of"] = translation_of
    return fingerprint.value_hash(curation)


def work_fingerprint(raw_bytes: bytes, work: dict, anchor: dict | None = None) -> dict:
    """The per-work inputs of a normalized work: its raw file and curation, and
    for a work of an enrolled source its anchor record (``anchor_record``)."""
    fp: dict = {"raw": fingerprint.sha16(raw_bytes), "curated": curated_hash(work)}
    if anchor is not None:
        fp["anchor"] = anchor
    return fp


def source_of(rel: str) -> str:
    """The source id of a normalized path (``ogpg/vol-032/epistulae.json`` → ``ogpg``)."""
    return rel.split("/", 1)[0]


def load_anchor(work: dict, output_dir: Path, paths: dict[str, str]) -> anchoring.Anchor | None:
    """The anchor of an enrolled *work* (``patristica.anchoring``), read from its
    normalized output, or None: no ``translation_of``, or the anchor isn't in
    the corpus (*paths*: work id → normalized path)."""
    target = anchoring.anchor_id(apply_translation_of(work))
    if target is None or target not in paths or not (output_dir / paths[target]).exists():
        return None
    return anchoring.Anchor.load(output_dir / paths[target], target)


def anchor_record(work: dict, output_dir: Path, paths: dict[str, str]) -> dict:
    """What ``_fingerprints.jsonl`` records about an enrolled work's anchor:
    ``{"work_id", "cuts"}`` (``anchoring.Anchor.record``), both None when it
    has none. It changes whenever the anchor's cuts or text change, so the work
    is re-split (#292)."""
    anchor = load_anchor(work, output_dir, paths)
    return anchor.record() if anchor is not None else dict(anchoring.UNANCHORED)


def anchor_order(works: dict[str, dict]) -> list[str]:
    """The paths of *works* (``path → work``, all enrolled) so that a work comes
    after any of them it is anchored on. Raises ``AnchoringError`` on a cycle."""
    by_id = {w.get("work_id"): rel for rel, w in works.items()}
    order: list[str] = []
    state: dict[str, int] = {}  # 1 visiting, 2 done

    def visit(rel: str, chain: tuple[str, ...]) -> None:
        if state.get(rel) == 2:
            return
        if state.get(rel) == 1:
            raise anchoring.AnchoringError(f"anchor cycle: {' → '.join([*chain, rel])}")
        state[rel] = 1
        target = anchoring.anchor_id(apply_translation_of(works[rel]))
        if target in by_id:
            visit(by_id[target], (*chain, rel))
        state[rel] = 2
        order.append(rel)

    for rel in sorted(works):
        visit(rel, ())
    return order


def read_step_fingerprints(output_dir: Path) -> dict[str, dict]:
    """``{step: {"code": hash}}`` from ``{output_dir}/_fingerprint.json``."""
    path = output_dir / FINGERPRINT_FILE
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_step_code(output_dir: Path, code: str | None) -> None:
    """Record *code* as the code every work was built with; None removes it."""
    steps = read_step_fingerprints(output_dir)
    if code is None:
        if STEP not in steps:
            return
        del steps[STEP]
    else:
        steps[STEP] = {"code": code}
    path = output_dir / FINGERPRINT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(steps, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if code is not None:
        log.info("Recorded %s code hash %s in %s", STEP, code, path)


#: Written next to a source's raw data by ``scripts.ingest._stamp`` (read here
#: as plain JSON, so the ingest machinery isn't part of normalize's code).
INGEST_STAMP = "_ingest.json"


def _record_ingest_stamps(output_dir: Path, json_files: list[Path], visited: Collection[str],
                          listed: Collection[str]) -> None:
    """Copy each normalized source's ingest stamp into ``_fingerprint.json``.

    ``{"ingest": {source_id: ingestor code hash}}`` tells ``scripts.status``
    which ingestor code the tracked data comes from. The entry changes only when
    this run rebuilt or confirmed (*visited*) every listed work of the source:
    a source with a refused or failed work, or one normalized only in part
    (``--raw-dir data/raw/ogpg/vol-001``), keeps its old entry, since some of
    its data wasn't made from this raw. A fully visited source whose raw has no
    stamp loses its entry (unknown).
    """
    sources: dict[str, Path] = {}
    for path in json_files:
        parts = path.parts
        if "raw" in parts:
            i = parts.index("raw")
            if len(parts) > i + 2:
                sources[parts[i + 1]] = Path(*parts[: i + 2])
    blocked = {rel.split("/", 1)[0] for rel in listed if rel not in visited}
    steps = read_step_fingerprints(output_dir)
    stamps = dict(steps.get("ingest", {}))
    for source, source_dir in sources.items():
        if source in blocked:
            continue
        stamp = source_dir / INGEST_STAMP
        if stamp.exists():
            stamps[source] = json.loads(stamp.read_text(encoding="utf-8"))["code"]
        else:
            stamps.pop(source, None)
    if stamps != steps.get("ingest", {}):
        steps["ingest"] = dict(sorted(stamps.items()))
        if not steps["ingest"]:
            del steps["ingest"]
        path = output_dir / FINGERPRINT_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(steps, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_work_fingerprints(output_dir: Path) -> dict[str, dict]:
    """``{path: {"raw", "curated"[, "anchor"]}}`` from ``{output_dir}/_fingerprints.jsonl``."""
    path = output_dir / FINGERPRINTS_FILE
    fps: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                fps[rec.pop("path")] = rec
    return fps


def _write_work_fingerprints(output_dir: Path, fps: dict[str, dict]) -> None:
    content = "".join(
        json.dumps({"path": rel, **fps[rel]}, sort_keys=True) + "\n" for rel in sorted(fps)
    )
    path = output_dir / FINGERPRINTS_FILE
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        path.write_text(content, encoding="utf-8")
        log.info("Wrote %s (%d works)", path, len(fps))


def read_works_manifest(output_dir: Path) -> dict[str, dict]:
    """``{path: work}`` for every line of ``{output_dir}/_works.jsonl``."""
    manifest_path = output_dir / WORKS_MANIFEST
    works: dict[str, dict] = {}
    if manifest_path.exists():
        for line in manifest_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rec = json.loads(line)
                works[rec["path"]] = rec["work"]
    return works


def normalize_all(
    raw_dir: Path,
    output_dir: Path,
    force: bool = False,
    accept_raw_change: bool = False,
) -> int:
    """Walk *raw_dir* recursively and normalize every raw work JSON file.

    A work is rebuilt when this step's code, its raw file or its curation
    changed since it was last normalized (or with *force*).  A work whose raw
    file changed is refused unless *accept_raw_change*: it keeps its output,
    manifest entry and fingerprint, and ``RawChangedError`` is raised once the
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
        log.info("normalize's code changed since the last full run: rebuilding every work")
        # Outputs about to be written under this code no longer match the
        # recorded hash; until every work is rebuilt, none is recorded (so a
        # revert of the code can't make half-rebuilt data look current).
        _write_step_code(output_dir, None)
    works = read_works_manifest(output_dir)
    previous = read_work_fingerprints(output_dir)
    fingerprints: dict[str, dict] = {}  # works built or confirmed this run
    refused: list[str] = []
    failed: list[str] = []  # works to rebuild that produced no output

    if not json_files:
        log.warning("No raw JSON files found under %s", raw_dir)
    else:
        log.info("Normalizing %d raw files…", len(json_files))
    total = 0
    paths = {w.get("work_id"): rel for rel, w in works.items()}  # work id → normalized path

    def visit(path: Path, rel: str, raw_bytes: bytes, raw_record: dict | None) -> None:
        nonlocal total
        prev = previous.get(rel)
        if prev and prev["raw"] != fingerprint.sha16(raw_bytes) and not accept_raw_change:
            refused.append(rel)
            return
        record = None  # the anchor record, for a work of an enrolled source
        if anchoring.is_enrolled(source_of(rel)):
            work = raw_record.get("work") if isinstance(raw_record, dict) else None
            record = anchor_record(work or works.get(rel) or {}, output_dir, paths)
        if (
            not force and code_current and prev and rel in works and (output_dir / rel).exists()
            and prev == work_fingerprint(raw_bytes, works[rel], record)
        ):
            fingerprints[rel] = prev
            return
        if raw_record is None:
            try:
                raw_record = json.loads(raw_bytes)
            except json.JSONDecodeError as exc:
                log.warning("Skipping %s: JSON error: %s", path, exc)
        anchor = None
        if record is not None and isinstance(raw_record, dict) and raw_record.get("work"):
            anchor = load_anchor(raw_record["work"], output_dir, paths)
        if not isinstance(raw_record, dict):
            written = None
        elif anchor is not None:
            written = _normalize_record(raw_record, path, output_dir, anchor=anchor)
        else:
            written = _normalize_record(raw_record, path, output_dir)
        if written is None:
            # No output: a file that never was a work (a catalogue) is
            # ignored; a work's old output must not pass as built from this raw.
            if prev or rel in works:
                failed.append(rel)
            return
        total += written
        paths[raw_record["work"].get("work_id")] = rel
        fingerprints[rel] = work_fingerprint(raw_bytes, raw_record["work"], record)

    # Works of enrolled sources (anchored derived verses, #292) come last, so
    # that their anchors are built first, and in anchor order among themselves.
    deferred: dict[str, tuple[Path, bytes, dict | None]] = {}
    for path in tqdm(json_files, desc="normalize"):
        rel = _output_rel(path).as_posix()
        raw_bytes = path.read_bytes()
        if anchoring.is_enrolled(source_of(rel)):
            try:
                raw_record = json.loads(raw_bytes)
            except json.JSONDecodeError:
                raw_record = None
            deferred[rel] = (path, raw_bytes, raw_record if isinstance(raw_record, dict) else None)
            continue
        visit(path, rel, raw_bytes, None)
    if deferred:
        order = anchor_order({
            rel: (rec or {}).get("work") or works.get(rel) or {}
            for rel, (_, _, rec) in deferred.items()})
        for rel in tqdm(order, desc="normalize (anchored)"):
            path, raw_bytes, raw_record = deferred[rel]
            visit(path, rel, raw_bytes, raw_record)

    log.info("Normalization complete: %d total chunks written", total)
    _prune_orphans(raw_dir, output_dir)
    write_works_manifest(output_dir, keep=refused, refresh=set(fingerprints))
    listed = read_works_manifest(output_dir)
    _write_work_fingerprints(
        output_dir,
        {rel: fingerprints.get(rel) or previous[rel] for rel in listed
         if rel in fingerprints or (rel in previous and rel not in failed)},
    )

    _record_ingest_stamps(output_dir, json_files, set(fingerprints), set(listed))
    if not code_current:
        uncovered = sorted(set(listed) - set(fingerprints))
        if uncovered:
            log.error(
                "Not recording the new %s code hash: %d works were not rebuilt with it "
                "(no raw file here, refused or failed), e.g. %s",
                STEP, len(uncovered), ", ".join(uncovered[:5]),
            )
        else:
            _write_step_code(output_dir, code)
    if failed:
        log.error("%d works produced no output from their raw file (empty or unreadable), so "
                  "their old output was kept and their fingerprint removed: fix the raw data "
                  "or the ingestor, e.g. %s", len(failed), ", ".join(failed[:5]))
    if refused:
        raise RawChangedError(
            f"{len(refused)} raw files differ from the ones their works were last normalized "
            f"from (old or re-ingested raw data?), e.g. {', '.join(refused[:5])}. Their "
            "normalized output was kept. If the raw change is intended, re-run with "
            "--accept-raw-change."
        )
    if failed:
        raise FailedWorksError(
            f"{len(failed)} works produced no output from their raw file, e.g. "
            f"{', '.join(failed[:5])}; their old output was kept, without a fingerprint."
        )
    return total


def write_works_manifest(
    output_dir: Path, raw_root: Path | None = None, keep: Collection[str] = (),
    refresh: Collection[str] | None = None,
) -> None:
    """Maintain ``{output_dir}/_works.jsonl``: the full ``Work`` record for every
    normalized file, one JSON object per line (``{"path": ..., "work": {...}}``).

    Normalized files hold only chunks, and ``data/raw`` is gitignored, so this
    is the tracked copy of work metadata (title, author, dates, translation_of,
    license, provenance) for Phase 2.  Entries are refreshed from the raw file
    when it exists; when it does not (fresh clone) the previous entry is kept.
    Either way the curated genre from ``patristica.genres`` is applied and
    ``author_ids`` is resolved from ``author`` (``patristica.authors``, #82),
    an undated work gets its authors' ``author_date_range`` (#151), and the
    curated ``translation_of`` is applied (``patristica.translation_links``, #153).
    An empty ``external_ids`` is left out.  *raw_root* defaults to the
    ``raw`` directory next to *output_dir*.  Entries in *keep* (works whose raw
    change normalize refused) are left as they were.  With *refresh*, only those
    works are refreshed from their raw file; the others keep their previous
    entry (with the curation applied), so a run over part of ``data/raw``
    can't pick up unchecked raw metadata of other sources.
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

    if raw_root is None:
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
        if refresh is not None and rel not in refresh and rel in previous:
            work = previous[rel]
        elif raw_path.exists():
            with raw_path.open(encoding="utf-8") as f:
                work = json.load(f).get("work")
        if work is None:
            work = previous.get(rel)
        if work is None:
            log.warning("No work metadata for %s (no raw file, not in manifest)", rel)
            continue
        work = apply_translation_of(
            apply_author_date_range(apply_author_ids(apply_genre_override(work))))
        if not work.get("external_ids", True):
            # Only sources that record catalogue ids carry the field (#178), so
            # adding it to Work doesn't rewrite every manifest entry.
            work = {k: v for k, v in work.items() if k != "external_ids"}
        entries[rel] = work

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
    parser.add_argument("--force", action="store_true",
                        help="rebuild every work (doesn't override the raw guard)")
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
    except (RawChangedError, FailedWorksError) as exc:
        log.error("%s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
