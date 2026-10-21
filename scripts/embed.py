"""
Embed the corpus with Voyage ``voyage-4-large`` (#136).

Reads ``data/normalized/`` (via ``_works.jsonl``) and the translation store
``data/translations/``, and writes ``data/embeddings/``, one shard per work at
the work's normalized path (format: ``patristica.embeddings``). Loading the
vectors into Postgres is a separate step (``scripts.build_index``).

What is embedded (IMPLEMENTATION_PLAN.md §2.3–2.5):

- every unit with at least ``MIN_CHARS`` characters of text, as a document,
  its ``text`` only (no context overlap, as in the eval; #3);
- for Syriac, Coptic, Armenian and Ge'ez units, also their fresh English
  translation (``patristica.translations``), as a second vector (#84). A unit
  with no fresh translation is counted and reported; run ``scripts.translate``.

Vectors are stored at the model's full 1024 dims in float16; the DB keeps 512
(``patristica.embedders.shorten``, #50). Each row records its run (model,
dims, input type, date), so a later re-embed with another model is labelled.

It is resumable and idempotent. A row is reused while the text it embeds is
unchanged and its run used the same model, dims and input type; only the
rest are sent. Texts of many works share requests (``VoyageEmbedder``
batch limits), identical texts are sent once, and each work's shard is
written as soon as all its vectors are in, so an interrupted run loses at
most the requests in flight. Rows of vanished chunks are dropped, unchanged
shards are not rewritten, and a full run (no filters) deletes the shards of
works no longer in the manifest.

Works whose licence is in ``upload_library.EXCLUDED_LICENSES`` (``unknown``)
are kept out of the search index, so they are skipped unless
``--include-unpublishable`` is given (as in ``scripts.translate``).

Usage::

    python -m scripts.embed --dry-run                     # what would be sent, and the cost
    python -m scripts.embed --source gez --workers 4      # pilot
    python -m scripts.embed [--work oshb/] [--limit-works 50]

Needs ``VOYAGE_API_KEY`` (environment or ``.env``) and the ``embed`` extra.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections.abc import Callable, Iterable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from tqdm import tqdm

from patristica import embeddings as emb
from patristica import translations as tr
from patristica.corpus import load_works, select  # noqa: F401  (re-exported)
from patristica.embedders import ApiEmbedder, VoyageEmbedder, cl100k

if TYPE_CHECKING:
    import numpy as np

log = logging.getLogger(__name__)

MODEL = "voyage-4-large"
DIMS = 1024
INPUT_TYPE = "document"
MIN_CHARS = emb.MIN_CHARS
# voyage-4-large list price per million tokens, before any free allowance.
# Only for --dry-run; Voyage counts rare scripts at up to ~2x cl100k, and the
# real count is logged at the end of a run.
PRICE_PER_MTOK = 0.12


@dataclass
class Item:
    chunk_id: str
    kind: int
    sha: str
    text: str


@dataclass
class Job:
    """One work: the rows it should have, and the vectors still missing."""

    work_id: str
    source_path: str
    items: list[Item]
    vecs: list[np.ndarray | None]
    runs: list[emb.EmbeddingRun | None]
    previous: emb.WorkEmbeddings | None
    remaining: int = 0


@dataclass
class Stats:
    works: int = 0
    units: int = 0
    short: int = 0
    untranslated: int = 0
    vectors: int = 0
    reused: int = 0
    to_embed: int = 0
    unique_texts: int = 0
    est_tokens: int = 0
    written: int = 0
    deleted: int = 0
    untranslated_works: dict[str, int] = field(default_factory=dict)


def wanted_items(chunks: list[dict], translations: tr.WorkTranslations | None,
                 stats: Stats, work_id: str) -> list[Item]:
    """The rows a work should have, in chunk order (text before translation)."""
    rows = translations.by_chunk() if translations is not None else {}
    items = []
    for c in chunks:
        stats.units += 1
        text = c["text"]
        if len(text.strip()) < MIN_CHARS:
            stats.short += 1
            continue
        sha = tr.text_sha(text)
        items.append(Item(c["chunk_id"], emb.KIND_TEXT, sha, text))
        if c["language"] in tr.TRANSLATED_LANGUAGES:
            t = rows.get(c["chunk_id"])
            if t is not None and t.source_sha256 == sha and t.text.strip():
                items.append(Item(c["chunk_id"], emb.KIND_TRANSLATION,
                                  tr.text_sha(t.text), t.text))
            else:
                stats.untranslated += 1
                stats.untranslated_works[work_id] = stats.untranslated_works.get(work_id, 0) + 1
    return items


def plan_job(entry: dict, input_dir: Path, store_dir: Path, trans_dir: Path,
             spec: emb.EmbeddingRun, stats: Stats) -> Job:
    """Load a work, its translations and its shard; reuse every vector still valid."""
    work = entry["work"]
    chunks = json.loads((input_dir / entry["path"]).read_text(encoding="utf-8"))
    translations = tr.load(trans_dir, entry["path"])
    items = wanted_items(chunks, translations, stats, work["work_id"])
    previous = emb.load(store_dir, entry["path"])
    job = Job(work["work_id"], entry["path"], items, [None] * len(items),
              [None] * len(items), previous)
    if previous is not None:
        index = previous.by_key()
        for i, item in enumerate(items):
            j = index.get((item.chunk_id, item.kind))
            if j is None:
                continue
            row = previous.rows[j]
            run = previous.runs[row.run]
            if row.sha == item.sha and run.same_space(spec):
                job.vecs[i] = previous.vecs[j]
                job.runs[i] = run
    job.remaining = sum(v is None for v in job.vecs)
    stats.works += 1
    stats.vectors += len(items)
    stats.reused += len(items) - job.remaining
    stats.to_embed += job.remaining
    return job


def finish(job: Job, store_dir: Path, stats: Stats) -> None:
    import numpy as np

    runs = {r.key: r for r in job.runs if r is not None}
    work = emb.WorkEmbeddings(
        job.work_id, job.source_path, runs,
        [emb.Row(it.chunk_id, it.kind, it.sha, r.key) for it, r in zip(job.items, job.runs)],
        np.stack(job.vecs).astype(np.float16) if job.items else None)
    if emb.save(store_dir, work, job.previous):
        if work.rows:
            stats.written += 1
        else:
            stats.deleted += 1


def prune(store_dir: Path, keep: Iterable[str], stats: Stats) -> None:
    """Delete shards of works not in *keep* (normalized paths)."""
    wanted = {emb.shard_path(store_dir, p) for p in keep}
    for path in sorted(store_dir.rglob("*.npz")) if store_dir.exists() else []:
        if path not in wanted:
            log.info("deleting %s (work no longer in scope)", path)
            path.unlink()
            stats.deleted += 1


def run(input_dir: Path, store_dir: Path, trans_dir: Path, *, sources: list[str] = (),
        prefixes: list[str] = (), limit_works: int | None = None, workers: int = 4,
        dry_run: bool = False, include_unpublishable: bool = False,
        make_embedder: Callable[[], ApiEmbedder] = lambda: VoyageEmbedder(MODEL, DIMS),
        ) -> Stats:
    import numpy as np

    stats = Stats()
    works = select(load_works(input_dir), list(sources), list(prefixes), include_unpublishable)
    spec = emb.EmbeddingRun(model=f"voyage/{MODEL}", dims=DIMS, input_type=INPUT_TYPE,
                            date=time.strftime("%Y-%m-%d"), script=__name__)
    embedder = None if dry_run else make_embedder()
    if embedder is not None:
        spec = spec.model_copy(update={"model": embedder.name,
                                       "dims": getattr(embedder, "dims", None) or DIMS})
    batch_size = getattr(embedder, "batch_size", VoyageEmbedder.batch_size)
    max_tokens = getattr(embedder, "max_batch_tokens", None) or VoyageEmbedder.max_batch_tokens
    enc = cl100k()

    waiters: dict[str, list[tuple[Job, int]]] = {}  # text → rows waiting for its vector
    inflight: dict[Future, list[str]] = {}
    seen: set[str] = set()  # dry run: hashes of texts already counted
    batch: list[str] = []
    batch_tokens = 0
    pool = ThreadPoolExecutor(max(1, workers)) if embedder is not None else None

    def handle(fut: Future) -> None:
        texts = inflight.pop(fut)
        vecs = fut.result()  # an ApiError ends the run; finished shards are already saved
        if len(vecs) != len(texts):
            raise RuntimeError(f"asked for {len(texts)} vectors, got {len(vecs)}")
        for text, v in zip(texts, vecs):
            for job, i in waiters.pop(text):
                job.vecs[i] = np.asarray(v, dtype=np.float16)
                job.runs[i] = spec
                job.remaining -= 1
                if job.remaining == 0:
                    finish(job, store_dir, stats)

    def submit() -> None:
        nonlocal batch, batch_tokens
        if not batch:
            return
        while len(inflight) >= 2 * max(1, workers):
            done, _ = wait(inflight, return_when=FIRST_COMPLETED)
            for fut in done:
                handle(fut)
        inflight[pool.submit(embedder.embed_batch, batch, INPUT_TYPE)] = batch
        batch, batch_tokens = [], 0

    embedded_works = 0
    try:
        for entry in tqdm(works, desc="works", unit="work"):
            if limit_works is not None and embedded_works >= limit_works:
                break
            job = plan_job(entry, input_dir, store_dir, trans_dir, spec, stats)
            if job.remaining:
                embedded_works += 1
            if dry_run:
                for item, v in zip(job.items, job.vecs):
                    if v is None and item.sha not in seen:
                        seen.add(item.sha)
                        stats.unique_texts += 1
                        stats.est_tokens += len(enc.encode_ordinary(item.text))
                continue
            if job.remaining == 0:
                finish(job, store_dir, stats)
                continue
            for i, (item, v) in enumerate(zip(job.items, job.vecs)):
                if v is not None:
                    continue
                if item.text in waiters:
                    waiters[item.text].append((job, i))
                    continue
                waiters[item.text] = [(job, i)]
                stats.unique_texts += 1
                n = len(enc.encode_ordinary(item.text))
                stats.est_tokens += n
                if batch and (len(batch) >= batch_size or batch_tokens + n > max_tokens):
                    submit()
                batch.append(item.text)
                batch_tokens += n
        if not dry_run:
            submit()
            while inflight:
                done, _ = wait(inflight, return_when=FIRST_COMPLETED)
                for fut in done:
                    handle(fut)
    finally:
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)

    if not dry_run and not sources and not prefixes and limit_works is None:
        prune(store_dir, [e["path"] for e in works], stats)
    report(stats, embedder, dry_run)
    return stats


def report(stats: Stats, embedder: ApiEmbedder | None, dry_run: bool) -> None:
    log.info("%d works, %d units: %d vectors wanted, %d reused, %d to embed "
             "(%d distinct texts, ~%.1fM cl100k tokens, ~$%.2f at list price)",
             stats.works, stats.units, stats.vectors, stats.reused, stats.to_embed,
             stats.unique_texts, stats.est_tokens / 1e6,
             stats.est_tokens / 1e6 * PRICE_PER_MTOK)
    log.info("skipped: %d units under %d characters; %d rare-language units with no "
             "fresh translation", stats.short, MIN_CHARS, stats.untranslated)
    for work_id, n in sorted(stats.untranslated_works.items(), key=lambda kv: -kv[1])[:10]:
        log.info("  untranslated: %s (%d)", work_id, n)
    if not dry_run:
        log.info("shards written: %d, deleted: %d; Voyage tokens used: %d (~$%.2f)",
                 stats.written, stats.deleted, embedder.tokens_used if embedder else 0,
                 (embedder.tokens_used if embedder else 0) / 1e6 * PRICE_PER_MTOK)


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input-dir", type=Path, default=Path("data/normalized"))
    p.add_argument("--store", type=Path, default=emb.DEFAULT_DIR)
    p.add_argument("--translations", type=Path, default=tr.DEFAULT_DIR)
    p.add_argument("--source", action="append", default=[], metavar="ID",
                   help="only works of this source_id (repeatable)")
    p.add_argument("--work", action="append", default=[], metavar="PREFIX",
                   help="only works whose id starts with PREFIX (repeatable)")
    p.add_argument("--limit-works", type=int, metavar="N",
                   help="pilot: stop after N works that need embedding")
    p.add_argument("--workers", type=int, default=4, help="concurrent requests")
    p.add_argument("--dry-run", action="store_true", help="report the work and cost only")
    p.add_argument("--include-unpublishable", action="store_true",
                   help="also embed works whose licence keeps them out of the index")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    run(args.input_dir, args.store, args.translations, sources=args.source,
        prefixes=args.work, limit_works=args.limit_works, workers=args.workers,
        dry_run=args.dry_run, include_unpublishable=args.include_unpublishable)


if __name__ == "__main__":
    main()
