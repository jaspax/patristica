"""Draw the random chunk sample that is hand-labelled for the PoC.

    uv run python -m scripts.ocr_poc.sample OUT.jsonl

Chunks are sampled uniformly within each (source, language) stratum, at least
20 characters long, and written in shuffled order without scores.
"""

from __future__ import annotations

import json
import random
import sys

from scripts.ocr_poc.corpus import chunks

STRATA: dict[tuple[str, str], int] = {
    ("ogpg", "grc"): 120,
    ("first1k", "grc"): 30,
    ("typikon", "grc"): 20,
    ("pta", "grc"): 15,
    ("perseus", "grc"): 15,
    ("oglt-pl", "lat"): 120,
    ("mozarabic", "lat"): 20,
    ("gallican", "lat"): 20,
    ("clementine", "lat"): 10,
    ("perseus", "lat"): 10,
    ("cursus", "lat"): 10,
}


def main() -> None:
    rng = random.Random(20261018)
    out = []
    for (src, lang), n in STRATA.items():
        # Reservoir sampling keeps memory flat on the 700 MB sources.
        res: list[tuple[str, str]] = []
        seen = 0
        for cid, text in chunks(src, lang):
            if len(text) < 20:
                continue
            seen += 1
            if len(res) < n:
                res.append((cid, text))
            else:
                j = rng.randrange(seen)
                if j < n:
                    res[j] = (cid, text)
        out += [{"chunk_id": c, "source": src, "language": lang, "text": t} for c, t in res]
    rng.shuffle(out)
    with open(sys.argv[1], "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
