"""
The data/ tiers in git-lfs: materialize what a job needs, archive the clones (#244).

``data/raw``, ``data/embeddings`` and the work files of ``data/normalized`` are
git-lfs files. ``.lfsconfig`` fetches none of them by default, so a clone, a
worktree or a CI checkout gets pointer files only; the machine that runs the
pipeline pulls everything once, and every other job pulls what it reads.

The upstream git clones under ``data/raw/_repos/`` (162k files, and OGPG keeps
its secondary scans only in each clone's object store) aren't tracked file by
file: each clone is one archive, ``data/raw/_repo_archives/{clone}.tar.gz``,
listed with its URL and HEAD in ``_repo_archives/_manifest.json``. ``pack``
writes the archives of clones that changed; ``unpack`` restores missing
clones. The git dirs of the clones the ingestors write into (PTA, First1K,
OGLT PL, ``data/raw/_gitdirs/``, ``scripts.ingest._clone``) are recorded there
too (URL and HEAD) but not archived: their files are tracked, and a git dir
is only needed to update them.

Usage::

    uv run python -m scripts.data pull --all          # the pipeline machine: everything
    uv run python -m scripts.data unpack              # … then the clones
    uv run python -m scripts.data pull --job tests    # CI: the files the unit tests read
    uv run python -m scripts.data needs --job status  # list them
    uv run python -m scripts.data pack                # after an ingest re-cloned or pulled
    uv run python -m scripts.data status
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tarfile
from collections.abc import Callable, Iterator
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from patristica import fingerprint

log = logging.getLogger(__name__)

REPO = fingerprint.REPO_ROOT
DATA = REPO / "data"
RAW = DATA / "raw"
REPOS = RAW / "_repos"
GITDIRS = RAW / "_gitdirs"
ARCHIVES = RAW / "_repo_archives"
MANIFEST = ARCHIVES / "_manifest.json"
NORMALIZED = DATA / "normalized"
TIERS = ("raw", "embeddings", "normalized")
LFS_POINTER = b"version https://git-lfs"
# Git bookkeeping that changes without the clone's content changing.
VOLATILE = (".git/logs/", ".git/FETCH_HEAD", ".git/ORIG_HEAD", ".git/index")


# ---------------------------------------------------------------------------
# What a job reads
# ---------------------------------------------------------------------------


def _works(norm: Path) -> list[dict]:
    from patristica.corpus import load_works

    return load_works(norm)


def book_group_paths(norm: Path) -> set[str]:
    """Members of a Scripture book's version group (``book:…``): ``scripts.align``'s
    ``group_record`` reads their refs (``tests/test_align_fingerprint.py``)."""
    from patristica.versions import derive_version_groups

    works = _works(norm)
    groups = derive_version_groups(
        {e["work"]["work_id"]: e["work"].get("translation_of") for e in works},
        external_ids={e["work"]["work_id"]: e["work"].get("external_ids", []) for e in works})
    members = {w for g, ms in groups.members.items() if g.startswith("book:") for w in ms}
    return {e["path"] for e in works if e["work"]["work_id"] in members}


def scripture_book_paths(norm: Path) -> set[str]:
    """Works whose id names a Scripture book (``patristica.versions.scripture_book``),
    also those with no other version: ``tests/test_versions.py`` reads their refs."""
    from patristica.versions import scripture_book

    return {e["path"] for e in _works(norm) if scripture_book(e["work"]["work_id"])}


def language_sample_paths(norm: Path, per_language: int = 2) -> set[str]:
    """The first works of each language in ``_works.jsonl`` (``tests/test_textfold.py``)."""
    seen: dict[str, int] = {}
    out = set()
    for e in _works(norm):
        lang = e["work"]["language"]
        if seen.get(lang, 0) < per_language:
            seen[lang] = seen.get(lang, 0) + 1
            out.add(e["path"])
    return out


def aligned_paths(norm: Path, align_dir: Path) -> set[str]:
    """Members of a tracked alignment (``status.alignments_with_changed_units``)."""
    from patristica import alignment_store as store

    by_id = {e["work"]["work_id"]: e["path"] for e in _works(norm)}
    return {by_id[w] for _, a in store.iter_store(align_dir) for w in a.members if w in by_id}


def translated_paths(norm: Path) -> set[str]:
    """Works in a language ``scripts.translate`` translates (``status.pending_translations``)."""
    from patristica import translations as tr

    return {e["path"] for e in _works(norm) if e["work"]["language"] in tr.TRANSLATED_LANGUAGES}


def anchored_paths(norm: Path) -> set[str]:
    """Works of sources enrolled for anchored derived verses and their originals
    (``tests/test_anchor_fingerprint.py`` and ``scripts.status``'s anchor row read
    both, #304)."""
    from patristica import anchoring

    works = _works(norm)
    by_id = {e["work"]["work_id"]: e["path"] for e in works}
    out: set[str] = set()
    for e in works:
        if anchoring.is_enrolled(e["work"]["source_id"]):
            out.add(e["path"])
            target = anchoring.anchor_id(e["work"])
            if target in by_id:
                out.add(by_id[target])
    return out


def needs(job: str, norm: Path = NORMALIZED, align_dir: Path | None = None) -> list[str]:
    """Repo-relative LFS paths *job* reads: ``tests`` the unit tests, ``status``
    also ``scripts.status``. A new test that reads normalized work files adds
    its set here."""
    from patristica import alignment_store as store

    align_dir = align_dir or REPO / store.DEFAULT_DIR
    if job not in ("tests", "status"):
        raise ValueError(f"unknown job {job!r}")
    paths = (book_group_paths(norm) | scripture_book_paths(norm)
             | aligned_paths(norm, align_dir) | language_sample_paths(norm)
             | anchored_paths(norm))
    if job == "status":
        paths |= translated_paths(norm)
    prefix = norm.relative_to(REPO).as_posix()
    return sorted(f"{prefix}/{p}" for p in paths)


def lfs_pull(include: list[str] | None, run: Callable[..., object] = subprocess.run) -> None:
    """``git lfs pull`` of *include* (every data/ tier when None), past ``.lfsconfig``'s
    fetchexclude."""
    if include is not None and any("," in p for p in include):
        raise ValueError("git lfs --include is comma-separated: a path contains a comma")
    patterns = ",".join(include) if include is not None else "data/**"
    if include == []:
        return
    run(["git", "-c", "lfs.fetchexclude=", "lfs", "pull", f"--include={patterns}"],
        cwd=REPO, check=True)


# ---------------------------------------------------------------------------
# Clone archives
# ---------------------------------------------------------------------------


def find_clones(root: Path = REPOS) -> list[Path]:
    """Directories under *root* that are git clones (not descending into them)."""
    clones = []
    for dirpath, dirnames, _ in os.walk(root):
        if ".git" in dirnames:
            clones.append(Path(dirpath))
            dirnames.clear()
        dirnames.sort()
    return sorted(clones)


def clone_state(clone: Path) -> str:
    """A hash of every file's path and size in *clone*, its git dir included,
    minus bookkeeping: changes when a pull, fetch or checkout changed it."""
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(clone):
        dirnames.sort()
        for name in sorted(filenames):
            path = Path(dirpath) / name
            rel = path.relative_to(clone).as_posix()
            if rel.startswith(VOLATILE):
                continue
            h.update(f"{rel}\0{path.lstat().st_size}\n".encode())
    return h.hexdigest()[:16]


def _git(git_dir: Path, *args: str) -> str:
    out = subprocess.run(["git", f"--git-dir={git_dir}", *args], capture_output=True, text=True)
    return out.stdout.strip() if out.returncode == 0 else ""


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def archive_path(rel: str, archives: Path = ARCHIVES) -> Path:
    return archives / f"{rel}.tar.gz"


def write_archive(clone: Path, target: Path) -> str:
    """Archive *clone* (its directory as the top entry) to *target*; its sha256."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    with tarfile.open(tmp, "w:gz", compresslevel=6) as tar:
        tar.add(clone, arcname=clone.name)
    tmp.replace(target)
    return sha256_file(target)


def _pack_one(args: tuple[str, str, str]) -> tuple[str, str]:
    rel, clone, target = args
    return rel, write_archive(Path(clone), Path(target))


def read_manifest(path: Path = MANIFEST) -> dict:
    if not path.exists():
        return {"repos": {}, "gitdirs": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def write_manifest(manifest: dict, path: Path = MANIFEST) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def pack(repos: Path = REPOS, gitdirs: Path = GITDIRS, archives: Path = ARCHIVES,
         force: bool = False, jobs: int = max(1, (os.cpu_count() or 2) - 1)) -> dict[str, int]:
    """Archive every clone under *repos* whose state changed; drop archives of
    clones that are gone; record the ingest-tree git dirs. Counts by outcome."""
    manifest_path = archives / "_manifest.json"
    old = read_manifest(manifest_path)
    repos_out: dict[str, dict] = {}
    todo = []
    for clone in find_clones(repos):
        rel = clone.relative_to(repos).as_posix()
        git_dir = clone / ".git"
        entry = {"url": _git(git_dir, "remote", "get-url", "origin"),
                 "head": _git(git_dir, "rev-parse", "HEAD"), "state": clone_state(clone)}
        prev = old["repos"].get(rel)
        if (not force and prev and prev.get("state") == entry["state"]
                and archive_path(rel, archives).exists()):
            repos_out[rel] = prev
            continue
        repos_out[rel] = entry
        todo.append((rel, str(clone), str(archive_path(rel, archives))))
    counts = {"archived": len(todo), "unchanged": len(repos_out) - len(todo), "removed": 0}
    if todo:
        from tqdm import tqdm

        with ProcessPoolExecutor(jobs) as pool:
            for rel, digest in tqdm(pool.map(_pack_one, todo), total=len(todo), desc="archives"):
                repos_out[rel]["sha256"] = digest
    for rel in sorted(set(old["repos"]) - set(repos_out)):
        archive_path(rel, archives).unlink(missing_ok=True)
        counts["removed"] += 1
    gitdirs_out = {}
    for git_dir in sorted(gitdirs.glob("*.git")) if gitdirs.is_dir() else []:
        gitdirs_out[git_dir.name.removesuffix(".git")] = {
            "url": _git(git_dir, "remote", "get-url", "origin"),
            "head": _git(git_dir, "rev-parse", "HEAD")}
    write_manifest({"repos": repos_out, "gitdirs": gitdirs_out}, manifest_path)
    return counts


def is_pointer(path: Path) -> bool:
    with path.open("rb") as f:
        return f.read(len(LFS_POINTER)) == LFS_POINTER


def unpack(repos: Path = REPOS, archives: Path = ARCHIVES, force: bool = False) -> dict[str, int]:
    """Restore every archived clone that is missing (all with *force*), checking
    each archive's sha256 first."""
    manifest = read_manifest(archives / "_manifest.json")
    counts = {"restored": 0, "present": 0}
    for rel, entry in sorted(manifest["repos"].items()):
        target = repos / rel
        if target.exists() and not force:
            counts["present"] += 1
            continue
        archive = archive_path(rel, archives)
        if not archive.exists() or is_pointer(archive):
            raise FileNotFoundError(f"{archive} is not here: run `scripts.data pull --all` first")
        if sha256_file(archive) != entry["sha256"]:
            raise ValueError(f"{archive} doesn't match its sha256 in the manifest")
        scratch = target.parent / f".{target.name}.unpack"
        shutil.rmtree(scratch, ignore_errors=True)
        scratch.mkdir(parents=True)
        with tarfile.open(archive, "r:gz") as tar:
            tar.extractall(scratch, filter="data")
        if target.exists():
            shutil.rmtree(target)
        (scratch / target.name).rename(target)
        scratch.rmdir()
        counts["restored"] += 1
    return counts


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


def lfs_files(tier: str) -> Iterator[str]:
    """The tier's files git tracks through LFS."""
    out = subprocess.run(["git", "lfs", "ls-files", "--name-only", "--include", f"data/{tier}/**"],
                         cwd=REPO, capture_output=True, text=True, check=True)
    yield from out.stdout.splitlines()


def status() -> list[str]:
    lines = []
    for tier in TIERS:
        files = list(lfs_files(tier))
        present = [f for f in files if (REPO / f).exists()]
        pointers = sum(is_pointer(REPO / f) for f in present)
        lines.append(f"{tier}: {len(files):,} LFS files, {len(present) - pointers:,} "
                     f"materialized, {pointers:,} pointers, {len(files) - len(present):,} absent")
    manifest = read_manifest()
    clones = manifest["repos"]
    unpacked = sum((REPOS / rel).exists() for rel in clones)
    stale = [rel for rel in clones if (REPOS / rel).exists()
             and clone_state(REPOS / rel) != clones[rel]["state"]]
    new = [c.relative_to(REPOS).as_posix() for c in find_clones()
           if c.relative_to(REPOS).as_posix() not in clones] if REPOS.is_dir() else []
    lines.append(f"clones: {len(clones)} archived, {unpacked} unpacked, {len(stale)} changed "
                 f"since archived, {len(new)} not archived"
                 + ("; run scripts.data pack" if stale or new else ""))
    return lines


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    n = sub.add_parser("needs", help="list the LFS files a job reads")
    n.add_argument("--job", required=True, choices=("tests", "status"))
    pl = sub.add_parser("pull", help="git lfs pull a job's files, or everything")
    which = pl.add_mutually_exclusive_group(required=True)
    which.add_argument("--job", choices=("tests", "status"))
    which.add_argument("--all", action="store_true")
    pk = sub.add_parser("pack", help="archive the clones under data/raw/_repos that changed")
    pk.add_argument("--force", action="store_true", help="re-archive every clone")
    up = sub.add_parser("unpack", help="restore archived clones that are missing")
    up.add_argument("--force", action="store_true", help="replace clones that exist")
    sub.add_parser("status", help="what is materialized, and clones to archive")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.cmd == "needs":
        print("\n".join(needs(args.job)))
    elif args.cmd == "pull":
        lfs_pull(None if args.all else needs(args.job))
    elif args.cmd == "pack":
        log.info("clones: %s", pack(force=args.force))
    elif args.cmd == "unpack":
        log.info("clones: %s", unpack(force=args.force))
    elif args.cmd == "status":
        print("\n".join(status()))
    sys.exit(0)


if __name__ == "__main__":
    main()
