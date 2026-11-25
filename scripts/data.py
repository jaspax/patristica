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
    uv run python -m scripts.data scope               # full or scoped ($PATRISTICA_SCOPE_BASE)
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
from collections.abc import Callable, Iterable, Iterator
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
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
    out: set[str] = set()

    def collect(members: list[str]) -> bool:  # the ids are all we need: decode nothing (#789)
        out.update(by_id[w] for w in members if w in by_id)
        return False

    for _ in store.iter_store(align_dir, members=collect):
        pass
    return out


def translated_paths(norm: Path) -> set[str]:
    """Works in a language ``scripts.translate`` translates (``status.pending_translations``)."""
    from patristica import translations as tr

    return {e["path"] for e in _works(norm) if e["work"]["language"] in tr.TRANSLATED_LANGUAGES}


# ---------------------------------------------------------------------------
# Scoped corpus checks (CI on a pull request)
# ---------------------------------------------------------------------------

#: CI sets it on a pull request to the commit the PR is compared with (the merge
#: commit's first parent): the corpus checks then cover only what changed since.
SCOPE_ENV = "PATRISTICA_SCOPE_BASE"
#: Changed paths that can change the corpus checks of works whose own files
#: didn't change: these run the checks in full.
FULL_SCOPE_FILES = frozenset({
    "data/normalized/_works.jsonl", "data/normalized/_fingerprints.jsonl",
    "data/normalized/_fingerprint.json", "pyproject.toml", "uv.lock",
    ".github/workflows/ci-python.yml", "patristica/fingerprint.py", "tests/conftest.py",
    "tests/test_anchor_fingerprint.py", "tests/test_alignment.py",
})
FULL_SCOPE_PREFIXES = ("patristica/data/",)
#: The code of the checks: a change to any module these import runs them in full.
SCOPE_CODE = ("scripts.anchor", "scripts.data", "patristica.alignment_store",
              "patristica.versions", "patristica.corpus")


@dataclass(frozen=True)
class Scope:
    """The repo-relative paths a pull request changed (the corpus checks look
    only at the works they touch)."""

    changed: frozenset[str]

    def normalized(self, *paths: str) -> bool:
        """Whether any of these ``data/normalized`` paths changed."""
        return any(f"data/normalized/{p}" in self.changed for p in paths)

    def anchors(self, path: str) -> bool:
        return f"data/anchors/{path}" in self.changed

    def alignment(self, path: str) -> bool:
        """Whether this alignment file (its path in ``data/alignments``) changed."""
        return f"data/alignments/{path}" in self.changed


def full_scope_reason(changed: Iterable[str], root: Path = REPO) -> str | None:
    """Why *changed* needs the corpus checks in full, or None."""
    code = {path.relative_to(root).as_posix()
            for m in fingerprint.module_closure(SCOPE_CODE, root)
            if (path := fingerprint.module_path(m, root)) is not None}
    for path in sorted(changed):
        if path in FULL_SCOPE_FILES or path.startswith(FULL_SCOPE_PREFIXES) or path in code:
            return path
    return None


def check_scope(base: str | None = None) -> Scope | None:
    """The scope of the corpus checks: None to check everything (no base set,
    or a change that can affect unchanged works, or git failed), else the
    paths changed since *base* (default: ``$PATRISTICA_SCOPE_BASE``)."""
    base = base or os.environ.get(SCOPE_ENV)
    if not base:
        return None
    out = subprocess.run(["git", "diff", "--name-only", "--no-renames", base, "HEAD"],
                         cwd=REPO, capture_output=True, text=True)
    if out.returncode != 0:
        log.warning("scope: git diff against %s failed, checking everything: %s",
                    base, out.stderr.strip())
        return None
    changed = frozenset(line for line in out.stdout.splitlines() if line)
    reason = full_scope_reason(changed)
    if reason is not None:
        log.info("scope: %s changed, checking everything", reason)
        return None
    return Scope(changed)


def scoped_anchored_paths(norm: Path, scope: Scope) -> set[str]:
    """:func:`anchored_paths` of the works *scope* touches (their own file, their
    anchor's or their cut file), with their anchors."""
    out: set[str] = set()
    for path, target in _anchor_pairs(norm):
        if scope.normalized(path, target or "") or scope.anchors(path):
            out.add(path)
            if target:
                out.add(target)
    return out


def scoped_aligned_paths(norm: Path, align_dir: Path, scope: Scope) -> set[str]:
    """Every member of each alignment *scope* touches (its file, or a member's)."""
    by_id = {e["work"]["work_id"]: e["path"] for e in _works(norm)}
    out: set[str] = set()
    for path, members in _alignment_members(align_dir):
        paths = [by_id[w] for w in members if w in by_id]
        if scope.alignment(path.relative_to(align_dir).as_posix()) or scope.normalized(*paths):
            out.update(paths)
    return out


def _alignment_members(align_dir: Path) -> Iterator[tuple[Path, list[str]]]:
    """Each alignment file with its member work ids (not decoded further)."""
    if not align_dir.is_dir():
        return
    for path in sorted(align_dir.rglob("*.json")):
        if not path.name.startswith("_"):
            raw = json.loads(path.read_text(encoding="utf-8"))
            yield path, [m["work_id"] for m in raw["members"]]


def anchored_paths(norm: Path) -> set[str]:
    """Works the anchoring rule anchors and their anchors (``tests/test_anchor_fingerprint.py``
    and ``scripts.status``'s anchor row read both, #304, #638)."""
    out: set[str] = set()
    for path, target in _anchor_pairs(norm):
        out.add(path)
        if target:
            out.add(target)
    return out


def _anchor_pairs(norm: Path) -> list[tuple[str, str | None]]:
    """(path, its anchor's path or None) of every work the rule anchors, except
    works normalize records as never anchored."""
    from patristica import anchor_rule

    works = _works(norm)
    by_id = {e["work"]["work_id"]: e["path"] for e in works}
    recorded = anchor_rule.recorded_anchors(norm.parent / "anchors")
    standard = set()  # never anchored: normalize's fingerprint records "anchor": null
    fps = norm / "_fingerprints.jsonl"
    if fps.exists():
        for line in fps.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line) if line.strip() else {}
            if "anchor" in rec and rec["anchor"] is None:
                standard.add(rec["path"])
    return [(by_id[work_id], by_id.get(target))
            for work_id, target in anchor_rule.anchors(
                {e["work"]["work_id"]: e["work"] for e in works}, recorded).items()
            if by_id[work_id] not in standard]


def needs(job: str, norm: Path = NORMALIZED, align_dir: Path | None = None,
          scope: Scope | None = None) -> list[str]:
    """Repo-relative LFS paths *job* reads: ``tests`` the unit tests, ``status``
    also ``scripts.status``. A new test that reads normalized work files adds
    its set here. With a *scope* (:func:`check_scope`), the corpus checks read
    only the works it touches."""
    from patristica import alignment_store as store

    align_dir = align_dir or REPO / store.DEFAULT_DIR
    if job not in ("tests", "status"):
        raise ValueError(f"unknown job {job!r}")
    paths = book_group_paths(norm) | scripture_book_paths(norm) | language_sample_paths(norm)
    if scope is None:
        paths |= aligned_paths(norm, align_dir) | anchored_paths(norm)
    else:
        paths |= scoped_aligned_paths(norm, align_dir, scope) | scoped_anchored_paths(norm, scope)
    if job == "status":
        paths |= translated_paths(norm)
    prefix = norm.relative_to(REPO).as_posix()
    return sorted(f"{prefix}/{p}" for p in paths)


# Bytes of one ``--include=`` argument: Linux caps a single argument at
# MAX_ARG_STRLEN (128 KiB), and the tests' list alone is past that (#494).
INCLUDE_ARG_MAX = 100_000


def include_batches(include: list[str], limit: int = INCLUDE_ARG_MAX) -> list[str]:
    """*include* as comma-joined pattern lists, each at most *limit* bytes."""
    batches: list[str] = []
    current: list[str] = []
    size = 0
    for path in include:
        n = len(path.encode())
        if n > limit:
            raise ValueError(f"LFS include pattern longer than {limit} bytes: {path[:80]}…")
        if current and size + 1 + n > limit:
            batches.append(",".join(current))
            current, size = [], 0
        size += n + (1 if current else 0)
        current.append(path)
    if current:
        batches.append(",".join(current))
    return batches


def lfs_pull(include: list[str] | None, run: Callable[..., object] = subprocess.run,
             limit: int = INCLUDE_ARG_MAX) -> None:
    """``git lfs pull`` of *include* (every data/ tier when None), past ``.lfsconfig``'s
    fetchexclude. A long list is pulled in several runs, each with an ``--include``
    under the kernel's per-argument limit."""
    if include is not None and any("," in p for p in include):
        raise ValueError("git lfs --include is comma-separated: a path contains a comma")
    batches = include_batches(include, limit) if include is not None else ["data/**"]
    for patterns in batches:
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
    sub.add_parser("scope", help=f"whether the corpus checks are scoped (${SCOPE_ENV}): "
                                 "prints 'full' or 'scoped'")
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
        print("\n".join(needs(args.job, scope=check_scope())))
    elif args.cmd == "scope":
        print("full" if check_scope() is None else "scoped")
    elif args.cmd == "pull":
        lfs_pull(None if args.all else needs(args.job, scope=check_scope()))
    elif args.cmd == "pack":
        log.info("clones: %s", pack(force=args.force))
    elif args.cmd == "unpack":
        log.info("clones: %s", unpack(force=args.force))
    elif args.cmd == "status":
        print("\n".join(status()))
    sys.exit(0)


if __name__ == "__main__":
    main()
