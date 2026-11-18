"""Model backends for the OCR stages: Gemini (direct or batch) and Claude (batch API or claude -p).

A Job is one request: a system prompt, text and images (base64 JPEG) in order,
and whether the answer is JSON. Every backend's run(jobs) returns
{key: Result}. Batch backends cost 50% of the direct price and finish within
24 hours (usually much sooner); they save the batch id under the stage
directory so an interrupted run resumes instead of paying again.
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta"
# A Gemini batch with inline requests must stay under 20 MB.
GEMINI_BATCH_BYTES = 15_000_000
_COMMENT = re.compile(r"^\W*(the|this) (image|strip|page)\b", re.IGNORECASE)


@dataclass
class Job:
    key: str
    system: str
    parts: list[tuple[str, str]]  # ("text", str) or ("image", base64 jpeg)
    json_answer: bool = False


@dataclass
class Result:
    text: str
    usage: dict = field(default_factory=dict)
    error: str | None = None


class BackendError(RuntimeError):
    pass


def drop_comments(text: str) -> str:
    """Remove lines where the model talks about the image instead of transcribing."""
    return "\n".join(ln for ln in text.splitlines() if not _COMMENT.match(ln)).strip()


def parse_json(text: str) -> dict:
    """The JSON object in a reply (a code fence or a stray word around it is ignored)."""
    a, b = text.find("{"), text.rfind("}")
    if a < 0 or b < a:
        raise ValueError(f"no JSON object in reply: {text[:200]!r}")
    return json.loads(text[a:b + 1])


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

class Gemini:
    """Gemini generateContent, direct (sync) or through the Batch API."""

    def __init__(self, model: str, thinking: str = "low", batch: bool = True,
                 state_dir: Path | None = None, workers: int = 4) -> None:
        self.model, self.thinking, self.batch = model, thinking, batch
        self.state_dir, self.workers = state_dir, workers
        self.key = os.environ.get("GEMINI_API_KEY") or ""
        if not self.key:
            raise BackendError("GEMINI_API_KEY is not set")

    def request(self, job: Job) -> dict:
        parts = [{"text": v} if k == "text" else
                 {"inline_data": {"mime_type": "image/jpeg", "data": v}} for k, v in job.parts]
        gen: dict = {"temperature": 0, "mediaResolution": "MEDIA_RESOLUTION_HIGH",
                     "thinkingConfig": {"thinkingLevel": self.thinking}}
        if job.json_answer:
            gen["responseMimeType"] = "application/json"
        return {"systemInstruction": {"parts": [{"text": job.system}]},
                "contents": [{"role": "user", "parts": parts}], "generationConfig": gen}

    def _post(self, client: httpx.Client, url: str, body: dict) -> dict:
        for attempt in range(6):
            try:
                r = client.post(url, json=body, headers={"x-goog-api-key": self.key})
            except httpx.TransportError:
                time.sleep(10 * (attempt + 1))
                continue
            if r.status_code == 200:
                return r.json()
            if r.status_code in (400, 401, 402, 403, 404):
                raise BackendError(f"Gemini HTTP {r.status_code}: {r.text[:300]}")
            time.sleep(10 * (attempt + 1))
        raise BackendError(f"Gemini: gave up on {url}")

    @staticmethod
    def _text(resp: dict) -> tuple[str, dict]:
        cand = (resp.get("candidates") or [{}])[0]
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return text, resp.get("usageMetadata", {})

    def run(self, jobs: list[Job]) -> dict[str, Result]:
        if not jobs:
            return {}
        return self._run_batch(jobs) if self.batch else self._run_sync(jobs)

    def _run_sync(self, jobs: list[Job]) -> dict[str, Result]:
        url = f"{GEMINI_URL}/models/{self.model}:generateContent"
        with httpx.Client(timeout=600) as client:
            def one(job: Job) -> tuple[str, Result]:
                text, usage = self._text(self._post(client, url, self.request(job)))
                return job.key, Result(text, usage)
            with ThreadPoolExecutor(self.workers) as ex:
                return dict(ex.map(one, jobs))

    def _chunks(self, jobs: list[Job]) -> list[list[Job]]:
        out, cur, size = [], [], 0
        for job in jobs:
            n = len(json.dumps(self.request(job)))
            if cur and size + n > GEMINI_BATCH_BYTES:
                out.append(cur)
                cur, size = [], 0
            cur.append(job)
            size += n
        return out + ([cur] if cur else [])

    def _run_batch(self, jobs: list[Job]) -> dict[str, Result]:
        results: dict[str, Result] = {}
        with httpx.Client(timeout=600) as client:
            for n, chunk in enumerate(self._chunks(jobs)):
                state = self.state_dir / f"_gemini_batch_{n}.json" if self.state_dir else None
                name = json.loads(state.read_text())["name"] if state and state.exists() else None
                if name is None:
                    body = {"batch": {"display_name": f"patristica-ocr-{int(time.time())}-{n}",
                                      "input_config": {"requests": {"requests": [
                                          {"request": self.request(j), "metadata": {"key": j.key}}
                                          for j in chunk]}}}}
                    url = f"{GEMINI_URL}/models/{self.model}:batchGenerateContent"
                    resp = self._post(client, url, body)
                    name = resp.get("name") or (resp.get("metadata") or {}).get("name")
                    if state:
                        state.write_text(json.dumps({"name": name, "keys": [j.key for j in chunk]}))
                    log.info("Gemini batch %s: %d requests", name, len(chunk))
                results.update(self._wait(client, name))
        return results

    def _wait(self, client: httpx.Client, name: str) -> dict[str, Result]:
        while True:
            r = client.get(f"{GEMINI_URL}/{name}", headers={"x-goog-api-key": self.key})
            r.raise_for_status()
            obj = r.json()
            state = _find(obj, "state") or ""
            if state.endswith("SUCCEEDED") or obj.get("done"):
                break
            if any(state.endswith(s) for s in ("FAILED", "CANCELLED", "EXPIRED")):
                raise BackendError(f"Gemini batch {name} ended {state}: {obj.get('error')}")
            time.sleep(30)
        out: dict[str, Result] = {}
        for item in _inlined(obj):
            key = ((item.get("metadata") or {}).get("key")) or item.get("key")
            if "response" in item:
                text, usage = self._text(item["response"])
                out[key] = Result(text, usage)
            else:
                out[key] = Result("", error=json.dumps(item.get("error"))[:300])
        return out


def _find(obj, key: str):
    """The first value of `key` anywhere in a JSON object."""
    if isinstance(obj, dict):
        if key in obj and isinstance(obj[key], str):
            return obj[key]
        for v in obj.values():
            if (r := _find(v, key)) is not None:
                return r
    elif isinstance(obj, list):
        for v in obj:
            if (r := _find(v, key)) is not None:
                return r
    return None


def _inlined(obj) -> list[dict]:
    """Every inlined response item in a finished batch, wherever the API nests them."""
    found: list[dict] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("inlinedResponses", "inlined_responses") and isinstance(v, list):
                found += [x for x in v if isinstance(x, dict)]
            else:
                found += _inlined(v)
    elif isinstance(obj, list):
        for v in obj:
            found += _inlined(v)
    return found


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------

def _claude_content(job: Job) -> list[dict]:
    return [{"type": "text", "text": v} if k == "text" else
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": v}}
            for k, v in job.parts]


def _safe_id(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", key)[:64]


class ClaudeBatch:
    """Claude through the Message Batches API (50% off), billed to ANTHROPIC_API_KEY."""

    def __init__(self, model: str = "claude-opus-5-5", effort: str = "medium",
                 state_dir: Path | None = None, max_tokens: int = 16000) -> None:
        import anthropic
        self.client = anthropic.Anthropic()
        self.model, self.effort = model, effort
        self.state_dir, self.max_tokens = state_dir, max_tokens

    def params(self, job: Job) -> dict:
        return {"model": self.model, "max_tokens": self.max_tokens, "system": job.system,
                "output_config": {"effort": self.effort},
                "messages": [{"role": "user", "content": _claude_content(job)}]}

    def run(self, jobs: list[Job]) -> dict[str, Result]:
        if not jobs:
            return {}
        ids = {_safe_id(j.key): j.key for j in jobs}
        if len(ids) != len(jobs):
            raise BackendError("job keys collide after sanitizing")
        state = self.state_dir / "_claude_batch.json" if self.state_dir else None
        if state and state.exists():
            batch_id = json.loads(state.read_text())["id"]
        else:
            batch = self.client.messages.batches.create(requests=[
                {"custom_id": cid, "params": self.params(next(j for j in jobs if j.key == key))}
                for cid, key in ids.items()])
            batch_id = batch.id
            if state:
                state.write_text(json.dumps({"id": batch_id}))
            log.info("Claude batch %s: %d requests", batch_id, len(jobs))
        while self.client.messages.batches.retrieve(batch_id).processing_status != "ended":
            time.sleep(30)
        out: dict[str, Result] = {}
        for r in self.client.messages.batches.results(batch_id):
            key = ids.get(r.custom_id, r.custom_id)
            if r.result.type == "succeeded":
                msg = r.result.message
                text = "".join(b.text for b in msg.content if b.type == "text")
                out[key] = Result(text, msg.usage.to_dict())
            else:
                out[key] = Result("", error=r.result.type)
        if state:
            state.unlink()
        return out


class ClaudeCLI:
    """Claude through a local `claude -p` (the Claude subscription; rate-limited, no money)."""

    def __init__(self, model: str = "opus", effort: str | None = None, workers: int = 3) -> None:
        self.model, self.effort, self.workers = model, effort, workers

    def _one(self, job: Job) -> tuple[str, Result]:
        msg = {"type": "user", "message": {"role": "user", "content": _claude_content(job)}}
        cmd = ["claude", "-p", "--model", self.model, "--system-prompt", job.system,
               "--tools", "", "--setting-sources", "", "--strict-mcp-config",
               "--no-session-persistence", "--verbose",
               "--input-format", "stream-json", "--output-format", "stream-json"]
        if self.effort:
            cmd += ["--effort", self.effort]
        with tempfile.TemporaryDirectory() as cwd:
            proc = subprocess.run(cmd, input=json.dumps(msg) + "\n", capture_output=True,
                                  text=True, cwd=cwd, timeout=1800)
        result = None
        for line in proc.stdout.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "result":
                result = ev
        if result is None or result.get("is_error"):
            return job.key, Result("", error=(proc.stderr or proc.stdout)[-300:])
        return job.key, Result(result.get("result") or "", result.get("usage") or {})

    def run(self, jobs: list[Job]) -> dict[str, Result]:
        with ThreadPoolExecutor(self.workers) as ex:
            return dict(ex.map(self._one, jobs))
