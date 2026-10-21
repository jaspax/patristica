"""The corpus as the steps after normalize see it: the work manifest and which
works may be published.

Shared by ``scripts.translate``, ``scripts.embed``, ``scripts.align`` and
``scripts.build_index``.  It lives here, not in one of those scripts, so a
step's code (its import closure, ``patristica.fingerprint``, #130) doesn't
include the others.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

#: Licences that keep a work out of everything public: the library upload,
#: translation, embedding and the search DB (see CLAUDE.md "Licensing").
EXCLUDED_LICENSES = frozenset({"unknown"})


def load_works(input_dir: Path) -> list[dict]:
    """Every ``{"path", "work"}`` entry of ``{input_dir}/_works.jsonl``."""
    with (input_dir / "_works.jsonl").open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def select(works: list[dict], sources: list[str], prefixes: list[str],
           include_unpublishable: bool) -> list[dict]:
    """The entries of *works* in the given sources / work-id prefixes (all when
    empty), leaving out unpublishable licences unless *include_unpublishable*."""
    out = []
    for entry in works:
        work = entry["work"]
        if sources and work["source_id"] not in sources:
            continue
        if prefixes and not any(work["work_id"].startswith(p) for p in prefixes):
            continue
        if work["license"] in EXCLUDED_LICENSES and not include_unpublishable:
            log.info("skipping %s (licence %s)", work["work_id"], work["license"])
            continue
        out.append(entry)
    return out
