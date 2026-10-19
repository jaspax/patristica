"""The passage group of a chunk: the key search folds versions by (#180).

Search shows each passage once, with its other versions attached
(IMPLEMENTATION_PLAN.md §2.4). Two chunks are versions of one passage when
they have the same group key:

1. the chunk's passage alignment group (``passage_groups``, #179), which
   covers every work with another version, Scripture included;
2. else its Scripture verse group (``chunks.translation_group_id``), for
   verses the alignment leaves out (no vector, or a flagged span);
3. else the chunk itself.

Passage groups are ``{version group}@{n}``, Scripture verse groups are refs
(``Gen.1.1``), and chunk ids always contain ``#``, which neither of the
others does, so the three kinds never collide. The lookup is a primary-key
probe per candidate row, so the search SQL around it stays unchanged.
"""

from __future__ import annotations


def passage_group(chunks: str = "c") -> str:
    """SQL for the passage group of the ``chunks`` row aliased *chunks*."""
    return ("coalesce((SELECT pg.group_id FROM passage_groups pg "
            f"WHERE pg.chunk_id = {chunks}.chunk_id), "
            f"{chunks}.translation_group_id, {chunks}.chunk_id)")
