"""Share of each source's chunks the v2 detector flags (a 10% sample per source).

uv run python -m scripts.ocr_poc.flagrate
"""

from __future__ import annotations

import random

from scripts.ocr_poc.corpus import chunks
from scripts.ocr_poc.score_sample import EVERYTHING
from scripts.ocr_poc.v2 import build

COMBOS = {"uni": ("unigram",), "uni|bi": ("unigram", "bigram"), "uni|tri": ("unigram", "trigram")}


def main() -> None:
    rng = random.Random(3)
    print(
        "source".ljust(22)
        + "lang".ljust(6)
        + "chunks".rjust(10)
        + "<20ch".rjust(8)
        + "".join(k.rjust(10) for k in COMBOS)
    )
    for lang in ("grc", "lat"):
        det = build(lang, accent_lexicon=False)
        for src in EVERYTHING[lang]:
            n = short = 0
            hits = dict.fromkeys(COMBOS, 0)
            for _, t in chunks(src, lang):
                if rng.random() >= 0.1:
                    continue
                if len(t) < 20:
                    short += 1
                    continue
                n += 1
                fl = det.flags(t)
                for k, parts in COMBOS.items():
                    hits[k] += any(fl[p] for p in parts)
            if n:
                print(
                    src.ljust(22)
                    + lang.ljust(6)
                    + str(n * 10).rjust(10)
                    + f"{short / (n + short):8.1%}"
                    + "".join(f"{hits[k] / n:10.1%}" for k in COMBOS)
                )


if __name__ == "__main__":
    main()
