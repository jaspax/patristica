"""Build the v2 detector (prep() input, script-aware unigram, bigram, trigram).

Held-out clean reference chunks are split in two: one half fixes the
thresholds (FLAG_RATE flagged), the other is left for testing.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from scripts.ocr_poc.corpus import chunks
from scripts.ocr_poc.models import AccentLexicon, CharNgram, ScriptUnigram, prep
from scripts.ocr_poc.score_sample import FLAG_RATE, REFERENCE, heldout, quantile


@dataclass
class Detector:
    scorers: dict[str, Callable[[str], float]]
    thresholds: dict[str, float]
    test: list[str]  # held-out clean chunks not used for thresholds

    def flags(self, text: str) -> dict[str, bool]:
        return {k: f(text) > self.thresholds[k] for k, f in self.scorers.items()}


def _half(cid: str) -> bool:
    return hashlib.md5(("x" + cid).encode()).digest()[0] < 128


def build(lang: str, accent_lexicon: bool = True) -> Detector:
    train, calib, test = [], [], []
    for src in REFERENCE[lang]:
        for cid, t in chunks(src, lang):
            if not heldout(cid):
                train.append(t)
            elif len(t) >= 40:
                (calib if _half(cid) else test).append(t)
    train_p = [prep(t, lang) for t in train]
    uni, bi, tri = ScriptUnigram(train_p, lang), CharNgram(train_p, 2), CharNgram(train_p, 3)
    scorers: dict[str, Callable[[str], float]] = {
        "unigram": lambda t: uni.score(prep(t, lang)),
        "bigram": lambda t: bi.score(prep(t, lang)),
        "trigram": lambda t: tri.score(prep(t, lang)),
    }
    if lang == "grc" and accent_lexicon:
        scorers["accent_lexicon"] = AccentLexicon(train).score
    th = {k: quantile([f(t) for t in calib], 1 - FLAG_RATE) for k, f in scorers.items()}
    return Detector(scorers, th, test)
