"""--offline for the ingestors (#215): nothing touches the network."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import httpx
import pytest

from scripts.ingest import _common, _stamp
from scripts.ingest._common import OfflineError, offline_mode


@pytest.fixture(autouse=True)
def _no_git_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop the GIT_* variables of an enclosing hook (#231): the code under test
    runs git in temporary repos, and GIT_DIR would point it at the pushing one."""
    for key in [k for k in os.environ if k.startswith("GIT_")]:
        monkeypatch.delenv(key)


@pytest.fixture
def no_subprocess(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Record subprocess.run calls in _common instead of running them."""
    calls: list[list[str]] = []
    monkeypatch.setattr(_common.subprocess, "run", lambda cmd, **kw: calls.append(cmd))
    return calls


# ---------------------------------------------------------------------------
# The switch and the safety net
# ---------------------------------------------------------------------------


def test_offline_mode_refuses_every_http_request_and_is_restored() -> None:
    send = httpx.Client.send
    with offline_mode():
        assert _common.offline()
        with pytest.raises(OfflineError, match="example.invalid"):
            httpx.Client().get("http://example.invalid/x")
        with pytest.raises(OfflineError):
            httpx.get("http://example.invalid/y")
    assert not _common.offline()
    assert httpx.Client.send is send


def test_offline_mode_false_is_a_no_op() -> None:
    send = httpx.Client.send
    with offline_mode(False):
        assert not _common.offline() and httpx.Client.send is send


def test_offline_mode_is_restored_after_an_error() -> None:
    with pytest.raises(ValueError), offline_mode():
        raise ValueError
    assert not _common.offline()


# ---------------------------------------------------------------------------
# download_file and ensure_repo
# ---------------------------------------------------------------------------


def test_download_file_uses_the_cache_even_with_force(tmp_path: Path) -> None:
    dest = tmp_path / "book.zip"
    dest.write_bytes(b"cached")
    with offline_mode():
        assert _common.download_file("http://example.invalid/book.zip", dest, force=True) == dest
    assert dest.read_bytes() == b"cached"


def test_download_file_without_a_cache_raises(tmp_path: Path) -> None:
    with offline_mode(), pytest.raises(OfflineError, match="book.zip"):
        _common.download_file("http://example.invalid/book.zip", tmp_path / "book.zip")


def test_ensure_repo_offline_uses_the_clone_without_pulling(tmp_path, no_subprocess) -> None:
    (tmp_path / "repo").mkdir()
    with offline_mode():
        _common.ensure_repo("https://example.invalid/r.git", tmp_path / "repo", "R", force=True)
    assert no_subprocess == []


def test_ensure_repo_offline_without_a_clone_raises(tmp_path, no_subprocess) -> None:
    with offline_mode(), pytest.raises(OfflineError, match="cloning"):
        _common.ensure_repo("https://example.invalid/r.git", tmp_path / "repo", "R")
    assert no_subprocess == []


def test_ensure_repo_online_pulls_on_force(tmp_path, no_subprocess) -> None:
    (tmp_path / "repo").mkdir()
    _common.ensure_repo("https://example.invalid/r.git", tmp_path / "repo", "R", force=True)
    assert no_subprocess == [["git", "-C", str(tmp_path / "repo"), "pull", "--ff-only"]]


# ---------------------------------------------------------------------------
# Ingestors with their own caches: --force rewrites outputs, not inputs
# ---------------------------------------------------------------------------


def test_cursus_uses_its_cached_zip(tmp_path: Path) -> None:
    from scripts.ingest import cursus

    zip_path = tmp_path / "cursus.zip"
    zip_path.write_bytes(b"PK")
    with offline_mode():
        cursus._ensure_zip(zip_path, force=True)  # no download
        with pytest.raises(OfflineError):
            cursus._ensure_zip(tmp_path / "missing.zip", force=True)


def test_armenian_uses_cached_pages(tmp_path: Path) -> None:
    from scripts.ingest import armenian

    cache = tmp_path / "page.html"
    cache.write_text("<html>cached</html>")
    with offline_mode(), httpx.Client() as client:
        assert "cached" in armenian._fetch_cached("http://example.invalid/p", cache, True, client)
        with pytest.raises(OfflineError):
            armenian._fetch_cached("http://example.invalid/q", tmp_path / "none.html", True,
                                   client)


def test_mozarabic_uses_its_cached_search(tmp_path: Path) -> None:
    from scripts.ingest import mozarabic

    with offline_mode():
        with pytest.raises(OfflineError, match="Internet Archive"):
            mozarabic._ia_search_first_id("liber ordinum", tmp_path, force=True)
        key = "liber_ordinum"
        (tmp_path / f"_ia_search_{key}.json").write_text(json.dumps({"identifier": "lib-ord"}))
        assert mozarabic._ia_search_first_id("liber ordinum", tmp_path, force=True) == "lib-ord"


def test_ogpg_uses_its_cached_repo_list(tmp_path: Path) -> None:
    from scripts.ingest import ogpg

    cache = tmp_path / "repos.json"
    with offline_mode():
        with pytest.raises(OfflineError):
            ogpg._list_repos(cache, force=True)
        cache.write_text(json.dumps(["Vol.-1"]))
        assert ogpg._list_repos(cache, force=True) == ["Vol.-1"]


def test_ogpg_never_clones_offline(tmp_path: Path) -> None:
    from scripts.ingest import ogpg

    with offline_mode(), pytest.raises(OfflineError, match="cloning"):
        ogpg._sparse_clone_with_pattern("Vol.-1", "*.txt", tmp_path / "clone")


def test_ogpg_offline_force_without_a_clone_reuses_a_current_extraction(tmp_path: Path,
                                                                       monkeypatch) -> None:
    """The extraction made with this pipeline is what re-extracting would produce."""
    from scripts.ingest import ogpg

    extract_dir = tmp_path / "_extract"
    extract_dir.mkdir()
    saved = {"repo": "Vol.-1", "pipeline": {"id": ogpg._pipeline_id()}, "page_heads": {},
             "paragraphs": []}
    (extract_dir / "vol-001.json").write_text(json.dumps(saved))
    monkeypatch.setattr(ogpg, "_sparse_clone",
                        lambda *a, **k: pytest.fail("must not clone offline"))
    with offline_mode():
        assert ogpg._extract_volume("Vol.-1", tmp_path / "_repos", extract_dir, force=True) == saved


def test_ogpg_offline_force_without_a_clone_needs_a_current_extraction(tmp_path: Path) -> None:
    from scripts.ingest import ogpg

    extract_dir = tmp_path / "_extract"
    extract_dir.mkdir()
    (extract_dir / "vol-001.json").write_text(json.dumps({"pipeline": {"id": "older"}}))
    with offline_mode(), pytest.raises(OfflineError, match="cloning"):
        ogpg._extract_volume("Vol.-1", tmp_path / "_repos", extract_dir, force=True)


def _git_repo(path: Path, files: dict[str, str]) -> None:
    """A committed repo at *path*. git runs without the GIT_* variables of an
    enclosing hook, so it can't touch another repository."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    path.mkdir(parents=True)
    for rel, text in files.items():
        (path / rel).parent.mkdir(parents=True, exist_ok=True)
        (path / rel).write_text(text)

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True, env=env)

    git("init", "-q")
    git("-c", "user.email=t@example.com", "-c", "user.name=t", "add", ".")
    git("-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-q", "-m", "x")


def test_ogpg_offline_marks_a_repo_whose_tree_has_no_ocr_text(tmp_path: Path) -> None:
    from scripts.ingest import ogpg

    repos, extract_dir = tmp_path / "_repos", tmp_path / "_extract"
    _git_repo(repos / "Vol.-61-62", {".gitignore": "*.pyc\n"})
    with offline_mode():
        assert ogpg._extract_volume("Vol.-61-62", repos, extract_dir, force=True) is None
    marker = json.loads((extract_dir / "vol-061-062.json").read_text())
    assert marker["empty"] and marker["pipeline"]["id"] == ogpg._pipeline_id()
    with offline_mode():  # a later run reads the marker
        assert ogpg._extract_volume("Vol.-61-62", repos, extract_dir, force=True) is None


def test_ogpg_offline_still_refuses_a_clone_with_ocr_text_not_checked_out(tmp_path: Path) -> None:
    """Text in the tree but not on disk needs a checkout: that is unknown offline."""
    from scripts.ingest import ogpg

    repo = tmp_path / "_repos" / "Vol.-1"
    _git_repo(repo, {"hvd.123_ocr/0001.txt": "κείμενον"})
    (repo / "hvd.123_ocr" / "0001.txt").unlink()
    with offline_mode(), pytest.raises(OfflineError, match="cloning"):
        ogpg._extract_volume("Vol.-1", tmp_path / "_repos", tmp_path / "_extract", force=True)


# ---------------------------------------------------------------------------
# With the stamps
# ---------------------------------------------------------------------------


def _cached_ingestor(cache: Path):
    def ingest(output_dir: Path, force: bool = False) -> list:
        _common.download_file("http://example.invalid/src.xml", cache, force=force)
        out = output_dir / "src" / "w.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"work": {"work_id": "src/w"}, "paragraphs": []}))
        return [out]
    return ingest


def test_force_offline_regenerates_and_stamps_from_the_cache(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(_stamp, "ingest_code_hash", lambda source_id: "code-1")
    cache = tmp_path / "cache" / "src.xml"
    cache.parent.mkdir()
    cache.write_text("<xml/>")
    with offline_mode():
        _stamp.run_stamped(_cached_ingestor(cache), tmp_path / "raw", "src", force=True)
    assert _stamp.read_stamp(tmp_path / "raw", "src") == "code-1"


def test_force_offline_without_the_cache_fails_unstamped(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(_stamp, "ingest_code_hash", lambda source_id: "code-1")
    with offline_mode(), pytest.raises(OfflineError):
        _stamp.run_stamped(_cached_ingestor(tmp_path / "missing.xml"), tmp_path / "raw", "src",
                           force=True)
    assert _stamp.read_stamp(tmp_path / "raw", "src") is None
