"""The passage group of a chunk: the key search folds versions by (#180).

Search shows each passage once, with its other versions attached
(IMPLEMENTATION_PLAN.md §2.4). Two chunks are versions of one passage when
they have the same group key. Today only Scripture has groups, from
``chunks.translation_group_id`` (``scripts.link_translations``); every other
chunk is its own group. When passage alignment (#179) gives other works
groups, only this expression changes.

Group ids are refs (``Gen.1.1``) and chunk ids always contain ``#``, so a
chunk's own id never collides with a group id.
"""

from __future__ import annotations


def passage_group(chunks: str = "c") -> str:
    """SQL for the passage group of the ``chunks`` row aliased *chunks*."""
    return f"coalesce({chunks}.translation_group_id, {chunks}.chunk_id)"
