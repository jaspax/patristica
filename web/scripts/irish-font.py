"""Build the self-hosted Old Irish fallback font in src/app/fonts/ (#544).

Old Irish is Latin script and uses the body font, Noto Serif, which Google
serves in unicode-range slices. The "latin" and "latin-ext" slices cover the
length marks and the precomposed punctum delens (ḟ ṡ ṁ ṅ, U+1E00-1EFF), but
not the editions' other signs: the Tironian et ⁊ (U+204A, missing from the
latin slice although its range lists it), the reversed c ↄ (U+2184, in no
slice) and the combining dot above U+0307 (only in the "math" slice, which we
don't load because its range also claims the Greek letters). Chromium shapes a
letter and its combining marks with one file, so a letter + U+0307 found no
file with both and fell back to another font (cf. #371).

This is Noto Serif's regular instance cut to Latin with its combining marks,
punctuation, letterlike symbols, number forms and the insular letters of
Latin Extended-D, in one file. globals.css puts it after Noto Serif for
:lang(sga), so ordinary text keeps the body font with its weights and only
what the slices can't draw falls back here, a cluster whole.

Noto Serif is OFL 1.1 with no Reserved Font Name (src/app/fonts/
NotoSerif-OFL.txt), pinned to the google/fonts commit slavonic-fonts.py uses.
Run from the repo root:

    uv run --with fonttools --with brotli python -I web/scripts/irish-font.py
"""

import io
import pathlib
import urllib.request

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

COMMIT = "6157dfaa640ca5738b4d1a7070fe389c3036d7fc"
URL = f"https://raw.githubusercontent.com/google/fonts/{COMMIT}/ofl/notoserif/NotoSerif%5Bwdth%2Cwght%5D.ttf"
OUT = pathlib.Path(__file__).resolve().parent.parent / "src" / "app" / "fonts" / "NotoSerif-Irish.woff2"

RANGES = [
    (0x0000, 0x00FF),  # Basic Latin, Latin-1
    (0x0100, 0x02FF),  # Latin Extended-A/B, IPA (ɫ), spacing modifiers
    (0x0300, 0x036F),  # combining diacritics (U+0307 dot above)
    (0x1DC0, 0x1DFF),  # combining diacritics supplement
    (0x1E00, 0x1EFF),  # Latin Extended Additional (ḟ ṡ ṁ ṅ)
    (0x2000, 0x206F),  # general punctuation (⁊)
    (0x2100, 0x218F),  # letterlike symbols, number forms (ↄ)
    (0x2C60, 0x2C7F),  # Latin Extended-C
    (0xA720, 0xA7FF),  # Latin Extended-D (insular letters)
]


def main() -> None:
    with urllib.request.urlopen(URL) as r:
        font = TTFont(io.BytesIO(r.read()))
    font = instancer.instantiateVariableFont(font, {"wght": 400, "wdth": 100})
    options = subset.Options()
    options.layout_features = ["*"]
    options.flavor = "woff2"
    options.name_IDs = ["*"]
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=[c for a, b in RANGES for c in range(a, b + 1)])
    subsetter.subset(font)
    font.flavor = "woff2"
    font.save(OUT)


if __name__ == "__main__":
    main()
