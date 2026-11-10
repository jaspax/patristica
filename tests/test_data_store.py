"""Tests for data/ in git-lfs (#244): scripts.data (clone archives, what a job
reads, the pull command) and scripts.ingest._clone (git dirs outside the tree)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts import data
from scripts.ingest import _clone


def clean_env() -> dict[str, str]:
    """``os.environ`` without git's per-repository variables (the pre-push hook
    runs this suite with GIT_DIR set)."""
    return {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env=clean_env()).stdout.strip()


def make_repo(path: Path, files: dict[str, str]) -> str:
    """A git repo at *path* with *files* committed; its HEAD."""
    path.mkdir(parents=True)
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.email", "t@example.com")
    git(path, "config", "user.name", "t")
    for name, text in files.items():
        (path / name).parent.mkdir(parents=True, exist_ok=True)
        (path / name).write_text(text)
    git(path, "add", ".")
    git(path, "commit", "-q", "-m", "c")
    return git(path, "rev-parse", "HEAD")


@pytest.fixture(autouse=True)
def no_git_env(monkeypatch):
    if shutil.which("git") is None:
        pytest.skip("git not available")
    for k in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(k)


# ---------------------------------------------------------------------------
# Clone archives
# ---------------------------------------------------------------------------


def test_pack_unpack_round_trip_and_repack_only_changes(tmp_path: Path):
    repos, archives = tmp_path / "_repos", tmp_path / "_repo_archives"
    head = make_repo(repos / "coptic", {"a.xml": "alpha"})
    make_repo(repos / "ogpg" / "Vol.-3", {"001.txt": "page"})
    git(repos / "coptic", "remote", "add", "origin", "https://example.org/coptic.git")

    assert data.pack(repos, tmp_path / "_gitdirs", archives, jobs=1) == {
        "archived": 2, "unchanged": 0, "removed": 0}
    manifest = json.loads((archives / "_manifest.json").read_text())
    assert sorted(manifest["repos"]) == ["coptic", "ogpg/Vol.-3"]
    assert manifest["repos"]["coptic"]["head"] == head
    assert manifest["repos"]["coptic"]["url"] == "https://example.org/coptic.git"
    assert (archives / "ogpg" / "Vol.-3.tar.gz").exists()

    # Nothing changed: nothing re-archived. A new file in one clone: only it.
    assert data.pack(repos, tmp_path / "_gitdirs", archives, jobs=1)["archived"] == 0
    (repos / "coptic" / "b.xml").write_text("beta")
    assert data.pack(repos, tmp_path / "_gitdirs", archives, jobs=1) == {
        "archived": 1, "unchanged": 1, "removed": 0}

    # A fresh checkout: the clones come back, git dir and all.
    shutil.rmtree(repos)
    assert data.unpack(repos, archives) == {"restored": 2, "present": 0}
    assert (repos / "coptic" / "b.xml").read_text() == "beta"
    assert git(repos / "coptic", "rev-parse", "HEAD") == head
    assert data.unpack(repos, archives) == {"restored": 0, "present": 2}

    # A clone that is gone loses its archive.
    shutil.rmtree(repos / "ogpg")
    assert data.pack(repos, tmp_path / "_gitdirs", archives, jobs=1)["removed"] == 1
    assert not (archives / "ogpg" / "Vol.-3.tar.gz").exists()


def test_unpack_refuses_pointers_and_corrupt_archives(tmp_path: Path):
    repos, archives = tmp_path / "_repos", tmp_path / "_repo_archives"
    make_repo(repos / "gez", {"a.txt": "x"})
    data.pack(repos, tmp_path / "_gitdirs", archives, jobs=1)
    shutil.rmtree(repos)
    archive = archives / "gez.tar.gz"
    archive.write_bytes(b"version https://git-lfs.github.com/spec/v1\noid sha256:0\nsize 1\n")
    with pytest.raises(FileNotFoundError, match="pull --all"):
        data.unpack(repos, archives)
    archive.write_bytes(b"not the archive")
    with pytest.raises(ValueError, match="sha256"):
        data.unpack(repos, archives)


def test_clone_state_ignores_git_bookkeeping(tmp_path: Path):
    clone = tmp_path / "c"
    make_repo(clone, {"a.txt": "x"})
    before = data.clone_state(clone)
    (clone / ".git" / "FETCH_HEAD").write_text("anything")
    git(clone, "status")  # may rewrite the index
    assert data.clone_state(clone) == before
    (clone / "new.txt").write_text("y")
    assert data.clone_state(clone) != before


def test_gitdirs_are_recorded_not_archived(tmp_path: Path):
    raw = tmp_path / "raw"
    head = make_repo(raw / "pta", {"data/x.xml": "x"})
    shutil.move(str(raw / "pta" / ".git"), str(raw / "_gitdirs" / "pta.git"))
    data.pack(raw / "_repos", raw / "_gitdirs", raw / "_repo_archives", jobs=1)
    manifest = json.loads((raw / "_repo_archives" / "_manifest.json").read_text())
    assert manifest["gitdirs"] == {"pta": {"url": "", "head": head}}
    assert manifest["repos"] == {}


# ---------------------------------------------------------------------------
# What a job reads
# ---------------------------------------------------------------------------


def test_needs_lists_paths_under_the_repo():
    tests = data.needs("tests")
    assert tests and all(p.startswith("data/normalized/") for p in tests)
    assert any(p.startswith("data/normalized/kjv/") for p in tests)
    status = data.needs("status")
    assert set(tests) <= set(status)
    with pytest.raises(ValueError):
        data.needs("deploy")


def test_needs_includes_anchored_works_and_their_originals(tmp_path, monkeypatch):
    lines = [{"path": "tr/w.json", "work": {"work_id": "tr/w", "source_id": "tr",
                                             "language": "eng", "translation_of": "orig/w"}},
             {"path": "orig/w.json", "work": {"work_id": "orig/w", "source_id": "orig",
                                               "language": "lat"}},
             {"path": "other/x.json", "work": {"work_id": "other/x", "source_id": "other",
                                                "language": "lat"}}]
    (tmp_path / "_works.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
    assert data.anchored_paths(tmp_path) == {"tr/w.json", "orig/w.json"}


def test_lfs_pull_overrides_the_default_exclude():
    calls = []
    data.lfs_pull(["data/normalized/kjv/gen.json", "data/normalized/kjv/exod.json"],
                  run=lambda cmd, **kw: calls.append(cmd))
    data.lfs_pull(None, run=lambda cmd, **kw: calls.append(cmd))
    data.lfs_pull([], run=lambda cmd, **kw: calls.append(cmd))
    assert calls == [
        ["git", "-c", "lfs.fetchexclude=", "lfs", "pull",
         "--include=data/normalized/kjv/gen.json,data/normalized/kjv/exod.json"],
        ["git", "-c", "lfs.fetchexclude=", "lfs", "pull", "--include=data/**"]]
    with pytest.raises(ValueError, match="comma"):
        data.lfs_pull(["data/a,b.json"], run=lambda cmd, **kw: None)


def test_lfs_pull_batches_a_long_include_list():
    paths = [f"data/normalized/src/w{i:03}.json" for i in range(100)]  # 28 bytes each
    calls = []
    data.lfs_pull(paths, run=lambda cmd, **kw: calls.append(cmd), limit=300)
    includes = [c[-1].removeprefix("--include=") for c in calls]
    assert len(calls) > 1
    assert all(len(i.encode()) <= 300 for i in includes)
    assert [p for i in includes for p in i.split(",")] == paths


def test_include_batches_edges():
    assert data.include_batches([], limit=10) == []
    assert data.include_batches(["abcd", "efgh"], limit=9) == ["abcd,efgh"]
    assert data.include_batches(["abcd", "efgh"], limit=8) == ["abcd", "efgh"]
    with pytest.raises(ValueError, match="longer"):
        data.include_batches(["x" * 11], limit=10)


# ---------------------------------------------------------------------------
# Ingest trees with their git dir outside (scripts.ingest._clone)
# ---------------------------------------------------------------------------


def test_ensure_clone_moves_an_inner_git_dir_and_pulls_with_it(tmp_path: Path):
    upstream = tmp_path / "upstream"
    make_repo(upstream, {"data/a.xml": "one"})
    raw = tmp_path / "raw"
    raw.mkdir()
    git(raw, "clone", "-q", str(upstream), "first1k")
    (raw / "first1k" / "out.json").write_text("{}")  # ingest output, untracked upstream

    _clone.ensure_clone(str(upstream), raw / "first1k", "t")
    assert not (raw / "first1k" / ".git").exists()
    git_dir = raw / "_gitdirs" / "first1k.git"
    assert git_dir.is_dir()

    (upstream / "data" / "a.xml").write_text("two")
    git(upstream, "commit", "-qam", "update")
    _clone.ensure_clone(str(upstream), raw / "first1k", "t", force=True)
    assert (raw / "first1k" / "data" / "a.xml").read_text() == "two"
    assert (raw / "first1k" / "out.json").read_text() == "{}"


def test_ensure_clone_uses_tracked_files_and_reclones_on_force(tmp_path: Path):
    upstream = tmp_path / "upstream"
    make_repo(upstream, {"data/a.xml": "one"})
    tree = tmp_path / "raw" / "pta"
    (tree / "data").mkdir(parents=True)
    (tree / "data" / "a.xml").write_text("stale")  # as checked out from git-lfs
    (tree / "out.json").write_text("{}")

    _clone.ensure_clone(str(upstream), tree, "t")  # no git dir, no --force: used as it is
    assert (tree / "data" / "a.xml").read_text() == "stale"
    assert not (tmp_path / "raw" / "_gitdirs").exists()

    _clone.ensure_clone(str(upstream), tree, "t", force=True)
    assert (tree / "data" / "a.xml").read_text() == "one"
    assert (tree / "out.json").read_text() == "{}"
    assert not (tree / ".git").exists()
    assert not (tmp_path / "raw" / "_gitdirs" / "pta.clone").exists()


def test_ensure_clone_offline_uses_the_tracked_files(tmp_path: Path):
    """A fresh checkout has the tree but no git dir: --force --offline re-ingests
    from the tree (re-stamping, #215) instead of trying to clone."""
    from scripts.ingest._common import offline_mode

    tree = tmp_path / "raw" / "oglt-pl"
    tree.mkdir(parents=True)
    (tree / "a.xml").write_text("tracked")
    with offline_mode():
        _clone.ensure_clone("https://example.org/never.git", tree, "t", force=True)
    assert (tree / "a.xml").read_text() == "tracked"
    assert not (tmp_path / "raw" / "_gitdirs").exists()
