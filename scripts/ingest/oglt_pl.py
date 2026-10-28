"""
Ingestor for the OGLT Patrologia Latina (OpenGreekAndLatin).

Source: https://github.com/OpenGreekAndLatin/patrologia_latina-dev
Format: TEI/EpiDoc XML, Migne Patrologia Latina volumes
License: CC-BY-SA 4.0

Acquisition
-----------
Shallow-clone the repo into ``data/raw/oglt-pl/`` using git.
On ``force=True`` we pull the latest changes.

File selection
--------------
We prefer the ``split/`` directory (one work per XML file).  If ``split/``
is absent or empty we fall back to ``corrected/`` (one volume per file;
each work is still encoded as a distinct ``<div>`` within the volume).

Filtering
---------
- Works dated after the collection period (``patristica.period``) are skipped.
- If dates cannot be extracted from the header, we try a substring-match
  of the author name against ``_patristic_meta.AUTHORS``.
- Default: include when uncertain.

Attribution index (``data/oglt_pl_index.csv``)
----------------------------------------------
The TEI headers are unreliable: a third have no author/title at all, and the
rest carry the *volume's* first author and title (``sourceDesc/monogr``), so
e.g. every PL16 work was titled "De Officiis" and Avitus of Vienne was filed
under Gelasius I.  Author / title / floruit dates therefore come from
``scripts/ingest/data/oglt_pl_index.csv``, which has one row per split file
(keyed by filename stem).  It was built by matching each split file's text
against the CTS-organised copy of the same corpus in the repo's own
``data/`` tree, whose ``__cts__.xml`` catalog files give a groupname
(author) and work title (same repo, same CC-BY-SA 4.0 licence; column
``cts_urn`` records the match), then hand-curated: author names normalised
to Latin forms, floruit dates added, misattributions corrected
(pseudepigrapha, Ambrosiaster, Quodvultdeus, letters *to* a pope filed
under the pope, ...), works and forgeries after the period dated, and early-modern
editorial apparatus (indices, admonitiones, prolegomena, notitiae by
Coustant, Gallandi, the Maurists, Migne's editors, ...) attributed to its
editor.

Column ``basis``:

- ``ogl-cts`` — catalog author (normalised) and title used as-is;
- ``ogl-cts+curated`` / ``tei+curated`` / ``curated`` — hand-corrected,
  starting from the catalog match, the TEI header, or nothing;
- ``editorial`` — early-modern editorial apparatus (excluded);
- ``scripture`` — biblical text of Jerome's "Divina bibliotheca" (PL28-29),
  which duplicates the Vulgate scripture source and is not patristic
  (excluded; Jerome's own prefaces are kept via ``keep_refs``);
- ``duplicate`` — stray file duplicating another split file (excluded).

Column ``keep_refs`` (optional) restricts a work to some of its paragraphs:
space-separated items, each either ``REF`` (that ref and its descendants,
``REF.*``) or ``A..B`` (inclusive positional range from ref A to ref B).
Filtering by ref is idempotent, so it can be re-applied to saved JSON.

A split file that holds several works gets *part rows* (#306): ``stem`` is
``{file stem}/{part}`` (``PL67_11_CO/sardica``, ``part`` a lower-case slug)
and ``keep_refs`` selects the part's paragraphs from the whole file.  Each part
is its own work, ``oglt-pl/{author}/{file stem}-{part}``, written beside the
file's JSON as ``{file stem}-{part}.json``; the file's own row keeps the rest
(its ``keep_refs`` lists what is left), so its work id stays the same.  Parts
are cut from a fresh parse of the XML on every run, and a part file whose row
is gone is removed.

An index row overrides whatever the TEI header gives.  Its dates go through
the same collection-period filter as TEI dates (``patristica.period`` →
excluded; works straddling the boundary keep ``date_composed`` as the midpoint).

``ingest()`` re-applies the index to already-written JSON files without
re-parsing or pulling (rewriting or deleting them as needed), so edits to
the CSV propagate on a plain, non-``--force`` run.

Canonical references
--------------------
``{work_prefix}.{div_n_path}.{para_index}``

Where *work_prefix* is derived from the CTS URN if present, otherwise from
the filename stem (``PL67_48_HO`` → ``PL67.HO``).
"""

from __future__ import annotations

import csv
import functools
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from lxml import etree
from tqdm import tqdm

from patristica.models import DateConfidence, Work
from patristica.period import work_in_period
from scripts.ingest._clone import ensure_clone
from scripts.ingest._common import dedupe_refs, slugify_ref
from scripts.ingest._patristic_meta import AUTHORS

log = logging.getLogger(__name__)

SOURCE_ID = "oglt-pl"

_REPO_URL = "https://github.com/OpenGreekAndLatin/patrologia_latina-dev.git"

_TEI = "http://www.tei-c.org/ns/1.0"
_XML_NS = "http://www.w3.org/XML/1998/namespace"


_STRUCTURAL_DIV_TYPES = frozenset({
    "textpart", "book", "chapter", "section", "part",
    "epistle", "sermon", "commentary", "prologue", "appendix",
    "praefatio", "fragment", "inscription",
})

_SKIP_ELEMENTS = frozenset({
    "head", "note", "pb", "lb", "cb", "fw", "figure",
    "table", "speaker", "stage",
})

# Regex to extract a usable work prefix from PL filenames like PL67_48_HO.xml
_PL_FILENAME_RE = re.compile(r"(PL\d+)(?:_\d+)?_([A-Z]+)", re.IGNORECASE)

_PL_INDEX_PATH = Path(__file__).parent / "data" / "oglt_pl_index.csv"
_INDEX_BASES = frozenset({
    "ogl-cts", "ogl-cts+curated", "tei+curated", "curated", "editorial", "scripture", "duplicate",
})
# Rows with these bases are dropped from the corpus regardless of date.
_EXCLUDED_BASES = frozenset({"editorial", "scripture", "duplicate"})


@dataclass(frozen=True)
class PLIndexEntry:
    """Curated attribution for one OGLT PL split file (see module docstring)."""

    author: str
    title: str
    date_range: tuple[int, int] | None
    basis: str
    keep_refs: tuple[str, ...] = ()

    @property
    def excluded(self) -> bool:
        """True when the work is dropped (excluded basis or dated after the period)."""
        return self.basis in _EXCLUDED_BASES or not work_in_period(self.date_range)


@functools.cache
def _load_pl_index(path: Path = _PL_INDEX_PATH) -> dict[str, PLIndexEntry]:
    """Load the stem → attribution index; ``#`` lines are comments."""
    with path.open(encoding="utf-8", newline="") as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        index: dict[str, PLIndexEntry] = {}
        for row in rows:
            stem = row["stem"]
            if "/" in stem:
                part = stem.split("/", 1)[1]
                if not re.fullmatch(r"[a-z][a-z0-9]*", part):
                    raise ValueError(f"{path}: part row {stem!r} needs a lower-case slug")
                if not (row.get("keep_refs") or "").strip():
                    raise ValueError(f"{path}: part row {stem!r} needs keep_refs")
            if not row["author"].strip() or not row["title"].strip():
                raise ValueError(f"{path}: row {stem!r} lacks author or title")
            if row["basis"] not in _INDEX_BASES:
                raise ValueError(f"{path}: row {stem!r} has unknown basis {row['basis']!r}")
            if stem in index:
                raise ValueError(f"{path}: duplicate stem {stem!r}")
            start, end = row["date_start"].strip(), row["date_end"].strip()
            if bool(start) != bool(end):
                raise ValueError(f"{path}: row {stem!r} needs both or neither date bound")
            date_range = (int(start), int(end)) if start else None
            if date_range and date_range[0] > date_range[1]:
                raise ValueError(f"{path}: row {stem!r} has inverted date range")
            keep_refs = tuple((row.get("keep_refs") or "").split())
            index[stem] = PLIndexEntry(
                row["author"].strip(), row["title"].strip(), date_range, row["basis"], keep_refs
            )
    return index


def _parts_of(stem: str) -> list[tuple[str, PLIndexEntry]]:
    """The part rows of split file *stem*, as ``(part, entry)``, in index order."""
    prefix = f"{stem}/"
    return [(key[len(prefix):], entry) for key, entry in _load_pl_index().items()
            if key.startswith(prefix)]


def _part_path(out_path: Path, part: str) -> Path:
    """Where part *part* of the split file written to *out_path* goes."""
    return out_path.with_name(f"{out_path.stem}-{part}.json")


def _filter_paragraphs(
    paragraphs: list[dict[str, str]], keep_refs: tuple[str, ...], stem: str
) -> list[dict[str, str]]:
    """Keep only the paragraphs selected by *keep_refs* (see module docstring)."""
    refs = [p["ref"] for p in paragraphs]
    keep: set[int] = set()
    for item in keep_refs:
        if ".." in item:
            first, last = item.split("..", 1)
            if first not in refs or last not in refs:
                raise ValueError(f"{stem}: keep_refs range {item!r} names a missing ref")
            lo, hi = refs.index(first), refs.index(last)
            if lo > hi:
                raise ValueError(f"{stem}: keep_refs range {item!r} is reversed")
            keep.update(range(lo, hi + 1))
        else:
            hits = {i for i, r in enumerate(refs) if r == item or r.startswith(item + ".")}
            if not hits:
                raise ValueError(f"{stem}: keep_refs prefix {item!r} matches no paragraph")
            keep |= hits
    return [p for i, p in enumerate(paragraphs) if i in keep]


def _work_id(author: str | None, stem: str) -> str:
    """``oglt-pl/{author_slug}/{stem}`` — the stem keeps it unique per split file."""
    author_slug = re.sub(r"[^a-z0-9]+", "-", (author or "unknown").lower()).strip("-")
    return f"{SOURCE_ID}/{author_slug}/{stem.lower()}"


def _apply_pl_index(
    work: Work, stem: str, paragraphs: list[dict[str, str]]
) -> tuple[Work, list[dict[str, str]]] | None:
    """Override *work*'s author/title/dates (and paragraph selection) from the index.

    Returns ``(work, paragraphs)`` unchanged when *stem* is not indexed,
    ``None`` when the row excludes the work (editorial / scripture / duplicate
    basis, or dated after the period), else an updated copy.  Idempotent.
    """
    entry = _load_pl_index().get(stem)
    if entry is None:
        return work, paragraphs
    return _apply_entry(work, stem, paragraphs, entry)


def _apply_entry(
    work: Work, stem: str, paragraphs: list[dict[str, str]], entry: PLIndexEntry
) -> tuple[Work, list[dict[str, str]]] | None:
    """Apply one index row to *work*; *stem* names the work (a part's is ``{stem}-{part}``)."""
    if entry.excluded:
        return None
    if entry.date_range is None:
        date_composed, date_confidence = None, "uncertain"
    else:
        lo, hi = entry.date_range
        date_composed, date_confidence = (lo + hi) // 2, "approximate"
    if entry.keep_refs:
        paragraphs = _filter_paragraphs(paragraphs, entry.keep_refs, stem)
    updated = work.model_copy(update={
        "work_id": _work_id(entry.author, stem),
        "author": entry.author,
        "title": entry.title,
        "date_composed": date_composed,
        "date_range": entry.date_range,
        "date_confidence": date_confidence,
    })
    return updated, paragraphs


def _ensure_repo(repo_dir: Path, force: bool) -> None:
    """Clone the repo if absent; pull latest on force (not offline, #215). Its git
    dir lives in ``_gitdirs/`` so the tree can be tracked (#244)."""
    ensure_clone(_REPO_URL, repo_dir, "OGLT Patrologia Latina", force)


def _extract_dates(
    root: etree._Element,
) -> tuple[int | None, tuple[int, int] | None, DateConfidence]:
    """Extract composition dates from teiHeader/profileDesc/creation/date."""
    ns = {"tei": _TEI}
    date_el = root.find(".//tei:profileDesc/tei:creation/tei:date", ns)
    if date_el is None:
        return None, None, "uncertain"

    not_before_s = date_el.get("notBefore") or date_el.get("when")
    not_after_s = date_el.get("notAfter") or date_el.get("when")

    def _parse_year(s: str | None) -> int | None:
        if not s:
            return None
        m = re.search(r"-?(\d{3,4})", s)
        if m:
            year = int(m.group(1))
            return -year if s.startswith("-") else year
        return None

    y_before = _parse_year(not_before_s)
    y_after = _parse_year(not_after_s)

    if y_before is None and y_after is None:
        return None, None, "uncertain"
    if y_before == y_after:
        return y_before, None, "established"

    date_range: tuple[int, int] | None = None
    date_composed: int | None = None
    if y_before is not None and y_after is not None:
        date_range = (y_before, y_after)
        date_composed = (y_before + y_after) // 2
    elif y_before is not None:
        date_composed = y_before
    else:
        date_composed = y_after

    return date_composed, date_range, "approximate"


def _lookup_author_dates(
    author_name: str,
) -> tuple[int | None, tuple[int, int] | None, DateConfidence]:
    """Try to find date info for *author_name* from the patristic metadata table."""
    name_lower = author_name.lower()
    for meta in AUTHORS.values():
        if meta.full_name.lower() in name_lower or name_lower in meta.full_name.lower():
            birth, death = meta.dates
            return death, (birth, death), "approximate"
    return None, None, "uncertain"


def _element_inner_text(el: etree._Element) -> str:
    """Collect all text inside an element, stripping child element tags."""
    parts: list[str] = []
    if el.text:
        parts.append(el.text)
    for child in el:
        parts.append(_element_inner_text(child))
        if child.tail:
            parts.append(child.tail)
    return "".join(parts)


def _extract_paragraphs(
    body_el: etree._Element,
    work_prefix: str,
    ns: dict[str, str],
) -> list[dict[str, str]]:
    """Recursively extract paragraphs from a TEI body or edition div."""
    records: list[dict[str, str]] = []

    def _walk(element: etree._Element, path_parts: list[str]) -> None:
        tag = etree.QName(element.tag).localname if element.tag != etree.Comment else ""

        if tag in ("p", "ab"):
            text = _element_inner_text(element).strip()
            text = re.sub(r"\s+", " ", text)
            if text:
                ref = slugify_ref(".".join([work_prefix] + path_parts))
                records.append({"ref": ref, "text": text})
            return

        if tag == "l":
            # Verse line — collect a group of lines into one paragraph record
            # (handled by parent <lg> below)
            text = _element_inner_text(element).strip()
            text = re.sub(r"\s+", " ", text)
            if text:
                ref = slugify_ref(".".join([work_prefix] + path_parts))
                records.append({"ref": ref, "text": text})
            return

        if tag == "div":
            div_type = element.get("type", "")
            if div_type in _STRUCTURAL_DIV_TYPES or div_type == "":
                n = element.get("n", "")
                new_parts = path_parts + [n] if n and re.match(r"^[\w\-]+$", n) else path_parts
                for child in element:
                    _walk(child, new_parts)
                return

        if tag not in _SKIP_ELEMENTS:
            for child in element:
                _walk(child, path_parts)

    for child in body_el:
        _walk(child, [])

    return dedupe_refs(records)


def _work_prefix_from_filename(xml_path: Path) -> str:
    """Derive a stable work prefix from a PL filename like ``PL67_48_HO.xml``."""
    m = _PL_FILENAME_RE.search(xml_path.stem)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    # Fall back to the stem with non-alphanumeric chars replaced by dots
    return re.sub(r"[^A-Za-z0-9]+", ".", xml_path.stem).strip(".")


def _parse_oglt_pl_file(
    xml_path: Path, apply_index: bool = True,
) -> tuple[Work, list[dict[str, str]]] | None:
    """Parse a single OGLT PL TEI/EpiDoc file.

    Returns ``(Work, paragraphs)`` or ``None`` if the file should be skipped.
    With ``apply_index=False`` the file's index row is not applied: the whole
    file, as its part rows cut it.
    """
    try:
        tree = etree.parse(str(xml_path))
    except etree.XMLSyntaxError as exc:
        log.warning("XML parse error in %s: %s", xml_path, exc)
        return None

    root = tree.getroot()
    ns = {"tei": _TEI}

    # --- Title & Author ---
    # titleStmt/title is often empty or a generic "Patrologiae Cursus Completus" header.
    # titleStmt/author is always a placeholder <author ref="urn:tmp"/> with no text.
    # The real metadata lives in sourceDesc/listBibl/biblStruct/monogr — take the first
    # non-empty author and title found there.
    title_el = root.find(".//tei:teiHeader/tei:fileDesc/tei:titleStmt/tei:title", ns)
    title = (title_el.text or "").strip() if title_el is not None else ""

    author: str | None = None

    # Try sourceDesc monogr for both author and title
    for monogr_el in root.findall(".//tei:teiHeader/tei:fileDesc/tei:sourceDesc//tei:monogr", ns):
        if author is None:
            auth_el = monogr_el.find("tei:author", ns)
            if auth_el is not None:
                candidate = " ".join((auth_el.text or "").split())
                if candidate:
                    author = candidate
        if not title or re.search(r"patrologiae\s+cursus\s+completus", title, re.IGNORECASE):
            t_el = monogr_el.find("tei:title", ns)
            if t_el is not None:
                candidate = " ".join((t_el.text or "").split())
                if candidate and not re.search(r"patrologiae\s+cursus\s+completus", candidate, re.IGNORECASE):
                    title = candidate
        if author and title:
            break

    # Final fallback: filename stem (e.g. "PL10_10_56" — stable volume+column identifier)
    if not title or re.search(r"patrologiae\s+cursus\s+completus", title, re.IGNORECASE):
        title = xml_path.stem

    # --- Body element ---
    edition_div = root.find(".//tei:text/tei:body/tei:div[@type='edition']", ns)
    body_el = edition_div if edition_div is not None else root.find(".//tei:text/tei:body", ns)
    if body_el is None:
        log.debug("No body content in %s — skipping", xml_path)
        return None

    # --- CTS URN for work prefix ---
    cts_urn = ""
    if edition_div is not None:
        cts_urn = edition_div.get("n", "")
    if not cts_urn:
        text_el = root.find(".//tei:text", ns)
        if text_el is not None:
            cts_urn = text_el.get(f"{{{_XML_NS}}}base", "")

    # work_id: use author slug + filename stem for a stable, human-readable identifier.
    # The filename (e.g. PL12_0_SAN) is unique per file and encodes PL volume + column,
    # so collision-free even when multiple files share the same author/title.
    work_id = _work_id(author, xml_path.stem)

    # work_prefix for canonical refs: derive from CTS URN if proper, else from filename.
    if cts_urn and cts_urn.startswith("urn:cts:"):
        cts_local = cts_urn.rsplit(":", 1)[-1]
        cts_parts = cts_local.split(".")
        a_id = cts_parts[0] if len(cts_parts) > 0 else ""
        w_id = cts_parts[1] if len(cts_parts) > 1 else ""
        work_prefix = f"{a_id}.{w_id}" if (a_id and w_id) else _work_prefix_from_filename(xml_path)
    else:
        work_prefix = _work_prefix_from_filename(xml_path)

    provenance_url = f"https://github.com/OpenGreekAndLatin/patrologia_latina-dev/blob/master/split/{xml_path.name}"

    # --- Dates ---
    date_composed, date_range, date_confidence = _extract_dates(root)
    if date_composed is None and author:
        date_composed, date_range, date_confidence = _lookup_author_dates(author)

    # Collection-period filter (an attribution-index row, applied below, takes precedence)
    if not work_in_period(date_range) and xml_path.stem not in _load_pl_index():
        log.debug("Skipping work after the collection period %s (date_range=%s)",
                  work_id, date_range)
        return None

    work = Work(
        work_id=work_id,
        source_id=SOURCE_ID,
        author=author,
        title=title,
        date_composed=date_composed,
        date_range=date_range,
        date_confidence=date_confidence,
        genre="patristic",
        language="lat",
        tradition="latin",
        license="cc-by-sa-4.0",
        provenance_url=provenance_url,
        edition=None,
        translation_of=None,
    )

    paragraphs = _extract_paragraphs(body_el, work_prefix, ns)
    if not apply_index:
        return work, paragraphs
    indexed = _apply_pl_index(work, xml_path.stem, paragraphs)
    if indexed is None:
        log.debug("Skipping %s: excluded by attribution index", xml_path.stem)
    return indexed


def _collect_xml_files(repo_dir: Path) -> list[Path]:
    """Return the list of XML files to process, preferring ``split/`` over ``corrected/``."""
    split_dir = repo_dir / "split"
    corrected_dir = repo_dir / "corrected"

    split_files = sorted(split_dir.rglob("*.xml")) if split_dir.exists() else []
    # Filter out __cts__.xml and catalog files
    split_files = [p for p in split_files if p.name != "__cts__.xml"]

    if split_files:
        log.info("Using split/ directory: %d XML files found", len(split_files))
        return split_files

    corrected_files = sorted(corrected_dir.rglob("*.xml")) if corrected_dir.exists() else []
    corrected_files = [p for p in corrected_files if p.name != "__cts__.xml"]

    if corrected_files:
        log.info("split/ empty/absent — falling back to corrected/: %d XML files", len(corrected_files))
        return corrected_files

    # Last resort: scan entire repo
    all_files = [
        p for p in sorted(repo_dir.rglob("*.xml"))
        if p.name != "__cts__.xml"
        and not any(part.startswith(".") for part in p.parts)
    ]
    log.info("No split/ or corrected/ found — scanning repo: %d XML files", len(all_files))
    return all_files


def _write_parts(xml_path: Path, out_path: Path) -> list[Work]:
    """Write the part works of *xml_path* (see "part rows"); remove stale part files."""
    parts = _parts_of(xml_path.stem)
    wanted = {_part_path(out_path, part) for part, _ in parts}
    stale = re.compile(rf"{re.escape(xml_path.stem)}-[a-z][a-z0-9]*\.json")
    if out_path.parent.is_dir():
        for path in out_path.parent.glob(f"{xml_path.stem}-*.json"):
            if stale.fullmatch(path.name) and path not in wanted:
                log.info("Removing %s: its part row is gone", path)
                path.unlink()
    if not parts:
        return []
    parsed = _parse_oglt_pl_file(xml_path, apply_index=False)
    if parsed is None:
        raise ValueError(f"{xml_path.name}: has part rows but no text")
    whole, paragraphs = parsed
    works: list[Work] = []
    for part, entry in parts:
        applied = _apply_entry(whole, f"{xml_path.stem}-{part}", paragraphs, entry)
        if applied is None:
            continue
        work, kept = applied
        path = _part_path(out_path, part)
        payload = json.dumps({"work": work.model_dump(), "paragraphs": kept},
                             ensure_ascii=False, indent=2)
        if not path.exists() or path.read_text(encoding="utf-8") != payload:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")
        works.append(work)
    return works


def ingest(output_dir: Path, force: bool = False) -> list[Work]:
    """Clone/pull the OGLT PL repo and ingest all Latin text editions.

    Parameters
    ----------
    output_dir: Root raw output directory (``data/raw``).
    force:      If True, pull latest git changes before processing.

    Returns
    -------
    List of ``Work`` records written.
    """
    repo_dir = output_dir / SOURCE_ID
    _ensure_repo(repo_dir, force)

    xml_files = _collect_xml_files(repo_dir)
    if not xml_files:
        raise FileNotFoundError(f"No XML files found in {repo_dir}")

    log.info("Found %d OGLT PL text files to process", len(xml_files))

    works: list[Work] = []
    skipped = 0
    refreshed = 0

    for xml_path in tqdm(xml_files, desc="OGLT PL ingest"):
        rel = xml_path.relative_to(repo_dir)
        out_path = output_dir / SOURCE_ID / rel.with_suffix(".json")
        works.extend(_write_parts(xml_path, out_path))

        if out_path.exists() and not force:
            saved = json.loads(out_path.read_text(encoding="utf-8"))
            saved_work = Work(**saved["work"])
            applied = _apply_pl_index(saved_work, xml_path.stem, saved["paragraphs"])
            if applied is None:
                log.info("Removing %s: excluded by attribution index", out_path)
                out_path.unlink()
                skipped += 1
                continue
            work, paragraphs = applied
            if work != saved_work or paragraphs != saved["paragraphs"]:
                saved["work"] = work.model_dump()
                saved["paragraphs"] = paragraphs
                out_path.write_text(json.dumps(saved, ensure_ascii=False, indent=2), encoding="utf-8")
                refreshed += 1
            works.append(work)
            continue

        result = _parse_oglt_pl_file(xml_path)
        if result is None:
            skipped += 1
            continue

        work, paragraphs = result
        if not paragraphs:
            log.debug("No paragraphs extracted from %s — skipping", xml_path)
            skipped += 1
            continue

        out_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"work": work.model_dump(), "paragraphs": paragraphs}
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        works.append(work)

    log.info(
        "OGLT PL ingestion complete: %d works (%d metadata refreshed), %d skipped",
        len(works),
        refreshed,
        skipped,
    )
    return works


if __name__ == "__main__":
    from scripts.ingest._ingestor_main import ingestor_main
    ingestor_main(ingest, SOURCE_ID)
