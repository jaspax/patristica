"""
Ingestor for the Jingjiao (Church of the East) texts on Chinese Wikisource (#650, part of #228).

Source: https://zh.wikisource.org
Format: MediaWiki wikitext, one page per work
License: CC-BY-SA 4.0 (Wikisource)

The Tang-era Christian texts in Literary Chinese the survey of #228 found on
zh.wikisource (category 景教 and others, checked 2026-11-12):

- **大秦景教流行中國碑頌**, the Xi'an stele (781), by Jingjing 景淨 (Adam).
  The page transcribes the stone diplomatically (㬌 for 景, 扵, 夲, the
  honorific spaces before 三一, 太宗 …) with its Syriac in Syriac script and
  the names on the two narrow sides, column by column. A second page,
  **景教流行中國碑**, is the 全唐文 卷916 text (Qing, 1814): normalized
  characters, the Qing taboo substitutions (元宗 for 玄宗, 房公元齡), the
  cross left out (印持（闕一字）), no Syriac, and below it a vertical copy of
  the first page's text. The first page is kept; the second is not ingested.
  The stele's Syriac (the byline, the dating under Patriarch Ḥnanishoʿ, the
  year 1092 of the Greeks, Yazdbozid's dedication, the clergy's names) is a
  separate ``syc`` work (``xian-stele-syriac``), with the same refs as the
  Chinese units it stands beside. Two later inscriptions on the stone are
  left out of both: Han Taihua's of 1859 (咸豐己未, on the left side) and
  Li Genyuan's of 1917 (民國六年, the right side's fourth column).
- **景教三威蒙度讚**, the hymn of Pelliot chinois 3847, and **尊經**, the
  list of saints and books that follows it in the same manuscript (two works).
- **志玄安樂經** (Li Shengduo's manuscript, Kyōu Shooku), a reading text
  with the manuscript's gaps as □.
- **大秦景教宣元至本經**: the page carries three witnesses. Kept: the text of
  the Luoyang pillar (經幢, 814/815, excavated 2006) with the pillar's
  dedication (幢記). Not ingested: the Dunhuang manuscript's 宣元本經 (Li
  Shengduo's, the pillar's first part; a second edition, follow-up issue) and
  Kojima manuscript B, which the page itself labels a forgery (偽經; Lin Wushu).
- **序聽迷詩所經** (Tomioka / Kyōu Shooku 羽459), with its authenticity
  debate recorded in the work's edition note.

Every page is pinned to a revision (:data:`PAGES`), fetched by revision id and
cached in ``data/raw/_cache/wikisource-lzh/``, so the ingest regenerates
offline. zh.wikisource rate-limits fast clients, hence the long throttle.

Text
----
Characters are stored exactly as each page has them (variants included;
folding them for search is #648). Only the page's frame is dropped (header
templates, licence and category tags, HTML and wiki markup, the language
conversion markup ``-{…}-``). A source paragraph is a run of lines between
blank lines; its lines (layout only) are joined with no space.

Editorial material (#236) is marked, not stripped:

- the manuscripts' and the stele's title lines (序聽迷詩所經一卷, the
  hymn's end title, 尊經, the stele's first column with its byline) are units
  of their own, wholly ``title``; the page's section headings (the stele's
  side columns 左面第一行 …, the pillar's two parts) are wholly ``heading``;
- the gap marks □, ……, the manuscript's spaces for unreadable characters in
  序聽迷詩所經, and ⁎ in the Syriac are ``lacuna``s; the editor's
  restorations ``[…]`` in 尊經 are ``supplement``s.

尊經's smaller-written notes (已上三身同歸一體, the closing 謹案諸經目錄 …)
are the manuscript's own and stay text.

Canonical references
--------------------
- Stele: ``XianStele.0`` the first column (title and byline), then
  ``XianStele.{n}`` per paragraph of the front face, and
  ``XianStele.{Left|Right}.{column}.{n}`` per entry of a side column (heading
  at ``XianStele.Left.1``). Entries are numbered by position, so an effaced
  name (the page's empty ``*``) or an entry with only one script keeps its
  number unused in the other work.
- ``SanweiMengdu.{n}`` per stanza, ``Zunjing.{n}``, ``ZhixuanAnle.{n}``,
  ``Xuting.{n}`` per paragraph (0 = title line).
- ``XuanyuanZhiben.{1|2}.{n}``: 1 the sutra on the pillar, 2 the pillar's
  dedication.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

import httpx

from patristica.models import Work
from scripts.ingest._common import require_network

log = logging.getLogger(__name__)

SOURCE_ID = "wikisource-lzh"

_API = "https://zh.wikisource.org/w/api.php"
_USER_AGENT = "Patristica/0.1 (https://patristica.app; corpus ingest)"
_THROTTLE_S = 10.0  # between requests: zh.wikisource rate-limits hard
_RETRIES = 4
_last_request = 0.0

_WS = "zh.wikisource"


@dataclass(frozen=True)
class Page:
    slug: str
    title: str  # the Wikisource page
    revid: int  # the revision ingested
    work_title: str
    author: str | None
    date_composed: int | None
    date_range: tuple[int, int]
    date_confidence: str
    genre: str
    edition: str
    language: str = "lzh"


def _edition(title: str, revid: int, date: str, rest: str) -> str:
    return f"Chinese Wikisource, «{title}», revision {revid} ({date}); {rest}"


STELE = Page(
    slug="xian-stele",
    title="大秦景教流行中國碑頌",
    revid=5621233,
    work_title="大秦景教流行中國碑頌并序 (Xi'an Stele)",
    author="景淨",
    date_composed=781,
    date_range=(781, 781),
    date_confidence="established",
    genre="patristic",
    edition=_edition(
        "大秦景教流行中國碑頌", 5621233, "2026-05-24",
        "diplomatic transcription of the stele erected in 781 at Chang'an (now in the Xi'an "
        "Beilin Museum), with the names on its sides; the Syriac is the separate work "
        "xian-stele-syriac. The later inscriptions of 1859 and 1917 are left out."),
)

STELE_SYRIAC = Page(
    slug="xian-stele-syriac",
    title="大秦景教流行中國碑頌",
    revid=5621233,
    work_title="ܟܬܒܐ ܕܠܘܚܐ (Xi'an Stele, Syriac inscriptions)",
    author=None,
    date_composed=781,
    date_range=(781, 781),
    date_confidence="established",
    genre="patristic",
    language="syc",
    edition=_edition(
        "大秦景教流行中國碑頌", 5621233, "2026-05-24",
        "the Syriac (Estrangela) inscriptions of the Xi'an stele of 781: the byline of Adam, "
        "the dating under Patriarch Ḥnanishoʿ, the year 1092 of the Greeks, Yazdbozid's "
        "dedication and the clergy's names, numbered as the Chinese units they stand beside "
        "(wikisource-lzh/xian-stele). ⁎ marks illegible letters."),
)

HYMN = Page(
    slug="sanwei-mengdu-zan",
    title="景教三威蒙度讚",
    revid=485789,
    work_title="景教三威蒙度讚 (Hymn to the Holy Trinity)",
    author=None,
    date_composed=None,
    date_range=(720, 845),
    date_confidence="approximate",
    genre="liturgical",
    edition=_edition(
        "景教三威蒙度讚", 485789, "2016-07-20",
        "diplomatic text of Pelliot chinois 3847 (Dunhuang; Bibliothèque nationale de France). "
        "A Chinese adaptation of the Gloria in excelsis; listed as 三威讚經 in the Zunjing."),
)

ZUNJING = Page(
    slug="zunjing",
    title="尊經",
    revid=1742288,
    work_title="尊經 (Book of Honoured Persons and Sacred Books)",
    author=None,
    date_composed=None,
    date_range=(781, 1000),
    date_confidence="approximate",
    genre="liturgical",
    edition=_edition(
        "尊經", 1742288, "2019-09-17",
        "text of Pelliot chinois 3847, following the hymn 景教三威蒙度讚; [ ] are the "
        "editor's restorations. Its closing note names Jingjing as translator of the books "
        "listed, so it is later than him."),
)

ZHIXUAN = Page(
    slug="zhixuan-anle-jing",
    title="志玄安樂經",
    revid=2009893,
    work_title="志玄安樂經 (Book of Profound and Mysterious Peace and Joy)",
    author=None,
    date_composed=None,
    date_range=(700, 800),
    date_confidence="approximate",
    genre="patristic",
    edition=_edition(
        "志玄安樂經", 2009893, "2020-12-26",
        "reading text of the manuscript formerly in Li Shengduo's collection, published in "
        "Kyōu Shooku's Tonkō hikyū (Osaka); □ marks the manuscript's gaps. Its beginning is "
        "lost. Listed in the Zunjing among the books Jingjing translated."),
)

XUANYUAN = Page(
    slug="xuanyuan-zhiben-jing",
    title="大秦景教宣元至本經",
    revid=517908,
    work_title="大秦景教宣元至本經 (Book of the Origin of Origins), Luoyang pillar",
    author=None,
    date_composed=None,
    date_range=(750, 815),
    date_confidence="approximate",
    genre="patristic",
    edition=_edition(
        "大秦景教宣元至本經", 517908, "2016-09-26",
        "the text of the Luoyang sutra pillar (經幢, dated 元和九年十二月 = 814/815, excavated "
        "2006) and the pillar's dedication (幢記); …… and □ mark damaged text. The page's "
        "other witnesses are not included: the Dunhuang manuscript (Li Shengduo's 宣元本經) "
        "and Kojima manuscript B, a modern forgery (Lin Wushu). Listed in the Zunjing among "
        "the books Jingjing translated."),
)

XUTING = Page(
    slug="xuting-mishisuo-jing",
    title="序聽迷詩所經",
    revid=447399,
    work_title="序聽迷詩所經 (Jesus-Messiah Sutra)",
    author=None,
    date_composed=None,
    date_range=(635, 641),
    date_confidence="uncertain",
    genre="patristic",
    edition=_edition(
        "序聽迷詩所經", 447399, "2015-11-03",
        "text of the manuscript formerly in Tomioka Kenzō's collection (Kyōu Shooku 羽459); "
        "the end is lost. Traditionally dated to Aluoben's mission, c. 635–638, as one of the "
        "earliest Jingjiao texts; its authenticity and date are debated (the manuscript "
        "surfaced through the antiquities trade, like 一神論, and some scholars doubt it or "
        "date it later)."),
)

PAGES: tuple[Page, ...] = (STELE, STELE_SYRIAC, HYMN, ZUNJING, ZHIXUAN, XUANYUAN, XUTING)


# ---------------------------------------------------------------------------
# Wikitext → plain text
# ---------------------------------------------------------------------------

_SYRIAC_TEMPLATE = re.compile(r"\{\{Syriac\|([^{}]*)\}\}")


def clean_markup(text: str) -> str:
    """Wikitext without templates, links, HTML tags, bold/italic quotes and ``-{…}-``.

    A template keeps its first argument where that is text (``{{*|并序}}`` →
    并序, ``{{YL|建中二年|781年}}`` → 建中二年, ``{{Syriac|…}}`` → …); other
    templates (``{{PD-old}}``, ``{{cleanup}}``) are dropped. Line breaks are kept.
    """
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    text = re.sub(r"\[\[(?:File|Image|Category|category|Category):[^\]]*\]\]", "", text)
    text = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]]*)\]\]", r"\1", text)
    text = re.sub(r"-\{([^{}]*)\}-", r"\1", text)
    for _ in range(3):  # nested templates, innermost first
        text = re.sub(r"\{\{(?:\*|YL|Syriac|另)\|([^{}|]*)(?:\|[^{}]*)?\}\}", r"\1", text)
        text = re.sub(r"\{\{[^{}]*\}\}", "", text)
    text = re.sub(r"<br\s*/?>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("'''", "").replace("''", "")
    return text


def _strip(text: str) -> str:
    """Strip whitespace, the ideographic space (U+3000) included."""
    return text.strip(" \t\n\r　")


def paragraphs(text: str) -> list[str]:
    """Blank-line separated paragraphs, each with its lines joined (no space: Chinese)."""
    out: list[str] = []
    for block in re.split(r"\n[ \t]*\n", text):
        line = "".join(_strip(part) for part in block.split("\n"))
        line = _strip(line)
        if line:
            out.append(line)
    return out


_LACUNA = re.compile(r"[□…⁎]+")
_SUPPLEMENT = re.compile(r"\[[^\[\]]+\]")
# 序聽迷詩所經 has no spaces but where the manuscript has a character the page
# could not give: a space between two characters is a gap.
_GAP_SPACE = re.compile(r"(?<=\S) (?=\S)")


def mark(text: str, gap_spaces: bool = False) -> list[list[Any]]:
    """Editorial spans of a unit: lacunae, supplements and (optionally) gap spaces."""
    spans = [[m.start(), m.end(), "supplement"] for m in _SUPPLEMENT.finditer(text)]
    spans += [[m.start(), m.end(), "lacuna"] for m in _LACUNA.finditer(text)]
    if gap_spaces:
        spans += [[m.start(), m.end(), "lacuna"] for m in _GAP_SPACE.finditer(text)]
    return sorted(spans)


def _unit(ref: str, text: str, spans: list[list[Any]] | None = None) -> dict[str, Any]:
    unit: dict[str, Any] = {"ref": ref, "text": text}
    if spans:
        unit["editorial"] = spans
    return unit


def _whole(ref: str, text: str, kind: str) -> dict[str, Any]:
    return _unit(ref, text, [[0, len(text), kind]])


def _body(wikitext: str) -> str:
    """The page's text: inside ``<onlyinclude>`` if it has one, without the header template."""
    m = re.search(r"<onlyinclude>(.*?)</onlyinclude>", wikitext, re.S)
    if m:
        return m.group(1)
    return re.sub(r"\{\{header2?\s*\|.*?\n\}\}", "", wikitext, count=1, flags=re.S | re.I)


# ---------------------------------------------------------------------------
# The stele: Chinese and Syriac
# ---------------------------------------------------------------------------

_SIDE = re.compile(r"^'''([左右])面第([一二三四])行'''$")
_SIDE_NAMES = {"左": "Left", "右": "Right"}
_NUMERALS = "一二三四"
# The later inscriptions on the stone (1859, 1917), by their opening.
_LATER = ("後一千七十九年", "{{YL|民國六年}}")


def _header_param(wikitext: str, name: str) -> str:
    m = re.search(rf"^\|\s*{name}\s*=(.*)$", wikitext, re.M)
    if not m:
        raise ValueError(f"stele: no |{name}= in the header")
    return m.group(1)


def parse_stele(wikitext: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """The stele's Chinese units and Syriac units, numbered alike."""
    chinese: list[dict[str, Any]] = []
    syriac: list[dict[str, Any]] = []

    title = clean_markup(_header_param(wikitext, "section"))
    byline_raw = _header_param(wikitext, "noauthor")
    byline_syr = _SYRIAC_TEMPLATE.findall(byline_raw)
    byline = _strip(clean_markup(_SYRIAC_TEMPLATE.sub("", byline_raw)))
    first = f"{_strip(title)}　{byline}"
    chinese.append(_whole("XianStele.0", first, "title"))
    if byline_syr:
        line = _strip(byline_syr[0])
        syriac.append(_unit("XianStele.0", line, mark(line)))

    prefix = "XianStele"
    n = 0
    sides_seen: list[str] = []
    skipped = 0
    for block in re.split(r"\n[ \t]*\n", _body(wikitext)):
        raw = _strip(block)
        if not raw:
            continue
        side = _SIDE.match(raw)
        if side:
            prefix = f"XianStele.{_SIDE_NAMES[side.group(1)]}.{_NUMERALS.index(side.group(2)) + 1}"
            sides_seen.append(raw)
            n = 0
            continue
        if raw.startswith(_LATER):
            skipped += 1
            continue
        n += 1
        ref = f"{prefix}.{n}"
        syr = [_strip(s) for s in _SYRIAC_TEMPLATE.findall(raw)]
        syr = [s for s in syr if s]
        rest = _SYRIAC_TEMPLATE.sub("", raw)
        rest = re.sub(r"^\*", "", rest)  # list bullet: an entry of a side column
        text = "".join(_strip(line) for line in clean_markup(rest).split("\n"))
        text = _strip(text)
        if text:
            chinese.append(_unit(ref, text, mark(text)))
        if syr:
            joined = " ".join(syr)
            syriac.append(_unit(ref, joined, mark(joined)))
    if skipped != 2:
        raise ValueError(f"stele: {skipped} later inscriptions found, expected 2")
    if len(sides_seen) != 8:
        raise ValueError(f"stele: {len(sides_seen)} side columns, expected 8")
    return _with_side_headings(chinese), syriac


def _with_side_headings(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A heading unit (左面第一行 …) before the first unit of each side column."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for unit in units:
        parts = unit["ref"].split(".")
        if len(parts) == 4:
            column = ".".join(parts[:3])
            if column not in seen:
                seen.add(column)
                side = "左" if parts[1] == "Left" else "右"
                out.append(_whole(column, f"{side}面第{_NUMERALS[int(parts[2]) - 1]}行", "heading"))
        out.append(unit)
    return out


# ---------------------------------------------------------------------------
# The other pages
# ---------------------------------------------------------------------------

def _plain_paragraphs(wikitext: str) -> list[str]:
    return paragraphs(clean_markup(_body(wikitext)))


def parse_hymn(wikitext: str) -> list[dict[str, Any]]:
    """Eleven stanzas, then the manuscript's end title (``SanweiMengdu.12``, wholly title)."""
    paras = _plain_paragraphs(wikitext)
    if not paras or not paras[-1].endswith("一卷"):
        raise ValueError("hymn: no end title")
    units = [_unit(f"SanweiMengdu.{n}", p, mark(p)) for n, p in enumerate(paras[:-1], 1)]
    units.append(_whole(f"SanweiMengdu.{len(paras)}", paras[-1], "title"))
    return units


def parse_zunjing(wikitext: str) -> list[dict[str, Any]]:
    """The title line (``Zunjing.0``), then the list's paragraphs and the closing note."""
    paras = _plain_paragraphs(wikitext)
    if not paras or paras[0] != "尊經":
        raise ValueError(f"zunjing: first paragraph is {paras[:1]!r}, expected 尊經")
    units = [_whole("Zunjing.0", paras[0], "title")]
    units += [_unit(f"Zunjing.{n}", p, mark(p)) for n, p in enumerate(paras[1:], 1)]
    return units


def parse_zhixuan(wikitext: str) -> list[dict[str, Any]]:
    paras = _plain_paragraphs(wikitext)
    return [_unit(f"ZhixuanAnle.{n}", p, mark(p)) for n, p in enumerate(paras, 1)]


def parse_xuting(wikitext: str) -> list[dict[str, Any]]:
    """The manuscript's title line (``Xuting.0``), then its text (one paragraph on the page)."""
    title, _, rest = clean_markup(_body(wikitext)).strip().partition("\n")
    title = _strip(title)
    if not title.endswith("一卷"):
        raise ValueError(f"xuting: title line is {title!r}")
    units = [_whole("Xuting.0", title, "title")]
    units += [_unit(f"Xuting.{n}", p, mark(p, gap_spaces=True))
              for n, p in enumerate(paragraphs(rest), 1)]
    return units


_SECTION = re.compile(r"^==\s*(.*?)\s*==\s*$", re.M)


def parse_xuanyuan(wikitext: str) -> list[dict[str, Any]]:
    """The pillar's sutra text (``XuanyuanZhiben.1``) and its dedication (``.2``).

    The page's first section (the Dunhuang manuscript) and last (Kojima
    manuscript B, a forgery) are left out.
    """
    parts = _SECTION.split(_body(wikitext))
    sections = dict(zip(parts[1::2], parts[2::2]))
    wanted = [(h, b) for h, b in sections.items() if h.startswith("經幢") or h.endswith("幢記")]
    others = [h for h in sections if not (h.startswith("經幢") or h.endswith("幢記"))]
    if len(wanted) != 2 or len(others) != 2 or not any("偽經" in h for h in others):
        raise ValueError(f"xuanyuan: unexpected sections {list(sections)}")
    units: list[dict[str, Any]] = []
    for number, (heading_raw, body) in enumerate(wanted, 1):
        heading = _strip(clean_markup(heading_raw))
        units.append(_whole(f"XuanyuanZhiben.{number}", heading, "heading"))
        paras = paragraphs(clean_markup(body))
        if not paras:
            raise ValueError(f"xuanyuan: section {heading!r} has no text")
        units += [_unit(f"XuanyuanZhiben.{number}.{n}", p, mark(p)) for n, p in enumerate(paras, 1)]
    return units


# ---------------------------------------------------------------------------
# Fetch and write
# ---------------------------------------------------------------------------

def _fetch(page: Page, cache_dir: Path) -> str:
    """The page's wikitext at its pinned revision (cached)."""
    path = cache_dir / f"rev-{page.revid}.json"  # one page may give two works (the stele)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))["wikitext"]
    require_network(f"fetching {page.title} from Chinese Wikisource")
    global _last_request
    for attempt in range(_RETRIES):
        time.sleep(max(0.0, _last_request + _THROTTLE_S * (2 ** attempt) - time.monotonic()))
        _last_request = time.monotonic()
        resp = httpx.get(_API, params={
            "action": "query", "prop": "revisions", "revids": str(page.revid),
            "rvprop": "content|ids|timestamp", "rvslots": "main",
            "format": "json", "formatversion": "2", "maxlag": "5",
        }, headers={"User-Agent": _USER_AGENT}, timeout=60)
        if resp.status_code == 429 or "too many requests" in resp.text[:500].lower():
            log.warning("%s: rate-limited, backing off", page.slug)
            continue
        resp.raise_for_status()
        break
    else:
        raise RuntimeError(f"{page.slug}: still rate-limited after {_RETRIES} attempts")
    found = resp.json()["query"]["pages"][0]
    revision = found["revisions"][0]
    if found["title"] != page.title or revision["revid"] != page.revid:
        raise ValueError(f"{page.slug}: revision {page.revid} is not of {page.title!r}")
    wikitext = revision["slots"]["main"]["content"]
    path.parent.mkdir(parents=True, exist_ok=True)
    cached = {"title": page.title, "revid": page.revid, "timestamp": revision["timestamp"],
              "wikitext": wikitext}
    path.write_text(json.dumps(cached, ensure_ascii=False, indent=1), encoding="utf-8")
    return wikitext


def _work(page: Page) -> Work:
    return Work(
        work_id=f"{SOURCE_ID}/{page.slug}",
        source_id=SOURCE_ID,
        author=page.author,
        title=page.work_title,
        date_composed=page.date_composed,
        date_range=page.date_range,
        date_confidence=page.date_confidence,  # type: ignore[arg-type]
        genre=page.genre,  # type: ignore[arg-type]
        language=page.language,  # type: ignore[arg-type]
        tradition="syriac",
        license="cc-by-sa-4.0",
        provenance_url=f"https://zh.wikisource.org/w/index.php?title={quote(page.title)}&oldid={page.revid}",
        edition=page.edition,
        translation_of=None,
    )


_PARSERS: dict[str, Callable[[str], list[dict[str, Any]]]] = {
    STELE.slug: lambda w: parse_stele(w)[0],
    STELE_SYRIAC.slug: lambda w: parse_stele(w)[1],
    HYMN.slug: parse_hymn,
    ZUNJING.slug: parse_zunjing,
    ZHIXUAN.slug: parse_zhixuan,
    XUANYUAN.slug: parse_xuanyuan,
    XUTING.slug: parse_xuting,
}


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Fetch the pinned pages and write one raw JSON file per work."""
    cache_dir = output_dir / "_cache" / SOURCE_ID
    works: list[Work] = []
    for page in PAGES:
        out_path = output_dir / SOURCE_ID / f"{page.slug}.json"
        if out_path.exists() and not force:
            works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
            continue
        work = _work(page)
        units = _PARSERS[page.slug](_fetch(page, cache_dir))
        if not units:
            raise ValueError(f"{page.slug}: no text")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({"work": work.model_dump(), "paragraphs": units},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
        works.append(work)
    log.info("Chinese Wikisource (Jingjiao): %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
