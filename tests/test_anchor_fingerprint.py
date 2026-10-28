"""Staleness of the tracked cut files of anchored derived verses (#304, #130).

Needs no vectors and no numpy: an enrolled work whose original is in the
corpus must have a cut file made from its current words, and its normalized
output must be cut as the file says. A cut file whose original changed since
is *frozen* (re-cut only with ``scripts.anchor --recut``): ``scripts.status``
reports it, this test doesn't fail on it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica import anchoring
from scripts import anchor, status
from scripts import normalize as nz

ROOT = Path(__file__).resolve().parents[1]
NORMALIZED = ROOT / "data" / "normalized"
ANCHORS = ROOT / "data" / "anchors"
RERUN = ("run `uv run --extra embed python -m scripts.anchor --pay` (paid, cents: ask the owner "
         "first) and commit data/anchors, data/normalized and data/embeddings; where only the "
         "output is stale, re-run scripts.normalize")


def test_every_enrolled_work_has_a_current_cut_file() -> None:
    bad = [anchor.describe(s) for s in anchor.check_works(NORMALIZED, ANCHORS)
           if s.status in anchor.FAILING]
    assert not bad, f"missing or stale cut files ({RERUN}): " + ", ".join(bad[:10])


def test_nothing_is_enrolled_without_a_reason() -> None:
    assert all(anchoring.load_enrolment().values())


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(anchoring, "enrolled_sources", lambda: {"tr": "test"})
    raw, norm = tmp_path / "raw", tmp_path / "normalized"
    for rel, lang, extra in (("orig/w.json", "lat", {}),
                             ("tr/w.json", "eng", {"translation_of": "orig/w"}),
                             ("tr/free.json", "eng", {})):
        source, name = rel.split("/")[0], Path(rel).stem
        (raw / source).mkdir(parents=True, exist_ok=True)
        (raw / rel).write_text(json.dumps({
            "work": {"work_id": f"{source}/{name}", "source_id": source, "title": "T",
                     "genre": "patristic", "language": lang, "license": "public_domain",
                     **extra},
            "paragraphs": [{"ref": "P.1", "text": "Some words. More words here."}]}))
    nz.normalize_all(raw, norm)
    return norm


def test_status_fails_on_a_missing_cut_file(corpus: Path) -> None:
    states = anchor.check_works(corpus, corpus.parent / "anchors")
    assert [(s.candidate.work_id, s.status) for s in states] == [("tr/w", anchor.MISSING)]
    [row] = status.anchor_rows(corpus, corpus.parent / "anchors")
    assert row.level == "fail" and "tr/w: missing" in row.detail
    p = anchor.plan(corpus, corpus.parent / "anchors")
    assert [s.candidate.work_id for s in p.todo] == ["tr/w"]


def test_status_is_ok_with_nothing_enrolled(corpus: Path, monkeypatch) -> None:
    monkeypatch.setattr(anchoring, "enrolled_sources", lambda: {})
    [row] = status.anchor_rows(corpus, corpus.parent / "anchors")
    assert row.level == "ok"
    assert anchor.pending(corpus, corpus.parent / "anchors") == (0, 0.0)
