"""Tests for GET /search (api/search.py, #141).

The query embedder is stubbed. The database tests load ``tests/index_fixture``
into the Postgres of ``PATRISTICA_TEST_DATABASE_URL`` and skip without it.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

np = pytest.importorskip("numpy")
pytest.importorskip("fastapi")
pytest.importorskip("psycopg_pool")

from fastapi.testclient import TestClient  # noqa: E402

from api import app as api_app  # noqa: E402
from api import search as s  # noqa: E402
from patristica.embedders import ApiError  # noqa: E402
from tests import index_fixture as fx  # noqa: E402


class StubClient:
    """Voyage stand-in: each known query embeds as a basis direction."""

    def __init__(self, axes: dict[str, int]) -> None:
        self.axes, self.calls = axes, []

    def embed_batch(self, texts: list[str], kind: str) -> Any:
        self.calls.append((texts, kind))
        return np.stack([fx.direction(self.axes[t]) for t in texts])


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    api_app.app.dependency_overrides.clear()


# --- pure ----------------------------------------------------------------


@pytest.mark.parametrize("q, phrases, text", [
    ("  grace   and\nfaith ", (), "grace and faith"),
    ('"in the beginning"', ("in the beginning",), ""),
    ("“in  principio”", ("in principio",), ""),
    ("„im Anfang“ «ἐν ἀρχῇ»", ("im Anfang", "ἐν ἀρχῇ"), ""),
    ('the "word" made flesh', ("word",), "the made flesh"),
    ('"in principio erat', ("in principio erat",), ""),  # an open quote runs to the end
    ('light "" darkness', (), "light darkness"),  # empty quotes are ignored
    ('""', (), ""),
    ("Augustine's \u05d2\u05f3 'grace'", (), "Augustine's \u05d2\u05f3 'grace'"),  # not quotes
])
def test_parse_query(q: str, phrases: tuple[str, ...], text: str) -> None:
    parsed = s.parse_query(q)
    assert (parsed.phrases, parsed.text) == (phrases, text)
    assert parsed.mode == ("keyword" if phrases else "vector")


def test_keyword_window_offsets_are_utf16() -> None:
    # Gothic letters are outside the BMP: two UTF-16 code units each.
    text = "𐌹𐌽 𐌰𐌽𐌰𐍃𐍄𐍉𐌳𐌴𐌹𐌽 𐍅𐌰𐍃"
    shown, start, truncated, matches = s.keyword_window(text, ("𐌰𐌽𐌰𐍃𐍄𐍉𐌳𐌴𐌹𐌽",))
    assert (shown, start, truncated) == (text, 0, False)
    assert matches == [[5, 25]]
    assert text.encode("utf-16-le")[10:50].decode("utf-16-le") == "𐌰𐌽𐌰𐍃𐍄𐍉𐌳𐌴𐌹𐌽"


def test_keyword_window_follows_a_late_match() -> None:
    text = "lorem ipsum " * 300 + "in principio erat verbum " + "dolor sit " * 50
    shown, start, truncated, matches = s.keyword_window(text, ("principio erat",))
    assert 0 < start < text.index("in principio")
    # Near the end, the window slides back to keep its full length.
    assert len(shown) == s.TEXT_CHARS and not truncated
    assert shown[matches[0][0]:matches[0][1]] == "principio erat"
    longer = text + "amen " * 1000
    shown, start, truncated, matches = s.keyword_window(longer, ("principio erat",))
    assert start == longer.index("in principio") - s.MATCH_CONTEXT + 3 and truncated
    assert shown[matches[0][0]:matches[0][1]] == "principio erat"
    # An early match keeps the start of the text.
    assert s.keyword_window("in principio " + text, ("in principio",))[1] == 0


def test_filters_sql() -> None:
    assert s.Filters().sql() == ("NOT out_of_period", {})
    where, params = s.Filters(language=["syc", "cop"], source=["pta"],
                              author=["ephrem-the-syrian", "anonymous"], date_from=300,
                              include_out_of_period=True).sql()
    assert where == ("language = ANY(%(language)s) AND source_id = ANY(%(source)s) AND "
                     "(author_ids && %(author)s::text[] OR author_ids = '{}') AND "
                     "date_range && int4range(%(date_from)s, %(date_to)s, '[]')")
    assert params == {"language": ["syc", "cop"], "source": ["pta"],
                      "author": ["ephrem-the-syrian"], "date_from": 300, "date_to": None}
    assert s.Filters(author=["anonymous"]).sql()[0] == "(author_ids = '{}') AND NOT out_of_period"


def test_citation() -> None:
    assert s.citation(["Ephrem the Syrian"], "Hymns on Faith", "Hymn.1.1") == \
        "Ephrem the Syrian, *Hymns on Faith* Hymn.1.1"
    assert s.citation([], "Genesis", "Gen.1.1") == "*Genesis* Gen.1.1"


def test_query_embedder_caches_and_shortens() -> None:
    client = StubClient({"grace": 3})
    embedder = s.QueryEmbedder(lambda: client, cache_size=1)
    vec, cached = embedder.embed("grace")
    assert (vec.shape, cached, float(np.linalg.norm(vec))) == ((512,), False, 1.0)
    assert client.calls == [(["grace"], "query")]
    assert embedder.embed("grace")[1] is True
    assert len(client.calls) == 1


def test_query_embedder_errors_are_unavailable() -> None:
    class Failing:
        def embed_batch(self, texts, kind):
            raise ApiError("voyage/voyage-4-large: gave up after 1 tries: 503")

    with pytest.raises(s.SearchUnavailable, match="did not answer"):
        s.QueryEmbedder(lambda: Failing()).embed("x")

    def no_key():
        raise KeyError("VOYAGE_API_KEY is not set")

    with pytest.raises(s.SearchUnavailable, match="not configured"):
        s.QueryEmbedder(no_key).embed("x")


class BlockingClient:
    """Voyage stand-in whose "grace" calls wait for *release* (then succeed or fail)."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[str] = []
        self.started, self.release, self.fail = threading.Event(), threading.Event(), fail
        self._lock = threading.Lock()

    def embed_batch(self, texts: list[str], kind: str) -> Any:
        with self._lock:
            self.calls.append(texts[0])
        if texts[0] == "grace":
            self.started.set()
            assert self.release.wait(5)
            if self.fail:
                raise ApiError("voyage/voyage-4-large: gave up after 1 tries: 503")
        return np.stack([fx.direction(3)])


def test_concurrent_misses_share_one_call() -> None:
    client = BlockingClient()
    embedder = s.QueryEmbedder(lambda: client)
    with ThreadPoolExecutor(8) as pool:
        waiting = [pool.submit(embedder.embed, "grace") for _ in range(6)]
        assert client.started.wait(5)
        # A different query is not held up by the one in flight.
        assert pool.submit(embedder.embed, "faith").result(timeout=5)[1] is False
        client.release.set()
        results = [f.result(timeout=5) for f in waiting]
    assert client.calls.count("grace") == 1
    assert [cached for _, cached in results].count(False) == 1
    assert all(np.array_equal(vec, results[0][0]) for vec, _ in results)
    assert embedder.embed("grace")[1] is True


def test_concurrent_misses_share_a_failure() -> None:
    client = BlockingClient(fail=True)
    embedder = s.QueryEmbedder(lambda: client)
    with ThreadPoolExecutor(4) as pool:
        waiting = [pool.submit(embedder.embed, "grace") for _ in range(4)]
        assert client.started.wait(5)
        client.release.set()
        errors = [f.exception(timeout=5) for f in waiting]
    assert all(isinstance(e, s.SearchUnavailable) for e in errors)
    assert client.calls.count("grace") == 1
    # A failure is not cached: the next request tries again.
    client.fail = False
    assert embedder.embed("grace")[1] is False
    assert client.calls.count("grace") == 2


def test_rate_limiter() -> None:
    now = [0.0]
    limiter = s.RateLimiter(rate=60, burst=2, clock=lambda: now[0])
    assert limiter.check("a") == 0 and limiter.check("a") == 0
    assert limiter.check("a") == pytest.approx(1.0)
    assert limiter.check("b") == 0  # per client
    now[0] = 1.0
    assert limiter.check("a") == 0


# --- HTTP, no database ---------------------------------------------------


class FakeSearcher:
    def __init__(self, exc: Exception | None = None) -> None:
        self.exc, self.calls = exc, []

    def search(self, q, filters, limit, offset):
        self.calls.append((q, filters, limit, offset))
        if self.exc:
            raise self.exc
        return {"results": []}


def _client(searcher: Any, limiter: s.RateLimiter | None = None) -> TestClient:
    api_app.app.dependency_overrides[api_app.get_searcher] = lambda: searcher
    api_app.app.dependency_overrides[api_app.get_rate_limiter] = (
        lambda: limiter or s.RateLimiter(rate=600, burst=100))
    return TestClient(api_app.app)


def test_search_parses_parameters() -> None:
    fake = FakeSearcher()
    r = _client(fake).get("/search", params=[
        ("q", "faith"), ("language", "syc,cop"), ("language", "grc"), ("author", "anonymous"),
        ("date_from", "300"), ("out_of_period", "true"), ("limit", "5"), ("offset", "10")])
    assert r.status_code == 200
    q, filters, limit, offset = fake.calls[0]
    assert (q, limit, offset) == ("faith", 5, 10)
    assert filters == s.Filters(language=["syc", "cop", "grc"], author=["anonymous"],
                                date_from=300, include_out_of_period=True)


@pytest.mark.parametrize("params", [
    {"q": "x" * (s.MAX_QUERY_CHARS + 1)}, {"q": ""}, {"q": "   "}, {},
    {"q": "x", "limit": s.MAX_LIMIT + 1}, {"q": "x", "offset": s.MAX_OFFSET + 1},
])
def test_search_rejects_bad_requests(params: dict) -> None:
    fake = FakeSearcher()
    assert _client(fake).get("/search", params=params).status_code == 422
    assert fake.calls == []


def test_search_rejects_reversed_date_range() -> None:
    fake = FakeSearcher()
    r = _client(fake).get("/search", params={"q": "x", "date_from": 400, "date_to": 300})
    assert r.status_code == 422
    assert r.json() == {"error": "date_from is after date_to"}
    assert fake.calls == []
    assert _client(fake).get("/search", params={"q": "x", "date_from": 300,
                                                 "date_to": 300}).status_code == 200


def test_search_rate_limited() -> None:
    client = _client(FakeSearcher(), s.RateLimiter(rate=6, burst=1))
    assert client.get("/search", params={"q": "a"}).status_code == 200
    r = client.get("/search", params={"q": "a"})
    assert r.status_code == 429
    assert r.headers["retry-after"] == "10"


def test_too_common_phrase_is_422() -> None:
    from api.keyword import PhraseTooBroad

    r = _client(FakeSearcher(PhraseTooBroad("this phrase is too common to search: add more words"))
                ).get("/search", params={"q": '"et in"'})
    assert r.status_code == 422
    assert r.json() == {"error": "this phrase is too common to search: add more words"}


def test_search_unavailable_is_503() -> None:
    r = _client(FakeSearcher(s.SearchUnavailable("the embedding service did not answer in time"))
                ).get("/search", params={"q": "a"})
    assert r.status_code == 503
    assert r.json() == {"error": "the embedding service did not answer in time"}


# --- against the database ------------------------------------------------

AXES = {
    "creation": fx.axis_of("kjv/gen", "Gen.1.1"),
    "void": fx.axis_of("kjv/gen", "Gen.1.2"),
    "hebrew creation": fx.axis_of("oshb/gen", "Gen.1.1"),
    "faith": fx.axis_of("pta/hymns", "Hymn.1.1", translation=True),
    "syriac faith": fx.axis_of("pta/hymns", "Hymn.1.1"),
    "unlicensed": fx.axis_of("hudra/secret", "H.1"),
}


def _searcher(url: str, ef_search: int = s.EF_SEARCH, **settings: str):
    """A Searcher on *url*, with extra session settings (``-c name=value``)."""
    from psycopg.conninfo import conninfo_to_dict, make_conninfo
    from psycopg_pool import ConnectionPool

    options = " ".join([conninfo_to_dict(url).get("options", ""),
                        *(f"-c {k}={v}" for k, v in settings.items())])
    pool = ConnectionPool(make_conninfo(url, options=options), min_size=1, max_size=2, open=True)
    return s.Searcher(pool, s.QueryEmbedder(lambda: StubClient(AXES)), ef_search=ef_search)


@pytest.fixture
def corpus_url(pg_url: str, tmp_path: Path) -> str:
    fx.load_corpus(tmp_path, pg_url)
    return pg_url


@pytest.fixture
def searcher(corpus_url: str):
    searcher = _searcher(corpus_url)
    try:
        yield searcher
    finally:
        searcher.pool.close()


def _ids(result: dict) -> list[str]:
    return [r["chunk_id"] for r in result["results"]]


def test_search_ranks_by_cosine(searcher: s.Searcher) -> None:
    res = searcher.search("void", s.Filters(), limit=2)
    assert _ids(res)[0] == "kjv/gen#Gen.1.2"
    top = res["results"][0]
    assert top["score"] == 1.0
    assert top["citation"] == "*Genesis* Gen.1.2"
    assert top["work"]["source_label"] == "King James Version"
    assert top["work"]["license"] == "public_domain"
    assert top["date_range"] == [-900, -400]
    assert "source_id" not in top["work"]
    assert res["next_offset"] == 2  # 4 searchable chunks


def test_translation_vector_match_appears_once(searcher: s.Searcher) -> None:
    res = searcher.search("faith", s.Filters(), limit=10)
    ids = _ids(res)
    assert ids[0] == "pta/hymns#Hymn.1.1" and ids.count("pta/hymns#Hymn.1.1") == 1
    top = res["results"][0]
    assert (top["matched"], top["score"], top["language"]) == ("translation", 1.0, "syc")
    assert top["translation"] == {"language": "eng", "text": "Our faith is true and glorious.",
                                  "model": "gpt-6.1-sol", "machine": True}
    assert top["work"]["authors"][0]["id"] == "ephrem-the-syrian"
    assert top["citation"].endswith(", *Hymns on Faith* Hymn.1.1")
    # The other vector of the chunk scores 0 but doesn't make it appear twice.
    assert len(ids) == len(set(ids)) == 4
    assert res["next_offset"] is None


def test_filters(searcher: s.Searcher) -> None:
    assert _ids(searcher.search("creation", s.Filters(language=["hbo"]))) == ["oshb/gen#Gen.1.1"]
    assert _ids(searcher.search("creation", s.Filters(author=["ephrem-the-syrian"]))) == [
        "pta/hymns#Hymn.1.1"]
    assert set(_ids(searcher.search("faith", s.Filters(author=["anonymous"])))) == {
        "kjv/gen#Gen.1.1", "kjv/gen#Gen.1.2", "oshb/gen#Gen.1.1"}
    assert _ids(searcher.search("void", s.Filters(date_from=300, date_to=400))) == [
        "pta/hymns#Hymn.1.1"]
    assert _ids(searcher.search("void", s.Filters(work=["oshb/gen"]))) == ["oshb/gen#Gen.1.1"]
    assert _ids(searcher.search("void", s.Filters(genre=["liturgical"]))) == []


def test_unpublishable_works_are_not_searchable(searcher: s.Searcher) -> None:
    assert "hudra/secret#H.1" not in _ids(searcher.search("unlicensed", s.Filters(), limit=50))


def test_pagination(searcher: s.Searcher) -> None:
    first = searcher.search("void", s.Filters(), limit=2)
    second = searcher.search("void", s.Filters(), limit=2, offset=2)
    assert len(_ids(first) + _ids(second)) == len(set(_ids(first) + _ids(second))) == 4
    assert second["next_offset"] is None


TIES = 30


def _add_ties(url: str) -> None:
    """TIES more KJV chunks whose vector is exactly that of Gen.1.2 ("void")."""
    import psycopg

    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO chunks (chunk_id, work_id, canonical_ref, chunk_index, language, text, "
            "date_range, date_confidence, out_of_period) SELECT 'kjv/gen#Tie.' || i, 'kjv/gen', "
            "'Tie.' || i, 100 + i, 'eng', 'tied', '[-900,-400]', 'approximate', false "
            "FROM generate_series(1, %s) i", (TIES,))
        conn.execute(
            "INSERT INTO chunk_vectors SELECT 'kjv/gen#Tie.' || i, kind, model_id, embedding, "
            "work_id, source_id, language, genre, author_ids, date_range, out_of_period "
            "FROM chunk_vectors, generate_series(1, %s) i WHERE chunk_id = 'kjv/gen#Gen.1.2'",
            (TIES,))


def _all_pages(searcher: s.Searcher, limit: int) -> list[str]:
    ids, offset = [], 0
    while offset is not None:
        res = searcher.search("void", s.Filters(), limit=limit, offset=offset)
        ids += _ids(res)
        offset = res["next_offset"]
    return ids


@pytest.mark.parametrize("forced_hnsw", [False, True])
def test_pagination_with_ties_is_stable(corpus_url: str, forced_hnsw: bool) -> None:
    _add_ties(corpus_url)
    # Forcing the HNSW index with the smallest ef_search makes the iterative,
    # relaxed-order scan return candidates in approximate order.
    settings = ({"enable_seqscan": "off", "enable_bitmapscan": "off", "enable_sort": "off"}
                if forced_hnsw else {})
    searcher = _searcher(corpus_url, ef_search=1 if forced_hnsw else s.EF_SEARCH, **settings)
    try:
        if forced_hnsw:
            with searcher.pool.connection() as conn:
                plan = "\n".join(r[0] for r in conn.execute(
                    "EXPLAIN SELECT chunk_id FROM chunk_vectors WHERE model_id = 1 "
                    "ORDER BY embedding <=> %s::halfvec LIMIT 5", (s._vec_literal(
                        np.eye(1, s.DIMS, fx.axis_of("kjv/gen", "Gen.1.2"))[0]),)))
            assert "chunk_vectors_hnsw_m1" in plan
        expected = 4 + TIES  # every searchable chunk, once
        for limit in (7, 3):  # pages smaller than the tie group
            ids = _all_pages(searcher, limit)
            assert len(ids) == len(set(ids)) == expected
            assert ids == _all_pages(searcher, limit)
        # The tied chunks come first (score 1), in chunk id order.
        first = searcher.search("void", s.Filters(), limit=s.MAX_LIMIT)
        assert _ids(first)[:TIES + 1] == sorted(
            ["kjv/gen#Gen.1.2", *(f"kjv/gen#Tie.{i}" for i in range(1, TIES + 1))])
    finally:
        searcher.pool.close()


def test_quoted_query_runs_keyword_search(searcher: s.Searcher) -> None:
    calls = []
    searcher.embedder = s.QueryEmbedder(lambda: calls.append(1) or StubClient(AXES))
    res = searcher.search('"the earth"', s.Filters())
    assert (res["mode"], res["phrases"], res["text"], res["total"]) == (
        "keyword", ["the earth"], "", 2)
    assert _ids(res) == ["kjv/gen#Gen.1.1", "kjv/gen#Gen.1.2"]
    assert calls == []  # a quote alone needs no query embedding
    first = res["results"][0]
    assert (first["matched"], first["score"], first["text_start"]) == ("phrase", None, 0)
    a, b = first["matches"][0]
    assert first["text"][a:b] == "the earth"
    assert first["citation"] == "*Genesis* Gen.1.1"


def test_keyword_matches_ignore_points_and_case(searcher: s.Searcher) -> None:
    res = searcher.search("«בראשית ברא»", s.Filters())
    top = res["results"][0]
    assert top["chunk_id"] == "oshb/gen#Gen.1.1"
    a, b = top["matches"][0]
    assert top["text"][a:b] == "בְּרֵאשִׁית בָּרָא"


def test_quote_with_free_text_ranks_by_meaning(searcher: s.Searcher) -> None:
    # Both KJV verses contain "the earth"; the free text points at Gen.1.2.
    res = searcher.search('"the earth" void', s.Filters())
    assert _ids(res) == ["kjv/gen#Gen.1.2", "kjv/gen#Gen.1.1"]
    assert res["results"][0]["score"] == 1.0
    assert res["text"] == "void"


def test_keyword_search_filters_and_pages(searcher: s.Searcher) -> None:
    assert _ids(searcher.search('"the earth"', s.Filters(language=["hbo"]))) == []
    first = searcher.search('"the earth"', s.Filters(), limit=1)
    assert (_ids(first), first["next_offset"], first["total"]) == (["kjv/gen#Gen.1.1"], 1, 2)
    second = searcher.search('"the earth"', s.Filters(), limit=1, offset=1)
    assert (_ids(second), second["next_offset"]) == (["kjv/gen#Gen.1.2"], None)


def test_unsearchable_queries(searcher: s.Searcher) -> None:
    with pytest.raises(s.QueryError):
        searcher.search('""', s.Filters())
    client = _client(searcher)
    r = client.get("/search", params={"q": '"in" principio'})
    assert r.status_code == 422
    assert "at least 3 letters" in r.json()["error"]
    assert client.get("/search", params={"q": '" "'}).status_code == 422


def test_search_endpoint_end_to_end(searcher: s.Searcher) -> None:
    r = _client(searcher).get("/search", params={"q": "syriac faith", "language": "syc"})
    assert r.status_code == 200
    assert [x["chunk_id"] for x in r.json()["results"]] == ["pta/hymns#Hymn.1.1"]
    assert r.json()["results"][0]["matched"] == "text"
