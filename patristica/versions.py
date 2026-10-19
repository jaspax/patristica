"""Work-level version groups (#178).

A *version group* is the set of works that are the same text in any language
or edition: a Greek Father, its English and Latin translations and a second
Greek edition; or Genesis in every Scripture source.  Groups are derived, never
stored: they are the connected components of the graph whose edges are

1. ``Work.translation_of`` (set by the ingestors; the direction is known),
2. **Scripture books**: works of a Scripture source (``versification.SOURCE_SCHEMES``)
   whose book is the same, i.e. whose local id is the same OSIS book
   (``kjv/gen``, ``oshb/gen``, ``lxx-rahlfs/gen``), whatever their genre,
3. **CTS work ids**: works of the CTS sources (``first1k``, ``perseus``, ``pta``,
   ids ``{source}/{textgroup}/{work}/{edition}``) with the same
   ``{textgroup}/{work}``.  First1KGreek and Perseus share one CTS namespace
   (``tlg``/``stoa``/``ogl``); PTA uses its own (``pta``), so the rule never
   crosses from PTA to the other two by accident,
4. the curated links in ``patristica/data/version_links.csv``
   (``work_id,other_work_id,relation,reason``) for everything else: Latin
   translations of Greek works, the same work in two editions without a shared
   id (OGPG vs First1K/PTA, OGLT PL vs Perseus), versions in the Oriental
   languages, and Scripture books whose sources name them differently.

``relation`` is ``translation_of`` (``work_id`` translates ``other_work_id``),
``same_work`` (sibling versions, neither known to be the other's original) or
``different_edition`` (the same text in the same language, another edition).

**Canon.** A Scripture book's group holds every witness of the book, whatever
its genre in that witness: genre records the book's status in the witness's
own tradition (CLAUDE.md "Genre values"), not what text it is, so Ge'ez
``gez/1en`` (``scripture``) and Coptic ``coptic-nt/1en`` (``apocrypha``) are one
group, and the Greek Enoch of First1K joins it through a curated link.  Readers
see each version's genre next to it.  Books that are only *part* of another
book in some witnesses (Susanna and Bel, printed as Daniel 13–14 in the
Vulgate; the Letter of Jeremiah as Baruch 6) keep their own group, because a
work can only belong to one group and joining a part to the whole would merge
Susanna with Daniel.

**Rule for curated links:** link two works only when they are the same work,
even if one edition is partial.  Never link a container (a Migne Work holding
several works, a florilegium, a catena) to one of the works it contains: the
components would merge every work it holds into one group.

**Group ids** are deterministic: ``book:{osis book}`` for a group holding a
Scripture book (the smallest book key when a curated link joins two), otherwise
the smallest ``work_id`` among the group's originals (members with no
``translation_of`` link inside the group), or among all members if every one is
a translation.  An id depends only on the links, not on input order, but it can
change when a link is added, so never use it as a URL or persist it.
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from patristica.versification import SOURCE_SCHEMES

LINKS_PATH = Path(__file__).parent / "data" / "version_links.csv"
RELATIONS: tuple[str, ...] = ("translation_of", "same_work", "different_edition")
#: Sources whose work ids are ``{source}/{textgroup}/{work}/{edition}`` CTS URNs.
CTS_SOURCES: frozenset[str] = frozenset({"first1k", "perseus", "pta"})
#: Sources whose works are one Scripture book each, with the OSIS book (lower case) as local id.
SCRIPTURE_SOURCES: frozenset[str] = frozenset(SOURCE_SCHEMES)


class VersionLinkError(ValueError):
    """The curated links file is malformed."""


@dataclass(frozen=True, order=True)
class VersionLink:
    work_id: str
    other_work_id: str
    relation: str
    reason: str


def load_version_links(path: Path = LINKS_PATH) -> list[VersionLink]:
    """Read and check the curated links file.

    Raises ``VersionLinkError`` for an unknown relation, a missing reason, a
    self-link or a pair listed twice (in either order).
    """
    links: list[VersionLink] = []
    seen: dict[frozenset[str], int] = {}
    with path.open(encoding="utf-8", newline="") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            a = (row.get("work_id") or "").strip()
            b = (row.get("other_work_id") or "").strip()
            rel = (row.get("relation") or "").strip()
            reason = (row.get("reason") or "").strip()
            where = f"{path}:{line}"
            if not a or not b:
                raise VersionLinkError(f"{where}: empty work id")
            if a == b:
                raise VersionLinkError(f"{where}: {a} is linked to itself")
            if rel not in RELATIONS:
                raise VersionLinkError(f"{where}: unknown relation {rel!r} (one of {RELATIONS})")
            if not reason:
                raise VersionLinkError(f"{where}: {a} – {b}: no reason given")
            pair = frozenset((a, b))
            if pair in seen:
                raise VersionLinkError(f"{where}: {a} – {b} is already linked on line {seen[pair]}")
            seen[pair] = line
            links.append(VersionLink(a, b, rel, reason))
    return links


@cache
def curated_links() -> tuple[VersionLink, ...]:
    return tuple(load_version_links())


def scripture_book(work_id: str) -> str | None:
    """The book key of a Scripture-source work (``kjv/gen`` → ``gen``), else None."""
    source, _, local = work_id.partition("/")
    if source in SCRIPTURE_SOURCES and local and "/" not in local:
        return local
    return None


def cts_work(work_id: str) -> str | None:
    """The CTS ``{textgroup}/{work}`` of a CTS-source work, else None.

    ``first1k`` and ``perseus`` share a namespace, so their keys are bare;
    ``pta`` keys are prefixed, since PTA numbers its own text groups.
    """
    parts = work_id.split("/")
    if len(parts) != 4 or parts[0] not in CTS_SOURCES:
        return None
    key = f"{parts[1]}/{parts[2]}"
    return f"pta:{key}" if parts[0] == "pta" else key


@dataclass(frozen=True)
class VersionGroups:
    """Version groups of a corpus: ``group_of`` maps every work in a multi-member group to its group id."""

    group_of: dict[str, str]
    members: dict[str, tuple[str, ...]]  # group id → sorted work ids (only groups of ≥ 2)
    #: Links that name a work not in the corpus, ignored: ``(work_id, other_work_id)``.
    dangling: tuple[tuple[str, str], ...] = ()

    def group(self, work_id: str) -> str | None:
        return self.group_of.get(work_id)


class _UnionFind:
    def __init__(self, items: Iterable[str]) -> None:
        self.parent = {x: x for x in items}

    def find(self, x: str) -> str:
        root = x
        while self.parent[root] != root:
            root = self.parent[root]
        while self.parent[x] != root:
            self.parent[x], x = root, self.parent[x]
        return root

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            # Deterministic regardless of order: the smaller id becomes the root.
            lo, hi = sorted((ra, rb))
            self.parent[hi] = lo


def derive_version_groups(
    translation_of: Mapping[str, str | None],
    links: Iterable[VersionLink] | None = None,
) -> VersionGroups:
    """Derive version groups for the works in *translation_of* (``work_id → translation_of``).

    *links* defaults to the curated file.  A link or ``translation_of`` that
    names a work not in the corpus is ignored and listed in ``dangling``
    (``tests/test_versions.py`` requires none in the tracked corpus).
    """
    works = set(translation_of)
    uf = _UnionFind(sorted(works))
    translated: set[str] = set()  # works with a translation_of edge (not originals)
    dangling: list[tuple[str, str]] = []

    for wid in sorted(works):
        target = translation_of[wid]
        if target:
            if target not in works:
                dangling.append((wid, target))
                continue
            uf.union(wid, target)
            translated.add(wid)

    by_key: dict[str, list[str]] = defaultdict(list)
    for wid in sorted(works):
        book = scripture_book(wid)
        if book:
            by_key[f"book:{book}"].append(wid)
        cts = cts_work(wid)
        if cts:
            by_key[f"cts:{cts}"].append(wid)
    for key in sorted(by_key):
        first, *rest = by_key[key]
        for wid in rest:
            uf.union(first, wid)

    for link in sorted(curated_links() if links is None else links):
        if link.work_id not in works or link.other_work_id not in works:
            dangling.append((link.work_id, link.other_work_id))
            continue
        uf.union(link.work_id, link.other_work_id)
        if link.relation == "translation_of":
            translated.add(link.work_id)

    components: dict[str, list[str]] = defaultdict(list)
    for wid in sorted(works):
        components[uf.find(wid)].append(wid)

    group_of: dict[str, str] = {}
    members: dict[str, tuple[str, ...]] = {}
    for comp in components.values():
        if len(comp) < 2:
            continue
        gid = _group_id(comp, translated)
        members[gid] = tuple(comp)
        for wid in comp:
            group_of[wid] = gid
    return VersionGroups(group_of, dict(sorted(members.items())), tuple(dangling))


def _group_id(members: list[str], translated: set[str]) -> str:
    books = sorted(b for b in (scripture_book(w) for w in members) if b)
    if books:
        return f"book:{books[0]}"
    originals = [w for w in members if w not in translated]
    return min(originals or members)


def language_pair_counts(
    groups: VersionGroups, language_of: Mapping[str, str]
) -> list[tuple[str, str, int, int]]:
    """Per language pair: ``(lang_a, lang_b, groups, works)``.

    ``groups`` counts the groups holding both languages (for a pair of one
    language, at least two works in it: two editions); ``works`` counts the
    works of either language in those groups.  Sorted by pair.
    """
    n_groups: Counter[tuple[str, str]] = Counter()
    n_works: Counter[tuple[str, str]] = Counter()
    for gid, mem in groups.members.items():
        langs = Counter(language_of[w] for w in mem)
        present = sorted(langs)
        for i, a in enumerate(present):
            for b in present[i:]:
                if a == b and langs[a] < 2:
                    continue
                n_groups[(a, b)] += 1
                n_works[(a, b)] += langs[a] + (langs[b] if a != b else 0)
    return [(a, b, n_groups[(a, b)], n_works[(a, b)]) for a, b in sorted(n_groups)]
