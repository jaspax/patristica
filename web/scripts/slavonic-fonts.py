"""Build the self-hosted Church Slavonic fonts in src/app/fonts/ (#371).

Google Fonts serves Monomakh in unicode-range slices: the Cyrillic letters
(U+0400-045F) in one file, the superscript letters (U+2DE0-2DFF, U+A674-A69F)
in another, and the inverted breve and dotted punctuation in none. Chromium
shapes a letter and its combining marks with one file, so к + ⷰ + ҇ found no
file with all three and rendered as tofu. The full font has every glyph, so we
serve it whole, and back it with one Noto Serif file that covers Cyrillic and
its combining marks together, for clusters Monomakh can't draw.

Both fonts are OFL 1.1 with no Reserved Font Name, pinned to a google/fonts
commit. Monomakh is only converted to WOFF2; Noto Serif is fixed at its
regular instance and subset. Run from the repo root:

    uv run --with fonttools --with brotli python -I web/scripts/slavonic-fonts.py
"""

import io
import pathlib
import urllib.request

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

COMMIT = "6157dfaa640ca5738b4d1a7070fe389c3036d7fc"
BASE = f"https://raw.githubusercontent.com/google/fonts/{COMMIT}/ofl"
OUT = pathlib.Path(__file__).resolve().parent.parent / "src" / "app" / "fonts"

# What the Noto Serif fallback keeps: Cyrillic with every combining mark the
# sources use, and the punctuation blocks, so a cluster stays in one file.
FALLBACK_RANGES = [
    (0x0000, 0x00FF),
    (0x0300, 0x036F),
    (0x0400, 0x052F),
    (0x1C80, 0x1C8F),
    (0x1DC0, 0x1DFF),
    (0x2000, 0x206F),
    (0x2DE0, 0x2DFF),
    (0x2E00, 0x2E7F),
    (0xA640, 0xA69F),
    (0xFE20, 0xFE2F),
]


def fetch(path: str) -> bytes:
    with urllib.request.urlopen(f"{BASE}/{path}") as r:
        return r.read()


def main() -> None:
    OUT.mkdir(exist_ok=True)

    mono = TTFont(io.BytesIO(fetch("monomakh/Monomakh-Regular.ttf")))
    mono.flavor = "woff2"
    mono.save(OUT / "Monomakh-Regular.woff2")
    (OUT / "Monomakh-OFL.txt").write_bytes(fetch("monomakh/OFL.txt"))

    serif = TTFont(io.BytesIO(fetch("notoserif/NotoSerif%5Bwdth%2Cwght%5D.ttf")))
    serif = instancer.instantiateVariableFont(serif, {"wght": 400, "wdth": 100})
    options = subset.Options()
    options.layout_features = ["*"]
    options.flavor = "woff2"
    options.name_IDs = ["*"]
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=[c for a, b in FALLBACK_RANGES for c in range(a, b + 1)])
    subsetter.subset(serif)
    serif.flavor = "woff2"
    serif.save(OUT / "NotoSerif-Slavonic.woff2")
    (OUT / "NotoSerif-OFL.txt").write_bytes(fetch("notoserif/OFL.txt"))


if __name__ == "__main__":
    main()
