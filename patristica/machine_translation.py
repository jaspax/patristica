"""Which works get a machine translation into English, and which already have one (#422, #423).

Machine translations (MT) are the works of the derived source ``mt-eng``
(``MACHINE_TRANSLATION_SOURCES``): English texts that ``scripts.machine_translate``
writes to ``data/raw/mt-eng/`` from an original in the corpus. Whether a work is
MT is decided by its ``source_id`` only, never by a ``Work`` field (a new field
would change every ingest stamp, #130). See ``docs/machine-translation.md``.

A work is a **candidate** for MT when

- it isn't English or MT, its licence is publishable, and it isn't Scripture;
- its version group (``patristica.versions``) has no English work, human or MT;
- it is the **original**: it has no ``translation_of``, or the work it names is
  not in the corpus (a translation whose original is lost or not collected).
  An ancient version of an original we have is a candidate only by a row in
  ``patristica/data/mt_exceptions.csv`` (``work_id,reason``): a version that
  diverges from its original in ways that matter to readers;
- of several originals in one language in the group (two editions), it is the
  preferred edition (``EDITION_PREFERENCE``).

An MT work is **redundant** once its group gains a human English work:
``scripts.export_library`` then leaves it out of the library.

This module is imported by the steps after normalize that need it (export,
status, the translator), never by ``scripts.normalize`` or ``scripts.align``, so
it isn't part of their code hashes.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from patristica.corpus import EXCLUDED_LICENSES
from patristica.sources import MACHINE_TRANSLATION_SOURCES
from patristica.versions import VersionGroups, derive_version_groups

ENGLISH = "eng"
EXCEPTIONS_PATH = Path(__file__).parent / "data" / "mt_exceptions.csv"

#: The edition translated when a group has several originals in one language,
#: best first: critical and digital editions before the OCR of Migne. A source
#: not listed ranks between the two.
EDITION_PREFERENCE: tuple[str, ...] = (
    "pta", "first1k", "perseus", "csel", "coptic-scriptorium", "dsc", "armenian",
    "ccmh-supr", "torot",
)
LAST_EDITIONS: tuple[str, ...] = ("ogpg", "oglt-pl")

#: Genres never machine-translated: every Scripture book has English versions,
#: and a Scripture source needs a versification scheme (``patristica.versification``).
SKIPPED_GENRES = frozenset({"scripture"})


class ExceptionsError(ValueError):
    """A malformed row in ``mt_exceptions.csv``."""


def is_machine_translation(work: Mapping[str, Any]) -> bool:
    """Whether *work* (a work record, as in ``_works.jsonl``) is a machine translation."""
    return work.get("source_id") in MACHINE_TRANSLATION_SOURCES


def load_exceptions(path: Path = EXCEPTIONS_PATH) -> dict[str, str]:
    """``work_id → reason`` of the derived versions to translate anyway."""
    out: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for n, row in enumerate(csv.DictReader(f), start=2):
            work_id, reason = (row.get("work_id") or "").strip(), (row.get("reason") or "").strip()
            if not work_id or not reason:
                raise ExceptionsError(f"{path}:{n}: work_id and reason are required")
            if work_id in out:
                raise ExceptionsError(f"{path}:{n}: {work_id} listed twice")
            out[work_id] = reason
    return out


def version_groups(works: Mapping[str, Mapping[str, Any]]) -> VersionGroups:
    """The version groups of *works* (``work_id → work record``)."""
    return derive_version_groups(
        {w: rec.get("translation_of") for w, rec in works.items()},
        external_ids={w: rec.get("external_ids") or [] for w, rec in works.items()})


def _group_members(work_id: str, groups: VersionGroups) -> tuple[str, ...]:
    gid = groups.group(work_id)
    return groups.members[gid] if gid else (work_id,)


def has_human_english(work_id: str, works: Mapping[str, Mapping[str, Any]],
                      groups: VersionGroups) -> bool:
    """Whether the version group of *work_id* has an English work that isn't MT."""
    return any(works[m]["language"] == ENGLISH and not is_machine_translation(works[m])
               for m in _group_members(work_id, groups))


def has_english(work_id: str, works: Mapping[str, Mapping[str, Any]],
                groups: VersionGroups) -> bool:
    """Whether the version group of *work_id* has any English work, human or MT."""
    return any(works[m]["language"] == ENGLISH for m in _group_members(work_id, groups))


def is_original(work: Mapping[str, Any], works: Mapping[str, Mapping[str, Any]]) -> bool:
    """Whether *work* is the oldest version the corpus has: no ``translation_of``,
    or one naming a work not in the corpus."""
    return work.get("translation_of") not in works


def edition_rank(source_id: str) -> int:
    if source_id in EDITION_PREFERENCE:
        return EDITION_PREFERENCE.index(source_id)
    if source_id in LAST_EDITIONS:
        return len(EDITION_PREFERENCE) + 1 + LAST_EDITIONS.index(source_id)
    return len(EDITION_PREFERENCE)


@dataclass(frozen=True)
class Candidate:
    """A work to machine-translate, with what a chooser needs to know about it."""

    work_id: str
    path: str  # its normalized path, which is also its MT's raw path under data/raw/mt-eng/
    title: str
    author: str | None
    author_ids: tuple[str, ...]
    language: str
    genre: str
    tradition: str | None
    source_id: str
    date_composed: int | None
    external_ids: tuple[str, ...]
    exception: str | None = None  # the reason, for a derived version listed in mt_exceptions.csv


def candidates(entries: Iterable[Mapping[str, Any]],
               exceptions: Mapping[str, str] | None = None) -> list[Candidate]:
    """The works of *entries* (``_works.jsonl`` lines) to machine-translate, sorted by id."""
    entries = list(entries)
    works = {e["work"]["work_id"]: e["work"] for e in entries}
    paths = {e["work"]["work_id"]: e["path"] for e in entries}
    exceptions = load_exceptions() if exceptions is None else exceptions
    groups = version_groups(works)
    out = []
    for work_id, w in sorted(works.items()):
        if (w["language"] == ENGLISH or is_machine_translation(w)
                or w["license"] in EXCLUDED_LICENSES or w["genre"] in SKIPPED_GENRES):
            continue
        exception = exceptions.get(work_id)
        if exception is not None:
            # A divergent version is translated in its own right, even where its
            # group has English (of the original): unless English made from it exists.
            if any(works[m]["language"] == ENGLISH and works[m].get("translation_of") == work_id
                   for m in _group_members(work_id, groups)):
                continue
        else:
            if has_english(work_id, works, groups) or not is_original(w, works):
                continue
            # Of several originals in this language, only the preferred edition.
            rivals = [m for m in _group_members(work_id, groups)
                      if works[m]["language"] == w["language"] and is_original(works[m], works)]
            best = min(rivals, key=lambda m: (edition_rank(works[m]["source_id"]), m))
            if best != work_id:
                continue
        out.append(Candidate(
            work_id=work_id, path=paths[work_id], title=w["title"], author=w.get("author"),
            author_ids=tuple(w.get("author_ids") or ()), language=w["language"],
            genre=w["genre"], tradition=w.get("tradition"), source_id=w["source_id"],
            date_composed=w.get("date_composed"),
            external_ids=tuple(w.get("external_ids") or ()), exception=exception))
    return out


def redundant(works: Mapping[str, Mapping[str, Any]],
              groups: VersionGroups | None = None,
              exceptions: Mapping[str, str] | None = None) -> set[str]:
    """The MT works of *works* made redundant by a human English work: one in
    the group, or for an MT of a listed divergent version, one made from it."""
    groups = version_groups(works) if groups is None else groups
    exceptions = load_exceptions() if exceptions is None else exceptions
    out = set()
    for w, rec in works.items():
        if not is_machine_translation(rec):
            continue
        source = rec.get("translation_of")
        if source in exceptions:
            human = any(works[m]["language"] == ENGLISH and not is_machine_translation(works[m])
                        and works[m].get("translation_of") == source
                        for m in _group_members(w, groups))
        else:
            human = has_human_english(w, works, groups)
        if human:
            out.add(w)
    return out
