"""Tests for scripts.pipeline (#248): step order, the --pay gate, the cost cap,
fail-fast and the preflight. Steps are stubbed: nothing runs or is sent."""

from __future__ import annotations

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

    def __init__(self, translate=(), embed=()) -> None:
        self._translate, self._embed = list(translate), list(embed)

    def translate(self, model: str = "sol") -> tuple[int, float]:
        return self._translate.pop(0) if self._translate else (0, 0.0)

    def embed(self) -> tuple[int, float]:
        return self._embed.pop(0) if self._embed else (0, 0.0)


def make(fail=(), changes=("data/normalized/kjv/gen.json",), translate=(), embed=(), **opts):
    runner = FakeRunner(fail)
    p = pl.Pipeline(pl.Options(**opts), runner, FakeEstimates(translate, embed),
                    validate_changes=lambda: list(changes))
    return p, runner


def statuses(p: pl.Pipeline) -> dict[str, str]:
    return {r.step: r.status for r in p.results}


def test_runs_every_step_in_order_and_sends_nothing_at_zero_cost():
    p, runner = make()
    assert p.run() == 0
    assert runner.commands == [
        ["scripts.normalize"], ["scripts.validate"], ["scripts.translate"],
        ["scripts.embed", "--no-requests"], ["scripts.align"], ["scripts.build_index"],
        ["scripts.export_library"], ["scripts.upload_library"]]
    assert [r.step for r in p.results] == list(pl.STEPS)
    assert set(statuses(p).values()) == {"done"}
    assert dict(runner.calls[5][1]) == {"tunnel": True}  # build_index: production via the tunnel


def test_without_pay_stops_before_the_first_paid_step_with_work():
    p, runner = make(translate=[(100, 0.14)])
    assert p.run() == 0
    assert runner.commands == [["scripts.normalize"], ["scripts.validate"]]
    assert statuses(p)["translate"] == "stopped"
    assert "100 units" in p.results[2].detail and "--pay" in p.results[2].detail
    assert all(r.status == "skipped" for r in p.results[3:])


def test_without_pay_a_free_translate_runs_and_the_run_stops_at_embed():
    p, runner = make(embed=[(5000, 0.6)])
    assert p.run() == 0
    assert runner.commands[-1] == ["scripts.translate"]
    assert statuses(p)["embed"] == "stopped"


def test_with_pay_sends_and_adds_up_the_cost():
    p, runner = make(pay=True, translate=[(100, 0.14)], embed=[(5000, 0.6)])
    assert p.run() == 0
    assert ["scripts.translate"] in runner.commands and ["scripts.embed"] in runner.commands
    assert p.spent == pytest.approx(0.74)
    assert "~$0.74" in pl.render(p.results)


def test_max_cost_caps_translate_and_refuses_what_would_exceed_it():
    p, runner = make(pay=True, max_cost=12.0, translate=[(1000, 5.0)], embed=[(9, 10.0)])
    assert p.run() == 1
    assert ["scripts.translate", "--max-cost", "12.00"] in runner.commands
    assert statuses(p)["embed"] == "failed"
    assert "--max-cost" in p.results[3].detail
    assert not any(c[0] == "scripts.embed" for c in runner.commands)
    assert statuses(p)["align"] == "skipped"


def test_what_sol_left_is_retried_with_opus():
    p, runner = make(pay=True, max_cost=20.0,
                     translate=[(100, 1.0), (3, 0.5), (1, 0.0)])
    assert p.run() == 0
    assert runner.commands[2:4] == [["scripts.translate", "--max-cost", "20.00"],
                                    ["scripts.translate", "--model", "opus", "--max-cost", "19.00"]]
    translate = p.results[2]
    assert translate.cost == pytest.approx(1.5)
    assert "3 retried with Opus" in translate.detail and "1 still untranslated" in translate.detail


def test_a_failing_step_stops_the_run():
    p, runner = make(fail=("scripts.align",))
    assert p.run() == 1
    assert runner.commands[-1] == ["scripts.align"]
    assert statuses(p)["align"] == "failed"
    assert [r.detail for r in p.results[5:]] == ["not reached"] * 3


def test_validate_runs_only_when_its_inputs_changed():
    p, runner = make(changes=())
    p.run()
    assert ["scripts.validate"] not in runner.commands
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


def run_preflight(data, opts, keys=(), bad=(), db=None):
    asked: list[str] = []

    def verify(name, value):
        asked.append(name)
        return "rejected by the provider (HTTP 401)" if name in bad else None

    checks = pl.preflight(opts, lookup=lambda k: "secret" if k in keys else None,
                          verify=verify, database=lambda url: db, **data)
    return {c.name: c for c in checks}, asked


def test_preflight_without_pay_checks_no_api_keys(data):
    checks, asked = run_preflight(data, pl.Options(), keys=pl.LIBRARY_KEYS)
    assert all(c.ok for c in checks.values())
    assert asked == [] and "VOYAGE_API_KEY" not in checks


def test_preflight_lists_every_problem_at_once(data):
    checks, asked = run_preflight(data, pl.Options(pay=True), keys=("OPENAI_API_KEY",),
                                  bad=("OPENAI_API_KEY",), db="failed: connection refused")
    failed = {name for name, c in checks.items() if not c.ok}
    assert failed == {"OPENAI_API_KEY", "ANTHROPIC_API_KEY", "VOYAGE_API_KEY",
                      "search database", "library upload key"}
    assert asked == ["OPENAI_API_KEY"]  # only present keys are tried
    assert "secret" not in " ".join(c.detail for c in checks.values())


def test_preflight_skipped_steps_need_nothing(data):
    opts = pl.Options(pay=True, skip=frozenset({"translate", "embed", "build_index",
                                                "upload_library"}))
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
