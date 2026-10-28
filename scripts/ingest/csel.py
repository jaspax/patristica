"""
Ingestor for the CSEL texts of Open Greek and Latin (csel-dev, #77).

Source: https://github.com/OpenGreekAndLatin/csel-dev
Format: TEI EpiDoc, organised by CTS URN (``data/{stoaNNNN}/{stoaNNN}/``)
License: CC-BY-SA 4.0 (stated in every file's ``<licence>``)

The Corpus scriptorum ecclesiasticorum Latinorum volumes printed before 1930
(Augustine, Cyprian, Lactantius, Arnobius, Sulpicius Severus, Cassian, …),
OCR'd and corrected at Leipzig and split into one file per work.  Each file's
``sourceDesc`` names the CSEL volume, its editor and the scan it was read from;
they go into ``Work.edition``.  The repo's ``Volumes/`` (whole volumes, 300 MB)
repeats the same text, so the clone is sparse: ``data/`` only.

Every text is ecclesiastical Latin, so there is no scope allowlist as for
First1K/Perseus.  The stoa ids are the namespace Perseus uses
(``stoa0275.stoa002`` is Tertullian's *Ad nationes* in both), so a CSEL work
and a Perseus edition of it are one version group (``patristica/versions.py``).
Where the same work is also in OGL's Patrologia Latina (``oglt-pl``), both are
kept, as different witnesses.

Text
----
``<note>`` (sources, the critical apparatus, running heads, page numbers),
``<pb>``, ``<lb>`` and ``<milestone>`` are dropped.  Words hyphenated at a line
end are joined, and the margin line numbers (5, 10, … 35) that the OCR left in
the running text are removed.

Canonical references
--------------------
``{author_id}.{work_id_short}.{div_n_path}``, as for Perseus:
``stoa0040.stoa001.1.1`` (Confessions 1.1).
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path

from lxml import etree
from tqdm import tqdm

from patristica.models import Work
from patristica.period import work_in_period
from scripts.ingest._common import dedupe_refs, require_network, slugify_ref
from scripts.ingest.first1k import _extract_dates, _place_headings

log = logging.getLogger(__name__)

SOURCE_ID = "csel"

_REPO_URL = "https://github.com/OpenGreekAndLatin/csel-dev.git"
_REPO_BLOB = "https://github.com/OpenGreekAndLatin/csel-dev/blob/master"

_TEI = "http://www.tei-c.org/ns/1.0"
_CTS_NS = "http://chs.harvard.edu/xmlns/cts"
_XML_NS = "http://www.w3.org/XML/1998/namespace"
_NS = {"tei": _TEI}

_STRUCTURAL_DIV_TYPES = frozenset({"textpart"})

_SKIP_ELEMENTS = frozenset({
    "note", "pb", "lb", "cb", "fw", "figure", "milestone", "table", "gap",
})

_XML_PARSER = etree.XMLParser(load_dtd=False, no_network=True, resolve_entities=False)

# Text groups whose catalogue name is wrong or too bare to resolve
# (``patristica/authors.py``): ``{stoa author id}: author``.
_AUTHOR_OVERRIDES: dict[str, str] = {
    "stoa0222a": "Paulinus of Béziers",  # catalogued as "Paul, the Apostle"; the Epigramma Paulini
    "stoa0278a": "Theodosius the Pilgrim",  # De situ terrae sanctae, not the emperor
    "stoa0111": "Egeria",  # "Itinera Hierosolymitana / Egragia": the Peregrinatio Aetheriae
}

# Text groups after the collection period (``patristica.period``), which CSEL
# prints beside the earlier texts they draw on: ``{stoa author id}: reason``.
_OUT_OF_PERIOD: dict[str, str] = {
    "stoa0227b": "Peter the Deacon of Monte Cassino (b. c. 1107), De locis sanctis (1137)",
}

# Single works printed inside a collection, cut out as works of their own (#315):
# ``{file stem}: ((section n, work segment, title), …)``.  The part's id is
# ``csel/{author}/{work segment}/{edition}``, a CTS work id of its own, so the CTS
# rule doesn't put it back into the collection's version group.
_PARTS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "stoa0040.stoa011.opp-lat2": (
        ("185", "stoa011-ep185", "Epistula CLXXXV ad Bonifatium (De correctione Donatistarum)"),),
}

# A word broken at a line end: "existi- memus", "SE- CVNDVS".
_HYPHEN = re.compile(r"(\w)[-¬]\s+(\w)")
# CSEL prints a line number every five lines in the margin; the OCR often
# kept it in the text, between words ("existi- 25 memus").
_LINE_NUMBER = re.compile(r"(?<!\S)(?:5|10|15|20|25|30|35)(?!\S)\s*")


def _ensure_repo(repo_dir: Path, force: bool) -> None:
    """Sparse-clone csel-dev's ``data/`` into *repo_dir*; pull the latest on *force*."""
    if not repo_dir.exists():
        require_network(f"cloning {_REPO_URL}")
        log.info("Cloning csel-dev (data/ only) into %s …", repo_dir)
        repo_dir.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--depth=1", "--filter=blob:none", "--sparse",
                        _REPO_URL, str(repo_dir)], check=True)
        subprocess.run(["git", "-C", str(repo_dir), "sparse-checkout", "set", "data"], check=True)
    elif force:
        log.info("Pulling latest csel-dev data …")
        subprocess.run(["git", "-C", str(repo_dir), "pull", "--ff-only"], check=True)


def _read_groupname(cts_path: Path) -> str | None:
    """The text group's (author's) English name from a ``__cts__.xml``."""
    if not cts_path.exists():
        return None
    root = etree.parse(str(cts_path), _XML_PARSER).getroot()
    names = root.findall(f".//{{{_CTS_NS}}}groupname")
    for el in names:
        if el.get(f"{{{_XML_NS}}}lang") == "eng" and (el.text or "").strip():
            return el.text.strip()
    return next(((el.text or "").strip() for el in names if (el.text or "").strip()), None)


def _inner_text(el: etree._Element) -> str:
    """All text inside *el*, without the skipped elements."""
    parts: list[str] = [el.text or ""]
    for child in el:
        if not isinstance(child.tag, str):  # comment or processing instruction
            parts.append(child.tail or "")
            continue
        if etree.QName(child.tag).localname not in _SKIP_ELEMENTS:
            parts.append(_inner_text(child))
        elif etree.QName(child.tag).localname == "lb":
            parts.append("\n")
        parts.append(child.tail or "")
    return "".join(parts)


def clean_text(raw: str) -> str:
    """Collapse whitespace, drop margin line numbers and join hyphenated words."""
    text = re.sub(r"\s+", " ", raw).strip()
    text = _LINE_NUMBER.sub("", text)
    return _HYPHEN.sub(r"\1\2", text).strip()


def extract_paragraphs(body_el: etree._Element, work_cts_id: str) -> list[dict[str, str]]:
    """An edition div's units: one per ``<p>``/``<ab>``/``<lg>`` or bare ``<l>``, with headings.

    Refs are the ``textpart`` ``@n`` path.  A ``<head>`` of a div becomes a
    heading record where the reader can show it as one (``_place_headings``).
    """
    records: list[dict[str, str]] = []
    headings: list[tuple[int, str, str]] = []

    def ref_of(path: list[str]) -> str:
        return slugify_ref(".".join([work_cts_id, *path]))

    def walk(element: etree._Element, path: list[str]) -> None:
        if not isinstance(element.tag, str):
            return
        tag = etree.QName(element.tag).localname
        if tag in ("p", "ab", "lg"):
            text = clean_text(_inner_text(element))
            if text:
                records.append({"ref": ref_of(path), "text": text})
            return
        if tag == "l":  # a verse line outside any <p>/<lg>: one unit per numbered line
            n = element.get("n", "")
            # The printed line number (every fifth line) leads the line's text.
            text = re.sub(rf"^{re.escape(n)}\s+", "", clean_text(_inner_text(element))) if n else \
                clean_text(_inner_text(element))
            if text:
                records.append({"ref": ref_of([*path, n] if n.isdigit() else path), "text": text})
            return
        if tag == "head":
            text = clean_text(_inner_text(element))
            if any(ch.isalpha() for ch in text):  # a bare "3" only repeats the ref
                headings.append((len(records), ref_of(path), text))
            return
        if tag == "div" and element.get("type") in _STRUCTURAL_DIV_TYPES:
            n = element.get("n", "")
            path = [*path, n] if re.fullmatch(r"[\w\-]+", n) else path
        if tag not in _SKIP_ELEMENTS:
            for child in element:
                walk(child, path)

    for child in body_el:
        walk(child, [])
    return _place_headings(dedupe_refs(records), headings)


def _edition(root: etree._Element, version: str) -> str:
    """"CSEL 33, ed. Pius Knöll (1896); OGL csel-dev opp-lat1; scan: …" from ``sourceDesc``."""
    bibl = root.find(".//tei:sourceDesc//tei:biblStruct", _NS)
    parts: list[str] = []
    if bibl is not None:
        volume = bibl.findtext("tei:series/tei:biblScope", default="", namespaces=_NS).strip()
        editors = [re.sub(r"\s+", " ", "".join(e.itertext())).strip()
                   for e in bibl.findall("tei:monogr/tei:editor", _NS)]
        date = bibl.findtext("tei:monogr/tei:imprint/tei:date", default="", namespaces=_NS).strip()
        label = f"CSEL {volume}" if volume else "CSEL"
        if any(editors):
            label += ", ed. " + ", ".join(e for e in editors if e)
        if date:
            label += f" ({date})"
        parts.append(label)
    parts.append(f"OGL csel-dev {version}".strip())
    scan = bibl.find("tei:ref", _NS) if bibl is not None else None
    if scan is not None and scan.get("target"):
        parts.append(f"scan: {scan.get('target')}")
    return "; ".join(parts)


def _license(root: etree._Element) -> str:
    """The file's licence; csel-dev states CC BY-SA 4.0 in every file."""
    for lic in root.findall(".//tei:availability/tei:licence", _NS):
        target = lic.get("target", "")
        if "by-sa" in target and "nc" not in target:
            return "cc-by-sa-4.0"
    raise ValueError("no CC BY-SA 4.0 licence in the header")


def parse_file(xml_path: Path, author_name: str | None) -> tuple[Work, list[dict[str, str]]] | None:
    """Parse one csel-dev TEI file; None if it holds no Latin edition."""
    root = etree.parse(str(xml_path), _XML_PARSER).getroot()
    edition_div = root.find(".//tei:text/tei:body/tei:div[@type='edition']", _NS)
    if edition_div is None:
        log.warning("%s: no edition div; skipped", xml_path.name)
        return None
    if "lat" not in edition_div.get(f"{{{_XML_NS}}}lang", "lat"):
        return None

    urn = edition_div.get("n", "") or xml_path.stem
    author_id, work_short, version = (urn.rsplit(":", 1)[-1].split(".") + ["", ""])[:3]
    work_cts_id = f"{author_id}.{work_short}"
    if author_id in _OUT_OF_PERIOD:
        log.info("%s: after the collection period (%s); skipped",
                 work_cts_id, _OUT_OF_PERIOD[author_id])
        return None

    date_composed, date_range, date_confidence = _extract_dates(root)
    if not work_in_period(date_range):
        log.info("%s: dated after the collection period %s; skipped", work_cts_id, date_range)
        return None

    title_el = root.find(".//tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", _NS)
    title = re.sub(r"\s+", " ", "".join(title_el.itertext())).strip() if title_el is not None \
        else ""
    author_el = root.find(".//tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:author", _NS)
    author = _AUTHOR_OVERRIDES.get(author_id) or author_name or (
        (author_el.text or "").strip() if author_el is not None else None)

    rel = xml_path.relative_to(xml_path.parents[2])
    work = Work(
        work_id=f"{SOURCE_ID}/{author_id}/{work_short}/{version}",
        source_id=SOURCE_ID,
        author=author or None,
        title=title or work_cts_id,
        date_composed=date_composed,
        date_range=date_range,
        date_confidence=date_confidence,
        genre="patristic",
        language="lat",
        tradition="latin",
        license=_license(root),
        provenance_url=f"{_REPO_BLOB}/data/{rel.as_posix()}",
        edition=_edition(root, version),
        translation_of=None,
    )
    return work, extract_paragraphs(edition_div, work_cts_id)


def split_parts(stem: str, work: Work, paragraphs: list[dict[str, str]]
                ) -> list[tuple[str, Work, list[dict[str, str]]]]:
    """*work* without its :data:`_PARTS` sections, then each part: ``(file stem, work, paras)``."""
    parts = _PARTS.get(stem, ())
    if not parts:
        return [(stem, work, paragraphs)]
    author_id, _, version = work.work_id.split("/")[1:]
    rest, out = list(paragraphs), []
    for n, segment, title in parts:
        prefix = f"{author_id}.{work.work_id.split('/')[2]}.{n}"
        mine = [p for p in rest if p["ref"] == prefix or p["ref"].startswith(prefix + ".")]
        if not mine:
            raise ValueError(f"{stem}: part {n} has no paragraphs")
        rest = [p for p in rest if p not in mine]
        part = work.model_copy(update={"work_id": f"{SOURCE_ID}/{author_id}/{segment}/{version}",
                                       "title": title})
        out.append((f"{author_id}.{segment}.{version}", part, mine))
    return [(stem, work, rest), *out]


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Clone csel-dev and write one raw JSON file per work to ``output_dir/csel/``."""
    repo_dir = output_dir / "_repos" / "csel-dev"
    _ensure_repo(repo_dir, force)
    data_dir = repo_dir / "data"
    if not data_dir.is_dir():
        raise FileNotFoundError(f"Expected csel-dev data directory at {data_dir}")

    xml_files = [p for p in sorted(data_dir.glob("*/*/*.xml")) if p.name != "__cts__.xml"]
    log.info("Found %d csel-dev text files", len(xml_files))

    works: list[Work] = []
    for xml_path in tqdm(xml_files, desc="CSEL ingest"):
        out_path = output_dir / SOURCE_ID / xml_path.relative_to(data_dir).with_suffix(".json")
        if out_path.exists() and not force:
            works.append(Work(**json.loads(out_path.read_text(encoding="utf-8"))["work"]))
            continue
        try:
            result = parse_file(xml_path, _read_groupname(xml_path.parents[1] / "__cts__.xml"))
        except (etree.XMLSyntaxError, ValueError) as exc:
            log.error("%s: %s; work dropped", xml_path.name, exc)
            continue
        if result is None:
            continue
        work, paragraphs = result
        if not paragraphs:
            log.error("%s: no text extracted; work dropped", xml_path.name)
            continue
        for stem, piece, paras in split_parts(xml_path.stem, work, paragraphs):
            path = out_path.with_name(f"{stem}.json")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"work": piece.model_dump(), "paragraphs": paras},
                                       ensure_ascii=False, indent=2), encoding="utf-8")
            works.append(piece)

    log.info("CSEL ingestion complete: %d works", len(works))
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
