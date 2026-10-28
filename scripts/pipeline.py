"""
Run every data pipeline step once, in order, skipping what is current (#248).

    normalize → anchor → validate → translate → embed → align → build_index
    → export_library → upload_library

Each step is its own script, run as a subprocess exactly as by hand, and each
skips the work its fingerprints show is current (#130), so a run after a small
change is quick and a second run does next to nothing. The scripts stay the
tools for targeted work (``scripts.embed --work …``, ``scripts.align --group …``).
Ingestors are not run: re-ingest by hand, then run this with
``--accept-raw-change``.

Paid steps (anchor: Voyage, for the derived verses of enrolled translations,
#304; translate: OpenAI, plus Anthropic for what Sol's content filter blocks;
embed: Voyage) send requests only with ``--pay``. Without it the run
stops before the first paid step that has paid work, prints the estimate and
exits 0. A paid step whose estimate is $0 (a metadata-only change) runs anyway,
without calling the API or needing a key, and the run goes on. ``--max-cost``
caps the run's estimated spend; translate also gets the rest of it as its own
``--max-cost``.

Before any step, a preflight lists every problem at once: missing local data,
the API keys (with ``--pay``), the search database through the SSH tunnel
(``infra/db-tunnel.sh``, or ``--database-url``) and the library upload key.
With ``--pay`` nothing waits on a human after that. A failing step stops the
run; every step is idempotent, so the next run resumes. The run never commits:
it ends with ``scripts.status --check`` and the changed ``data/`` paths, for
you to commit. Output also goes to ``logs/pipeline-{time}.log``.

Usage::

    uv run --extra pipeline python -m scripts.pipeline --dry-run
    uv run --extra pipeline python -m scripts.pipeline [--pay [--max-cost 20]]
        [--accept-raw-change] [--skip upload_library] [--database-url URL]
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO

from patristica import alignment_store, fingerprint
from patristica import embeddings as emb
from patristica import translations as tr

log = logging.getLogger(__name__)

REPO = fingerprint.REPO_ROOT
NORMALIZED = REPO / "data" / "normalized"
RAW = REPO / "data" / "raw"
TRANSLATIONS = REPO / tr.DEFAULT_DIR
EMBEDDINGS = REPO / emb.DEFAULT_DIR
ALIGNMENTS = REPO / alignment_store.DEFAULT_DIR
LOG_DIR = REPO / "logs"
TUNNEL = REPO / "infra" / "db-tunnel.sh"

STEPS = ("normalize", "anchor", "validate", "translate", "embed", "align", "build_index",
         "export_library", "upload_library")
PAID = frozenset({"anchor", "translate", "embed"})
LIBRARY_KEYS = ("LIBRARY_ACCESS_KEY_ID", "LIBRARY_SECRET_ACCESS_KEY", "LIBRARY_BUCKET")
LFS_POINTER = b"version https://git-lfs"


class StepFailed(Exception):
    """A step failed, or the run must not go on (exit 1)."""


class Stop(Exception):
    """A paid step has paid work and ``--pay`` wasn't given (exit 0)."""


@dataclass
class Options:
    pay: bool = False
    max_cost: float | None = None
    accept_raw_change: bool = False
    skip: frozenset[str] = frozenset()
    database_url: str | None = None


@dataclass
class Result:
    step: str
    status: str  # done | skipped | stopped | failed
    detail: str = ""
    seconds: float = 0.0
    cost: float = 0.0  # estimated dollars sent to paid APIs


def python(module: str, *args: str) -> list[str]:
    return [sys.executable, "-m", module, *args]


# ---------------------------------------------------------------------------
# Running steps
# ---------------------------------------------------------------------------


class Runner:
    """Runs a command in the repo root, streaming its output to the console and
    the run log. Returns the exit code."""

    def __init__(self, log_file: BinaryIO | None = None) -> None:
        self.log_file = log_file

    def note(self, text: str) -> None:
        line = (text + "\n").encode("utf-8")
        sys.stdout.buffer.write(line)
        sys.stdout.flush()
        if self.log_file is not None:
            self.log_file.write(line)
            self.log_file.flush()

    def __call__(self, argv: list[str], *, tunnel: bool = False,
                 env: dict[str, str] | None = None) -> int:
        cmd = ([str(TUNNEL)] if tunnel else []) + argv
        self.note("$ " + " ".join(Path(c).name if c == sys.executable else c for c in cmd))
        full_env = {**os.environ, "PYTHONUNBUFFERED": "1", **(env or {})}
        with subprocess.Popen(cmd, cwd=REPO, env=full_env, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT) as proc:
            assert proc.stdout is not None
            for chunk in iter(lambda: proc.stdout.read1(65536), b""):
                sys.stdout.buffer.write(chunk)
                sys.stdout.flush()
                if self.log_file is not None:
                    self.log_file.write(chunk)
        return proc.returncode


class Estimates:
    """What the paid steps would send now: (units, estimated dollars)."""

    def translate(self, model: str = "sol") -> tuple[int, float]:
        from scripts import status, translate

        by_lang, _ = status.pending_translations(NORMALIZED, TRANSLATIONS)
        units = sum(by_lang.values())
        return units, units * translate.COST_PER_CHUNK * (
            translate.MODELS[model].price_out / translate.MODELS[translate.DEFAULT_MODEL].price_out)

    def embed(self) -> tuple[int, float]:
        from scripts import status

        return status.pending_vectors(NORMALIZED, TRANSLATIONS, EMBEDDINGS)

    def anchor(self) -> tuple[int, float]:
        """Works to cut and an upper bound of the cost (``scripts.anchor``)."""
        from scripts import anchor

        return anchor.pending(NORMALIZED, REPO / anchor.ANCHORS, EMBEDDINGS,
                              REPO / anchor.SCRATCH)


def changed_paths() -> list[str]:
    """Paths changed on this branch and in the working tree: the diff from the
    merge base with origin/master (else HEAD) to the working tree, plus
    untracked files."""
    def git(*args: str) -> list[str]:
        out = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
        return out.stdout.splitlines() if out.returncode == 0 else []

    base = (git("merge-base", "HEAD", "origin/master") or ["HEAD"])[0]
    return sorted(set(git("diff", "--name-only", base))
                  | set(git("ls-files", "--others", "--exclude-standard")))


def validate_inputs() -> list[str]:
    """The changed paths ``scripts.validate`` reads (empty: validate can be skipped)."""
    from scripts import validate

    return validate.inputs_changed(changed_paths())


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def env_value(name: str) -> str | None:
    """*name* from the environment, the repo-root ``.env`` or ``web/.env``."""
    from patristica.embedders import env_key

    for env_file in (REPO / ".env", REPO / "web" / ".env"):
        try:
            return env_key(name, env_file)
        except KeyError:
            continue
    return None


def verify_key(name: str, value: str) -> str | None:
    """Ask the provider whether *value* works (free model listings); the
    problem, or None. Keys without a free check are only checked present."""
    import httpx

    urls = {"OPENAI_API_KEY": ("https://api.openai.com/v1/models",
                               {"Authorization": f"Bearer {value}"}),
            "ANTHROPIC_API_KEY": ("https://api.anthropic.com/v1/models",
                                  {"x-api-key": value, "anthropic-version": "2023-06-01"})}
    if name not in urls:
        return None
    url, headers = urls[name]
    try:
        r = httpx.get(url, headers=headers, timeout=20)
    except httpx.HTTPError as exc:
        return f"could not reach {url}: {type(exc).__name__}"
    if r.status_code in (401, 403):
        return f"rejected by the provider (HTTP {r.status_code})"
    if r.status_code != 200:
        return f"HTTP {r.status_code} from {url}"
    return None


def check_database(url: str | None) -> str | None:
    """Run ``SELECT 1`` on the search database, through the tunnel unless
    *url* is given; the problem, or None."""
    probe = ("import os, psycopg\n"
             "with psycopg.connect(os.environ['DATABASE_URL'], connect_timeout=20) as c:\n"
             "    c.execute('SELECT 1')\n")
    cmd = [sys.executable, "-c", probe]
    env = {**os.environ, **({"DATABASE_URL": url} if url else {})}
    try:
        out = subprocess.run(cmd if url else [str(TUNNEL), *cmd], cwd=REPO, env=env,
                             capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return "timed out"
    if out.returncode != 0:
        last = (out.stderr.strip().splitlines() or ["no output"])[-1]
        return f"failed: {last}"
    return None


def lfs_pointers(root: Path, pattern: str) -> int:
    """Files under *root* that are git-lfs pointers rather than their content (#244)."""
    n = 0
    for path in root.rglob(pattern):
        with path.open("rb") as f:
            n += f.read(len(LFS_POINTER)) == LFS_POINTER
    return n


def preflight(opts: Options, *, lookup: Callable[[str], str | None] = env_value,
              verify: Callable[[str, str], str | None] = verify_key,
              database: Callable[[str | None], str | None] = check_database,
              normalized: Path = NORMALIZED, raw: Path = RAW,
              embeddings: Path = EMBEDDINGS) -> list[Check]:
    """Everything the run will need, checked up front. Paid keys only with --pay:
    without it a paid step runs only when it sends nothing."""
    checks = [Check("data/normalized", (normalized / "_works.jsonl").is_file(),
                    "" if (normalized / "_works.jsonl").is_file() else "no _works.jsonl"),
              Check("data/raw", raw.is_dir(), "" if raw.is_dir() else
                    "missing: run the pipeline on the fully materialized checkout")]
    if not {"embed", "anchor"} <= opts.skip:
        shards = embeddings.is_dir() and any(embeddings.rglob("*.npz"))
        pointers = lfs_pointers(embeddings, "*.npz") if shards else 0
        checks.append(Check(
            "data/embeddings", shards and not pointers,
            "" if shards and not pointers else
            f"{pointers} shards are git-lfs pointers: git lfs pull first" if pointers else
            "no vectors here: embed would re-embed the whole corpus"))
    if opts.pay:
        wanted = []
        if "translate" not in opts.skip:
            wanted += ["OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
        if not {"embed", "anchor"} <= opts.skip:
            wanted.append("VOYAGE_API_KEY")
        for name in wanted:
            value = lookup(name)
            problem = "not set (environment or .env)" if not value else verify(name, value)
            checks.append(Check(name, problem is None, problem or ""))
    if "build_index" not in opts.skip:
        problem = database(opts.database_url)
        where = "--database-url" if opts.database_url else "the SSH tunnel (infra/db-tunnel.sh)"
        checks.append(Check("search database", problem is None,
                            f"via {where}: {problem}" if problem else f"via {where}"))
    if "upload_library" not in opts.skip:
        missing = [k for k in LIBRARY_KEYS if not lookup(k)]
        checks.append(Check("library upload key", not missing,
                            f"not set: {', '.join(missing)}" if missing else ""))
    return checks


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


@dataclass
class Pipeline:
    opts: Options
    run_cmd: Callable[..., int]
    estimates: Estimates = field(default_factory=Estimates)
    validate_changes: Callable[[], list[str]] = validate_inputs
    results: list[Result] = field(default_factory=list)
    spent: float = 0.0

    def run(self) -> int:
        """Every step in order; the exit code (0 also when stopped for --pay)."""
        for step in STEPS:
            started = time.monotonic()
            result = Result(step, "done")
            if step in self.opts.skip:
                result.status, result.detail = "skipped", "--skip"
                self.results.append(result)
                continue
            try:
                result.detail, result.cost = getattr(self, step)()
                if result.detail.startswith("skipped"):
                    result.status = "skipped"
            except Stop as exc:
                result.status, result.detail = "stopped", str(exc)
            except StepFailed as exc:
                result.status, result.detail = "failed", str(exc)
            result.seconds = time.monotonic() - started
            self.spent += result.cost
            self.results.append(result)
            if result.status in ("stopped", "failed"):
                for later in STEPS[STEPS.index(step) + 1:]:
                    self.results.append(Result(later, "skipped", "not reached"))
                return 0 if result.status == "stopped" else 1
        return 0

    def _run(self, argv: list[str], **kw: object) -> None:
        code = self.run_cmd(argv, **kw)
        if code != 0:
            raise StepFailed(f"exit {code}: see its output above")

    def _budget(self, units: int, cost: float, pending: float = 0.0) -> None:
        """Raise unless *units* of paid work (~*cost*) may be sent, with *pending*
        already spent in this step."""
        if not self.opts.pay:
            raise Stop(f"{units:,} units to send (~${cost:,.2f}): re-run with --pay")
        so_far = self.spent + pending
        if self.opts.max_cost is not None and so_far + cost > self.opts.max_cost:
            raise StepFailed(f"~${cost:,.2f} would exceed --max-cost ${self.opts.max_cost:,.2f} "
                             f"(~${so_far:,.2f} spent so far)")

    def _cap(self, pending: float = 0.0) -> list[str]:
        """translate's own --max-cost: what is left of the run's."""
        if self.opts.max_cost is None:
            return []
        return ["--max-cost", f"{self.opts.max_cost - self.spent - pending:.2f}"]

    def normalize(self) -> tuple[str, float]:
        self._run(python("scripts.normalize",
                         *(["--accept-raw-change"] if self.opts.accept_raw_change else [])))
        return "", 0.0

    def anchor(self) -> tuple[str, float]:
        works, cost = self.estimates.anchor()
        if not works:  # no cut file missing or stale: nothing to run, no key needed
            return "nothing to cut", 0.0
        self._budget(works, cost)
        self._run(python("scripts.anchor", "--pay", *self._cap()))
        return f"{works:,} works cut (the estimate is an upper bound)", cost

    def validate(self) -> tuple[str, float]:
        changed = self.validate_changes()
        if not changed:
            return "skipped: nothing validate reads changed", 0.0
        self._run(python("scripts.validate"))
        return f"{len(changed)} changed inputs, e.g. {changed[0]}", 0.0

    def translate(self) -> tuple[str, float]:
        units, cost = self.estimates.translate()
        if not units:  # reuses identical text and drops stale rows; sends nothing
            self._run(python("scripts.translate"))
            return "nothing to send", 0.0
        self._budget(units, cost)
        self._run(python("scripts.translate", *self._cap()))
        spent, detail = cost, f"{units:,} units with Sol"
        left, opus_cost = self.estimates.translate("opus")
        if left:  # what Sol's content filter blocked (or what failed): Claude Opus
            self._budget(left, opus_cost, pending=spent)
            self._run(python("scripts.translate", "--model", "opus", *self._cap(pending=spent)))
            spent += opus_cost
            detail += f", {left:,} retried with Opus"
            still, _ = self.estimates.translate()
            if still:
                detail += f"; {still:,} still untranslated (see the log)"
        return detail, spent

    def embed(self) -> tuple[str, float]:
        units, cost = self.estimates.embed()
        if not units:  # rewrites and prunes shards; needs no key
            self._run(python("scripts.embed", "--no-requests"))
            return "nothing to send", 0.0
        self._budget(units, cost)
        self._run(python("scripts.embed"))
        return f"{units:,} vectors", cost

    def align(self) -> tuple[str, float]:
        self._run(python("scripts.align"))
        return "", 0.0

    def build_index(self) -> tuple[str, float]:
        if self.opts.database_url:
            self._run(python("scripts.build_index"),
                      env={"DATABASE_URL": self.opts.database_url})
        else:
            self._run(python("scripts.build_index"), tunnel=True)
        return "", 0.0

    def export_library(self) -> tuple[str, float]:
        self._run(python("scripts.export_library"))
        return "", 0.0

    def upload_library(self) -> tuple[str, float]:
        self._run(python("scripts.upload_library"))
        return "", 0.0


def render(results: list[Result]) -> str:
    lines = [f"{'step':<15} {'result':<8} {'time':>7} {'cost':>9}  detail"]
    for r in results:
        cost = f"~${r.cost:,.2f}" if r.cost else ""
        secs = f"{r.seconds:.0f}s" if r.seconds else ""
        lines.append(f"{r.step:<15} {r.status:<8} {secs:>7} {cost:>9}  {r.detail}")
    total = sum(r.cost for r in results)
    if total:
        lines.append(f"estimated spend: ~${total:,.2f} (each paid step logs what it spent)")
    return "\n".join(lines)


def changed_data() -> list[str]:
    out = subprocess.run(["git", "status", "--short", "--", "data/"], cwd=REPO,
                         capture_output=True, text=True)
    return out.stdout.splitlines()


def dry_run(opts: Options, run_cmd: Runner) -> int:
    """Report what a run would do; send and write nothing."""
    checks = preflight(opts)
    db_ok = all(c.ok for c in checks if c.name == "search database")
    status_args = ["--raw", "--vectors"]
    if "build_index" not in opts.skip and db_ok:
        status_args.append("--db")
    run_cmd(python("scripts.status", *status_args),
            tunnel="--db" in status_args and not opts.database_url,
            env={"DATABASE_URL": opts.database_url} if opts.database_url else None)
    est = Estimates()
    works, acost = est.anchor() if "anchor" not in opts.skip else (0, 0.0)
    units, cost = est.translate()
    vectors, vcost = est.embed()
    changed = validate_inputs()
    print("\nBefore normalize runs (its rebuilt works can add to these):")
    print(f"  anchor: {works:,} works to cut (≤ ~${acost:,.2f})")
    print(f"  translate: {units:,} units (~${cost:,.2f})")
    print(f"  embed: {vectors:,} vectors (~${vcost:,.2f}), more once translate has run")
    print(f"  validate: {'runs' if changed else 'skipped'} "
          f"({len(changed)} of its inputs changed)")
    print("\nPreflight:")
    for c in checks:
        print(f"  {'ok  ' if c.ok else 'FAIL'} {c.name}" + (f": {c.detail}" if c.detail else ""))
    if not opts.pay:
        print("\nWithout --pay the run stops before anchor, translate or embed if one "
              "has work.")
    return 0 if all(c.ok for c in checks) else 1


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--pay", action="store_true",
                   help="let anchor, translate and embed send paid requests")
    p.add_argument("--max-cost", type=float, metavar="USD",
                   help="refuse paid work that would take the run's estimated spend past this")
    p.add_argument("--dry-run", action="store_true",
                   help="report what is stale, the costs and the preflight; change nothing")
    p.add_argument("--accept-raw-change", action="store_true",
                   help="pass to normalize after a deliberate re-ingest")
    p.add_argument("--skip", action="append", default=[], choices=STEPS, metavar="STEP",
                   help=f"leave out a step (repeatable): {', '.join(STEPS)}")
    p.add_argument("--database-url",
                   help="load this database instead of production through infra/db-tunnel.sh")
    args = p.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    opts = Options(pay=args.pay, max_cost=args.max_cost, accept_raw_change=args.accept_raw_change,
                   skip=frozenset(args.skip), database_url=args.database_url)

    if args.dry_run:
        sys.exit(dry_run(opts, Runner()))

    checks = preflight(opts)
    failed = [c for c in checks if not c.ok]
    if failed:
        for c in failed:
            log.error("preflight: %s: %s", c.name, c.detail)
        sys.exit(1)
    LOG_DIR.mkdir(exist_ok=True)
    log_path = LOG_DIR / f"pipeline-{time.strftime('%Y%m%d-%H%M%S')}.log"
    with log_path.open("wb") as log_file:
        runner = Runner(log_file)
        pipeline = Pipeline(opts, runner)
        try:
            code = pipeline.run()
        except KeyboardInterrupt:
            runner.note("interrupted: every step is idempotent, so the next run resumes")
            code = 130
        if code == 0 and not any(r.status == "stopped" for r in pipeline.results):
            if runner(python("scripts.status", "--check")) != 0:
                runner.note("scripts.status --check failed: see the table above")
                code = 1
        runner.note("\n" + render(pipeline.results))
        changed = changed_data()
        runner.note(f"\n{len(changed)} changed paths under data/" + (
            ":\n" + "\n".join(changed[:30]) + ("\n…" if len(changed) > 30 else "")
            + "\nReview them (git diff), then commit." if changed else "."))
        runner.note(f"log: {log_path.relative_to(REPO)}")
    sys.exit(code)


if __name__ == "__main__":
    main()
