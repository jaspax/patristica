"""
The collection period: the first thousand years of Christianity.

Interpreted broadly.  A text is in scope if

- its author was born before ``AUTHOR_BORN_BEFORE`` (1025), or
- the author's birth year is unknown or not recorded (anonymous texts,
  pseudepigrapha, collective works), and it was composed by ``COMPOSED_BY``
  (1050) — roughly the working life of someone born around 1000.

Whole works are excluded only on positive evidence: a date range that starts
after ``COMPOSED_BY``, or an author known to be born after
``AUTHOR_BORN_BEFORE``.  Author birth years come from the author index
(``patristica.authors``, #82).  Undated works are included.  Works that straddle the
boundary (hybrid texts such as the Typikon, CANTUS manuscripts, mixed Migne
volumes) are kept, and each chunk records whether its own date falls after the
period in ``Chunk.out_of_period``, so search can filter at query time.

This is the single definition of the period; ingestors and pipeline scripts
must use these helpers rather than hard-coding years.
"""

from __future__ import annotations

#: Texts by authors born before this year are in scope regardless of composition date.
AUTHOR_BORN_BEFORE = 1025

#: Texts without a recorded author birth year are in scope if composed by this year.
COMPOSED_BY = 1050


def work_in_period(
    date_range: tuple[int, int] | list[int] | None,
    author_birth_year: int | None = None,
) -> bool:
    """Return True if a whole work belongs in the collection.

    *author_birth_year*, when known, decides on its own.  Otherwise the work is
    excluded only if its composition date range starts after ``COMPOSED_BY``.
    """
    if author_birth_year is not None:
        return author_birth_year < AUTHOR_BORN_BEFORE
    return date_range is None or date_range[0] <= COMPOSED_BY


def is_out_of_period(
    date_composed: int | None,
    date_range: tuple[int, int] | list[int] | None,
    author_birth_year: int | None = None,
) -> bool:
    """Return True if a kept chunk's own date falls after the period.

    Used for ``Chunk.out_of_period`` on works that are kept as a whole but
    whose (estimated) composition date lies past ``COMPOSED_BY``.
    *author_birth_year*, when known, decides on its own, as in
    ``work_in_period``: a late work by an author born before
    ``AUTHOR_BORN_BEFORE`` is in period.
    """
    if author_birth_year is not None:
        return author_birth_year >= AUTHOR_BORN_BEFORE
    if date_composed is not None and date_composed > COMPOSED_BY:
        return True
    return date_range is not None and date_range[0] > COMPOSED_BY
