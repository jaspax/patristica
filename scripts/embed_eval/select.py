"""
Choose eval targets and assemble the sampled corpus.

Targets are the passages queries are written for. Each target language gets
two kinds:

- ``scripture`` — verses with parallels in other languages (linked by
  ``translation_group_id``). They test cross-lingual retrieval, but a good
  embedding treats all translations of a verse alike, so they cannot show
  whether one particular language is reachable.
- ``unique`` — passages from works that exist only in that language in our
  corpus (not a linked translation, nor the original of one). They test
  recall *within* the language.

The corpus is the search space: every chunk of the selected translation
groups (all languages, including English, Ge'ez and Gothic), the unique
targets with their neighbouring chunks (hard negatives from the same work),
and a random sample of distractors from every language.

Chunks outside ``MIN_CHARS``–``MAX_CHARS`` are not used as targets or
distractors, so chunk-size normalization (#2) does not confound the eval.
"""

from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass, field

# Languages that get targets. Gothic has no text of its own and Ge'ez is too
# thin until its cleanup issues are fixed (#23, #24, #39); both are searchable
# only as co-indexed translations for now. English is a query language.
TARGET_LANGS: tuple[str, ...] = ("grc", "lat", "hbo", "syc", "cop", "hye")

# Works that look language-unique by metadata but are not.
EXCLUDED_UNIQUE_WORKS: dict[str, str] = {
    "pta/pta0200/pta001/pta-syc1": "Syriac translation of Eusebius, Hist. eccl.; Greek in corpus",
    # Old Georgian (#529): the lectionaries are Gospel and Epistle pericopes,
    # the same text as the TITUS Bible witnesses, so not Georgian-only.
    "titus-paris-lectionary/lectionarium-hierosolymitanum": "Scripture pericopes (Paris)",
    "titus-khanmeti-lectionary/lectionarium-gracense": "Scripture pericopes (Khanmeti)",
}

# Explicit language-unique works, overriding the metadata rule in
# ``unique_works``. Ge'ez Scripture books with no parallel elsewhere count as
# unique; 1 Enoch is left out (Greek and Coptic fragments exist), as are the
# works with open cleanup issues (#23, #24, #39), the mislabelled 2 Kings (#66),
# and "Apocalypse of Ezra" (really 1 Esdras) and Testament of Our Lord (#76).
#
# Arabic (#483): every Arabic work is an original and most have an English
# version (tertullian.org, Evetts's History of the Patriarchs), so the metadata
# rule would leave only al-Kindi. The one-language set (``langset arb``) holds
# no English, so within it each of them is unique. There is no Arabic Scripture.
UNIQUE_WORKS: dict[str, tuple[str, ...]] = {
    "gez": (
        "gez/jub", "gez/1meq", "gez/3meq",
        "gez/clem",
    ),
    "arb": (
        "openiti/apology-of-al-kindi",
        "openiti/history-of-the-patriarchs-1", "openiti/history-of-the-patriarchs-2",
        "openiti/history-of-the-patriarchs-3", "openiti/history-of-the-patriarchs-4",
        "pearse-arabic/al-majdalus-commentary-on-the-creed",
        "pearse-arabic/ibn-al-tayyib-knowledge-and-miracles",
        "pearse-arabic/severus-book-of-the-councils-cairo-fragment",
        "pearse-arabic/yahya-ibn-adi-differences-in-the-gospels",
        "pearse-arabic/yahya-ibn-adi-incarnate-of-the-holy-spirit",
        "pearse-arabic/yahya-ibn-adi-truth-of-the-gospel",
    ),
}

MIN_CHARS = 30
MAX_CHARS = 2000


@dataclass(frozen=True)
class ChunkMeta:
    """What selection needs to know about a chunk (no text)."""

    chunk_id: str
    work_id: str
    language: str
    genre: str
    chunk_index: int
    n_chars: int
    translation_group_id: str | None = None
    out_of_period: bool = False

    @property
    def eligible(self) -> bool:
        return MIN_CHARS <= self.n_chars <= MAX_CHARS and not self.out_of_period


@dataclass(frozen=True)
class Target:
    chunk_id: str
    language: str
    origin: str  # "scripture" | "unique"


@dataclass
class Selection:
    targets: list[Target] = field(default_factory=list)
    corpus_ids: set[str] = field(default_factory=set)
    # corpus chunk id → why it is in the corpus (first reason wins)
    roles: dict[str, str] = field(default_factory=dict)

    def add(self, chunk_id: str, role: str) -> None:
        self.corpus_ids.add(chunk_id)
        self.roles.setdefault(chunk_id, role)


def unique_works(works: list[dict], excluded: dict[str, str] | None = None) -> dict[str, set[str]]:
    """Return language → work_ids that exist only in that language in the corpus."""
    excluded = EXCLUDED_UNIQUE_WORKS if excluded is None else excluded
    originals = {w["translation_of"] for w in works if w.get("translation_of")}
    out: dict[str, set[str]] = defaultdict(set)
    for w in works:
        if (
            w["genre"] != "scripture"
            and not w.get("translation_of")
            and w["work_id"] not in originals
            and w["work_id"] not in excluded
        ):
            out[w["language"]].add(w["work_id"])
    known = {w["work_id"] for w in works}
    for lang, ids in UNIQUE_WORKS.items():
        if listed := known.intersection(ids):
            out[lang] = listed
    return out


def select(
    chunks: list[ChunkMeta],
    works: list[dict],
    *,
    seed: int = 0,
    target_langs: tuple[str, ...] = TARGET_LANGS,
    scripture_per_lang: int = 100,
    unique_per_lang: int = 100,
    neighbours: int = 2,
    distractors_per_lang: int = 2000,
    required: frozenset[str] = frozenset(),
) -> Selection:
    """Pick targets and corpus members. Deterministic for a given *seed* and input.

    *required* chunk ids (targets of authored queries) are always in the
    corpus, with the rest of their translation group.
    """
    rng = random.Random(seed)
    sel = Selection()
    chunks = sorted(chunks, key=lambda c: c.chunk_id)

    by_group: dict[str, list[ChunkMeta]] = defaultdict(list)
    by_work: dict[str, list[ChunkMeta]] = defaultdict(list)
    for c in chunks:
        if c.translation_group_id:
            by_group[c.translation_group_id].append(c)
        by_work[c.work_id].append(c)
    for members in by_work.values():
        members.sort(key=lambda c: c.chunk_index)

    # Scripture: per language, sample verse groups with an eligible verse in it.
    for lang in target_langs:
        groups = sorted(
            g for g, members in by_group.items()
            if any(c.language == lang and c.eligible for c in members)
        )
        for g in rng.sample(groups, min(scripture_per_lang, len(groups))):
            candidates = [c for c in by_group[g] if c.language == lang and c.eligible]
            sel.targets.append(Target(rng.choice(candidates).chunk_id, lang, "scripture"))
            for c in by_group[g]:
                sel.add(c.chunk_id, "parallel")

    # Unique: per language, round-robin over shuffled works for variety.
    uniq = unique_works(works)
    for lang in target_langs:
        pools = []
        for work_id in sorted(uniq.get(lang, ())):
            pool = [c for c in by_work.get(work_id, []) if c.eligible]
            if pool:
                rng.shuffle(pool)
                pools.append(pool)
        rng.shuffle(pools)
        picked: list[ChunkMeta] = []
        while pools and len(picked) < unique_per_lang:
            pools = [p for p in pools if p]
            for pool in pools:
                if len(picked) < unique_per_lang and pool:
                    picked.append(pool.pop())
        for c in picked:
            sel.targets.append(Target(c.chunk_id, lang, "unique"))
            sel.add(c.chunk_id, "target")
            members = by_work[c.work_id]
            i = next(k for k, m in enumerate(members) if m.chunk_id == c.chunk_id)
            for m in members[max(0, i - neighbours): i + neighbours + 1]:
                sel.add(m.chunk_id, "neighbour")

    for c in chunks:
        if c.chunk_id in required:
            sel.add(c.chunk_id, "authored")
            for m in by_group.get(c.translation_group_id or "", []):
                sel.add(m.chunk_id, "parallel")

    # Distractors from every language present.
    by_lang: dict[str, list[str]] = defaultdict(list)
    for c in chunks:
        if c.eligible:
            by_lang[c.language].append(c.chunk_id)
    for lang in sorted(by_lang):
        ids = by_lang[lang]
        for cid in rng.sample(ids, min(distractors_per_lang, len(ids))):
            sel.add(cid, "distractor")

    return sel


def extend(
    chunks: list[ChunkMeta],
    works: list[dict],
    lang: str,
    corpus_ids: set[str],
    *,
    seed: int = 0,
    scripture_per_lang: int = 100,
    unique_per_lang: int = 100,
    neighbours: int = 2,
) -> Selection:
    """Pick targets for one more language without disturbing an existing corpus.

    Scripture targets come first from translation groups already in the
    corpus (so no new parallels are needed); unique targets bring their
    neighbours. Uses its own random stream, so the result does not depend on
    which languages were selected before.
    """
    rng = random.Random(f"{seed}:extend:{lang}")
    sel = Selection()
    chunks = sorted(chunks, key=lambda c: c.chunk_id)
    by_group: dict[str, list[ChunkMeta]] = defaultdict(list)
    by_work: dict[str, list[ChunkMeta]] = defaultdict(list)
    for c in chunks:
        if c.translation_group_id:
            by_group[c.translation_group_id].append(c)
        by_work[c.work_id].append(c)
    for members in by_work.values():
        members.sort(key=lambda c: c.chunk_index)

    candidates = {
        g: [c for c in members if c.language == lang and c.eligible]
        for g, members in by_group.items()
    }
    candidates = {g: cs for g, cs in candidates.items() if cs}
    present = sorted(g for g in candidates if any(c.chunk_id in corpus_ids for c in by_group[g]))
    absent = sorted(set(candidates) - set(present))
    rng.shuffle(present)
    rng.shuffle(absent)
    for g in (present + absent)[:scripture_per_lang]:
        sel.targets.append(Target(rng.choice(candidates[g]).chunk_id, lang, "scripture"))
        for c in by_group[g]:
            sel.add(c.chunk_id, "parallel")

    pools = []
    for work_id in sorted(unique_works(works).get(lang, ())):
        pool = [c for c in by_work.get(work_id, []) if c.eligible]
        if pool:
            rng.shuffle(pool)
            pools.append(pool)
    rng.shuffle(pools)
    picked: list[ChunkMeta] = []
    while pools and len(picked) < unique_per_lang:
        pools = [p for p in pools if p]
        for pool in pools:
            if len(picked) < unique_per_lang and pool:
                picked.append(pool.pop())
    for c in picked:
        sel.targets.append(Target(c.chunk_id, lang, "unique"))
        sel.add(c.chunk_id, "target")
        members = by_work[c.work_id]
        i = next(k for k, m in enumerate(members) if m.chunk_id == c.chunk_id)
        for m in members[max(0, i - neighbours): i + neighbours + 1]:
            sel.add(m.chunk_id, "neighbour")
    return sel
