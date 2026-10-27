"""
Editorial material: marked in the text, kept for readers, left out of
embedding and translation (#236).

Many texts carry material that is not the text itself: titles and headings
an editor added, supplements, lacuna markers, chant metadata, notes. Readers
should see it, but it distorts search when it is embedded with the text. So
instead of being stripped at ingest, it is *marked*: a unit's text stays
whole, and a list of spans says which parts of it are editorial.

**Representation.** A span is ``[start, end, kind]``: character offsets into
the unit's text (Python ``str`` indices, end exclusive) and one of
:data:`KINDS`. Spans are sorted, don't overlap and are not empty. A unit
whose whole text is editorial (a heading an editor added) has one span over
all of it; it gets no vector and no translation.

- **Raw data:** an ingestor puts the spans on a raw unit, next to its text:
  ``{"ref": …, "text": …, "editorial": [[start, end, kind], …]}``. Offsets
  are into that raw ``text``. Ingestors write the lists themselves and don't
  import this module, so a change here never invalidates their ingest stamps
  (#130).
- **Normalized data:** ``scripts.normalize`` validates the spans
  (:func:`check`), moves them onto the cleaned chunk text and carries them
  through the derived-verse split (:func:`unit_spans`, :func:`split_spans`).
  A chunk with spans gets an ``editorial`` key in its normalized JSON; a
  chunk without has no key, so unmarked works are byte-identical to what they
  were before this module existed. It is not a ``Chunk`` field: every
  ingestor imports ``patristica/models.py``, and a new field would
  invalidate every ingest stamp.
- **Library export:** a work file has ``editorial: {ref_suffix: spans}`` for
  its marked chunks, with offsets in UTF-16 code units, which is how
  JavaScript indexes strings (:func:`utf16_spans`).

**Consumers.**

- ``scripts.translate``, ``scripts.embed``, ``scripts.align`` and
  ``scripts.build_index`` read a unit's *source text*, its text without the
  editorial spans (:func:`source_text`), and hash that. The exception is a
  ``supplement``, an editor's addition the passage needs for its sense: its
  text stays and only its brackets go (:data:`KEPT_KINDS`). Marking a span
  re-translates and re-embeds exactly the units it is in, and a unit without
  spans hashes its ``text`` as before.
- The keyword index (``patristica.keyword``) folds the full text, editorial
  material included: a phrase search finds what the reader shows.
- The derived-verse split cuts the full text, so marking material in an
  existing text never renumbers derived verses.
- The reader shows editorial spans with a neutral marker; the dedicated
  style per kind is #291.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

#: The kinds of editorial material.
KINDS: frozenset[str] = frozenset({
    "title",       # a title or superscription the source or an editor gives a text
    "heading",     # a heading an editor added inside the text
    "supplement",  # text an editor supplied (embedded; only its brackets are not)
    "lacuna",      # a marker for text lost or left out ([…], <gap/>)
    "metadata",    # catalogue data in the text (CANTUS feast, mode and id)
    "note",        # an editor's or transcriber's note, a variant reading
})

#: Kinds whose text stays in the source text (translated and embedded): an
#: editor's supplement is an addition the passage needs for its sense. Only
#: its brackets, if the span includes them, are left out. Every other kind is
#: left out whole.
KEPT_KINDS: frozenset[str] = frozenset({"supplement"})

# Brackets an edition puts around a supplement (Leiden <…>, […], ⟨…⟩).
_OPENERS = "<[(⟨{〈"
_CLOSERS = ">])⟩}〉"

#: The key that holds the spans, on a raw unit and on a normalized chunk.
KEY = "editorial"

Span = tuple[int, int, str]


class EditorialError(ValueError):
    """Editorial spans that don't fit their text."""


def check(text: str, spans: Iterable[Sequence[Any]], where: str = "") -> list[Span]:
    """*spans* as tuples, after checking them against *text*.

    Raises ``EditorialError`` for an unknown kind, an empty span, one outside
    the text, and spans that are unsorted or overlap.
    """
    out: list[Span] = []
    prefix = f"{where}: " if where else ""
    if isinstance(spans, (str, bytes)) or not isinstance(spans, Iterable):
        raise EditorialError(f"{prefix}editorial spans {spans!r} are not a list")
    for span in spans:
        if not isinstance(span, (list, tuple)) or len(span) != 3:
            raise EditorialError(f"{prefix}editorial span {span!r} is not [start, end, kind]")
        start, end, kind = span
        if not (isinstance(start, int) and isinstance(end, int)) or isinstance(start, bool) \
                or isinstance(end, bool):
            raise EditorialError(f"{prefix}editorial span {span!r} has non-integer offsets")
        if not isinstance(kind, str) or kind not in KINDS:
            raise EditorialError(f"{prefix}unknown editorial kind {kind!r} "
                                 f"(one of {', '.join(sorted(KINDS))})")
        if not 0 <= start < end <= len(text):
            raise EditorialError(f"{prefix}editorial span {span!r} is empty or outside "
                                 f"the text ({len(text)} characters)")
        if out and start < out[-1][1]:
            raise EditorialError(f"{prefix}editorial spans overlap or are unsorted: "
                                 f"{list(out[-1])!r}, {span!r}")
        out.append((start, end, kind))
    return out


def strip(text: str, spans: Sequence[Span]) -> str:
    """*text* without its editorial spans: the source text.

    A removed span and the whitespace around it become one space, or nothing
    at either end of the text, so ``a […] b``, ``a […]b`` and ``a[…]b`` all
    give ``a b``: what was on either side of the span stays apart.

    A ``supplement`` (:data:`KEPT_KINDS`) is the editor's addition to the text,
    needed for its sense, so it stays: only its brackets are dropped
    (:func:`supplement_text`), and it joins its neighbours as written, so
    ``ⲡⲁⲅⲅⲉ<ⲗⲟⲥ>`` gives ``ⲡⲁⲅⲅⲉⲗⲟⲥ``. Without spans, *text* is returned
    unchanged.
    """
    if not spans:
        return text
    out = ""
    pos = 0
    gap = False  # a span was removed since the last text kept
    for start, end, kind in spans:
        out, gap = _append(out, text[pos:start], gap)
        if kind in KEPT_KINDS:
            out, gap = _append(out, supplement_text(text[start:end]), gap)
        else:
            gap = True
        pos = end
    out, _ = _append(out, text[pos:], gap)
    return out.strip()


def supplement_text(span_text: str) -> str:
    """A supplement's text without the editor's brackets around it.

    One opening bracket at the start and one closing bracket at the end are
    dropped, each on its own: a supplement cut by the derived-verse split may
    keep only one of them.
    """
    if span_text[:1] in _OPENERS:
        span_text = span_text[1:]
    if span_text[-1:] in _CLOSERS:
        span_text = span_text[:-1]
    return span_text


def _append(out: str, piece: str, gap: bool) -> tuple[str, bool]:
    """``strip``'s step: add *piece* to *out*, after a removed span if *gap*."""
    if not gap:
        return out + piece, False
    piece = piece.lstrip()
    if not piece:  # only whitespace between two spans: still one gap
        return out, True
    out = out.rstrip()
    return (f"{out} {piece}" if out else piece), False


def spans_of(chunk: Mapping[str, Any]) -> list[Span]:
    """The editorial spans of a normalized chunk (a dict), as tuples."""
    return [tuple(s) for s in chunk.get(KEY) or ()]  # type: ignore[misc]


def source_text(chunk: Mapping[str, Any]) -> str:
    """The text of a normalized chunk without its editorial material.

    What ``scripts.translate`` translates and ``scripts.embed`` embeds, and
    what their hashes cover. A chunk without spans gives its ``text``
    unchanged.
    """
    text: str = chunk["text"]
    return strip(text, spans_of(chunk)) if chunk.get(KEY) else text


def clip(spans: Sequence[Span], start: int, end: int) -> list[Span]:
    """The parts of *spans* inside ``[start, end)``, shifted to start there."""
    out: list[Span] = []
    for s, e, kind in spans:
        s, e = max(s, start), min(e, end)
        if s < e:
            out.append((s - start, e - start, kind))
    return out


def unit_spans(raw_text: str, text: str, spans: Sequence[Span], where: str = "") -> list[Span]:
    """Move spans on a raw unit's text onto its cleaned chunk text.

    ``scripts.normalize`` cleans a unit's text by cutting off a prefix
    (surrounding whitespace, a repeated section number) and trailing
    whitespace, so *text* is one slice of *raw_text*: the one that starts
    after the leading whitespace and the cut prefix.
    """
    if not spans:
        return []
    stripped = raw_text.strip()
    start = len(raw_text) - len(raw_text.lstrip()) + len(stripped) - len(text)
    if not stripped.endswith(text) or raw_text[start:start + len(text)] != text:
        raise EditorialError(f"{where}: the chunk text is not a slice of the raw text, "
                             "so its editorial spans can't be placed")
    return clip(spans, start, start + len(text))


def split_spans(text: str, pieces: Sequence[str], spans: Sequence[Span]) -> list[list[Span]]:
    """The spans of each of *pieces*, consecutive slices of *text*.

    The derived-verse split (``patristica.versify``) cuts a text into pieces
    that are slices of it in order, stripped of whitespace. A span across a
    cut is divided between the pieces; whitespace between two pieces belongs
    to neither.
    """
    out: list[list[Span]] = []
    pos = 0
    for piece in pieces:
        at = text.find(piece, pos)
        if at < 0:
            raise EditorialError(f"derived verse {piece[:40]!r} is not a slice of its unit")
        out.append(clip(spans, at, at + len(piece)))
        pos = at + len(piece)
    return out


def utf16_spans(text: str, spans: Sequence[Span]) -> list[list[Any]]:
    """*spans* with offsets in UTF-16 code units (JavaScript string indices).

    They differ from Python's only after a character outside the Basic
    Multilingual Plane (Gothic, some symbols).
    """
    def at(i: int) -> int:
        return len(text[:i].encode("utf-16-le")) // 2

    return [[at(s), at(e), kind] for s, e, kind in spans]
