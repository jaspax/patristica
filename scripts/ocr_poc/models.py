"""Character n-gram and word-lexicon scorers for flagging OCR-damaged chunks.

Every scorer maps a chunk's text to a number where *higher means more
suspicious*, and can explain which spans drove the score.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable

from patristica.textfold import fold

# Space before closing punctuation / after opening brackets is a typographic
# convention (French-style Migne), not a property of the text.
_SPACE_BEFORE = re.compile(r" +([:;?!·.,»)\]])")
_SPACE_AFTER = re.compile(r"([«(\[]) +")


def typo(text: str) -> str:
    """Normalize typographic spacing so editions with different conventions compare."""
    return _SPACE_AFTER.sub(r"\1", _SPACE_BEFORE.sub(r"\1", text))


# Well-formed editorial apparatus that the reference editions lack: footnote
# markers "(58)" / "(b)", and in Latin free-standing numbers and Roman
# numerals (Bible citations, paragraph numbers). Digits glued to letters
# ("magni1") and lone digits inside Greek ("6 τὴν" for ὁ) are left alone.
_FOOTNOTE = re.compile(r"\((?:\d{1,3}|[a-z])\)")
_ROMAN = r"M{0,3}(?:CM|CD|D?C{0,3})(?:XC|XL|L?X{0,3})(?:IX|IV|V?I{0,3})"
_LAT_NUMBER = re.compile(
    rf"(?<!\w)(?:\d+|(?=[IVXLCDM]){_ROMAN}|(?=[ivxlcdm])(?i:{_ROMAN})(?=[.,;)]))(?!\w)"
)


def prep(text: str, lang: str) -> str:
    """typo() + mask legitimate apparatus + casefold: the v2 model input."""
    t = _FOOTNOTE.sub("", typo(text))
    if lang == "lat":
        t = _LAT_NUMBER.sub("0", t)
    return " ".join(_fold_case(t).split())


def _fold_case(text: str) -> str:
    # casefold() decomposes some polytonic letters (ῶ → ω + U+0342); recompose.
    return unicodedata.normalize("NFC", text.casefold())


SCRIPT = {"grc": "GREEK", "lat": "LATIN"}


def foreign(ch: str, lang: str) -> bool:
    """A letter from another script, or (in Greek) a digit."""
    if ch.isdigit():
        return lang == "grc"
    if not ch.isalpha():
        return False
    return not unicodedata.name(ch, "").startswith(SCRIPT[lang])


def _pad(text: str) -> str:
    # One boundary space on each side so word-initial/final bigrams count.
    return " " + _fold_case(text) + " "


class Unigram:
    """Per-character probabilities; score = surprisal of the rarest character."""

    def __init__(self, texts: Iterable[str], alpha: float = 0.5) -> None:
        self.counts: Counter[str] = Counter()
        for t in texts:
            self.counts.update(t)
        self.n = sum(self.counts.values())
        self.alpha = alpha
        # Reserve mass for one unseen symbol class.
        self.v = len(self.counts) + 1

    def logp(self, ch: str) -> float:
        return math.log10((self.counts.get(ch, 0) + self.alpha) / (self.n + self.alpha * self.v))

    def surprisals(self, text: str) -> list[float]:
        return [-self.logp(c) for c in text]

    def score(self, text: str) -> float:
        return max(self.surprisals(text), default=0.0)

    def explain(self, text: str, thresh: float) -> list[str]:
        return sorted({c for c in text if -self.logp(c) > thresh})


class ScriptUnigram(Unigram):
    """Unigram that treats letters of another script as unseen, however common."""

    def __init__(self, texts: Iterable[str], lang: str, alpha: float = 0.5) -> None:
        super().__init__(texts, alpha)
        self.lang = lang

    def logp(self, ch: str) -> float:
        if foreign(ch, self.lang):
            return math.log10(self.alpha / (self.n + self.alpha * self.v))
        return super().logp(ch)


class CharNgram:
    """Casefolded order-n model, interpolated (Witten–Bell) down to a unigram.

    Scores are on the conditional surprisal of each character given the
    previous n-1, so a common character in an impossible context scores high.
    """

    def __init__(self, texts: Iterable[str], n: int = 2) -> None:
        self.n = n
        self.ctx: list[Counter[str]] = [
            Counter() for _ in range(n)
        ]  # ctx[k]: counts of k-char contexts
        self.ngr: list[Counter[str]] = [
            Counter() for _ in range(n)
        ]  # ngr[k]: counts of (k+1)-grams
        self.types: list[Counter[str]] = [
            Counter() for _ in range(n)
        ]  # distinct continuations per context
        for t in texts:
            s = _pad(t)
            for k in range(n):
                g = self.ngr[k]
                for i in range(len(s) - k):
                    g[s[i : i + k + 1]] += 1
        for k in range(n):
            for gram, c in self.ngr[k].items():
                self.ctx[k][gram[:-1]] += c
                self.types[k][gram[:-1]] += 1
        self.v = len(self.ngr[0]) + 1

    def prob(self, hist: str, ch: str) -> float:
        p = (self.ngr[0].get(ch, 0) + 0.5) / (self.ctx[0][""] + 0.5 * self.v)
        for k in range(1, self.n):
            h = hist[-k:]
            if len(h) < k:
                break
            c_h = self.ctx[k].get(h, 0)
            if not c_h:
                continue
            t_h = self.types[k][h]
            lam = c_h / (c_h + t_h)
            p = lam * self.ngr[k].get(h + ch, 0) / c_h + (1 - lam) * p
        return p

    def surprisals(self, text: str) -> list[float]:
        s = _pad(text)
        k = self.n - 1
        return [-math.log10(self.prob(s[max(0, i - k) : i], s[i])) for i in range(1, len(s))]

    def score(self, text: str) -> float:
        """Surprisal of the least likely character-in-context."""
        return max(self.surprisals(text), default=0.0)

    def mean_score(self, text: str) -> float:
        """Mean surprisal per character (log10 perplexity)."""
        s = self.surprisals(text)
        return sum(s) / len(s) if s else 0.0

    def explain(self, text: str, thresh: float) -> list[str]:
        s = _pad(text)
        sur = self.surprisals(text)
        k = self.n - 1
        return [s[max(0, i - k) : i + 1] for i, x in zip(range(1, len(s)), sur) if x > thresh]


_WORD = re.compile(r"\w+")


class Lexicon:
    """Folded word list; score = share of word tokens (≥3 letters) not in it."""

    def __init__(self, texts: Iterable[str], min_count: int = 2) -> None:
        c: Counter[str] = Counter()
        for t in texts:
            c.update(fold(t).split())
        self.words = {w for w, k in c.items() if k >= min_count}

    def tokens(self, text: str) -> list[str]:
        return [w for w in fold(text).split() if len(w) >= 3 and not w.isdigit()]

    def score(self, text: str) -> float:
        toks = self.tokens(text)
        if not toks:
            return 0.0
        return sum(w not in self.words for w in toks) / len(toks)

    def explain(self, text: str, thresh: float = 0.0) -> list[str]:
        return [w for w in self.tokens(text) if w not in self.words]


_GRAVE = 0x0300
_ACUTE = 0x0301


def accent_key(word: str) -> str:
    """Lowercase polytonic word with grave folded to acute (graves are positional)."""
    d = unicodedata.normalize("NFD", word.casefold())
    d = d.replace(chr(_GRAVE), chr(_ACUTE))
    return unicodedata.normalize("NFC", d)


_GREEK_WORD = re.compile(r"[Ͱ-Ͽἀ-῿̀-ͯ]+")


class AccentLexicon:
    """Greek word list that keeps accents and breathings; score = OOV share."""

    def __init__(self, texts: Iterable[str], min_count: int = 2) -> None:
        c: Counter[str] = Counter()
        for t in texts:
            c.update(accent_key(w) for w in _GREEK_WORD.findall(t))
        self.words = {w for w, k in c.items() if k >= min_count}

    def tokens(self, text: str) -> list[str]:
        return [accent_key(w) for w in _GREEK_WORD.findall(text) if len(w) >= 2]

    def score(self, text: str) -> float:
        toks = self.tokens(text)
        if not toks:
            return 0.0
        return sum(w not in self.words for w in toks) / len(toks)

    def explain(self, text: str, thresh: float = 0.0) -> list[str]:
        return [w for w in self.tokens(text) if w not in self.words]
