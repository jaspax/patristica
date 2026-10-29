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
left out, see below) and, per version group, what it was aligned from: its
publishable members and, for a Scripture book, a hash of every member's
versification-mapped refs (``group_record``), plus the reason if the group was
skipped. Neither needs vectors, so ``tests/test_align_fingerprint.py`` checks
them in CI (``check_groups``): a member added to or removed from a group, or a
change to ``SOURCE_SCHEMES`` / ``BOOK_SCHEME_OVERRIDES`` /
``CHAPTER_SCHEME_OVERRIDES`` that moves a book's refs, makes exactly that group
stale, and a new group fails until it is aligned. When the code hash changed,
every group is aligned again; a group whose result is unchanged keeps its file.

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
from patristica.editorial import source_text
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
#: {"align": {"code": hash}, "groups": {group: {"members": [...], "keys": hash, "skipped": why}}}
FINGERPRINT_FILE = "_fingerprint.json"
#: Registries left out of the code hash, since their effect is covered per group:
#: - the versification registries through the Scripture keys (``group_record``), so
#:   adding a source or correcting an override makes only the groups it touches stale;
#: - ``TRANSLATED_LANGUAGES`` through each member's inputs hash (``Loaded.inputs``),
#:   which records the vector row every unit is aligned on: enrolling a language
#:   (#336) re-aligns only the groups whose members then have translation vectors,
#:   in the next align run, and nothing before its units are translated.
REGISTRIES = {"patristica.versification": ("SOURCE_SCHEMES", "BOOK_SCHEME_OVERRIDES",
                                           "CHAPTER_SCHEME_OVERRIDES"),
              "patristica.translations": ("TRANSLATED_LANGUAGES",)}
NO_VECTORS = "fewer than two members with vectors"


def align_code_hash() -> str:
    """Hash of the code this step runs (see ``patristica.fingerprint``)."""
    return fingerprint.code_hash("scripts.align", exclude=REGISTRIES)


def read_fingerprint(out_dir: Path) -> dict:
    """``{"align": {"code": …}, "groups": {group: record}}`` (empty if none)."""
    path = out_dir / FINGERPRINT_FILE
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_fingerprint(out_dir: Path, code: str | None, records: dict[str, dict],
                      full: bool) -> None:
    """Record the groups' records and, when given, the code hash (else keep the old one).

    A full run replaces every record; a partial one updates only its groups'.
    """
    old = read_fingerprint(out_dir)
    groups = dict(records) if full else {**old.get("groups", {}), **records}
    data = {STEP: {"code": code} if code else old.get(STEP, {}),
            "groups": dict(sorted(groups.items()))}
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


def group_record(group: str, entries: list[dict], input_dir: Path) -> dict:
    """What *group* is aligned from, without vectors: its publishable members
    and, for a Scripture book, the hash of each member's mapped refs."""
    record: dict = {"members": sorted(e["work"]["work_id"] for e in entries)}
    if group.startswith("book:"):
        h = hashlib.sha256()
        for e in sorted(entries, key=lambda e: e["work"]["work_id"]):
            chunks = json.loads((input_dir / e["path"]).read_text(encoding="utf-8"))
            keys = scripture_keys(e["work"]["work_id"], [c["canonical_ref"] for c in chunks])
            h.update(e["work"]["work_id"].encode("utf-8") + b"\x00")
            h.update("\x00".join(keys or []).encode("utf-8") + b"\x01")
        record["keys"] = h.hexdigest()[:16]
    return record


def check_groups(input_dir: Path, out_dir: Path) -> dict[str, str]:
    """Version groups whose tracked alignment is stale, with the reason.

    Checks every group with two or more publishable members against its record
    in ``_fingerprint.json`` (``group_record``) and its file, and reports
    records of groups that no longer need one.
    """
    works = load_works(input_dir)
    by_id = {e["work"]["work_id"]: e for e in select(works, [], [], include_unpublishable=False)}
    records = read_fingerprint(out_dir).get("groups", {})
    problems: dict[str, str] = {}
    wanted = set()
    for group, members in version_groups(works).items():
        entries = [by_id[w] for w in members if w in by_id]
        if len(entries) < 2:
            continue
        wanted.add(group)
        rec = records.get(group)
        current = group_record(group, entries, input_dir)
        if rec is None:
            problems[group] = "not aligned"
        elif rec["members"] != current["members"]:
            problems[group] = "members changed"
        elif rec.get("keys") != current.get("keys"):
            problems[group] = "versification changed"
        elif "skipped" not in rec and not store.path_for(out_dir, group).exists():
            problems[group] = "no alignment file"
    for group in sorted(set(records) - wanted):
        problems[group] = "no longer a group to align"
    return dict(sorted(problems.items()))


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
        return None, sum(wants_vector(source_text(c)) for c in chunks)
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
        text = source_text(c)
        sha = tr.text_sha(text)
        k = index.get((c["chunk_id"], emb.KIND_TEXT))
        if wants_vector(text) and (k is None or shard.rows[k].sha != sha):
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
    if len(job.entries) >= 2 and missing and not job.allow_missing_vectors:
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


def make_jobs(input_dir: Path, trans_dir: Path, store_dir: Path, out_dir: Path, *,
              only: list[str] = (), prefixes: list[str] = (), force: bool = False,
              dry_run: bool = False, allow_missing_vectors: bool = False,
              code: str | None = None) -> tuple[list[Job], dict[str, tuple[str, ...]], bool]:
    """The jobs a run makes, biggest first; the version groups; and whether the
    recorded code hash is current (*code* defaults to ``align_code_hash()``).

    Unpublishable works are left out of each group.
    """
    works = load_works(input_dir)
    by_id = {e["work"]["work_id"]: e for e in select(works, [], [], include_unpublishable=False)}
    groups = version_groups(works)
    chosen = [g for g in groups
              if (not only or g in only)
              and (not prefixes or any(g.startswith(p) for p in prefixes))]
    code_current = (read_fingerprint(out_dir).get(STEP, {}).get("code")
                    == (code or align_code_hash()))
    today = date.today().isoformat()
    jobs = [Job(g, [by_id[w] for w in groups[g] if w in by_id], input_dir, trans_dir, store_dir,
                out_dir, force, dry_run, today, allow_missing_vectors, code_current)
            for g in chosen]
    # Big groups first, so the pool doesn't end on one.
    jobs.sort(key=lambda j: -sum(len(e["path"]) for e in j.entries))
    return jobs, groups, code_current


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

    code = align_code_hash()
    jobs, groups, code_current = make_jobs(
        args.input_dir, args.translations_dir, args.embeddings_dir, args.output_dir,
        only=args.group, prefixes=args.prefix, force=args.force, dry_run=args.dry_run,
        allow_missing_vectors=args.allow_missing_vectors, code=code)
    if not code_current:
        log.info("align's code changed since the last full run: aligning every group")
    by_group = {j.group: j for j in jobs}
    outcome: dict[str, int] = {}
    refused: dict[str, str] = {}
    records: dict[str, dict] = {}
    old_records = read_fingerprint(args.output_dir).get("groups", {})
    with make_pool(args.jobs) as pool:
        for group, result in tqdm(pool.map(run_job, jobs), total=len(jobs), desc="groups"):
            kind = result.split(":", 1)[0]
            outcome[kind] = outcome.get(kind, 0) + 1
            job = by_group[group]
            if len(job.entries) < 2:
                continue
            if kind == "refused":
                refused[group] = result.split(": ", 1)[1]
                if group in old_records:  # its file is kept, so is its record
                    records[group] = old_records[group]
                continue
            records[group] = group_record(group, job.entries, args.input_dir)
            if kind in ("skipped", "deleted"):
                records[group]["skipped"] = NO_VECTORS
    full_run = not args.group and not args.prefix and not args.dry_run
    if not args.dry_run:
        write_fingerprint(args.output_dir, code if full_run and not refused else None, records,
                          full=full_run)
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
