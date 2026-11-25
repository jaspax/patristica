"""OCR pipeline for Migne PG pages (#705, #720).

    uv run --extra ocr python -m scripts.ocr flags-train            # once; needs data/normalized
    uv run --extra ocr python -m scripts.ocr run --pages PAGES --images DIR --out DIR
    uv run --extra ocr python -m scripts.ocr cost --out DIR
    uv run --extra ocr python -m scripts.ocr prepare --volume vol-075 --out DIR  # #721
    uv run --extra ocr python -m scripts.ocr export --run DIR/run --prep DIR

On the OGPG holes, `prepare` crops the Greek column of each located page
(scripts.ogpg_images) into DIR/images with DIR/pages.txt, `run` reads them
(--pages DIR/pages.txt --images DIR/images --out DIR/run), and `export` checks
each page's running head and writes data/ocr/ogpg/{volume}.jsonl for the
ingestor (scripts/ocr/ogpg.py).

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
from collections import defaultdict
from pathlib import Path

from patristica.console import setup_logging
from scripts.ocr import flags, stages
from scripts.ocr.backends import ClaudeBatch, ClaudeCLI, Gemini

log = logging.getLogger(__name__)

STAGES = ("kraken", "kgc", "gemini_page", "opus_page", "synth1", "synth2", "final")
GEMINI_MODEL = "gemini-3.8-flash"
CLAUDE_MODELS = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5",
                 "haiku": "claude-haiku-5-5"}


def _claude_price(i: float, o: float) -> dict[str, float]:
    # Cache reads 0.1x input; cache writes 1.25x (5-minute) or 2x (1-hour).
    return {"in": i, "out": o, "cache_read": i / 10, "cache_write_5m": i * 1.25,
            "cache_write_1h": i * 2}


# USD per million tokens, standard (direct) rates; batch APIs bill half.
# Gemini 3.8 Flash doubles on 2027-01-01 ($1.50 / $7.50).
PRICES = {
    "gemini-3.8-flash": {"in": 0.75, "out": 3.75},
    "gemini-3.1-pro-preview": {"in": 2.00, "out": 12.00},
    "claude-opus-5-5": _claude_price(4.00, 20.00),
    "claude-sonnet-5-5": _claude_price(2.00, 10.00),
    "claude-haiku-5-5": _claude_price(0.10, 0.50),
}
DEFAULT_MODEL = {"gemini": GEMINI_MODEL, "claude": CLAUDE_MODELS["opus"]}
# The second whole-page reader when the subscription is nearly spent
# (--second-reader gemini|auto): as good as Opus on the eval (#751).
SECOND_READER_GEMINI = "gemini-3.1-pro-preview"
PROVIDER = {"kgc": "gemini", "gemini_page": "gemini", "opus_page": "claude",
            "synth1": "claude", "synth2": "claude"}


def _record_model(args: argparse.Namespace, stage: str, provider: str, model: str,
                  effort: str | None) -> None:
    """Note the model a stage runs with, for `cost`."""
    d = Path(args.out) / stage
    d.mkdir(parents=True, exist_ok=True)
    (d / "_model.json").write_text(json.dumps({"provider": provider, "model": model,
                                               "effort": effort}))


def _gemini(args: argparse.Namespace, stage: str) -> Gemini:
    _record_model(args, stage, "gemini", args.gemini_model, "low")
    return Gemini(args.gemini_model, thinking="low", batch=not args.direct,
                  state_dir=Path(args.out) / stage)


def _claude(args: argparse.Namespace, stage: str):
    model = CLAUDE_MODELS[args.claude_model]
    if args.claude == "cli":
        _record_model(args, stage, "claude", model, args.effort)
        # Under auto, a window that fills during the stage stops it (the calls
        # left are skipped), so the rest goes to Gemini or waits for a reset.
        stop_at = args.switch_at if args.second_reader == "auto" else None
        return ClaudeCLI(args.claude_model, effort=args.effort, stop_at=stop_at)
    _record_model(args, stage, "claude", model, args.effort or "medium")
    return ClaudeBatch(model, effort=args.effort or "medium", state_dir=Path(args.out) / stage)


def _with_windows(args: argparse.Namespace, run: stages.Run, stage: str, body) -> None:
    """Run a Claude stage; with claude -p, record the subscription windows around it."""
    if args.claude != "cli" or not run.todo(stage):
        body()
        return
    before = ClaudeCLI.windows()
    body()
    after = ClaudeCLI.windows()
    with (run.dir(stage) / "_windows.jsonl").open("a") as f:
        f.write(json.dumps({"before": before, "after": after}) + "\n")


def _windows_now(tries: int = 3) -> dict[str, float]:
    """The subscription's usage windows; {} when `claude -p` doesn't report them."""
    for _ in range(tries):
        w = ClaudeCLI.windows()
        if w:
            return w
    return {}


def _nearly_spent(args: argparse.Namespace) -> dict[str, float]:
    """The windows at or over --switch-at ({} when none is, or none could be read)."""
    if args.second_reader != "auto" or args.claude != "cli":
        return {}
    return {k: v for k, v in _windows_now().items() if v is not None and v >= args.switch_at}


def _backfill_usage(stage_dir: Path) -> None:
    """Tag the stage's usage lines that name no reader with the reader its
    _model.json records (Opus when it has none), before another reader may
    overwrite that file: ``cost`` prices each line by its own reader."""
    f = stage_dir / "_usage.jsonl"
    if not f.exists():
        return
    meta_f = stage_dir / "_model.json"
    meta = json.loads(meta_f.read_text()) if meta_f.exists() else {}
    provider = meta.get("provider", "claude")
    model = meta.get("model") or DEFAULT_MODEL[provider]
    lines = [json.loads(line) for line in f.read_text().splitlines()]
    if all("model" in r for r in lines):
        return
    for r in lines:
        if "model" not in r:
            r.update(provider=provider, model=model)
    f.write_text("".join(json.dumps(r, ensure_ascii=False, default=str) + "\n" for r in lines))


def _second_reader(args: argparse.Namespace, run: stages.Run, stage: str) -> None:
    """The second whole-page reader: Opus, or Gemini 3.1 Pro (--second-reader gemini,
    or auto when a subscription window is nearly spent).

    A run with no page to read changes nothing.  A Gemini batch already
    submitted for the stage (its checkpoint) is finished with Gemini whatever
    the windows say now, so its pages are not paid for twice.
    """
    if not run.todo(stage):
        return
    stage_dir = run.dir(stage)
    _backfill_usage(stage_dir)
    use_gemini = args.second_reader == "gemini"
    if not use_gemini and (stage_dir / "_batch_gemini.json").exists():
        log.info("%s: a Gemini batch is pending; finishing it with %s", stage,
                 SECOND_READER_GEMINI)
        use_gemini = True
    if not use_gemini:
        spent = _nearly_spent(args)
        if spent:
            log.info("subscription windows %s at or over %.0f%%: %s reads with %s", spent,
                     100 * args.switch_at, stage, SECOND_READER_GEMINI)
            use_gemini = True
    if use_gemini:
        _record_model(args, stage, "gemini", SECOND_READER_GEMINI, "low")
        backend = Gemini(SECOND_READER_GEMINI, thinking="low", batch=not args.direct,
                         state_dir=Path(args.out) / stage)
        stages.page_reader(run, stage, backend, provider="gemini", model=SECOND_READER_GEMINI)
        return
    claude = _claude(args, stage)
    _with_windows(args, run, stage, lambda: stages.page_reader(
        run, stage, claude, provider="claude", model=CLAUDE_MODELS[args.claude_model]))
    if getattr(claude, "stopped", None) and run.todo(stage):
        log.info("subscription windows %s at or over %.0f%% during %s: the %d pages left "
                 "read with %s", claude.stopped, 100 * args.switch_at, stage,
                 len(run.todo(stage)), SECOND_READER_GEMINI)
        _record_model(args, stage, "gemini", SECOND_READER_GEMINI, "low")
        backend = Gemini(SECOND_READER_GEMINI, thinking="low", batch=not args.direct,
                         state_dir=Path(args.out) / stage)
        stages.page_reader(run, stage, backend, provider="gemini", model=SECOND_READER_GEMINI)


def cmd_run(args: argparse.Namespace) -> int:
    if args.second_reader == "auto" and args.claude != "cli":
        log.error("--second-reader auto watches the subscription's windows, so it needs "
                  "--claude cli (with the default --claude api it would send paid API "
                  "requests instead)")
        return 2
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
            _second_reader(args, run, stage)
        elif stage in ("synth1", "synth2"):
            spent = _nearly_spent(args) if run.todo(stage) else {}
            if spent:
                log.warning("subscription windows %s at or over %.0f%%: stopping before %s; "
                            "run again once they reset", spent, 100 * args.switch_at, stage)
                return 3
            claude = _claude(args, stage)
            _with_windows(args, run, stage, lambda: stages.synth(run, stage, claude))
            if getattr(claude, "stopped", None) and run.todo(stage):
                log.warning("subscription windows %s at or over %.0f%% during %s: %d pages "
                            "left; run again once they reset", claude.stopped,
                            100 * args.switch_at, stage, len(run.todo(stage)))
                return 3
        elif stage == "final":
            stages.final(run)
    return 0


def _charge(provider: str, u: dict, model: str | None = None) -> tuple[float, float, float]:
    """(input tokens, output tokens, USD at direct rates) of one request.

    Claude's cache reads and writes are priced at their own rates: a read at
    0.1x input, a write at 1.25x (5-minute) or 2x (1-hour) input.
    """
    p = PRICES[model or DEFAULT_MODEL[provider]]
    if provider == "gemini":
        tin = u.get("promptTokenCount", 0)
        tout = u.get("candidatesTokenCount", 0) + (u.get("thoughtsTokenCount") or 0)
        return tin, tout, (tin * p["in"] + tout * p["out"]) / 1e6
    plain, read = u.get("input_tokens", 0), u.get("cache_read_input_tokens", 0)
    write = u.get("cache_creation_input_tokens", 0)
    by_ttl = u.get("cache_creation") or {}
    w1h = by_ttl.get("ephemeral_1h_input_tokens", 0)
    w5m = write - w1h
    tout = u.get("output_tokens", 0)
    usd = (plain * p["in"] + read * p["cache_read"] + w5m * p["cache_write_5m"]
           + w1h * p["cache_write_1h"] + tout * p["out"]) / 1e6
    return plain + read + write, tout, usd


def cmd_cost(args: argparse.Namespace) -> int:
    """Tokens and dollars per page for each stage, at direct and batch rates.

    For stages run through `claude -p`, also how far the run moved the
    subscription's usage windows (five_hour, seven_day), as percentage points.
    """
    out = Path(args.out)
    total = 0.0
    print(f"{'stage':12s} {'pages':>5s} {'in/page':>9s} {'out/page':>9s} {'$/page':>8s} "
          f"{'batch $/page':>13s}  subscription windows")
    for stage, provider in PROVIDER.items():
        f = out / stage / "_usage.jsonl"
        if not f.exists():
            continue
        meta_f = out / stage / "_model.json"
        meta = json.loads(meta_f.read_text()) if meta_f.exists() else {}
        model = meta.get("model")
        provider = meta.get("provider", provider)  # a stage may run on the other provider
        tin = tout = usd = 0.0
        windows: dict[str, list[float]] = defaultdict(list)
        for line in f.read_text().splitlines():
            r = json.loads(line)
            if r.get("error"):
                continue
            u = r["usage"] or {}
            # A stage may mix readers (--second-reader auto): each line says its own.
            i, o, d = _charge(r.get("provider") or provider, u, r.get("model") or model)
            tin, tout, usd = tin + i, tout + o, usd + d
            for w, v in (u.get("limits") or {}).items():
                if v is not None:
                    windows[w].append(v)
        # A page with no disputed line makes no synthesis request but still counts.
        n = len(list((out / stage).glob("*.txt"))) or 1
        total += usd / n
        win = "  ".join(f"{w} {100 * (max(v) - min(v)):.1f} pts"
                        for w, v in sorted(windows.items()))
        wf = out / stage / "_windows.jsonl"
        if wf.exists():  # before/after readings of each claude -p run of the stage
            used: dict[str, float] = defaultdict(float)
            for line in wf.read_text().splitlines():
                r = json.loads(line)
                for w, v in r["before"].items():
                    if w in r["after"]:
                        used[w] += r["after"][w] - v  # negative if the window reset meanwhile
            win = "  ".join(f"{w} {100 * v:.1f} pts" + (" (window reset?)" if v < 0 else "")
                            for w, v in sorted(used.items()))
        label = f"{meta.get('model', '')} {meta.get('effort') or ''}".strip()
        print(f"{stage:12s} {n:5d} {tin / n:9.0f} {tout / n:9.0f} {usd / n:8.4f} "
              f"{usd / n / 2:13.4f}  {win}  [{label}]")
    print(f"{'total':12s} {'':5s} {'':9s} {'':9s} {total:8.4f} {total / 2:13.4f}")
    return 0


def cmd_prepare(args: argparse.Namespace) -> int:
    from scripts.ocr import ogpg
    ogpg.prepare(args.volume, Path(args.out), Path(args.images_dir), Path(args.located),
                 args.limit, Path(args.run) if args.run else None)
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    from scripts.ocr import ogpg
    ogpg.export(Path(args.run), Path(args.prep), Path(args.ocr_dir))
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
    r.add_argument("--claude-model", choices=tuple(CLAUDE_MODELS), default="opus",
                   help="Claude model for the Claude stages (default opus)")
    r.add_argument("--gemini-model", default=GEMINI_MODEL,
                   help=f"Gemini model for the Gemini stages (default {GEMINI_MODEL})")
    r.add_argument("--second-reader", choices=("opus", "gemini", "auto"), default="opus",
                   help="the second whole-page reader (stage opus_page): Opus (default), "
                        f"{SECOND_READER_GEMINI}, or auto: Opus until a claude -p window "
                        "reaches --switch-at (before or during the stage; a reached limit "
                        "counts as full), then Gemini for the pages left; auto also stops "
                        "a synthesis stage while a window is that full (exit 3)")
    r.add_argument("--switch-at", type=float, default=0.95,
                   help="window utilization at which --second-reader auto switches (0.95)")
    r.add_argument("--effort", choices=("low", "medium", "high"),
                   help="Claude effort (default medium)")
    r.set_defaults(func=cmd_run)
    from scripts.ocr import ogpg
    pr = sub.add_parser("prepare", help="OGPG holes: crop the Greek column of each located page")
    pr.add_argument("--volume", required=True, help="e.g. vol-075")
    pr.add_argument("--out", required=True, help="directory for images/, pages.txt, prepare.jsonl")
    pr.add_argument("--images-dir", default=str(ogpg.IMAGES_DIR))
    pr.add_argument("--located", default=str(ogpg.LOCATED),
                    help="scripts.ogpg_images locate output")
    pr.add_argument("--limit", type=int, help="only the first N pages")
    pr.add_argument("--run", help="the run whose outputs of a re-cropped page are removed "
                                  "(default OUT/run)")
    pr.set_defaults(func=cmd_prepare)
    ex = sub.add_parser("export", help="OGPG holes: a run's pages -> data/ocr/ogpg/{volume}.jsonl")
    ex.add_argument("--run", required=True, help="the run's --out directory")
    ex.add_argument("--prep", required=True, help="the prepare --out directory")
    ex.add_argument("--ocr-dir", default=str(ogpg.OCR_DIR))
    ex.set_defaults(func=cmd_export)
    c = sub.add_parser("cost", help="tokens and dollars per page of a run")
    c.add_argument("--out", required=True)
    c.set_defaults(func=cmd_cost)
    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
