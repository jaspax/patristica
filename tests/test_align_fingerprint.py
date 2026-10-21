"""Staleness of the tracked passage alignments (#130).

These check the committed ``data/alignments`` against this branch's code and
version groups, through the same functions ``scripts.status`` reports with.
They need no vectors: what they can't see (vectors that changed since the last
run) ``scripts.align`` checks itself, refusing groups whose members lack current
vectors. ``tests/test_alignment.py`` checks that each file's members still have
the units it counts.
"""

from __future__ import annotations

from pathlib import Path

from scripts import status

ROOT = Path(__file__).resolve().parents[1]
NORMALIZED = ROOT / "data" / "normalized"
ALIGNMENTS = ROOT / "data" / "alignments"
RERUN = ("re-run `uv run --extra embed python -m scripts.align --embeddings-dir "
         "data/embeddings` (after scripts.embed) and commit data/alignments")


def test_committed_alignments_were_made_with_this_code() -> None:
    assert status.align_code_current(ALIGNMENTS), (
        f"the aligner's code changed since data/alignments was produced: {RERUN}"
    )


def test_every_version_group_is_aligned_or_recorded_as_skipped() -> None:
    missing = status.unaligned_groups(NORMALIZED, ALIGNMENTS)
    assert not missing, f"version groups with no alignment ({RERUN}): {missing[:10]}"


def test_recorded_skips_are_current_groups() -> None:
    gone = status.stale_skips(NORMALIZED, ALIGNMENTS)
    assert not gone, (
        f"_fingerprint.json skips groups that no longer need aligning ({RERUN}): {gone}"
    )
