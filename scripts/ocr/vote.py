"""Word-level vote across transcriptions of one page, and deterministic repairs."""

from __future__ import annotations

import unicodedata
from collections import Counter

from rapidfuzz.distance import Levenshtein

from scripts.ocr.eval.metrics import clean, strip_marks
from scripts.ocr.text import norm


def _key(tok: str) -> str:
    return clean(tok, conventions=True)


def vote(primary: str, others: list[str]) -> str:
    """The primary transcription with each word replaced by the majority reading.

    Words are compared by their convention-folded form; a voter votes for a
    word where its alignment to the primary is a same-length substitution or
    an exact match. The primary wins ties. Line breaks are the primary's.
    """
    lines = [norm(x).split() for x in primary.splitlines()]
    flat = [t for ln in lines for t in ln]
    keys = [_key(t) for t in flat]
    votes = [Counter({k: 1.01}) for k in keys]
    raw: list[dict[str, str]] = [{k: t} for k, t in zip(keys, flat)]
    for other in others:
        toks = norm(" ".join(other.splitlines())).split()
        okeys = [_key(t) for t in toks]
        for op in Levenshtein.opcodes(keys, okeys):
            if op.tag == "equal":
                for k in range(op.src_start, op.src_end):
                    votes[k][keys[k]] += 1
            elif op.tag == "replace" and op.src_end - op.src_start == op.dest_end - op.dest_start:
                for k, j in zip(range(op.src_start, op.src_end), range(op.dest_start, op.dest_end)):
                    votes[k][okeys[j]] += 1
                    raw[k].setdefault(okeys[j], toks[j])
    chosen = [raw[k][votes[k].most_common(1)[0][0]] for k in range(len(flat))]
    out, i = [], 0
    for ln in lines:
        out.append(" ".join(chosen[i:i + len(ln)]))
        i += len(ln)
    return "\n".join(out)


_THEOS = {"θεος", "θεου", "θεω", "θεον", "θεε"}


def capitalize_theos(text: str) -> str:
    """Migne capitalizes the singular forms of Θεός (377 of 396 in the eval set)."""
    def fix(tok: str) -> str:
        core = "".join(c for c in tok if c.isalpha() or unicodedata.category(c) == "Mn")
        if core and core[0] == "θ" and strip_marks(core).lower() in _THEOS:
            i = tok.index("θ")
            return tok[:i] + "Θ" + tok[i + 1:]
        return tok
    return "\n".join(" ".join(fix(t) for t in ln.split(" ")) for ln in text.split("\n"))
