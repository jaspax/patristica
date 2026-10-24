"""
Upstream clones whose working tree the patristica repo tracks (#244).

PTA, First1K and OGLT PL are shallow git clones of their upstream repos, and
their ingestors write their per-work JSON into the same tree. The working tree
is tracked in this repo (git-lfs), but git refuses to track files below a
directory that holds a ``.git``, so each clone's git dir lives in
``data/raw/_gitdirs/{name}.git`` instead and every git command names both
(``--git-dir`` / ``--work-tree``). Never ``git -C`` such a tree: with no
``.git`` there, git would climb to this repo.

A clone's git dir is only needed to update it (``--force``): a checkout has
the files from git-lfs, so without a git dir and without ``--force`` the
tree is used as it is.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from scripts.ingest._common import offline, require_network

log = logging.getLogger(__name__)

GIT_DIRS = "_gitdirs"


def git_dir_for(repo_dir: Path) -> Path:
    """Where *repo_dir*'s git dir lives: ``{raw}/_gitdirs/{name}.git``."""
    return repo_dir.parent / GIT_DIRS / f"{repo_dir.name}.git"


def ensure_clone(repo_url: str, repo_dir: Path, label: str, force: bool = False) -> None:
    """Make *repo_dir* a usable clone of *repo_url*; pull the latest on *force*.

    A ``.git`` left inside the tree (a clone made before #244) is moved to
    ``_gitdirs/`` first. Offline, nothing is fetched; a missing tree raises
    ``OfflineError``.
    """
    git_dir = git_dir_for(repo_dir)
    inner = repo_dir / ".git"
    if inner.is_dir() and not git_dir.exists():
        log.info("moving %s's git dir to %s (#244)", label, git_dir)
        git_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(inner), str(git_dir))
    elif inner.exists():
        raise RuntimeError(f"{repo_dir} has a .git and {git_dir} exists too: remove one")
    git = ["git", f"--git-dir={git_dir}", f"--work-tree={repo_dir}"]

    if git_dir.exists():
        if force and offline():
            log.info("--offline: using the existing %s clone without pulling", label)
        elif force:
            log.info("Pulling latest %s data …", label)
            subprocess.run([*git, "pull", "--ff-only"], check=True)
        return
    if repo_dir.exists() and not force:
        return  # the tracked files; a clone is only needed to update them
    if repo_dir.exists() and offline():
        log.info("--offline: using the %s files without a clone to pull", label)
        return
    require_network(f"cloning {repo_url}")
    log.info("Cloning %s repo into %s …", label, repo_dir)
    scratch = git_dir.parent / f"{repo_dir.name}.clone"
    git_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", "--depth=1", "--no-checkout",
                    f"--separate-git-dir={git_dir}", repo_url, str(scratch)], check=True)
    shutil.rmtree(scratch)  # holds only the .git file pointing at git_dir
    repo_dir.mkdir(parents=True, exist_ok=True)
    # Writes the upstream files over the tree; ingest output (untracked upstream) stays.
    subprocess.run([*git, "checkout", "-f", "HEAD"], check=True)
