"""Print the character inventory of each source in a language.

uv run python -m scripts.ocr_poc.inventory grc sblgnt ogpg ...
"""

from __future__ import annotations

import collections
import sys

from scripts.ocr_poc.corpus import chunks


def main() -> None:
    lang = sys.argv[1]
    for src in sys.argv[2:]:
        c: collections.Counter[str] = collections.Counter()
        n = 0
        for _, t in chunks(src, lang):
            c.update(t)
            n += len(t)
        common = c.most_common()
        print(f"== {src} {lang} chars={n:,} distinct={len(c)}")
        print("  top:", "".join(ch for ch, _ in common[:100]))
        print("  chars covering 99.9%:", sum(1 for _ in _cover(common, n, 0.999)))
        print("  tail (<1e-5):", "".join(ch for ch, k in common if k / n < 1e-5)[:200])


def _cover(common: list[tuple[str, int]], n: int, frac: float):
    acc = 0
    for ch, k in common:
        if acc >= frac * n:
            return
        acc += k
        yield ch


if __name__ == "__main__":
    main()
