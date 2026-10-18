"""Single-error injection: what share of one OCR error of each type each model sees.

    uv run python -m scripts.ocr_poc.synth

Held-out clean reference chunks are split in two: one half fixes the
thresholds (2% flag rate), the other gets exactly one injected error per copy.
"""

from __future__ import annotations

import random
import re
import unicodedata
from collections.abc import Callable

from scripts.ocr_poc.v2 import build

Corruptor = Callable[[str, random.Random], str | None]


def _sub_pairs(pairs: list[tuple[str, str]]) -> Corruptor:
    """Replace one random occurrence of one applicable pair's left side."""

    def f(t: str, rng: random.Random) -> str | None:
        opts = [(m.start(), a, b) for a, b in pairs for m in re.finditer(re.escape(a), t)]
        # Only inside words, so the error is not at a chunk edge.
        opts = [(i, a, b) for i, a, b in opts if 0 < i and i + len(a) < len(t)]
        if not opts:
            return None
        i, a, b = rng.choice(opts)
        return t[:i] + b + t[i + len(a) :]

    return f


def _split(t: str, rng: random.Random) -> str | None:
    words = [m for m in re.finditer(r"\w{6,}", t)]
    if not words:
        return None
    m = rng.choice(words)
    k = rng.randrange(m.start() + 2, m.end() - 2)
    return t[:k] + " " + t[k:]


def _join(t: str, rng: random.Random) -> str | None:
    spaces = [m.start() for m in re.finditer(r"(?<=\w) (?=\w)", t)]
    if not spaces:
        return None
    k = rng.choice(spaces)
    return t[:k] + t[k + 1 :]


def _hyphenate(t: str, rng: random.Random) -> str | None:
    words = [m for m in re.finditer(r"\w{6,}", t)]
    if not words:
        return None
    m = rng.choice(words)
    k = rng.randrange(m.start() + 2, m.end() - 2)
    return t[:k] + "- " + t[k:]


def _greek_accent(kind: str) -> Corruptor:
    """Accent/breathing errors seen in the OGPG OCR."""

    def f(t: str, rng: random.Random) -> str | None:
        words = [m for m in re.finditer(r"[Ͱ-Ͽἀ-῿]{2,}", t)]
        rng.shuffle(words)
        for m in words:
            w = unicodedata.normalize("NFD", m.group())
            if kind == "drop_breathing" and ("̓" in w[:3] or "̔" in w[:3]):
                w2 = w.replace("̓", "", 1).replace("̔", "", 1)
            elif kind == "swap_breathing" and ("̓" in w[:3] or "̔" in w[:3]):
                w2 = w.translate({0x313: 0x314, 0x314: 0x313})
            elif kind == "acute_grave" and ("́" in w or "̀" in w):
                w2 = w.translate({0x301: 0x300, 0x300: 0x301})
            elif kind == "drop_accent" and any(c in w for c in "́̀͂"):
                w2 = re.sub("[́̀͂]", "", w, count=1)
            elif kind == "smooth_to_grave" and "̓" in w[:3]:
                # ἐν → ὲν: the breathing read as a grave.
                w2 = re.sub("̓́?|̓", "̀", w, count=1)
            else:
                continue
            w2 = unicodedata.normalize("NFC", w2)
            if w2 != m.group():
                return t[: m.start()] + w2 + t[m.end() :]
        return None

    return f


ERRORS: dict[str, dict[str, Corruptor]] = {
    "grc": {
        "X: Latin look-alike (ο→o, ι→i, ν→v, α→a, κ→k)": _sub_pairs(
            [("ο", "o"), ("ι", "i"), ("ν", "v"), ("α", "a"), ("κ", "k"), ("τ", "t")]
        ),
        "X: digit/junk (ὁ→6, ο→0, ι→1, ’→')": _sub_pairs(
            [(" ὁ ", " 6 "), ("ο", "0"), ("ι", "1"), ("ε", "€"), ("·", "*")]
        ),
        "L: letter confusion (ο→σ, ν↔υ, β→δ, ὸ→δ, ε→ς, ρ→ς, η→ῃ)": _sub_pairs(
            [
                ("ο", "σ"),
                ("ν", "υ"),
                ("υ", "ν"),
                ("β", "δ"),
                ("ὸ", "δ"),
                ("ε", "ς"),
                ("η", "ῃ"),
                ("ρ", "ς"),
            ]
        ),
        "A: drop initial breathing (εἰς→είς)": _greek_accent("drop_breathing"),
        "A: smooth breathing read as grave (ἐν→ὲν)": _greek_accent("smooth_to_grave"),
        "A: swap breathing (αὐτοῦ→αὑτοῦ)": _greek_accent("swap_breathing"),
        "A: acute↔grave (γὰρ→γάρ)": _greek_accent("acute_grave"),
        "A: drop accent (λοιπὸν→λοιπον)": _greek_accent("drop_accent"),
        "S: split word": _split,
        "S: hyphen split (ἀριθμουμ- νη)": _hyphenate,
        "S: join words": _join,
    },
    "lat": {
        "X: digit/junk (i→1, l→|, e→©, s→$)": _sub_pairs(
            [("i", "1"), ("l", "|"), ("e", "©"), ("s", "$"), ("t", "†")]
        ),
        "L: c↔e": _sub_pairs([("c", "e"), ("e", "c")]),
        "L: n↔u": _sub_pairs([("n", "u"), ("u", "n")]),
        "L: rn↔m, cl↔d, li↔h": _sub_pairs(
            [("rn", "m"), ("m", "rn"), ("d", "cl"), ("h", "li"), ("li", "h")]
        ),
        "L: h↔b, i↔l, t↔l, f↔s (long s)": _sub_pairs(
            [("h", "b"), ("b", "h"), ("i", "l"), ("l", "i"), ("t", "l"), ("s", "f")]
        ),
        "L: æ→x / œ→oe, a→o": _sub_pairs([("æ", "x"), ("ae", "x"), ("a", "o"), ("o", "a")]),
        "L: case (tempus→tempUs)": _sub_pairs([("u", "U"), ("m", "M"), ("e", "E")]),
        "S: split word": _split,
        "S: hyphen split (assumptio- nem)": _hyphenate,
        "S: join words": _join,
    },
}


def main() -> None:
    rng = random.Random(7)
    for lang in ("grc", "lat"):
        det = build(lang)
        scorers, th = det.scorers, det.thresholds
        test = rng.sample(det.test, min(1500, len(det.test)))
        base = {k: [f(t) > th[k] for t in test] for k, f in scorers.items()}

        print(f"\n## {lang}: {len(test)} test chunks")
        names = list(scorers) + ["uni|bi", "uni|tri"]
        print("error type".ljust(62) + "n".rjust(6) + "".join(n.rjust(16) for n in names))
        fp = {k: sum(v) / len(v) for k, v in base.items()}
        print(
            "(uncorrupted: flag rate)".ljust(62)
            + str(len(test)).rjust(6)
            + "".join(f"{fp[n]:16.1%}" if n in fp else " " * 16 for n in names)
        )
        for etype, corrupt in ERRORS[lang].items():
            # Only count a detection the error caused: the clean copy must be unflagged.
            hits = {n: 0 for n in names}
            n = 0
            for i, t in enumerate(test):
                if any(base[k][i] for k in scorers):
                    continue
                c = corrupt(t, rng)
                if c is None or c == t:
                    continue
                n += 1
                fl = {k: f(c) > th[k] for k, f in scorers.items()}
                fl["uni|bi"] = fl["unigram"] or fl["bigram"]
                fl["uni|tri"] = fl["unigram"] or fl["trigram"]
                for k in names:
                    hits[k] += fl[k]
            print(
                etype[:61].ljust(62)
                + str(n).rjust(6)
                + "".join(f"{hits[k] / n:16.1%}" if n else " " * 16 for k in names)
            )


if __name__ == "__main__":
    main()
