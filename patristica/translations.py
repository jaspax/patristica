"""
Machine translations of corpus chunks, stored in ``data/translations/`` (#93).

The store mirrors ``data/normalized/``: the translations of the work at
``data/normalized/{path}`` live in ``data/translations/{path}``, where *path*
is the work's ``path`` in ``_works.jsonl``. Only works with translated chunks
have a file.

Each file is a ``WorkTranslations``. Run metadata (model, prompt version,
date, script) is recorded once per run in ``provenance``, and each row points
to its run by key. A row also records the hash of the exact source text it
translates, so it is used only while that text is unchanged (``fresh``).
There is one translation per chunk: re-translating a chunk replaces its row.

``save`` writes rows in normalized chunk order, drops rows whose chunk no
longer exists or has changed, and drops provenance entries nothing points to,
so the output depends only on the content.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

from pydantic import BaseModel

from patristica.editorial import source_text
from patristica.models import Language

DEFAULT_DIR = Path("data/translations")
TARGET_LANGUAGE = "eng"
# Languages no embedder reaches from English (#3), indexed through these
# translations (#84): scripts.translate translates them, scripts.embed embeds
# the translation as a second vector.
TRANSLATED_LANGUAGES: frozenset[str] = frozenset({"syc", "cop", "hye", "gez", "chu", "oge"})


def text_sha(text: str) -> str:
    """First 16 hex digits of the SHA-256 of *text* (UTF-8)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class Provenance(BaseModel):
    """One translation run."""

    model: str
    prompt_version: str
    date: str  # YYYY-MM-DD
    script: str  # module that produced the run

    @property
    def key(self) -> str:
        return f"{self.model}/{self.prompt_version}/{self.date}"


class ChunkTranslation(BaseModel):
    chunk_id: str
    source_sha256: str
    provenance: str  # key into WorkTranslations.provenance
    group_size: int  # chunks of the work translated together in one request
    text: str


class WorkTranslations(BaseModel):
    work_id: str
    source_path: str  # the work's path under data/normalized/
    source_language: Language
    target_language: Language = TARGET_LANGUAGE
    provenance: dict[str, Provenance] = {}
    translations: list[ChunkTranslation] = []

    def by_chunk(self) -> dict[str, ChunkTranslation]:
        """chunk_id → translation; a later row for the same chunk wins."""
        return {t.chunk_id: t for t in self.translations}

    def fresh(self, chunk_id: str, text: str) -> ChunkTranslation | None:
        """The translation of *chunk_id*, if it was made from exactly *text*."""
        t = self.by_chunk().get(chunk_id)
        return t if t is not None and t.source_sha256 == text_sha(text) else None

    def put(self, row: ChunkTranslation, provenance: Provenance) -> None:
        """Add or replace the translation of ``row.chunk_id``.

        The new row is appended; ``by_chunk`` and ``compact`` keep the latest
        row per chunk, so a put costs O(1) however large the work.
        """
        if row.provenance != provenance.key:
            raise ValueError(f"row points to {row.provenance!r}, not {provenance.key!r}")
        self.provenance.setdefault(provenance.key, provenance)
        self.translations.append(row)

    def compact(self, chunks: list[dict]) -> None:
        """Keep only fresh rows, in the order of *chunks*, and the runs they use."""
        rows = self.by_chunk()
        kept = []
        for c in chunks:
            t = rows.get(c["chunk_id"])
            if t is not None and t.source_sha256 == text_sha(source_text(c)):
                kept.append(t)
        self.translations = kept
        used = {t.provenance for t in kept}
        self.provenance = {k: self.provenance[k] for k in sorted(used)}


def translation_path(store_dir: Path, source_path: str) -> Path:
    return store_dir / source_path


def load(store_dir: Path, source_path: str) -> WorkTranslations | None:
    path = translation_path(store_dir, source_path)
    if not path.exists():
        return None
    return WorkTranslations.model_validate_json(path.read_text(encoding="utf-8"))


def save(store_dir: Path, work: WorkTranslations, chunks: list[dict]) -> Path | None:
    """Compact *work* against *chunks* and write it; delete the file if nothing is left.

    Returns the path written, or None when the work has no translations.
    """
    work.compact(chunks)
    path = translation_path(store_dir, work.source_path)
    if not work.translations:
        path.unlink(missing_ok=True)
        return None
    content = json.dumps(work.model_dump(), ensure_ascii=False, indent=2) + "\n"
    if not path.exists() or path.read_text(encoding="utf-8") != content:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(path)
    return path


def iter_store(store_dir: Path = DEFAULT_DIR) -> Iterator[WorkTranslations]:
    """Every work file in the store, in path order."""
    for path in sorted(store_dir.rglob("*.json")):
        yield WorkTranslations.model_validate_json(path.read_text(encoding="utf-8"))


def fresh_translations(chunks: list[dict], store_dir: Path = DEFAULT_DIR,
                       model: str | None = None) -> dict[str, str]:
    """chunk_id → English text for each of *chunks* with a fresh translation.

    With *model*, only translations made by that model are returned.
    """
    wanted = {c["chunk_id"]: text_sha(source_text(c)) for c in chunks}
    out = {}
    for work in iter_store(store_dir):
        for t in work.translations:
            if wanted.get(t.chunk_id) != t.source_sha256:
                continue
            if model is None or work.provenance[t.provenance].model == model:
                out[t.chunk_id] = t.text
    return out
