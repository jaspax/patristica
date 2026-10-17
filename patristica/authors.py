"""The author index (#82): canonical author ids, aliases and dates.

``Work.author`` is the source's own free-text author string (``Augustinus``,
``Augustine of Hippo``, ``Cyril of Jerusalem; Apollinaris of Laodicea``).  This
module maps it to canonical author ids, so one person is one author across
sources.  The data lives in two reviewable CSV files:

``patristica/data/authors.csv``
    One row per person: ``author_id`` (a stable slug, used in URLs), ``name``
    (English display name), ``aliases`` (every source spelling, ``|``-separated),
    ``birth``, ``death`` and ``floruit`` (see *Dates* below), ``tradition``,
    ``external_ids`` (TLG / PHI / stoa / PTA author ids, ``|``-separated),
    ``pseudo_of`` (for a pseudonymous author: the id of the real author whose
    name the works carry) and a free ``note``.

``patristica/data/author_strings.csv``
    Source strings that are not a simple alias: anonymous works and work titles
    in the author field (resolve to no author), collective authors (councils,
    "the elders"), modern editors named as author, ambiguous bare names, and
    multi-person strings that need explicit ids.  Columns: ``source_string``,
    ``author_ids`` (``|``-separated, may be empty) and ``reason`` (required).

Matching is on ``patristica.textfold.fold``-ed text, so case, accents,
punctuation and the Latin u/v, i/j spellings do not matter.  A string that is
in neither table is split on ``;`` and each part resolved on its own
(``"John of Scythopolis; Maximus the Confessor"``); filler parts such as
``anonymous`` or ``others`` are dropped.  Anything still unknown raises
``UnknownAuthorError``: a new source must add its spellings to the index.

Dates
-----
``birth``, ``death`` and ``floruit`` hold a year or a range, with the certainty
written into the value:

- ``354`` — established; ``c. 347`` — approximate; ``350?`` — uncertain
- ``340/345`` — a range (earliest/latest); ``c. 360/370`` — an approximate range
- negative years are BCE (``c. -20``)

``floruit`` is the span of known activity, recorded when it is more useful
than (or there is no) birth date.

The period rule (``patristica.period``) uses ``Author.period_birth_year``: the
earliest possible birth year when a birth date is recorded; otherwise, when
the floruit or death year is before ``AUTHOR_BORN_BEFORE``, that year (the
person was certainly born before it); otherwise ``None`` (unknown, so the
composition date decides).
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import get_args

from patristica.models import DateConfidence, Tradition
from patristica.period import AUTHOR_BORN_BEFORE
from patristica.textfold import fold

DATA_DIR = Path(__file__).parent / "data"
AUTHORS_PATH = DATA_DIR / "authors.csv"
AUTHOR_STRINGS_PATH = DATA_DIR / "author_strings.csv"

#: Allowed ``tradition`` values: the corpus traditions plus non-Christian
#: Jewish authors (Philo, Josephus) whose works are in the corpus.
AUTHOR_TRADITIONS: tuple[str, ...] = (*get_args(Tradition), "jewish")

_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_DATE_RE = re.compile(r"^(c\. )?(-?\d{1,4})(?:/(-?\d{1,4}))?(\?)?$")

#: Parts of a list-style author string that name no one.
FILLER_PARTS = frozenset(
    fold(s) for s in ("anonymous", "anonymus", "others", "alii", "et alii", "et al.", "various")
)
_TRAILING_FILLER_RE = re.compile(r"\s+(?:et al\.?|et alii|et socii|and others)\s*$", re.IGNORECASE)


class AuthorIndexError(ValueError):
    """The author index files are malformed or inconsistent."""


class UnknownAuthorError(LookupError):
    """An author string matches nothing in the author index."""


@dataclass(frozen=True)
class AuthorDate:
    """A year or year range with its certainty."""

    low: int
    high: int
    confidence: DateConfidence

    @property
    def year(self) -> int:
        """Single best year: the midpoint of a range."""
        return (self.low + self.high) // 2

    def to_json(self) -> dict[str, int | str]:
        return {"low": self.low, "high": self.high, "confidence": self.confidence}


def parse_author_date(value: str) -> AuthorDate | None:
    """Parse a ``birth`` / ``death`` / ``floruit`` cell (see the module docstring)."""
    value = value.strip()
    if not value:
        return None
    m = _DATE_RE.match(value)
    if not m:
        raise AuthorIndexError(f"unparseable date {value!r}")
    approx, low_s, high_s, uncertain = m.groups()
    low = int(low_s)
    high = int(high_s) if high_s is not None else low
    if high < low:
        raise AuthorIndexError(f"date range {value!r} is inverted")
    confidence: DateConfidence = (
        "uncertain" if uncertain else "approximate" if approx else "established"
    )
    return AuthorDate(low, high, confidence)


@dataclass(frozen=True)
class Author:
    author_id: str
    name: str
    aliases: tuple[str, ...]
    birth: AuthorDate | None
    death: AuthorDate | None
    floruit: AuthorDate | None
    tradition: str | None
    external_ids: tuple[str, ...]
    pseudo_of: str | None
    note: str | None

    @property
    def period_birth_year(self) -> int | None:
        """Birth year to feed ``work_in_period`` (see the module docstring)."""
        if self.birth is not None:
            if self.birth.confidence == "uncertain" and self.birth.low >= AUTHOR_BORN_BEFORE:
                return None  # exclusion needs positive evidence
            return self.birth.low
        later = [d.high for d in (self.floruit, self.death) if d is not None]
        if later and min(later) < AUTHOR_BORN_BEFORE:
            return min(later)
        return None

    def to_json(self) -> dict:
        """The record exported to the library's ``authors.json``."""
        return {
            "id": self.author_id,
            "name": self.name,
            "aliases": list(self.aliases),
            "birth": self.birth.to_json() if self.birth else None,
            "death": self.death.to_json() if self.death else None,
            "floruit": self.floruit.to_json() if self.floruit else None,
            "tradition": self.tradition,
            "external_ids": list(self.external_ids),
            "pseudo_of": self.pseudo_of,
        }


def _split(cell: str | None) -> tuple[str, ...]:
    return tuple(p.strip() for p in (cell or "").split("|") if p.strip())


def _rows(path: Path):
    with path.open(encoding="utf-8", newline="") as f:
        lines = (line for line in f if not line.startswith("#"))
        yield from csv.DictReader(lines)


def load_authors(path: Path = AUTHORS_PATH) -> dict[str, Author]:
    """Read ``authors.csv`` into ``{author_id: Author}``, checking each row."""
    authors: dict[str, Author] = {}
    for row in _rows(path):
        aid = (row.get("author_id") or "").strip()
        where = f"{path.name}: {aid or '<empty id>'}"
        if not _SLUG_RE.match(aid):
            raise AuthorIndexError(f"{where}: author_id must be a lowercase slug")
        if aid in authors:
            raise AuthorIndexError(f"{where}: author_id is listed twice")
        name = (row.get("name") or "").strip()
        if not name:
            raise AuthorIndexError(f"{where}: no name")
        tradition = (row.get("tradition") or "").strip() or None
        if tradition is not None and tradition not in AUTHOR_TRADITIONS:
            raise AuthorIndexError(f"{where}: unknown tradition {tradition!r}")
        try:
            birth = parse_author_date(row.get("birth") or "")
            death = parse_author_date(row.get("death") or "")
            floruit = parse_author_date(row.get("floruit") or "")
        except AuthorIndexError as exc:
            raise AuthorIndexError(f"{where}: {exc}") from exc
        if birth and death and death.high < birth.low:
            raise AuthorIndexError(f"{where}: death before birth")
        authors[aid] = Author(
            author_id=aid,
            name=name,
            aliases=_split(row.get("aliases")),
            birth=birth,
            death=death,
            floruit=floruit,
            tradition=tradition,
            external_ids=_split(row.get("external_ids")),
            pseudo_of=(row.get("pseudo_of") or "").strip() or None,
            note=(row.get("note") or "").strip() or None,
        )
    for a in authors.values():
        if a.pseudo_of is not None and a.pseudo_of not in authors:
            raise AuthorIndexError(f"{path.name}: {a.author_id}: pseudo_of {a.pseudo_of!r} is unknown")
        if a.pseudo_of == a.author_id:
            raise AuthorIndexError(f"{path.name}: {a.author_id}: pseudo_of itself")
    return authors


def load_author_strings(path: Path = AUTHOR_STRINGS_PATH) -> dict[str, tuple[str, tuple[str, ...]]]:
    """Read ``author_strings.csv`` into ``{folded string: (string, author_ids)}``."""
    strings: dict[str, tuple[str, tuple[str, ...]]] = {}
    for row in _rows(path):
        s = (row.get("source_string") or "").strip()
        if not s:
            raise AuthorIndexError(f"{path.name}: empty source_string")
        if not (row.get("reason") or "").strip():
            raise AuthorIndexError(f"{path.name}: {s!r}: no reason given")
        key = fold(s)
        if key in strings:
            raise AuthorIndexError(f"{path.name}: {s!r} collides with {strings[key][0]!r}")
        strings[key] = (s, _split(row.get("author_ids")))
    return strings


@dataclass(frozen=True)
class AuthorIndex:
    authors: dict[str, Author]
    #: folded alias or name → author_id
    aliases: dict[str, str]
    #: folded source string → (source string, author_ids)
    strings: dict[str, tuple[str, tuple[str, ...]]]

    def _lookup(self, part: str) -> tuple[str, ...] | None:
        key = fold(part)
        if key in self.strings:
            return self.strings[key][1]
        if key in self.aliases:
            return (self.aliases[key],)
        return None

    def resolve(self, source: str | None) -> list[str]:
        """Canonical author ids for a ``Work.author`` string (``[]`` if anonymous)."""
        if source is None or not source.strip():
            return []
        found = self._lookup(source)
        if found is None:
            ids: list[str] = []
            for raw_part in source.split(";"):
                part = _TRAILING_FILLER_RE.sub("", raw_part).strip()
                if not part or fold(part) in FILLER_PARTS:
                    continue
                part_ids = self._lookup(part)
                if part_ids is None:
                    raise UnknownAuthorError(
                        f"unknown author {part!r} (in {source!r}): add it to "
                        f"{AUTHORS_PATH.name} (aliases) or {AUTHOR_STRINGS_PATH.name}"
                    )
                ids.extend(part_ids)
            found = tuple(ids)
        return list(dict.fromkeys(found))

    def birth_year(self, author_ids: list[str]) -> int | None:
        """Period birth year of a work's authors: the latest, if all are known.

        A work by several authors is judged by its youngest author; if any
        author's birth is unknown (or the work is anonymous), ``None``.
        """
        years = [self.authors[a].period_birth_year for a in author_ids]
        if not years or any(y is None for y in years):
            return None
        return max(y for y in years if y is not None)


def build_index(
    authors_path: Path = AUTHORS_PATH, strings_path: Path = AUTHOR_STRINGS_PATH
) -> AuthorIndex:
    """Load and cross-check both files.

    Raises ``AuthorIndexError`` if an alias (or name) belongs to two authors,
    an alias is also listed in ``author_strings.csv``, or a string there names
    an unknown author id.
    """
    authors = load_authors(authors_path)
    strings = load_author_strings(strings_path)
    aliases: dict[str, str] = {}
    for a in authors.values():
        for alias in dict.fromkeys((a.name, *a.aliases)):
            key = fold(alias)
            other = aliases.get(key)
            if other is not None and other != a.author_id:
                raise AuthorIndexError(f"alias {alias!r} belongs to both {other} and {a.author_id}")
            aliases[key] = a.author_id
    for key, (s, ids) in strings.items():
        if key in aliases:
            raise AuthorIndexError(
                f"{strings_path.name}: {s!r} is also an alias of {aliases[key]}"
            )
        unknown = [i for i in ids if i not in authors]
        if unknown:
            raise AuthorIndexError(f"{strings_path.name}: {s!r}: unknown author ids {unknown}")
    return AuthorIndex(authors, aliases, strings)


@cache
def author_index() -> AuthorIndex:
    """The repository's author index, loaded once."""
    return build_index()


def resolve_author(source: str | None) -> list[str]:
    """Canonical author ids for *source* (a ``Work.author`` string).

    Anonymous works (``None``, ``Anonymus``, a work title in the author field)
    give ``[]``.  Raises ``UnknownAuthorError`` for a name not in the index.
    """
    return author_index().resolve(source)
