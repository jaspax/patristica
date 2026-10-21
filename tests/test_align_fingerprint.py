"""Staleness of the tracked passage alignments (#130).

These check the committed ``data/alignments`` against this branch's code and
version groups. They need no vectors: what they can't see (vectors that
changed since the last run) ``scripts.align`` checks itself, refusing groups
whose members lack current vectors. ``tests/test_alignment.py`` checks the
other way round, that each file's members still have the units it counts.
"""

from __future__ import annotations

from pathlib import Path

from patristica import alignment_store as store
from patristica.corpus import load_works, select
from scripts import align

ROOT = Path(__file__).resolve().parents[1]
NORMALIZED = ROOT / "data" / "normalized"
ALIGNMENTS = ROOT / "data" / "alignments"
RERUN = ("re-run `uv run --extra embed python -m scripts.align --embeddings-dir "
         "data/embeddings` (after scripts.embed) and commit data/alignments")


def test_committed_alignments_were_made_with_this_code() -> None:
    recorded = align.read_fingerprint(ALIGNMENTS).get(align.STEP, {}).get("code")
    assert recorded == align.align_code_hash(), (
        f"the aligner's code changed since data/alignments was produced: {RERUN}"
    )


def _publishable_members() -> dict[str, list[str]]:
    works = load_works(NORMALIZED)
    publishable = {e["work"]["work_id"] for e in select(works, [], [], False)}
    return {g: [w for w in mem if w in publishable]
            for g, mem in align.version_groups(works).items()}


def test_every_version_group_is_aligned_or_recorded_as_skipped() -> None:
    skipped = align.read_fingerprint(ALIGNMENTS).get("skipped", {})
    missing = sorted(
        g for g, mem in _publishable_members().items()
        if len(mem) >= 2 and g not in skipped and not store.path_for(ALIGNMENTS, g).exists()
    )
    assert not missing, f"version groups with no alignment ({RERUN}): {missing[:10]}"


def test_recorded_skips_are_current_groups() -> None:
    skipped = align.read_fingerprint(ALIGNMENTS).get("skipped", {})
    groups = _publishable_members()
    gone = sorted(g for g in skipped if len(groups.get(g, [])) < 2)
    assert not gone, (
        f"_fingerprint.json skips groups that no longer need aligning ({RERUN}): {gone}"
    )
