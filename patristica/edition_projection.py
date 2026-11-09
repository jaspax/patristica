"""Derived verses of an edition cut where another edition of the same text cuts (#200).

Two editions of one text in one language (Migne's OCR'd Greek and a critical
text, a CSEL volume and the Patrologia Latina) are cut into derived verses
independently (``patristica.versify``), and their punctuation differs, so the
cuts fall at different words and parallel reading shows rows that start and
end at different places (#199). An *edition anchored on a reference edition*
takes the reference's cuts instead: each of the reference's unit starts is
carried through the word alignment of the two texts
(``patristica.text_alignment.align_words``, #199) to the word it is matched
with, and cuts the edition's paragraph there.

**Words.** Both editions' source paragraphs (``anchoring.paragraphs``) are
split into the words cut positions index (``anchoring.words``); each word is
folded (``textfold.fold``) into zero or more tokens, which are aligned. Only
tokens in matched runs of ``Params.min_run`` count, as in the text aligner.

**Projection.** A reference unit start (paragraph starts included: editions
divide paragraphs differently) is projected through its first token, or the
first matched token within ``Params.window`` tokens after it, shifted back by
the distance (an OCR-damaged word at the start of a sentence). A start that
lands inside one of the edition's paragraphs, not at its first word, is a cut
there. A paragraph of the edition gets the projected cuts only when at least
``Params.min_cover`` of its tokens are matched; any other paragraph (text only
the edition has: an apparatus, a passage the reference lacks) keeps its
provisional cut (``versify.split_text``), as does every paragraph of an
edition whose texts don't match at all.

The result is a cut per paragraph in the format of ``patristica.anchor_store``
(word positions), so ``scripts.normalize`` applies it like a vector-anchored
cut. No numpy, no vectors, no API calls.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field

from patristica import fingerprint
from patristica.anchoring import Paragraph
from patristica.text_alignment import Params as TextParams
from patristica.text_alignment import align_words, in_runs
from patristica.textfold import fold

#: Bump when a change to the projection should re-cut (cut files made with
#: another version are frozen, like ``anchoring.ANCHOR_VERSION``).
PROJECTION_VERSION = 1


@dataclass(frozen=True)
class Params:
    """Settings of the projection; recorded in every cut file (``method_hash``)."""

    min_run: int = 3  # matched tokens count only in runs of this many (as #199)
    window: int = 3  # tokens after a start searched for a matched one
    min_cover: float = 0.5  # share of a paragraph's tokens matched to take projected cuts
    text: TextParams = field(default_factory=TextParams)

    def to_dict(self) -> dict:
        return asdict(self)


def method_hash(params: Params = Params()) -> str:
    """What a cut file made by projection records as its ``method``."""
    return fingerprint.value_hash({"projection": PROJECTION_VERSION, "params": params.to_dict()})


@dataclass(frozen=True)
class Projection:
    """``starts`` per paragraph of the edition (None: keep the provisional cut)."""

    starts: list[tuple[int, ...] | None]
    stats: dict[str, float | int]


def _tokens(paras: Sequence[Paragraph]) -> tuple[list[str], list[tuple[int, int]],
                                                 dict[tuple[int, int], int]]:
    """Folded tokens, the (paragraph, word) of each, and each word's first token."""
    toks: list[str] = []
    where: list[tuple[int, int]] = []
    first: dict[tuple[int, int], int] = {}
    for pi, p in enumerate(paras):
        for wi, w in enumerate(p.words):
            first[(pi, wi)] = len(toks)
            for t in fold(w).split():
                toks.append(t)
                where.append((pi, wi))
    return toks, where, first


def project(reference: Sequence[Paragraph], edition: Sequence[Paragraph],
            params: Params = Params()) -> Projection:
    """Cut *edition*'s paragraphs where *reference*'s units start."""
    tr, _, first_r = _tokens(reference)
    te, where_e, _ = _tokens(edition)
    pairs = in_runs(align_words(tr, te, params.text), params.min_run)
    to_e = dict(pairs)
    matched_e = [0] * len(edition)
    tokens_e = [0] * len(edition)
    for pi, _ in where_e:
        tokens_e[pi] += 1
    for _, j in pairs:
        matched_e[where_e[j][0]] += 1

    cuts: list[set[int]] = [set() for _ in edition]
    projected = lost = 0
    for pi, p in enumerate(reference):
        for s in p.starts:
            k = first_r.get((pi, s))
            hit = None
            if k is not None:
                for d in range(params.window + 1):
                    if k + d in to_e:
                        hit = to_e[k + d] - d
                        break
            if hit is None or hit < 0:
                lost += 1
                continue
            pe, we = where_e[hit]
            projected += 1
            if we > 0:
                cuts[pe].add(we)

    starts: list[tuple[int, ...] | None] = []
    kept = covered = 0
    for pi, p in enumerate(edition):
        if tokens_e[pi] and matched_e[pi] >= params.min_cover * tokens_e[pi]:
            starts.append((0, *sorted(c for c in cuts[pi] if c < len(p.words))))
            covered += 1
        else:
            starts.append(None)
            kept += 1
    shorter = min(len(tr), len(te))
    stats = {"paragraphs": len(edition), "projected_paragraphs": covered,
             "provisional_paragraphs": kept, "starts_projected": projected,
             "starts_lost": lost,
             "shared": round(len(pairs) / shorter, 4) if shorter else 0.0}
    return Projection(starts, stats)
