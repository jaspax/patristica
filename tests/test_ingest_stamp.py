"""Ingest stamps (#130): scripts.ingest._stamp and normalize copying them."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica import fingerprint, genres
from scripts import normalize as nz
from scripts import status
from scripts.ingest import _stamp


def fake_ingestor(text: str = "Text"):
    """An ingest() that writes one work, skipping it if it exists unless forced."""
    def ingest(output_dir: Path, force: bool = False) -> list:
        path = output_dir / "src" / "w.json"
        if path.exists() and not force:
            return []
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "work": {"work_id": "src/w", "source_id": "src", "title": "T", "genre": "patristic",
                     "language": "eng", "license": "public_domain"},
            "paragraphs": [{"ref": "T.1", "text": text}]}), encoding="utf-8")
        return [path]
    return ingest


@pytest.fixture
def code(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    current = ["ingest-1"]
    monkeypatch.setattr(_stamp, "ingest_code_hash", lambda source_id: current[0])
    return current


def test_module_for_follows_the_source_id_convention() -> None:
    assert _stamp.module_for("lxx-rahlfs") == "scripts.ingest.lxx_rahlfs"
    assert _stamp.module_for("oshb") == "scripts.ingest.oshb"


def test_ingest_hash_leaves_out_the_shared_runners() -> None:
    modules = fingerprint.module_closure(_stamp.module_for("oshb"), ignore=_stamp.RUNNERS)
    assert "scripts.ingest.oshb" in modules and "scripts.ingest._common" in modules
    assert not set(_stamp.RUNNERS) & set(modules)
    assert _stamp.ingest_code_hash("no-such-source") is None


def test_first_run_stamps_then_a_changed_ingestor_needs_force(tmp_path, code, caplog) -> None:
    _stamp.run_stamped(fake_ingestor(), tmp_path, "src")
    assert _stamp.read_stamp(tmp_path, "src") == "ingest-1"

    code[0] = "ingest-2"
    _stamp.run_stamped(fake_ingestor("New"), tmp_path, "src")  # skips the existing file
    assert _stamp.read_stamp(tmp_path, "src") == "ingest-1"
    assert "re-run with --force" in caplog.text

    _stamp.run_stamped(fake_ingestor("New"), tmp_path, "src", force=True)
    assert _stamp.read_stamp(tmp_path, "src") == "ingest-2"


def test_unstamped_old_raw_is_not_stamped_without_force(tmp_path, code) -> None:
    fake_ingestor()(tmp_path)  # raw from before ingest stamps
    _stamp.run_stamped(fake_ingestor(), tmp_path, "src")
    assert _stamp.read_stamp(tmp_path, "src") is None


@pytest.fixture
def normalized(tmp_path: Path, code, monkeypatch) -> tuple[Path, Path]:
    monkeypatch.setattr(genres, "_overrides", lambda: {})
    monkeypatch.setattr(nz, "normalize_code_hash", lambda: "norm-1")
    raw, norm = tmp_path / "raw", tmp_path / "normalized"
    _stamp.run_stamped(fake_ingestor(), raw, "src")
    nz.normalize_all(raw, norm)
    return raw, norm


def test_normalize_copies_the_stamp(normalized) -> None:
    raw, norm = normalized
    assert nz.read_step_fingerprints(norm)["ingest"] == {"src": "ingest-1"}


def test_refused_source_keeps_its_old_stamp(normalized, code) -> None:
    raw, norm = normalized
    code[0] = "ingest-2"
    _stamp.run_stamped(fake_ingestor("Changed"), raw, "src", force=True)
    with pytest.raises(nz.RawChangedError):
        nz.normalize_all(raw, norm)
    assert nz.read_step_fingerprints(norm)["ingest"] == {"src": "ingest-1"}
    nz.normalize_all(raw, norm, accept_raw_change=True)
    assert nz.read_step_fingerprints(norm)["ingest"] == {"src": "ingest-2"}


def test_status_warns_about_a_changed_ingestor(normalized, code) -> None:
    raw, norm = normalized
    assert status.ingest_drift(norm) == ([], [])
    code[0] = "ingest-2"  # the ingestor changed; the data wasn't regenerated
    assert status.ingest_drift(norm) == (["src"], [])
    (raw / "src" / _stamp.STAMP).unlink()
    nz.normalize_all(raw, norm, force=True)  # unstamped raw: the stamp is unknown
    assert status.ingest_drift(norm) == ([], ["src"])
