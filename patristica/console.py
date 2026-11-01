"""Console output shared by the pipeline steps (#535).

Every step script calls :func:`setup_logging` instead of its own
``logging.basicConfig``, so the steps of ``scripts.pipeline`` read as one:

- INFO lines are the message alone; they are the few lines a step prints by
  default (what it is about to do when that takes a while, and one summary at
  the end). WARNING and ERROR are prefixed (``warning: …``). Detail is DEBUG
  (per work, per file) or :data:`TRACE` (per round, per request).
- The level comes from ``PATRISTICA_LOG_LEVEL`` (``DEBUG``, ``TRACE``, or a
  number), which ``scripts.pipeline -v`` / ``-vv`` sets for every step; a
  script's own default applies otherwise.
- Log lines are written through ``tqdm.write``, so they never break a
  progress bar. Chatty third-party loggers (httpx, botocore) stay at WARNING
  unless the level is TRACE.

``scripts.normalize`` and ``scripts.align`` are part of their own code hashes
(#130), with the ``patristica`` modules they import: editing them, even a log
call, rebuilds the corpus or re-aligns every group. Their detail lines are
demoted here instead (:data:`DEMOTED`), and ``scripts.pipeline`` runs every
step through this module
(``python -m patristica.console scripts.normalize …``), which configures
logging before the step's own ``basicConfig`` (then a no-op) runs. When one of
those modules changes anyway, move its entries into the code (#535).
"""

from __future__ import annotations

import logging
import os
import runpy
import sys
from collections.abc import Mapping

TRACE = 5
logging.addLevelName(TRACE, "TRACE")

LEVEL_ENV = "PATRISTICA_LOG_LEVEL"

#: Loggers kept at WARNING unless the level is TRACE.
QUIET_LIBRARIES = ("httpx", "httpcore", "botocore", "boto3", "s3transfer", "urllib3")

#: INFO messages (their unformatted ``msg``) shown at DEBUG, per module, for
#: modules whose code is hashed (see the module docstring).
DEMOTED: Mapping[str, frozenset[str]] = {
    "scripts.normalize": frozenset({
        "Normalizing %d raw files…",
        "Wrote %s (%d works)",
        "Recorded %s code hash %s in %s",
    }),
    "scripts.align": frozenset({
        "deleting %s (no longer a version group)",
    }),
    # In align's closure: one line per unpublishable work, from every step
    # that selects works (embed, align, build_index).
    "patristica.corpus": frozenset({
        "skipping %s (licence %s)",
    }),
}

#: The module run as ``__main__`` by :func:`main` (its logger is ``__main__``).
_main_module: str | None = None


def level_from_env(default: int = logging.INFO) -> int:
    """``PATRISTICA_LOG_LEVEL`` as a level number, else *default*."""
    value = os.environ.get(LEVEL_ENV, "").strip()
    if not value:
        return default
    if value.isdigit():
        return int(value)
    level = logging.getLevelName(value.upper())
    if not isinstance(level, int):
        raise ValueError(f"{LEVEL_ENV}={value!r} is not a log level")
    return level


class ConsoleFormatter(logging.Formatter):
    """INFO: the message; WARNING and up: ``warning: …``; detail: ``debug name: …``."""

    def format(self, record: logging.LogRecord) -> str:
        message = record.getMessage()
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)
        if record.levelno == logging.INFO:
            return message
        level = record.levelname.lower()
        if record.levelno >= logging.WARNING:
            return f"{level}: {message}"
        return f"{level} {_logger_name(record)}: {message}"


def _logger_name(record: logging.LogRecord) -> str:
    return _main_module if record.name == "__main__" and _main_module else record.name


class Demote(logging.Filter):
    """Show the :data:`DEMOTED` INFO messages at DEBUG."""

    def __init__(self, demoted: Mapping[str, frozenset[str]] = DEMOTED) -> None:
        super().__init__()
        self.demoted = demoted

    def filter(self, record: logging.LogRecord) -> bool:
        if (record.levelno == logging.INFO
                and record.msg in self.demoted.get(_logger_name(record), ())):
            record.levelno, record.levelname = logging.DEBUG, "DEBUG"
            return logging.getLogger().getEffectiveLevel() <= logging.DEBUG
        return True


class TqdmHandler(logging.StreamHandler):
    """Writes through ``tqdm.write``, which clears and redraws open bars."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            from tqdm import tqdm

            tqdm.write(self.format(record), file=self.stream)
        except Exception:
            self.handleError(record)


def setup_logging(default: int = logging.INFO) -> int:
    """Configure the root logger for a step's console output; the level used.

    Idempotent: a second call (a step run through :func:`main`) only sets the
    level again, from the environment or the step's own *default*.
    """
    level = level_from_env(default)
    root = logging.getLogger()
    if not any(isinstance(h, TqdmHandler) for h in root.handlers):
        for h in list(root.handlers):
            root.removeHandler(h)
        handler = TqdmHandler(sys.stderr)
        handler.setFormatter(ConsoleFormatter())
        handler.addFilter(Demote())
        root.addHandler(handler)
    root.setLevel(level)
    for name in QUIET_LIBRARIES:
        logging.getLogger(name).setLevel(logging.NOTSET if level <= TRACE else logging.WARNING)
    return level


def main(argv: list[str] | None = None) -> None:
    """``python -m patristica.console MODULE [ARGS…]``: run MODULE as ``python
    -m MODULE ARGS…`` would, with logging configured first."""
    global _main_module
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        sys.exit("usage: python -m patristica.console MODULE [ARGS…]")
    module, *args = argv
    _main_module = module
    setup_logging()
    sys.argv = [module, *args]
    runpy.run_module(module, run_name="__main__", alter_sys=True)


if __name__ == "__main__":
    # Run the imported module's main, not this __main__ copy: the steps import
    # patristica.console, and its handler class and _main_module must be the
    # ones configured here.
    from patristica.console import main as _main

    _main()
