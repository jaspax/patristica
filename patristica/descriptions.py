"""Author bios and work descriptions (#795).

Short reader-facing prose (target 50–100 words) for every author and every
work, with a link to the English Wikipedia article where one exists. They are
tracked in ``data/descriptions/`` (plain git), one JSON object per line:

- ``authors.jsonl``: ``{"id": author_id, "text", "wikipedia", "model", "sources"}``
- ``works.jsonl``:   ``{"id": work_id, "text", "wikipedia", "model", "sources"}``

``text`` is the bio or description, ``wikipedia`` the article URL or null,
``model`` what wrote the text (``scripts.describe``; ``lorem-ipsum`` for
layout placeholders) and ``sources`` the URLs it was written from. Lines are
sorted by id, so a re-run that changes nothing leaves the files byte-identical.

The members of a version group (#178) share one description: the generator
writes it once per group and copies it to every member, so a group's works
never disagree. ``scripts.export_library`` publishes them as small
``about/…`` files the pages fetch on their own (they stay out of
``index.json`` and the work files, which every visitor downloads).
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_DIR = Path("data/descriptions")
AUTHORS_FILE = "authors.jsonl"
WORKS_FILE = "works.jsonl"

#: ``model`` of layout placeholders: never published as if real.
PLACEHOLDER_MODEL = "lorem-ipsum"

WIKIPEDIA_PREFIX = "https://en.wikipedia.org/wiki/"


class DescriptionError(ValueError):
    """Raised on a malformed description file or entry."""


@dataclass(frozen=True)
class Description:
    id: str
    text: str
    wikipedia: str | None = None
    model: str = ""
    sources: list[str] = field(default_factory=list)

    def check(self) -> None:
        if not self.id:
            raise DescriptionError("description without an id")
        if not self.text.strip():
            raise DescriptionError(f"{self.id}: empty text")
        if self.wikipedia is not None and not self.wikipedia.startswith(WIKIPEDIA_PREFIX):
            raise DescriptionError(f"{self.id}: not an English Wikipedia URL: {self.wikipedia}")

    def about(self) -> dict[str, object]:
        """The library's ``about`` file: what the page shows."""
        return {"text": self.text, "wikipedia": self.wikipedia}


def load(path: Path) -> dict[str, Description]:
    """id → description from a ``.jsonl`` file; ``{}`` when it doesn't exist."""
    if not path.exists():
        return {}
    out: dict[str, Description] = {}
    with path.open(encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                d = Description(**json.loads(line))
            except (json.JSONDecodeError, TypeError) as exc:
                raise DescriptionError(f"{path}:{lineno}: {exc}") from exc
            d.check()
            if d.id in out:
                raise DescriptionError(f"{path}:{lineno}: duplicate id {d.id}")
            out[d.id] = d
    return out


def save(path: Path, entries: Iterable[Description]) -> None:
    """Write *entries* sorted by id, one JSON object per line."""
    rows = sorted(entries, key=lambda d: d.id)
    for d in rows:
        d.check()
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(asdict(d), ensure_ascii=False) + "\n" for d in rows)
    if not path.exists() or path.read_text(encoding="utf-8") != text:
        path.write_text(text, encoding="utf-8")


def load_authors(root: Path = DEFAULT_DIR) -> dict[str, Description]:
    return load(root / AUTHORS_FILE)


def load_works(root: Path = DEFAULT_DIR) -> dict[str, Description]:
    return load(root / WORKS_FILE)
