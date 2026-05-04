"""
Ingestor for Ecumenical Council texts (Schaff/Percival edition).

Source: NPNF2 Vol. 14 — https://ccel.org/ccel/s/schaff/npnf214.xml
License: Public domain (19th-century English translation)
Language: English (eng)
Genre: council

Produces one Work per council/synod:
  7 ecumenical councils + Council in Trullo + 5 provincial synods
  + Sardica, Carthage, Constantinople-Nectarius, Carthage-Cyprian
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from lxml import etree

from patristica.models import Work
from scripts.ingest._ccel_common import _element_inner_text, _find_body
from scripts.ingest._common import download_file

log = logging.getLogger(__name__)

SOURCE_ID = "councils/ecumenical"

_NPNF214_URL = "https://ccel.org/ccel/s/schaff/npnf214.xml"
_SCHISM_YEAR = 1054


# ---------------------------------------------------------------------------
# Council / synod metadata
# ---------------------------------------------------------------------------

@dataclass
class _SynodInfo:
    slug: str
    title: str
    date_composed: int
    date_range: tuple[int, int]
    ref_prefix: str


# Ecumenical councils: div1[@id] → synod info
_ECUMENICAL = {
    "vii":  _SynodInfo("nicaea1",   "The First Council of Nicaea",             325, (318, 325), "Nicaea1"),
    "ix":   _SynodInfo("const1",    "The First Council of Constantinople",     381, (378, 381), "Const1"),
    "x":    _SynodInfo("ephesus",   "The Council of Ephesus",                  431, (428, 431), "Ephesus"),
    "xi":   _SynodInfo("chalcedon", "The Council of Chalcedon",                451, (449, 451), "Chalcedon"),
    "xii":  _SynodInfo("const2",    "The Second Council of Constantinople",    553, (548, 553), "Const2"),
    "xiii": _SynodInfo("const3",    "The Third Council of Constantinople",     681, (678, 681), "Const3"),
    "xvi":  _SynodInfo("nicaea2",   "The Second Council of Nicaea",            787, (784, 787), "Nicaea2"),
}

# Council in Trullo (single div1 id="xiv")
_TRULLO_ID = "xiv"
_TRULLO = _SynodInfo("trullo", "Council in Trullo (Quinisext)", 692, (691, 692), "Trullo")

# Provincial synods: container div1 id="viii", one Work per div2
_PROVINCIAL: dict[str, _SynodInfo] = {
    "viii.iii": _SynodInfo("ancyra",      "Council of Ancyra",      314, (314, 314), "Ancyra"),
    "viii.iv":  _SynodInfo("neocaesarea", "Council of Neocaesarea", 314, (314, 320), "Neocaesarea"),
    "viii.v":   _SynodInfo("gangra",      "Council of Gangra",      340, (340, 341), "Gangra"),
    "viii.vi":  _SynodInfo("antioch-syn", "Synod of Antioch",       341, (341, 341), "Antioch"),
    "viii.vii": _SynodInfo("laodicea",    "Synod of Laodicea",      363, (363, 364), "Laodicea"),
}

# Sardica/Carthage group: container div1 id="xv", one Work per div2
_SARDICA: dict[str, _SynodInfo] = {
    "xv.iii": _SynodInfo("sardica",          "Council of Sardica",                        343, (343, 344), "Sardica"),
    "xv.iv":  _SynodInfo("carthage-african", "Code of Canons of the African Church",      419, (393, 419), "Carthage"),
    "xv.v":   _SynodInfo("const-nect",       "Council of Constantinople under Nectarius", 381, (381, 381), "ConstNect"),
    "xv.vi":  _SynodInfo("carthage-cyprian", "Council of Carthage under Cyprian",         256, (254, 258), "CarthageCyp"),
}

# All container div1 ids → their per-div2 mapping
_CONTAINER_DIVS = {"viii": _PROVINCIAL, "xv": _SARDICA}


# ---------------------------------------------------------------------------
# Paragraph extraction helpers
# ---------------------------------------------------------------------------

def _roman_to_int(s: str) -> int:
    """Convert Roman numeral string to int (I=1 … M=1000)."""
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    result, prev = 0, 0
    for ch in reversed(s.upper()):
        v = vals.get(ch, 0)
        result += v if v >= prev else -v
        prev = v
    return result


# Title substrings that indicate editorial/structural sections to skip
_SKIP_KWDS = (
    "excursus",
    "historical note",
    "historical introduction",
    "bibliograph",
    "title page",
    "introductory note",
    "prefatory note",
    "introduction on the number",
    "note on the",
    "warning to the reader",
    "proposed action",
    "captions of the arabic",
    "appended note",
    "indexes",
    "index",
    "subsequent history",
    "authority of the",
    "words ",        # "Excursus on the Words …" style sections
    "word ",         # "Excursus on the Word …"
)

# Title substrings → canonical section type (first match wins)
_TITLE_SECTION_MAP = (
    ("nicene creed",           "Creed"),
    ("creed",                  "Creed"),
    ("symbol of faith",        "Creed"),
    ("definition of faith",    "Definition"),
    ("the definition of",      "Definition"),
    ("synodal letter",         "Letter"),
    ("synodical letter",       "Letter"),
    ("tome of",                "Letter"),
    ("epistle of cyril",       "Letter"),
    ("letter of cyril",        "Letter"),
    ("the letter of",          "Letter"),
    ("decretal letter",        "Letter"),
    ("decretal epistle",       "Letter"),
    # Fifth Council (const2) specific section types
    ("the capitula of",        "Canon"),
    ("the anathemas against",  "Anathematism"),
    ("anathematisms of",       "Anathematism"),
    ("the sentence of the",    "Decree"),
    # General decrees and acts
    ("condemnation sent",      "Decree"),
    ("decree on",              "Decree"),
    ("decree with",            "Decree"),
)


def _should_skip(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in _SKIP_KWDS)


def _section_type(title: str) -> str | None:
    t = title.lower()
    for kw, sect in _TITLE_SECTION_MAP:
        if kw in t:
            return sect
    return None


def _extract_ps(
    el: etree._Element,
    base_ref: str,
    records: list[dict[str, str]],
    seen: dict[str, int],
) -> None:
    """Collect direct <p> children of el into records with base_ref (dedup by suffix)."""
    for child in el:
        if not isinstance(child.tag, str):
            continue
        if etree.QName(child.tag).localname != "p":
            continue
        text = _element_inner_text(child)
        if not text or len(text) < 20:
            continue
        count = seen.get(base_ref, 0)
        ref = base_ref if count == 0 else f"{base_ref}.{count}"
        seen[base_ref] = count + 1
        records.append({"ref": ref, "text": text})


def _collect(
    el: etree._Element,
    ref_prefix: str,
    records: list[dict[str, str]],
    seen: dict[str, int],
    counters: dict[str, int],
) -> None:
    """Recursively collect canonical content from el's children."""
    for child in el:
        if not isinstance(child.tag, str):
            continue
        local = etree.QName(child.tag).localname
        if local not in ("div2", "div3", "div4", "div5", "div6"):
            continue

        title = child.get("title", "") or ""
        div_type = child.get("type", "") or ""
        n_attr = child.get("n", "") or ""

        # Primary canonical sections with explicit type
        if div_type in ("Canon", "Anathematism"):
            n_int = _roman_to_int(n_attr) if n_attr else 0
            if n_int > 0:
                base_ref = f"{ref_prefix}.{div_type}.{n_int}"
            else:
                counters[div_type] = counters.get(div_type, 0) + 1
                base_ref = f"{ref_prefix}.{div_type}.{counters[div_type]}"
            _extract_ps(child, base_ref, records, seen)
            continue

        # Skip editorial/structural sections
        if _should_skip(title):
            continue

        # Named section by title keyword
        sect = _section_type(title)
        if sect:
            counters[sect] = counters.get(sect, 0) + 1
            base_ref = f"{ref_prefix}.{sect}.{counters[sect]}"
            _extract_ps(child, base_ref, records, seen)
            continue

        # Otherwise recurse (handles "Canons of…" container divs, Sessions, etc.)
        pre_count = len(records)
        _collect(child, ref_prefix, records, seen, counters)

        # Fallback: if recursion found nothing and this div has direct <p> content,
        # treat it as a generic Section (handles leaf divs like const-nect text blocks)
        if len(records) == pre_count:
            direct_ps = [
                c for c in child
                if isinstance(c.tag, str) and etree.QName(c.tag).localname == "p"
            ]
            if direct_ps:
                counters["Section"] = counters.get("Section", 0) + 1
                base_ref = f"{ref_prefix}.Section.{counters['Section']}"
                for p in direct_ps:
                    text = _element_inner_text(p)
                    if text and len(text) >= 20:
                        count = seen.get(base_ref, 0)
                        ref = base_ref if count == 0 else f"{base_ref}.{count}"
                        seen[base_ref] = count + 1
                        records.append({"ref": ref, "text": text})


def _extract_council_paragraphs(
    container: etree._Element,
    ref_prefix: str,
) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    _collect(container, ref_prefix, records, {}, {})
    return records


# ---------------------------------------------------------------------------
# Work factory
# ---------------------------------------------------------------------------

def _make_work(info: _SynodInfo) -> Work:
    return Work(
        work_id=f"councils/{info.slug}",
        source_id=SOURCE_ID,
        author=None,
        title=info.title,
        date_composed=info.date_composed,
        date_range=info.date_range,
        date_confidence="established",
        genre="council",
        language="eng",
        tradition=None,
        license="public_domain",
        provenance_url=_NPNF214_URL,
        edition="Nicene and Post-Nicene Fathers, Series 2, Vol. 14",
        translation_of=None,
    )


def _write_work(
    out_dir: Path,
    info: _SynodInfo,
    paragraphs: list[dict[str, str]],
    force: bool,
) -> Work | None:
    """Write one council Work JSON to out_dir/{slug}.json.  Returns Work or None if skipped."""
    out_path = out_dir / f"{info.slug}.json"
    work = _make_work(info)
    if out_path.exists() and not force:
        try:
            saved = json.loads(out_path.read_text(encoding="utf-8"))
            return Work(**saved["work"])
        except Exception:
            pass

    if not paragraphs:
        log.warning("No paragraphs extracted for %s", info.slug)
        return None

    payload = {"work": work.model_dump(), "paragraphs": paragraphs}
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("  Wrote %d paragraphs → %s", len(paragraphs), out_path.name)
    return work


# ---------------------------------------------------------------------------
# Main ingest function
# ---------------------------------------------------------------------------

def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download and parse NPNF2-14, producing one Work per council/synod."""
    out_dir = output_dir / "councils" / "ecumenical"
    out_dir.mkdir(parents=True, exist_ok=True)

    xml_path = download_file(_NPNF214_URL, out_dir / "npnf214.xml", force=force)

    parser = etree.XMLParser(no_network=True, load_dtd=False, recover=True)
    try:
        tree = etree.parse(str(xml_path), parser)
    except etree.XMLSyntaxError as exc:
        log.error("Failed to parse %s: %s", xml_path, exc)
        return []

    root = tree.getroot()
    body = _find_body(root)
    if body is None:
        log.error("No body element found in npnf214.xml")
        return []

    works: list[Work] = []

    for div1 in body:
        if not isinstance(div1.tag, str):
            continue
        if etree.QName(div1.tag).localname != "div1":
            continue

        div1_id = div1.get("id", "")

        # Seven ecumenical councils
        if div1_id in _ECUMENICAL:
            info = _ECUMENICAL[div1_id]
            paras = _extract_council_paragraphs(div1, info.ref_prefix)
            w = _write_work(out_dir, info, paras, force)
            if w:
                works.append(w)
                log.info("Council %s: %d paragraphs", info.slug, len(paras))

        # Council in Trullo
        elif div1_id == _TRULLO_ID:
            paras = _extract_council_paragraphs(div1, _TRULLO.ref_prefix)
            w = _write_work(out_dir, _TRULLO, paras, force)
            if w:
                works.append(w)
                log.info("Council %s: %d paragraphs", _TRULLO.slug, len(paras))

        # Container div1s (provincial synods, Sardica/Carthage)
        elif div1_id in _CONTAINER_DIVS:
            synod_map = _CONTAINER_DIVS[div1_id]
            for div2 in div1:
                if not isinstance(div2.tag, str):
                    continue
                if etree.QName(div2.tag).localname != "div2":
                    continue
                div2_id = div2.get("id", "")
                if div2_id not in synod_map:
                    continue
                info = synod_map[div2_id]
                paras = _extract_council_paragraphs(div2, info.ref_prefix)
                w = _write_work(out_dir, info, paras, force)
                if w:
                    works.append(w)
                    log.info("Synod %s: %d paragraphs", info.slug, len(paras))

    log.info("Council ingestion complete: %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
