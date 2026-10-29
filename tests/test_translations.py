"""Tests for the translation store (patristica.translations) and scripts.translate."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from patristica import translations as tr

PROV = tr.Provenance(model="m", prompt_version="v1", date="2026-10-12", script="test")
NEW = tr.Provenance(model="m", prompt_version="v2", date="2026-10-13", script="test")


def chunk(cid: str, text: str, lang: str = "syc") -> dict:
    return {"chunk_id": f"w#{cid}", "language": lang, "text": text}


def row(cid: str, text: str, out: str, prov: tr.Provenance = PROV) -> tr.ChunkTranslation:
    return tr.ChunkTranslation(chunk_id=f"w#{cid}", source_sha256=tr.text_sha(text),
                               provenance=prov.key, group_size=1, text=out)


def test_save_orders_by_chunks_drops_stale_rows_and_unused_runs(tmp_path: Path):
    work = tr.WorkTranslations(work_id="w", source_path="a/w.json", source_language="syc")
    work.put(row("2", "b", "B"), PROV)
    work.put(row("1", "a", "A old"), PROV)
    work.put(row("1", "a", "A", NEW), NEW)   # re-translation replaces the old row
    work.put(row("3", "gone", "X"), PROV)    # chunk no longer exists
    chunks = [chunk("1", "a"), chunk("2", "b changed")]

    path = tr.save(tmp_path, work, chunks)
    assert path == tmp_path / "a/w.json"
    saved = tr.load(tmp_path, "a/w.json")
    assert [(t.chunk_id, t.text) for t in saved.translations] == [("w#1", "A")]
    assert list(saved.provenance) == [NEW.key]  # PROV is no longer used
    assert saved.fresh("w#1", "a").text == "A"
    assert saved.fresh("w#1", "a edited") is None

    mtime = path.stat().st_mtime_ns
    tr.save(tmp_path, saved, chunks)          # unchanged content: file not rewritten
    assert path.stat().st_mtime_ns == mtime

    tr.save(tmp_path, saved, [chunk("1", "a edited")])
    assert not path.exists()                  # nothing fresh left: file removed


def test_put_rejects_mismatched_provenance():
    work = tr.WorkTranslations(work_id="w", source_path="w.json", source_language="syc")
    with pytest.raises(ValueError):
        work.put(row("1", "a", "A", PROV), NEW)


def test_fresh_translations_filters_by_hash_and_model(tmp_path: Path):
    other = tr.Provenance(model="other", prompt_version="v1", date="2026-10-12", script="t")
    work = tr.WorkTranslations(work_id="w", source_path="w.json", source_language="syc")
    work.put(row("1", "a", "A"), PROV)
    work.put(row("2", "b", "B", other), other)
    chunks = [chunk("1", "a"), chunk("2", "b"), chunk("3", "c")]
    tr.save(tmp_path, work, chunks)
    assert tr.fresh_translations(chunks, tmp_path) == {"w#1": "A", "w#2": "B"}
    assert tr.fresh_translations(chunks, tmp_path, model="m") == {"w#1": "A"}
    assert tr.fresh_translations([chunk("1", "changed")], tmp_path) == {}


# --- scripts.translate ------------------------------------------------------------

def test_make_groups_split_by_size_count_and_language(monkeypatch):
    from scripts import translate

    monkeypatch.setattr(translate, "BULK_MAX_CHARS", 10)
    monkeypatch.setattr(translate, "BULK_MAX_ITEMS", 3)
    chunks = [chunk(str(i), "xxxx") for i in range(4)]
    chunks += [chunk("4", "y", "eng"), chunk("5", "z" * 50)]
    groups = translate.make_groups(chunks)
    assert [[c["chunk_id"] for c in g] for g in groups] == [
        ["w#0", "w#1"], ["w#2", "w#3"], ["w#4"], ["w#5"]]


def write_corpus(root: Path, works: dict[str, tuple[str, list[dict]]]) -> Path:
    """works: work_id → (license, chunks). Returns the normalized dir."""
    norm = root / "normalized"
    lines = []
    for wid, (lic, chunks) in works.items():
        path = f"src/{wid}.json"
        (norm / path).parent.mkdir(parents=True, exist_ok=True)
        (norm / path).write_text(json.dumps(
            [{**c, "chunk_id": c["chunk_id"].replace("w#", f"{wid}#")} for c in chunks]))
        lines.append(json.dumps({"path": path, "work": {
            "work_id": wid, "language": "syc", "license": lic}}))
    (norm / "_works.jsonl").write_text("\n".join(lines) + "\n")
    return norm


class FakeClients:
    def __init__(self) -> None:
        self.requests: list[str] = []

    def call(self, name, system, user, schema, effort=None):
        from scripts.translate import BulkItem, BulkTranslation

        self.requests.append(user)
        n = user.count("\n\n") + 1
        items = [BulkItem(n=i, translation=f"EN {i}") for i in range(1, n + 1)]
        return BulkTranslation(items=items), {"model": "sol", "input": 100, "output": 50}


def test_run_translates_reuses_and_is_idempotent(tmp_path: Path, monkeypatch):
    from scripts import translate

    fake = FakeClients()
    monkeypatch.setattr(translate, "Clients", lambda: fake)
    store = tmp_path / "translations"
    norm = write_corpus(tmp_path, {
        "a": ("public_domain", [chunk("1", "ܫܠܡܐ"), chunk("2", "ܐܠܗܐ"),
                                chunk("3", "Title", "eng"), chunk("4", " ")]),
        "b": ("public_domain", [chunk("1", "ܫܠܡܐ")]),   # same text as a#1
        "h": ("unknown", [chunk("1", "ܚܘܕܪܐ")]),        # kept out of the index
    })
    # b#1 was translated before; a#1 has the same text, so it is reused.
    b = tr.WorkTranslations(work_id="b", source_path="src/b.json", source_language="syc")
    b.put(tr.ChunkTranslation(chunk_id="b#1", source_sha256=tr.text_sha("ܫܠܡܐ"),
                              provenance=PROV.key, group_size=1, text="peace"), PROV)
    tr.save(store, b, [{"chunk_id": "b#1", "text": "ܫܠܡܐ"}])

    args = dict(input_dir=norm, store_dir=store, langs=["syc"], work_prefixes=[], workers=2,
                max_requests=None, max_cost=None, include_unpublishable=False)
    translate.run(dry_run=True, **args)
    assert fake.requests == [] and not (store / "src/a.json").exists()

    translate.run(dry_run=False, **args)
    assert fake.requests == ["[1]\nܐܠܗܐ"]   # only a#2: a#1 reused, eng/blank/unknown skipped
    a = tr.load(store, "src/a.json")
    assert [(t.chunk_id, t.text) for t in a.translations] == [("a#1", "peace"), ("a#2", "EN 1")]
    assert a.provenance[a.translations[0].provenance] == PROV
    assert a.provenance[a.translations[1].provenance].model == "gpt-6.1-sol"
    assert not (store / "src/h.json").exists()

    translate.run(dry_run=False, **args)    # nothing left to do
    assert len(fake.requests) == 1


def test_run_sends_and_hashes_the_text_without_editorial_material(tmp_path: Path, monkeypatch):
    """Editorial spans (#236) are not translated: the request and the stored hash
    cover the source text, and a wholly editorial unit is skipped."""
    from scripts import translate

    fake = FakeClients()
    monkeypatch.setattr(translate, "Clients", lambda: fake)
    store = tmp_path / "translations"
    marked = {**chunk("1", "ܫܠܡܐ […] ܐܠܗܐ"), "editorial": [[5, 8, "lacuna"]]}
    title = {**chunk("2", "ܡܐܡܪܐ"), "editorial": [[0, 5, "title"]]}
    norm = write_corpus(tmp_path, {"a": ("public_domain", [marked, title])})
    args = dict(input_dir=norm, store_dir=store, langs=["syc"], work_prefixes=[], workers=1,
                max_requests=None, max_cost=None, include_unpublishable=False)
    translate.run(dry_run=False, **args)
    assert fake.requests == ["[1]\nܫܠܡܐ ܐܠܗܐ"]
    (t,) = tr.load(store, "src/a.json").translations
    assert t.chunk_id == "a#1" and t.source_sha256 == tr.text_sha("ܫܠܡܐ ܐܠܗܐ")

    translate.run(dry_run=False, **args)    # fresh against the source text: nothing to do
    assert len(fake.requests) == 1
    chunks = json.loads((norm / "src/a.json").read_text())
    assert tr.fresh_translations(chunks, store) == {"a#1": "EN 1"}


def test_run_stops_at_max_cost(tmp_path: Path, monkeypatch):
    from scripts import translate

    fake = FakeClients()
    monkeypatch.setattr(translate, "Clients", lambda: fake)
    monkeypatch.setattr(translate, "BULK_MAX_ITEMS", 1)
    norm = write_corpus(tmp_path, {"a": ("public_domain",
                                         [chunk(str(i), f"ܐ{i}") for i in range(5)])})
    translate.run(input_dir=norm, store_dir=tmp_path / "t", langs=["syc"], work_prefixes=[],
                  workers=1, max_requests=None, max_cost=0.0001, dry_run=False,
                  include_unpublishable=False)
    assert len(fake.requests) == 1
    assert len(tr.load(tmp_path / "t", "src/a.json").translations) == 1


def test_run_with_opus_records_the_model_that_answered(tmp_path: Path, monkeypatch):
    from scripts import translate

    class Served(FakeClients):
        def call(self, name, system, user, schema, effort=None):
            out, usage = super().call(name, system, user, schema, effort)
            self.names = [*getattr(self, "names", []), name]
            # first request answered by Opus, second by a server-side fallback model
            served = "claude-opus-5-5" if len(self.requests) == 1 else "claude-fallback-x"
            return out, {**usage, "model": name, "served_by": served}

    fake = Served()
    monkeypatch.setattr(translate, "Clients", lambda: fake)
    monkeypatch.setattr(translate, "BULK_MAX_ITEMS", 1)
    norm = write_corpus(tmp_path, {"a": ("public_domain", [chunk("1", "ܐ"), chunk("2", "ܒ")])})
    translate.run(input_dir=norm, store_dir=tmp_path / "t", langs=["syc"], work_prefixes=[],
                  workers=1, max_requests=None, max_cost=None, dry_run=False,
                  include_unpublishable=False, model="opus")
    assert fake.names == ["opus", "opus"]
    a = tr.load(tmp_path / "t", "src/a.json")
    assert {a.provenance[t.provenance].model for t in a.translations} == {
        "claude-opus-5-5", "claude-fallback-x"}


def test_clients_are_lazy_and_keep_their_dispatch_methods():
    from scripts.embed_eval import translate as et

    clients = et.Clients()
    # The lazily created SDK client must not shadow the _anthropic/_openai methods.
    assert callable(clients._anthropic) and callable(clients._openai)
    assert clients._anthropic_client is None and clients._http is None


# --- local Claude backend (#417) ------------------------------------------------

def stream(*events: dict) -> str:
    return "\n".join(json.dumps(e) for e in events) + "\n"


RATE_EVENT = {"type": "rate_limit_event", "rate_limit_info": {
    "status": "allowed", "isUsingOverage": False, "unifiedWindows": {
        "five_hour": {"utilization": 0.09, "resetsAt": 1793311200, "status": "allowed"},
        "seven_day": {"utilization": 0.52, "resetsAt": 1793433600, "status": "allowed"}}}}
RESULT_EVENT = {"type": "result", "subtype": "success", "is_error": False,
                "structured_output": {"items": [{"n": 1, "translation": "Peace."}]},
                "usage": {"input_tokens": 2, "cache_creation_input_tokens": 1000,
                          "cache_read_input_tokens": 10, "output_tokens": 72},
                "modelUsage": {"claude-opus-5-5": {}}}


def test_parse_claude_stream_returns_the_output_tokens_model_and_usage_windows():
    from scripts.embed_eval.translate import cost, parse_claude_stream
    from scripts.translate import BulkTranslation

    out, usage = parse_claude_stream(
        "local-opus", stream({"type": "system", "subtype": "init"}, RATE_EVENT, RESULT_EVENT)
        + "not json\n", 0, "", BulkTranslation)
    assert out.items[0].translation == "Peace."
    assert usage["input"] == 1012 and usage["output"] == 72
    assert usage["served_by"] == "claude-opus-5-5"
    assert usage["limits"]["five_hour"] == {"utilization": 0.09, "resets_at": 1793311200,
                                            "status": "allowed"}
    assert cost([usage]) == 0   # the subscription has no price per token


def test_parse_claude_stream_raises_on_an_error_or_a_missing_result():
    from scripts.embed_eval.translate import parse_claude_stream
    from scripts.translate import BulkTranslation

    failed = {**RESULT_EVENT, "is_error": True, "subtype": "error_during_execution",
              "result": "usage limit reached", "structured_output": None}
    with pytest.raises(RuntimeError, match="usage limit reached"):
        parse_claude_stream("local-opus", stream(RATE_EVENT, failed), 1, "", BulkTranslation)
    with pytest.raises(RuntimeError, match="without a result"):
        parse_claude_stream("local-opus", "", 1, "not logged in", BulkTranslation)


def test_claude_cli_maps_the_request_onto_isolated_claude_arguments(monkeypatch):
    import subprocess

    from scripts.embed_eval import translate as et
    from scripts.translate import BulkTranslation

    seen = {}

    def fake_run(cmd, input, capture_output, text, cwd, timeout):
        seen.update(cmd=cmd, input=input, cwd=cwd)
        return subprocess.CompletedProcess(cmd, 0, stream(RATE_EVENT, RESULT_EVENT), "")

    monkeypatch.setattr(et.subprocess, "run", fake_run)
    out, usage = et.Clients().call("local-opus", "SYSTEM", "[1]\nܫܠܡܐ", BulkTranslation,
                                   effort="low")
    cmd = seen["cmd"]
    arg = {cmd[i]: cmd[i + 1] for i in range(1, len(cmd) - 1) if cmd[i].startswith("--")}
    assert cmd[:2] == ["claude", "-p"] and seen["input"] == "[1]\nܫܠܡܐ"
    assert arg["--model"] == "claude-opus-5-5" and arg["--system-prompt"] == "SYSTEM"
    assert json.loads(arg["--json-schema"]) == BulkTranslation.model_json_schema()
    assert arg["--tools"] == "" and arg["--setting-sources"] == "" and arg["--effort"] == "low"
    assert "--strict-mcp-config" in cmd and "--no-session-persistence" in cmd
    assert arg["--output-format"] == "stream-json"
    assert not Path(seen["cwd"]).exists()   # an empty directory, removed afterwards
    assert usage["model"] == "local-opus" and usage["limits"]


def test_limits_report_uses_the_latest_usage_windows():
    from scripts.embed_eval.translate import limits_report

    older = {"limits": {"five_hour": {"utilization": 0.01, "resets_at": 0}}}
    latest = {"limits": {"five_hour": {"utilization": 0.09, "resets_at": 1793311200},
                         "seven_day": {"utilization": 0.52, "resets_at": 1793433600},
                         "overage": True}}
    assert limits_report([older, latest, {"model": "sol"}]) == (
        "5-hour 9% (resets Thu 22:00 UTC), 7-day 52% (resets Sat 08:00 UTC), "
        "using extra usage")
    assert limits_report([{"model": "sol"}]) is None


def test_run_logs_subscription_usage_and_never_stops_on_it(tmp_path: Path, monkeypatch,
                                                           caplog):
    from scripts import translate

    class Local(FakeClients):
        def call(self, name, system, user, schema, effort=None):
            out, usage = super().call(name, system, user, schema, effort)
            full = {"five_hour": {"utilization": 1.0, "resets_at": 1793311200}}
            return out, {**usage, "model": name, "served_by": "claude-opus-5-5",
                         "limits": full}

    fake = Local()
    monkeypatch.setattr(translate, "Clients", lambda: fake)
    monkeypatch.setattr(translate, "BULK_MAX_ITEMS", 1)
    norm = write_corpus(tmp_path, {"a": ("public_domain", [chunk("1", "ܐ"), chunk("2", "ܒ")])})
    with caplog.at_level("INFO"):
        translate.run(input_dir=norm, store_dir=tmp_path / "t", langs=["syc"],
                      work_prefixes=[], workers=1, max_requests=None, max_cost=None,
                      dry_run=False, include_unpublishable=False, model="local-opus")
    assert len(fake.requests) == 2   # usage is reported, not enforced
    assert "subscription usage 5-hour 100% (resets Thu 22:00 UTC)" in caplog.text
