"""
Translate the rare-language chunks of the corpus into English (#93).

Syriac, Coptic, Armenian, Ge'ez (#84), Church Slavonic (#336) and Old Georgian (#529)
are indexed for search through English translations by GPT-6.1 Sol (see ``docs/embedding-eval.md``).
This step reads ``data/normalized/`` and writes ``data/translations/``, one
file per work at the work's normalized path (format: ``patristica.translations``).

It is resumable and idempotent. A chunk is skipped while its stored
translation was made from exactly its current text, without its editorial
material (``patristica.editorial.source_text``, #236), which is all that is
sent. A chunk with no fresh translation reuses any stored translation of identical text in the same
language (renamed works, repeated refrains). Only the rest are sent to the
model, as consecutive chunks of one work per request (up to
``BULK_MAX_CHARS`` / ``BULK_MAX_ITEMS``), so it sees context and the
per-request overhead is shared. Works are written as their requests finish,
and on exit, so an interrupted run loses at most the requests in flight.

Works whose licence is in ``upload_library.EXCLUDED_LICENSES`` (``unknown``)
are kept out of the search index, so they are skipped unless
``--include-unpublishable`` is given.

Usage::

    python -m scripts.translate --dry-run            # what would be sent, and the cost
    python -m scripts.translate --max-requests 20    # pilot
    python -m scripts.translate [--langs syc cop] [--work hudra/] [--max-cost 50]
    python -m scripts.translate --model opus         # retry what Sol's filter blocked
    python -m scripts.translate --model local-opus --workers 4  # on the subscription
    python -m scripts.translate --usage              # the subscription's usage now

``--model`` picks the translator (default ``sol``). ``opus`` (Claude Opus 5.5,
which scored as well as Sol in the #84 quality eval) is for the few requests
Sol's content filter blocks; it needs ``ANTHROPIC_API_KEY``. ``local-opus`` is
the same model through a local ``claude -p`` on the Claude subscription login
(#417): it costs nothing per request but counts against the subscription's
5-hour and 7-day usage windows, which the run logs alongside its progress.
The run never stops on usage; watching it is the controlling agent's job
(``docs/translation-backends.md``). Each row's provenance records the model
that actually answered.

Needs ``OPENAI_API_KEY`` (environment or ``.env``) for Sol.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel

from patristica import console
from patristica import translations as tr
from patristica.corpus import EXCLUDED_LICENSES
from patristica.editorial import source_text
from scripts.embed_eval.translate import (
    LANGUAGE_NAMES,
    MODELS,
    PROMPT_NAMES,
    TRANSLATOR_SYSTEM,
    Clients,
    cost,
    limits_report,
)

log = logging.getLogger(__name__)

DEFAULT_MODEL = "sol"
TRANSLATORS = ("sol", "opus", "local-opus")  # Sol and Opus ≈4.4–4.5/5 fidelity in #84
# Bump when BULK_SYSTEM or the grouping changes, so stored translations say
# which prompt produced them.
BULK_PROMPT_VERSION = "bulk-2026-10-12"
BULK_MAX_CHARS = 3000
BULK_MAX_ITEMS = 25
# Measured with Sol on the #84 run (11,239 chunks, grouped): used only for
# --dry-run, scaled by the model's output price for other translators.
COST_PER_CHUNK = 0.0014

BULK_SYSTEM = TRANSLATOR_SYSTEM.split("- Rate your confidence")[0] + """\
- The passages are numbered consecutive pieces of one work. Translate each one \
separately and return one item per number, in order; use the neighbouring \
passages only as context."""


class BulkItem(BaseModel):
    n: int
    translation: str


class BulkTranslation(BaseModel):
    items: list[BulkItem]


@dataclass
class WorkJob:
    """One work's chunks, stored translations and outstanding requests."""

    work_id: str
    source_path: str
    language: str
    chunks: list[dict]
    store: tr.WorkTranslations
    groups: list[list[dict]] = field(default_factory=list)
    pending: int = 0
    dirty: bool = False


def load_works(input_dir: Path) -> list[dict]:
    with (input_dir / "_works.jsonl").open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def make_groups(chunks: list[dict]) -> list[list[dict]]:
    """Split *chunks* (one work, in order) into requests of one language each."""
    groups: list[list[dict]] = []
    cur: list[dict] = []
    size = 0
    for c in chunks:
        if cur and (size + len(source_text(c)) > BULK_MAX_CHARS or len(cur) >= BULK_MAX_ITEMS
                    or c["language"] != cur[0]["language"]):
            groups.append(cur)
            cur, size = [], 0
        cur.append(c)
        size += len(source_text(c))
    if cur:
        groups.append(cur)
    return groups


def plan(input_dir: Path, store_dir: Path, langs: list[str], work_prefixes: list[str],
         include_unpublishable: bool) -> tuple[list[WorkJob], int]:
    """Load every in-scope work; fill in reusable translations; group the rest.

    Returns the jobs and the number of chunks filled by reusing identical text.
    """
    by_text: dict[tuple[str, str], tuple[tr.ChunkTranslation, tr.Provenance]] = {}
    for stored in tr.iter_store(store_dir):
        for t in stored.translations:
            by_text[(stored.source_language, t.source_sha256)] = (
                t, stored.provenance[t.provenance])

    jobs = []
    reused = 0
    for entry in load_works(input_dir):
        work = entry["work"]
        if work["language"] not in langs:
            continue
        if work_prefixes and not any(work["work_id"].startswith(p) for p in work_prefixes):
            continue
        if work["license"] in EXCLUDED_LICENSES and not include_unpublishable:
            log.debug("skipping %s (licence %s)", work["work_id"], work["license"])
            continue
        chunks = json.loads((input_dir / entry["path"]).read_text(encoding="utf-8"))
        store = tr.load(store_dir, entry["path"]) or tr.WorkTranslations(
            work_id=work["work_id"], source_path=entry["path"],
            source_language=work["language"])
        job = WorkJob(work["work_id"], entry["path"], work["language"], chunks, store)
        rows = store.by_chunk()
        todo = []
        for c in chunks:
            text = source_text(c)  # without editorial material (#236)
            if c["language"] != work["language"] or not text.strip():
                continue
            sha = tr.text_sha(text)
            row = rows.get(c["chunk_id"])
            if row is not None and row.source_sha256 == sha:
                continue
            hit = by_text.get((c["language"], sha))
            if hit is not None:
                t, prov = hit
                store.put(t.model_copy(update={"chunk_id": c["chunk_id"]}), prov)
                job.dirty = True
                reused += 1
                continue
            todo.append(c)
        job.groups = make_groups(todo)
        if job.dirty or job.groups or has_stale_rows(store, chunks):
            jobs.append(job)
    return jobs, reused


def has_stale_rows(store: tr.WorkTranslations, chunks: list[dict]) -> bool:
    """True when the stored file has rows for changed or vanished chunks."""
    if not store.translations:
        return False
    current = {c["chunk_id"]: tr.text_sha(source_text(c)) for c in chunks}
    return any(current.get(t.chunk_id) != t.source_sha256 for t in store.translations)


def run(input_dir: Path, store_dir: Path, langs: list[str], work_prefixes: list[str],
        workers: int, max_requests: int | None, max_cost: float | None,
        dry_run: bool, include_unpublishable: bool, model: str = DEFAULT_MODEL) -> None:
    jobs, reused = plan(input_dir, store_dir, langs, work_prefixes, include_unpublishable)
    requests = [(job, g) for job in jobs for g in job.groups]
    if max_requests is not None:
        requests = random.Random(0).sample(requests, min(max_requests, len(requests)))
    by_lang: dict[str, int] = defaultdict(int)
    for job, g in requests:
        by_lang[job.language] += len(g)
    n_chunks = sum(by_lang.values())
    if not requests:
        log.info("nothing to translate%s", f" ({reused:,} reused from identical text)"
                 if reused else "")
    else:
        log.info("%s chunks to translate in %s requests (%s); %s reused from identical text; "
                 "estimated $%.2f", f"{n_chunks:,}", f"{len(requests):,}",
                 ", ".join(f"{k} {v:,}" for k, v in sorted(by_lang.items())),
                 f"{reused:,}", n_chunks * COST_PER_CHUNK * MODELS[model].price_out
                 / MODELS[DEFAULT_MODEL].price_out)
    if dry_run:
        return

    for job, _ in requests:
        job.pending += 1
    lock = threading.Lock()
    spent: list[dict] = []
    stop = threading.Event()
    clients = Clients() if requests else None
    today = time.strftime("%Y-%m-%d")

    def write(job: WorkJob) -> None:
        tr.save(store_dir, job.store, job.chunks)
        job.dirty = False

    def one(item: tuple[WorkJob, list[dict]]) -> None:
        job, group = item
        try:
            if stop.is_set():
                return
            lang = group[0]["language"]
            user = "\n\n".join(f"[{i}]\n{source_text(c)}" for i, c in enumerate(group, start=1))
            out, usage = clients.call(model, BULK_SYSTEM.format(language=PROMPT_NAMES[lang]),
                                      user, BulkTranslation)
            got = {it.n: it.translation for it in out.items}
            provenance = tr.Provenance(
                model=usage.get("served_by") or MODELS[model].model_id,
                prompt_version=BULK_PROMPT_VERSION, date=today, script=__name__)
            with lock:
                spent.append(usage)
                for i, c in enumerate(group, start=1):
                    if i not in got:
                        log.warning("no translation for %s", c["chunk_id"])
                        continue
                    job.store.put(tr.ChunkTranslation(
                        chunk_id=c["chunk_id"], source_sha256=tr.text_sha(source_text(c)),
                        provenance=provenance.key, group_size=len(group), text=got[i],
                    ), provenance)
                    job.dirty = True
                if max_cost is not None and cost(spent) >= max_cost and not stop.is_set():
                    log.warning("reached --max-cost $%.2f; finishing requests in flight",
                                max_cost)
                    stop.set()
        except Exception as e:
            log.error("request starting %s failed: %s", group[0]["chunk_id"], e)
        finally:
            with lock:
                job.pending -= 1
                if job.pending == 0 and job.dirty:
                    write(job)

    from tqdm import tqdm

    done = 0
    try:
        with ThreadPoolExecutor(workers) as pool, \
                tqdm(total=len(requests), desc="translate", unit="req",
                     disable=not requests) as bar:
            for _ in pool.map(one, requests):
                done += 1
                bar.update()
                if done % 10 == 0:
                    bar.set_postfix_str(f"${cost(spent):.2f}")
                if done % 50 == 0:
                    # On the subscription the usage windows are what to watch
                    # (docs/translation-backends.md): log them. Otherwise the
                    # bar shows the progress, and the log gets it at DEBUG.
                    suffix = _limits_suffix(spent)
                    log.log(logging.INFO if suffix else logging.DEBUG,
                            "%d/%d requests, $%.2f so far%s", done, len(requests),
                            cost(spent), suffix)
    finally:
        with lock:
            for job in jobs:
                if job.dirty or not job.groups:
                    write(job)
    if requests:
        log.info("%s requests, $%.2f%s", f"{len(spent):,}", cost(spent), _limits_suffix(spent))


def _limits_suffix(spent: list[dict]) -> str:
    """The subscription's usage windows for a progress line (local-opus only)."""
    report = limits_report(spent)
    return f"; subscription usage {report}" if report else ""


def probe_usage() -> str:
    """One tiny local Claude request, for the subscription's current usage."""

    class Ok(BaseModel):
        ok: bool

    _, usage = Clients().call("local-haiku", "Answer with ok: true.", "ok?", Ok)
    return limits_report([usage]) or "the CLI reported no usage windows"


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input-dir", type=Path, default=Path("data/normalized"))
    p.add_argument("--store", type=Path, default=tr.DEFAULT_DIR)
    p.add_argument("--langs", nargs="+", default=list(LANGUAGE_NAMES),
                   choices=list(PROMPT_NAMES),
                   help="a language not yet enrolled (EVAL_LANGUAGES) needs another --store")
    p.add_argument("--work", action="append", default=[], metavar="PREFIX",
                   help="only works whose id starts with PREFIX (repeatable)")
    p.add_argument("--model", choices=TRANSLATORS, default=DEFAULT_MODEL,
                   help="translator (default %(default)s)")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--max-requests", type=int, help="pilot: a random sample of N requests")
    p.add_argument("--max-cost", type=float, help="stop sending requests after $N")
    p.add_argument("--dry-run", action="store_true", help="report the work and cost only")
    p.add_argument("--usage", action="store_true",
                   help="print the Claude subscription's usage windows (one tiny local request)")
    p.add_argument("--include-unpublishable", action="store_true",
                   help="also translate works whose licence keeps them out of the index")
    args = p.parse_args()
    if (unenrolled := set(args.langs) - set(LANGUAGE_NAMES)) and \
            args.store.resolve() == tr.DEFAULT_DIR.resolve():
        p.error(f"{', '.join(sorted(unenrolled))} not enrolled in TRANSLATED_LANGUAGES: "
                "translate it into an eval store (--store), not data/translations")
    console.setup_logging()
    if args.usage:
        log.info("subscription usage %s", probe_usage())
        return
    run(args.input_dir, args.store, args.langs, args.work, args.workers, args.max_requests,
        args.max_cost, args.dry_run, args.include_unpublishable, args.model)


if __name__ == "__main__":
    main()
