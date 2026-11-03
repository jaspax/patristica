"""Tests for scripts.pipeline (#248): step order, the --pay gate, the cost cap,
fail-fast and the preflight. Steps are stubbed: nothing runs or is sent."""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

from scripts import pipeline as pl


class FakeRunner:
    """Records each command; fails the commands whose module is in *fail*."""

    def __init__(self, fail: tuple[str, ...] = ()) -> None:
        self.calls: list[tuple[list[str], dict]] = []
        self.fail = fail

    def __call__(self, argv: list[str], **kw) -> int:
        self.calls.append((argv[2:], kw))  # drop the interpreter and -m
        return 1 if argv[2] in self.fail else 0

    @property
    def commands(self) -> list[list[str]]:
        return [argv for argv, _ in self.calls]


class FakeEstimates:
    """Scripted (units, cost) answers, in call order; then (0, 0)."""

    def anchor(self) -> tuple[int, float]:
        return self._anchor.pop(0) if self._anchor else (0, 0.0)

    def __init__(self, translate=(), embed=(), anchor=()) -> None:
        self._translate, self._embed, self._anchor = list(translate), list(embed), list(anchor)
        self.models: list[str] = []

    def translate(self, model: str = pl.DEFAULT_TRANSLATE_MODEL) -> tuple[int, float]:
        self.models.append(model)
        return self._translate.pop(0) if self._translate else (0, 0.0)

    def embed(self) -> tuple[int, float]:
        return self._embed.pop(0) if self._embed else (0, 0.0)


def make(fail=(), changes=("data/normalized/kjv/gen.json",), translate=(), embed=(),
         anchor=(), **opts):
    runner = FakeRunner(fail)
    p = pl.Pipeline(pl.Options(**opts), runner, FakeEstimates(translate, embed, anchor),
                    validate_changes=lambda: list(changes))
    return p, runner


def statuses(p: pl.Pipeline) -> dict[str, str]:
    return {r.step: r.status for r in p.results}


def test_runs_every_step_in_order_and_sends_nothing_at_zero_cost():
    p, runner = make()
    assert p.run() == 0
    assert runner.commands == [
        ["scripts.normalize"], ["scripts.anchor", "--check"], ["scripts.validate", "--brief"],
        ["scripts.translate"],
        ["scripts.embed", "--no-requests"], ["scripts.align"], ["scripts.build_index"],
        ["scripts.export_library"], ["scripts.upload_library"]]
    assert [r.step for r in p.results] == list(pl.STEPS)
    assert set(statuses(p).values()) == {"done"}
    assert dict(runner.calls[6][1]) == {"tunnel": True}  # build_index: production via the tunnel


def test_without_pay_stops_before_the_first_paid_step_with_work():
    p, runner = make(translate=[(100, 0.14)])
    assert p.run() == 0
    assert runner.commands == [["scripts.normalize"], ["scripts.anchor", "--check"],
                               ["scripts.validate", "--brief"]]
    assert statuses(p)["translate"] == "stopped"
    assert "100 units" in p.results[3].detail and "--pay" in p.results[3].detail
    assert all(r.status == "skipped" for r in p.results[4:])


def test_without_pay_a_free_translate_runs_and_the_run_stops_at_embed():
    p, runner = make(embed=[(5000, 0.6)])
    assert p.run() == 0
    assert runner.commands[-1] == ["scripts.translate"]
    assert statuses(p)["embed"] == "stopped"


def test_with_pay_sends_and_adds_up_the_cost():
    p, runner = make(pay=True, translate=[(100, 0.14)], embed=[(5000, 0.6)])
    assert p.run() == 0
    assert LOCAL in runner.commands and ["scripts.embed"] in runner.commands
    assert p.spent == pytest.approx(0.74)
    assert "~$0.74" in pl.render(p.results)


def test_max_cost_caps_translate_and_refuses_what_would_exceed_it():
    p, runner = make(pay=True, max_cost=12.0, translate=[(1000, 5.0)], embed=[(9, 10.0)])
    assert p.run() == 1
    assert [*LOCAL, "--max-cost", "12.00"] in runner.commands
    assert statuses(p)["embed"] == "failed"
    assert "--max-cost" in p.results[4].detail
    assert not any(c[0] == "scripts.embed" for c in runner.commands)
    assert statuses(p)["align"] == "skipped"


LOCAL = ["scripts.translate", "--model", "local-opus", "--workers", "4"]


def test_translate_uses_local_opus_by_default_with_no_api_fallback():
    p, runner = make(pay=True, translate=[(100, 0.0), (2, 0.0)])
    assert p.run() == 0
    assert [c for c in runner.commands if c[0] == "scripts.translate"] == [LOCAL]
    assert set(p.estimates.models) == {"local-opus"}
    translate = p.results[3]
    assert translate.cost == 0
    assert "100 units with local-opus" in translate.detail
    assert "2 still untranslated" in translate.detail


def test_local_opus_still_needs_pay():
    p, runner = make(translate=[(100, 0.0)])
    assert p.run() == 0
    assert statuses(p)["translate"] == "stopped"
    assert not any(c[0] == "scripts.translate" for c in runner.commands)


def test_what_sol_left_is_retried_with_opus():
    p, runner = make(pay=True, max_cost=20.0, translate_model="sol",
                     translate=[(100, 1.0), (3, 0.5), (1, 0.0)])
    assert p.run() == 0
    assert runner.commands[3:5] == [["scripts.translate", "--model", "sol", "--max-cost", "20.00"],
                                    ["scripts.translate", "--model", "opus", "--max-cost", "19.00"]]
    translate = p.results[3]
    assert translate.cost == pytest.approx(1.5)
    assert "3 retried with Opus" in translate.detail and "1 still untranslated" in translate.detail


def test_a_failing_step_stops_the_run():
    p, runner = make(fail=("scripts.align",))
    assert p.run() == 1
    assert runner.commands[-1] == ["scripts.align"]
    assert statuses(p)["align"] == "failed"
    assert [r.detail for r in p.results[6:]] == ["not reached"] * 3


def test_anchor_is_free_when_no_cut_file_is_stale():
    p, runner = make()
    p.run()
    assert [c for c in runner.commands if c[0] == "scripts.anchor"] == [
        ["scripts.anchor", "--check"]]  # no --pay: no key, nothing sent
    assert p.results[1].step == "anchor" and p.results[1].detail == "nothing to cut"


def test_a_failing_anchor_check_stops_the_run_before_publishing():
    p, runner = make(fail=("scripts.anchor",))
    assert p.run() == 1
    assert statuses(p)["anchor"] == "failed"
    assert runner.commands[-1] == ["scripts.anchor", "--check"]


def test_anchor_needs_pay_and_counts_against_max_cost():
    p, runner = make(anchor=[(2, 0.05)])
    assert p.run() == 0
    assert runner.commands == [["scripts.normalize"]]
    assert statuses(p)["anchor"] == "stopped" and "--pay" in p.results[1].detail

    p, runner = make(pay=True, max_cost=1.0, anchor=[(2, 0.05)], translate=[(10, 0.96)])
    assert p.run() == 1
    assert runner.commands[1] == ["scripts.anchor", "--pay", "--max-cost", "1.00"]
    assert statuses(p)["translate"] == "failed"
    assert p.spent == pytest.approx(0.05)


def test_validate_runs_only_when_its_inputs_changed():
    p, runner = make(changes=())
    p.run()
    assert ["scripts.validate", "--brief"] not in runner.commands
    assert statuses(p)["validate"] == "skipped"


def test_skip_database_url_and_accept_raw_change():
    p, runner = make(skip=frozenset({"upload_library"}), database_url="postgresql://x/y",
                     accept_raw_change=True)
    assert p.run() == 0
    assert runner.commands[0] == ["scripts.normalize", "--accept-raw-change"]
    assert ["scripts.upload_library"] not in runner.commands
    build = runner.calls[runner.commands.index(["scripts.build_index"])][1]
    assert build == {"env": {"DATABASE_URL": "postgresql://x/y"}}
    assert statuses(p)["upload_library"] == "skipped"


# ---------------------------------------------------------------------------
# Preflight
# ---------------------------------------------------------------------------


@pytest.fixture
def data(tmp_path: Path) -> dict[str, Path]:
    norm, raw, vecs = tmp_path / "normalized", tmp_path / "raw", tmp_path / "embeddings"
    norm.mkdir()
    (norm / "_works.jsonl").write_text("{}\n")
    raw.mkdir()
    (vecs / "kjv").mkdir(parents=True)
    (vecs / "kjv" / "gen.npz").write_bytes(b"PK\x03\x04 a real shard")
    return {"normalized": norm, "raw": raw, "embeddings": vecs}


def run_preflight(data, opts, keys=(), bad=(), db=None, claude="/usr/bin/claude"):
    asked: list[str] = []

    def verify(name, value):
        asked.append(name)
        return "rejected by the provider (HTTP 401)" if name in bad else None

    checks = pl.preflight(opts, lookup=lambda k: "secret" if k in keys else None,
                          verify=verify, database=lambda url: db,
                          which=lambda name: claude, **data)
    return {c.name: c for c in checks}, asked


def test_preflight_without_pay_checks_no_api_keys(data):
    checks, asked = run_preflight(data, pl.Options(), keys=pl.LIBRARY_KEYS)
    assert all(c.ok for c in checks.values())
    assert asked == [] and "VOYAGE_API_KEY" not in checks


def test_preflight_local_opus_needs_the_claude_cli_not_api_keys(data):
    checks, asked = run_preflight(data, pl.Options(pay=True),
                                  keys=("VOYAGE_API_KEY", *pl.LIBRARY_KEYS))
    assert all(c.ok for c in checks.values())
    assert "OPENAI_API_KEY" not in checks and "ANTHROPIC_API_KEY" not in checks
    assert checks["claude CLI (local-opus)"].ok

    checks, _ = run_preflight(data, pl.Options(pay=True), claude=None,
                              keys=("VOYAGE_API_KEY", *pl.LIBRARY_KEYS))
    assert not checks["claude CLI (local-opus)"].ok


def test_preflight_opus_needs_only_the_anthropic_key(data):
    checks, asked = run_preflight(data, pl.Options(pay=True, translate_model="opus"),
                                  keys=("ANTHROPIC_API_KEY", "VOYAGE_API_KEY",
                                        *pl.LIBRARY_KEYS))
    assert all(c.ok for c in checks.values()) and "OPENAI_API_KEY" not in checks
    assert "claude CLI (local-opus)" not in checks


def test_preflight_lists_every_problem_at_once(data):
    checks, asked = run_preflight(data, pl.Options(pay=True, translate_model="sol"),
                                  keys=("OPENAI_API_KEY",),
                                  bad=("OPENAI_API_KEY",), db="failed: connection refused")
    failed = {name for name, c in checks.items() if not c.ok}
    assert failed == {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "VOYAGE_API_KEY",
                      "search database", "library upload key"}
    assert asked == ["OPENAI_API_KEY"]  # only present keys are tried
    assert "secret" not in " ".join(c.detail for c in checks.values())


def test_preflight_skipped_steps_need_nothing(data):
    opts = pl.Options(pay=True, skip=frozenset({"anchor", "translate", "embed",
                                                "build_index", "upload_library"}))
    checks, _ = run_preflight(data, opts)
    assert set(checks) == {"data/normalized", "data/raw"}


def test_preflight_refuses_missing_vectors_and_lfs_pointers(data):
    (data["embeddings"] / "kjv" / "gen.npz").write_bytes(
        b"version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 12\n")
    checks, _ = run_preflight(data, pl.Options(), keys=pl.LIBRARY_KEYS)
    assert not checks["data/embeddings"].ok and "pointers" in checks["data/embeddings"].detail

    (data["embeddings"] / "kjv" / "gen.npz").unlink()
    checks, _ = run_preflight(data, pl.Options(), keys=pl.LIBRARY_KEYS)
    assert "re-embed the whole corpus" in checks["data/embeddings"].detail


# ---------------------------------------------------------------------------
# Console output (#535)
# ---------------------------------------------------------------------------


def console(width: int = 60) -> tuple[pl.Console, io.BytesIO, io.BytesIO]:
    screen, log = io.BytesIO(), io.BytesIO()
    return pl.Console(log, stream=screen, width=width, color=False), screen, log


def test_the_log_keeps_each_progress_bar_once_and_the_last_line_is_the_summary():
    out, screen, log = console()
    out.output(b"works:  10%|#  | 1/10 [00:01<00:09, 1.0work/s]\rworks: 100%|###| 10/10 "
               b"[00:10<00:00, 1.0work/s]\nregroup: 0work [00:00, ?work/s]\n")
    out.output(b"\rfold:  50%|#  | 1/2 [00:01<00:01]\r       \r")  # a bar that cleared itself
    out.output(b"10 works, 3 to embed")
    out.end_output()
    assert log.getvalue().decode().splitlines() == [
        "works: 100%|###| 10/10 [00:10<00:00, 1.0work/s]", "regroup: 0work [00:00, ?work/s]",
        "10 works, 3 to embed"]
    assert out.last_line == "10 works, 3 to embed"
    assert b"1/10" in screen.getvalue()  # the console gets every redraw


def test_each_step_is_headed_and_closed_and_the_table_takes_its_summary():
    out, screen, _ = console()
    p = pl.Pipeline(pl.Options(skip=frozenset({"upload_library"})), FakeRunner(),
                    FakeEstimates(), validate_changes=lambda: [], console=out)

    def normalize() -> tuple[str, float]:
        out.output(b"276 total chunks written\n")
        return "", 0.0

    p.normalize = normalize
    assert p.run() == 0
    text = screen.getvalue().decode()
    assert "── [1/9] normalize ──" in text and "── [9/9]" not in text
    assert "✓ normalize done in 0s" in text
    assert "– [9/9] upload_library: skipped (--skip)" in text
    assert "– validate skipped in 0s · skipped: nothing validate reads changed" in text
    assert p.results[0].detail == "276 total chunks written"
    assert all(len(line) <= 60 for line in text.splitlines() if line.startswith("──"))


def test_summary_table_totals_and_fits_the_width():
    results = [pl.Result("translate", "done", "x" * 200, 65, 0.5),
               pl.Result("embed", "failed", "exit 1", 3725, 1.25)]
    table = pl.render(results, width=80).splitlines()
    assert all(len(line) <= 80 for line in table)
    assert table[1].startswith("✓ translate") and table[1].endswith("…")
    assert "1h 02m" in table[2] and table[2].startswith("✗ embed")
    assert table[-1].split()[:3] == ["total", "1h", "03m"] and "~$1.75" in table[-1]


def test_duration():
    assert [pl.duration(s) for s in (4.4, 98, 3600 + 125)] == ["4s", "1m 38s", "1h 02m"]


def test_runner_passes_the_width_and_level_and_runs_modules_through_the_launcher(monkeypatch):
    out, screen, log = console(width=123)
    runner = pl.Runner(out, verbosity=2)
    code = runner([sys.executable, "-c",
                   "import os; print(os.environ['COLUMNS'], os.environ['PATRISTICA_LOG_LEVEL'])"])
    assert code == 0 and out.last_line == "123 TRACE"
    calls = []
    monkeypatch.setattr(pl.subprocess, "Popen", lambda cmd, **kw: calls.append(cmd) or 1 / 0)
    with pytest.raises(ZeroDivisionError):
        runner(pl.python("scripts.validate", "--brief"))
    assert calls[0][1:] == ["-m", "patristica.console", "scripts.validate", "--brief"]
    assert "$ python" in screen.getvalue().decode().splitlines()[-1]
    assert "patristica.console" not in screen.getvalue().decode()
