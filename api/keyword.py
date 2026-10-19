"""Phrase search over the keyword index (#86; ``patristica.keyword``).

A chunk matches when every phrase occurs in its folded text as whole words
(``text_folded LIKE '% phrase %'``, served by the ``pg_trgm`` GIN index).
Matches have no similarity score of their own. With a ranking vector (the
free text of a query, #143) they are ordered by their best vector's
distance to it, matches without a vector last. Without one, by:

1. Scripture first (a quote is most often from Scripture);
2. then the earliest date: the chunk's date range, else its work's, undated last;
3. then work and position in the work, so paging is stable.

The filters are those of vector search (``api.search.Filters``), over the
same columns, here taken from the chunk and its work. After filtering, the
matches fold by passage group (``api.passages``, #180): each group is one
result, led by its first match in this order.
"""

from __future__ import annotations

from typing import Any

import psycopg

from api.passages import passage_group
from patristica.keyword import phrase_pattern

#: A phrase of very common words can match a large part of the corpus.
TIMEOUT_MS = 5000


#: A chunk and its distance to the ranking vector (None without one).
Hit = tuple[str, float | None]
#: One page of folded matches: (lead chunk, distance, the other versions found).
Page = list[tuple[str, float | None, list[Hit]]]


class PhraseTooBroad(RuntimeError):
    """The phrase matched too much to search in time."""


_MATCHES = """
    SELECT k.* FROM (
        SELECT c.chunk_id, c.work_id, c.chunk_index, c.language, c.out_of_period,
               w.genre, w.source_id, w.author_ids,
               coalesce(c.date_range, w.date_range) AS date_range,
               {group} AS grp
        FROM chunks c JOIN works w ON w.work_id = c.work_id
        WHERE {phrases}
    ) k
    WHERE {where}
"""

#: The order of matches without a ranking vector, and with one.
_ORDER = "genre = 'scripture' DESC, lower(date_range) NULLS LAST, work_id, chunk_index"
_RANKED_ORDER = "distance NULLS LAST, chunk_id"

# Each match's best (text or translation) vector of the query's model.
_DISTANCE = """
    LEFT JOIN LATERAL (
        SELECT min(v.embedding <=> %(q)s::halfvec) AS distance FROM chunk_vectors v
        WHERE v.chunk_id = m.chunk_id AND v.model_id = {model_id}
    ) d ON true
"""

# The matches in order (pos), folded by passage group (#180): the first match
# of each group leads (n = 1), and the page is cut from the leads. The total
# counts leads; each lead lists the other matches of its group, in order.
_SQL = """
WITH o AS (
    SELECT m.chunk_id, m.grp, {distance} AS distance,
           row_number() OVER (ORDER BY {order}) AS pos,
           row_number() OVER (PARTITION BY m.grp ORDER BY {order}) AS n
    FROM ({matches}) m {join}
), page AS (
    SELECT chunk_id, grp, distance, pos, count(*) OVER () AS total FROM o
    WHERE n = 1 ORDER BY pos OFFSET %(offset)s LIMIT %(limit)s
), versions AS (
    SELECT grp, json_agg(json_build_array(chunk_id, distance) ORDER BY pos) AS versions
    FROM o WHERE n > 1 AND grp IN (SELECT grp FROM page) GROUP BY grp
)
SELECT p.chunk_id, p.total, p.distance, coalesce(v.versions, '[]')
FROM page p LEFT JOIN versions v ON v.grp = p.grp
ORDER BY p.pos
"""


def phrase_search(conn: psycopg.Connection, phrases: list[str], where: str,
                  params: dict[str, Any], limit: int, offset: int = 0,
                  rank: tuple[str, int] | None = None,
                  timeout_ms: int = TIMEOUT_MS) -> tuple[Page, int | None]:
    """One page of the passages containing every phrase, and the number of them.

    Matches are folded by passage group (``api.passages``, #180): the first
    match of a group in the order leads, and the others are its versions.
    Returns ``([(chunk_id, distance, [(chunk_id, distance), ...]), ...], total)``,
    the total counting folded results. *where* and *params*
    are ``Filters.sql()``. *rank* is ``(query vector literal, model_id)``
    to order the matches by distance to; without it the distance is None.
    The total is None when the page is past the end. Raises
    ``patristica.keyword.PhraseError`` for a phrase too short to search and
    ``PhraseTooBroad`` when it times out.
    """
    if not phrases:
        raise ValueError("no phrases")
    patterns = {f"phrase{i}": phrase_pattern(p) for i, p in enumerate(phrases)}
    matches = _MATCHES.format(where=where, group=passage_group("c"), phrases=" AND ".join(
        f"c.text_folded LIKE %({name})s" for name in patterns))
    if rank is None:
        sql = _SQL.format(matches=matches, distance="NULL::float8", order=_ORDER, join="")
    else:
        sql = _SQL.format(matches=matches, distance="d.distance", order=_RANKED_ORDER,
                          join=_DISTANCE.format(model_id=int(rank[1])))
        patterns["q"] = rank[0]
    with conn.transaction():
        conn.execute("SELECT set_config('statement_timeout', %s, true), "
                     "set_config('jit', 'off', true)", (str(timeout_ms),))
        try:
            # Unprepared, so the planner sees the pattern and uses the trigram index.
            rows = conn.execute(sql, {**params, **patterns, "limit": limit, "offset": offset},
                                prepare=False).fetchall()
        except psycopg.errors.QueryCanceled as exc:
            raise PhraseTooBroad("This phrase is too common to search: add more words.") from exc
    page = [(r[0], r[2], [(cid, dist) for cid, dist in r[3]]) for r in rows]
    return page, (rows[0][1] if rows else None)
