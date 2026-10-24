"""The pre-push hook (scripts/hooks/pre-push, #130): which pushes it validates.

The hook runs in a scratch git repository with a stub ``uv`` on ``PATH``: the
stub passes the unit tests, reports the commits listed in ``$CHANGED`` as
changing validate's inputs, and logs each full validation.

Every git process gets an environment without ``GIT_*`` variables: when pytest
itself runs inside a git hook (the pre-push hook runs this suite), git sets
``GIT_DIR`` and friends, and inheriting them would point these commands at the
enclosing repository instead of the scratch one.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[1] / "scripts" / "hooks" / "pre-push"
ZERO = "0" * 40

STUB_UV = """#!/usr/bin/env bash
case "$*" in
  *--inputs-changed*) rev="${@: -1}"; grep -qx "$rev" "$CHANGED" && echo data/normalized/x.json ;;
  *pytest*) exit 0 ;;
  *scripts.validate*) echo validate >> "$LOG" ;;
esac
exit 0
"""

# git runs `git lfs …` as git-lfs on PATH: record the call and the ref lines it was given.
STUB_LFS = """#!/usr/bin/env bash
{ echo "lfs $*"; cat; } >> "$LFS_LOG"
"""


def clean_env(**extra: str) -> dict[str, str]:
    """``os.environ`` without git's per-repository variables, plus *extra*."""
    return {**{k: v for k, v in os.environ.items() if not k.startswith("GIT_")}, **extra}


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True, env=clean_env()).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> dict:
    if shutil.which("git") is None:
        pytest.skip("git not available")
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "master")
    git_dir = Path(git(root, "rev-parse", "--absolute-git-dir")).resolve()
    assert git_dir.is_relative_to(tmp_path.resolve()), f"not a scratch repository: {git_dir}"
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    shas = []
    for name in ("base", "other", "head"):
        (root / f"{name}.txt").write_text(name)
        git(root, "add", ".")
        git(root, "commit", "-q", "-m", name)
        shas.append(git(root, "rev-parse", "HEAD"))
        if name == "base":
            git(root, "switch", "-q", "-c", "feature")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "uv").write_text(STUB_UV)
    (bin_dir / "uv").chmod(0o755)
    (bin_dir / "git-lfs").write_text(STUB_LFS)
    (bin_dir / "git-lfs").chmod(0o755)
    return {"root": root, "base": shas[0], "other": shas[1], "head": shas[2],
            "bin": bin_dir, "changed": tmp_path / "changed", "log": tmp_path / "log",
            "lfs_log": tmp_path / "lfs_log"}


def push(repo: dict, lines: list[str], changed: list[str], **env: str) -> tuple[int, str, int]:
    """Run the hook; return (exit code, stderr, number of full validations)."""
    repo["changed"].write_text("".join(f"{c}\n" for c in changed))
    repo["log"].write_text("")
    repo["lfs_log"].write_text("")
    proc = subprocess.run(
        ["bash", str(HOOK)], cwd=repo["root"], input="".join(f"{line}\n" for line in lines),
        capture_output=True, text=True,
        env=clean_env(PATH=f"{repo['bin']}:{os.environ['PATH']}",
                      CHANGED=str(repo["changed"]), LOG=str(repo["log"]),
                      LFS_LOG=str(repo["lfs_log"]), **env))
    return proc.returncode, proc.stderr, len(repo["log"].read_text().splitlines())


def ref(local: str, remote_sha: str, branch: str = "feature") -> str:
    return f"refs/heads/{branch} {local} refs/heads/{branch} {remote_sha}"


def test_pushed_head_that_changes_inputs_is_validated(repo) -> None:
    code, _, runs = push(repo, [ref(repo["head"], repo["base"])], changed=[repo["head"]])
    assert (code, runs) == (0, 1)


def test_unchanged_inputs_are_not_validated(repo) -> None:
    assert push(repo, [ref(repo["head"], repo["base"])], changed=[])[::2] == (0, 0)


def test_another_revision_that_changes_inputs_is_refused(repo) -> None:
    """A ref that isn't HEAD can't be validated from this checkout (#204 review)."""
    code, err, runs = push(repo, [ref(repo["other"], repo["base"], "other")],
                           changed=[repo["other"]])
    assert (code, runs) == (1, 0)
    assert "isn't the checked-out HEAD" in err


def test_every_pushed_ref_is_checked(repo) -> None:
    lines = [ref(repo["head"], repo["base"]), ref(repo["other"], repo["base"], "other")]
    code, _, runs = push(repo, lines, changed=[repo["other"]])
    assert (code, runs) == (1, 0)  # the second ref is not HEAD


def test_new_branch_compares_with_master_and_deletions_are_skipped(repo) -> None:
    lines = [ref(repo["head"], ZERO), f"(delete) {ZERO} refs/heads/gone {repo['base']}"]
    assert push(repo, lines, changed=[repo["head"]])[::2] == (0, 1)


def test_push_to_master_is_refused(repo) -> None:
    code, err, _ = push(repo, [ref(repo["head"], repo["base"], "master")], changed=[])
    assert code == 1 and "direct pushes to master" in err


def test_skip_variable(repo) -> None:
    assert push(repo, [ref(repo["head"], repo["base"])], changed=[repo["head"]],
                PATRISTICA_SKIP_VALIDATE="1")[::2] == (0, 0)


def test_lfs_objects_are_pushed_with_the_same_ref_lines(repo) -> None:
    """data/ is in git-lfs (#244): the hook hands git's ref lines to git lfs pre-push,
    also when validation is skipped."""
    line = ref(repo["head"], repo["base"])
    for env in ({}, {"PATRISTICA_SKIP_VALIDATE": "1"}):
        code, _, _ = push(repo, [line], [], **env)
        assert code == 0
        assert repo["lfs_log"].read_text().splitlines() == ["lfs pre-push", line]


def test_lfs_objects_are_not_pushed_when_a_check_fails(repo) -> None:
    code, _, _ = push(repo, [ref(repo["head"], repo["base"], "master")], [])
    assert code == 1 and repo["lfs_log"].read_text() == ""
