"""
Propose the works #200's migration enrols one by one (``patristica/data/anchored_works.csv``).

Two kinds of published work get derived verses anchored on another work:

**Translations.** A prose work with derived verses whose ``translation_of`` is in
the corpus in another language, not already enrolled (by source, language or
work), not Scripture, and with both sides publishable. ``scripts.anchor``
refines it on its original's vectors; the row leaves ``anchor`` empty.

**Editions.** Same-language members of a version group that #199 aligned by
their text (``run.text.editions`` in ``data/alignments``) form a cluster. Its
*reference edition* keeps its cuts: an edition of a critical text before
OCR'd Migne (``OCR_SOURCES``, owner 2026-11-09), then the member whose own
words the others match most (``TextAlignment.clean_a``). Every other member
without a ``translation_of`` is enrolled on it, but only where projecting the
reference's cuts (``patristica.edition_projection``) beats today's cut by
``--margin`` in the share of the reference's shared units in a confident 1:1
bead (the measure of ``scripts.edition_eval``): today's cut is kept where the
projection doesn't clearly win.

Rows already in the table are kept as they are. ``--write`` rewrites the
table (sorted by work id); without it, the counts and the rows it would add
are printed.

Usage::

    uv run python -m scripts.anchor_enrol [--write] [--margin 0.02] [--jobs 8]
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from patristica import alignment_store as store
from patristica import anchoring
from patristica.corpus import EXCLUDED_LICENSES, load_works
from patristica.versify import is_derived_ref

log = logging.getLogger(__name__)

#: OCR'd Migne (PG, PL): never the reference edition when a cluster has an
#: edition from a critical text (owner, 2026-11-09). The clean share alone
#: can't tell them apart: a Migne volume holding part of a work has all its
#: words in the critical text, so it looks cleaner than the whole work.
OCR_SOURCES = frozenset({"ogpg", "oglt-pl"})


def _units(norm: Path, path: str) -> list[dict]:
    return json.loads((norm / path).read_text(encoding="utf-8"))


def _enrolled(work: dict) -> bool:
    return anchoring.is_enrolled(work["source_id"], work.get("language"), work["work_id"])


def translations(entries: dict[str, dict], norm: Path) -> dict[str, str]:
    """``{work_id: reason}`` for the translations to anchor on their translation_of."""
    out: dict[str, str] = {}
    for wid, e in sorted(entries.items()):
        w = e["work"]
        target = w.get("translation_of")
        if not target or target not in entries or _enrolled(w):
            continue
        orig = entries[target]["work"]
        if (w["genre"] == "scripture" or orig["language"] == w["language"]
                or w.get("license") in EXCLUDED_LICENSES
                or orig.get("license") in EXCLUDED_LICENSES):
            continue
        if not any(is_derived_ref(c["canonical_ref"]) for c in _units(norm, e["path"])):
            continue
        out[wid] = (f"#200: {w['language']} translation, cut on its translation_of "
                    f"({orig['language']})")
    return out


def _clean_and_score(job: tuple[Path, str, str, str, str]) -> dict:
    """Clean shares of an (edition, reference) pair and the projection's gain."""
    from patristica.edition_projection import project
    from patristica.text_alignment import align_texts

    norm, edition, ref, ed_path, ref_path = job
    rp = anchoring.paragraphs(_units(norm, ref_path))
    ep = anchoring.paragraphs(_units(norm, ed_path))
    ref_units = [u for p in rp for u in p.units]
    old = [u for p in ep for u in p.units]
    proj = project(rp, ep)
    new: list[str] = []
    for p, st in zip(ep, proj.starts):
        new += list(p.units) if st is None else anchoring.cut_at(" ".join(p.units), st)

    def one_one(units: list[str]) -> tuple[int, int, float, float]:
        r = align_texts(ref_units, units)
        one = sum(1 for t in r.beads if t.i1 - t.i0 == 1 and t.j1 - t.j0 == 1 and t.conf >= 0.5)
        return one, sum(t.i1 - t.i0 for t in r.beads if t.conf >= 0.5), r.clean_a, r.clean_b

    b, cb, clean_ref, clean_ed = one_one(old)
    a, ca, _, _ = one_one(new)
    units = max(cb, ca, 1)
    return {"edition": edition, "reference": ref, "before": b / units, "after": a / units,
            "units": units, "clean_reference": clean_ref, "clean_edition": clean_ed}


def clusters(entries: dict[str, dict], align_dir: Path) -> list[list[str]]:
    """Same-language members #199 aligned by text, one list per (group, language)."""
    out: list[list[str]] = []
    for _, a in store.iter_store(align_dir):
        editions = a.run.get("text", {}).get("editions", {})
        by_lang: dict[str, set[str]] = {}
        for wid, info in editions.items():
            for m in (wid, info["head"]):
                if m in entries:
                    by_lang.setdefault(entries[m]["work"]["language"], set()).add(m)
        out += [sorted(ms) for ms in by_lang.values() if len(ms) >= 2]
    return out


def editions(entries: dict[str, dict], norm: Path, align_dir: Path, margin: float,
             jobs: int) -> tuple[dict[str, tuple[str, str]], list[dict]]:
    """``{work_id: (reference, reason)}`` for editions to project, and every scored pair."""
    eligible = lambda w: (not w.get("translation_of") and not _enrolled(w)  # noqa: E731
                          and w.get("license") not in EXCLUDED_LICENSES)
    # 1. The reference of each cluster: score every member against the longest
    #    one, then take the member whose own words are matched most.
    plans = []
    for members in clusters(entries, align_dir):
        members = [m for m in members if eligible(entries[m]["work"])]
        if len(members) < 2:
            continue
        sizes = {m: len(_units(norm, entries[m]["path"])) for m in members}
        plans.append((members, max(members, key=lambda m: (sizes[m], m))))
    first = [(norm, m, head, entries[m]["path"], entries[head]["path"])
             for members, head in plans for m in members if m != head]
    with ProcessPoolExecutor(jobs) as ex:
        scored = list(ex.map(_clean_and_score, first))
    clean: dict[str, float] = {}
    for s in scored:
        clean[s["edition"]] = s["clean_edition"]
        clean[s["reference"]] = max(clean.get(s["reference"], 0.0), s["clean_reference"])
    refs = {tuple(members): max(members, key=lambda m: (
                entries[m]["work"]["source_id"] not in OCR_SOURCES, round(clean.get(m, 0.0), 2), m))
            for members, _ in plans}
    # 2. Score each other member against its reference (re-using step 1 where
    #    the reference is the longest member).
    done = {(s["edition"], s["reference"]): s for s in scored}
    second = [(norm, m, ref, entries[m]["path"], entries[ref]["path"])
              for members, ref in refs.items() for m in members
              if m != ref and (m, ref) not in done]
    with ProcessPoolExecutor(jobs) as ex:
        for s in ex.map(_clean_and_score, second):
            done[(s["edition"], s["reference"])] = s
    rows: dict[str, tuple[str, str]] = {}
    report: list[dict] = []
    for members, ref in refs.items():
        for m in members:
            if m == ref:
                continue
            s = done[(m, ref)]
            report.append(s)
            if s["after"] >= s["before"] + margin:
                rows[m] = (ref, f"#200: {entries[m]['work']['language']} edition, cut where "
                                f"the cleaner edition cuts (1:1 rows {s['before']:.0%} → "
                                f"{s['after']:.0%})")
    return rows, report


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    ap.add_argument("--normalized-dir", type=Path, default=Path("data/normalized"))
    ap.add_argument("--alignments-dir", type=Path, default=store.DEFAULT_DIR)
    ap.add_argument("--table", type=Path, default=anchoring.WORKS_PATH)
    ap.add_argument("--margin", type=float, default=0.02)
    ap.add_argument("--jobs", type=int, default=4)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--report", type=Path, help="write every scored edition pair (JSON)")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    entries = {e["work"]["work_id"]: e for e in load_works(args.normalized_dir)}
    existing: dict[str, tuple[str, str]] = {}
    with args.table.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            existing[row["work_id"]] = (row["anchor"], row["reason"])
    trans = translations(entries, args.normalized_dir)
    eds, report = editions(entries, args.normalized_dir, args.alignments_dir, args.margin,
                           args.jobs)
    if args.report:
        args.report.write_text(json.dumps(report, indent=1), encoding="utf-8")
    new: dict[str, tuple[str, str]] = {}
    for wid, reason in trans.items():
        new.setdefault(wid, ("", reason))
    for wid, (ref, reason) in eds.items():
        new.setdefault(wid, (ref, reason))
    added = {w: r for w, r in new.items() if w not in existing}
    kept = len(report) - len(eds)
    log.info("translations %d, editions %d (%d kept today's cut: no clear gain), already "
             "listed %d; %d rows to add", len(trans), len(eds), kept, len(existing), len(added))
    if not args.write:
        for wid, (anchor, reason) in sorted(added.items())[:20]:
            print(f"{wid},{anchor},{reason}")
        return
    rows = {**added, **existing}
    with args.table.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["work_id", "anchor", "reason"])
        for wid in sorted(rows):
            w.writerow([wid, *rows[wid]])
    log.info("wrote %s: %d rows", args.table, len(rows))


if __name__ == "__main__":
    main()
