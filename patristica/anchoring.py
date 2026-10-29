"""Derived verses anchored on the original (#292, #304; ``docs/anchored-derived-verses.md``).

Derived verses (#2, ``patristica.versify``) are cut in every work on its own,
at a per-language size, so the versions of one work are cut at different
places and parallel reading shows rows that start and end at different words.
An *anchored* work is a translation whose derived verses are cut where its text
corresponds to its original's derived verses (``Work.translation_of``), so that
most rows become 1:1.

The cut is computed by the paid step ``scripts.anchor`` (from Voyage vectors,
``patristica.anchor_refine``) and recorded in a tracked *cut file*
(``patristica.anchor_store``): per source paragraph, the word positions where
its derived verses start. ``scripts.normalize`` applies a current cut file
(:func:`units_of`) and stays free, deterministic and vector-free. A paragraph
without a current record (no cut file yet, or its words changed) is cut as
today (``versify.split_text``, the *provisional* cut).

**Enrolment** is per source (``patristica/data/anchored_sources.csv``,
``source_id,language,reason``): a source is enrolled before its first
normalize, never after (that would re-cut published refs: #200's migration).
A row with a ``language`` enrols only that source's works in that language
(#335: PTA's one Slavonic text, while PTA's English translations keep their
derived verses); a row without one enrols the whole source. Only prose works
are anchored: Scripture and works ingested as verses keep their verses.

**The anchor** of an enrolled work is its ``translation_of``. A work without
one, with an anchor not in the corpus, or with an anchor in its own language
(another edition: #199's job, :func:`same_language`) is cut as today.

This module is part of normalize's code (no numpy). ``ANCHOR_VERSION`` and
:class:`RefineParams` live here too: like ``VERSE_TOKENS`` they are frozen,
since changing them re-cuts every anchored work.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, get_args

from patristica import fingerprint
from patristica.models import Language
from patristica.versify import _atoms, is_derived_ref

if TYPE_CHECKING:
    from patristica.anchor_store import CutFile
    from patristica.models import Chunk

ENROLMENT_PATH = Path(__file__).parent / "data" / "anchored_sources.csv"

#: The method version of the refinement. Bump it (deliberately, like
#: ``LOADER_VERSION``) when a change to ``scripts.anchor`` should re-cut: cut
#: files made with another version are reported stale but frozen (they are
#: re-cut only with ``scripts.anchor --recut``).
ANCHOR_VERSION = 1


class AnchoringError(ValueError):
    """The enrolment table is malformed, or anchors form a cycle."""


# ---------------------------------------------------------------- enrolment


def load_enrolment(path: Path = ENROLMENT_PATH) -> dict[tuple[str, str | None], str]:
    """``{(source_id, language): reason}`` from the enrolment table; the
    language is None for a row that enrols the whole source. The ``language``
    column is optional."""
    rows: dict[tuple[str, str | None], str] = {}
    languages = set(get_args(Language))
    with path.open(encoding="utf-8", newline="") as f:
        for line, row in enumerate(csv.DictReader(f), start=2):
            source = (row.get("source_id") or "").strip()
            language = (row.get("language") or "").strip() or None
            reason = (row.get("reason") or "").strip()
            where = f"{path}:{line}"
            if not source or "/" in source:
                raise AnchoringError(f"{where}: bad source_id {source!r}")
            if language is not None and language not in languages:
                raise AnchoringError(f"{where}: {source}: unknown language {language!r}")
            if not reason:
                raise AnchoringError(f"{where}: {source}: no reason given")
            if (source, language) in rows:
                raise AnchoringError(f"{where}: {source} {language or ''} is listed twice")
            if (source, None) in rows or (language is None
                                          and any(s == source for s, _ in rows)):
                raise AnchoringError(
                    f"{where}: {source} is enrolled both as a whole and by language")
            rows[(source, language)] = reason
    return rows


@cache
def enrolled_sources() -> dict[str, str]:
    """``{source_id: reason}`` of the sources enrolled as a whole."""
    return {s: r for (s, lang), r in load_enrolment().items() if lang is None}


@cache
def enrolled_languages() -> dict[tuple[str, str], str]:
    """``{(source_id, language): reason}`` of the sources enrolled by language."""
    return {(s, lang): r for (s, lang), r in load_enrolment().items() if lang is not None}


def enrols_by_language(source_id: str) -> bool:
    """True if some of *source_id*'s works are enrolled by their language, so
    :func:`is_enrolled` needs the work's language to decide."""
    return any(s == source_id for s, _ in enrolled_languages())


def is_enrolled(source_id: str, language: str | None = None) -> bool:
    """True if the works of *source_id* (in *language*) get anchored derived
    verses: the source is enrolled as a whole, or for *language*."""
    return source_id in enrolled_sources() or (
        language is not None and (source_id, language) in enrolled_languages())


def anchor_id(work: Mapping[str, object]) -> str | None:
    """The work an enrolled work is anchored on: its ``translation_of``, or None."""
    target = work.get("translation_of")
    return target if isinstance(target, str) and target else None


def same_language(work_language: str, anchor_language: str) -> bool:
    """The #199 hook: an anchor in the work's own language is another edition,
    which needs a text-level alignment rather than vectors. Until #199 lands
    such a work isn't anchored (it is cut as today)."""
    return work_language == anchor_language


def anchor_order(anchors: Mapping[str, str | None]) -> list[str]:
    """The work ids of *anchors* (``work id → anchor id``) so that a work comes
    after the work it is anchored on, when that one is in *anchors* too.
    Raises ``AnchoringError`` on a cycle."""
    order: list[str] = []
    state: dict[str, int] = {}  # 1 visiting, 2 done

    def visit(work_id: str, chain: tuple[str, ...]) -> None:
        if state.get(work_id) == 2:
            return
        if state.get(work_id) == 1:
            raise AnchoringError(f"anchor cycle: {' → '.join([*chain, work_id])}")
        state[work_id] = 1
        target = anchors[work_id]
        if target is not None and target in anchors:
            visit(target, (*chain, work_id))
        state[work_id] = 2
        order.append(work_id)

    for work_id in sorted(anchors):
        visit(work_id, ())
    return order


# ---------------------------------------------------------------- parameters


@dataclass(frozen=True)
class RefineParams:
    """Settings of the refinement (``patristica.anchor_refine``; the design §4).

    Recorded in every cut file (:func:`params_hash`). Changing one re-cuts
    every anchored work, so bump :data:`ANCHOR_VERSION` with it.
    """

    margin: float = 0.05  # as the aligner (#179)
    merge_penalty: float = 0.06  # per extra original unit in a bead
    max_originals: int = 3  # original units per bead
    max_segments: int = 24
    max_tokens_verses: float = 12.0  # a piece is at most this many verses of its language
    skip_segment: float = 0.03  # cost of leaving a segment out of every bead
    break_cost: tuple[float, float, float, float] = (0.0, 0.01, 0.03, 0.08)  # by end strength
    cross_paragraph: float = 0.02  # per translation paragraph break inside a bead
    band: int = 6  # original units either side of the provisional estimate
    #: Charged to a piece scored by its summed segments rather than its own
    #: vector: a hysteresis that keeps an embedded piece unless the estimate
    #: is clearly better, so the rounds converge.
    unembedded: float = 0.02
    max_rounds: int = 3  # exploring rounds, then one exact-only round (owner, 2026-10-28)
    #: Calibration needs this many confident 1:1 beads of the provisional cut.
    min_calibration: int = 20


def params_hash(params: RefineParams = RefineParams()) -> str:
    """What a cut file records of the method: its version and parameters."""
    return fingerprint.value_hash({"version": ANCHOR_VERSION, "params": asdict(params)})


# --------------------------------------------------------------- paragraphs


def words(text: str) -> list[str]:
    """*text*'s words (``versify._atoms``, each with the whitespace before it),
    without a trailing whitespace atom. Cut positions index this list."""
    return [a for a in _atoms(text) if a.strip()]


def words_hash(ws: Sequence[str]) -> str:
    """Hash of a paragraph's words, ignoring the whitespace between them."""
    return fingerprint.value_hash([w.strip() for w in ws])


def cut_at(text: str, starts: Sequence[int]) -> list[str]:
    """*text* cut before the words at *starts* (``starts[0] == 0``), as stripped
    slices of it (as ``versify.split_text`` returns them)."""
    ws = words(text)
    bounds = [*starts, len(ws)]
    return ["".join(ws[a:b]).strip() for a, b in zip(bounds, bounds[1:])]


def valid_starts(starts: Sequence[int], n_words: int) -> bool:
    return (bool(starts) and starts[0] == 0
            and all(a < b for a, b in zip(starts, starts[1:])) and starts[-1] < n_words)


@dataclass(frozen=True)
class Paragraph:
    """A source paragraph rebuilt from a work's normalized units: its ref (the
    chunk's, before the split), its words and the word index where each of
    its units starts."""

    ref: str
    words: tuple[str, ...]
    starts: tuple[int, ...]
    units: tuple[str, ...]

    @property
    def words_hash(self) -> str:
        return words_hash(self.words)


def paragraphs(chunks: Sequence[Mapping[str, object]]) -> list[Paragraph]:
    """A work's source paragraphs, rebuilt from its normalized chunks.

    Consecutive derived verses of one chunk (``ref.s1``, ``ref.s2``, …) are one
    paragraph; any other chunk is a paragraph of one unit.
    """
    groups: list[tuple[str, list[str]]] = []
    last: str | None = None
    for c in chunks:
        ref, text = str(c["canonical_ref"]), str(c["text"])
        parent = ref.rsplit(".", 1)[0] if is_derived_ref(ref) else ref
        if parent != ref and parent == last:
            groups[-1][1].append(text)
        else:
            groups.append((parent, [text]))
        last = parent if parent != ref else None
    out = []
    for ref, units in groups:
        ws: list[str] = []
        starts: list[int] = []
        for u in units:
            starts.append(len(ws))
            ws.extend(words(u))
        out.append(Paragraph(ref, tuple(ws), tuple(starts), tuple(units)))
    return out


def cuts_hash(units: Sequence[tuple[str, str]]) -> str:
    """Hash of a work's cuts: its units' refs and texts, in order (the
    original's ``anchor_cuts`` in a cut file)."""
    return fingerprint.value_hash([[ref, text] for ref, text in units])


def chunks_cuts_hash(chunks: Sequence[Mapping[str, object]]) -> str:
    return cuts_hash([(str(c["canonical_ref"]), str(c["text"])) for c in chunks])


# ---------------------------------------------------------------- applying


def units_of(chunks: Sequence[Chunk], cut: CutFile) -> dict[str, list[str]]:
    """Derived-verse texts per chunk id from a cut file, for ``versify_chunks``.

    *chunks* are a work's chunks before the split. A chunk gets the recorded
    units when the cut file has its ref and the hash of its words matches;
    every other chunk is left to ``split_text`` (the provisional cut).
    """
    out: dict[str, list[str]] = {}
    for c in chunks:
        if is_derived_ref(c.canonical_ref):
            continue
        rec = cut.paragraphs.get(c.canonical_ref)
        if rec is None:
            continue
        ws = words(c.text)
        if rec.words != words_hash(ws) or not valid_starts(rec.starts, len(ws)):
            continue
        out[c.chunk_id] = cut_at(c.text, rec.starts)
    return out
