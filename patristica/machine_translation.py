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

A work listed in ``patristica/data/mt_blocked.csv`` (``work_id,issue,reason``)
is never a candidate: its text is too damaged to translate (severe OCR or source
problems) until the GitHub issue named fixes it. Agents add exception and
blocked rows themselves, and remove a blocked row once its issue is closed.

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
BLOCKED_PATH = Path(__file__).parent / "data" / "mt_blocked.csv"

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
    """A malformed row in ``mt_exceptions.csv`` or ``mt_blocked.csv``."""


def is_machine_translation(work: Mapping[str, Any]) -> bool:
    """Whether *work* (a work record, as in ``_works.jsonl``) is a machine translation."""
    return work.get("source_id") in MACHINE_TRANSLATION_SOURCES


def _rows(path: Path, columns: tuple[str, ...]) -> list[tuple[int, dict[str, str]]]:
    """The rows of a curated CSV keyed by ``work_id``: every column required,
    no work twice, sorted by ``work_id``."""
    out: list[tuple[int, dict[str, str]]] = []
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if tuple(reader.fieldnames or ()) != columns:
            raise ExceptionsError(f"{path}: columns must be {','.join(columns)}")
        for n, row in enumerate(reader, start=2):
            row = {k: (row.get(k) or "").strip() for k in columns}
            if not all(row.values()):
                raise ExceptionsError(f"{path}:{n}: {', '.join(columns)} are all required")
            if out and row["work_id"] <= out[-1][1]["work_id"]:
                raise ExceptionsError(f"{path}:{n}: {row['work_id']} is a repeat or out of "
                                      "order (keep the rows sorted by work_id)")
            out.append((n, row))
    return out


def load_exceptions(path: Path = EXCEPTIONS_PATH) -> dict[str, str]:
    """``work_id → reason`` of the derived versions to translate anyway."""
    return {row["work_id"]: row["reason"] for _, row in _rows(path, ("work_id", "reason"))}


@dataclass(frozen=True)
class Blocked:
    issue: int  # the GitHub issue that tracks the fix
    reason: str


def load_blocked(path: Path = BLOCKED_PATH) -> dict[str, Blocked]:
    """``work_id → Blocked`` of the works too damaged to translate for now."""
    out = {}
    for n, row in _rows(path, ("work_id", "issue", "reason")):
        issue = row["issue"].lstrip("#")
        if not issue.isdigit() or int(issue) < 1:
            raise ExceptionsError(f"{path}:{n}: issue must be a GitHub issue number, "
                                  f"not {row['issue']!r}")
        out[row["work_id"]] = Blocked(int(issue), row["reason"])
    return out


def unknown_works(work_ids: Iterable[str], works: Mapping[str, Any]) -> list[str]:
    """The ids of *work_ids* not in *works*: curated rows naming no work of the corpus."""
    return sorted(w for w in work_ids if w not in works)


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
class Version:
    """Another non-English member of a work's version group."""

    work_id: str
    path: str
    language: str
    source_id: str
    translation_of: str | None
    kind: str  # "derived" (it has a translation_of) or "edition" (another original)


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
    #: The other non-English members of its version group, by work id.
    versions: tuple[Version, ...] = ()


def other_versions(work_id: str, works: Mapping[str, Mapping[str, Any]],
                   paths: Mapping[str, str], groups: VersionGroups) -> tuple[Version, ...]:
    """The non-English members of *work_id*'s version group other than itself."""
    return tuple(
        Version(m, paths[m], works[m]["language"], works[m]["source_id"],
                works[m].get("translation_of"),
                "derived" if works[m].get("translation_of") else "edition")
        for m in _group_members(work_id, groups)
        if m != work_id and works[m]["language"] != ENGLISH)


def _translatable(w: Mapping[str, Any]) -> bool:
    return not (w["language"] == ENGLISH or is_machine_translation(w)
                or w["license"] in EXCLUDED_LICENSES or w["genre"] in SKIPPED_GENRES)


def candidates(entries: Iterable[Mapping[str, Any]],
               exceptions: Mapping[str, str] | None = None,
               blocked: Mapping[str, Blocked] | None = None) -> list[Candidate]:
    """The works of *entries* (``_works.jsonl`` lines) to machine-translate, sorted by id."""
    entries = list(entries)
    works = {e["work"]["work_id"]: e["work"] for e in entries}
    paths = {e["work"]["work_id"]: e["path"] for e in entries}
    exceptions = load_exceptions() if exceptions is None else exceptions
    blocked = load_blocked() if blocked is None else blocked
    groups = version_groups(works)
    out = []
    for work_id, w in sorted(works.items()):
        if not _translatable(w) or work_id in blocked:
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
            external_ids=tuple(w.get("external_ids") or ()), exception=exception,
            versions=other_versions(work_id, works, paths, groups)))
    return out


def versions_to_review(entries: Iterable[Mapping[str, Any]],
                       exceptions: Mapping[str, str] | None = None) -> list[Version]:
    """Derived non-English versions with no exception row, in groups with no human English.

    Not translated by default (their original is), these are the versions
    whose divergence from the original an agent should weigh for an
    ``mt_exceptions.csv`` row.
    """
    entries = list(entries)
    works = {e["work"]["work_id"]: e["work"] for e in entries}
    paths = {e["work"]["work_id"]: e["path"] for e in entries}
    exceptions = load_exceptions() if exceptions is None else exceptions
    groups = version_groups(works)
    return [Version(w, paths[w], rec["language"], rec["source_id"], rec["translation_of"],
                    "derived")
            for w, rec in sorted(works.items())
            if _translatable(rec) and not is_original(rec, works) and w not in exceptions
            and not has_human_english(w, works, groups)]


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
