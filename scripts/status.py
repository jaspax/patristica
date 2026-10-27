"""
Freshness of every pipeline step, in one table (#130).

Each step already records what it was built from (normalize and align a code
hash and per-work or per-group input hashes; translations and vectors the hash
of the text they were made from). This compares those records with the
current code and data and reports, per step, what is stale or pending. It runs
nothing: the steps are run by hand where they can run (see CLAUDE.md "Stale
data").

Levels:

- ``fail``: tracked data doesn't match this branch's code or curated data. The
  same checks are pytest tests (``tests/test_normalize_fingerprint.py``,
  ``tests/test_align_fingerprint.py``), so CI and the pre-push hook fail too.
- ``warn``: work is pending that CI can't do (paid steps, local data), or
  local data differs from what the tracked output was made from.
- ``ok``.

Checks that need local data run only when asked: ``--raw`` compares
``data/raw`` with normalize's raw hashes (the works normalize would refuse);
``--vectors`` loads ``data/embeddings`` (8 GB) for the units still to embed and
the alignment groups whose inputs changed or that align would refuse; ``--db``
connects to the search database (``DATABASE_URL``; on the droplet through
``infra/db-tunnel.sh``) for build_index's code hash and, with ``--vectors``,
the works it would reload, apart from those it would only update in place
(metadata, #234).

Usage::

    uv run python -m scripts.status [--raw] [--vectors] [--db [URL]] [--check] [--summary FILE]
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from patristica import alignment_store as store
from patristica import fingerprint
from patristica import translations as tr
from patristica.corpus import load_works

log = logging.getLogger(__name__)

NORMALIZED = Path("data/normalized")
RAW = Path("data/raw")
TRANSLATIONS = tr.DEFAULT_DIR
EMBEDDINGS = Path("data/embeddings")
ALIGNMENTS = store.DEFAULT_DIR


@dataclass
class Row:
    step: str
    check: str
    level: str  # ok | warn | fail
    detail: str


def _examples(items: list[str], n: int = 3) -> str:
    more = f", … (+{len(items) - n})" if len(items) > n else ""
    return ", ".join(items[:n]) + more


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------


def normalize_code_current(norm: Path = NORMALIZED) -> bool:
    from scripts import normalize as nz

    recorded = nz.read_step_fingerprints(norm).get(nz.STEP, {}).get("code")
    return recorded == nz.normalize_code_hash()


def unfingerprinted_works(norm: Path = NORMALIZED) -> list[str]:
    """Works in ``_works.jsonl`` without a fingerprint (and fingerprints without a work)."""
    from scripts import normalize as nz

    works, fps = nz.read_works_manifest(norm), nz.read_work_fingerprints(norm)
    return sorted(set(works) ^ set(fps))


def curation_stale_works(norm: Path = NORMALIZED) -> list[str]:
    """Works whose genre override or author resolution changed since normalize ran."""
    from scripts import normalize as nz

    works, fps = nz.read_works_manifest(norm), nz.read_work_fingerprints(norm)
    return sorted(p for p, w in works.items()
                  if p in fps and fps[p]["curated"] != nz.curated_hash(w))


def anchor_stale_works(norm: Path = NORMALIZED) -> list[str]:
    """Works whose anchor record (#292) doesn't match their anchor's current cuts.

    A work of a source enrolled for anchored derived verses
    (``patristica.anchoring``) records the work it was cut on and a hash of
    that work's cuts; after the anchor changes, normalize must re-split it.
    A record on a work of a source that is no longer enrolled is stale too.
    """
    from patristica import anchoring
    from scripts import normalize as nz

    works, fps = nz.read_works_manifest(norm), nz.read_work_fingerprints(norm)
    paths = {w.get("work_id"): p for p, w in works.items()}
    stale: list[str] = []
    for p, w in works.items():
        if p not in fps:
            continue
        recorded = fps[p].get("anchor")
        if anchoring.is_enrolled(nz.source_of(p)):
            if recorded != nz.anchor_record(w, norm, paths):
                stale.append(p)
        elif recorded is not None:
            stale.append(p)
    return sorted(stale)


def manifest_mismatch(norm: Path = NORMALIZED) -> tuple[list[str], list[str]]:
    """(normalized files not in ``_works.jsonl``, manifest entries with no file)."""
    from scripts import normalize as nz

    files = {p.relative_to(norm).as_posix() for p in norm.rglob("*.json")
             if not p.name.startswith("_")}
    listed = set(nz.read_works_manifest(norm))
    return sorted(files - listed), sorted(listed - files)


def _is_work(path: Path) -> bool:
    """Whether a raw JSON file is a work record (normalize skips anything else)."""
    try:
        record = json.loads(path.read_bytes())
    except ValueError:
        return False
    return isinstance(record, dict) and bool(record.get("work"))


def raw_changes(norm: Path = NORMALIZED, raw: Path = RAW) -> tuple[list[str], list[str]]:
    """(works whose local raw differs from what they were built from, raw files
    with no normalized work yet). Needs ``data/raw``."""
    from scripts import normalize as nz

    fps = nz.read_work_fingerprints(norm)
    changed, new = [], []
    for path in sorted(raw.rglob("*.json")):
        if any(part.startswith("_") for part in path.relative_to(raw).parts):
            continue
        rel = path.relative_to(raw).as_posix()
        if rel not in fps:
            if _is_work(path):  # not catalogue/metadata files normalize skips
                new.append(rel)
        elif fps[rel]["raw"] != fingerprint.sha16(path.read_bytes()):
            changed.append(rel)
    return changed, new


def ingest_drift(norm: Path = NORMALIZED) -> tuple[list[str], list[str]]:
    """(sources whose ingestor changed since their data was normalized, sources
    with no ingest stamp recorded)."""
    from scripts import normalize as nz
    from scripts.ingest import _stamp

    recorded = nz.read_step_fingerprints(norm).get("ingest", {})
    sources = sorted({w["source_id"] for w in nz.read_works_manifest(norm).values()})
    drift = [s for s in sources if s in recorded and recorded[s] != _stamp.ingest_code_hash(s)]
    return drift, [s for s in sources if s not in recorded]


# ---------------------------------------------------------------------------
# align
# ---------------------------------------------------------------------------


def align_code_current(align_dir: Path = ALIGNMENTS) -> bool:
    from scripts import align

    recorded = align.read_fingerprint(align_dir).get(align.STEP, {}).get("code")
    return recorded == align.align_code_hash()


def stale_groups(norm: Path = NORMALIZED, align_dir: Path = ALIGNMENTS) -> dict[str, str]:
    """Version groups whose tracked alignment is stale, with the reason
    (``scripts.align.check_groups``: new groups, changed members or Scripture
    refs, missing files, records of groups no longer aligned)."""
    from scripts import align

    return align.check_groups(norm, align_dir)


def alignments_with_changed_units(norm: Path = NORMALIZED,
                                  align_dir: Path = ALIGNMENTS) -> list[str]:
    """Alignment files with a member whose chunk ids changed since it was aligned
    (consumers drop that member until ``scripts.align`` runs again)."""
    paths = {e["work"]["work_id"]: e["path"] for e in load_works(norm)}
    stale = []
    for path, a in store.iter_store(align_dir):
        for wid, m in a.members.items():
            if wid not in paths or not (norm / paths[wid]).exists():
                stale.append(a.group)
                break
            chunks = json.loads((norm / paths[wid]).read_text(encoding="utf-8"))
            if m.ids != store.ids_sha([c["chunk_id"] for c in chunks]):
                stale.append(a.group)
                break
    return stale


def align_drift(norm: Path, trans: Path, vecs: Path, align_dir: Path) -> Counter[str]:
    """What ``scripts.align`` would do now, by outcome (needs the vectors)."""
    from scripts import align

    jobs, _, _ = align.make_jobs(norm, trans, vecs, align_dir, dry_run=True)
    counts: Counter[str] = Counter()
    with align.make_pool(max(1, (os.cpu_count() or 2) // 2)) as pool:
        for _, outcome in pool.map(align.run_job, jobs):
            counts[outcome.split(":", 1)[0]] += 1
    return counts


# ---------------------------------------------------------------------------
# Paid steps
# ---------------------------------------------------------------------------


def pending_translations(norm: Path = NORMALIZED,
                         trans: Path = TRANSLATIONS) -> tuple[dict[str, int], float]:
    """Units still to translate, by language, and the estimated cost in dollars.

    Units whose identical text is already translated elsewhere are reused by
    ``scripts.translate`` for free and aren't counted.
    """
    from scripts import translate

    jobs, _ = translate.plan(norm, trans, sorted(tr.TRANSLATED_LANGUAGES), [], False)
    by_lang: Counter[str] = Counter()
    for job in jobs:
        by_lang[job.language] += sum(len(g) for g in job.groups)
    return dict(by_lang), sum(by_lang.values()) * translate.COST_PER_CHUNK


def pending_vectors(norm: Path, trans: Path, vecs: Path) -> tuple[int, float]:
    """Vectors still to embed and the estimated cost in dollars (needs the vectors)."""
    from scripts import embed

    stats = embed.run(norm, vecs, trans, dry_run=True)
    return stats.to_embed, stats.est_tokens / 1e6 * embed.PRICE_PER_MTOK


def db_rows(url: str, norm: Path, trans: Path, vecs: Path | None,
            align_dir: Path) -> list[Row]:
    """build_index's code hash and, with the vectors, what a run would change."""
    import psycopg

    from scripts import build_index

    rows = []
    with psycopg.connect(url, autocommit=True) as conn:
        stored = build_index.stored_code(conn)
        current = stored == build_index.build_index_code_hash()
        rows.append(Row("build_index", "code", "ok" if current else "warn",
                        "current" if current else
                        ("no full run recorded" if stored is None else "changed since the last "
                         "full run (bump LOADER_VERSION if stored data should change)")))
        if vecs is not None and vecs.is_dir():
            st = build_index.run(conn, norm, trans, vecs, dry_run=True, align_dir=align_dir)
            busy = (st.loaded or st.updated or st.deleted or st.regrouped or st.passages
                    or st.backfilled)
            rows.append(Row("build_index", "database", "warn" if busy or st.stale_alignments
                            else "ok",
                            f"{st.loaded} works to load (vectors re-sent), "
                            f"{st.updated} to update in place (metadata only, #234), "
                            f"{st.backfilled} body hashes to fill in, {st.deleted} to delete, "
                            f"{st.regrouped} chunks to regroup, {st.passages} passage rows, "
                            f"{len(st.stale_alignments)} works with stale alignments"
                            + ("; run scripts.build_index" if busy else "")))
    return rows


# ---------------------------------------------------------------------------
# The table
# ---------------------------------------------------------------------------


def _guarded(rows: list[Row], step: str, check: str, fn: Callable[[], list[Row]]) -> None:
    """Add *fn*'s rows; a check that raises becomes a failing row naming the error,
    so the table (and the CI summary) is always written."""
    try:
        rows.extend(fn())
    except Exception as exc:  # reported in the table, not swallowed
        log.exception("%s %s check failed", step, check)
        rows.append(Row(step, check, "fail", f"check failed: {type(exc).__name__}: {exc}"))


def collect(norm: Path = NORMALIZED, raw: Path | None = None, vecs: Path | None = None,
            trans: Path = TRANSLATIONS, align_dir: Path = ALIGNMENTS,
            db: str | None = None) -> list[Row]:
    rows: list[Row] = []
    renorm = "re-run scripts.normalize"
    realign = "re-run scripts.align (after scripts.embed)"

    def ingest() -> list[Row]:
        drift, unstamped = ingest_drift(norm)
        return [Row("ingest", "code", "warn" if drift else "ok",
                    f"{len(drift)} sources whose ingestor changed since their data was "
                    f"normalized, {len(unstamped)} not stamped yet"
                    + (f" ({_examples(drift)}): re-ingest with --force, then scripts.normalize "
                       "--accept-raw-change" if drift else ""))]

    def code() -> list[Row]:
        current = normalize_code_current(norm)
        return [Row("normalize", "code", "ok" if current else "fail",
                    "current" if current else f"changed: {renorm}")]

    def works() -> list[Row]:
        missing, curated = unfingerprinted_works(norm), curation_stale_works(norm)
        anchored = anchor_stale_works(norm)
        bad = missing + curated + anchored
        return [Row("normalize", "works", "fail" if bad else "ok",
                    f"{len(missing)} without a fingerprint, {len(curated)} with changed curation, "
                    f"{len(anchored)} with a changed anchor"
                    + (f" ({_examples(bad)}): {renorm}" if bad else ""))]

    absent: list[str] = []

    def manifest() -> list[Row]:
        unlisted, gone = manifest_mismatch(norm)
        absent.extend(gone)
        return [Row("normalize", "manifest", "fail" if unlisted or gone else "ok",
                    f"{len(unlisted)} files not in _works.jsonl, {len(gone)} entries "
                    f"without a file" + (f" ({_examples(unlisted + gone)}): {renorm}"
                                         if unlisted or gone else ""))]

    def local_raw() -> list[Row]:
        if raw is None:
            return []
        if not raw.is_dir():
            return [Row("normalize", "local raw", "warn", f"no {raw} here")]
        changed, new = raw_changes(norm, raw)
        return [Row("normalize", "local raw", "warn" if changed or new else "ok",
                    f"{len(changed)} works whose raw changed (normalize refuses them; "
                    f"--accept-raw-change after a re-ingest), {len(new)} new raw files"
                    + (f": {_examples(changed + new)}" if changed or new else ""))]

    def align_code() -> list[Row]:
        current = align_code_current(align_dir)
        return [Row("align", "code", "ok" if current else "fail",
                    "current" if current else f"changed: {realign}")]

    def align_groups() -> list[Row]:
        stale = stale_groups(norm, align_dir)
        return [Row("align", "groups", "fail" if stale else "ok",
                    f"{len(stale)} version groups whose alignment is stale"
                    + (" (" + _examples([f"{g}: {why}" for g, why in stale.items()])
                       + f"): {realign}" if stale else ""))]

    def align_units() -> list[Row]:
        changed_units = alignments_with_changed_units(norm, align_dir)
        return [Row("align", "units", "fail" if changed_units else "ok",
                    f"{len(changed_units)} alignments with a member whose chunks changed"
                    + (f" ({_examples(changed_units)}): {realign}" if changed_units else ""))]

    def translate() -> list[Row]:
        by_lang, cost = pending_translations(norm, trans)
        n = sum(by_lang.values())
        return [Row("translate", "pending", "warn" if n else "ok",
                    f"{n:,} units (~${cost:,.2f})"
                    + (": " + ", ".join(f"{k} {v:,}" for k, v in sorted(by_lang.items()))
                       + "; run scripts.translate" if n else ""))]

    def vectors() -> list[Row]:
        if vecs is None:
            return []
        if not vecs.is_dir():
            return [Row("embed", "pending", "warn", f"no {vecs} here")]
        todo, vcost = pending_vectors(norm, trans, vecs)
        out = [Row("embed", "pending", "warn" if todo else "ok",
                   f"{todo:,} vectors (~${vcost:,.2f})" + ("; run scripts.embed" if todo else ""))]
        drift = align_drift(norm, trans, vecs, align_dir)
        busy = drift.get("aligned", 0) + drift.get("deleted", 0)
        refused = drift.get("refused", 0)
        out.append(Row("align", "vectors", "warn" if busy or refused else "ok",
                       f"{busy} groups to re-align, {refused} refused (missing vectors)"
                       + (f": {realign}" if busy or refused else "")))
        return out

    for step, check, fn in (("ingest", "code", ingest),
                            ("normalize", "code", code), ("normalize", "works", works),
                            ("normalize", "manifest", manifest),
                            ("normalize", "local raw", local_raw), ("align", "code", align_code)):
        _guarded(rows, step, check, fn)
    # The rest read the normalized files: with entries whose file is missing they
    # can't run, which the manifest row already reports.
    dependent = (("align", "groups", align_groups), ("align", "units", align_units),
                 ("translate", "pending", translate), ("embed", "pending", vectors))
    for step, check, fn in dependent:
        if fn is vectors and vecs is None:
            continue
        if absent:
            rows.append(Row(step, check, "fail",
                            f"skipped: {len(absent)} works in _works.jsonl have no normalized "
                            "file (see the manifest row)"))
        else:
            _guarded(rows, step, check, fn)
    if db:
        _guarded(rows, "build_index", "database",
                 lambda: db_rows(db, norm, trans, vecs, align_dir))
    return rows


def render(rows: list[Row]) -> str:
    lines = ["| step | check | | detail |", "|---|---|---|---|"]
    mark = {"ok": "✅", "warn": "⚠️", "fail": "❌"}
    for r in rows:
        lines.append(f"| {r.step} | {r.check} | {mark[r.level]} | {r.detail} |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Freshness of every pipeline step (#130).")
    parser.add_argument("--normalized-dir", type=Path, default=NORMALIZED)
    parser.add_argument("--translations-dir", type=Path, default=TRANSLATIONS)
    parser.add_argument("--alignments-dir", type=Path, default=ALIGNMENTS)
    parser.add_argument("--raw", nargs="?", const=RAW, type=Path, metavar="DIR",
                        help=f"also compare local raw data (default {RAW})")
    parser.add_argument("--vectors", nargs="?", const=EMBEDDINGS, type=Path, metavar="DIR",
                        help=f"also check embeddings and alignment inputs (default {EMBEDDINGS})")
    parser.add_argument("--db", nargs="?", const="", metavar="URL",
                        help="also check the search database (default: DATABASE_URL)")
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if any check fails (what CI enforces)")
    parser.add_argument("--summary", type=Path, metavar="FILE",
                        help="append the table as Markdown (e.g. $GITHUB_STEP_SUMMARY)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    db = args.db
    if db == "":
        from patristica.embedders import env_key

        db = env_key("DATABASE_URL")
    rows = collect(args.normalized_dir, raw=args.raw, vecs=args.vectors,
                   trans=args.translations_dir, align_dir=args.alignments_dir, db=db)
    table = render(rows)
    print(table)
    if args.summary:
        with args.summary.open("a", encoding="utf-8") as f:
            f.write("## Pipeline status (#130)\n\n" + table + "\n\n")
    if args.check and any(r.level == "fail" for r in rows):
        sys.exit(1)


if __name__ == "__main__":
    main()
