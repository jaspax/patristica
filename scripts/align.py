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

Staleness (#130): ``data/alignments/_fingerprint.json`` records the hash of
this step's code (``patristica.fingerprint``; the versification registries are
left out, since their effect reaches each member's inputs through the
Scripture keys) and the groups a full run skipped for lack of vectors. When
the code hash changed, every group is aligned again; a group whose result is
unchanged keeps its file. ``tests/test_align_fingerprint.py`` fails until a
full run has recorded the hash, and when a version group has neither a file
nor a recorded skip.

A group with a member whose units lack a current vector (a work normalized or
translated since ``scripts.embed`` last ran) is *refused*: its file is kept and
the run exits with an error, since aligning without those vectors would
quietly lose passages. Run ``scripts.embed`` first, or pass
``--allow-missing-vectors``.

Usage::

    uv run --extra embed python -m scripts.align --dry-run
    uv run --extra embed python -m scripts.align [--group book:prov] [--prefix book:]
        [--embeddings-dir data/embeddings] [--jobs 4] [--force] [--allow-missing-vectors]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path

from tqdm import tqdm

from patristica import alignment_store as store
from patristica import embeddings as emb
from patristica import fingerprint
from patristica import translations as tr
from patristica.corpus import load_works, select
from patristica.versification import SOURCE_SCHEMES, VersificationError, to_org_ref
from patristica.versions import derive_version_groups

log = logging.getLogger(__name__)

#: Bump when the aligner changes in a way its parameters don't show: every group is redone.
ALIGNER_VERSION = 2
METHOD = ("pivot star; banded monotonic DP over unit vectors (vecalign-style beads up to 4:1, "
          "baseline-corrected cosine), mutual-nearest-neighbour anchors, re-alignment of "
          "unaligned blocks")
SCRIPTURE_PRIOR = 0.1

STEP = "align"
FINGERPRINT_FILE = "_fingerprint.json"  # {"align": {"code": hash}, "skipped": {group: reason}}
#: Per-source registries left out of the code hash: they act through the
#: Scripture keys, which are in each member's inputs, so adding a source
#: re-aligns only the groups it touches.
REGISTRIES = {"patristica.versification": ("SOURCE_SCHEMES", "BOOK_SCHEME_OVERRIDES",
                                           "CHAPTER_SCHEME_OVERRIDES")}
NO_VECTORS = "fewer than two members with vectors"


def align_code_hash() -> str:
    """Hash of the code this step runs (see ``patristica.fingerprint``)."""
    return fingerprint.code_hash("scripts.align", exclude=REGISTRIES)


def read_fingerprint(out_dir: Path) -> dict:
    """``{"align": {"code": …}, "skipped": {group: reason}}`` (empty if none)."""
    path = out_dir / FINGERPRINT_FILE
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_fingerprint(out_dir: Path, code: str | None, skipped: dict[str, str]) -> None:
    """Record the skipped groups and, when given, the code hash (else keep the old one)."""
    old = read_fingerprint(out_dir)
    data = {STEP: {"code": code} if code else old.get(STEP, {}),
            "skipped": dict(sorted(skipped.items()))}
    path = out_dir / FINGERPRINT_FILE
    text = json.dumps(data, indent=1, sort_keys=True) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


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
    return load_member_checked(entry, input_dir, trans_dir, store_dir, with_keys)[0]


def wants_vector(text: str) -> bool:
    """Whether ``scripts.embed`` gives a unit with this text a vector."""
    return len(text.strip()) >= emb.MIN_CHARS


def load_member_checked(entry: dict, input_dir: Path, trans_dir: Path, store_dir: Path,
                        with_keys: bool) -> tuple[Loaded | None, int]:
    """``load_member``, and the number of units that should have a current text
    vector (``wants_vector``) but have none: units normalized since the last
    ``scripts.embed`` run."""
    import numpy as np

    path = entry["path"]
    work = entry["work"]
    shard = emb.load(store_dir, path)
    with (input_dir / path).open(encoding="utf-8") as f:
        chunks = json.load(f)
    if shard is None or shard.vecs is None:
        return None, sum(wants_vector(c["text"]) for c in chunks)
    translated = work["language"] in tr.TRANSLATED_LANGUAGES
    trans = tr.load(trans_dir, path) if translated else None
    trans_rows = trans.by_chunk() if trans is not None else {}
    index = shard.by_key()
    dims = shard.vecs.shape[1]
    vecs = np.zeros((len(chunks), dims), dtype=np.float32)
    h = hashlib.sha256()
    models: set[str] = set()
    missing = 0
    for u, c in enumerate(chunks):
        sha = tr.text_sha(c["text"])
        k = index.get((c["chunk_id"], emb.KIND_TEXT))
        if wants_vector(c["text"]) and (k is None or shard.rows[k].sha != sha):
            missing += 1
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
        return None, missing
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    vecs = np.divide(vecs, norms, out=np.zeros_like(vecs), where=norms > 0)
    keys = None
    if with_keys:
        refs = scripture_keys(work["work_id"], [c["canonical_ref"] for c in chunks])
        if refs is not None:
            h.update(b"keys" + "\x00".join(refs).encode("utf-8"))
            keys = np.array([ref_key(r) if r else -1 for r in refs], dtype=np.int64)
    return Loaded(work["work_id"], work["language"], len(chunks), h.hexdigest()[:16],
                  store.ids_sha([c["chunk_id"] for c in chunks]), vecs, keys,
                  frozenset(models)), missing


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
    allow_missing_vectors: bool = False
    code_current: bool = True  # False: the code changed, so align even unchanged inputs


def run_job(job: Job) -> tuple[str, str]:
    """Align one group; return (group, outcome).

    The outcome is unchanged, aligned, skipped (fewer than two members with
    vectors), deleted (skipped, and the group's old file removed, since an
    alignment of members that are no longer eligible must not stay visible),
    or ``refused: {work_id} {n}, …`` when members have units without a current
    vector (see the module docstring); a refused group's file is kept.
    """
    with_keys = job.group.startswith("book:")
    members: list[Loaded] = []
    missing: dict[str, int] = {}
    for e in job.entries:
        m, n = load_member_checked(e, job.input_dir, job.trans_dir, job.store_dir, with_keys)
        if m is not None:
            members.append(m)
        if n:
            missing[e["work"]["work_id"]] = n
    if missing and not job.allow_missing_vectors:
        return job.group, "refused: " + ", ".join(f"{w} {n}" for w, n in sorted(missing.items()))
    path = store.path_for(job.out_dir, job.group)
    if len(members) < 2:
        if path.exists():
            if not job.dry_run:
                path.unlink()
            return job.group, "deleted"
        return job.group, "skipped"
    inputs = group_inputs(job.group, members)
    if not job.force and job.code_current and path.exists():
        try:
            if store.from_json(path.read_text(encoding="utf-8")).inputs == inputs:
                return job.group, "unchanged"
        except (store.AlignmentFormatError, KeyError, ValueError):
            pass
    if job.dry_run:
        return job.group, "aligned"
    changed = store.save(job.out_dir, align_group(job.group, members, inputs, job.today))
    return job.group, "aligned" if changed else "unchanged"


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
    parser.add_argument("--allow-missing-vectors", action="store_true",
                        help="align groups even when members have units without a current "
                             "vector (run scripts.embed first instead)")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    entries = select(load_works(args.input_dir), [], [], include_unpublishable=False)
    by_id = {e["work"]["work_id"]: e for e in entries}
    groups = version_groups(load_works(args.input_dir))
    chosen = [g for g in groups
              if (not args.group or g in args.group)
              and (not args.prefix or any(g.startswith(p) for p in args.prefix))]
    today = date.today().isoformat()
    code = align_code_hash()
    code_current = read_fingerprint(args.output_dir).get(STEP, {}).get("code") == code
    if not code_current:
        log.info("align's code changed since the last full run: aligning every group")
    jobs = [Job(g, [by_id[w] for w in groups[g] if w in by_id], args.input_dir,
                args.translations_dir, args.embeddings_dir, args.output_dir, args.force,
                args.dry_run, today, args.allow_missing_vectors, code_current)
            for g in chosen]
    publishable = {j.group: len(j.entries) for j in jobs}
    # Big groups first, so the pool doesn't end on one.
    jobs.sort(key=lambda j: -sum(len(e["path"]) for e in j.entries))
    outcome: dict[str, int] = {}
    refused: dict[str, str] = {}
    skipped: dict[str, str] = {}
    with make_pool(args.jobs) as pool:
        for group, result in tqdm(pool.map(run_job, jobs), total=len(jobs), desc="groups"):
            kind = result.split(":", 1)[0]
            outcome[kind] = outcome.get(kind, 0) + 1
            if kind == "refused":
                refused[group] = result.split(": ", 1)[1]
            elif kind in ("skipped", "deleted") and publishable[group] >= 2:
                skipped[group] = NO_VECTORS
    full_run = not args.group and not args.prefix and not args.dry_run
    if full_run:
        write_fingerprint(args.output_dir, None if refused else code, skipped)
    if not args.group and not args.prefix and not args.dry_run:
        keep = {store.path_for(args.output_dir, g) for g in groups}
        for path, _ in list(store.iter_store(args.output_dir)):
            if path not in keep:
                log.info("deleting %s (no longer a version group)", path)
                path.unlink()
                outcome["deleted"] = outcome.get("deleted", 0) + 1
    log.info("%s%d groups: %s", "dry run: " if args.dry_run else "", len(jobs),
             ", ".join(f"{n} {k}" for k, n in sorted(outcome.items())))
    if refused:
        for group, detail in sorted(refused.items())[:20]:
            log.error("refused %s: units without a current vector: %s", group, detail)
        log.error("%d groups refused (their files were kept): run scripts.embed first, or "
                  "pass --allow-missing-vectors%s", len(refused),
                  "; the new code hash was not recorded" if full_run and not code_current else "")
        sys.exit(1)


if __name__ == "__main__":
    main()
