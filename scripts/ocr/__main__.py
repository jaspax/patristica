"""OCR pipeline for Migne PG pages (#705, #720).

    uv run --extra ocr python -m scripts.ocr flags-train            # once; needs data/normalized
    uv run --extra ocr python -m scripts.ocr run --pages PAGES --images DIR --out DIR
    uv run --extra ocr python -m scripts.ocr cost --out DIR

`run` executes the stages in order (see scripts/ocr/stages.py) and resumes
where a previous run stopped. Gemini (GEMINI_API_KEY) and Claude
(ANTHROPIC_API_KEY) go through their batch APIs by default, at half price;
`--direct` calls them synchronously instead, and `--claude cli` uses a local
`claude -p` on the Claude subscription. Kraken needs KRAKEN_BIN (its CLI, in
its own Python 3.11 environment) and KRAKEN_MODEL (cllg_recognition_v1.mlmodel,
Zenodo 21295925).

Every paid call spends money: Gemini and the Claude API need the owner's yes
for a bulk run (CLAUDE.md).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from patristica.console import setup_logging
from scripts.ocr import flags, stages
from scripts.ocr.backends import ClaudeBatch, ClaudeCLI, Gemini

log = logging.getLogger(__name__)

STAGES = ("kraken", "kgc", "gemini_page", "opus_page", "synth1", "synth2", "final")
GEMINI_MODEL = "gemini-3.8-flash"
CLAUDE_MODEL = "claude-opus-5-5"

# USD per million tokens, standard (direct) rates; batch APIs bill half.
# Gemini 3.8 Flash doubles on 2027-01-01 ($1.50 / $7.50).
PRICES = {
    "gemini": {"in": 0.75, "out": 3.75},
    "claude": {"in": 4.00, "out": 20.00, "cache_write_1h": 8.00, "cache_read": 0.40},
}
PROVIDER = {"kgc": "gemini", "gemini_page": "gemini", "opus_page": "claude",
            "synth1": "claude", "synth2": "claude"}


def _gemini(args: argparse.Namespace, stage: str) -> Gemini:
    return Gemini(GEMINI_MODEL, thinking="low", batch=not args.direct,
                  state_dir=Path(args.out) / stage)


def _claude(args: argparse.Namespace, stage: str):
    if args.claude == "cli":
        return ClaudeCLI("opus", effort=args.effort)
    return ClaudeBatch(CLAUDE_MODEL, effort=args.effort or "medium",
                       state_dir=Path(args.out) / stage)


def cmd_run(args: argparse.Namespace) -> int:
    pages = Path(args.pages).read_text(encoding="utf-8").split()
    run = stages.Run(pages, Path(args.images), Path(args.out))
    wanted = args.stage or list(STAGES)
    for stage in STAGES:
        if stage not in wanted:
            continue
        ext = "xml" if stage == "kraken" else "txt"
        log.info("stage %s: %d pages to do", stage, len(run.todo(stage, ext)))
        if stage == "kraken":
            stages.kraken(run)
        elif stage == "kgc":
            stages.kgc(run, _gemini(args, stage))
        elif stage == "gemini_page":
            stages.page_reader(run, stage, _gemini(args, stage))
        elif stage == "opus_page":
            stages.page_reader(run, stage, _claude(args, stage))
        elif stage in ("synth1", "synth2"):
            stages.synth(run, stage, _claude(args, stage))
        elif stage == "final":
            stages.final(run)
    return 0


def _tokens(provider: str, u: dict) -> tuple[float, float]:
    if provider == "gemini":
        return (u.get("promptTokenCount", 0),
                u.get("candidatesTokenCount", 0) + (u.get("thoughtsTokenCount") or 0))
    return (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
            + u.get("cache_read_input_tokens", 0), u.get("output_tokens", 0))


def cmd_cost(args: argparse.Namespace) -> int:
    """Tokens and dollars per page for each stage, at direct and batch rates."""
    out = Path(args.out)
    total = 0.0
    print(f"{'stage':12s} {'pages':>5s} {'in/page':>9s} {'out/page':>9s} {'$/page':>8s} "
          f"{'batch $/page':>13s}")
    for stage, provider in PROVIDER.items():
        f = out / stage / "_usage.jsonl"
        if not f.exists():
            continue
        tin = tout = 0.0
        pages = set()
        for line in f.read_text().splitlines():
            r = json.loads(line)
            if r.get("error"):
                continue
            pages.add(r["key"].split("#")[0])
            i, o = _tokens(provider, r["usage"] or {})
            tin, tout = tin + i, tout + o
        # A page with no disputed line makes no synthesis request but still counts.
        n = len(list((out / stage).glob("*.txt"))) or len(pages) or 1
        p = PRICES[provider]
        usd = (tin * p["in"] + tout * p["out"]) / 1e6 / n
        total += usd
        print(f"{stage:12s} {n:5d} {tin / n:9.0f} {tout / n:9.0f} {usd:8.4f} {usd / 2:13.4f}")
    print(f"{'total':12s} {'':5s} {'':9s} {'':9s} {total:8.4f} {total / 2:13.4f}")
    return 0


def cmd_flags_train(args: argparse.Namespace) -> int:
    n = flags.train(Path(args.normalized))
    log.info("Flag models trained on %d reference chunks -> %s", n, flags.MODEL)
    return 0


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    p = argparse.ArgumentParser(prog="python -m scripts.ocr", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("flags-train", help="train the word-flag n-gram models")
    t.add_argument("--normalized", default=str(flags.REPO_ROOT / "data" / "normalized"))
    t.set_defaults(func=cmd_flags_train)
    r = sub.add_parser("run", help="run the pipeline over a list of pages")
    r.add_argument("--pages", required=True, help="file of page ids (image file stems)")
    r.add_argument("--images", required=True, help="directory of page images")
    r.add_argument("--out", required=True, help="output directory, one subdirectory per stage")
    r.add_argument("--stage", action="append", choices=STAGES, help="only these stages")
    r.add_argument("--direct", action="store_true",
                   help="synchronous Gemini calls, not the batch API")
    r.add_argument("--claude", choices=("api", "cli"), default="api",
                   help="Claude via the batch API (default) or a local claude -p")
    r.add_argument("--effort", choices=("low", "medium", "high"),
                   help="Claude effort (default medium)")
    r.set_defaults(func=cmd_run)
    c = sub.add_parser("cost", help="tokens and dollars per page of a run")
    c.add_argument("--out", required=True)
    c.set_defaults(func=cmd_cost)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
