"""Curated ``Work.translation_of`` for the ancient versions (#153).

``translation_of`` names the work a version was translated from.  Ingestors set
it for the English translations of #11/#150; the links of every other version
are curated here and applied by ``scripts.normalize``, which writes them to
``data/normalized/_works.jsonl`` (as ``patristica.genres`` does for genre).
They are not set in ingestor code: every Scripture ingestor imports
``scripts/ingest/_scripture_meta.py``, so a table there would invalidate their
ingest stamps (#130) and rewrite their raw files.

Two curated sources:

1. **Scripture**, per source and book: ``patristica/data/scripture_translation_of.csv``
   (``source_id,books,translation_of,note``).  ``books`` is ``*``, ``ot``
   (every book not in ``NT_BOOKS``), ``nt``, or ``|``-separated book keys (the
   local id of a ``{source}/{book}`` work); an explicit book beats ``ot``/``nt``,
   which beat ``*``.  ``translation_of`` is

   - a source id: the same book in that source (``oshb`` → ``oshb/gen``),
   - a work id (contains ``/``): exactly that work (``pta-lxx/danthdt``),
   - ``original``: the work is in the language the book was written in, or is
     the earliest form of it in the corpus (no ``translation_of``),
   - ``unlinked``: a translation whose source is not in the corpus, or only
     inside a work that holds more than this book (no ``translation_of``).

   Each version points at **one designated edition** of its source text, not
   its exact Vorlage: Hebrew → ``oshb``, Greek Old Testament → ``pta-lxx``,
   Greek New Testament → ``sblgnt`` (``DATA_COLLECTION_PLAN.md`` explains the
   choice).  A secondary source (the Greek additions of Vulgate Esther, the
   LXX influence on the Peshitta) is recorded in the note, since
   ``translation_of`` is one work id.

2. **Everything else**: the ``translation_of`` rows of
   ``patristica/data/version_links.csv`` (``work_id`` translates
   ``other_work_id``), which also join the two works' version group
   (``patristica.versions``).  A Scripture-source work is never listed there.

Links may chain (Coptic Genesis → LXX Genesis → Hebrew Genesis), so a work's
translation history is recorded however many steps it took; there are no
cycles (``tests/test_translation_of.py``).

This module reads the CSV files itself rather than importing
``patristica.versions`` (which imports ``patristica.versification``): it is in
``scripts.normalize``'s code hash, and edits to the versification tables must
not make every work look stale.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import cache
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
SCRIPTURE_PATH = DATA_DIR / "scripture_translation_of.csv"
VERSION_LINKS_PATH = DATA_DIR / "version_links.csv"

ORIGINAL = "original"
UNLINKED = "unlinked"

#: New Testament book keys (local ids of Scripture works); every other book is ``ot``.
NT_BOOKS: frozenset[str] = frozenset({
    "matt", "mark", "luke", "john", "acts", "rom", "1cor", "2cor", "gal", "eph",
    "phil", "col", "1thess", "2thess", "1tim", "2tim", "titus", "phlm", "heb",
    "jas", "1pet", "2pet", "1john", "2john", "3john", "jude", "rev",
})
_GROUP_KEYS = ("*", "ot", "nt")


class TranslationOfError(ValueError):
    """A curated table is malformed, or curation contradicts an ingestor's link."""


@dataclass(frozen=True)
class ScriptureRule:
    source_id: str
    books: str  # "*", "ot", "nt" or one book key
    translation_of: str  # a source id, a work id, ORIGINAL or UNLINKED
    note: str

    def target(self, book: str) -> str | None:
        """The work id this rule names for *book* (None for ORIGINAL/UNLINKED)."""
        if self.translation_of in (ORIGINAL, UNLINKED):
            return None
        if "/" in self.translation_of:
            return self.translation_of
        return f"{self.translation_of}/{book}"


def load_scripture_rules(path: Path = SCRIPTURE_PATH) -> dict[tuple[str, str], ScriptureRule]:
    """Read the Scripture table into ``{(source_id, books key): rule}``.

    Raises ``TranslationOfError`` for an empty field, a missing note, or a
    source and book (or ``*``/``ot``/``nt``) listed twice.
    """
    rules: dict[tuple[str, str], ScriptureRule] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            source = (row.get("source_id") or "").strip()
            books = (row.get("books") or "").strip()
            target = (row.get("translation_of") or "").strip()
            note = (row.get("note") or "").strip()
            where = f"{path}:{line}"
            if not source or not books or not target:
                raise TranslationOfError(f"{where}: empty source_id, books or translation_of")
            if not note:
                raise TranslationOfError(f"{where}: {source} {books}: no note given")
            keys = [books] if books in _GROUP_KEYS else books.split("|")
            for key in keys:
                key = key.strip()
                if not key or "/" in key:
                    raise TranslationOfError(f"{where}: bad book key {key!r}")
                if (source, key) in rules:
                    raise TranslationOfError(f"{where}: {source} {key} is listed twice")
                rules[(source, key)] = ScriptureRule(source, key, target, note)
    return rules


def load_curated_links(path: Path = VERSION_LINKS_PATH) -> dict[str, str]:
    """The ``translation_of`` rows of the version links file: ``{work_id: other_work_id}``.

    The file's own checks are ``patristica.versions.load_version_links``; this
    raises ``TranslationOfError`` only for a work given two originals.
    """
    links: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            if (row.get("relation") or "").strip() != "translation_of":
                continue
            work = (row.get("work_id") or "").strip()
            other = (row.get("other_work_id") or "").strip()
            if work in links and links[work] != other:
                raise TranslationOfError(
                    f"{path}:{line}: {work} is already a translation of {links[work]}")
            links[work] = other
    return links


@cache
def _scripture_rules() -> dict[tuple[str, str], ScriptureRule]:
    return load_scripture_rules()


@cache
def _curated_links() -> dict[str, str]:
    return load_curated_links()


@cache
def scripture_sources() -> frozenset[str]:
    """The sources the Scripture table covers (one book per work)."""
    return frozenset(source for source, _ in _scripture_rules())


def scripture_rule(work_id: str) -> ScriptureRule | None:
    """The rule for a Scripture-source work, or None (not such a work, or no rule)."""
    source, _, book = work_id.partition("/")
    if source not in scripture_sources() or not book or "/" in book:
        return None
    rules = _scripture_rules()
    group = "nt" if book in NT_BOOKS else "ot"
    for key in (book, group, "*"):
        rule = rules.get((source, key))
        if rule is not None:
            return rule
    return None


def curated_translation_of(work_id: str) -> str | None:
    """The curated ``translation_of`` of *work_id*, or None if curation sets none."""
    rule = scripture_rule(work_id)
    if rule is not None:
        return rule.target(work_id.partition("/")[2])
    return _curated_links().get(work_id)


def apply_translation_of(work: dict) -> dict:
    """Return *work* (a raw or manifest work record) with its curated ``translation_of``.

    A copy if it changes.  Raises ``TranslationOfError`` if the ingestor set a
    different link: the two must agree, so fix one of them.
    """
    curated = curated_translation_of(work.get("work_id", ""))
    if curated is None:
        return work
    own = work.get("translation_of")
    if own == curated:
        return work
    if own:
        raise TranslationOfError(
            f"{work.get('work_id')}: the ingestor says translation_of {own!r}, "
            f"the curated tables say {curated!r}")
    return {**work, "translation_of": curated}


def translation_chain(work_id: str, translation_of: dict[str, str | None]) -> list[str]:
    """*work_id* followed by every work it was translated from, in order.

    Raises ``TranslationOfError`` on a cycle.  The chain stops at a work with
    no ``translation_of`` or one not in *translation_of*.
    """
    chain = [work_id]
    seen = {work_id}
    current = translation_of.get(work_id)
    while current:
        if current in seen:
            raise TranslationOfError(f"translation_of cycle: {' → '.join([*chain, current])}")
        chain.append(current)
        seen.add(current)
        current = translation_of.get(current)
    return chain
