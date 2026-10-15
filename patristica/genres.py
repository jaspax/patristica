"""Curated per-work genre decisions (#103).

Ingestors give each work a default genre, usually one per source.  Some works
need a different one: apocrypha filed under ``patristic``, a book canonical in
one tradition, a text with liturgical use.  Those decisions live in
``patristica/data/genre_overrides.csv`` (``work_id,genre,reason``), one row
per work with the reason for it, and ``scripts.normalize`` applies them, so
``data/normalized/_works.jsonl`` carries the final genre.  A row may restate
the ingestor's genre to record a deliberate decision (e.g. the Shepherd of
Hermas stays ``patristic``).

The rules (from #103): genre is decided per work, not per book.  A work
canonical in the tradition it belongs to (its language and edition) is
``scripture``, so one book can be ``scripture`` in one witness and
``apocrypha`` in another (Ge'ez vs Greek 1 Enoch); a work with any liturgical
use is ``liturgical``; other apocryphal gospels, acts,
apocalypses, testaments and Old Testament pseudepigrapha are ``apocrypha``.
Patristic works about apocrypha, hagiography and martyr acts stay
``patristic``.
"""

from __future__ import annotations

import csv
from functools import cache
from pathlib import Path
from typing import get_args

from patristica.models import Genre

OVERRIDES_PATH = Path(__file__).parent / "data" / "genre_overrides.csv"
GENRES: tuple[str, ...] = get_args(Genre)


class GenreOverrideError(ValueError):
    """The overrides file is malformed."""


def load_genre_overrides(path: Path = OVERRIDES_PATH) -> dict[str, str]:
    """Read *path* into ``{work_id: genre}``.

    Raises ``GenreOverrideError`` for an unknown genre, a missing reason or a
    work listed twice.
    """
    overrides: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            work_id = (row.get("work_id") or "").strip()
            genre = (row.get("genre") or "").strip()
            if not work_id:
                raise GenreOverrideError(f"{path}:{line}: empty work_id")
            if genre not in GENRES:
                raise GenreOverrideError(f"{path}:{line}: {work_id}: unknown genre {genre!r}")
            if not (row.get("reason") or "").strip():
                raise GenreOverrideError(f"{path}:{line}: {work_id}: no reason given")
            if work_id in overrides:
                raise GenreOverrideError(f"{path}:{line}: {work_id} is listed twice")
            overrides[work_id] = genre
    return overrides


@cache
def _overrides() -> dict[str, str]:
    return load_genre_overrides()


def override_for(work_id: str) -> str | None:
    """The curated genre for *work_id*, or None if the file doesn't list it."""
    return _overrides().get(work_id)


def genre_for(work: dict) -> str:
    """The curated genre for a raw work record, or its own genre."""
    return _overrides().get(work.get("work_id", ""), work.get("genre", ""))


def apply_genre_override(work: dict) -> dict:
    """Return *work* with its curated genre (a copy if it changes)."""
    genre = genre_for(work)
    if genre == work.get("genre"):
        return work
    return {**work, "genre": genre}
