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
    weighted = retrieval.RRF([Fixed("a", [0, 1, 2]), Fixed("b", [1, 2, 0])], [1.0, 0.1])
    assert weighted.name == "hybrid:a+b@0.1"
    assert weighted.search(["q"], 3)[0] == [0, 1, 2]


class CharEmbedder:
    """Deterministic toy embedder: character counts modulo 64."""

    name = "fake/chars"

    def __init__(self):
        self.calls = 0

    def _vec(self, texts):
        import numpy as np

        m = np.zeros((len(texts), 64), dtype=np.float32)
        for i, t in enumerate(texts):
            for ch in t.lower():
                m[i, ord(ch) % 64] += 1
        return m

    def embed_documents(self, texts):
        self.calls += 1
        return self._vec(texts)

    def embed_queries(self, texts):
        self.calls += 1
        return self._vec(texts)


def test_dense_search_and_language_filter():
    pytest.importorskip("numpy")
    d = retrieval.Dense(CharEmbedder(), DOCS)
    assert d.name == "dense:fake/chars"
    assert d.search(["beati pauperes"], 1)[0] == [3]
    assert d.search(["beati pauperes"], 2, [frozenset({0, 1})])[0][0] in {0, 1}


def test_cached_embedder_resumes(tmp_path: Path):
    np = pytest.importorskip("numpy")
    from scripts.embed_eval.embedders import CachedEmbedder

    inner = CharEmbedder()
    first = CachedEmbedder(inner, tmp_path / "c.sqlite", batch_size=2).embed_documents(DOCS[:3])
    assert inner.calls == 2  # batches of 2
    again = CachedEmbedder(inner, tmp_path / "c.sqlite").embed_documents(DOCS)
    assert inner.calls == 3  # only DOCS[3] was missing
    np.testing.assert_array_equal(first, again[:3])
    CachedEmbedder(inner, tmp_path / "c.sqlite").embed_queries(DOCS[:1])
    assert inner.calls == 4  # queries are cached separately from documents


def test_load_authored_relevance():
    corpus = [
        {"chunk_id": "lxx#Ps.1.1", "language": "grc", "translation_group_id": "Ps.1.1"},
        {"chunk_id": "rahlfs#Ps.1.1", "language": "grc", "translation_group_id": "Ps.1.1"},
        {"chunk_id": "kjv#Ps.1.1", "language": "eng", "translation_group_id": "Ps.1.1"},
        {"chunk_id": "shen#3", "language": "cop", "translation_group_id": None},
    ]
    base = {"mode": "paraphrase", "text": "q", "query_lang": "eng"}
    rows = [
        {**base, "query_id": "p1", "target_lang": "grc", "origin": "scripture",
         "target_chunk_id": "lxx#Ps.1.1"},
        {**base, "query_id": "p2", "target_lang": "cop", "origin": "unique",
         "target_chunk_id": "shen#3"},
        {**base, "query_id": "p3", "target_lang": "cop", "origin": "unique",
         "target_chunk_id": "missing"},
    ]
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "a.jsonl"
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))
        qs = queries.load_authored([path], corpus)
    assert [q.query_id for q in qs] == ["p1", "p2"]
    assert qs[0].relevant_ids == ("lxx#Ps.1.1", "rahlfs#Ps.1.1")
    assert qs[1].relevant_ids == ("shen#3",)


def test_api_key_from_env_file(tmp_path: Path, monkeypatch):
    from scripts.embed_eval.embedders import _env_key

    monkeypatch.delenv("FAKE_KEY", raising=False)
    env = tmp_path / ".env"
    env.write_text("# FAKE_KEY=no\nOTHER=1\nFAKE_KEY='abc'\n")
    assert _env_key("FAKE_KEY", env) == "abc"
    monkeypatch.setenv("FAKE_KEY", "fromenv")
    assert _env_key("FAKE_KEY", env) == "fromenv"
    with pytest.raises(KeyError):
        _env_key("NOPE_KEY", env)


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


def test_api_batches_respect_count_tokens_and_truncation():
    from scripts.embed_eval.embedders import ApiEmbedder

    class Fake(ApiEmbedder):
        name = "fake/api"
        batch_size = 3
        max_batch_tokens = 10
        max_input_tokens = 6

        def __init__(self):  # no HTTP client needed
            pass

    texts = ["one two three four five six seven eight", "a", "b", "c", "d"]
    batches = Fake()._batches(texts)
    assert [len(b) for b, _ in batches] == [3, 2]  # long text truncated to 6, then count cap
    assert batches[0][1] <= 10 and len(batches[0][0][0].split()) == 6
    Fake.max_batch_tokens = 6
    assert [len(b) for b, _ in Fake()._batches(texts)] == [1, 3, 1]


def test_report_tables(tmp_path: Path):
    from scripts.embed_eval import report

    def result(name, r1, r3):
        return {"retriever": name, "summaries": {"lang": [
            {"mode": "exact", "lang": "grc", "origin": "unique", "n": 10, "R@1": r1},
            {"mode": "paraphrase", "lang": "grc", "origin": "unique", "n": 5, "R@3": r3},
        ]}}

    for i, r in enumerate([result("bm25", 0.9, 0.0), result("dense:x", 0.5, 0.8)]):
        (tmp_path / f"{i}.json").write_text(json.dumps(r))
    out = report.report(tmp_path, "lang")
    assert "| bm25 | 0.90 | 0.90 |" in out
    para = out.split("### paraphrase")[1]
    assert para.index("dense:x") < para.index("bm25")  # sorted by mean
    assert "### topical" in out and "(no results)" in out


def test_extend_appends_language_without_touching_existing(tmp_path: Path):
    words = "ቃል እግዚአብሔር ሕይወት ብርሃን ጽልመት ዓለም ሥጋ ስብሐት ጸጋ ጽድቅ መንፈስ ማይ".split()
    grc = "λόγος θεὸς ζωὴ φῶς σκοτία κόσμος σὰρξ δόξα χάρις ἀλήθεια πνεῦμα ὕδωρ".split()
    rows = []
    for v in range(6):
        g = f"Gen.1.{v + 1}"
        for lang, wid, vocab in (("grc", "lxx/gen", grc), ("gez", "scripture/gez/gen", words)):
            rows.append({"chunk_id": f"{wid}#{g}", "work_id": wid, "language": lang,
                         "text": " ".join(w + "ሀ" * (v + 1) if lang == "gez" else w + "α" * (v + 1)
                                          for w in vocab),
                         "chunk_index": v, "translation_group_id": g})
    for i in range(8):
        rows.append({"chunk_id": f"scripture/gez/jub#Jub.1.{i}", "work_id": "scripture/gez/jub",
                     "language": "gez", "chunk_index": i, "translation_group_id": None,
                     "text": " ".join(w + "ለ" * (i + 1) for w in words)})
    chunks_dir = tmp_path / "chunks"
    chunks_dir.mkdir()
    (chunks_dir / "c.json").write_text(json.dumps(rows, ensure_ascii=False))
    works = [{"work_id": "lxx/gen", "language": "grc", "genre": "scripture"},
             {"work_id": "scripture/gez/gen", "language": "gez", "genre": "scripture"},
             {"work_id": "scripture/gez/jub", "language": "gez", "genre": "scripture"}]
    works_path = tmp_path / "works.jsonl"
    works_path.write_text("".join(json.dumps({"work": w}) + "\n" for w in works))
    out = tmp_path / "eval"

    build.build(chunks_dir, works_path, out, scripture_per_lang=2, unique_per_lang=0,
                distractors_per_lang=0, authored_dir=tmp_path / "none")
    before_corpus = (out / "corpus.jsonl").read_text()
    before_queries = (out / "queries.jsonl").read_text()

    ext = build.extend_build(chunks_dir, works_path, out, "gez",
                             scripture_per_lang=2, unique_per_lang=3)
    assert ext["targets"] == {"gez/scripture": 2, "gez/unique": 3}
    assert (out / "corpus.jsonl").read_text().startswith(before_corpus)
    assert (out / "queries.jsonl").read_text().startswith(before_queries)
    corpus = [json.loads(line) for line in (out / "corpus.jsonl").open()]
    assert len({c["chunk_id"] for c in corpus}) == len(corpus)  # nothing duplicated
    gez_q = [json.loads(line) for line in (out / "queries.jsonl").open()
             if json.loads(line)["target_lang"] == "gez"]
    assert {q["origin"] for q in gez_q} == {"scripture", "unique"}
    assert "extensions" in json.loads((out / "build.json").read_text())
    with pytest.raises(ValueError):
        build.extend_build(chunks_dir, works_path, out, "gez")


def test_openai_schema_is_strict():
    from scripts.embed_eval.translate import Judgement, Translation, openai_schema

    def check(node):
        if isinstance(node, dict):
            if "properties" in node:
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"])
            assert "minimum" not in node and "maximum" not in node
            for v in node.values():
                check(v)
        elif isinstance(node, list):
            for v in node:
                check(v)

    for model in (Translation, Judgement):
        check(openai_schema(model))


def test_dense_alt_texts_take_the_better_vector():
    pytest.importorskip("numpy")
    docs = ["ⲡⲛⲟⲩⲧⲉ ⲡⲉ ⲡⲟⲩⲟⲉⲓⲛ", "Beati pauperes spiritu"]
    plain = retrieval.Dense(CharEmbedder(), docs)
    with_tr = retrieval.Dense(CharEmbedder(), docs, ["God is the light", None], alt_name="tr:x")
    assert with_tr.name == "dense:fake/chars+tr:x"
    q = ["god is the light"]
    assert plain.search(q, 1)[0] == [1]   # Latin letters beat Coptic for an English query
    assert with_tr.search(q, 1)[0] == [0]  # the translation makes the Coptic doc findable


def test_bulk_groups_split_by_work_size_and_count(monkeypatch):
    from scripts.embed_eval import translate

    monkeypatch.setattr(translate, "BULK_MAX_CHARS", 10)
    monkeypatch.setattr(translate, "BULK_MAX_ITEMS", 3)
    chunks = [{"work_id": "a", "chunk_id": f"a#{i}", "text": "xxxx"} for i in range(4)]
    chunks += [{"work_id": "b", "chunk_id": "b#0", "text": "y" * 50}]
    groups = translate.bulk_groups(chunks)
    assert [[c["chunk_id"] for c in g] for g in groups] == [
        ["a#0", "a#1"], ["a#2", "a#3"], ["b#0"]]


def test_bulk_groups_use_natural_order():
    from scripts.embed_eval import translate

    chunks = [{"work_id": "w", "chunk_id": f"w#Gen.1.{v}", "text": "x"} for v in (10, 2, 1)]
    assert [c["chunk_id"] for c in translate.bulk_groups(chunks)[0]] == [
        "w#Gen.1.1", "w#Gen.1.2", "w#Gen.1.10"]


def test_review_overlap_and_passes():
    from scripts.embed_eval import review

    kjv = "In the beginning God created the heaven and the earth."
    assert review.overlap("In the beginning God created the heaven and the earth", [kjv]) == 1.0
    assert review.overlap("At the start of everything the Lord made sky and land", [kjv]) == 0.0
    assert review.overlap("", [kjv]) == 0.0
    good = {"paraphrase": {"accuracy": 5}, "topical": {"relevance": 4, "specificity": "broad"}}
    narrow = {"paraphrase": {"accuracy": 3}, "topical": {"relevance": 5, "specificity": "narrow"}}
    assert review.passes("paraphrase", good, 0.1)
    assert not review.passes("paraphrase", good, 0.9)  # echoes an English Bible
    assert review.passes("topical", good, 0.0)
    assert not review.passes("paraphrase", narrow, 0.0)
    assert not review.passes("topical", narrow, 0.0)
    assert not review.passes("topical", None, 0.0)


def test_review_resolve_follows_coptic_rename():
    from scripts.embed_eval.review import resolve

    corpus = {"liturgical/coptic-scriptorium/x#1": {}, "a#1": {}}
    assert resolve("a#1", corpus) == "a#1"
    old = "liturgical/coptic-scriptorium/x#1"
    assert resolve("patristic/coptic-scriptorium/x#1", corpus) == old
    assert resolve("missing#1", corpus) is None
