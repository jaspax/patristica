"""OCR eval set and scorer for the Patrologia Graeca (#718).

    uv run --extra ocr python -m scripts.ocr.eval build      # ground truth → scripts/ocr/eval/data
    uv run --extra ocr python -m scripts.ocr.eval baseline --data-root ../../..  # OGL's OCR
    uv run --extra ocr python -m scripts.ocr.eval score --engine ogl [--engine …] [--by volume]

The ground truth (tracked) is ``scripts/ocr/eval/data/``: ``manifest.csv``
(one row per page) and ``gt/{page_id}.txt`` (the Greek column's lines). Page
images and engine outputs live in the gitignored cache ``data/cache/ocr_eval/``:
``images/{page_id}.{ext}`` and ``hyp/{engine}/{page_id}.txt``. An engine's
output may instead be ``{page_id}.json`` with ``text`` and optional
``columns`` (the running heads' column numbers), which the column metric needs.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path

from patristica.console import setup_logging
from scripts.ingest._greek_lexicon import load_lexicon

from . import groundtruth
from .metrics import Counts, score_page

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(__file__).resolve().parent / "data"
MANIFEST = DATA_DIR / "manifest.csv"
GT_DIR = DATA_DIR / "gt"
CACHE_DIR = REPO_ROOT / "data" / "cache" / "ocr_eval"


def read_manifest(path: Path = MANIFEST) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_manifest(rows: list[dict[str, str]], path: Path = MANIFEST) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=groundtruth.MANIFEST_FIELDS, lineterminator="\n")
        w.writeheader()
        for row in sorted(rows, key=lambda r: r["page_id"]):
            w.writerow({k: row.get(k, "") for k in groundtruth.MANIFEST_FIELDS})


def _columns(value: str | list | None) -> tuple[int, ...] | None:
    if not value:
        return None
    if isinstance(value, str):
        value = value.split("|")
    return tuple(int(v) for v in value)


ERRATA = DATA_DIR / "errata.csv"


def read_errata(path: Path = ERRATA) -> dict[str, list[dict[str, str]]]:
    """Corrections to the ground truth, by page (see data/README.md)."""
    out: dict[str, list[dict[str, str]]] = defaultdict(list)
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                out[row["page_id"]].append(row)
    return out


def apply_errata(text: str, errata: list[dict[str, str]]) -> str:
    """``text`` with each erratum applied on its line.

    An erratum's ``gt`` is one token or a run of space-separated tokens; the
    first occurrence of that run on the line is replaced by ``corrected``. A
    word Calfa left out is an erratum whose ``gt`` is the word before it and
    whose ``corrected`` adds the missing word.
    """
    lines = text.split("\n")
    for e in errata:
        i = int(e["line"]) - 1
        toks = lines[i].split(" ")
        run = e["gt"].split(" ")
        at = next((k for k in range(len(toks) - len(run) + 1) if toks[k:k + len(run)] == run), None)
        if at is None:
            raise ValueError(f"erratum not found: {e}")
        toks[at:at + len(run)] = e["corrected"].split(" ") if e["corrected"] else []
        lines[i] = " ".join(toks)
    return "\n".join(lines)


def read_hypothesis(engine_dir: Path, page_id: str) -> tuple[str, tuple[int, ...] | None] | None:
    """An engine's text and column numbers for a page; None if it has none."""
    js = engine_dir / f"{page_id}.json"
    if js.exists():
        data = json.loads(js.read_text(encoding="utf-8"))
        return data.get("text", ""), _columns(data.get("columns"))
    txt = engine_dir / f"{page_id}.txt"
    if txt.exists():
        return txt.read_text(encoding="utf-8"), None
    return None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_build(args: argparse.Namespace) -> int:
    rows = groundtruth.build(GT_DIR, args.cache / "zenodo", args.cache / "images")
    old = {r["page_id"]: r for r in read_manifest()} if MANIFEST.exists() else {}
    # Keep what other commands recorded (the OGL match) and hand-made rows.
    for row in rows:
        for k, v in old.pop(row["page_id"], {}).items():
            if v and not row.get(k):
                row[k] = v
    kept = [r for r in old.values() if not r["set"].startswith("calfa")]
    write_manifest(rows + kept)
    log.info("Ground truth: %d Calfa pages, %d others → %s", len(rows), len(kept), MANIFEST)
    return 0


def _note(row: dict[str, str], ogl: str) -> str:
    """The row's note with its ``OGL: …`` part replaced by ``ogl``."""
    parts = [p for p in row.get("note", "").split("; ") if p and not p.startswith("OGL:")]
    return "; ".join(parts + ([ogl] if ogl else []))


def cmd_baseline(args: argparse.Namespace) -> int:
    from . import ogl

    rows = read_manifest()
    out_dir = args.cache / "hyp" / "ogl"
    out_dir.mkdir(parents=True, exist_ok=True)
    found = 0
    for row in rows:
        ref = (GT_DIR / f"{row['page_id']}.txt").read_text(encoding="utf-8")
        try:
            m = ogl.find_page(args.data_root, row["pg_volume"], ref)
        except FileNotFoundError as e:
            log.warning("%s: %s", row["page_id"], e)
            m = None
        if m is None:
            # OGL has no page with this text: it is a hole, scored as empty.
            row.update(ogl_scan="", ogl_stem="", ogl_containment="",
                       note=_note(row, "OGL: no page has this text (scored empty)"))
            (out_dir / f"{row['page_id']}.txt").write_text("", encoding="utf-8")
            continue
        found += 1
        row.update(ogl_scan=m.scan, ogl_stem=m.stem, ogl_containment=f"{m.containment:.2f}",
                   note=_note(row, "" if m.ingested
                              else "OGL: best of all scans (volume not ingested)"))
        hyp = ogl.trim_to(m.text, ref)
        (out_dir / f"{row['page_id']}.txt").write_text(hyp + "\n", encoding="utf-8")
    write_manifest(rows)
    log.info("OGL baseline: %d of %d pages found → %s", found, len(rows), out_dir)
    return 0


def _fmt(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.2f}"


def cmd_score(args: argparse.Namespace) -> int:
    rows = read_manifest()
    if args.set:
        rows = [r for r in rows if r["set"] in args.set]
    if args.pages:
        wanted = set(args.pages.read_text(encoding="utf-8").split())
        rows = [r for r in rows if r["page_id"] in wanted]
    rows = [r for r in rows if r.get("status", "checked") == "checked"]
    lexicon = load_lexicon()
    errata = read_errata() if args.errata else {}
    header = ("group", "pages", "missing", "chars", "CER%", "baseCER%", "accent%",
              "WER%", "realword%", "cols%")
    for engine in args.engine:
        engine_dir = args.cache / "hyp" / engine
        groups: dict[str, Counts] = defaultdict(Counts)
        missing: dict[str, int] = defaultdict(int)
        for row in rows:
            key = row[args.by] if args.by else "all"
            hyp = read_hypothesis(engine_dir, row["page_id"])
            if hyp is None:
                missing[key] += 1
                groups[key] = groups[key]  # keep the group in the table
                continue
            ref = (GT_DIR / f"{row['page_id']}.txt").read_text(encoding="utf-8")
            if errata.get(row["page_id"]):
                ref = apply_errata(ref, errata[row["page_id"]])
            groups[key] = groups[key] + score_page(
                ref, hyp[0], lexicon, dehyphenate=args.dehyphenate,
                conventions=args.fold_conventions,
                ref_columns=_columns(row.get("columns")), hyp_columns=hyp[1],
            )
        flags = [f for f, on in (("dehyphenated", args.dehyphenate), ("errata", args.errata),
                                 ("conventions folded", args.fold_conventions)) if on]
        print(f"\n## {engine}" + (f" ({', '.join(flags)})" if flags else ""))
        print(" | ".join(header))
        print(" | ".join("---" for _ in header))
        total = Counts()
        for key in sorted(groups, key=_sort_key):
            c = groups[key]
            total = total + c
            print(_row(key, c, missing[key]))
        if len(groups) > 1:
            print(_row("total", total, sum(missing.values())))
        if args.examples and total.examples:
            print("real-word substitutions (reference → reading): "
                  + ", ".join(f"{r} → {h}" for r, h in total.examples[: args.examples]))
    return 0


def _sort_key(key: str) -> tuple[float, str]:
    try:
        return (float(key), key)
    except ValueError:
        return (float("inf"), key)


def _row(key: str, c: Counts, missing: int) -> str:
    return " | ".join((
        key, str(c.pages), str(missing), str(c.chars), _fmt(c.cer), _fmt(c.base_cer),
        _fmt(c.accent_share), _fmt(c.wer), _fmt(c.realword_rate), _fmt(c.column_accuracy),
    ))


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    p = argparse.ArgumentParser(prog="python -m scripts.ocr.eval",
                                description=__doc__.split("\n\n")[0])
    p.add_argument("--cache", type=Path, default=CACHE_DIR,
                   help="images, downloads and engine outputs")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="download Calfa's ground truth → GT files and manifest")
    b.set_defaults(func=cmd_build)

    bl = sub.add_parser("baseline", help="find each page in OGL's primary scan → hyp/ogl/")
    bl.add_argument("--data-root", type=Path, default=REPO_ROOT,
                    help="checkout with data/raw materialized (the main checkout)")
    bl.set_defaults(func=cmd_baseline)

    s = sub.add_parser("score", help="score engines' outputs against the ground truth")
    s.add_argument("--engine", action="append", required=True, help="a dir under hyp/ (repeatable)")
    s.add_argument("--set", action="append", help="only these sets (calfa-v2, ours)")
    s.add_argument("--pages", type=Path, metavar="FILE",
                   help="only the page ids listed in FILE (whitespace-separated)")
    s.add_argument("--by", choices=("pg_volume", "set", "page_id"), help="one row per group")
    s.add_argument("--fold-conventions", action="store_true",
                   help="unify apostrophes and drop footnote markers, on both sides")
    s.add_argument("--errata", action="store_true",
                   help="apply data/errata.csv (rule-based corrections of the ground truth)")
    s.add_argument("--dehyphenate", action="store_true",
                   help="join words split at line ends, on both sides")
    s.add_argument("--examples", type=int, default=0, metavar="N",
                   help="print N real-word substitutions")
    s.set_defaults(func=cmd_score)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
