"""OCR pipeline (#720): vote, repairs, disputed lines, images, backends, cost."""

import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from scripts.ocr import backends, flags, stages
from scripts.ocr.__main__ import main
from scripts.ocr.images import n_strips, stack, strips
from scripts.ocr.text import pair_lines, same_reading
from scripts.ocr.vote import capitalize_theos, vote

ALTO = """<?xml version="1.0"?>
<alto xmlns="http://www.loc.gov/standards/alto/ns-v4#"><Layout><Page><PrintSpace>
{lines}
</PrintSpace></Page></Layout></alto>"""


def _alto(lines: list[str]) -> str:
    out = []
    for i, ln in enumerate(lines):
        words = "".join(f'<String CONTENT="{w}" WC="0.9"/>' for w in ln.split())
        out.append(f'<TextLine HPOS="10" VPOS="{10 + 40 * i}" WIDTH="300" HEIGHT="30">'
                   f'{words}</TextLine>')
    return ALTO.format(lines="\n".join(out))


def test_vote_majority_keeps_lines_and_ties_go_to_primary() -> None:
    primary = "ὁ λόγος ἦν\nπρὸς τὸν θεόν"
    others = ["ὁ λόγος ἦν πρὸς τὸν Θεόν", "ὁ λόγος ἦν πρὸς τὸν Θεόν", "ὁ νόμος ἦν πρὸς τὸν Θεόν"]
    assert vote(primary, others) == "ὁ λόγος ἦν\nπρὸς τὸν Θεόν"
    # One dissenter against the primary: the primary stays.
    assert vote("ὁ λόγος", ["ὁ νόμος"]) == "ὁ λόγος"


def test_vote_compares_by_convention_fold() -> None:
    # Migne's space before the comma and the plain apostrophe are the same reading
    # (the output is normalized: no space before punctuation).
    assert vote("δι’ αὐτοῦ ,", ["δι' αὐτοῦ,", "δι' αὐτοῦ,"]) == "δι’ αὐτοῦ,"


def test_capitalize_theos() -> None:
    assert capitalize_theos("ὁ θεὸς καὶ «θεοῦ θεοί") == "ὁ Θεὸς καὶ «Θεοῦ θεοί"


def test_pair_lines_and_same_reading() -> None:
    assert pair_lines(["ἐν ἀρχῇ ἦν", "ὁ λόγος καὶ"], ["ὁ λόγος καὶ"]) == [(0, None), (1, 0)]
    assert same_reading("φωτὸς ,", "φωτός,")
    assert not same_reading("τὸ", "τὰ")


def _run(tmp_path: Path, page: str = "p1") -> stages.Run:
    (tmp_path / "img").mkdir()
    Image.new("RGB", (400, 200), "white").save(tmp_path / "img" / f"{page}.jpg")
    (tmp_path / "out" / "kraken").mkdir(parents=True)
    (tmp_path / "out" / "kraken" / f"{page}.xml").write_text(
        _alto(["ἐν ἀρχῇ ἦν", "ὁ λόγος καὶ", "ὁ λόγος ἦν"]), encoding="utf-8")
    for stage, text in {"kgc": "ἐν ἀρχῇ ἦν\nὁ λόγος καὶ\nὁ λόγος ἦν",
                        "opus_page": "ἐν ἀρχῇ ἦν\nὁ λόγος καὶ\nὁ λόγος ἦν",
                        "gemini_page": "ἐν ἀρχῇ ἦν\nὁ νόμος καὶ\nὁ λόγος ἦν"}.items():
        (tmp_path / "out" / stage).mkdir()
        (tmp_path / "out" / stage / f"{page}.txt").write_text(text, encoding="utf-8")
    return stages.Run([page], tmp_path / "img", tmp_path / "out")


def test_disputed_lines(tmp_path: Path) -> None:
    lines, agreed, readings, missing = stages.disputed(_run(tmp_path), "p1")
    assert missing == {}
    assert [a is None for a in agreed] == [False, True, False]
    assert readings[1] == ["ὁ λόγος καὶ", "ὁ λόγος καὶ", "ὁ λόγος καὶ", "ὁ νόμος καὶ"]


class _Fake:
    """A backend that answers every synthesis job with fixed lines."""

    def __init__(self, answer: dict) -> None:
        self.answer, self.jobs = answer, []

    def run(self, jobs):
        self.jobs += jobs
        return {j.key: backends.Result(json.dumps(self.answer), {"input_tokens": 10}) for j in jobs}

    def ack(self):
        self.acked = True


def test_synth_sends_only_disputed_lines(tmp_path: Path) -> None:
    run = _run(tmp_path)
    fake = _Fake({"lines": [{"id": 1, "text": "ὁ λόγος καὶ"}]})
    stages.synth(run, "synth1", fake)
    (job,) = fake.jobs
    listing = job.parts[0][1]
    assert "Line 1:" in listing and "Line 0:" not in listing and "Line 2:" not in listing
    assert run.text("synth1", "p1").splitlines() == ["ἐν ἀρχῇ ἦν", "ὁ λόγος καὶ", "ὁ λόγος ἦν"]
    assert (run.out / "synth1" / "_usage.jsonl").exists()


def test_strips_and_stack() -> None:
    img = Image.new("L", (300, 900), 255)
    d = ImageDraw.Draw(img)
    for y in range(20, 900, 60):
        d.rectangle((10, y, 290, y + 25), fill=0)
    assert n_strips(img) == 3
    parts = strips(img, 3)
    assert len(parts) == 3 and sum(p.height for p in parts) == 900
    st = stack(img.convert("RGB"), [(0, (10, 20, 290, 45)), (1, (10, 80, 290, 105))])
    assert st.width > 280 and st.height > 50


def test_gemini_request_and_batch_parsing(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    g = backends.Gemini("gemini-3.8-flash", thinking="low")
    req = g.request(backends.Job("k", "sys", [("image", "QUJD"), ("text", "hi")], json_answer=True))
    assert req["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}
    assert req["generationConfig"]["responseMimeType"] == "application/json"
    assert req["contents"][0]["parts"][0]["inline_data"]["mime_type"] == "image/jpeg"
    finished = {"metadata": {"state": "BATCH_STATE_SUCCEEDED", "output": {"inlinedResponses": {
        "inlinedResponses": [
            {"response": {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]},
             "metadata": {"key": "a"}},
            {"error": {"code": 3}, "metadata": {"key": "b"}}]}}}}
    items = backends._inlined(finished)
    assert [i["metadata"]["key"] for i in items] == ["a", "b"]
    assert backends._GeminiBase._text(items[0]["response"])[0] == "ok"


def test_claude_batch_params(monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    c = backends.ClaudeBatch("claude-opus-5-5", effort="low")
    p = c.params(backends.Job("k", "sys", [("text", "hi"), ("image", "QUJD")]))
    assert p["output_config"] == {"effort": "low"} and p["system"] == "sys"
    assert p["messages"][0]["content"][1]["source"]["media_type"] == "image/jpeg"
    assert backends._safe_id("calfa-v2-grc_tlg.mpg#2") == "calfa-v2-grc_tlg_mpg_2"


def test_parse_json_and_drop_comments() -> None:
    assert backends.parse_json('```json\n{"lines": []}\n```') == {"lines": []}
    assert backends.drop_comments("The image contains no text.\nκαὶ") == "καὶ"


def test_flag_score_uses_fit() -> None:
    f = flags.fit()
    X = np.array([[0, 0, 0, 0, 0.0], [10, 12, 1, 1, 0.9]])
    s = flags.score(X, f)
    assert s[0] < s[1]
    assert set(f["thresholds"]) == {"r80", "r90", "r95"}


def test_cost_command(tmp_path: Path, capsys) -> None:
    d = tmp_path / "synth1"
    d.mkdir()
    (d / "p1.txt").write_text("x")
    (d / "_usage.jsonl").write_text(json.dumps(
        {"key": "p1", "usage": {"input_tokens": 1_000_000, "output_tokens": 0},
         "error": None}) + "\n")
    assert main(["cost", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "synth1" in out and "4.0000" in out and "2.0000" in out


def test_cost_prices_claude_cache_reads_separately(tmp_path: Path, capsys) -> None:
    d = tmp_path / "opus_page"
    d.mkdir()
    (d / "p1.txt").write_text("x")
    usage = {"input_tokens": 0, "cache_read_input_tokens": 1_000_000, "output_tokens": 0,
             "limits": {"five_hour": 0.10}}
    (d / "_usage.jsonl").write_text(json.dumps({"key": "p1#0", "usage": usage, "error": None})
                                    + "\n" + json.dumps({"key": "p1#1", "usage": {
                                        "input_tokens": 0, "output_tokens": 0,
                                        "limits": {"five_hour": 0.13}}, "error": None}) + "\n")
    assert main(["cost", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "0.4000" in out  # $0.40 per million cache reads, not $4
    assert "five_hour 3.0 pts" in out


class _FakeBatch(backends._Batched):
    """A batch backend whose batches answer immediately; counts submissions."""

    provider = "fake"

    def __init__(self, state_dir, fail=()):
        super().__init__(state_dir)
        self.submitted, self.fail = [], set(fail)

    def request(self, job):
        return {"text": job.parts[0][1]}

    def submit(self, jobs):
        self.submitted.append([j.key for j in jobs])
        self.last = jobs
        return [f"b{len(self.submitted)}"]

    def fetch(self, batch_id, keys):
        return {k: backends.Result("", error="boom") if k in self.fail
                else backends.Result(f"ok {k}") for k in keys}


def test_batch_checkpoint_reuses_identical_requests_only(tmp_path: Path) -> None:
    jobs = [backends.Job("a", "s", [("text", "1")]), backends.Job("b", "s", [("text", "2")])]
    first = _FakeBatch(tmp_path, fail={"b"})
    r = first.run(jobs)
    assert r["a"].text == "ok a" and r["b"].error == "boom"
    # A rerun before ack: "a" is reused, the failed "b" is resubmitted alone.
    second = _FakeBatch(tmp_path)
    r = second.run(jobs)
    assert second.submitted == [["b"]] and r["b"].text == "ok b"
    # A changed request is not served the old result.
    third = _FakeBatch(tmp_path)
    third.run([backends.Job("a", "s", [("text", "changed")])])
    assert third.submitted == [["a"]]
    third.ack()
    assert not (tmp_path / "_batch_fake.json").exists()


def test_lines_kraken_missed_are_recovered(tmp_path: Path) -> None:
    run = _run(tmp_path)
    for stage in ("opus_page", "gemini_page"):
        p = run.out / stage / "p1.txt"
        lines = p.read_text(encoding="utf-8").splitlines()
        lines.insert(2, "καὶ θεὸς ἦν ὁ λόγος")
        p.write_text("\n".join(lines), encoding="utf-8")
    _, _, _, missing = stages.disputed(run, "p1")
    insert, review = stages.recovered_lines(missing)
    assert insert == {1: ["καὶ θεὸς ἦν ὁ λόγος"]} and review[0]["after_line"] == 1
    stages.synth(run, "synth1", _Fake({"lines": [{"id": 1, "text": "ὁ λόγος καὶ"}]}))
    assert run.text("synth1", "p1").splitlines()[2] == "καὶ θεὸς ἦν ὁ λόγος"
    assert (run.out / "synth1" / "_review.jsonl").exists()


def test_cost_prices_each_stage_by_its_recorded_model(tmp_path: Path, capsys) -> None:
    # A Gemini model standing in as the second whole-page reader is priced as Gemini.
    d = tmp_path / "opus_page"
    d.mkdir()
    (d / "p1.txt").write_text("x")
    (d / "_model.json").write_text(json.dumps(
        {"provider": "gemini", "model": "gemini-3.1-pro-preview", "effort": "low"}))
    (d / "_usage.jsonl").write_text(json.dumps(
        {"key": "p1#0", "usage": {"promptTokenCount": 1_000_000, "candidatesTokenCount": 0},
         "error": None}) + "\n")
    assert main(["cost", "--out", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "2.0000" in out and "gemini-3.1-pro-preview low" in out


def _run_dir(tmp_path: Path) -> tuple[Path, Path]:
    pages = tmp_path / "pages.txt"
    pages.write_text("p1\n")
    (tmp_path / "img").mkdir()
    Image.new("RGB", (40, 40), "white").save(tmp_path / "img" / "p1.jpg")
    return pages, tmp_path / "out"


def test_second_reader_auto_switches_to_gemini_when_a_window_is_nearly_spent(
        tmp_path: Path, monkeypatch) -> None:
    from scripts.ocr import __main__ as cli

    pages, out = _run_dir(tmp_path)
    used = []
    monkeypatch.setattr(cli.stages, "page_reader",
                        lambda run, stage, backend, **reader: used.append(reader["model"]))
    monkeypatch.setattr(cli, "_claude", lambda args, stage: "claude-backend")
    monkeypatch.setattr(cli, "_with_windows", lambda args, run, stage, body: body())
    monkeypatch.setattr(cli, "Gemini", lambda *a, **k: "gemini-backend")
    argv = ["run", "--pages", str(pages), "--images", str(tmp_path / "img"), "--out", str(out),
            "--stage", "opus_page", "--claude", "cli", "--second-reader", "auto"]
    for windows, model in (({"five_hour": 0.40, "seven_day": 0.80}, "claude-opus-5-5"),
                           ({"five_hour": 0.30, "seven_day": 0.96}, cli.SECOND_READER_GEMINI),
                           ({}, "claude-opus-5-5")):        # unreadable: stays on Opus
        monkeypatch.setattr(cli.ClaudeCLI, "windows", staticmethod(lambda w=windows: w))
        used.clear()
        assert main(argv) == 0
        assert used == [model]


def test_second_reader_auto_stops_before_synthesis_in_a_full_window(
        tmp_path: Path, monkeypatch) -> None:
    from scripts.ocr import __main__ as cli

    pages, out = _run_dir(tmp_path)
    monkeypatch.setattr(cli.ClaudeCLI, "windows", staticmethod(lambda: {"five_hour": 0.97}))
    called = []
    monkeypatch.setattr(cli.stages, "synth", lambda *a: called.append(a))
    argv = ["run", "--pages", str(pages), "--images", str(tmp_path / "img"), "--out", str(out),
            "--stage", "synth1", "--claude", "cli", "--second-reader", "auto"]
    assert main(argv) == 3 and called == []


def test_cost_prices_a_mixed_stage_line_by_line(tmp_path: Path, capsys) -> None:
    d = tmp_path / "opus_page"
    d.mkdir()
    (d / "p1.txt").write_text("x")
    (d / "_model.json").write_text(json.dumps(
        {"provider": "gemini", "model": "gemini-3.1-pro-preview", "effort": "low"}))
    lines = [{"key": "p1#0", "usage": {"input_tokens": 1_000_000, "output_tokens": 0},
              "error": None, "provider": "claude", "model": "claude-opus-5-5"},
             {"key": "p1#1", "usage": {"promptTokenCount": 1_000_000, "candidatesTokenCount": 0},
              "error": None, "provider": "gemini", "model": "gemini-3.1-pro-preview"}]
    (d / "_usage.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines))
    assert main(["cost", "--out", str(tmp_path)]) == 0
    assert "6.0000" in capsys.readouterr().out     # $4 of Opus + $2 of Gemini 3.1 Pro
