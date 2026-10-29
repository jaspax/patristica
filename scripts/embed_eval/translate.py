"""
Translation eval for the low-resource languages (#3): which model translates
Syriac, Coptic, Armenian and Ge'ez well enough that we can embed the English
instead of the original?

``quality`` translates the targets of the drafted paraphrase/topical queries
with every model in ``TRANSLATORS`` (Claude Haiku/Sonnet/Opus 5.5 and OpenAI
GPT-6.1 Sol), then has every model in ``JUDGES`` (Opus and Sol) rate all
translations of a passage blind, under shuffled labels, against the original.
For Scripture targets a published English translation from the same verse
group (WEB, else KJV/ASV) is given to the judges as a reference. Having
judges from two vendors means every translation also gets a verdict from a
model other than the one that produced it.

``local-opus`` runs Opus through a local ``claude -p`` on the Claude
subscription login instead of the API (``Clients._claude_cli``): no API key
and no bill, but it counts against the subscription's usage windows, which
each call reports (``limits_report``).

Translations and judgements are cached in ``data/eval/translation/``
(``translations.jsonl``, ``judgements.jsonl``), so runs resume and new models
can be added without redoing the rest. Token usage is logged for cost.

Usage::

    python -m scripts.embed_eval.translate quality [--limit N] [--langs syc cop hye gez]
    python -m scripts.embed_eval.translate summary

Bulk translation of the corpus for indexing is ``scripts.translate`` (#93),
which reuses ``Clients`` and the translator prompt from here.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import string
import subprocess
import tempfile
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Model:
    vendor: Literal["anthropic", "openai", "claude-cli"]
    model_id: str
    price_in: float  # USD per million tokens
    price_out: float


# Prices: Claude from the claude-api model table; Sol from third-party
# listings (Oct 2026) - check OpenAI's pricing page before budgeting on it.
# "claude-cli" models run on the subscription: no price, usage windows instead.
MODELS: dict[str, Model] = {
    "haiku": Model("anthropic", "claude-haiku-5-5", 0.10, 0.50),
    "sonnet": Model("anthropic", "claude-sonnet-5-5", 2.00, 10.00),
    "opus": Model("anthropic", "claude-opus-5-5", 4.00, 20.00),
    "sol": Model("openai", "gpt-6.1-sol", 2.00, 10.00),
    "local-opus": Model("claude-cli", "claude-opus-5-5", 0.0, 0.0),
    "local-haiku": Model("claude-cli", "claude-haiku-5-5", 0.0, 0.0),  # usage probe
}
TRANSLATORS = ("haiku", "sonnet", "opus", "sol")
JUDGES = ("opus", "sol")

FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-opus-5-5", "claude-sonnet-5-5"}

LANGUAGE_NAMES = {
    "syc": "Syriac",
    "cop": "Coptic (Sahidic)",
    "hye": "Classical Armenian (Grabar)",
    "gez": "Ge'ez (Classical Ethiopic)",
    "chu": "Old Church Slavonic",
}
# Languages measured before deciding whether they get translation vectors
# (docs/adding-a-language.md section 3). They are prompt names only: enrolling
# a language means moving it to LANGUAGE_NAMES (and TRANSLATED_LANGUAGES).
EVAL_LANGUAGES: dict[str, str] = {}
PROMPT_NAMES = {**LANGUAGE_NAMES, **EVAL_LANGUAGES}

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
translation, and several candidate translations labelled with letters.

For each candidate, rate fidelity to the original from 1 to 5:
5 = all meaning preserved, nothing added or lost; 4 = minor nuance lost; \
3 = some clauses wrong or missing, but the gist is right; 2 = the gist is \
distorted; 1 = mostly wrong or invented.
List each error with its type: omission, addition, mistranslation, or \
hallucination (content not in the original at all).

Judge against the original. A reference translation, if given, may follow a \
different textual tradition; do not penalise a candidate for matching the \
original where the reference differs. Rate each candidate on its own merits, \
not by comparison with the others. Say how confidently you can read the \
original yourself."""


class Translation(BaseModel):
    translation: str
    confidence: Literal["high", "medium", "low"]
    recognized_source: str | None = Field(
        description="Known text the passage comes from, e.g. 'Luke 15:32', or null")


class TranslationError(BaseModel):
    type: Literal["omission", "addition", "mistranslation", "hallucination"]
    detail: str


class Verdict(BaseModel):
    label: str
    fidelity: int = Field(ge=1, le=5)
    errors: list[TranslationError]


class Judgement(BaseModel):
    verdicts: list[Verdict]
    judge_can_read_original: Literal["well", "partly", "poorly"]


def openai_schema(model: type[BaseModel]) -> dict:
    """Pydantic schema → OpenAI strict schema: every field required, no extra keys."""
    schema = model.model_json_schema()

    def fix(node: dict) -> None:
        if "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"])
            for child in node["properties"].values():
                fix(child)
        for key in ("minimum", "maximum", "title", "default"):
            node.pop(key, None)
        if isinstance(node.get("items"), dict):
            fix(node["items"])
        for child in node.get("anyOf", []):
            fix(child)
        for child in node.get("$defs", {}).values():
            fix(child)

    fix(schema)
    return schema


class Clients:
    """API clients, created on first use, so a run that only calls one vendor
    needs only that vendor's key (and the anthropic package only for Claude)."""

    def __init__(self) -> None:
        self._anthropic_client = None
        self._openai_key: str | None = None
        self._http = None
        self._lock = threading.Lock()

    @property
    def anthropic(self):
        with self._lock:
            if self._anthropic_client is None:
                import anthropic

                from scripts.embed_eval.embedders import _env_key

                self._anthropic_client = anthropic.Anthropic(
                    api_key=_env_key("ANTHROPIC_API_KEY"), max_retries=6)
            return self._anthropic_client

    @property
    def openai_key(self) -> str:
        with self._lock:
            if self._openai_key is None:
                from scripts.embed_eval.embedders import _env_key

                self._openai_key = _env_key("OPENAI_API_KEY")
            return self._openai_key

    @property
    def http(self):
        with self._lock:
            if self._http is None:
                import httpx

                self._http = httpx.Client(timeout=900)
            return self._http

    def call(self, name: str, system: str, user: str, schema: type[BaseModel],
             effort: str | None = None) -> tuple[BaseModel, dict]:
        m = MODELS[name]
        if m.vendor == "anthropic":
            return self._anthropic(name, m, system, user, schema, effort)
        if m.vendor == "claude-cli":
            return self._claude_cli(name, m, system, user, schema, effort)
        return self._openai(name, m, system, user, schema, effort)

    def _anthropic(self, name, m, system, user, schema, effort):
        kwargs: dict = dict(model=m.model_id, max_tokens=16000, system=system,
                            messages=[{"role": "user", "content": user}], output_format=schema)
        if effort:
            kwargs["output_config"] = {"effort": effort}
        if m.model_id in FALLBACK_MODELS:
            resp = self.anthropic.beta.messages.parse(
                betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
        else:
            resp = self.anthropic.messages.parse(**kwargs)
        if resp.stop_reason in ("refusal", "max_tokens"):
            raise RuntimeError(f"{name}: stop_reason {resp.stop_reason}")
        # With server-side fallback, a declined request can be served by another
        # model; resp.model names the one that answered.
        usage = {"model": name, "input": resp.usage.input_tokens,
                 "output": resp.usage.output_tokens, "served_by": resp.model}
        return resp.parsed_output, usage

    def _openai(self, name, m, system, user, schema, effort):
        body = {
            "model": m.model_id, "max_completion_tokens": 32000,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "response_format": {"type": "json_schema", "json_schema": {
                "name": schema.__name__, "schema": openai_schema(schema), "strict": True}},
        }
        if effort:
            body["reasoning_effort"] = effort
        for attempt in range(6):
            r = self.http.post("https://api.openai.com/v1/chat/completions",
                               headers={"Authorization": f"Bearer {self.openai_key}"},
                               json=body)
            if r.status_code == 200:
                break
            if r.status_code not in (429, 500, 502, 503) or attempt == 5:
                raise RuntimeError(f"{name}: HTTP {r.status_code}: {r.text[:300]}")
            time.sleep(10 * (attempt + 1))
        j = r.json()
        choice = j["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise RuntimeError(f"{name}: finish_reason {choice.get('finish_reason')}")
        usage = {"model": name, "input": j["usage"]["prompt_tokens"],
                 "output": j["usage"]["completion_tokens"]}
        return schema.model_validate_json(choice["message"]["content"]), usage

    def _claude_cli(self, name, m, system, user, schema, effort):
        # The request's fields as claude -p arguments: no tools, settings, MCP
        # servers or session, and an empty working directory, so no project
        # context (CLAUDE.md, memory) reaches the model. The user text goes on
        # stdin. Auth is the local login; usage windows come back per call.
        cmd = ["claude", "-p", "--model", m.model_id, "--system-prompt", system,
               "--json-schema", json.dumps(schema.model_json_schema()),
               "--tools", "", "--setting-sources", "", "--strict-mcp-config",
               "--no-session-persistence", "--verbose", "--output-format", "stream-json"]
        if effort:
            cmd += ["--effort", effort]
        with tempfile.TemporaryDirectory() as cwd:
            proc = subprocess.run(cmd, input=user, capture_output=True, text=True,
                                  cwd=cwd, timeout=900)
        return parse_claude_stream(name, proc.stdout, proc.returncode, proc.stderr, schema)


def parse_claude_stream(name: str, stdout: str, returncode: int, stderr: str,
                        schema: type[BaseModel]) -> tuple[BaseModel, dict]:
    """The output of ``claude -p --output-format stream-json`` → (parsed, usage).

    ``usage["limits"]`` holds the subscription's usage windows from the last
    ``rate_limit_event`` (``{"five_hour": {"utilization", "resets_at"}, …}``),
    or is missing when the CLI sent none.
    """
    result = None
    limits: dict = {}
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "rate_limit_event":
            info = event.get("rate_limit_info") or {}
            for window, w in (info.get("unifiedWindows") or {}).items():
                limits[window] = {"utilization": w.get("utilization"),
                                  "resets_at": w.get("resetsAt"), "status": w.get("status")}
            if info.get("isUsingOverage"):
                limits["overage"] = True
        elif event.get("type") == "result":
            result = event
    if result is None:
        raise RuntimeError(f"{name}: claude exited {returncode} without a result: "
                           f"{(stderr or stdout)[-300:]}")
    if result.get("is_error") or result.get("structured_output") is None:
        raise RuntimeError(f"{name}: claude {result.get('subtype')}: "
                           f"{str(result.get('result'))[:300]}")
    u = result.get("usage") or {}
    served = [k for k in result.get("modelUsage") or {}]
    usage = {"model": name,
             "input": u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
             + u.get("cache_read_input_tokens", 0),
             "output": u.get("output_tokens", 0)}
    if len(served) == 1:
        usage["served_by"] = served[0]
    if limits:
        usage["limits"] = limits
    return schema.model_validate(result["structured_output"]), usage


def limits_report(usages: list[dict]) -> str | None:
    """The latest subscription usage among *usages*, for the log; None if none."""
    latest = next((u["limits"] for u in reversed(usages) if u.get("limits")), None)
    if latest is None:
        return None
    parts = []
    for window, label in (("five_hour", "5-hour"), ("seven_day", "7-day")):
        w = latest.get(window)
        if not w or w.get("utilization") is None:
            continue
        resets = (time.strftime("%a %H:%M UTC", time.gmtime(w["resets_at"]))
                  if w.get("resets_at") else "?")
        parts.append(f"{label} {w['utilization']:.0%} (resets {resets})")
    if latest.get("overage"):
        parts.append("using extra usage")
    return ", ".join(parts) or None


def cost(usages: list[dict]) -> float:
    return sum(u["input"] * MODELS[u["model"]].price_in / 1e6
               + u["output"] * MODELS[u["model"]].price_out / 1e6 for u in usages)


# --- target selection -----------------------------------------------------------

def quality_targets(eval_dir: Path, authored_dir: Path, langs: list[str]) -> list[dict]:
    """Targets of authored queries in *langs*, with an English reference for Scripture."""
    corpus = {}
    eng_by_group: dict[str, list[dict]] = defaultdict(list)
    for line in (eval_dir / "corpus.jsonl").open(encoding="utf-8"):
        c = json.loads(line)
        corpus[c["chunk_id"]] = c
        if c.get("translation_group_id") and c["language"] == "eng":
            eng_by_group[c["translation_group_id"]].append(c)
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
        eng = eng_by_group.get(c.get("translation_group_id") or "", [])
        for source in ("web/", "kjv/", "asv/"):
            ref = next((e["text"] for e in eng if e["work_id"].startswith(source)), None)
            if ref:
                break
        out.append({"chunk_id": cid, "language": c["language"], "origin": origin,
                    "text": c["text"], "reference": ref})
    return out


# --- run ------------------------------------------------------------------------

class Store:
    """Append-only JSONL of results keyed by (model, chunk_id); thread-safe."""

    def __init__(self, path: Path) -> None:
        self.path, self.lock = path, threading.Lock()
        self.rows: dict[tuple[str, str], dict] = {}
        if path.exists():
            for line in path.open(encoding="utf-8"):
                r = json.loads(line)
                self.rows[(r["model"], r["chunk_id"])] = r

    def get(self, model: str, chunk_id: str) -> dict | None:
        return self.rows.get((model, chunk_id))

    def put(self, row: dict) -> None:
        with self.lock:
            self.rows[(row["model"], row["chunk_id"])] = row
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_quality(eval_dir: Path, authored_dir: Path, langs: list[str], limit: int | None,
                workers: int, seed: int = 0) -> None:
    out_dir = eval_dir / "translation"
    out_dir.mkdir(parents=True, exist_ok=True)
    translations = Store(out_dir / "translations.jsonl")
    judgements = Store(out_dir / "judgements.jsonl")
    targets = quality_targets(eval_dir, authored_dir, langs)
    if limit is not None:
        per_lang: dict[str, list[dict]] = defaultdict(list)
        for t in targets:
            per_lang[t["language"]].append(t)
        targets = [t for lang in langs for t in per_lang[lang][:limit]]
    log.info("%d passages, %d translators, %d judges", len(targets), len(TRANSLATORS),
             len(JUDGES))
    clients = Clients()

    def translate_one(job: tuple[str, dict]) -> None:
        name, t = job
        if translations.get(name, t["chunk_id"]):
            return
        system = TRANSLATOR_SYSTEM.format(language=PROMPT_NAMES[t["language"]])
        out, usage = clients.call(name, system, t["text"], Translation)
        translations.put({"model": name, "chunk_id": t["chunk_id"], **out.model_dump(),
                          "usage": usage})

    def judge_one(job: tuple[str, dict]) -> None:
        judge, t = job
        if judgements.get(judge, t["chunk_id"]):
            return
        names = [n for n in TRANSLATORS if translations.get(n, t["chunk_id"])]
        rng = random.Random(f"{seed}:{judge}:{t['chunk_id']}")
        rng.shuffle(names)
        labels = dict(zip(string.ascii_uppercase, names, strict=False))
        parts = [f"Original ({PROMPT_NAMES[t['language']]}):\n{t['text']}"]
        if t["reference"]:
            parts.append(f"Published reference translation:\n{t['reference']}")
        parts += [f"Candidate {label}:\n{translations.get(n, t['chunk_id'])['translation']}"
                  for label, n in labels.items()]
        system = JUDGE_SYSTEM.format(language=PROMPT_NAMES[t["language"]])
        out, usage = clients.call(judge, system, "\n\n".join(parts), Judgement, effort="high")
        by_model = {}
        for v in out.verdicts:
            if v.label in labels:
                by_model[labels[v.label]] = {"fidelity": v.fidelity,
                                             "errors": [e.model_dump() for e in v.errors]}
        missing = set(names) - set(by_model)
        if missing:
            raise RuntimeError(f"{judge} gave no verdict for {missing} on {t['chunk_id']}")
        judgements.put({"model": judge, "chunk_id": t["chunk_id"], "language": t["language"],
                        "origin": t["origin"], "verdicts": by_model,
                        "judge_can_read_original": out.judge_can_read_original,
                        "usage": usage})

    with ThreadPoolExecutor(workers) as pool:
        list(pool.map(_safe(translate_one), [(n, t) for t in targets for n in TRANSLATORS]))
        list(pool.map(_safe(judge_one), [(j, t) for t in targets for j in JUDGES]))
    summarize(out_dir)


def _safe(fn):
    def wrapped(job):
        try:
            fn(job)
        except Exception as e:
            log.error("%s on %s failed: %s", job[0], job[1]["chunk_id"], e)
    return wrapped


def summarize(out_dir: Path) -> None:
    translations = Store(out_dir / "translations.jsonl")
    judgements = Store(out_dir / "judgements.jsonl")
    usages = [r["usage"] for r in translations.rows.values()]
    usages += [r["usage"] for r in judgements.rows.values()]
    print(f"cost so far ${cost(usages):.2f} "
          f"({len(translations.rows)} translations, {len(judgements.rows)} judgements)")
    for name in TRANSLATORS:
        tr = [r["usage"] for (m, _), r in translations.rows.items() if m == name]
        if tr:
            print(f"  {name:6s} translation: ${cost(tr):.3f} for {len(tr)} passages "
                  f"(${cost(tr) / len(tr):.4f} each)")

    cells: dict[tuple, list[int]] = defaultdict(list)
    hallu: dict[tuple[str, str], int] = defaultdict(int)
    for (judge, _), r in judgements.rows.items():
        for name, v in r["verdicts"].items():
            for key in ((r["language"], r["origin"]), ("all", "all")):
                cells[(name, judge, *key)].append(v["fidelity"])
            if any(e["type"] == "hallucination" for e in v["errors"]):
                hallu[(name, judge)] += 1
    groups = sorted({k[2:] for k in cells} - {("all", "all")}) + [("all", "all")]
    print("\nmean fidelity (1-5), translator × judge; (self) = judge scored its own work")
    print(f"{'translator':10s} {'judge':5s} "
          + " ".join(f"{g[0] + '/' + g[1][:4]:>9s}" for g in groups) + "  hallucinated")
    for name in TRANSLATORS:
        for judge in JUDGES:
            vals = [cells.get((name, judge, *g)) for g in groups]
            if not any(vals):
                continue
            row = " ".join(f"{sum(v) / len(v):9.2f}" if v else f"{'–':>9s}" for v in vals)
            tag = " (self)" if name == judge else ""
            print(f"{name:10s} {judge:5s} {row}  {hallu[(name, judge)]:>12d}{tag}")

    pairs = []
    for (judge, cid), r in judgements.rows.items():
        other = judgements.get(JUDGES[1], cid) if judge == JUDGES[0] else None
        if other:
            pairs += [(v["fidelity"], other["verdicts"][n]["fidelity"])
                      for n, v in r["verdicts"].items() if n in other["verdicts"]]
    if pairs:
        exact = sum(a == b for a, b in pairs) / len(pairs)
        within1 = sum(abs(a - b) <= 1 for a, b in pairs) / len(pairs)
        print(f"\njudge agreement ({JUDGES[0]} vs {JUDGES[1]}, {len(pairs)} translations): "
              f"exact {exact:.2f}, within one point {within1:.2f}")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("quality")
    q.add_argument("--langs", nargs="+", default=list(LANGUAGE_NAMES),
                   choices=list(PROMPT_NAMES))
    q.add_argument("--limit", type=int, help="at most N passages per language")
    q.add_argument("--workers", type=int, default=6)
    sub.add_parser("summary")
    p.add_argument("--eval-dir", type=Path, default=DEFAULT_DIR)
    p.add_argument("--authored", type=Path, default=DEFAULT_AUTHORED)
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.cmd == "quality":
        run_quality(args.eval_dir, args.authored, args.langs, args.limit, args.workers)
    else:
        summarize(args.eval_dir / "translation")


if __name__ == "__main__":
    main()
