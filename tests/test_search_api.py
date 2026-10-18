"""Tests for GET /search (api/search.py, #141).

The query embedder is stubbed. The database tests load ``tests/index_fixture``
into the Postgres of ``PATRISTICA_TEST_DATABASE_URL`` and skip without it.
"""

from __future__ import annotations

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


@pytest.mark.parametrize("q, expected", [
    ("  grace   and\nfaith ", s.ParsedQuery("vector", "grace and faith")),
    ('"in the beginning"', s.ParsedQuery("phrase", "in the beginning")),
    ("“in  principio”", s.ParsedQuery("phrase", "in principio")),
    ('""', s.ParsedQuery("vector", '""')),
    ('the "word" made flesh', s.ParsedQuery("vector", 'the "word" made flesh')),
])
def test_parse_query(q: str, expected: s.ParsedQuery) -> None:
    assert s.parse_query(q) == expected


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


def test_search_rate_limited() -> None:
    client = _client(FakeSearcher(), s.RateLimiter(rate=6, burst=1))
    assert client.get("/search", params={"q": "a"}).status_code == 200
    r = client.get("/search", params={"q": "a"})
    assert r.status_code == 429
    assert r.headers["retry-after"] == "10"


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


@pytest.fixture
def searcher(pg_url: str, tmp_path: Path):
    from psycopg_pool import ConnectionPool

    fx.load_corpus(tmp_path, pg_url)
    pool = ConnectionPool(pg_url, min_size=1, max_size=2, open=True)
    try:
        yield s.Searcher(pool, s.QueryEmbedder(lambda: StubClient(AXES)))
    finally:
        pool.close()


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


def test_phrase_query_falls_back_to_vector(searcher: s.Searcher) -> None:
    res = searcher.search('"void"', s.Filters(), limit=1)
    assert (res["mode"], res["requested_mode"], _ids(res)) == (
        "vector", "phrase", ["kjv/gen#Gen.1.2"])


def test_search_endpoint_end_to_end(searcher: s.Searcher) -> None:
    r = _client(searcher).get("/search", params={"q": "syriac faith", "language": "syc"})
    assert r.status_code == 200
    assert [x["chunk_id"] for x in r.json()["results"]] == ["pta/hymns#Hymn.1.1"]
    assert r.json()["results"][0]["matched"] == "text"
