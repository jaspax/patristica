"""Phrase search over the keyword index (#86; ``patristica.keyword``).

A chunk matches when every phrase occurs in its folded text as whole words
(``text_folded LIKE '% phrase %'``, served by the ``pg_trgm`` GIN index).
Matches have no similarity score, so they are ordered by:

1. Scripture first (a quote is most often from Scripture);
2. then the earliest date: the chunk's date range, else its work's, undated last;
3. then work and position in the work, so paging is stable.

The filters are those of vector search (``api.search.Filters``), over the
same columns, here taken from the chunk and its work.
"""

from __future__ import annotations

from typing import Any

import psycopg

from patristica.keyword import phrase_pattern

#: A phrase of very common words can match a large part of the corpus.
TIMEOUT_MS = 5000


class PhraseTooBroad(RuntimeError):
    """The phrase matched too much to search in time."""


_SQL = """
SELECT chunk_id, count(*) OVER () FROM (
    SELECT c.chunk_id, c.work_id, c.chunk_index, c.language, c.out_of_period,
           w.genre, w.source_id, w.author_ids,
           coalesce(c.date_range, w.date_range) AS date_range
    FROM chunks c JOIN works w ON w.work_id = c.work_id
    WHERE {phrases}
) k
WHERE {where}
ORDER BY genre = 'scripture' DESC, lower(date_range) NULLS LAST, work_id, chunk_index
OFFSET %(offset)s LIMIT %(limit)s
"""


def phrase_search(conn: psycopg.Connection, phrases: list[str], where: str,
                  params: dict[str, Any], limit: int, offset: int = 0,
                  timeout_ms: int = TIMEOUT_MS) -> tuple[list[str], int | None]:
    """(chunk ids of one page of matches, total matches) for chunks containing every phrase.

    *where* and *params* are ``Filters.sql()``. The total is None when the
    page is past the end. Raises ``patristica.keyword.PhraseError`` for a
    phrase too short to search and ``PhraseTooBroad`` when it times out.
    """
    if not phrases:
        raise ValueError("no phrases")
    patterns = {f"phrase{i}": phrase_pattern(p) for i, p in enumerate(phrases)}
    sql = _SQL.format(where=where, phrases=" AND ".join(
        f"c.text_folded LIKE %({name})s" for name in patterns))
    with conn.transaction():
        conn.execute("SELECT set_config('statement_timeout', %s, true), "
                     "set_config('jit', 'off', true)", (str(timeout_ms),))
        try:
            # Unprepared, so the planner sees the pattern and uses the trigram index.
            rows = conn.execute(sql, {**params, **patterns, "limit": limit, "offset": offset},
                                prepare=False).fetchall()
        except psycopg.errors.QueryCanceled as exc:
            raise PhraseTooBroad("this phrase is too common to search: add more words") from exc
    return [r[0] for r in rows], (rows[0][1] if rows else None)
