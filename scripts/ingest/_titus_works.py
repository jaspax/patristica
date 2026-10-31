"""
Shared ingest of TITUS Old Georgian sets as one work per text (#517).

The codices, homiliaries, liturgies, chronicles and translations of #517 are
TITUS sets (see ``_titus.py``) that hold one text or many. Each source module
(``titus_shatberdi``, ``titus_liturgy``, ``titus_translations``,
``titus_chronicles``) names a curated table,
``scripts/ingest/data/titus_{source}.csv``, with one row per text:

``set``
    The set's frame page under ``https://titus.uni-frankfurt.de/texte/``
    (``etcs/cauc/ageo/satberd/satbe.htm``).
``select``
    Which part of the set is the text: ``Label=value`` on TITUS's location
    levels (``Text=Greg.Nyss._Hom.Op.``), several joined with ``&``, and
    alternatives with ``;``; empty for a set that is one text. Every text of a
    set must have a row: a segment no row selects is logged at ERROR (a
    dropped text, #130).
``slug``
    The local work id (``{source}/{slug}``); it is in reader URLs, so never
    rename one. A row with ``skip`` set has none.
``ref``
    The ref prefix (``Satb.GrNyss.HomOp``) and ``units``, the location labels
    that make a unit, ``|``-separated (``Chapter|Page of ed.``). A unit's ref
    is the prefix and its label values (``Satb.GrNyss.HomOp.Intr.67``); text
    before the first value of a label gets ``0`` for it (a title).
``title``, ``author``, ``genre``, ``date_from``, ``date_to``,
``date_composed``, ``date_confidence``, ``external_ids`` (``|``-separated)
    The work's metadata. A translation is dated by its translation and its
    author is the original's author; the translator goes in ``edition``
    (``edition_note``).
``rubrics``
    ``1`` for a liturgical text: TITUS's rubric segments (red ink, the ``b``
    flag) are marked as ``rubric`` spans (#236).
``printed_edition``
    The printed edition TITUS follows, when the set's header names several
    (default: the header's bibliography).
``exclude``
    Locations left out of the text, ``Label=value`` joined with ``|``
    (``Chapter=Notes``: an apparatus TITUS sets as a chapter).
``scripts``
    The Georgian scripts to keep, ``|``-separated (``mx``), for a set that
    gives each line twice: in the manuscript's script and transcribed into
    Mkhedruli (default: every script).
``skip``
    Why a text is left out (members only, out of period, not Christian
    literature): logged, never written.
``note``
    Free text for the curator (not used).

Units: the Old Georgian text of each location (variant readings left out),
cleaned by ``_titus.clean_text`` (supplements, lacunae and notes as editorial
spans). An editor's heading in modern Georgian (``ng``) is kept and marked as
a ``heading``.

Licence: every work is ``_titus.TITUS_LICENSE`` (``unknown`` until TITUS
grants permission, #514), so nothing is translated, embedded, indexed or
published.
"""

from __future__ import annotations

import csv
import json
import logging
import re
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from patristica.models import Work
from scripts.ingest import _titus as T

log = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent / "data"

@dataclass(frozen=True)
class TextRow:
    """One row of a source's table."""

    set: str
    select: tuple[tuple[tuple[str, str], ...], ...]  # alternatives of conditions
    slug: str
    ref: str
    units: tuple[str, ...]
    title: str
    author: str
    genre: str
    date_from: int | None
    date_to: int | None
    date_composed: int | None
    date_confidence: str
    external_ids: tuple[str, ...]
    edition_note: str
    rubrics: bool
    skip: str
    printed_edition: str = ""
    exclude: tuple[tuple[str, str], ...] = ()
    scripts: tuple[str, ...] = ()

    def matches(self, loc: Mapping[str, str]) -> bool:
        """Whether a location is in this text (selected and not excluded)."""
        return self.selects(loc) and not any(loc.get(lab) == val for lab, val in self.exclude)

    def selects(self, loc: Mapping[str, str]) -> bool:
        """Whether one of the row's alternatives selects the location (exclusions aside)."""
        return any(all(loc.get(lab) == val for lab, val in alt) for alt in self.select)

    @property
    def select_text(self) -> str:
        alts = ("&".join(f"{a}={b}" for a, b in alt) for alt in self.select)
        return ";".join(alts) or "(whole set)"


def _int(s: str) -> int | None:
    s = s.strip()
    return int(s) if s else None


def _select(s: str) -> tuple[tuple[str, str], ...]:
    out = []
    for part in filter(None, (p.strip() for p in s.split("&"))):
        lab, _, val = part.partition("=")
        out.append((lab.strip(), val.strip()))
    return tuple(out)


def read_table(source_id: str) -> list[TextRow]:
    """The curated rows of *source_id* (``data/titus_{source}.csv``)."""
    path = DATA_DIR / f"{source_id.replace('-', '_')}.csv"
    rows = []
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            rows.append(TextRow(
                set=r["set"].strip(),
                select=tuple(_select(alt) for alt in r["select"].split(";")),
                slug=r["slug"].strip(),
                ref=r["ref"].strip(),
                units=tuple(u.strip() for u in r["units"].split("|") if u.strip()),
                title=r["title"].strip(),
                author=r["author"].strip(),
                genre=r["genre"].strip() or "patristic",
                date_from=_int(r["date_from"]),
                date_to=_int(r["date_to"]),
                date_composed=_int(r["date_composed"]),
                date_confidence=r["date_confidence"].strip() or "uncertain",
                external_ids=tuple(x.strip() for x in r["external_ids"].split("|") if x.strip()),
                edition_note=r["edition_note"].strip(),
                rubrics=r["rubrics"].strip() == "1",
                skip=r["skip"].strip(),
                printed_edition=(r.get("printed_edition") or "").strip(),
                exclude=_select((r.get("exclude") or "").replace("|", "&")),
                scripts=tuple(x.strip() for x in (r.get("scripts") or "").split("|") if x.strip()),
            ))
    slugs = [r.slug for r in rows if not r.skip]
    dupes = {s for s in slugs if slugs.count(s) > 1}
    if dupes:
        raise ValueError(f"{path.name}: duplicate slugs {sorted(dupes)}")
    return rows


# ---------------------------------------------------------------------------
# Units
# ---------------------------------------------------------------------------

def ref_part(value: str | None) -> str:
    """A location value as one ref segment: ``Intr.`` → ``Intr``, ``255_(45)`` → ``255``."""
    if value is None:
        return "0"
    # a second numbering in parentheses ("255_(45)"); a value that is all in
    # parentheses ("(Io.Rait._Epist.)") keeps its content
    v = re.sub(r"_?\(.*?\)", "", value) if re.search(r"[^()]\s*_?\(", value) else value
    v = re.sub(r"[^0-9A-Za-z]+", "_", v).strip("_")
    return v or "0"


# Scripts other than Georgian that a text quotes (Hebrew letters in Epiphanius
# De mensuris, Greek words): kept as text.
_QUOTED_SCRIPT_RE = re.compile(r"^(hb|gr)[a-z]*\d+$")


def include_segment(seg: T.Segment) -> bool:
    """Old Georgian text (no variant readings), an editor's heading, quoted scripts."""
    return (T.is_main_text(seg) or seg.lang == "ng"
            or bool(_QUOTED_SCRIPT_RE.match(seg.cls)))


def _include_for(row: TextRow) -> Callable[[T.Segment], bool]:
    if not row.scripts:
        return include_segment
    return lambda seg: include_segment(seg) and (not seg.script or seg.script in row.scripts)


# A footnote number with TITUS's apparatus pointer ("ძისა5*"): the notes
# aren't carried, so the marker is noise (dropped, #236's rule for noise).
_FOOTNOTE_RE = re.compile(r"(?<=\S)\d+\*")


def clean_unit_text(raw: str) -> tuple[str, list[list[int | str]]]:
    """``_titus.clean_text`` after dropping footnote markers."""
    return T.clean_text(_FOOTNOTE_RE.sub("", raw))


def segment_kind(rubrics: bool):  # noqa: ANN201
    """The ``span_kind`` for ``collect_units``: rubrics (liturgy only) and headings."""
    def kind(seg: T.Segment) -> str | None:
        if seg.lang == "ng":
            return "heading"
        if rubrics and seg.is_old_georgian and "b" in seg.flags:
            return "rubric"
        return None
    return kind


@dataclass
class RawUnit:
    ref: str
    text: str
    editorial: list[list[int | str]]

    def record(self) -> dict[str, object]:
        rec: dict[str, object] = {"ref": self.ref, "text": self.text}
        if self.editorial:
            rec["editorial"] = self.editorial
        return rec


def _with_unit_labels(located: Iterable[T.Located], row: TextRow) -> Iterator[T.Located]:
    """The located segments *row* selects, each unit label set (``"0"`` before its first value)."""
    for item in located:
        if not row.matches(item.loc):
            continue
        merged = {**item.xloc, **item.loc}
        loc = dict(item.loc)
        for lab in row.units:
            loc[lab] = ref_part(merged.get(lab))
        yield T.Located(loc=loc, xloc=item.xloc, segment=item.segment)


def build_units(located: Iterable[T.Located], row: TextRow) -> list[RawUnit]:
    """The units of the text *row* selects, in order, with unique refs."""
    units: list[RawUnit] = []
    seen: dict[str, int] = {}
    for u in T.collect_units(_with_unit_labels(located, row), row.units,
                             include=_include_for(row), clean=clean_unit_text,
                             span_kind=segment_kind(row.rubrics)):
        ref = ".".join((row.ref, *(v or "0" for v in u.key)))
        spans = [list(s) for s in u.editorial]
        if ref in seen:
            # a location seen again later: number it (e.g. a page shared by two chapters)
            seen[ref] += 1
            ref = f"{ref}_{seen[ref]}"
            log.debug("repeated location %s", ref)
        else:
            seen[ref] = 1
        units.append(RawUnit(ref, u.text, spans))
    return units


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------

def _set_located(
    set_path: str, raw_dir: Path, force: bool,
) -> tuple[list[T.Located], T.SetHeader, str]:
    frame_url = T.BASE_URL + set_path
    events: list[T.Event] = []
    header: T.SetHeader | None = None
    for i, (_url, page) in enumerate(T.iter_pages(frame_url, raw_dir, force=force)):
        if i == 0:
            header = T.parse_header(page)
        events.extend(T.parse_page(page))
    assert header is not None
    return list(T.locate(events)), header, frame_url


def _work(source_id: str, row: TextRow, header: T.SetHeader, frame_url: str) -> Work:
    edition = T.edition_line(row.printed_edition or header.printed_edition,
                             editors=header.version_by,
                             last_changed=header.last_changed)
    if row.edition_note:
        edition = f"{row.edition_note}; {edition}"
    date_range = (row.date_from, row.date_to) if row.date_from is not None else None
    return Work(
        work_id=f"{source_id}/{row.slug}",
        source_id=source_id,
        author=row.author or None,
        title=row.title,
        date_composed=row.date_composed,
        date_range=date_range,
        date_confidence=row.date_confidence,
        genre=row.genre,
        language="oge",
        tradition="georgian",
        license=T.TITUS_LICENSE,
        provenance_url=frame_url,
        edition=edition,
        external_ids=list(row.external_ids),
    )


def _unselected(located: list[T.Located], rows: list[TextRow]) -> Iterator[str]:
    """Locations of Old Georgian text that no row of the set selects."""
    seen: set[str] = set()
    for item in located:
        seg = item.segment
        if not (seg.is_old_georgian and not seg.is_variant):
            continue
        if any(r.selects(item.loc) for r in rows):
            continue  # selected (or deliberately excluded) by a row
        desc = ", ".join(f"{k}={v}" for k, v in list(item.loc.items())[:3])
        if desc not in seen:
            seen.add(desc)
            yield desc


def ingest_titus_source(source_id: str, output_dir: Path, force: bool = False) -> list[Work]:
    """Ingest every text of *source_id*'s table; write ``{output_dir}/{source}/{slug}.json``."""
    rows = read_table(source_id)
    out_root = Path(output_dir) / source_id
    out_root.mkdir(parents=True, exist_ok=True)
    works: list[Work] = []
    by_set: dict[str, list[TextRow]] = {}
    for r in rows:
        by_set.setdefault(r.set, []).append(r)
    for set_path, set_rows in by_set.items():
        todo = [r for r in set_rows if not r.skip]
        for r in set_rows:
            if r.skip:
                log.warning("%s: skipping %s %s: %s", source_id, set_path,
                            r.select_text, r.skip)
        if not todo:
            continue
        if not force and all((out_root / f"{r.slug}.json").exists() for r in todo):
            for r in todo:
                saved = json.loads((out_root / f"{r.slug}.json").read_text(encoding="utf-8"))
                works.append(Work(**saved["work"]))
            log.info("%s: %s already written", source_id, set_path)
            continue
        try:
            located, header, frame_url = _set_located(set_path, Path(output_dir), force)
        except T.TitusRestricted as exc:
            log.warning("%s: %s is restricted, skipped: %s", source_id, set_path, exc)
            continue
        for desc in _unselected(located, set_rows):
            log.error("%s: text in %s selected by no row (dropped): %s", source_id, set_path, desc)
        for r in todo:
            units = build_units(located, r)
            if not units:
                log.error("%s: %s (%s) has no text", source_id, r.slug, set_path)
                continue
            work = _work(source_id, r, header, frame_url)
            path = out_root / f"{r.slug}.json"
            path.write_text(
                json.dumps({"work": work.model_dump(mode="json", exclude_none=False),
                            "paragraphs": [u.record() for u in units]},
                           ensure_ascii=False, indent=1) + "\n",
                encoding="utf-8")
            log.info("%s: %s, %d units", source_id, work.work_id, len(units))
            works.append(work)
    return works
