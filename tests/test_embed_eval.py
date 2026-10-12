import json
import random
from pathlib import Path

import pytest

from scripts.embed_eval import build, metrics, queries, retrieval, select
from scripts.embed_eval.select import ChunkMeta

LOREM = "alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu nu xi"


def _meta(cid, work, lang, idx, *, genre="patristic", group=None, n_chars=100, oop=False):
    return ChunkMeta(cid, work, lang, genre, idx, n_chars, group, oop)


# --- select -----------------------------------------------------------------

def test_unique_works_excludes_translations_and_their_originals():
    works = [
        {"work_id": "g/orig", "language": "grc", "genre": "patristic"},
        {"work_id": "e/tr", "language": "eng", "genre": "patristic", "translation_of": "g/orig"},
        {"work_id": "g/solo", "language": "grc", "genre": "patristic"},
        {"work_id": "g/bible", "language": "grc", "genre": "scripture"},
        {"work_id": "s/excluded", "language": "syc", "genre": "patristic"},
    ]
    got = select.unique_works(works, excluded={"s/excluded": "test"})
    assert got == {"grc": {"g/solo"}}


def test_eligibility_bounds_and_period():
    assert _meta("a", "w", "grc", 0).eligible
    assert not _meta("a", "w", "grc", 0, n_chars=select.MIN_CHARS - 1).eligible
    assert not _meta("a", "w", "grc", 0, n_chars=select.MAX_CHARS + 1).eligible
    assert not _meta("a", "w", "grc", 0, oop=True).eligible


def _fixture_metas():
    metas = []
    for v in range(10):
        g = f"John.1.{v + 1}"
        for lang, work in (("grc", "nt/grc"), ("cop", "nt/cop"), ("eng", "nt/eng")):
            metas.append(_meta(f"{work}#{g}", work, lang, v, genre="scripture", group=g))
    for i in range(20):
        metas.append(_meta(f"shen#{i}", "shen", "cop", i))
        metas.append(_meta(f"dist#{i}", "dist", "eng", i))
    return metas


FIXTURE_WORKS = [
    {"work_id": "nt/grc", "language": "grc", "genre": "scripture"},
    {"work_id": "nt/cop", "language": "cop", "genre": "scripture"},
    {"work_id": "nt/eng", "language": "eng", "genre": "scripture"},
    {"work_id": "shen", "language": "cop", "genre": "patristic"},
    {"work_id": "dist", "language": "eng", "genre": "patristic", "translation_of": "x"},
]


def test_select_targets_and_corpus():
    sel = select.select(
        _fixture_metas(), FIXTURE_WORKS, target_langs=("grc", "cop"),
        scripture_per_lang=3, unique_per_lang=4, neighbours=1, distractors_per_lang=5,
    )
    kinds = sorted((t.language, t.origin) for t in sel.targets)
    assert kinds.count(("grc", "scripture")) == 3
    assert kinds.count(("cop", "scripture")) == 3
    assert kinds.count(("cop", "unique")) == 4
    assert ("grc", "unique") not in kinds
    # every member of a selected translation group is in the corpus, English included
    for t in sel.targets:
        assert t.chunk_id in sel.corpus_ids
        if t.origin == "scripture":
            group = t.chunk_id.split("#")[1]
            assert f"nt/eng#{group}" in sel.corpus_ids
    assert any(role == "neighbour" for role in sel.roles.values())


def test_select_is_deterministic():
    a = select.select(_fixture_metas(), FIXTURE_WORKS, seed=3, distractors_per_lang=5)
    b = select.select(list(reversed(_fixture_metas())), FIXTURE_WORKS, seed=3,
                      distractors_per_lang=5)
    assert a.targets == b.targets and a.corpus_ids == b.corpus_ids


# --- queries ----------------------------------------------------------------

def test_draw_span_length_and_edges():
    rng = random.Random(0)
    for _ in range(50):
        span = queries.draw_span("«" + LOREM + ".»", rng)
        n = len(span.split())
        assert queries.MIN_WORDS <= n <= queries.MAX_WORDS
        assert span[0].isalpha() and span[-1].isalpha()
    assert queries.draw_span("too short text", rng) is None


def test_perturb_greek_and_latin():
    rng = random.Random(0)
    assert queries.perturb("Ἐν ἀρχῇ ἦν ὁ λόγος,", "grc", rng) == "εν αρχη ην ο λογος"
    for seed in range(20):
        out = queries.perturb("Iustus mihi gratia", "lat", random.Random(seed))
        assert out != "iustus mihi gratia"  # at least one variant always fires
        assert out.islower()


def test_make_queries_relevance_includes_duplicates():
    corpus = [
        {"chunk_id": "a", "language": "grc", "text": "Ἐν ἀρχῇ ἦν ὁ λόγος καὶ ὁ λόγος ἦν πρὸς"},
        {"chunk_id": "b", "language": "grc", "text": "Εν αρχη ην ο λογος και ο λογος ην προς"},
        {"chunk_id": "c", "language": "grc", "text": "ἄλλο τι παντελῶς ἕτερον κείμενον ἐνθάδε"},
    ]
    qs = queries.make_queries([("a", "grc", "scripture", corpus[0]["text"])], corpus)
    assert [q.mode for q in qs] == ["exact", "near"]
    for q in qs:
        assert set(q.relevant_ids) == {"a", "b"}
        assert q.target_chunk_id == "a"
    assert queries.Query.from_json(json.loads(json.dumps(qs[0].to_json()))) == qs[0]


def test_make_queries_skips_formulaic_spans():
    text = "gloria patri et filio et spiritui sancto amen"
    corpus = [{"chunk_id": f"c{i}", "language": "lat", "text": text} for i in range(10)]
    assert queries.make_queries([("c0", "lat", "unique", text)], corpus) == []


# --- retrieval & metrics ----------------------------------------------------

DOCS = [
    "Ἐν ἀρχῇ ἦν ὁ λόγος",
    "In principio erat Verbum",
    "In the beginning was the Word",
    "Beati pauperes spiritu",
]


def test_bm25_folds_and_filters():
    bm = retrieval.BM25(DOCS)
    assert bm.search(["εν αρχη ην"], 2)[0][0] == 0
    assert bm.search(["in principio"], 1)[0] == [1]
    # restricted to English, "in" still matches doc 2 but never doc 1
    assert bm.search(["in principio"], 3, [frozenset({2, 3})])[0] == [2]


def test_rrf_merges_rankings():
    class Fixed:
        def __init__(self, name, ranking):
            self.name, self.ranking = name, ranking

        def search(self, qs, k, allowed=None):
            return [self.ranking[:k] for _ in qs]

    rrf = retrieval.RRF([Fixed("a", [0, 1, 2]), Fixed("b", [1, 2, 0])])
    assert rrf.name == "hybrid:a+b"
    assert rrf.search(["q"], 3)[0] == [1, 0, 2]


def test_dense_with_fake_embedder_and_cache(tmp_path: Path):
    np = pytest.importorskip("numpy")

    class CharEmbedder:
        name = "fake/chars"
        calls = 0

        def _vec(self, texts):
            m = np.zeros((len(texts), 64), dtype=np.float32)
            for i, t in enumerate(texts):
                for ch in t.lower():
                    m[i, ord(ch) % 64] += 1
            return m

        def embed_documents(self, texts):
            CharEmbedder.calls += 1
            return self._vec(texts)

        def embed_queries(self, texts):
            return self._vec(texts)

    ids = [str(i) for i in range(len(DOCS))]
    d = retrieval.Dense(CharEmbedder(), ids, DOCS, cache_dir=tmp_path)
    assert d.name == "dense:fake/chars"
    assert d.search(["beati pauperes"], 1)[0] == [3]
    assert d.search(["beati pauperes"], 2, [frozenset({0, 1})])[0][0] in {0, 1}
    retrieval.Dense(CharEmbedder(), ids, DOCS, cache_dir=tmp_path)
    assert CharEmbedder.calls == 1  # second construction used the cache


def test_metrics():
    assert metrics.first_rank(["x", "a", "b"], ["b", "a"]) == 2
    assert metrics.first_rank(["x"], ["a"]) is None
    s = metrics.summarize([1, 3, None, 10], ks=(1, 3))
    assert s == {"n": 4, "R@1": 0.25, "R@3": 0.5, "MRR": pytest.approx((1 + 1 / 3 + 0.1) / 4)}
    table = metrics.markdown_table(metrics.breakdown([(("exact", "grc"), 1)], ks=(1,)),
                                   ("mode", "lang"))
    assert "| exact | grc | 1 | 1.00 | 1.00 |" in table


# --- end to end ---------------------------------------------------------------

def test_build_and_bm25_run_end_to_end(tmp_path: Path):
    from scripts.embed_eval.run import evaluate, make_retriever

    chunks_dir = tmp_path / "chunks"
    (chunks_dir / "x").mkdir(parents=True)
    grc_words = "λόγος θεὸς ζωὴ φῶς σκοτία κόσμος σὰρξ δόξα χάρις ἀλήθεια πνεῦμα ὕδωρ".split()
    rows, works = [], []
    for v in range(6):
        g = f"John.1.{v + 1}"
        words = [w + "α" * (v + 1) for w in grc_words]  # distinct vocabulary per verse
        for lang, wid, text in (("grc", "nt/grc", " ".join(words)),
                                ("eng", "nt/eng", f"verse {v} " + LOREM)):
            rows.append({"chunk_id": f"{wid}#{g}", "work_id": wid, "language": lang,
                         "text": text, "chunk_index": v, "translation_group_id": g})
    (chunks_dir / "x" / "c.json").write_text(json.dumps(rows, ensure_ascii=False))
    works = [{"work_id": "nt/grc", "language": "grc", "genre": "scripture"},
             {"work_id": "nt/eng", "language": "eng", "genre": "scripture"}]
    works_path = tmp_path / "works.jsonl"
    works_path.write_text("".join(json.dumps({"path": "", "work": w}) + "\n" for w in works))

    out = tmp_path / "eval"
    stats = build.build(chunks_dir, works_path, out, scripture_per_lang=3, unique_per_lang=0,
                        distractors_per_lang=2)
    assert stats["targets"] == {"grc/scripture": 3}
    corpus = [json.loads(line) for line in (out / "corpus.jsonl").open()]
    qs = [queries.Query.from_json(json.loads(line)) for line in (out / "queries.jsonl").open()]
    assert len(qs) == 6
    result = evaluate(make_retriever("bm25", corpus, None), corpus, qs)
    for scope in ("all", "lang"):
        exact = result["summaries"][scope][("exact", "grc", "scripture")]
        assert exact["R@1"] == 1.0
