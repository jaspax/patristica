"""Tests for patristica.console (#535): the steps' shared log format and levels."""

from __future__ import annotations

import io
import logging
import subprocess
import sys
from pathlib import Path

import pytest

from patristica import console


@pytest.fixture
def root():
    """The root logger, restored after the test."""
    logger = logging.getLogger()
    handlers, level = list(logger.handlers), logger.level
    yield logger
    for h in list(logger.handlers):
        logger.removeHandler(h)
    for h in handlers:
        logger.addHandler(h)
    logger.setLevel(level)
    console._main_module = None


def record(level: int, msg: str, *args: object, name: str = "scripts.x") -> logging.LogRecord:
    return logging.LogRecord(name, level, __file__, 1, msg, args, None)


def test_info_is_the_message_alone_and_the_rest_is_labelled():
    f = console.ConsoleFormatter()
    assert f.format(record(logging.INFO, "%d works", 3)) == "3 works"
    assert f.format(record(logging.WARNING, "careful")) == "warning: careful"
    assert f.format(record(logging.ERROR, "broken")) == "error: broken"
    assert f.format(record(logging.DEBUG, "detail")) == "debug scripts.x: detail"
    assert f.format(record(console.TRACE, "round 1")) == "trace scripts.x: round 1"


def test_level_from_the_environment(monkeypatch):
    monkeypatch.delenv(console.LEVEL_ENV, raising=False)
    assert console.level_from_env(logging.WARNING) == logging.WARNING
    for value, level in (("debug", logging.DEBUG), ("TRACE", console.TRACE), ("15", 15)):
        monkeypatch.setenv(console.LEVEL_ENV, value)
        assert console.level_from_env() == level
    monkeypatch.setenv(console.LEVEL_ENV, "loud")
    with pytest.raises(ValueError, match="loud"):
        console.level_from_env()


def test_demoted_messages_show_only_at_debug(root):
    demote = console.Demote({"scripts.normalize": frozenset({"Wrote %s (%d works)"})})
    root.setLevel(logging.INFO)
    wrote = record(logging.INFO, "Wrote %s (%d works)", "x", 2, name="scripts.normalize")
    assert not demote.filter(wrote)
    assert wrote.levelname == "DEBUG"
    assert demote.filter(record(logging.INFO, "Normalization complete", name="scripts.normalize"))
    assert demote.filter(record(logging.INFO, "Wrote %s (%d works)", name="scripts.other"))
    root.setLevel(logging.DEBUG)
    assert demote.filter(record(logging.INFO, "Wrote %s (%d works)", name="scripts.normalize"))


def test_every_demoted_message_is_still_logged_by_its_module():
    """A demotion whose message changed would silently stop working."""
    for module, messages in console.DEMOTED.items():
        source = Path(__file__).parents[1].joinpath(*module.split(".")).with_suffix(".py")
        text = source.read_text(encoding="utf-8")
        for msg in messages:
            assert f'"{msg}"' in text, (module, msg)


def test_the_launched_module_is_named_for_its_main_logger(root):
    console._main_module = "scripts.normalize"
    rec = record(logging.INFO, "Wrote %s (%d works)", "x", 2, name="__main__")
    root.setLevel(logging.INFO)
    assert not console.Demote().filter(rec)
    assert console.ConsoleFormatter().format(rec) == "debug scripts.normalize: Wrote x (2 works)"


def test_setup_is_idempotent_and_quiets_libraries(root, monkeypatch):
    monkeypatch.delenv(console.LEVEL_ENV, raising=False)
    root.addHandler(logging.StreamHandler(io.StringIO()))  # e.g. pytest's or a basicConfig
    assert console.setup_logging() == logging.INFO
    assert console.setup_logging(logging.WARNING) == logging.WARNING
    assert len(root.handlers) == 1 and isinstance(root.handlers[0], console.TqdmHandler)
    assert root.level == logging.WARNING
    assert logging.getLogger("httpx").level == logging.WARNING
    monkeypatch.setenv(console.LEVEL_ENV, "TRACE")
    console.setup_logging()
    assert logging.getLogger("httpx").level == logging.NOTSET


def test_launcher_configures_logging_before_the_module_does(tmp_path):
    """A module's own basicConfig is a no-op under the launcher: its logger
    ``__main__`` gets the shared format and the demotions."""
    (tmp_path / "chatty.py").write_text(
        "import logging\n"
        "log = logging.getLogger(__name__)\n"
        "logging.basicConfig(level=logging.INFO, format='%(levelname)s %(name)s: %(message)s')\n"
        "log.info('summary')\n"
        "log.warning('careful')\n")
    out = subprocess.run([sys.executable, "-m", "patristica.console", "chatty"],
                         capture_output=True, text=True, check=True,
                         env={"PYTHONPATH": f"{tmp_path}:{Path(__file__).parents[1]}"})
    assert out.stderr.splitlines() == ["summary", "warning: careful"]
