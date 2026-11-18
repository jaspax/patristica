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
    lines, agreed, readings = stages.disputed(_run(tmp_path), "p1")
    assert [a is None for a in agreed] == [False, True, False]
    assert readings[1] == ["ὁ λόγος καὶ", "ὁ λόγος καὶ", "ὁ λόγος καὶ", "ὁ νόμος καὶ"]


class _Fake:
    """A backend that answers every synthesis job with fixed lines."""

    def __init__(self, answer: dict) -> None:
        self.answer, self.jobs = answer, []

    def run(self, jobs):
        self.jobs += jobs
        return {j.key: backends.Result(json.dumps(self.answer), {"input_tokens": 10}) for j in jobs}


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
    assert backends.Gemini._text(items[0]["response"])[0] == "ok"


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
