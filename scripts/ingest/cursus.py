"""
Ingestor for the CURSUS Medieval Liturgical Texts project.

Source: https://zenodo.org/records/5090613  (cursusProject.zip, 43.6 MB)
Format: TEI P3/custom XML with a cross-referenced chant repository
License: CC-BY-NC 4.0

Contents
--------
Twelve English Benedictine breviary manuscripts (12th–15th c.) encoded as
XML.  The actual chant/prayer texts are stored in a shared ``repository/``
directory (~500 antiphon, respond, and prayer files, each identified by a
``c{n}`` or ``o{n}`` ID).  Manuscript files reference repository items via
``<xptr from="ID({id})"/>`` elements; the surrounding structure gives
liturgical context (Day, service, nocturn, etc.).

Although the manuscripts are late medieval, the Benedictine Office repertoire
is largely first-millennium in origin (6th–10th c.); we therefore set
``out_of_period=False`` and ``date_confidence="approximate"`` for all chunks.

Repository text extraction
--------------------------
Each repository file contains one chant or prayer element:
  * ``<ant>`` — antiphon; text in ``<aBody>``
  * ``<res>`` — respond; text in ``<rBody>`` (+ ``<verses>/<vBody>`` for verse)
  * ``<prayer>`` — prayer/collect; text in ``<pBody>``

Textual variants are encoded as ``<app><rdg wit="...">…</rdg></app>``.  We
select the reading whose ``wit`` attribute includes the current manuscript's
sigil; if no specific reading matches we use the first ``<rdg>`` child.

Canonical references
--------------------
``CURSUS.{ms_sigil}.{day_num:03d}.{service_slug}.{seq:04d}``

Example: ``CURSUS.Wcb.001.matins.0003``
"""

from __future__ import annotations

import json
import logging
import re
import zipfile
from pathlib import Path
from typing import Iterator

from lxml import etree
from tqdm import tqdm

from patristica.models import Work
from scripts.ingest._common import offline, require_network, slugify_ref

log = logging.getLogger(__name__)

SOURCE_ID = "cursus"

_ZIP_NAME = "cursus.zip"
_ZIP_URL = "https://zenodo.org/records/5090613/files/cursusProject.zip?download=1"

# Mapping: filename stem → (sigil, shortname, ms_date_desc, earliest_year)
_MS_INFO: dict[str, tuple[str, str, str, int]] = {
    "battle":       ("Bat",  "Battle Breviary",       "late 15th c.",   1450),
    "chertsey":     ("Cht",  "Chertsey Breviary",     "c. 1320",        1320),
    "coldingham":   ("Cdm",  "Coldingham Breviary",   "13th c.",        1200),
    "ely":          ("Ely",  "Ely Breviary-Missal",   "13th c.",        1200),
    "evesham":      ("Evm",  "Evesham Breviary",      "13th c.",        1200),
    "gloucester":   ("Glo",  "Gloucester Diurnal",    "12th–15th c.",   1150),
    "hyde":         ("Hyd",  "Hyde Breviary",         "13th/14th c.",   1250),
    "muchelney":    ("Mch",  "Muchelney Breviary",    "13th c.",        1200),
    "peterborough": ("Pet",  "Peterborough Antiphoner","14th c.",       1300),
    "stalbans":     ("Alb2", "St Albans Breviary",    "printed 1532",   1532),
    "winchcombe":   ("Wcb",  "Winchcombe Breviary-Missal","c. 1140",    1140),
    "worcester":    ("Wor",  "Worcester Antiphoner",  "13th/14th c.",   1200),
}


# ---------------------------------------------------------------------------
# ZIP / file helpers
# ---------------------------------------------------------------------------

def _ensure_zip(zip_path: Path, force: bool) -> None:
    """Download the CURSUS ZIP if not already present."""
    if zip_path.exists() and (not force or offline()):
        log.debug("ZIP already present: %s", zip_path)
        return
    require_network(f"downloading {_ZIP_URL}")
    import httpx
    log.info("Downloading CURSUS ZIP from Zenodo…")
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with httpx.stream("GET", _ZIP_URL, timeout=120, follow_redirects=True) as r:
        r.raise_for_status()
        with open(zip_path, "wb") as f:
            for chunk in r.iter_bytes(chunk_size=65536):
                f.write(chunk)
    log.info("  Saved %s (%.1f MB)", zip_path.name, zip_path.stat().st_size / 1_048_576)


# ---------------------------------------------------------------------------
# Repository loader
# ---------------------------------------------------------------------------

def _load_repository(zf: zipfile.ZipFile) -> dict[str, etree._Element]:
    """Parse all repository XML files and return {id: root_element}."""
    repo: dict[str, etree._Element] = {}
    repo_names = [n for n in zf.namelist()
                  if "content/repository/" in n and n.endswith(".xml")]
    for name in repo_names:
        raw = zf.read(name)
        try:
            root = etree.fromstring(raw)
        except etree.XMLSyntaxError:
            # Some files use entity refs the parser can't resolve standalone;
            # strip the doctype line and retry.
            raw_str = raw.decode("utf-8", errors="replace")
            raw_str = re.sub(r"<!DOCTYPE[^>]*>", "", raw_str, flags=re.DOTALL)
            try:
                root = etree.fromstring(raw_str.encode("utf-8"))
            except etree.XMLSyntaxError as exc:
                log.debug("  Skipping %s: %s", name, exc)
                continue

        item_id = root.get("id") or ""
        if item_id:
            repo[item_id] = root
    log.info("Loaded %d repository items", len(repo))
    return repo


# ---------------------------------------------------------------------------
# Text extraction from repository elements
# ---------------------------------------------------------------------------

def _pick_rdg(app_elem: etree._Element, ms_sigil: str) -> etree._Element | None:
    """From an <app> element, pick the <rdg> whose wit includes ms_sigil."""
    rdgs = app_elem.findall("rdg")
    if not rdgs:
        return None
    for rdg in rdgs:
        wits = (rdg.get("wit") or "").split()
        if ms_sigil in wits:
            return rdg
    # Fall back to first rdg
    return rdgs[0]


def _extract_body_text(body_elem: etree._Element, ms_sigil: str) -> str:
    """Recursively extract text from a body element, resolving <app>/<rdg>."""
    parts: list[str] = []

    # Leading text of the body element itself
    if body_elem.text:
        parts.append(body_elem.text)

    for child in body_elem:
        tag = etree.QName(child).localname
        if tag == "app":
            rdg = _pick_rdg(child, ms_sigil)
            if rdg is not None:
                parts.append(_extract_body_text(rdg, ms_sigil))
        elif tag in ("gap", "note", "bibl", "ref"):
            # Skip editorial marks
            pass
        else:
            parts.append(_extract_body_text(child, ms_sigil))
        # Tail text follows the child
        if child.tail:
            parts.append(child.tail)

    return " ".join(p.strip() for p in parts if p.strip())


def _get_repo_text(item: etree._Element, ms_sigil: str) -> str:
    """Extract the primary text from a repository item (ant/res/prayer)."""
    tag = etree.QName(item).localname
    texts: list[str] = []

    if tag == "ant":
        # Antiphon: one or more <aBody> elements
        for body in item.findall("aBody"):
            wits = (body.get("wit") or "").split()
            # Use this body if: it has no wit restriction, OR ms_sigil is listed
            if not wits or ms_sigil in wits:
                t = _extract_body_text(body, ms_sigil)
                if t:
                    texts.append(t)
                    break  # use first matching body
        if not texts:
            # Fall back: use any aBody
            for body in item.findall("aBody"):
                t = _extract_body_text(body, ms_sigil)
                if t:
                    texts.append(t)
                    break

    elif tag == "res":
        # Respond: <rBody> for main text + <verses>/<vBody> for verse
        for body in item.findall("rBody"):
            wits = (body.get("wit") or "").split()
            if not wits or ms_sigil in wits:
                t = _extract_body_text(body, ms_sigil)
                if t:
                    texts.append(t)
                    break
        if not texts:
            for body in item.findall("rBody"):
                t = _extract_body_text(body, ms_sigil)
                if t:
                    texts.append(t)
                    break
        # Append verse if present
        verses = item.find("verses")
        if verses is not None:
            for vbody in verses.findall("vBody"):
                wits = (vbody.get("wit") or "").split()
                if not wits or ms_sigil in wits:
                    vt = _extract_body_text(vbody, ms_sigil)
                    if vt:
                        texts.append("V. " + vt)
                        break

    elif tag == "prayer":
        for body in item.findall("pBody"):
            wits = (body.get("wit") or "").split()
            if not wits or ms_sigil in wits:
                t = _extract_body_text(body, ms_sigil)
                if t:
                    texts.append(t)
                    break
        if not texts:
            for body in item.findall("pBody"):
                t = _extract_body_text(body, ms_sigil)
                if t:
                    texts.append(t)
                    break

    return " ".join(texts).strip()


# ---------------------------------------------------------------------------
# Manuscript XML walker
# ---------------------------------------------------------------------------

def _iter_ms_chunks(
    ms_root: etree._Element,
    ms_sigil: str,
    repo: dict[str, etree._Element],
) -> Iterator[tuple[str, str, str]]:
    """
    Walk a manuscript XML element tree and yield (day_num, service_slug, text).

    Resolves <xptr> references against the repository dict.
    Inline text elements (rubric, incipit) are emitted directly.
    """

    # Resolve a single xptr element to text
    def _resolve_xptr(xptr_elem: etree._Element) -> str:
        from_attr = xptr_elem.get("from") or ""
        m = re.match(r"ID\(([^)]+)\)", from_attr)
        if not m:
            return ""
        item_id = m.group(1)
        item = repo.get(item_id)
        if item is None:
            return ""
        return _get_repo_text(item, ms_sigil)

    # Extract all text from a generic element, resolving xptrs inside it
    def _elem_text(elem: etree._Element) -> str:
        parts: list[str] = []
        if elem.text and elem.text.strip():
            parts.append(elem.text.strip())
        for child in elem:
            if not isinstance(child.tag, str):
                continue
            child_tag = etree.QName(child).localname
            if child_tag == "xptr":
                t = _resolve_xptr(child)
                if t:
                    parts.append(t)
            elif child_tag in ("gap",):
                pass  # skip
            else:
                t = _elem_text(child)
                if t:
                    parts.append(t)
            if child.tail and child.tail.strip():
                parts.append(child.tail.strip())
        return " ".join(parts)

    def _clean(s: str) -> str:
        # Collapse whitespace and trim entity artefacts
        s = re.sub(r"\s+", " ", s)
        # Remove bare entity placeholders like & ; that weren't resolved
        s = re.sub(r"&\s*;", "", s)
        return s.strip()

    # Walk the tree
    text_elem = ms_root.find("text")
    if text_elem is None:
        text_elem = ms_root
    body = text_elem.find("body")
    if body is None:
        body = text_elem

    # Find all Day elements anywhere under body
    for day_elem in body.iter():
        if not isinstance(day_elem.tag, str):
            continue  # skip comments, PIs
        if etree.QName(day_elem).localname != "Day":
            continue
        day_num_str = day_elem.get("num") or "0"
        try:
            day_num = int(day_num_str)
        except ValueError:
            day_num = 0

        for svc_elem in day_elem:
            if not isinstance(svc_elem.tag, str):
                continue
            svc_tag = etree.QName(svc_elem).localname
            if svc_tag != "service":
                continue
            service_name = (svc_elem.get("name") or "office").lower()
            service_slug = re.sub(r"[^a-z0-9]+", "_", service_name).strip("_")

            # Walk all descendants of this service element
            for elem in svc_elem.iter():
                if not isinstance(elem.tag, str):
                    continue
                elem_tag = etree.QName(elem).localname

                if elem_tag == "Day":
                    # Don't recurse into nested Day elements
                    break

                if elem_tag in (
                    "antiphon", "invitatory", "respond", "prayer",
                    "hymn", "lection", "incipit", "rubric",
                ):
                    raw = _elem_text(elem)
                    text = _clean(raw)
                    if text:
                        label = elem_tag
                        yield (day_num, service_slug, label, text)


# ---------------------------------------------------------------------------
# Per-manuscript processing
# ---------------------------------------------------------------------------

def _process_manuscript(
    zf: zipfile.ZipFile,
    ms_stem: str,
    ms_sigil: str,
    shortname: str,
    date_desc: str,
    earliest_year: int,
    repo: dict[str, etree._Element],
    out_path: Path,
    force: bool,
) -> Work | None:
    """Parse one manuscript XML file and write the output JSON."""
    zip_path = f"cursusProject/content/mss/{ms_stem}.xml"

    try:
        raw = zf.read(zip_path)
    except KeyError:
        log.warning("  Not found in ZIP: %s", zip_path)
        return None

    # lxml can't resolve the external entity declarations; strip them
    raw_str = raw.decode("utf-8", errors="replace")
    # Remove internal subset that declares external entities
    raw_str = re.sub(r"<!DOCTYPE[^[]*\[.*?\]>", "", raw_str, flags=re.DOTALL)
    raw_str = re.sub(r"<!DOCTYPE[^>]*>", "", raw_str)
    # Replace unresolved entity references with their conventional equivalents
    # &R; = "R." (respond sigil), &V; = "V." (versicle), etc.
    entity_map = {
        "&R;": "R.", "&V;": "V.", "&A;": "A.", "&O;": "℟.",
        "&Cant;": "[Cant.]", "&I;": "I.", "&AC;": "[AC]",
        "&teiHeader;": "", "&punctus;": ".",
    }
    for ent, sub in entity_map.items():
        raw_str = raw_str.replace(ent, sub)
    # Drop any remaining &name; entities we don't know
    raw_str = re.sub(r"&[A-Za-z][A-Za-z0-9_.-]*;", "", raw_str)

    try:
        ms_root = etree.fromstring(raw_str.encode("utf-8"))
    except etree.XMLSyntaxError as exc:
        log.error("  XML parse error for %s: %s", ms_stem, exc)
        return None

    # Collect chunks
    paragraphs: list[dict] = []
    seq_counters: dict[tuple[int, str], int] = {}

    for day_num, service_slug, label, text in _iter_ms_chunks(ms_root, ms_sigil, repo):
        key = (day_num, service_slug)
        seq_counters[key] = seq_counters.get(key, 0) + 1
        seq = seq_counters[key]

        ref = slugify_ref(
            f"CURSUS.{ms_sigil}.{day_num:03d}.{service_slug}.{seq:04d}"
        )
        # Prefix with element type so rubrics are distinguishable
        if label == "rubric":
            full_text = f"[Rubric] {text}"
        elif label == "lection":
            full_text = f"[Lection] {text}"
        else:
            full_text = text

        paragraphs.append({"ref": ref, "text": full_text})

    if not paragraphs:
        log.warning("  No chunks extracted from %s", ms_stem)
        return None

    work = Work(
        work_id=f"{SOURCE_ID}/{ms_sigil}",
        source_id=SOURCE_ID,
        author=None,
        title=f"{shortname} ({date_desc})",
        # Benedictine Office tradition: content origin ~6th–10th c.
        date_composed=800,
        date_range=(400, 1050),
        date_confidence="approximate",
        genre="liturgical",
        language="lat",
        tradition="latin",
        license="cc-by-nc-4.0",
        provenance_url=_ZIP_URL,
        edition=f"CURSUS project, Zenodo 5090613; ms: {ms_sigil} ({date_desc})",
    )

    out_path.write_text(
        json.dumps(
            {"work": work.model_dump(), "paragraphs": paragraphs},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    log.info("  Wrote %s (%d chunks)", out_path.name, len(paragraphs))
    return work


# ---------------------------------------------------------------------------
# Ingestor entry point
# ---------------------------------------------------------------------------

def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Download CURSUS ZIP and write per-manuscript JSON output files."""
    zip_dir = Path(output_dir) / "_zips"
    zip_dir.mkdir(parents=True, exist_ok=True)
    zip_path = zip_dir / _ZIP_NAME

    _ensure_zip(zip_path, force)

    out_root = Path(output_dir) / SOURCE_ID
    out_root.mkdir(parents=True, exist_ok=True)

    works: list[Work] = []

    with zipfile.ZipFile(zip_path) as zf:
        log.info("Loading repository items…")
        repo = _load_repository(zf)

        for ms_stem, (sigil, shortname, date_desc, earliest_year) in tqdm(
            _MS_INFO.items(), desc="Processing manuscripts"
        ):
            out_path = out_root / f"{sigil}.json"
            if out_path.exists() and not force:
                log.debug("  Skipping %s (already exists)", out_path.name)
                with open(out_path) as f:
                    saved = json.load(f)
                works.append(Work(**saved["work"]))
                continue

            work = _process_manuscript(
                zf, ms_stem, sigil, shortname, date_desc,
                earliest_year, repo, out_path, force,
            )
            if work:
                works.append(work)

    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
