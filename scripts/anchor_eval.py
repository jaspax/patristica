"""
Dry-run measurement of anchored derived verses (#292, #200): writes nothing.

For each pair (anchor, translation) of existing works, re-cut the translation's
source paragraphs on the anchor's current derived verses with
``patristica.anchoring.project`` and report:

- **projected**: the share of the anchor's internal unit boundaries the
  projection is sure of (the rest fall back to a size split);
- **sentence ends kept**: the share of the anchor's sentence ends the best
  path maps to sentence ends (below ``MIN_SENTENCE_AGREEMENT`` the translation
  is free and not anchored);
- **agree**: of the projected boundaries that the passage alignment (#179,
  ``data/alignments``, computed from the vectors) also places, the share the
  projection puts at the same word of the translation (exactly, within
  ``NEAR`` words, and off by more than ``FAR``: a misaligned window). That
  alignment is independent of the projection (vectors, not lengths), but it is
  only defined where today's cuts of both works break a group at the same
  place, so it checks a subset;
- **1:1 rows**: the share of the anchor's units that are a row of their own
  with exactly one unit of the translation, today (alignment groups with
  one unit on each side) and anchored (both boundaries projected, in one
  translation paragraph);
- the translation's unit count today and anchored.

Today's units come from ``data/normalized`` (a translation's source paragraphs
are rebuilt from its derived verses), so the run needs no raw data and no
vectors. A work without an alignment (a new source, before ``scripts.embed``)
gets everything but **agree** and today's 1:1 rows: check it by hand with
``--sample``, which prints random anchored 1:1 rows (anchor unit, then the
translation's).

The passage alignment can only break a group where today's cuts of both works
break, so where the true correspondence falls between two of today's units it
is wrong, and **agree** understates the projection: checked by hand, most
disagreements on Augustine's Tractates were the reference's, not the
projection's (#292).

Usage::

    uv run python -m scripts.anchor_eval                       # the default pairs (#292)
    uv run python -m scripts.anchor_eval --pair ANCHOR TRANSLATION [--pair …] [--sample 20]
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path

from patristica import alignment_store as store
from patristica.anchoring import MIN_SENTENCE_AGREEMENT, Anchor, project
from patristica.versify import _atoms

log = logging.getLogger(__name__)

NORMALIZED = Path("data/normalized")
ALIGNMENTS = Path("data/alignments")
NEAR = 5  # words
FAR = 50  # words: a misaligned window rather than a clause too early or late

#: The pilot groups of #200/#292: (anchor, translation).
DEFAULT_PAIRS: tuple[tuple[str, str], ...] = (
    # Basil's letters: the English translates the Perseus Greek; Migne is
    # another edition of it (same language: what #199 would do, measured
    # here with the length projection only for comparison).
    ("perseus/tlg2040/tlg004/perseus-grc2", "npnf-works/basil-letters"),
    ("perseus/tlg2040/tlg004/perseus-grc2", "ogpg/vol-032/epistulae"),
    # Augustine, Tractates on John: Latin → English.
    ("oglt-pl/augustinus/pl35_3_s.", "npnf-works/augustine-tractates-on-john"),
    # Severian of Gabala, Greek → Armenian (PTA).
    ("pta/pta0001/pta014/pta-grc1", "pta/pta0001/pta014/pta-xcl1"),
    ("pta/pta0001/pta031/pta-grc1", "pta/pta0001/pta031/pta-xcl1"),
)

_DERIVED = re.compile(r"\.s\d+$")


def _paths(norm: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in (norm / "_works.jsonl").read_text(encoding="utf-8").splitlines():
        rec = json.loads(line)
        out[rec["work"]["work_id"]] = rec["path"]
    return out


def _chunks(norm: Path, paths: dict[str, str], work_id: str) -> list[dict]:
    return json.loads((norm / paths[work_id]).read_text(encoding="utf-8"))


@dataclass
class Translation:
    """A translation's source paragraphs, rebuilt from its units."""

    language: str
    paragraphs: list[str]
    refs: list[str]
    #: Global unit index → (paragraph, word) where the unit starts.
    unit_start: list[tuple[int, int]]
    para_words: list[int]


def _translation(chunks: list[dict]) -> Translation:
    paras: list[list[str]] = []
    refs: list[str] = []
    last: str | None = None
    for c in chunks:
        ref = c["canonical_ref"]
        parent = _DERIVED.sub("", ref)
        if parent != ref and parent == last:
            paras[-1].append(c["text"])
        else:
            paras.append([c["text"]])
            refs.append(parent)
        last = parent if parent != ref else None
    starts: list[tuple[int, int]] = []
    words: list[int] = []
    for p, units in enumerate(paras):
        w = 0
        for text in units:
            starts.append((p, w))
            w += len(_atoms(text))
        words.append(w)
    return Translation(chunks[0]["language"], [" ".join(u) for u in paras], refs, starts, words)


def _global(pos: tuple[int, int], offsets: list[int]) -> int:
    return offsets[pos[0]] + pos[1]


def _reference(anchor_id: str, trans_id: str, alignments: Path
               ) -> tuple[dict[int, int], int, int, int] | None:
    """The passage alignment's boundaries: anchor unit → translation unit, plus
    (rows, 1:1 rows, anchor units in 1:1 rows) of today's cut."""
    for _, a in store.iter_store(alignments,
                                 members=lambda ws: anchor_id in ws and trans_id in ws):
        spans = [(s[anchor_id], s[trans_id]) for s in a.groups_of().values()
                 if anchor_id in s and trans_id in s]
        spans.sort()
        ref: dict[int, int] = {}
        for (oa, ta), (ob, tb) in zip(spans, spans[1:]):
            if oa[1] == ob[0] and ta[1] == tb[0]:
                ref[ob[0]] = tb[0]
        one = [s for s in spans if s[0][1] - s[0][0] == 1 and s[1][1] - s[1][0] == 1]
        return ref, len(spans), len(one), len(one)
    return None


def evaluate(anchor_id: str, trans_id: str, norm: Path = NORMALIZED,
             alignments: Path = ALIGNMENTS, sample: int = 0, seed: int = 1
             ) -> dict[str, object]:
    """The numbers of one pair (see the module docstring); with *sample*, also
    print that many random anchored 1:1 rows for checking by hand."""
    paths = _paths(norm)
    anchor = Anchor.from_chunks(anchor_id, _chunks(norm, paths, anchor_id))
    t_chunks = _chunks(norm, paths, trans_id)
    tr = _translation(t_chunks)
    started = time.monotonic()
    proj = project(anchor.paragraphs(), anchor.language, tr.paragraphs, tr.language)
    seconds = time.monotonic() - started
    n_anchor = len(anchor.units)
    internal = n_anchor - 1

    offsets = [0]
    for w in tr.para_words:
        offsets.append(offsets[-1] + w)
    projected = {u: _global(pos, offsets) for u, pos in proj.boundary.items()}

    result: dict[str, object] = {
        "anchor": anchor_id, "translation": trans_id,
        "languages": f"{anchor.language}→{tr.language}",
        "anchor_units": n_anchor, "boundaries": internal,
        "projected": len(projected), "projected_share": len(projected) / max(internal, 1),
        "units_today": len(t_chunks), "units_anchored": sum(len(u) for u in proj.units),
        "unmatched_paragraphs": len(proj.unmatched), "paragraphs": len(tr.paragraphs),
        "sentence_agreement": round(proj.sentence_agreement, 3),
        "free": proj.sentence_agreement < MIN_SENTENCE_AGREEMENT,
        "seconds": round(seconds, 1),
    }

    # Anchored 1:1 rows: anchor units with both boundaries marked, in one paragraph.
    edges = dict(projected)
    edges[0] = 0
    edges[n_anchor] = offsets[-1]
    para_of = []
    for p, w in enumerate(tr.para_words):
        para_of.extend([p] * w)
    one_one: list[tuple[int, int, int]] = []
    for u in range(n_anchor):
        a, b = edges.get(u), edges.get(u + 1)
        if a is None or b is None or b <= a:
            continue
        if para_of[a] == para_of[b - 1]:
            one_one.append((u, a, b))
    result["one_one_anchored"] = len(one_one) / n_anchor
    if sample:
        words = [w for p in tr.paragraphs for w in _atoms(p)]
        for u, a, b in sorted(random.Random(seed).sample(one_one, min(sample, len(one_one)))):
            print(f"--- {anchor.units[u][0]}\n  {anchor.units[u][1]}\n  "
                  f"{''.join(words[a:b]).strip()}")

    ref = _reference(anchor_id, trans_id, alignments)
    if ref is not None:
        boundaries, rows, rows_one, units_one = ref
        result["one_one_today"] = units_one / n_anchor
        result["rows_today"] = rows
        checked = [u for u in projected if u in boundaries]
        exact = near = far = 0
        for u in checked:
            want = _global(tr.unit_start[boundaries[u]], offsets)
            d = abs(projected[u] - want)
            exact += d == 0
            near += d <= NEAR
            far += d > FAR
        result["checked"] = len(checked)
        result["agree_exact"] = exact / max(len(checked), 1)
        result["agree_near"] = near / max(len(checked), 1)
        result["off_far"] = far / max(len(checked), 1)
        result["reference_boundaries"] = len(boundaries)
        result["reference_recall"] = exact / max(len(boundaries), 1)
    return result


def render(rows: list[dict[str, object]]) -> str:
    head = ("| anchor → translation | langs | anchor units | sentence ends kept | projected "
            "| agree exact / ±5 words / off > 50 words (checked) | 1:1 rows today → anchored "
            "| translation units today → anchored |")
    lines = [head, "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        agree = (f"{r['agree_exact']:.0%} / {r['agree_near']:.0%} / {r['off_far']:.0%} "
                 f"({r['checked']:,})"
                 if "checked" in r else "n/a")
        today = f"{r['one_one_today']:.0%}" if "one_one_today" in r else "n/a"
        lines.append(
            f"| `{r['anchor']}` → `{r['translation']}` | {r['languages']} "
            f"| {r['anchor_units']:,} | {r['sentence_agreement']:.0%}"
            f"{' (free: not anchored)' if r['free'] else ''} "
            f"| {r['projected_share']:.0%} | {agree} "
            f"| {today} → {r['one_one_anchored']:.0%} "
            f"| {r['units_today']:,} → {r['units_anchored']:,} |")
    return "\n".join(lines)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--pair", nargs=2, action="append", metavar=("ANCHOR", "TRANSLATION"))
    parser.add_argument("--normalized-dir", type=Path, default=NORMALIZED)
    parser.add_argument("--alignments-dir", type=Path, default=ALIGNMENTS)
    parser.add_argument("--json", action="store_true", help="print the raw numbers as JSON")
    parser.add_argument("--sample", type=int, default=0, metavar="N",
                        help="also print N random anchored 1:1 rows per pair, to check by hand "
                             "(the only check for a work that has no vectors yet)")
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    rows = []
    for anchor_id, trans_id in args.pair or DEFAULT_PAIRS:
        log.info("%s → %s", anchor_id, trans_id)
        rows.append(evaluate(anchor_id, trans_id, args.normalized_dir, args.alignments_dir,
                             args.sample, args.seed))
    print(json.dumps(rows, indent=2) if args.json else render(rows))


if __name__ == "__main__":
    main()
