"""Tests for the embedding store (patristica.embeddings) and scripts.embed."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

from patristica import embeddings as emb  # noqa: E402
from patristica import translations as tr  # noqa: E402
from patristica.embedders import shorten  # noqa: E402
from scripts import embed  # noqa: E402

DIMS = 8


class FakeEmbedder:
    """Deterministic vectors from the text; records every request."""

    name = "fake/model"
    batch_size = 3
    max_batch_tokens = 10_000

    def __init__(self, dims: int = DIMS) -> None:
        self.dims = dims
        self.calls: list[list[str]] = []
        self.tokens_used = 0

    def embed_batch(self, texts: list[str], kind: str = "document") -> np.ndarray:
        assert kind == "document"
        self.calls.append(list(texts))
        out = np.zeros((len(texts), self.dims), dtype=np.float32)
        for i, t in enumerate(texts):
            for ch in t:
                out[i, ord(ch) % self.dims] += 1
        return out / np.linalg.norm(out, axis=1, keepdims=True)

    @property
    def sent(self) -> list[str]:
        return [t for call in self.calls for t in call]


def write_corpus(root: Path, works: dict[str, tuple[str, list[tuple[str, str]]]],
                 licence: dict[str, str] | None = None) -> Path:
    """works: work_id → (language, [(ref, text)]); returns the normalized dir."""
    norm = root / "normalized"
    norm.mkdir(parents=True, exist_ok=True)
    lines = []
    for work_id, (lang, units) in works.items():
        source = work_id.split("/")[0]
        path = f"{work_id}.json"
        (norm / path).parent.mkdir(parents=True, exist_ok=True)
        chunks = [{"chunk_id": f"{work_id}#{ref}", "work_id": work_id, "canonical_ref": ref,
                   "language": lang, "text": text, "chunk_index": i}
                  for i, (ref, text) in enumerate(units)]
        (norm / path).write_text(json.dumps(chunks), encoding="utf-8")
        lines.append(json.dumps({"path": path, "work": {
            "work_id": work_id, "source_id": source, "language": lang,
            "license": (licence or {}).get(work_id, "public_domain")}}))
    (norm / "_works.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return norm


def translate(root: Path, work_id: str, lang: str, rows: dict[str, tuple[str, str]]) -> None:
    """rows: ref → (source text, English)."""
    prov = tr.Provenance(model="sol", prompt_version="v1", date="2026-10-14", script="t")
    work = tr.WorkTranslations(work_id=work_id, source_path=f"{work_id}.json",
                               source_language=lang)
    chunks = []
    for ref, (src, eng) in rows.items():
        cid = f"{work_id}#{ref}"
        work.put(tr.ChunkTranslation(chunk_id=cid, source_sha256=tr.text_sha(src),
                                     provenance=prov.key, group_size=1, text=eng), prov)
        chunks.append({"chunk_id": cid, "text": src})
    tr.save(root / "translations", work, chunks)


def run(root: Path, fake: FakeEmbedder, **kw) -> embed.Stats:
    return embed.run(root / "normalized", root / "embeddings", root / "translations",
                     make_embedder=lambda: fake, workers=2, **kw)


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    write_corpus(tmp_path, {
        "kjv/gen": ("eng", [("Gen.1.1", "In the beginning God created the heaven."),
                            ("Gen.1.2", "And the earth was without form."),
                            ("Gen.1.0", "GENESIS")]),          # under MIN_CHARS: skipped
        "pta/aphrahat": ("syc", [("1.1", "ܒܪܫܝܬ ܐܝܬܘܗܝ ܗܘܐ ܡܠܬܐ"),
                                 ("1.2", "ܘܗܘ ܡܠܬܐ ܐܝܬܘܗܝ ܗܘܐ ܠܘܬ")]),
    })
    translate(tmp_path, "pta/aphrahat", "syc", {
        "1.1": ("ܒܪܫܝܬ ܐܝܬܘܗܝ ܗܘܐ ܡܠܬܐ", "In the beginning was the Word."),
        # 1.2 has no translation yet
    })
    return tmp_path


def test_embeds_text_and_translation_vectors_and_skips_short_units(corpus: Path):
    fake = FakeEmbedder()
    stats = run(corpus, fake)
    assert stats.short == 1 and stats.untranslated == 1
    assert stats.vectors == stats.to_embed == 5   # 2 kjv + 2 syc + 1 translation
    assert sorted(fake.sent) == sorted([
        "In the beginning God created the heaven.", "And the earth was without form.",
        "ܒܪܫܝܬ ܐܝܬܘܗܝ ܗܘܐ ܡܠܬܐ", "ܘܗܘ ܡܠܬܐ ܐܝܬܘܗܝ ܗܘܐ ܠܘܬ", "In the beginning was the Word."])
    assert all(len(c) <= FakeEmbedder.batch_size for c in fake.calls)

    shard = emb.load(corpus / "embeddings", "pta/aphrahat.json")
    assert [(r.chunk_id, r.kind) for r in shard.rows] == [
        ("pta/aphrahat#1.1", emb.KIND_TEXT), ("pta/aphrahat#1.1", emb.KIND_TRANSLATION),
        ("pta/aphrahat#1.2", emb.KIND_TEXT)]
    assert shard.rows[1].sha == tr.text_sha("In the beginning was the Word.")
    assert shard.vecs.dtype == np.float16 and shard.vecs.shape == (3, DIMS)
    (run_,) = shard.runs.values()                    # the model is recorded per row
    assert (run_.model, run_.dims, run_.input_type) == ("fake/model", DIMS, "document")
    assert {r.run for r in shard.rows} == {run_.key}
    np.testing.assert_allclose(
        shard.vecs[2].astype(np.float32),
        fake.embed_batch(["ܘܗܘ ܡܠܬܐ ܐܝܬܘܗܝ ܗܘܐ ܠܘܬ"])[0], atol=1e-3)


def test_rerun_reuses_everything_and_rewrites_nothing(corpus: Path):
    run(corpus, FakeEmbedder())
    paths = sorted((corpus / "embeddings").rglob("*.npz"))
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths}

    fake = FakeEmbedder()
    stats = run(corpus, fake)
    assert fake.calls == [] and stats.to_embed == 0 and stats.reused == 5
    assert stats.written == 0
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in paths} == before


def test_changed_text_new_translation_and_vanished_chunk(corpus: Path):
    run(corpus, FakeEmbedder())
    write_corpus(corpus, {
        "kjv/gen": ("eng", [("Gen.1.1", "In the beginning God created the heavens.")]),  # edited
        "pta/aphrahat": ("syc", [("1.1", "ܒܪܫܝܬ ܐܝܬܘܗܝ ܗܘܐ ܡܠܬܐ"),
                                 ("1.2", "ܘܗܘ ܡܠܬܐ ܐܝܬܘܗܝ ܗܘܐ ܠܘܬ")]),
    })
    translate(corpus, "pta/aphrahat", "syc", {
        "1.1": ("ܒܪܫܝܬ ܐܝܬܘܗܝ ܗܘܐ ܡܠܬܐ", "In the beginning was the Word."),
        "1.2": ("ܘܗܘ ܡܠܬܐ ܐܝܬܘܗܝ ܗܘܐ ܠܘܬ", "And the Word was with God."),
    })
    fake = FakeEmbedder()
    stats = run(corpus, fake)
    assert sorted(fake.sent) == ["And the Word was with God.",
                                 "In the beginning God created the heavens."]
    assert stats.reused == 3 and stats.untranslated == 0
    gen = emb.load(corpus / "embeddings", "kjv/gen.json")
    assert [r.chunk_id for r in gen.rows] == ["kjv/gen#Gen.1.1"]   # Gen.1.2 dropped


def test_other_model_rows_are_reembedded(corpus: Path):
    run(corpus, FakeEmbedder())
    other = FakeEmbedder()
    other.name = "fake/other"
    stats = run(corpus, other)
    assert stats.reused == 0 and len(other.sent) == 5
    shard = emb.load(corpus / "embeddings", "kjv/gen.json")
    assert {r.model for r in shard.runs.values()} == {"fake/other"}  # old run dropped


def test_identical_texts_are_sent_once(tmp_path: Path):
    same = "Blessed is the man that walketh not."
    write_corpus(tmp_path, {"kjv/ps": ("eng", [("Ps.1.1", same)]),
                            "asv/ps": ("eng", [("Ps.1.1", same)])})
    fake = FakeEmbedder()
    stats = run(tmp_path, fake)
    assert fake.sent == [same] and stats.unique_texts == 1
    a = emb.load(tmp_path / "embeddings", "kjv/ps.json")
    b = emb.load(tmp_path / "embeddings", "asv/ps.json")
    assert np.array_equal(a.vecs, b.vecs)


def test_filters_unpublishable_and_prune(tmp_path: Path):
    write_corpus(tmp_path, {"kjv/gen": ("eng", [("Gen.1.1", "In the beginning God.")]),
                            "unlicensed/a": ("syc", [("1", "ܒܪܫܝܬ ܐܝܬܘܗܝ ܗܘܐ")])},
                 licence={"unlicensed/a": "unknown"})
    fake = FakeEmbedder()
    stats = run(tmp_path, fake)
    assert stats.works == 1 and fake.sent == ["In the beginning God."]
    assert not emb.shard_path(tmp_path / "embeddings", "unlicensed/a.json").exists()

    stale = emb.shard_path(tmp_path / "embeddings", "gone/work.json")
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"")
    run(tmp_path, FakeEmbedder(), sources=["kjv"])      # filtered run: no pruning
    assert stale.exists()
    stats = run(tmp_path, FakeEmbedder())               # full run prunes
    assert not stale.exists() and stats.deleted == 1


def test_dry_run_estimates_without_calling_the_api(corpus: Path):
    def boom():
        raise AssertionError("dry run must not create an embedder")
    stats = embed.run(corpus / "normalized", corpus / "embeddings", corpus / "translations",
                      dry_run=True, make_embedder=boom)
    assert stats.to_embed == stats.unique_texts == 5 and stats.est_tokens > 0
    assert not (corpus / "embeddings").exists()


def test_limit_works(corpus: Path):
    fake = FakeEmbedder()
    run(corpus, fake, limit_works=1)
    assert sorted(p.name for p in (corpus / "embeddings").rglob("*.npz")) == ["gen.npz"]


def test_api_error_keeps_finished_shards(tmp_path: Path):
    write_corpus(tmp_path, {"a/one": ("eng", [("1", "first work text here")]),
                            "b/two": ("eng", [("1", "second work text here")])})

    class Failing(FakeEmbedder):
        batch_size = 1

        def embed_batch(self, texts, kind="document"):
            if texts == ["second work text here"]:
                raise RuntimeError("quota")
            return super().embed_batch(texts, kind)

    with pytest.raises(RuntimeError, match="quota"):
        embed.run(tmp_path / "normalized", tmp_path / "embeddings", tmp_path / "translations",
                  make_embedder=Failing, workers=1)
    assert emb.load(tmp_path / "embeddings", "a/one.json") is not None
    fake = FakeEmbedder()
    run(tmp_path, fake)                                  # resumes with the rest only
    assert fake.sent == ["second work text here"]


def test_no_requests_rewrites_shards_and_refuses_to_send(corpus: Path, monkeypatch):
    """--no-requests (scripts.pipeline at $0, #248): no key, no calls; shards are
    still rewritten, and a text still to embed fails the run."""
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    monkeypatch.chdir(corpus)  # no .env to read a key from

    class Voyage(FakeEmbedder):  # rows look like the real model's, so NoRequests reuses them
        name = f"voyage/{embed.MODEL}"

    run(corpus, Voyage(embed.DIMS))
    aphrahat = ("syc", [("1.1", "ܒܪܫܝܬ ܐܝܬܘܗܝ ܗܘܐ ܡܠܬܐ"), ("1.2", "ܘܗܘ ܡܠܬܐ ܐܝܬܘܗܝ ܗܘܐ ܠܘܬ")])
    gen = ("eng", [("Gen.1.1", "In the beginning God created the heaven.")])  # 1.2 dropped
    write_corpus(corpus, {"kjv/gen": gen, "pta/aphrahat": aphrahat})
    stats = embed.run(corpus / "normalized", corpus / "embeddings", corpus / "translations",
                      make_embedder=embed.NoRequests, workers=1)
    assert stats.to_embed == 0 and stats.written == 1
    shard = emb.load(corpus / "embeddings", "kjv/gen.json")
    assert [r.chunk_id for r in shard.rows] == ["kjv/gen#Gen.1.1"]

    write_corpus(corpus, {"kjv/gen": ("eng", [("Gen.1.1", "A text never embedded before.")]),
                          "pta/aphrahat": aphrahat})
    with pytest.raises(embed.ApiError, match="--no-requests"):
        embed.run(corpus / "normalized", corpus / "embeddings", corpus / "translations",
                  make_embedder=embed.NoRequests, workers=1)


def test_store_round_trip_and_rejects_mismatched_vectors(tmp_path: Path):
    r = emb.EmbeddingRun(model="m", dims=4, input_type="document", date="2026-10-17",
                         script="t")
    work = emb.WorkEmbeddings("w", "s/w.json", {r.key: r},
                              [emb.Row("w#1", 0, "abc", r.key)],
                              np.ones((1, 4), dtype=np.float16))
    assert emb.save(tmp_path, work) is True
    assert emb.save(tmp_path, emb.load(tmp_path, "s/w.json")) is False
    assert emb.load(tmp_path, "s/w.json").same_content(work)
    work.vecs = np.ones((2, 4), dtype=np.float16)
    with pytest.raises(ValueError):
        emb.save(tmp_path, work)


def test_shorten_renormalizes():
    v = shorten(np.array([[3.0, 4.0, 12.0], [0.0, 0.0, 1.0]]), 2)
    np.testing.assert_allclose(v, [[0.6, 0.8], [0.0, 0.0]])
    with pytest.raises(ValueError):
        shorten(np.ones((1, 2)), 3)


def test_translated_languages_match_the_translator():
    from scripts.embed_eval.translate import LANGUAGE_NAMES

    assert tr.TRANSLATED_LANGUAGES == set(LANGUAGE_NAMES)
