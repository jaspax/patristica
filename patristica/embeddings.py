"""
Corpus embedding vectors, stored in ``data/embeddings/`` (#136).

The store mirrors ``data/normalized/``: the vectors of the work at
``data/normalized/{path}`` live in ``data/embeddings/{path}`` with the
extension ``.npz``. Only works with at least one vector have a file. The
directory is gitignored; ``scripts.embed`` writes it and
``scripts.build_index`` loads it into Postgres.

Each file is a ``WorkEmbeddings``. Like the translation store
(``patristica.translations``), the model is recorded per row, not in the path:
``runs`` lists the embedding runs (model, dims, input type, date, script) and
each row points to its run. A row also records the hash of the exact text it
embeds (``sha``, ``translations.text_sha``), so it is used only while that
text is unchanged. A chunk has up to one row per *kind*: ``KIND_TEXT`` embeds
its own text, ``KIND_TRANSLATION`` its English translation (Syriac, Coptic,
Armenian and Ge'ez; #84).

On disk a shard is an uncompressed ``.npz`` (float16 vectors barely
compress) with the arrays ``meta`` (JSON: work id, source path, runs),
``chunk_id``, ``kind`` (uint8), ``sha``, ``run`` (uint16 index into the
runs) and ``vec`` (float16, rows × dims). It is read with
``allow_pickle=False``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    import numpy as np

DEFAULT_DIR = Path("data/embeddings")
KIND_TEXT = 0
KIND_TRANSLATION = 1


class EmbeddingRun(BaseModel):
    """One embedding run: the model and settings that produced a set of rows."""

    model: str  # e.g. "voyage/voyage-4-large"
    dims: int
    input_type: str  # "document"
    date: str  # YYYY-MM-DD
    script: str  # module that produced the run

    @property
    def key(self) -> str:
        return f"{self.model}/{self.dims}/{self.input_type}/{self.date}"

    def same_space(self, other: EmbeddingRun) -> bool:
        """True when vectors of both runs are comparable (same model, dims, input type)."""
        return (self.model, self.dims, self.input_type) == (
            other.model, other.dims, other.input_type)


@dataclass
class Row:
    chunk_id: str
    kind: int
    sha: str  # text_sha of the embedded text
    run: str  # key into WorkEmbeddings.runs


@dataclass
class WorkEmbeddings:
    work_id: str
    source_path: str  # the work's path under data/normalized/
    runs: dict[str, EmbeddingRun] = field(default_factory=dict)
    rows: list[Row] = field(default_factory=list)
    vecs: np.ndarray | None = None  # float16, len(rows) × dims

    def by_key(self) -> dict[tuple[str, int], int]:
        """(chunk_id, kind) → row index."""
        return {(r.chunk_id, r.kind): i for i, r in enumerate(self.rows)}

    def same_content(self, other: WorkEmbeddings) -> bool:
        import numpy as np

        if (self.work_id, self.source_path, self.rows) != (
                other.work_id, other.source_path, other.rows):
            return False
        if {k: r.model_dump() for k, r in self.runs.items()} != {
                k: r.model_dump() for k, r in other.runs.items()}:
            return False
        if self.vecs is None or other.vecs is None:
            return self.vecs is None and other.vecs is None
        return self.vecs.shape == other.vecs.shape and bool(np.array_equal(self.vecs, other.vecs))


def shard_path(store_dir: Path, source_path: str) -> Path:
    return store_dir / Path(source_path).with_suffix(".npz")


def load(store_dir: Path, source_path: str) -> WorkEmbeddings | None:
    path = shard_path(store_dir, source_path)
    if not path.exists():
        return None
    return read(path)


def read(path: Path) -> WorkEmbeddings:
    import numpy as np

    with np.load(path, allow_pickle=False) as z:
        meta = json.loads(str(z["meta"]))
        runs = [EmbeddingRun(**r) for r in meta["runs"]]
        keys = [r.key for r in runs]
        rows = [Row(str(c), int(k), str(s), keys[int(i)])
                for c, k, s, i in zip(z["chunk_id"], z["kind"], z["sha"], z["run"])]
        vecs = z["vec"].astype(np.float16, copy=False)
    return WorkEmbeddings(meta["work_id"], meta["source_path"],
                          {r.key: r for r in runs}, rows, vecs)


def save(store_dir: Path, work: WorkEmbeddings, previous: WorkEmbeddings | None = None) -> bool:
    """Write *work* (deleting the file when it has no rows); return True if the file changed.

    Runs no row points to are dropped. Nothing is written when the content
    equals *previous* (the shard as loaded) or, without *previous*, the
    shard on disk.
    """
    import numpy as np

    used = sorted({r.run for r in work.rows})
    work.runs = {k: work.runs[k] for k in used}
    path = shard_path(store_dir, work.source_path)
    if not work.rows:
        existed = path.exists()
        path.unlink(missing_ok=True)
        return existed
    if work.vecs is None or len(work.vecs) != len(work.rows):
        raise ValueError(f"{work.work_id}: {len(work.rows)} rows but "
                         f"{0 if work.vecs is None else len(work.vecs)} vectors")
    if previous is None and path.exists():
        previous = read(path)
    if previous is not None and work.same_content(previous):
        return False
    meta = {"work_id": work.work_id, "source_path": work.source_path,
            "runs": [work.runs[k].model_dump() for k in used]}
    index = {k: i for i, k in enumerate(used)}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with tmp.open("wb") as f:
        np.savez(
            f,
            meta=np.array(json.dumps(meta, ensure_ascii=False, sort_keys=True)),
            chunk_id=np.array([r.chunk_id for r in work.rows], dtype=str),
            kind=np.array([r.kind for r in work.rows], dtype=np.uint8),
            sha=np.array([r.sha for r in work.rows], dtype=str),
            run=np.array([index[r.run] for r in work.rows], dtype=np.uint16),
            vec=np.asarray(work.vecs, dtype=np.float16),
        )
    tmp.replace(path)
    return True


def iter_store(store_dir: Path = DEFAULT_DIR) -> Iterator[tuple[Path, WorkEmbeddings]]:
    """Every shard in the store, in path order."""
    for path in sorted(store_dir.rglob("*.npz")):
        yield path, read(path)
