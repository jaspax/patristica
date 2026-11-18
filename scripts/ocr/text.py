"""Text helpers shared by the OCR stages: normalization, line pairing, comparison."""

from __future__ import annotations

import re
import unicodedata

from rapidfuzz.distance import Levenshtein

from scripts.ocr.eval.metrics import clean

# Notation differences only, never readings: apostrophe and hyphen variants,
# and the space Migne prints before punctuation.
_UNIFY = str.maketrans({**{c: "’" for c in "'´ʼ᾽‘`′ʹʹ"}, **{c: "-" for c in "‐‑‒"}})
_SPACE_PUNCT = re.compile(r"\s+(?=[,·;:.])")
_WS = re.compile(r"\s+")


def norm(s: str) -> str:
    """NFC, unified apostrophes/hyphens, no space before punctuation, single spaces."""
    s = unicodedata.normalize("NFC", s).translate(_UNIFY)
    return _WS.sub(" ", _SPACE_PUNCT.sub("", s)).strip()


def same_reading(a: str, b: str) -> bool:
    """True if two readings differ at most in transcription conventions."""
    return clean(a, conventions=True) == clean(b, conventions=True)


def pair_lines(a: list[str], b: list[str],
               min_sim: float = 0.5) -> list[tuple[int | None, int | None]]:
    """Monotonic alignment of two line lists by text similarity."""
    n, m = len(a), len(b)
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    back = [[""] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        back[i][0] = "a"
    for j in range(1, m + 1):
        back[0][j] = "b"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            sim = Levenshtein.normalized_similarity(a[i - 1], b[j - 1])
            best, step = score[i - 1][j], "a"
            if score[i][j - 1] > best:
                best, step = score[i][j - 1], "b"
            if sim >= min_sim and score[i - 1][j - 1] + sim > best:
                best, step = score[i - 1][j - 1] + sim, "ab"
            score[i][j], back[i][j] = best, step
    pairs: list[tuple[int | None, int | None]] = []
    i, j = n, m
    while i or j:
        step = back[i][j]
        if step == "ab":
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif step == "a":
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    return pairs[::-1]


def lines_of(text: str) -> list[str]:
    """A transcription's non-empty normalized lines."""
    return [x for x in (norm(y) for y in text.splitlines()) if x]
