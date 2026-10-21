"""Staleness of the tracked passage alignments (#130).

These check the committed ``data/alignments`` against this branch's code,
version groups and versification. They need no vectors: what they can't see
(vectors that changed since the last run) ``scripts.align`` checks itself,
refusing groups whose members lack current vectors. ``tests/test_alignment.py``
checks that each file's members still have the units it counts.
"""

from __future__ import annotations

from pathlib import Path

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


def test_every_version_group_is_aligned_from_its_current_members() -> None:
    """New groups, added or removed members, and versification changes that move a
    Scripture book's refs all make that group stale."""
    problems = align.check_groups(NORMALIZED, ALIGNMENTS)
    assert not problems, f"stale alignments ({RERUN}): " + ", ".join(
        f"{g} ({why})" for g, why in list(problems.items())[:10])
