"""Context for search results: the units around each hit, and its English version (#209).

Every result is shown with the unit before and after it (``context``): the
chunks at ``chunk_index ± 1`` in its work, a Scripture verse or a derived
verse (``patristica.versify``) alike. A preceding section heading is left
out, and so is a side that a keyword window already cuts off.

A result that is not in English carries an English ``translation`` of the
hit and of the same two neighbours:

1. a **linked English version** when one exists: the English chunks in the
   passage group (``passage_groups``, #179) or Scripture verse group
   (``chunks.translation_group_id``) of the hit, and of each neighbour.
   Scripture prefers the KJV; other works prefer an English work that is a
   ``translation_of`` the hit's work; then the work id decides. Units mapped
   to the hit are the translation's text, and units mapped only to a
   neighbour are its before and after.
2. else the **machine translation** (``chunk_translations``, #93) of the hit,
   with the machine translations of its neighbours where they have one.

Three queries a page, whatever its size.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from patristica.sources import source_label

ENGLISH = "eng"
# A neighbour longer than this is cut: from its start for the unit after, and
# to its end for the unit before, so the part next to the hit is kept.
CONTEXT_CHARS = 400
# Scripture's English version of choice, when the passage has several (source ids, in order).
SCRIPTURE_ENGLISH = ("kjv",)

# The units before (side -1) and after (side 1) each hit, in its work.
_NEIGHBOURS_SQL = """
SELECT h.chunk_id, sign(n.chunk_index - h.chunk_index)::int, n.chunk_id, n.canonical_ref,
       CASE WHEN n.chunk_index < h.chunk_index THEN right(n.text, %(chars)s)
            ELSE left(n.text, %(chars)s) END,
       length(n.text) > %(chars)s
FROM chunks h
JOIN chunks n ON n.work_id = h.work_id
             AND n.chunk_index IN (h.chunk_index - 1, h.chunk_index + 1)
WHERE h.chunk_id = ANY(%(ids)s::text[])
"""

# The English chunks in the passage group or verse group of each source chunk.
_ENGLISH_SQL = """
WITH src AS (
    SELECT c.chunk_id, pg.group_id AS pg, c.translation_group_id AS tg
    FROM chunks c LEFT JOIN passage_groups pg ON pg.chunk_id = c.chunk_id
    WHERE c.chunk_id = ANY(%(ids)s::text[])
), members AS (
    SELECT s.chunk_id AS src, p.chunk_id FROM src s JOIN passage_groups p ON p.group_id = s.pg
    UNION
    SELECT s.chunk_id, c.chunk_id FROM src s JOIN chunks c ON c.translation_group_id = s.tg
)
SELECT m.src, e.work_id, e.chunk_index, e.canonical_ref, left(e.text, %(chars)s),
       w.source_id, w.edition, w.translation_of
FROM members m
JOIN chunks e ON e.chunk_id = m.chunk_id
JOIN works w ON w.work_id = e.work_id
WHERE e.language = %(eng)s
"""

_MACHINE_SQL = """
SELECT chunk_id, text FROM chunk_translations
WHERE chunk_id = ANY(%(ids)s::text[]) AND language = %(eng)s
"""


@dataclass(frozen=True)
class Neighbour:
    chunk_id: str
    ref: str
    text: str  # cut to CONTEXT_CHARS, with "…" where cut


@dataclass(frozen=True)
class EnglishUnit:
    work_id: str
    index: int
    ref: str
    text: str
    source_id: str
    edition: str | None
    translation_of: str | None


def _is_heading_of(ref: str, hit_ref: str) -> bool:
    """Whether *ref* is a section above *hit_ref* (``Hom.3`` above ``Hom.3.1``): a heading."""
    return hit_ref.startswith(ref + ".")


def _clip(text: str, cut: bool, side: int) -> str:
    if not cut:
        return text
    return "…" + text.lstrip() if side < 0 else text.rstrip() + "…"


def _join(units: list[EnglishUnit]) -> str | None:
    return " ".join(u.text.strip() for u in units) or None


def _clip_context(text: str | None, side: int) -> str | None:
    """A neighbour's English, cut like the original's (*side* -1 before the hit, 1 after)."""
    if text is None or len(text) <= CONTEXT_CHARS:
        return text
    return _clip(text[-CONTEXT_CHARS:] if side < 0 else text[:CONTEXT_CHARS], True, side)


def english_version(result: dict[str, Any], before: str | None, after: str | None,
                    units: dict[str, list[EnglishUnit]]) -> dict[str, Any] | None:
    """The linked English version of *result*, from the English *units* of each source chunk.

    *before* and *after* are the chunk ids of the hit's neighbours. None when
    no English chunk is linked to the hit itself.
    """
    hit_units = units.get(result["chunk_id"], [])
    if not hit_units:
        return None
    scripture = result["work"]["genre"] == "scripture"

    def preference(work_id: str) -> tuple:
        unit = next(u for u in hit_units if u.work_id == work_id)
        preferred = len(SCRIPTURE_ENGLISH)
        if scripture and unit.source_id in SCRIPTURE_ENGLISH:
            preferred = SCRIPTURE_ENGLISH.index(unit.source_id)
        return (preferred, unit.translation_of != result["work_id"], work_id)

    work_id = min({u.work_id for u in hit_units}, key=preference)

    def in_work(chunk_id: str | None) -> dict[int, EnglishUnit]:
        return {u.index: u for u in units.get(chunk_id or "", []) if u.work_id == work_id}

    hit = in_work(result["chunk_id"])
    first, last = min(hit), max(hit)
    # A neighbour's units, less those already in the hit's (one English unit can render both).
    prev = [u for i, u in sorted(in_work(before).items()) if i < first]
    nxt = [u for i, u in sorted(in_work(after).items()) if i > last]
    shown = [hit[i] for i in sorted(hit)]
    lead = shown[0]
    return {
        "language": ENGLISH,
        "text": _join(shown),
        "before": _clip_context(_join(prev), -1),
        "after": _clip_context(_join(nxt), 1),
        "machine": False,
        "model": None,
        "work_id": work_id,
        "canonical_ref": lead.ref,
        "source_label": source_label(lead.source_id),
        "edition": lead.edition,
    }


def add_context(conn: Any, results: list[dict[str, Any]], text_chars: int) -> None:
    """Set ``context`` on each of *results*, and its English ``translation`` (see the module doc).

    *text_chars* caps the English text of the hit, as ``TEXT_CHARS`` caps the original's.
    """
    for r in results:
        r["context"] = {"before": None, "after": None}
    if not results:
        return
    ids = [r["chunk_id"] for r in results]
    around: dict[str, dict[int, Neighbour]] = {}
    for hit, side, chunk_id, ref, text, cut in conn.execute(
            _NEIGHBOURS_SQL, {"ids": ids, "chars": CONTEXT_CHARS}).fetchall():
        around.setdefault(hit, {})[side] = Neighbour(chunk_id, ref, _clip(text, cut, side))

    for r in results:
        sides = around.get(r["chunk_id"], {})
        before, after = sides.get(-1), sides.get(1)
        # A heading above the hit, or a side the keyword window already cuts, is no context.
        if before and (_is_heading_of(before.ref, r["canonical_ref"]) or r["text_start"] > 0):
            sides.pop(-1)
        if after and r["text_truncated"]:
            sides.pop(1)
        r["context"] = {
            key: None if n is None else {"chunk_id": n.chunk_id, "canonical_ref": n.ref,
                                         "text": n.text}
            for key, n in (("before", sides.get(-1)), ("after", sides.get(1)))
        }

    foreign = [r for r in results if r["language"] != ENGLISH]
    if not foreign:
        return
    sources = [cid for r in foreign for cid in (
        r["chunk_id"], *(n.chunk_id for n in around.get(r["chunk_id"], {}).values()))]
    units: dict[str, list[EnglishUnit]] = {}
    for src, work_id, index, ref, text, source_id, edition, translation_of in conn.execute(
            _ENGLISH_SQL, {"ids": sources, "chars": text_chars, "eng": ENGLISH}).fetchall():
        units.setdefault(src, []).append(
            EnglishUnit(work_id, index, ref, text, source_id, edition, translation_of))
    machine = dict(conn.execute(_MACHINE_SQL, {"ids": sources, "eng": ENGLISH}).fetchall())

    for r in foreign:
        neighbours = {side: n.chunk_id for side, n in around.get(r["chunk_id"], {}).items()}
        before, after = r["context"]["before"], r["context"]["after"]
        human = english_version(r, neighbours.get(-1) if before else None,
                                neighbours.get(1) if after else None, units)
        if human is not None:
            r["translation"] = human
        elif r["translation"] is not None:
            r["translation"].update(
                before=_clip_context(machine.get(before["chunk_id"]) if before else None, -1),
                after=_clip_context(machine.get(after["chunk_id"]) if after else None, 1),
                work_id=None, canonical_ref=None, source_label=None, edition=None)
