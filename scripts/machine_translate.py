"""
Machine-translate whole works into English for readers (#422, #423).

Unlike ``scripts.translate`` (chunk-by-chunk English for the search vectors of
the rare languages), this translates a work's **paragraphs, a chapter or the
whole work per request**, for a fluent text a reader can follow. The result is
a new work of the derived source ``mt-eng``, written as a raw file:
``data/raw/mt-eng/{the original's normalized path}``, tracked in plain git (not
git-lfs), so a PR shows the translation itself. ``scripts.pipeline`` then
normalizes it, cuts its derived verses on the original (``anchored_sources.csv``,
#304), aligns it, and indexes and exports it as a machine translation: it gets
no search vectors and doesn't match keyword search. Which works qualify is
``patristica.machine_translation``; the whole design is
``docs/machine-translation.md``.

The units are the original's paragraphs: its normalized chunks with derived
verses (``{ref}.sN``) joined back under their paragraph's ref, so the MT's
units have the original's refs. A work the original's ingestor delivered as
verses (``scripts.normalize.is_standard``) keeps them as verses. Editorial
material (#236) isn't translated, except a unit that is editorial as a whole
(an added title or heading): it is translated for readers and marked as
editorial again in the MT, so it is never embedded. Each unit records the hash
of the source text it was made from (``source_sha``), which ``stale`` checks.

Requests group consecutive paragraphs of a section (its ref without the last
segment), merging small sections, up to ``DOC_MAX_CHARS`` of source; a longer
section is split at paragraph boundaries, each part seeing the paragraphs
before it as context. Each response must return every paragraph, none empty,
at a plausible length; a request that fails is retried once. A work is all or
nothing: finished requests are kept in ``--partial-dir`` (gitignored scratch),
so an interrupted work resumes where it stopped, and the raw file is written
only when every request is done.

Usage::

    python -m scripts.machine_translate candidates [--lang grc lat] [--json]  # with their versions
    python -m scripts.machine_translate review-versions [--json]  # divergent enough to translate?
    python -m scripts.machine_translate translate WORK_ID [--model local-opus] [--workers 3]
    python -m scripts.machine_translate stale            # MT whose original's text changed
    python -m scripts.machine_translate translate WORK_ID --update   # re-translate only that

The default translator is ``local-opus`` (Claude Opus through ``claude -p`` on
the subscription, ``docs/translation-backends.md``): its usage windows are
logged, never enforced. ``--model opus`` / ``sol`` use the APIs and cost money.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from patristica import machine_translation as mt
from patristica.corpus import load_works
from patristica.editorial import source_text, spans_of
from patristica.sources import source_label
from patristica.translations import text_sha
from patristica.versify import is_derived_ref
from scripts.embed_eval.translate import MODELS, Clients, cost, limits_report
from scripts.translate import BulkTranslation

log = logging.getLogger(__name__)

MT_SOURCE = "mt-eng"
DEFAULT_MODEL = "local-opus"
TRANSLATORS = ("local-opus", "opus", "sol")
# Bump when DOCUMENT_SYSTEM or the request layout changes: it is recorded with each work.
PROMPT_VERSION = "document-2026-10-29"
# Source characters per request: about a chapter. A work under it goes in one request.
DOC_MAX_CHARS = 20000
# Paragraphs before a request (of the same section) shown as context.
CONTEXT_PARAGRAPHS = 2
CONTEXT_CHARS = 3000
# English characters per source character, for a whole request: outside this
# band a response is taken as truncated, summarised or padded.
RATIO_BAND: dict[str, tuple[float, float]] = {
    "grc": (0.6, 3.0), "lat": (0.6, 2.8), "hbo": (0.8, 5.0), "syc": (0.7, 5.0),
    "cop": (0.5, 3.5), "hye": (0.6, 4.0), "gez": (0.6, 4.5), "chu": (0.6, 3.5),
    "got": (0.6, 3.0),
}
DEFAULT_BAND = (0.5, 5.0)
# A source paragraph this long whose English is under MIN_ITEM_RATIO of it is an omission.
ITEM_CHECK_CHARS = 300
MIN_ITEM_RATIO = 0.25

#: Prompt names of the languages a work may be translated from. Separate from
#: ``scripts.embed_eval.translate.LANGUAGE_NAMES``, which enrols search translation.
DOCUMENT_LANGUAGES: dict[str, str] = {
    "grc": "Ancient and Byzantine Greek",
    "lat": "Latin",
    "hbo": "Biblical Hebrew",
    "syc": "Classical Syriac",
    "cop": "Coptic",
    "hye": "Classical Armenian (Grabar)",
    "gez": "Ge'ez (Classical Ethiopic)",
    "chu": "Old Church Slavonic",
    "got": "Gothic",
}

DOCUMENT_SYSTEM = """\
You translate early Christian and Jewish texts from {language} into English for \
readers of an online library. The English is published as a machine translation \
beside the original, so it must be faithful and complete, and read as fluent, \
plain modern English prose (or verse, where the original is verse).

- You are given numbered paragraphs of one work, in order, sometimes after a few \
earlier paragraphs marked as context. Translate every numbered paragraph and only \
those: return one item per number, in order. Never merge, split, skip or reorder \
paragraphs, but let the English flow across them as one text.
- Translate everything in a paragraph: no summary, no commentary, no notes, \
nothing added. Translate titles, headings and rubrics too.
- Use conventional English forms of proper names, and the usual English names of \
biblical books. Render a scriptural quotation in your own translation of this text.
- Keep the author's register, but prefer clarity to word-for-word literalism.
- Where the text is damaged or garbled, or a word is unknown to you, translate what \
you can and mark the gap with [?]. Do not guess silently."""


class MachineTranslateError(RuntimeError):
    """A work that can't be translated as asked."""


# --- the original's units -------------------------------------------------------


@dataclass
class Unit:
    """One paragraph (or verse) of the original."""

    ref: str
    text: str  # what is sent: the source text, or the whole text of an editorial unit
    sha: str  # text_sha of the source text of its chunks (what ``stale`` compares)
    editorial: str | None = None  # kind, when the unit is editorial as a whole


def _parent_ref(ref: str) -> str:
    return ref.rsplit(".", 1)[0] if is_derived_ref(ref) else ref


def units_of(chunks: list[dict]) -> list[Unit]:
    """The original's paragraphs: its chunks, derived verses joined under their paragraph."""
    grouped: list[tuple[str, list[dict]]] = []
    for c in chunks:
        ref = _parent_ref(c["canonical_ref"])
        if grouped and grouped[-1][0] == ref:
            grouped[-1][1].append(c)
        else:
            grouped.append((ref, [c]))
    out = []
    for ref, parts in grouped:
        source = " ".join(t for t in (source_text(c).strip() for c in parts) if t)
        full = " ".join(c["text"].strip() for c in parts)
        kinds = {s[2] for c in parts for s in spans_of(c)}
        whole = not source and full and len(kinds) == 1
        if not source and not whole:
            continue  # nothing to translate (blank, or editorial of mixed kinds)
        out.append(Unit(ref, full if whole else source, text_sha(source or full),
                        next(iter(kinds)) if whole else None))
    return out


def section_of(ref: str) -> str:
    return ref.rsplit(".", 1)[0] if "." in ref else ""


@dataclass
class Request:
    units: list[Unit]
    context: list[Unit] = field(default_factory=list)

    @property
    def key(self) -> str:
        """What the request sends: a partial result is reused only while it matches."""
        return text_sha(PROMPT_VERSION + "\n" + "\n".join(f"{u.ref}\t{u.sha}" for u in self.units))


def make_requests(units: list[Unit], max_chars: int | None = None) -> list[Request]:
    """Consecutive units in requests of at most *max_chars* (``DOC_MAX_CHARS``),
    cut at section ends where possible."""
    max_chars = DOC_MAX_CHARS if max_chars is None else max_chars
    sections: list[list[Unit]] = []
    for u in units:
        if sections and section_of(sections[-1][-1].ref) == section_of(u.ref):
            sections[-1].append(u)
        else:
            sections.append([u])
    requests: list[Request] = []
    cur: list[Unit] = []
    size = 0
    for sec in sections:
        sec_size = sum(len(u.text) for u in sec)
        if cur and size + sec_size > max_chars:
            requests.append(Request(cur))
            cur, size = [], 0
        if sec_size <= max_chars:
            cur.extend(sec)
            size += sec_size
            continue
        # A long section: parts of it, each with the paragraphs before as context.
        part: list[Unit] = []
        part_size = 0
        for i, u in enumerate(sec):
            if part and part_size + len(u.text) > max_chars:
                requests.append(_with_context(part, sec, i - len(part)))
                part, part_size = [], 0
            part.append(u)
            part_size += len(u.text)
        cur, size = part, part_size
        if cur and len(cur) < len(sec):
            requests.append(_with_context(cur, sec, len(sec) - len(cur)))
            cur, size = [], 0
    if cur:
        requests.append(Request(cur))
    return requests


def _with_context(part: list[Unit], section: list[Unit], start: int) -> Request:
    context: list[Unit] = []
    chars = 0
    for u in reversed(section[max(0, start - CONTEXT_PARAGRAPHS):start]):
        if chars + len(u.text) > CONTEXT_CHARS and context:
            break
        context.insert(0, u)
        chars += len(u.text)
    return Request(part, context)


def request_text(req: Request) -> str:
    parts = []
    if req.context:
        parts.append("Context, already translated (do not translate):\n\n"
                     + "\n\n".join(u.text for u in req.context))
        parts.append("Translate:")
    parts.append("\n\n".join(f"[{i}]\n{u.text}" for i, u in enumerate(req.units, start=1)))
    return "\n\n".join(parts)


def check_response(req: Request, got: dict[int, str], language: str) -> str | None:
    """Why the response to *req* is unusable, or None when it is fine."""
    want = set(range(1, len(req.units) + 1))
    if set(got) != want:
        missing, extra = sorted(want - set(got)), sorted(set(got) - want)
        return f"items missing {missing[:5]} extra {extra[:5]}"
    empty = [i for i in want if not got[i].strip()]
    if empty:
        return f"empty items {empty[:5]}"
    src = sum(len(u.text) for u in req.units)
    eng = sum(len(t) for t in got.values())
    lo, hi = RATIO_BAND.get(language, DEFAULT_BAND)
    if src >= 200 and not lo <= eng / src <= hi:
        return f"length ratio {eng / src:.2f} outside {lo}–{hi}"
    short = [i for i, u in enumerate(req.units, start=1)
             if len(u.text) >= ITEM_CHECK_CHARS and len(got[i]) < MIN_ITEM_RATIO * len(u.text)]
    if short:
        return f"items much shorter than their source {short[:5]}"
    return None


# --- the original, and its MT ---------------------------------------------------


def find_entry(input_dir: Path, work_id: str) -> dict:
    for entry in load_works(input_dir):
        if entry["work"]["work_id"] == work_id:
            return entry
    raise MachineTranslateError(f"{work_id}: not in {input_dir}/_works.jsonl")


def original_is_standard(entry: dict, raw_dir: Path) -> bool:
    """Whether the original keeps its own verses (``scripts.normalize.is_standard``),
    from its raw file; without one, Scripture only."""
    from scripts.normalize import is_standard

    path = raw_dir / entry["path"]
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        log.warning("%s: no readable raw file at %s; taking it as prose", entry["work"]["work_id"],
                    path)
        return entry["work"]["genre"] == "scripture"
    return is_standard(record)


def mt_path(output_dir: Path, entry: dict) -> Path:
    return output_dir / MT_SOURCE / entry["path"]


def mt_work_record(original: dict, served: str, date: str) -> dict:
    """The ``work`` of the MT raw file: the original's metadata, in English, from ``mt-eng``."""
    edition = original.get("edition") or source_label(original["source_id"])
    return {
        "work_id": f"{MT_SOURCE}/{original['work_id']}",
        "source_id": MT_SOURCE,
        "author": original.get("author"),
        "title": original["title"],
        "date_composed": original.get("date_composed"),
        "date_range": original.get("date_range"),
        "date_confidence": original.get("date_confidence", "uncertain"),
        "genre": original["genre"],
        "language": "eng",
        "tradition": original.get("tradition"),
        "license": original["license"],
        "provenance_url": original.get("provenance_url"),
        "edition": f"Machine translation ({served}, Patristica, {date}) of: {edition}",
        "translation_of": original["work_id"],
    }


def raw_record(entry: dict, units: list[Unit], english: dict[str, str], standard: bool,
               served: str, date: str, requests: int) -> dict:
    out_units = []
    for u in units:
        text = english[u.ref].strip()
        unit: dict[str, Any] = {"ref": u.ref, "text": text, "source_sha": u.sha}
        if u.editorial:
            unit["editorial"] = [[0, len(text), u.editorial]]
        out_units.append(unit)
    return {
        "work": mt_work_record(entry["work"], served, date),
        "verses" if standard else "paragraphs": out_units,
        "machine_translation": {
            "model": served,
            "prompt_version": PROMPT_VERSION,
            "date": date,
            "original": entry["work"]["work_id"],
            "original_path": entry["path"],
            "requests": requests,
            "script": "scripts.machine_translate",
        },
    }


def _load_partial(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"requests": {}}


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def translate_work(work_id: str, input_dir: Path, raw_dir: Path, output_dir: Path,
                   partial_dir: Path, model: str = DEFAULT_MODEL, workers: int = 3,
                   update: bool = False, dry_run: bool = False,
                   clients: Clients | None = None) -> Path | None:
    """Translate *work_id* into ``{output_dir}/mt-eng/{its path}``; the path, or None on a dry run.

    With *update*, an existing MT keeps every request whose units' source is unchanged.
    """
    entry = find_entry(input_dir, work_id)
    work = entry["work"]
    language = work["language"]
    if language not in DOCUMENT_LANGUAGES:
        raise MachineTranslateError(f"{work_id}: no prompt name for language {language!r}")
    if mt.is_machine_translation(work) or language == mt.ENGLISH:
        raise MachineTranslateError(f"{work_id}: already English")
    out = mt_path(output_dir, entry)
    if out.exists() and not update:
        raise MachineTranslateError(f"{out} exists: use --update to re-translate what changed")
    chunks = json.loads((input_dir / entry["path"]).read_text(encoding="utf-8"))
    units = units_of(chunks)
    if not units:
        raise MachineTranslateError(f"{work_id}: nothing to translate")
    standard = original_is_standard(entry, raw_dir)
    requests = make_requests(units)

    done: dict[str, dict] = {}  # request key → {"items": {ref: english}, "model": …}
    if update and out.exists():
        old = json.loads(out.read_text(encoding="utf-8"))
        old_units = {u["ref"]: u for u in old.get("verses") or old.get("paragraphs") or []}
        old_model = old["machine_translation"]["model"]
        for req in requests:
            if all(u.ref in old_units and old_units[u.ref]["source_sha"] == u.sha
                   for u in req.units):
                done[req.key] = {"items": {u.ref: old_units[u.ref]["text"] for u in req.units},
                                 "model": old_model}
    partial_path = partial_dir / MT_SOURCE / entry["path"]
    partial = _load_partial(partial_path)
    for req in requests:
        if req.key not in done and req.key in partial["requests"]:
            done[req.key] = partial["requests"][req.key]
    todo = [r for r in requests if r.key not in done]
    chars = sum(len(u.text) for r in todo for u in r.units)
    log.info("%s: %d units, %d requests (%d to send, %s source characters), %s",
             work_id, len(units), len(requests), len(todo), f"{chars:,}",
             "verses" if standard else "paragraphs")
    if dry_run:
        return None

    clients = clients or (Clients() if todo else None)
    system = DOCUMENT_SYSTEM.format(language=DOCUMENT_LANGUAGES[language])
    lock = threading.Lock()
    spent: list[dict] = []
    failures: list[str] = []

    def one(req: Request) -> None:
        reason = None
        for attempt in (1, 2):
            try:
                parsed, usage = clients.call(model, system, request_text(req), BulkTranslation)
            except Exception as e:  # noqa: BLE001 - logged, retried once, then the work fails
                reason = f"{type(e).__name__}: {e}"
            else:
                with lock:
                    spent.append(usage)
                got = {it.n: it.translation for it in parsed.items}
                reason = check_response(req, got, language)
                if reason is None:
                    result = {"items": {u.ref: got[i] for i, u in enumerate(req.units, start=1)},
                              "model": usage.get("served_by") or MODELS[model].model_id}
                    with lock:
                        done[req.key] = result
                        partial["requests"][req.key] = result
                        _write_json(partial_path, partial)
                    return
            log.warning("%s: request at %s, attempt %d: %s", work_id, req.units[0].ref,
                        attempt, reason)
        with lock:
            failures.append(f"{req.units[0].ref}: {reason}")

    with ThreadPoolExecutor(max(1, workers)) as pool:
        for i, _ in enumerate(pool.map(one, todo), start=1):
            if i % 5 == 0 or i == len(todo):
                report = limits_report(spent)
                log.info("%s: %d/%d requests, $%.2f%s", work_id, i, len(todo), cost(spent),
                         f"; subscription usage {report}" if report else "")
    if failures:
        raise MachineTranslateError(
            f"{work_id}: {len(failures)} requests failed (kept {len(done)} finished in "
            f"{partial_path}; re-run to resume): {failures[:3]}")
    english = {ref: text for r in requests for ref, text in done[r.key]["items"].items()}
    served = sorted({done[r.key]["model"] for r in requests})
    date = time.strftime("%Y-%m-%d")
    _write_json(out, raw_record(entry, units, english, standard, " + ".join(served), date,
                                len(requests)))
    partial_path.unlink(missing_ok=True)
    report = limits_report(spent)
    log.info("%s → %s (%d requests sent, $%.2f%s)", work_id, out, len(spent), cost(spent),
             f"; subscription usage {report}" if report else "")
    return out


# --- staleness ------------------------------------------------------------------


def stale(input_dir: Path, output_dir: Path) -> list[tuple[str, str]]:
    """``(MT work id, why)`` for every MT raw file that no longer matches its original."""
    entries = {e["work"]["work_id"]: e for e in load_works(input_dir)}
    out = []
    for path in sorted((output_dir / MT_SOURCE).rglob("*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        meta = record.get("machine_translation") or {}
        work_id = record["work"]["work_id"]
        entry = entries.get(meta.get("original", ""))
        if entry is None:
            out.append((work_id, f"original {meta.get('original')!r} not in the corpus"))
            continue
        chunks = json.loads((input_dir / entry["path"]).read_text(encoding="utf-8"))
        now = {u.ref: u.sha for u in units_of(chunks)}
        had = {u["ref"]: u["source_sha"] for u in record.get("verses") or record.get("paragraphs")}
        changed = [r for r in now if had.get(r) != now[r]]
        gone = [r for r in had if r not in now]
        if changed or gone:
            out.append((work_id, f"{len(changed)} paragraphs new or changed, {len(gone)} gone"
                        + (f" (e.g. {(changed + gone)[0]})" if changed or gone else "")))
    return out


# --- CLI ------------------------------------------------------------------------


def _chunks(input_dir: Path, path: str) -> list[dict]:
    return json.loads((input_dir / path).read_text(encoding="utf-8"))


def _version_info(input_dir: Path, v: mt.Version) -> dict[str, Any]:
    """A version for the listings: its fields, without the path, with its source characters."""
    info = {k: val for k, val in dataclasses.asdict(v).items() if k != "path"}
    info["chars"] = sum(len(u.text) for u in units_of(_chunks(input_dir, v.path)))
    return info


def candidate_rows(input_dir: Path, *, works: list[str] | None = None,
                   langs: list[str] | None = None, genres: list[str] | None = None,
                   exclude_sources: list[str] | None = None, min_chars: int | None = None,
                   max_chars: int | None = None, sort: str | None = None,
                   limit: int | None = None) -> list[dict[str, Any]]:
    """The candidates as listed by ``candidates``, filtered here so the nightly agent
    never needs shell text tools (#432). Metadata filters run before the files are read."""
    picked = []
    for cand in mt.candidates(load_works(input_dir)):
        if works and cand.work_id not in works:
            continue
        if (langs and cand.language not in langs) or (genres and cand.genre not in genres):
            continue
        if exclude_sources and cand.source_id in exclude_sources:
            continue
        units = units_of(_chunks(input_dir, cand.path))
        chars = sum(len(u.text) for u in units)
        if (min_chars is not None and chars < min_chars) or \
                (max_chars is not None and chars > max_chars):
            continue
        picked.append((cand, units, chars))
    if sort == "chars":
        picked.sort(key=lambda x: (x[2], x[0].work_id))
    rows = []
    for cand, units, chars in picked[:limit]:
        rows.append({**dataclasses.asdict(cand), "units": len(units), "chars": chars,
                     "requests": len(make_requests(units)),
                     "versions": [_version_info(input_dir, v) for v in cand.versions]})
    return rows


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input-dir", type=Path, default=Path("data/normalized"))
    p.add_argument("--raw-dir", type=Path, help="the originals' raw files (default: beside "
                   "--input-dir); only read to tell verses from paragraphs")
    p.add_argument("--output-dir", type=Path, default=Path("data/raw"),
                   help="where mt-eng/ is written (default data/raw)")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("candidates", help="works to machine-translate, with their sizes")
    c.add_argument("--work", nargs="+", help="only these work ids (their details)")
    c.add_argument("--lang", nargs="+", help="only these languages")
    c.add_argument("--genre", nargs="+", help="only these genres")
    c.add_argument("--exclude-source", nargs="+", metavar="SOURCE", help="leave out these sources")
    c.add_argument("--min-chars", type=int, help="at least N source characters")
    c.add_argument("--max-chars", type=int, help="at most N source characters")
    c.add_argument("--sort", choices=["chars"], help="smallest first (default: corpus order)")
    c.add_argument("--limit", type=int, help="at most N rows, after filtering and sorting")
    c.add_argument("--json", action="store_true", help="one JSON object per line")
    t = sub.add_parser("translate", help="machine-translate one work")
    t.add_argument("work_id")
    t.add_argument("--model", choices=TRANSLATORS, default=DEFAULT_MODEL)
    t.add_argument("--workers", type=int, default=3)
    t.add_argument("--partial-dir", type=Path, default=Path("logs/mt-partial"),
                   help="finished requests of unfinished works (gitignored scratch)")
    t.add_argument("--update", action="store_true",
                   help="re-translate only what changed in an existing MT")
    t.add_argument("--dry-run", action="store_true", help="report the requests only")
    sub.add_parser("stale", help="MT works whose original's text changed")
    r = sub.add_parser("review-versions",
                       help="derived versions with no exception row in groups with no "
                            "published English: is one divergent enough to translate?")
    r.add_argument("--json", action="store_true", help="one JSON object per line")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    raw_dir = args.raw_dir or args.input_dir.parent / "raw"

    if args.cmd == "candidates":
        for info in candidate_rows(
                args.input_dir, works=args.work, langs=args.lang, genres=args.genre,
                exclude_sources=args.exclude_source, min_chars=args.min_chars,
                max_chars=args.max_chars, sort=args.sort, limit=args.limit):
            if args.json:
                print(json.dumps(info, ensure_ascii=False))
            else:
                others = ", ".join(f"{v['work_id']} ({v['language']}, {v['kind']}, "
                                   f"{v['chars']:,})" for v in info["versions"])
                print(f"{info['work_id']}\t{info['language']}\t{info['chars']:>9,}\t"
                      f"{info['author'] or '-'}\t{info['title']}"
                      + (f"\tversions: {others}" if others else ""))
    elif args.cmd == "review-versions":
        for v in mt.versions_to_review(load_works(args.input_dir)):
            info = _version_info(args.input_dir, v)
            if args.json:
                print(json.dumps(info, ensure_ascii=False))
            else:
                print(f"{v.work_id}\t{v.language}\t{info['chars']:>9,}\t"
                      f"translation of {v.translation_of}")
    elif args.cmd == "translate":
        try:
            translate_work(args.work_id, args.input_dir, raw_dir, args.output_dir,
                           args.partial_dir, args.model, args.workers, args.update, args.dry_run)
        except MachineTranslateError as e:
            log.error("%s", e)
            raise SystemExit(1) from e
    else:
        rows = stale(args.input_dir, args.output_dir)
        for work_id, why in rows:
            print(f"{work_id}\t{why}")
        log.info("%d stale machine translations", len(rows))


if __name__ == "__main__":
    main()
