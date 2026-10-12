"""
Translation eval for the low-resource languages (#3): can a cheap model
translate Syriac, Coptic, Armenian and Ge'ez well enough that we can embed
the English instead of the original?

``quality`` translates the targets of the drafted paraphrase/topical queries
with the bulk model (Haiku) and a reference model (Opus), then has Opus judge
both translations blind, in random order, against the original. For
Scripture targets a published English translation from the same verse group
(WEB, else KJV/ASV) is given to the judge as a reference. Results are
appended to ``data/eval/translation/quality.jsonl`` (resumable), and token
usage is reported so cost can be checked before scaling up.

Usage::

    python -m scripts.embed_eval.translate quality [--limit N] [--langs syc cop hye gez]
    python -m scripts.embed_eval.translate summary
"""

from __future__ import annotations

import argparse
import json
import logging
import random
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

BULK_MODEL = "claude-haiku-5-5"
REFERENCE_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

LANGUAGE_NAMES = {
    "syc": "Syriac",
    "cop": "Coptic (Sahidic)",
    "hye": "Classical Armenian (Grabar)",
    "gez": "Ge'ez (Classical Ethiopic)",
}

# USD per million tokens (input, output), from the claude-api model table.
PRICES = {BULK_MODEL: (0.10, 0.50), REFERENCE_MODEL: (4.00, 20.00)}

DEFAULT_DIR = Path("data/eval")
DEFAULT_AUTHORED = Path("data/eval_authored")

TRANSLATOR_SYSTEM = """\
You translate early Christian and Jewish texts from {language} into plain modern \
English. The translation will be indexed for search, so it must carry the full \
meaning of the passage.

- Translate the whole passage faithfully: no summary, no commentary, no omissions, \
nothing added. Translate rubrics and headings too.
- Use conventional English forms of proper names.
- Where the text is damaged or garbled, or a word is unknown to you, translate what \
you can and mark the gap with [?]. Do not guess silently.
- Rate your confidence in the translation, and name the source if you recognize the \
passage as a known text (for example a Bible verse); otherwise leave it null."""

JUDGE_SYSTEM = """\
You assess English translations of {language} passages from early Christian and \
Jewish texts. You are given the original, sometimes a published reference \
translation, and two candidate translations labelled A and B.

For each candidate, rate fidelity to the original from 1 to 5:
5 = all meaning preserved, nothing added or lost; 4 = minor nuance lost; \
3 = some clauses wrong or missing, but the gist is right; 2 = the gist is \
distorted; 1 = mostly wrong or invented.
List each error with its type: omission, addition, mistranslation, or \
hallucination (content not in the original at all).

Judge against the original. A reference translation, if given, may follow a \
different textual tradition; do not penalise a candidate for matching the \
original where the reference differs. Say how confidently you can read the \
original yourself."""


class Translation(BaseModel):
    translation: str
    confidence: Literal["high", "medium", "low"]
    recognized_source: str | None = Field(
        description="Known text the passage comes from, e.g. 'Luke 15:32', or null")


class TranslationError(BaseModel):
    type: Literal["omission", "addition", "mistranslation", "hallucination"]
    detail: str


class CandidateVerdict(BaseModel):
    fidelity: int = Field(ge=1, le=5)
    errors: list[TranslationError]


class Judgement(BaseModel):
    a: CandidateVerdict
    b: CandidateVerdict
    same_meaning: bool = Field(description="Do A and B say the same thing?")
    judge_can_read_original: Literal["well", "partly", "poorly"]


def _client():
    import anthropic

    from scripts.embed_eval.embedders import _env_key

    return anthropic.Anthropic(api_key=_env_key("ANTHROPIC_API_KEY"), max_retries=6)


def translate(client, model: str, lang: str, text: str) -> tuple[Translation, dict]:
    kwargs = dict(
        model=model,
        max_tokens=16000,
        system=TRANSLATOR_SYSTEM.format(language=LANGUAGE_NAMES[lang]),
        messages=[{"role": "user", "content": text}],
        output_format=Translation,
    )
    if model == REFERENCE_MODEL:
        resp = client.beta.messages.parse(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
    else:
        resp = client.messages.parse(**kwargs)
    _check(resp)
    return resp.parsed_output, _usage(model, resp)


def judge(client, lang: str, text: str, reference: str | None,
          a: str, b: str) -> tuple[Judgement, dict]:
    parts = [f"Original ({LANGUAGE_NAMES[lang]}):\n{text}"]
    if reference:
        parts.append(f"Published reference translation:\n{reference}")
    parts += [f"Candidate A:\n{a}", f"Candidate B:\n{b}"]
    resp = client.beta.messages.parse(
        model=REFERENCE_MODEL,
        max_tokens=16000,
        betas=[FALLBACK_BETA],
        fallbacks="default",
        output_config={"effort": "high"},
        system=JUDGE_SYSTEM.format(language=LANGUAGE_NAMES[lang]),
        messages=[{"role": "user", "content": "\n\n".join(parts)}],
        output_format=Judgement,
    )
    _check(resp)
    return resp.parsed_output, _usage(REFERENCE_MODEL, resp)


def _check(resp) -> None:
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"refused: {resp.stop_details}")
    if resp.stop_reason == "max_tokens":
        raise RuntimeError("hit max_tokens")


def _usage(model: str, resp) -> dict:
    u = resp.usage
    return {"model": model, "input": u.input_tokens, "output": u.output_tokens}


def cost(usages: list[dict]) -> float:
    total = 0.0
    for u in usages:
        pin, pout = PRICES[u["model"]]
        total += u["input"] * pin / 1e6 + u["output"] * pout / 1e6
    return total


# --- target selection -----------------------------------------------------------

def quality_targets(eval_dir: Path, authored_dir: Path, langs: list[str]) -> list[dict]:
    """Targets of authored queries in *langs*, with an English reference for Scripture."""
    corpus = {}
    by_group: dict[str, list[dict]] = defaultdict(list)
    for line in (eval_dir / "corpus.jsonl").open(encoding="utf-8"):
        c = json.loads(line)
        corpus[c["chunk_id"]] = c
        if c.get("translation_group_id") and c["language"] == "eng":
            by_group[c["translation_group_id"]].append(c)
    ids: dict[str, str] = {}
    for path in sorted(authored_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                q = json.loads(line)
                if q["target_lang"] in langs:
                    ids[q["target_chunk_id"]] = q["origin"]
    out = []
    for cid, origin in sorted(ids.items()):
        c = corpus.get(cid)
        if c is None:
            continue
        ref = None
        eng = by_group.get(c.get("translation_group_id") or "", [])
        for source in ("scripture/web/", "scripture/kjv/", "scripture/asv/"):
            ref = next((e["text"] for e in eng if e["work_id"].startswith(source)), None)
            if ref:
                break
        out.append({"chunk_id": cid, "language": c["language"], "origin": origin,
                    "text": c["text"], "reference": ref})
    return out


def run_quality(eval_dir: Path, authored_dir: Path, langs: list[str], limit: int | None,
                workers: int, seed: int = 0) -> None:
    out_dir = eval_dir / "translation"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "quality.jsonl"
    done = set()
    if out_path.exists():
        done = {json.loads(line)["chunk_id"] for line in out_path.open(encoding="utf-8")}
    targets = [t for t in quality_targets(eval_dir, authored_dir, langs)
               if t["chunk_id"] not in done]
    if limit is not None:
        per_lang: dict[str, list[dict]] = defaultdict(list)
        for t in targets:
            per_lang[t["language"]].append(t)
        targets = [t for lang in langs for t in per_lang[lang][:limit]]
    log.info("Translating and judging %d passages (%d already done)", len(targets), len(done))
    client = _client()

    def one(t: dict) -> dict:
        rng = random.Random(f"{seed}:{t['chunk_id']}")
        haiku, u1 = translate(client, BULK_MODEL, t["language"], t["text"])
        opus, u2 = translate(client, REFERENCE_MODEL, t["language"], t["text"])
        haiku_is_a = rng.random() < 0.5
        a, b = (haiku, opus) if haiku_is_a else (opus, haiku)
        j, u3 = judge(client, t["language"], t["text"], t["reference"],
                      a.translation, b.translation)
        hv, ov = (j.a, j.b) if haiku_is_a else (j.b, j.a)
        return {**t, "haiku": haiku.model_dump(), "opus": opus.model_dump(),
                "haiku_verdict": hv.model_dump(), "opus_verdict": ov.model_dump(),
                "same_meaning": j.same_meaning,
                "judge_can_read_original": j.judge_can_read_original,
                "usage": [u1, u2, u3]}

    with ThreadPoolExecutor(workers) as pool, out_path.open("a", encoding="utf-8") as f:
        for row in pool.map(_safe(one), targets):
            if row is not None:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
                f.flush()
    summarize(out_path)


def _safe(fn):
    def wrapped(t):
        try:
            return fn(t)
        except Exception:
            log.exception("failed on %s", t["chunk_id"])
            return None
    return wrapped


def summarize(path: Path) -> None:
    rows = [json.loads(line) for line in path.open(encoding="utf-8")]
    if not rows:
        print("no results")
        return
    print(f"{len(rows)} passages, cost so far ${cost([u for r in rows for u in r['usage']]):.2f}")
    print(f"{'lang':4s} {'origin':9s} {'n':>3s} {'haiku':>6s} {'opus':>6s} "
          f"{'h<=2':>5s} {'h_hallu':>7s} {'agree':>6s} {'judge_reads_well':>16s}")
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in rows:
        groups[(r["language"], r["origin"])].append(r)
    for (lang, origin), rs in sorted(groups.items()):
        n = len(rs)
        h = sum(r["haiku_verdict"]["fidelity"] for r in rs) / n
        o = sum(r["opus_verdict"]["fidelity"] for r in rs) / n
        bad = sum(r["haiku_verdict"]["fidelity"] <= 2 for r in rs)
        hallu = sum(any(e["type"] == "hallucination" for e in r["haiku_verdict"]["errors"])
                    for r in rs)
        agree = sum(r["same_meaning"] for r in rs)
        reads = Counter(r["judge_can_read_original"] for r in rs)["well"]
        print(f"{lang:4s} {origin:9s} {n:3d} {h:6.2f} {o:6.2f} {bad:5d} {hallu:7d} "
              f"{agree:6d} {reads:16d}")
    conf = Counter((r["haiku"]["confidence"], r["haiku_verdict"]["fidelity"] >= 4) for r in rows)
    print("haiku confidence vs fidelity>=4:", dict(sorted(conf.items())))


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("quality")
    q.add_argument("--langs", nargs="+", default=list(LANGUAGE_NAMES))
    q.add_argument("--limit", type=int, help="at most N new passages per language")
    q.add_argument("--workers", type=int, default=4)
    sub.add_parser("summary")
    p.add_argument("--eval-dir", type=Path, default=DEFAULT_DIR)
    p.add_argument("--authored", type=Path, default=DEFAULT_AUTHORED)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.cmd == "quality":
        run_quality(args.eval_dir, args.authored, args.langs, args.limit, args.workers)
    else:
        summarize(args.eval_dir / "translation" / "quality.jsonl")


if __name__ == "__main__":
    main()
