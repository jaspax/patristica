"""
Align the passages of the versions of every work (#179).

For every version group with two or more members (``patristica.versions``),
align each member with the group's pivot (``patristica.alignment``) and write
``data/alignments/{group}.json`` (``patristica.alignment_store``). Vectors
come from the embedding store (``data/embeddings/``, gitignored; nothing is
embedded here, so the run makes no API calls): a unit's own vector, or for
Syriac, Coptic, Armenian and Ge'ez its English translation's vector. Units
without a current vector are aligned only through their refs (Scripture) or
not at all. Works whose licence is unpublishable are left out, as in
``scripts.embed``.

Scripture books (groups ``book:…``) use their versification-mapped refs
(``patristica.versification``) as a prior (``SCRIPTURE_PRIOR``): the refs
decide where the content is ambiguous, the content where it clearly
disagrees (Ge'ez Proverbs, the Armenian psalm titles).

It is idempotent: a group whose inputs (units, vectors, ref keys, method and
parameters) hash to the ``inputs`` recorded in its file is skipped, so an
interrupted run resumes. A full run (no ``--group``/``--prefix``) deletes the
files of groups that no longer exist.

Usage::

    uv run --extra embed python -m scripts.align --dry-run
    uv run --extra embed python -m scripts.align [--group book:prov] [--prefix book:]
        [--embeddings-dir data/embeddings] [--jobs 4] [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from tqdm import tqdm

from patristica import alignment_store as store
from patristica import embeddings as emb
from patristica import translations as tr
from patristica.versification import SOURCE_SCHEMES, VersificationError, to_org_ref
from patristica.versions import derive_version_groups
from scripts.embed import load_works, select

log = logging.getLogger(__name__)

#: Bump when the aligner changes in a way its parameters don't show: every group is redone.
ALIGNER_VERSION = 2
METHOD = ("pivot star; banded monotonic DP over unit vectors (vecalign-style beads up to 4:1, "
          "baseline-corrected cosine), mutual-nearest-neighbour anchors, re-alignment of "
          "unaligned blocks")
SCRIPTURE_PRIOR = 0.1


@dataclass
class Loaded:
    """A member as loaded for alignment."""

    work_id: str
    language: str
    units: int
    inputs: str
    ids: str  # alignment_store.ids_sha of the chunk ids
    vecs: object  # np.ndarray (units × dims, unit rows, zero rows: no vector)
    keys: object | None  # np.ndarray of int64, or None
    models: frozenset[str]

    @property
    def vectored(self) -> int:
        import numpy as np

        return int((np.abs(self.vecs).sum(axis=1) > 0).sum())


def ref_key(ref: str) -> int:
    """A stable integer for a reference key."""
    return int(hashlib.sha256(ref.encode("utf-8")).hexdigest()[:15], 16)


def scripture_keys(work_id: str, refs: list[str]) -> list[str] | None:
    """Versification-mapped refs of a Scripture-source work (None for any other work)."""
    source = work_id.split("/", 1)[0]
    if source not in SOURCE_SCHEMES:
        return None
    out = []
    for ref in refs:
        try:
            out.append(to_org_ref(source, ref))
        except VersificationError:
            out.append("")
    return out


def load_member(entry: dict, input_dir: Path, trans_dir: Path, store_dir: Path,
                with_keys: bool) -> Loaded | None:
    """Load a work's units and vectors; None if it has no vectors at all."""
    import numpy as np

    path = entry["path"]
    work = entry["work"]
    shard = emb.load(store_dir, path)
    if shard is None or shard.vecs is None:
        return None
    with (input_dir / path).open(encoding="utf-8") as f:
        chunks = json.load(f)
    translated = work["language"] in tr.TRANSLATED_LANGUAGES
    trans = tr.load(trans_dir, path) if translated else None
    trans_rows = trans.by_chunk() if trans is not None else {}
    index = shard.by_key()
    dims = shard.vecs.shape[1]
    vecs = np.zeros((len(chunks), dims), dtype=np.float32)
    h = hashlib.sha256()
    models: set[str] = set()
    for u, c in enumerate(chunks):
        sha = tr.text_sha(c["text"])
        row = None
        if translated:
            t = trans_rows.get(c["chunk_id"])
            k = index.get((c["chunk_id"], emb.KIND_TRANSLATION))
            if (t is not None and k is not None and t.source_sha256 == sha
                    and shard.rows[k].sha == tr.text_sha(t.text)):
                row = k
        if row is None:
            k = index.get((c["chunk_id"], emb.KIND_TEXT))
            if k is not None and shard.rows[k].sha == sha:
                row = k
        h.update(c["chunk_id"].encode("utf-8") + b"\x00")
        if row is not None:
            vecs[u] = shard.vecs[row]
            r = shard.rows[row]
            models.add(shard.runs[r.run].model)
            h.update(f"{r.kind}:{r.sha}:{r.run}".encode("utf-8"))
        h.update(b"\x01")
    if not models:
        return None
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    vecs = np.divide(vecs, norms, out=np.zeros_like(vecs), where=norms > 0)
    keys = None
    if with_keys:
        refs = scripture_keys(work["work_id"], [c["canonical_ref"] for c in chunks])
        if refs is not None:
            h.update(b"keys" + "\x00".join(refs).encode("utf-8"))
            keys = np.array([ref_key(r) if r else -1 for r in refs], dtype=np.int64)
    return Loaded(work["work_id"], work["language"], len(chunks), h.hexdigest()[:16],
                  store.ids_sha([c["chunk_id"] for c in chunks]), vecs, keys, frozenset(models))


def params_for(group: str):
    from patristica.alignment import Params

    p = Params()
    return replace(p, prior=SCRIPTURE_PRIOR) if group.startswith("book:") else p


def group_inputs(group: str, members: list[Loaded]) -> str:
    h = hashlib.sha256()
    head = {"aligner": ALIGNER_VERSION, "params": params_for(group).to_dict(),
            "members": sorted((m.work_id, m.inputs) for m in members)}
    h.update(json.dumps(head, sort_keys=True).encode("utf-8"))
    return h.hexdigest()[:16]


def align_group(group: str, members: list[Loaded], inputs: str, today: str,
                params=None) -> store.Alignment:
    """Align *members* (at least two) and build the stored alignment.

    *params* overrides the group's parameters (``scripts.align_eval``).
    """
    from patristica.alignment import Version, align_pair, choose_pivot, merge, span_fit

    p = params or params_for(group)
    by_id = {m.work_id: m for m in members}
    pivot = choose_pivot({m.work_id: (m.language, m.vectored) for m in members})
    pv = by_id[pivot]
    b = Version(pivot, pv.vecs, pv.keys)
    pairs = {}
    for m in members:
        if m.work_id == pivot:
            continue
        beads = align_pair(Version(m.work_id, m.vecs, m.keys), b, p)
        pairs[m.work_id] = (m.units, beads)
    merged = merge(pivot, pv.units, pairs,
                   span_fit({m.work_id: m.vecs for m in members}, pv.vecs))
    run = {"aligner": ALIGNER_VERSION, "method": METHOD, "params": p.to_dict(),
           "models": sorted(set().union(*(m.models for m in members))),
           "date": today, "script": "scripts.align"}
    out = store.Alignment(group, pivot, merged.n_groups, inputs, run)
    for wid in sorted(by_id):
        conf = {g: int(c * 10) for g, c in merged.conf[wid].items()}
        group_of = [int(g) for g in merged.group_of[wid]]
        m = by_id[wid]
        out.members[wid] = store.Member(wid, m.units, m.inputs, group_of, conf, m.ids)
    return out


def make_pool(jobs: int) -> ProcessPoolExecutor:
    """Worker processes, each with one BLAS thread (``jobs`` processes share the cores)."""
    import multiprocessing

    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[var] = "1"
    return ProcessPoolExecutor(max_workers=jobs, mp_context=multiprocessing.get_context("spawn"))


def version_groups(entries: list[dict]) -> dict[str, tuple[str, ...]]:
    groups = derive_version_groups(
        {e["work"]["work_id"]: e["work"].get("translation_of") for e in entries},
        external_ids={e["work"]["work_id"]: e["work"].get("external_ids", []) for e in entries})
    return groups.members


@dataclass
class Job:
    group: str
    entries: list[dict]
    input_dir: Path
    trans_dir: Path
    store_dir: Path
    out_dir: Path
    force: bool
    dry_run: bool
    today: str


def run_job(job: Job) -> tuple[str, str]:
    """Align one group; return (group, outcome).

    The outcome is unchanged, aligned, skipped (fewer than two members with
    vectors), or deleted: skipped, and the group's old file removed, since an
    alignment of members that are no longer eligible must not stay visible.
    """
    with_keys = job.group.startswith("book:")
    members = [m for e in job.entries
               if (m := load_member(e, job.input_dir, job.trans_dir, job.store_dir, with_keys))]
    path = store.path_for(job.out_dir, job.group)
    if len(members) < 2:
        if path.exists():
            if not job.dry_run:
                path.unlink()
            return job.group, "deleted"
        return job.group, "skipped"
    inputs = group_inputs(job.group, members)
    if not job.force and path.exists():
        try:
            if store.from_json(path.read_text(encoding="utf-8")).inputs == inputs:
                return job.group, "unchanged"
        except (store.AlignmentFormatError, KeyError, ValueError):
            pass
    if job.dry_run:
        return job.group, "aligned"
    store.save(job.out_dir, align_group(job.group, members, inputs, job.today))
    return job.group, "aligned"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1],
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input-dir", type=Path, default=Path("data/normalized"))
    parser.add_argument("--translations-dir", type=Path, default=tr.DEFAULT_DIR)
    parser.add_argument("--embeddings-dir", type=Path, default=emb.DEFAULT_DIR)
    parser.add_argument("--output-dir", type=Path, default=store.DEFAULT_DIR)
    parser.add_argument("--group", action="append", default=[], help="only this group (repeatable)")
    parser.add_argument("--prefix", action="append", default=[],
                        help="only groups whose id starts with this (repeatable)")
    parser.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) // 2))
    parser.add_argument("--force", action="store_true", help="align even unchanged groups")
    parser.add_argument("--dry-run", action="store_true", help="report what would be aligned")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    entries = select(load_works(args.input_dir), [], [], include_unpublishable=False)
    by_id = {e["work"]["work_id"]: e for e in entries}
    groups = version_groups(load_works(args.input_dir))
    chosen = [g for g in groups
              if (not args.group or g in args.group)
              and (not args.prefix or any(g.startswith(p) for p in args.prefix))]
    today = date.today().isoformat()
    jobs = [Job(g, [by_id[w] for w in groups[g] if w in by_id], args.input_dir,
                args.translations_dir, args.embeddings_dir, args.output_dir, args.force,
                args.dry_run, today) for g in chosen]
    # Big groups first, so the pool doesn't end on one.
    jobs.sort(key=lambda j: -sum(len(e["path"]) for e in j.entries))
    outcome: dict[str, int] = {}
    with make_pool(args.jobs) as pool:
        for _, result in tqdm(pool.map(run_job, jobs), total=len(jobs), desc="groups"):
            outcome[result] = outcome.get(result, 0) + 1
    if not args.group and not args.prefix and not args.dry_run:
        keep = {store.path_for(args.output_dir, g) for g in groups}
        for path, _ in list(store.iter_store(args.output_dir)):
            if path not in keep:
                log.info("deleting %s (no longer a version group)", path)
                path.unlink()
                outcome["deleted"] = outcome.get("deleted", 0) + 1
    log.info("%s%d groups: %s", "dry run: " if args.dry_run else "", len(jobs),
             ", ".join(f"{n} {k}" for k, n in sorted(outcome.items())))


if __name__ == "__main__":
    main()
