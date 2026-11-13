"""Build the self-hosted fallback font for Literary Chinese (#649).

Literary Chinese (:lang(lzh)) is set in Noto Serif TC, which next/font/google
self-hosts in Google's unicode-range slices (fonts.ts). Noto Serif TC covers
the URO and the characters Taiwan and Hong Kong use, but not every character
the sources print: the Taishō Tripiṭaka (CBETA) has supplementary-plane
variants (𭨝 U+2DA1D, 𮊵 U+2E2B5, …) and zh.wikisource Ext-A ones (䫟), and
Japanese and simplified forms (将 来 浄). Google's slices also leave out
characters the font has but its slicing plan doesn't list (厏 U+538F on the
stele), so "has" here means: in the font's cmap and in a slice's
unicode-range (Google's CSS is fetched on every run).

This script collects every code point the Chinese sources use, keeps those
Noto Serif TC as served lacks, and cuts them from Jigmo (Kamichi Koichi, after
GlyphWiki; CC0 1.0, src/app/fonts/Jigmo-LICENSE.txt), which covers all of
CJK Unified Ideographs and Extensions A–I. The result is one small WOFF2,
src/app/fonts/Jigmo-Chinese.woff2, after Noto Serif TC in the :lang(lzh)
stack (globals.css), and the list of its characters,
src/app/fonts/Jigmo-Chinese.txt, so a change of coverage shows in review.

Sources (cached under --cache, fetched once):
- zh.wikisource: the Jingjiao texts (#650), through the MediaWiki API
  (action=parse&prop=wikitext), 2 s apart, backing off on rate limits;
- CBETA XML P5 (#651): T54n2142–2144, the Taishō's Manichaean and Jingjiao
  texts; <g ref> characters are resolved through the file's charDecl.
- The raw data of the ingested Chinese sources, when it is materialized
  (data/raw/wikisource-lzh, data/raw/cbeta): every "text" of every unit.

Re-run it when a Chinese source is added or re-ingested (add its pages here),
then commit the two files. Run from the repo root:

    uv run --with fonttools --with brotli python -I web/scripts/chinese-font.py
"""

import argparse
import io
import json
import os
import pathlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from fontTools import subset
from fontTools.merge import Merger
from fontTools.ttLib import TTFont

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
OUT = REPO / "web" / "src" / "app" / "fonts"

USER_AGENT = "PatristicaFontBuilder/1.0 (https://patristica.app; font coverage check)"

# Noto Serif TC as the google/fonts repo has it (the pinned commit of slavonic-fonts.py).
NOTO_TC = (
    "https://raw.githubusercontent.com/google/fonts/6157dfaa640ca5738b4d1a7070fe389c3036d7fc"
    "/ofl/notoseriftc/NotoSerifTC%5Bwght%5D.ttf"
)
# The CSS next/font/google reads (fonts.ts: Noto_Serif_TC, weight "variable").
GOOGLE_CSS = "https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@200..900&display=swap"
JIGMO ="https://kamichikoichi.github.io/jigmo/Jigmo-20250912.zip"

WIKISOURCE_API = "https://zh.wikisource.org/w/api.php"
WIKISOURCE_PAGES = [
    "大秦景教流行中國碑頌",
    "景教三威蒙度讚",
    "尊經",
    "序聽迷詩所經",
    "志玄安樂經",
    "大秦景教宣元至本經",
]
CBETA = "https://raw.githubusercontent.com/cbeta-org/xml-p5/master/T/T54/T54n{n}.xml"
CBETA_TEXTS = ["2142", "2143", "2144"]

# Raw data of the Chinese sources, read when present (not LFS pointers).
RAW_SOURCES = ["wikisource-lzh", "cbeta"]

# Han characters and the ideographic description characters (an unencoded
# character may be spelled as an IDS); everything else is the body fonts' job.
HAN_RANGES = [
    (0x2E80, 0x2FFF),  # radicals, Kangxi radicals, IDCs
    (0x3000, 0x303F),  # CJK symbols and punctuation
    (0x31C0, 0x31EF),  # strokes
    (0x3400, 0x4DBF),  # Ext A
    (0x4E00, 0x9FFF),  # URO
    (0xF900, 0xFAFF),  # compatibility ideographs
    (0xFF00, 0xFFEF),  # fullwidth forms
    (0x20000, 0x323AF),  # Ext B–H, compatibility supplement
    (0x2EBF0, 0x2EE5F),  # Ext I
]

_last_request = 0.0


def fetch(url: str, cache: pathlib.Path, *, polite: bool = False) -> bytes:
    """GET a URL once, caching the body; polite requests are 2 s apart and back off on 429/503."""
    global _last_request
    if cache.exists():
        return cache.read_bytes()
    delay = 2.0
    for _ in range(6):
        if polite:
            time.sleep(max(0.0, _last_request + 2.0 - time.monotonic()))
        _last_request = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                retry = e.headers.get("Retry-After")
                time.sleep(float(retry) if retry and retry.isdigit() else delay)
                delay *= 2
                continue
            raise
        if b"ratelimited" in body[:500]:
            time.sleep(delay)
            delay *= 2
            continue
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(body)
        return body
    raise RuntimeError(f"rate limited too often: {url}")


def wikisource_text(page: str, cache: pathlib.Path) -> str:
    query = urllib.parse.urlencode(
        {"action": "parse", "page": page, "prop": "wikitext", "redirects": 1, "format": "json", "formatversion": 2}
    )
    data = json.loads(fetch(f"{WIKISOURCE_API}?{query}", cache / "wikisource" / f"{page}.json", polite=True))
    if "error" in data:
        raise RuntimeError(f"zh.wikisource {page}: {data['error'].get('info')}")
    return data["parse"]["wikitext"]


def cbeta_text(n: str, cache: pathlib.Path) -> str:
    """The file's text plus every Unicode form its charDecl gives a <g> character."""
    xml = fetch(CBETA.format(n=n), cache / "cbeta" / f"T54n{n}.xml").decode("utf-8")
    mapped = re.findall(r"<mapping[^>]*type=\"(?:normal_)?unicode\"[^>]*>U\+([0-9A-Fa-f]+)</mapping>", xml)
    return xml + "".join(chr(int(h, 16)) for h in mapped)


def raw_text(source: str) -> str:
    """Every unit's text in data/raw/{source}, if it is materialized."""
    parts: list[str] = []
    for path in sorted((REPO / "data" / "raw" / source).glob("**/*.json")):
        if path.name.startswith("_"):
            continue
        body = path.read_bytes()
        if body.startswith(b"version https://git-lfs"):
            continue
        record = json.loads(body)
        for unit in record.get("verses", []) + record.get("paragraphs", []):
            parts.append(unit["text"])
    return "".join(parts)


def google_served(cache: pathlib.Path) -> set[int]:
    """Code points in the unicode-ranges of Google's Noto Serif TC slices.

    Google slices CJK fonts by a fixed plan and leaves out characters the plan
    doesn't list, although the font has them (厏 U+538F), so what next/font
    serves is the font's cmap cut to these ranges.
    """
    req = urllib.request.Request(
        GOOGLE_CSS,
        # A browser that takes WOFF2 gets the sliced CSS.
        headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"},
    )
    # Fetched on every run (it is small), since Google can change its slices.
    with urllib.request.urlopen(req, timeout=60) as r:
        css = r.read().decode("utf-8")
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "NotoSerifTC.css").write_text(css, encoding="utf-8")
    served: set[int] = set()
    for ranges in re.findall(r"unicode-range:\s*([^;]+);", css):
        for part in ranges.split(","):
            part = part.strip().lower().removeprefix("u+")
            if "?" in part:
                lo, hi = int(part.replace("?", "0"), 16), int(part.replace("?", "f"), 16)
            elif "-" in part:
                lo, hi = (int(x.removeprefix("u+"), 16) for x in part.split("-"))
            else:
                lo = hi = int(part, 16)
            served.update(range(lo, hi + 1))
    if len(served) < 10000:
        raise RuntimeError(f"Google's Noto Serif TC CSS lists only {len(served)} code points: not the sliced CSS?")
    return served


def is_han(cp: int) -> bool:
    return any(a <= cp <= b for a, b in HAN_RANGES)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    cache_default = pathlib.Path(os.environ.get("XDG_CACHE_HOME", pathlib.Path.home() / ".cache")) / "patristica-cjk-font"
    ap.add_argument("--cache", type=pathlib.Path, default=cache_default, help="download cache")
    args = ap.parse_args()
    cache: pathlib.Path = args.cache

    text = "".join(wikisource_text(p, cache) for p in WIKISOURCE_PAGES)
    text += "".join(cbeta_text(n, cache) for n in CBETA_TEXTS)
    text += "".join(raw_text(s) for s in RAW_SOURCES)
    used = sorted({ord(c) for c in text if is_han(ord(c))})

    noto = TTFont(io.BytesIO(fetch(NOTO_TC, cache / "NotoSerifTC.ttf")))
    have = set(noto.getBestCmap()) & google_served(cache)
    missing = [cp for cp in used if cp not in have]

    archive = zipfile.ZipFile(io.BytesIO(fetch(JIGMO, cache / "Jigmo.zip")))
    parts: list[TTFont] = []
    covered: list[int] = []
    for name in ("Jigmo.ttf", "Jigmo2.ttf", "Jigmo3.ttf"):
        font = TTFont(io.BytesIO(archive.read(name)))
        cmap = font.getBestCmap()
        wanted = [cp for cp in missing if cp in cmap and cp not in covered]
        if not wanted:
            continue
        options = subset.Options()
        options.layout_features = []
        options.name_IDs = ["*"]
        options.notdef_outline = True
        subsetter = subset.Subsetter(options)
        subsetter.populate(unicodes=wanted)
        subsetter.subset(font)
        buf = io.BytesIO()
        font.save(buf)
        buf.seek(0)
        parts.append(buf)
        covered += wanted
    lacking = [cp for cp in missing if cp not in covered]

    if len(parts) == 1:
        merged = TTFont(parts[0])
    else:
        merged = Merger().merge(parts)
    merged.flavor = "woff2"
    OUT.mkdir(exist_ok=True)
    merged.save(OUT / "Jigmo-Chinese.woff2")
    (OUT / "Jigmo-LICENSE.txt").write_bytes(archive.read("LICENSE.txt"))

    lines = [
        "# Characters of the Chinese sources that Noto Serif TC lacks, in Jigmo-Chinese.woff2",
        "# (generated by web/scripts/chinese-font.py; do not edit).",
    ]
    lines += [f"U+{cp:04X}\t{chr(cp)}" for cp in sorted(covered)]
    if lacking:
        lines.append("# In neither font:")
        lines += [f"# U+{cp:04X}\t{chr(cp)}" for cp in lacking]
    (OUT / "Jigmo-Chinese.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(used)} Han code points used, {len(missing)} not in Noto Serif TC, {len(covered)} from Jigmo, {len(lacking)} in neither")


if __name__ == "__main__":
    main()
