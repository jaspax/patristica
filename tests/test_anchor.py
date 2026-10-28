"""The anchor step (#304) end to end on a small synthetic corpus, with a fake
embedder: no API calls.

The fake embedder knows a "concept" per word: ``lat17`` and ``eng17`` mean the
same, so a text's vector is the normalized sum of its concepts' random
vectors, and a translation's sentence has the vector of the Latin it renders.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from patristica import anchor_refine, anchor_store, anchoring  # noqa: E402
from patristica import embeddings as emb  # noqa: E402
from scripts import anchor  # noqa: E402
from scripts import normalize as nz  # noqa: E402

DIMS = anchor.DIMS


def concept_vec(c: int) -> np.ndarray:
    return np.random.default_rng(c).standard_normal(DIMS)


class FakeEmbedder:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, texts: list[str]) -> np.ndarray:
        self.calls.append(list(texts))
        out = []
        for t in texts:
            v = np.zeros(DIMS)
            for c in re.findall(r"(?:lat|eng)(\d+)", t):
                v += concept_vec(int(c))
            if not v.any():
                v = concept_vec(10_000 + len(t))
            out.append(v / np.linalg.norm(v))
        return np.array(out, dtype=np.float32)

    @property
    def sent(self) -> int:
        return sum(len(c) for c in self.calls)


# The original's sentences, each a list of concepts. Sentence ends where the
# Latin has them; the English joins two of them into one sentence (with a
# semicolon) and splits another one in two, so its provisional cut by size can't
# match the original's units.
SENTENCES = [list(range(i * 7, i * 7 + 7)) for i in range(16)]


def latin(sents: list[list[int]]) -> str:
    return " ".join(" ".join(f"lat{c}" for c in s) + "." for s in sents)


def english(sents: list[list[int]]) -> str:
    out = []
    for i, s in enumerate(sents):
        words = [f"eng{c}" for c in s]
        if i % 5 == 1:
            out.append(" ".join(words[:3]) + ". " + " ".join(words[3:]) + ".")
        elif i % 5 == 3:
            out.append(" ".join(words) + ";")
        else:
            out.append(" ".join(words) + ".")
    return " ".join(out)


def write_work(raw: Path, rel: str, language: str, paragraphs: list[str],
               translation_of: str | None = None) -> None:
    source_id, name = rel.split("/")[0], Path(rel).stem
    work = {"work_id": f"{source_id}/{name}", "source_id": source_id, "title": "T",
            "genre": "patristic", "language": language, "license": "public_domain"}
    if translation_of:
        work["translation_of"] = translation_of
    path = raw / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"work": work, "paragraphs": [
        {"ref": f"P.{i}", "text": t} for i, t in enumerate(paragraphs, 1)]}), encoding="utf-8")


def embed_work(norm: Path, store: Path, rel: str, fake: FakeEmbedder) -> None:
    chunks = json.loads((norm / rel).read_text(encoding="utf-8"))
    run = anchor.run_spec()
    keep = [c for c in chunks if anchor.wants_vector(c["text"])]
    vecs = fake([c["text"] for c in keep])
    emb.save(store, emb.WorkEmbeddings(
        chunks[0]["work_id"], rel, {run.key: run},
        [emb.Row(c["chunk_id"], emb.KIND_TEXT, anchor.text_sha(c["text"]), run.key)
         for c in keep], vecs.astype(np.float16)))


@pytest.fixture
def corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    monkeypatch.setattr(anchoring, "enrolled_sources", lambda: {"tr": "test"})
    d = {k: tmp_path / k for k in ("raw", "normalized", "anchors", "embeddings", "scratch")}
    write_work(d["raw"], "orig/w.json", "lat",
               [latin(SENTENCES[:8]), latin(SENTENCES[8:])])
    write_work(d["raw"], "tr/w.json", "eng",
               [english(SENTENCES[:8]), english(SENTENCES[8:])], translation_of="orig/w")
    nz.normalize_all(d["raw"], d["normalized"], anchors_dir=d["anchors"])
    return d


def run(d: dict[str, Path], fake: FakeEmbedder | None, **kw) -> dict[str, list[str]]:
    return anchor.run(d["normalized"], d["raw"], d["anchors"], d["embeddings"], d["scratch"],
                      embed=fake, **kw)


def units(d: dict[str, Path], rel: str) -> list[dict]:
    return json.loads((d["normalized"] / rel).read_text(encoding="utf-8"))


def concepts(text: str) -> tuple[int, ...]:
    return tuple(int(c) for c in re.findall(r"(?:lat|eng)(\d+)", text))


def test_the_original_needs_current_vectors(corpus) -> None:
    states = {s.candidate.work_id: s.status for s in anchor.check_works(
        corpus["normalized"], corpus["anchors"])}
    assert states == {"tr/w": anchor.MISSING}
    done = run(corpus, FakeEmbedder())
    assert done["refused"] == ["tr/w"] and done["cut"] == []
    assert not (corpus["anchors"] / "tr/w.json").exists()


def test_without_an_embedder_nothing_is_sent(corpus) -> None:
    embed_work(corpus["normalized"], corpus["embeddings"], "orig/w.json", FakeEmbedder())
    p = anchor.plan(corpus["normalized"], corpus["anchors"])
    est = anchor.estimate(p, corpus["normalized"], corpus["embeddings"], corpus["scratch"])
    assert est.works == 1 and est.first_tokens > 0 and est.rounds_tokens > 0
    with pytest.raises(anchor_refine.NeedsVectors):
        run(corpus, None)


def test_anchor_cuts_the_translation_on_the_original(corpus) -> None:
    d = corpus
    embed_work(d["normalized"], d["embeddings"], "orig/w.json", FakeEmbedder())
    fake = FakeEmbedder()
    done = run(d, fake)
    assert done["cut"] == ["tr/w"]
    cut = anchor_store.load(d["anchors"], "tr/w.json")
    assert cut is not None and cut.anchor == "orig/w"
    assert cut.method == anchoring.params_hash()
    # Each original unit has a translation unit with exactly its concepts.
    orig = {concepts(c["text"]) for c in units(d, "orig/w.json")}
    trans = [concepts(c["text"]) for c in units(d, "tr/w.json")]
    assert sum(t in orig for t in trans) >= len(orig) - 1
    # The step re-normalized the work, and normalize agrees.
    assert nz.read_work_fingerprints(d["normalized"])["tr/w.json"]["anchor"] == {
        "cuts": cut.sha}
    before = (d["normalized"] / "tr/w.json").read_bytes()
    assert nz.normalize_all(d["raw"], d["normalized"], anchors_dir=d["anchors"]) == 0
    assert (d["normalized"] / "tr/w.json").read_bytes() == before
    # Every final unit has its production vector: embed has nothing to send.
    shard = emb.load(d["embeddings"], "tr/w.json")
    have = {r.chunk_id for r in shard.rows if r.kind == emb.KIND_TEXT}
    assert have == {c["chunk_id"] for c in units(d, "tr/w.json")}
    assert all(shard.runs[r.run].script == "scripts.anchor" for r in shard.rows)
    # Current now; a second run sends nothing and changes nothing.
    assert [s.status for s in anchor.check_works(d["normalized"], d["anchors"])] == [
        anchor.CURRENT]
    again = FakeEmbedder()
    assert run(d, again)["cut"] == []
    assert again.calls == []
    # The scratch store makes a re-cut free and gives the same cut.
    sent = fake.sent
    assert run(d, again, recut=["tr/w"])["cut"] == ["tr/w"]
    assert again.sent < sent / 4
    assert anchor_store.load(d["anchors"], "tr/w.json").paragraphs == cut.paragraphs


def test_a_changed_original_freezes_the_cut_until_recut(corpus) -> None:
    d = corpus
    embed_work(d["normalized"], d["embeddings"], "orig/w.json", FakeEmbedder())
    run(d, FakeEmbedder())
    write_work(d["raw"], "orig/w.json", "lat",
               [latin(SENTENCES[:9]), latin(SENTENCES[9:])])
    nz.normalize_all(d["raw"], d["normalized"], anchors_dir=d["anchors"],
                     accept_raw_change=True)
    [state] = anchor.check_works(d["normalized"], d["anchors"])
    assert state.status == anchor.ANCHOR_CUTS
    p = anchor.plan(d["normalized"], d["anchors"])
    assert p.todo == [] and [s.status for s in p.frozen] == [anchor.ANCHOR_CUTS]
    embed_work(d["normalized"], d["embeddings"], "orig/w.json", FakeEmbedder())
    assert run(d, FakeEmbedder())["cut"] == []
    assert run(d, FakeEmbedder(), recut=["all"])["cut"] == ["tr/w"]
    [state] = anchor.check_works(d["normalized"], d["anchors"])
    assert state.status == anchor.CURRENT


def test_changed_words_and_stale_output_fail(corpus) -> None:
    d = corpus
    embed_work(d["normalized"], d["embeddings"], "orig/w.json", FakeEmbedder())
    run(d, FakeEmbedder())
    cut = anchor_store.load(d["anchors"], "tr/w.json")
    # A cut file normalize hasn't applied yet.
    ref = next(iter(cut.paragraphs))
    rec = cut.paragraphs[ref]
    moved = (0, *(s + 1 for s in rec.starts[1:])) if len(rec.starts) > 1 else rec.starts
    cut.paragraphs[ref] = anchor_store.ParagraphCut(rec.words, moved)
    anchor_store.save(d["anchors"], "tr/w.json", cut)
    if moved != rec.starts:
        [state] = anchor.check_works(d["normalized"], d["anchors"])
        assert state.status == anchor.OUTPUT
    # The translation's text changed: re-cut by a plain run.
    write_work(d["raw"], "tr/w.json", "eng",
               [english(SENTENCES[:8]) + " eng999.", english(SENTENCES[8:])],
               translation_of="orig/w")
    nz.normalize_all(d["raw"], d["normalized"], anchors_dir=d["anchors"],
                     accept_raw_change=True)
    [state] = anchor.check_works(d["normalized"], d["anchors"])
    assert state.status == anchor.WORDS
    assert run(d, FakeEmbedder())["cut"] == ["tr/w"]


def test_orphan_cut_files_are_reported(corpus) -> None:
    anchor_store.save(corpus["anchors"], "tr/gone.json", anchor_store.CutFile(
        "tr/gone", "orig/w", "m", "c", "w", "", {}))
    states = anchor.check_works(corpus["normalized"], corpus["anchors"])
    assert {s.status for s in states} == {anchor.MISSING, anchor.ORPHAN}


# ---------------------------------------------------------------- the DP


def test_refine_matches_original_units_on_a_close_translation() -> None:
    fake = FakeEmbedder()
    lat = [latin(SENTENCES[i:i + 2]) for i in range(0, 16, 2)]
    eng_par = english(SENTENCES)
    orig_vecs = fake(lat)
    orig = anchor_refine.Units("o", "lat", [f"P.1.s{i}" for i in range(1, 9)], lat, orig_vecs)
    today_texts = anchoring.cut_at(eng_par, list(range(0, len(anchoring.words(eng_par)), 30)))
    today = anchor_refine.Units("t", "eng", [f"P.1.s{i}" for i in range(1, len(today_texts) + 1)],
                                today_texts, np.zeros((len(today_texts), DIMS), np.float32))
    cache = anchor_refine.VectorCache(None, "t", "t.json", fake, anchor.run_spec(),
                                      lambda t: len(t.split()))
    result = anchor_refine.refine(orig, today, cache)
    got = [concepts(t) for t in result.texts()]
    want = [concepts(t) for t in lat]
    assert got == want
    assert result.history[-1]["new_units"] == 0
