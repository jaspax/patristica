"""
Shared machinery for the table-driven CCEL carving ingestors (``anf_works``,
``npnf_works``).

Each ingestor declares a table of ``_WorkSpec`` rows: one properly attributed
Work made of one or more ThML divs (``_Part``) of a CCEL ANF/NPNF volume.  The
generic series ingestors (``ccel_anf``, ``ccel_npnf1``, ``ccel_npnf2``) must
skip those divs, so each is registered in ``_ccel_common.EXCLUDED_DIVS`` with
the carving ingestor's source_id.

Inside an extracted div, nested divs are left out when their ``@title`` marks
them as editorial apparatus (``_EDITORIAL_TITLE_RE``) or when they are
registered as ``"non-text: …"`` in ``EXCLUDED_DIVS``; separator rules
("————") are dropped too.

Canonical refs are ``{ref_prefix}[.{part label}].{div3}.{div4}[.n]`` — the
``_ccel_common._extract_paragraphs_from_div1`` scheme applied to each part.
Output: ``{output_dir}/{source_id}/{volume}/{slug}.json`` with work_id
``{source name}/{slug}``; only changed files are rewritten and outputs no
longer in the table are removed.  Rows composed after the collection period are skipped (their
divs stay registered so they do not fall back into the generic blob).
"""

from __future__ import annotations

import copy
import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from lxml import etree

from patristica.models import DateConfidence, Genre, Tradition, Work
from patristica.period import work_in_period
from scripts.ingest._ccel_common import (
    EXCLUDED_DIVS,
    _extract_paragraphs_from_div1,
    _find_body,
    download_volume,
)

log = logging.getLogger(__name__)


#: Nested divs (inside an extracted part) whose ``@title`` marks them as
#: editorial apparatus rather than text of the work.
_EDITORIAL_TITLE_RE = re.compile(
    r"^\s*(Elucidations?|Notes?\b|Two Notes|General Note|Introductory (Not(e|ice)|Essay)"
    r"|Translator['’]s (Biographical Notice|Introduct|Preface)|Prefatory Note"
    r"|Title Page)",
    re.IGNORECASE,
)
#: Paragraphs that are only a typographic rule or ornament.
_SEPARATOR_RE = re.compile(r"^[\s—–_\-•·*.]+$")
#: Peter of Alexandria's canons are printed with 12th-century Byzantine
#: commentary; these patterns split canon text from commentary.
_COMMENTARY_START_RE = re.compile(r"^(Balsamon|Zonaras)\b")
_CANON_HEAD_RE = re.compile(r"^Canon [IVXL]+\.$")

#: Volume-id prefix → (cache dir relative to the raw output dir, edition label)
_SERIES: dict[str, tuple[Path, str]] = {
    "anf": (Path("ccel-anf"), "ANF Vol. {n}"),
    "npnf1": (Path("ccel-npnf1"), "NPNF Series 1 Vol. {n}"),
    "npnf2": (Path("ccel-npnf2"), "NPNF Series 2 Vol. {n}"),
}


def _series(volume: str) -> tuple[Path, str]:
    """Return ``(cache dir, edition label)`` for a volume id like ``anf05``/``npnf212``."""
    for prefix in ("npnf1", "npnf2", "anf"):
        if volume.startswith(prefix) and volume[len(prefix):].isdigit():
            cache, label = _SERIES[prefix]
            return cache, label.format(n=int(volume[len(prefix):]))
    raise ValueError(f"Unknown CCEL volume id {volume!r}")


@dataclass(frozen=True)
class _Part:
    div_id: str          # ThML @id of the div holding (part of) the text
    title_check: str     # case-insensitive substring expected in the div's @title
    label: str = ""      # ref segment distinguishing parts of a multi-part work
    drop_leading: int = 0   # leading paragraphs that are the editor's preface
    drop_trailing: int = 0  # trailing paragraphs that are the editor's note
    #: Nested divs (``@id``s inside ``div_id``) to take alone, or to leave out,
    #: when one registered div holds several works (#380).  Refs are those of
    #: the whole div: left-out divs still advance its counters.
    keep: tuple[str, ...] = ()
    skip: tuple[str, ...] = ()


@dataclass(frozen=True)
class _WorkSpec:
    volume: str
    slug: str
    title: str
    author: str | None
    date_composed: int | None
    date_range: tuple[int, int]
    date_confidence: DateConfidence
    tradition: Tradition | None
    ref_prefix: str
    parts: tuple[_Part, ...]
    genre: Genre = "patristic"
    #: ``"canons"`` / ``"commentary"``: keep only canon text or only the
    #: Balsamon/Zonaras commentary (ANF06 Peter of Alexandria).
    split: str | None = None
    #: work_id of the original-language Work in the corpus (``Work.translation_of``).
    translation_of: str | None = None
    #: Re-chunks the extracted paragraphs, e.g. at the verse numbers the edition
    #: prints inline (``_printed_verses.rechunk``, #122).
    rechunk: Callable[[list[dict[str, str]]], list[dict[str, str]]] | None = None


def P(
    div_id: str, title_check: str, label: str = "",
    drop_leading: int = 0, drop_trailing: int = 0,
    keep: tuple[str, ...] = (), skip: tuple[str, ...] = (),
) -> _Part:
    return _Part(div_id, title_check, label, drop_leading, drop_trailing, keep, skip)


def W(
    volume: str, slug: str, title: str, author: str | None,
    date: int | None, rng: tuple[int, int], conf: DateConfidence,
    tradition: Tradition | None, ref_prefix: str, *parts: _Part,
    genre: Genre = "patristic", split: str | None = None,
    rechunk: Callable[[list[dict[str, str]]], list[dict[str, str]]] | None = None,
) -> _WorkSpec:
    return _WorkSpec(volume, slug, title, author, date, rng, conf, tradition,
                     ref_prefix, tuple(parts), genre, split, rechunk=rechunk)


def link_originals(
    works: tuple[_WorkSpec, ...], originals: dict[str, str],
) -> tuple[_WorkSpec, ...]:
    """Return *works* with ``translation_of`` set from *originals* (slug → work_id).

    Raises if a key names no row, so a renamed slug cannot silently drop a link.
    """
    slugs = {s.slug for s in works}
    unknown = sorted(set(originals) - slugs)
    if unknown:
        raise ValueError(f"translation_of keys name no table row: {unknown}")
    return tuple(
        replace(s, translation_of=originals[s.slug]) if s.slug in originals else s
        for s in works
    )


def _norm(text: str) -> str:
    """Casefold and collapse whitespace (CCEL titles contain NBSPs and double spaces)."""
    return " ".join(text.split()).casefold()


def _index_ids(root: etree._Element) -> dict[str, etree._Element]:
    return {
        el.get("id"): el
        for el in root.iter()
        if isinstance(el.tag, str) and el.get("id")
    }


def _editorial_ids(div: etree._Element, volume: str | None = None) -> frozenset[str]:
    """``@id``s of nested divs inside *div* that are editorial (by title, or
    registered as non-text for *volume* in ``EXCLUDED_DIVS``)."""
    non_text = {
        d for d, why in EXCLUDED_DIVS.get(volume or "", {}).items() if why.startswith("non-text")
    }
    out = set()
    for el in div.iterdescendants():
        if not isinstance(el.tag, str) or not el.get("id"):
            continue
        if not re.fullmatch(r"div\d", etree.QName(el.tag).localname):
            continue
        if el.get("id") in non_text or _EDITORIAL_TITLE_RE.match(el.get("title", "")):
            out.add(el.get("id"))
    return frozenset(out)


def _split_commentary(paragraphs: list[dict[str, str]], keep: str) -> list[dict[str, str]]:
    """Keep canon text (``keep="canons"``) or Balsamon/Zonaras commentary."""
    out: list[dict[str, str]] = []
    in_commentary = False
    for para in paragraphs:
        text = para["text"]
        if _CANON_HEAD_RE.match(text):
            in_commentary = False
        elif _COMMENTARY_START_RE.match(text):
            in_commentary = True
        if in_commentary == (keep == "commentary"):
            out.append(para)
    return out


def _is_div(el: etree._Element) -> bool:
    return isinstance(el.tag, str) and re.fullmatch(r"div\d", etree.QName(el.tag).localname) is not None


def _select(div: etree._Element, part: _Part, slug: str) -> tuple[etree._Element, frozenset[str]]:
    """Apply ``part.keep`` / ``part.skip`` to *div*.

    Returns the div to extract (a copy without the paragraphs outside the kept
    divs when ``keep`` is set) and the ``@id``s of the nested divs to leave out.
    Left-out divs are skipped by the extractor, which still counts them, so
    every kept paragraph gets the ref it has when the whole div is extracted.
    """
    if not part.keep and not part.skip:
        return div, frozenset()
    nested = {el.get("id") for el in div.iterdescendants() if _is_div(el)}
    missing = sorted((set(part.keep) | set(part.skip)) - nested)
    if missing:
        raise RuntimeError(f"div {part.div_id!r} has no nested div {missing} (for {slug})")
    skip = set(part.skip)
    if part.keep:
        div = copy.deepcopy(div)
        kept = [el for el in div.iterdescendants() if _is_div(el) and el.get("id") in part.keep]
        path = {a for k in kept for a in k.iterancestors()}
        for parent in path:
            for child in list(parent):
                if child in path or child in kept:
                    continue
                if not _is_div(child):
                    parent.remove(child)
                elif child.get("id"):
                    skip.add(child.get("id"))
                else:
                    raise RuntimeError(f"div without @id next to a kept div (for {slug})")
    return div, frozenset(skip)


def extract_work(spec: _WorkSpec, ids: dict[str, etree._Element]) -> list[dict[str, str]]:
    """Return the ``{"ref", "text"}`` paragraphs of *spec* from an indexed volume."""
    paragraphs: list[dict[str, str]] = []
    for part in spec.parts:
        div = ids.get(part.div_id)
        if div is None:
            raise RuntimeError(f"{spec.volume} has no div {part.div_id!r} (for {spec.slug})")
        if _norm(part.title_check) not in _norm(div.get("title", "")):
            raise RuntimeError(
                f"{spec.volume} div {part.div_id!r} has title {div.get('title')!r}; "
                f"expected it to contain {part.title_check!r} (for {spec.slug})"
            )
        prefix = f"{spec.ref_prefix}.{part.label}" if part.label else spec.ref_prefix
        div, left_out = _select(div, part, spec.slug)
        paras = _extract_paragraphs_from_div1(
            div, prefix, _editorial_ids(div, spec.volume) | left_out)
        paras = paras[part.drop_leading:len(paras) - part.drop_trailing]
        paras = [p for p in paras if not _SEPARATOR_RE.match(p["text"])]
        paragraphs.extend(paras)
    if spec.split:
        paragraphs = _split_commentary(paragraphs, spec.split)
    if spec.rechunk:
        paragraphs = spec.rechunk(paragraphs)
    refs = [p["ref"] for p in paragraphs]
    if len(set(refs)) != len(refs):
        raise RuntimeError(f"Duplicate canonical refs in {spec.slug}")
    return paragraphs


def make_work(spec: _WorkSpec, source_id: str) -> Work:
    _, edition = _series(spec.volume)
    return Work(
        work_id=f"{source_id}/{spec.slug}",
        source_id=source_id,
        author=spec.author,
        title=spec.title,
        date_composed=spec.date_composed,
        date_range=spec.date_range,
        date_confidence=spec.date_confidence,
        genre=spec.genre,
        language="eng",
        tradition=spec.tradition,
        license="public_domain",
        provenance_url=f"https://ccel.org/ccel/s/schaff/{spec.volume}.xml",
        edition=edition,
        translation_of=spec.translation_of,
    )


def ingest_table(
    output_dir: Path, source_id: str, works: tuple[_WorkSpec, ...], force: bool = False,
) -> list[Work]:
    """Write one JSON file per row of *works* (only when its content changed).

    *force* re-downloads the volume XML; otherwise the series cache is used
    as-is.  Outputs no longer produced by the table are removed.
    """
    out_root = output_dir / source_id
    result: list[Work] = []
    produced: set[Path] = set()

    for volume in sorted({s.volume for s in works}):
        cache_dir = output_dir / _series(volume)[0]
        xml_path = download_volume(volume, cache_dir, force=force)
        root = etree.parse(str(xml_path)).getroot()
        if _find_body(root) is None:
            raise RuntimeError(f"No body element found in {xml_path}")
        ids = _index_ids(root)

        for spec in (s for s in works if s.volume == volume):
            if not work_in_period(spec.date_range):
                log.info("Skipping %s: composed after the collection period", spec.slug)
                continue
            paragraphs = extract_work(spec, ids)
            if not paragraphs:
                raise RuntimeError(f"No paragraphs extracted for {spec.slug}")
            work = make_work(spec, source_id)
            out_path = out_root / volume / f"{spec.slug}.json"
            produced.add(out_path)
            content = json.dumps(
                {"work": work.model_dump(), "paragraphs": paragraphs},
                ensure_ascii=False, indent=2,
            )
            if not out_path.exists() or out_path.read_text(encoding="utf-8") != content:
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(content, encoding="utf-8")
                log.info("Wrote %s (%d paragraphs)", out_path, len(paragraphs))
            result.append(work)

    for stale in sorted(out_root.glob("*/*.json")):
        if stale not in produced:
            log.info("Removing %s (no longer in the table)", stale)
            stale.unlink()

    log.info("%s: %d works", source_id, len(result))
    return result
