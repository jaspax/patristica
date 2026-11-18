"""Model backends for the OCR stages: Gemini (direct or batch) and Claude (batch API or claude -p).

A Job is one request: a system prompt, text and images (base64 JPEG) in order,
and whether the answer is JSON. Every backend's run(jobs) returns
{key: Result}; a stage calls ack() once it has written its outputs.

Batch backends cost 50% of the direct price and finish within 24 hours
(usually much sooner). They keep a checkpoint under the stage directory
(`_batch_<provider>.json`): each submitted batch with the identity of its
requests (job key + hash of the request), and every result as soon as it is
fetched. A rerun reuses a result only for the identical request, waits for a
batch still running, and submits a new batch for requests that failed or were
never sent. The checkpoint is removed only by ack(), after the stage has saved
its pages, so an interrupted run never pays twice for the same request.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

import httpx

from patristica.embedders import env_key

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


def _digest(obj: dict) -> str:
    blob = json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(blob).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Batch checkpoint
# ---------------------------------------------------------------------------

class Checkpoint:
    """Submitted batches and fetched results, bound to request identities."""

    def __init__(self, path: Path | None) -> None:
        self.path = path
        self.data: dict = {"batches": [], "results": {}}
        if path and path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))

    def save(self) -> None:
        if self.path:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)

    def result(self, key: str, digest: str) -> Result | None:
        """A fetched, successful result for exactly this request."""
        r = self.data["results"].get(key)
        if r and r["digest"] == digest and not r["error"]:
            return Result(r["text"], r["usage"], None)
        return None

    def pending_batches(self, wanted: dict[str, str]) -> list[dict]:
        """Unfetched batches that hold at least one wanted request, identical."""
        return [b for b in self.data["batches"] if not b.get("fetched")
                and any(wanted.get(k) == d for k, d in b["requests"].items())]

    def add_batch(self, batch_id: str, requests: dict[str, str]) -> dict:
        b = {"id": batch_id, "requests": requests, "fetched": False}
        self.data["batches"].append(b)
        self.save()
        return b

    def store(self, batch: dict, results: dict[str, Result]) -> None:
        for key, r in results.items():
            if key in batch["requests"]:
                self.data["results"][key] = {"digest": batch["requests"][key], **asdict(r)}
        batch["fetched"] = True
        self.save()

    def clear(self) -> None:
        if self.path and self.path.exists():
            self.path.unlink()
        self.data = {"batches": [], "results": {}}


class _Batched:
    """Shared batch logic; a subclass supplies request(), submit() and fetch()."""

    provider = ""

    def __init__(self, state_dir: Path | None) -> None:
        self.ckpt = Checkpoint(state_dir / f"_batch_{self.provider}.json" if state_dir else None)

    def request(self, job: Job) -> dict:
        raise NotImplementedError

    def submit(self, jobs: list[Job]) -> list[str]:
        raise NotImplementedError

    def fetch(self, batch_id: str, keys: list[str]) -> dict[str, Result]:
        raise NotImplementedError

    def run(self, jobs: list[Job]) -> dict[str, Result]:
        if not jobs:
            return {}
        wanted = {j.key: _digest(self.request(j)) for j in jobs}
        out: dict[str, Result] = {}
        for j in jobs:
            if (r := self.ckpt.result(j.key, wanted[j.key])) is not None:
                out[j.key] = r
        for b in self.ckpt.pending_batches({k: d for k, d in wanted.items() if k not in out}):
            log.info("%s batch %s: resuming", self.provider, b["id"])
            self.ckpt.store(b, self.fetch(b["id"], list(b["requests"])))
            for k in b["requests"]:
                if k in wanted and (r := self.ckpt.result(k, wanted[k])) is not None:
                    out[k] = r
        todo = [j for j in jobs if j.key not in out]
        if todo:
            for batch_id, chunk in zip(self.submit(todo), self._chunks(todo)):
                b = self.ckpt.add_batch(batch_id, {j.key: wanted[j.key] for j in chunk})
                log.info("%s batch %s: %d requests", self.provider, batch_id, len(chunk))
                fetched = self.fetch(batch_id, [j.key for j in chunk])
                self.ckpt.store(b, fetched)
                out.update({k: fetched[k] for k in b["requests"] if k in fetched})
        return {j.key: out.get(j.key, Result("", error="no result")) for j in jobs}

    def _chunks(self, jobs: list[Job]) -> list[list[Job]]:
        return [jobs]

    def ack(self) -> None:
        """The stage has saved its outputs: drop the checkpoint."""
        self.ckpt.clear()


# ---------------------------------------------------------------------------
# Gemini
# ---------------------------------------------------------------------------

class _GeminiBase:
    def __init__(self, model: str, thinking: str = "low") -> None:
        self.model, self.thinking = model, thinking
        try:
            self.key = env_key("GEMINI_API_KEY")
        except KeyError as e:
            raise BackendError(str(e)) from None

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


class GeminiDirect(_GeminiBase):
    """Gemini generateContent, one synchronous call per job."""

    def __init__(self, model: str, thinking: str = "low", workers: int = 4) -> None:
        super().__init__(model, thinking)
        self.workers = workers

    def run(self, jobs: list[Job]) -> dict[str, Result]:
        url = f"{GEMINI_URL}/models/{self.model}:generateContent"
        with httpx.Client(timeout=600) as client:
            def one(job: Job) -> tuple[str, Result]:
                try:
                    text, usage = self._text(self._post(client, url, self.request(job)))
                    return job.key, Result(text, usage)
                except BackendError as e:
                    return job.key, Result("", error=str(e))
            with ThreadPoolExecutor(self.workers) as ex:
                return dict(ex.map(one, jobs))

    def ack(self) -> None:
        pass


class GeminiBatch(_GeminiBase, _Batched):
    """Gemini Batch API with inline requests (50% off)."""

    provider = "gemini"

    def __init__(self, model: str, thinking: str = "low", state_dir: Path | None = None,
                 poll: float = 30) -> None:
        _GeminiBase.__init__(self, model, thinking)
        _Batched.__init__(self, state_dir)
        self.poll = poll

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

    def submit(self, jobs: list[Job]) -> list[str]:
        names = []
        with httpx.Client(timeout=600) as client:
            for n, chunk in enumerate(self._chunks(jobs)):
                body = {"batch": {"display_name": f"patristica-ocr-{int(time.time())}-{n}",
                                  "input_config": {"requests": {"requests": [
                                      {"request": self.request(j), "metadata": {"key": j.key}}
                                      for j in chunk]}}}}
                url = f"{GEMINI_URL}/models/{self.model}:batchGenerateContent"
                resp = self._post(client, url, body)
                names.append(resp.get("name") or (resp.get("metadata") or {}).get("name"))
        return names

    def fetch(self, batch_id: str, keys: list[str]) -> dict[str, Result]:
        with httpx.Client(timeout=600) as client:
            while True:
                r = client.get(f"{GEMINI_URL}/{batch_id}", headers={"x-goog-api-key": self.key})
                r.raise_for_status()
                obj = r.json()
                state = _find(obj, "state") or ""
                if state.endswith("SUCCEEDED") or obj.get("done"):
                    break
                if any(state.endswith(s) for s in ("FAILED", "CANCELLED", "EXPIRED")):
                    return {k: Result("", error=f"batch {state}") for k in keys}
                time.sleep(self.poll)
        out: dict[str, Result] = {}
        for n, item in enumerate(_inlined(obj)):
            # The key is echoed in metadata; fall back to the request order.
            key = (item.get("metadata") or {}).get("key") or (keys[n] if n < len(keys) else None)
            if key is None:
                continue
            if "response" in item:
                text, usage = self._text(item["response"])
                out[key] = Result(text, usage)
            else:
                out[key] = Result("", error=json.dumps(item.get("error"))[:300])
        return out


def Gemini(model: str, thinking: str = "low", batch: bool = True,  # noqa: N802
           state_dir: Path | None = None):
    """The Gemini backend: batch (default) or direct."""
    return GeminiBatch(model, thinking, state_dir) if batch else GeminiDirect(model, thinking)


def _find(obj, key: str):
    """The first string value of `key` anywhere in a JSON object."""
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


class ClaudeBatch(_Batched):
    """Claude through the Message Batches API (50% off), billed to ANTHROPIC_API_KEY."""

    provider = "claude"

    def __init__(self, model: str = "claude-opus-5-5", effort: str = "medium",
                 state_dir: Path | None = None, max_tokens: int = 16000, poll: float = 30) -> None:
        import anthropic
        try:
            key = env_key("ANTHROPIC_API_KEY")
        except KeyError as e:
            raise BackendError(str(e)) from None
        self.client = anthropic.Anthropic(api_key=key)
        self.model, self.effort = model, effort
        self.max_tokens, self.poll = max_tokens, poll
        super().__init__(state_dir)

    def request(self, job: Job) -> dict:
        return {"model": self.model, "max_tokens": self.max_tokens, "system": job.system,
                "output_config": {"effort": self.effort},
                "messages": [{"role": "user", "content": _claude_content(job)}]}

    params = request  # the Messages API name for it

    def submit(self, jobs: list[Job]) -> list[str]:
        ids = [_safe_id(j.key) for j in jobs]
        if len(set(ids)) != len(ids):
            raise BackendError("job keys collide after sanitizing")
        batch = self.client.messages.batches.create(requests=[
            {"custom_id": cid, "params": self.request(j)} for cid, j in zip(ids, jobs)])
        return [batch.id]

    def fetch(self, batch_id: str, keys: list[str]) -> dict[str, Result]:
        while self.client.messages.batches.retrieve(batch_id).processing_status != "ended":
            time.sleep(self.poll)
        by_id = {_safe_id(k): k for k in keys}
        out: dict[str, Result] = {}
        for r in self.client.messages.batches.results(batch_id):
            key = by_id.get(r.custom_id)
            if key is None:
                continue
            if r.result.type == "succeeded":
                msg = r.result.message
                text = "".join(b.text for b in msg.content if b.type == "text")
                out[key] = Result(text, msg.usage.to_dict())
            else:
                out[key] = Result("", error=r.result.type)
        return out


class ClaudeCLI:
    """Claude through a local `claude -p` (the Claude subscription; rate-limited, no money).

    Each Result's usage carries the subscription's usage windows after the call
    (`limits`: five_hour / seven_day utilization), so a run can report how
    much of the windows it took.
    """

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
        result, limits = None, {}
        for line in proc.stdout.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "result":
                result = ev
            elif ev.get("type") == "rate_limit_event":
                windows = (ev.get("rate_limit_info") or {}).get("unifiedWindows") or {}
                limits.update({w: v.get("utilization") for w, v in windows.items()})
        if result is None or result.get("is_error"):
            return job.key, Result("", error=(proc.stderr or proc.stdout)[-300:])
        return job.key, Result(result.get("result") or "", {**(result.get("usage") or {}),
                                                             "limits": limits})

    def run(self, jobs: list[Job]) -> dict[str, Result]:
        with ThreadPoolExecutor(self.workers) as ex:
            return dict(ex.map(self._one, jobs))

    def ack(self) -> None:
        pass
