"""Build the self-hosted Runic font in src/app/fonts/ (#564).

The ASPR Old English poems print runes as Unicode futhorc (U+16A0-16FF):
Cynewulf's signatures, the Rune Poem, Solomon and Saturn. Neither Noto Serif
nor the medieval fallback (medieval-font.py) has them. This is Noto Sans
Runic cut to the Runic block. globals.css puts it after the medieval fallback
for :lang(ang) and the other medieval Latin-script languages.

It is self-hosted rather than loaded with next/font/google because that
loader adds a metric-adjusted local(Arial) face ("Noto Sans Runic Fallback")
to the font's CSS variable even with adjustFontFallback: false, and in the
:lang() stack that Arial would sit ahead of the body font's script fonts.

Noto Sans Runic is OFL 1.1 with no Reserved Font Name (src/app/fonts/
NotoSansRunic-OFL.txt), pinned to the google/fonts commit the other scripts
use. Run from the repo root:

    uv run --with fonttools --with brotli python -I web/scripts/runic-font.py
"""

import io
import pathlib
import urllib.request

from fontTools import subset
from fontTools.ttLib import TTFont

COMMIT = "6157dfaa640ca5738b4d1a7070fe389c3036d7fc"
URL = f"https://raw.githubusercontent.com/google/fonts/{COMMIT}/ofl/notosansrunic/NotoSansRunic-Regular.ttf"
OUT = pathlib.Path(__file__).resolve().parent.parent / "src" / "app" / "fonts" / "NotoSansRunic-Runes.woff2"


def main() -> None:
    with urllib.request.urlopen(URL) as r:
        font = TTFont(io.BytesIO(r.read()))
    options = subset.Options()
    options.layout_features = ["*"]
    options.flavor = "woff2"
    options.name_IDs = ["*"]
    subsetter = subset.Subsetter(options)
    subsetter.populate(unicodes=range(0x16A0, 0x1700))
    subsetter.subset(font)
    font.flavor = "woff2"
    font.save(OUT)


if __name__ == "__main__":
    main()
