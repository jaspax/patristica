"""Tests for GET /search (api/search.py, #141).

The query embedder is stubbed. The database tests load ``tests/index_fixture``
into the Postgres of ``PATRISTICA_TEST_DATABASE_URL`` and skip without it.
"""

from __future__ import annotations

import logging
import re
import sys
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
                     "(date_range && int4range(%(date_from)s, %(date_to)s, '[]') "
                     "OR (date_range IS NULL AND work_id IN (SELECT work_id FROM works "
                     "WHERE author_date_range && int4range(%(date_from)s, %(date_to)s, "
                     "'[]'))))")
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

    def search(self, q, filters, limit, cursor):
        self.calls.append((q, filters, limit, cursor))
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
        ("date_from", "300"), ("out_of_period", "true"), ("limit", "5"), ("cursor", "WzIwXQ")])
    assert r.status_code == 200
    q, filters, limit, cursor = fake.calls[0]
    assert (q, limit, cursor) == ("faith", 5, "WzIwXQ")
    assert filters == s.Filters(language=["syc", "cop", "grc"], author=["anonymous"],
                                date_from=300, include_out_of_period=True)


@pytest.mark.parametrize("params", [
    {"q": "x" * (s.MAX_QUERY_CHARS + 1)}, {"q": ""}, {"q": "   "}, {},
    {"q": "x", "limit": s.MAX_LIMIT + 1}, {"q": "x", "cursor": "x" * (s.MAX_CURSOR_CHARS + 1)},
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

    r = _client(FakeSearcher(PhraseTooBroad("This phrase is too common to search: add more words."))
                ).get("/search", params={"q": '"et in"'})
    assert r.status_code == 422
    assert r.json() == {"error": "This phrase is too common to search: add more words."}


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
    "unlicensed": fx.axis_of("unlicensed/secret", "H.1"),
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
    cursor = s.Cursor.decode(res["next_cursor"])
    assert cursor == s.Cursor(2, ((s.pool_size(0, 2), cursor.levels[0][1], _ids(res)[1]),))


def test_translation_vector_match_appears_once(searcher: s.Searcher) -> None:
    res = searcher.search("faith", s.Filters(), limit=10)
    ids = _ids(res)
    assert ids[0] == "pta/hymns#Hymn.1.1" and ids.count("pta/hymns#Hymn.1.1") == 1
    top = res["results"][0]
    assert (top["matched"], top["score"], top["language"]) == ("translation", 1.0, "syc")
    # Hymn.1.2, after it, has no translation of its own.
    assert top["translation"] == {"language": "eng", "text": "Our faith is true and glorious.",
                                  "model": "gpt-6.1-sol", "machine": True,
                                  "before": None, "after": None, "work_id": None,
                                  "canonical_ref": None, "source_label": None, "edition": None}
    assert top["work"]["authors"][0]["id"] == "ephrem-the-syrian"
    assert top["citation"].endswith(", *Hymns on Faith* Hymn.1.1")
    # The other vector of the chunk scores 0 but doesn't make it appear twice.
    # (3 results: the two versions of Gen.1.1 are one.)
    assert len(ids) == len(set(ids)) == 3
    assert res["next_cursor"] is None


def test_filters(searcher: s.Searcher) -> None:
    assert _ids(searcher.search("creation", s.Filters(language=["hbo"]))) == ["oshb/gen#Gen.1.1"]
    assert _ids(searcher.search("creation", s.Filters(author=["ephrem-the-syrian"]))) == [
        "pta/hymns#Hymn.1.1"]
    assert set(_ids(searcher.search("faith", s.Filters(author=["anonymous"])))) == {
        "kjv/gen#Gen.1.1", "kjv/gen#Gen.1.2"}  # oshb/gen#Gen.1.1 is a version of the first
    assert _ids(searcher.search("void", s.Filters(date_from=300, date_to=400))) == [
        "pta/hymns#Hymn.1.1"]
    assert _ids(searcher.search("void", s.Filters(work=["oshb/gen"]))) == ["oshb/gen#Gen.1.1"]
    assert _ids(searcher.search("void", s.Filters(genre=["liturgical"]))) == []


def test_date_filter_matches_an_undated_work_by_its_authors_dates(
        searcher: s.Searcher, corpus_url: str) -> None:
    """A work with no date of its own matches through ``works.author_date_range`` (#151)."""
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(corpus_url, autocommit=True) as conn:
        conn.execute("UPDATE works SET date_range = NULL, author_date_range = '[300,330]' "
                     "WHERE work_id = 'oshb/gen'")
        conn.execute("UPDATE chunks SET date_range = NULL WHERE work_id = 'oshb/gen'")
        conn.execute("UPDATE chunk_vectors SET date_range = NULL WHERE work_id = 'oshb/gen'")
    assert set(_ids(searcher.search("void", s.Filters(date_from=300, date_to=400)))) == {
        "pta/hymns#Hymn.1.1", "oshb/gen#Gen.1.1"}
    assert _ids(searcher.search("void", s.Filters(date_from=340, date_to=400))) == [
        "pta/hymns#Hymn.1.1"]
    # A work's own date wins: the author range of a dated work is never consulted.
    with psycopg.connect(corpus_url, autocommit=True) as conn:
        conn.execute("UPDATE works SET author_date_range = '[300,330]' WHERE work_id = 'kjv/gen'")
    assert "kjv/gen#Gen.1.2" not in _ids(searcher.search("void", s.Filters(date_from=300,
                                                                            date_to=330)))


def test_unpublishable_works_are_not_searchable(searcher: s.Searcher) -> None:
    assert "unlicensed/secret#H.1" not in _ids(searcher.search("unlicensed", s.Filters(), limit=50))


def test_pagination(searcher: s.Searcher) -> None:
    first = searcher.search("void", s.Filters(), limit=2)
    second = searcher.search("void", s.Filters(), limit=2, cursor=first["next_cursor"])
    assert len(_ids(first) + _ids(second)) == len(set(_ids(first) + _ids(second))) == 3
    assert second["next_cursor"] is None


def test_cursor_round_trip() -> None:
    for cursor in (s.Cursor(), s.Cursor(20),
                   s.Cursor(40, ((168, 0.123456789012345, "kjv/gen#Gen.1.2"),
                                 (336, 0.2, "kjv/gen#Gen.1.3"))),
                   s.Cursor(1, ((16, -0.5, "pta/ἅγιος#1.1"),))):
        token = cursor.encode()
        assert "=" not in token and "/" not in token and "+" not in token
        assert s.Cursor.decode(token) == cursor


@pytest.mark.parametrize("token", [
    "!", "bm90IGpzb24", s.Cursor(s.MAX_DEPTH + 1).encode(), s.Cursor(-1).encode(),
    "eyJhIjoxfQ",  # {"a":1}
    "WzEsIngiLCJ5Il0",  # [1,"x","y"]
    "WzEuNV0",  # [1.5]
    s.Cursor(1, ((s.MAX_POOL + 1, 0.5, "x"),)).encode(),
    s.Cursor(1, ((32, 0.5, "x"), (16, 0.6, "y"))).encode(),  # pools must grow
    s.Cursor(1, ((16, 0.5, "x"), (16, 0.6, "y"))).encode(),
])
def test_bad_cursors_are_query_errors(token: str) -> None:
    with pytest.raises(s.QueryError):
        s.Cursor.decode(token)


def test_cursor_of_the_other_mode_is_refused(searcher: s.Searcher) -> None:
    vector_cursor = searcher.search("void", s.Filters(), limit=1)["next_cursor"]
    with pytest.raises(s.QueryError):
        searcher.search('"the earth"', s.Filters(), cursor=vector_cursor)
    with pytest.raises(s.QueryError):
        searcher.search("void", s.Filters(), cursor=s.Cursor(1).encode())
    r = _client(searcher).get("/search", params={"q": "void", "cursor": "!"})
    assert r.status_code == 422 and "cursor" in r.json()["error"]


def test_pages_scan_the_first_pages_pool(searcher: s.Searcher,
                                         caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="api.search")
    first = searcher.search("void", s.Filters(), limit=1)
    searcher.search("void", s.Filters(), limit=1, cursor=first["next_cursor"])
    pools = [int(m) for m in re.findall(r"pool (\d+)", caplog.text)]
    assert pools == [s.pool_size(0, 1)] * 2


def test_a_short_pool_doubles(corpus_url: str, caplog: pytest.LogCaptureFixture,
                              monkeypatch: pytest.MonkeyPatch) -> None:
    # 20 passages in 12 versions each: 8 rows a result fold into too few results.
    monkeypatch.setattr(sys.modules[__name__], "GROUP_SIZE", 12)
    _add_tied_groups(corpus_url)
    searcher = _searcher(corpus_url)
    try:
        caplog.set_level(logging.INFO, logger="api.search")
        res = searcher.search("void", s.Filters(), limit=10)
        assert len(res["results"]) == 10
        pool = int(re.findall(r"pool (\d+)", caplog.text)[-1])
        assert pool == s.pool_size(0, 10) * 2
        assert s.Cursor.decode(res["next_cursor"]).levels[-1][0] == pool
    finally:
        searcher.pool.close()


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
    ids, cursor = [], None
    while True:
        res = searcher.search("void", s.Filters(), limit=limit, cursor=cursor)
        ids += _ids(res)
        cursor = res["next_cursor"]
        if cursor is None:
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
        expected = 3 + TIES  # every searchable passage, once
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


# --- folding versions of a passage (#180) ---------------------------------

# Versions added to the fixture's Gen.1.1 group (kjv/gen and oshb/gen are in it
# already): (work_id, source_id, language, edition, text, score for "creation").
VERSIONS = [
    ("clementine/gen", "clementine", "lat", "Clementine Vulgate (1592)",
     "In principio creavit Deus caelum et terram.", 0.8),
    ("lxx-rahlfs/gen", "lxx-rahlfs", "grc", "Rahlfs (1935)",
     "Ἐν ἀρχῇ ἐποίησεν ὁ θεὸς τὸν οὐρανὸν καὶ τὴν γῆν.", 0.6),
    ("asv/gen", "asv", "eng", "American Standard Version (1901)",
     "In the beginning God created the heavens and the earth.", 0.5),
]
SPARE_AXIS = 400  # no fixture vector uses it


def _toward(axis: int, score: float) -> str:
    """A unit vector whose cosine similarity to basis *axis* is *score*."""
    vec = np.zeros(s.DIMS, dtype=np.float32)
    vec[axis], vec[SPARE_AXIS] = score, (1 - score * score) ** 0.5
    return s._vec_literal(vec)


def _insert_chunk(conn: Any, work_id: str, source_id: str, language: str, edition: str,
                  ref: str, text: str, group: str | None, embedding: str) -> None:
    from patristica.keyword import index_text

    conn.execute(
        "INSERT INTO works (work_id, source_id, title, date_range, date_confidence, genre, "
        "language, license, edition, path, content_sha) VALUES (%s, %s, 'Genesis', "
        "'[-900,-400]', 'approximate', 'scripture', %s, 'public_domain', %s, 'x', 'x') "
        "ON CONFLICT DO NOTHING", (work_id, source_id, language, edition))
    cid = fx.chunk_id(work_id, ref)
    conn.execute(
        "INSERT INTO chunks (chunk_id, work_id, canonical_ref, chunk_index, language, text, "
        "date_range, date_confidence, out_of_period, translation_group_id, text_folded) "
        "VALUES (%s, %s, %s, 0, %s, %s, '[-900,-400]', 'approximate', false, %s, %s)",
        (cid, work_id, ref, language, text, group, index_text(text)))
    conn.execute(
        "INSERT INTO chunk_vectors SELECT %s, 0, model_id, %s::halfvec, %s, %s, %s, "
        "'scripture', '{}', '[-900,-400]', false FROM embedding_models", (
            cid, embedding, work_id, source_id, language))


@pytest.fixture
def versions_url(corpus_url: str) -> str:
    """The corpus with three more versions of Gen.1.1."""
    import psycopg

    axis = fx.axis_of("kjv/gen", "Gen.1.1")
    with psycopg.connect(corpus_url, autocommit=True) as conn:
        assert conn.execute("SELECT count(*) FROM chunks WHERE translation_group_id = "
                            "'Gen.1.1'").fetchone() == (2,)  # kjv and oshb, from the loader
        for work_id, source_id, language, edition, text, score in VERSIONS:
            _insert_chunk(conn, work_id, source_id, language, edition, "Gen.1.1", text,
                          "Gen.1.1", _toward(axis, score))
    return corpus_url


@pytest.fixture
def versions(versions_url: str):
    searcher = _searcher(versions_url)
    try:
        yield searcher
    finally:
        searcher.pool.close()


def _versions(result: dict) -> list[str]:
    return [v["chunk_id"] for v in result["versions"]]


def _rounded(versions: list[dict]) -> list[dict]:
    """*versions* with scores to 2 places (halfvec storage rounds 0.8 to 0.7999)."""
    return [{**v, "score": None if v["score"] is None else round(v["score"], 2)}
            for v in versions]


def test_vector_search_folds_versions(versions: s.Searcher) -> None:
    res = versions.search("creation", s.Filters(), limit=10)
    ids = _ids(res)
    # One result per passage: Gen.1.1 (5 versions), Gen.1.2, Hymn.1.1.
    assert len(ids) == 3 and ids[0] == "kjv/gen#Gen.1.1"
    top = res["results"][0]
    assert top["score"] == 1.0 and top["work"]["source_label"] == "King James Version"
    # The other versions, best first, as the API shows them (no source ids).
    assert _rounded(top["versions"]) == [
        {"chunk_id": "clementine/gen#Gen.1.1", "work_id": "clementine/gen",
         "canonical_ref": "Gen.1.1", "language": "lat", "source_label": "Clementine Vulgate",
         "edition": "Clementine Vulgate (1592)", "score": 0.8},
        {"chunk_id": "lxx-rahlfs/gen#Gen.1.1", "work_id": "lxx-rahlfs/gen",
         "canonical_ref": "Gen.1.1", "language": "grc", "source_label": "Septuagint (Rahlfs)",
         "edition": "Rahlfs (1935)", "score": 0.6},
        {"chunk_id": "asv/gen#Gen.1.1", "work_id": "asv/gen", "canonical_ref": "Gen.1.1",
         "language": "eng", "source_label": "American Standard Version",
         "edition": "American Standard Version (1901)", "score": 0.5},
        {"chunk_id": "oshb/gen#Gen.1.1", "work_id": "oshb/gen", "canonical_ref": "Gen.1.1",
         "language": "hbo", "source_label": "Open Scriptures Hebrew Bible",
         "edition": "Open Scriptures Hebrew Bible", "score": 0.0},
    ]
    # Passages without other versions have none.
    assert [r["versions"] for r in res["results"][1:]] == [[], []]


def test_search_folds_by_passage_groups(corpus_url: str) -> None:
    """Passage alignment groups (#179) fold any work's versions, and come before verse groups."""
    import psycopg

    with psycopg.connect(corpus_url, autocommit=True) as conn:
        conn.execute("INSERT INTO passage_groups VALUES ('kjv/gen#Gen.1.2', 'g@0', 9), "
                     "('pta/hymns#Hymn.1.1', 'g@0', 9), ('kjv/gen#Gen.1.1', 'g@1', 9)")
    searcher = _searcher(corpus_url)
    try:
        top = searcher.search("void", s.Filters())["results"][0]
        assert (top["chunk_id"], _versions(top)) == ("kjv/gen#Gen.1.2", ["pta/hymns#Hymn.1.1"])
        # KJV Gen 1:1 is in a passage group of its own now, so the Hebrew verse,
        # still in verse group Gen.1.1, is no longer folded with it.
        res = searcher.search("creation", s.Filters(), limit=10)
        assert all(v["chunk_id"] != "oshb/gen#Gen.1.1"
                   for r in res["results"] if r["chunk_id"] == "kjv/gen#Gen.1.1"
                   for v in r["versions"])
        keyword = searcher.search('"the earth"', s.Filters())
        assert keyword["total"] == 2
    finally:
        searcher.pool.close()


def test_vector_lead_is_the_best_scoring_version(versions: s.Searcher) -> None:
    top = versions.search("hebrew creation", s.Filters())["results"][0]
    assert (top["chunk_id"], top["language"], top["score"]) == ("oshb/gen#Gen.1.1", "hbo", 1.0)
    assert set(_versions(top)) == {"kjv/gen#Gen.1.1", "clementine/gen#Gen.1.1",
                                   "lxx-rahlfs/gen#Gen.1.1", "asv/gen#Gen.1.1"}


def test_vector_filters_apply_before_folding(versions: s.Searcher) -> None:
    # Only Latin: the Vulgate verse is a result of its own, with no versions.
    res = versions.search("creation", s.Filters(language=["lat"]))
    assert _ids(res) == ["clementine/gen#Gen.1.1"] and res["results"][0]["versions"] == []
    assert res["results"][0]["score"] == pytest.approx(0.8, abs=1e-3)
    # Latin and Greek: the Vulgate leads, the Septuagint is its version.
    top = versions.search("creation", s.Filters(language=["lat", "grc"]))["results"][0]
    assert (top["chunk_id"], _versions(top)) == ("clementine/gen#Gen.1.1",
                                                 ["lxx-rahlfs/gen#Gen.1.1"])
    # A source filter keeps out the other sources' versions too.
    top = versions.search("creation", s.Filters(source=["kjv", "asv"]))["results"][0]
    assert (top["chunk_id"], _versions(top)) == ("kjv/gen#Gen.1.1", ["asv/gen#Gen.1.1"])


GROUPS, GROUP_SIZE = 20, 3


def _add_tied_groups(url: str) -> None:
    """GROUPS passages of GROUP_SIZE versions each, every vector that of Gen.1.2 ("void")."""
    import psycopg

    void = _toward(fx.axis_of("kjv/gen", "Gen.1.2"), 1.0)
    with psycopg.connect(url, autocommit=True) as conn:
        for g in range(GROUPS):
            for v in range(GROUP_SIZE):
                _insert_chunk(conn, f"ed{v}/gen", f"ed{v}", "eng", f"Edition {v}",
                              f"Tie.{g}", "tied", f"Tie.{g}", void)


@pytest.mark.parametrize("forced_hnsw", [False, True])
@pytest.mark.parametrize("group_size", [GROUP_SIZE, 12])  # 12: pages cross pool doublings
def test_folded_pagination_with_ties_is_stable(corpus_url: str, forced_hnsw: bool,
                                               group_size: int,
                                               monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.modules[__name__], "GROUP_SIZE", group_size)
    _add_tied_groups(corpus_url)
    settings = ({"enable_seqscan": "off", "enable_bitmapscan": "off", "enable_sort": "off"}
                if forced_hnsw else {})
    searcher = _searcher(corpus_url, ef_search=1 if forced_hnsw else s.EF_SEARCH, **settings)
    try:
        expected = 3 + GROUPS  # every passage once
        for limit in (7, 2):  # pages smaller than the tie group
            ids = _all_pages(searcher, limit)
            assert len(ids) == len(set(ids)) == expected
            assert ids == _all_pages(searcher, limit)
        res = searcher.search("void", s.Filters(), limit=s.MAX_LIMIT)
        tied = [r for r in res["results"] if r["canonical_ref"].startswith("Tie.")]
        assert len(tied) == GROUPS
        for r in tied:
            # Every version scores 1: the lowest chunk id leads, the others follow in order.
            assert r["chunk_id"] == f"ed0/gen#{r['canonical_ref']}"
            # (As sets: the database's collation orders ed10 before ed1/.)
            assert set(_versions(r)) == {f"ed{v}/gen#{r['canonical_ref']}"
                                         for v in range(1, GROUP_SIZE)}
            assert {v["score"] for v in r["versions"]} == {1.0}
    finally:
        searcher.pool.close()


def test_pool_has_room_for_folded_versions() -> None:
    # Each result up to the page can take FOLD_ROWS passages' worth of rows (text
    # and translation vectors) from the pool, with one result to spare.
    assert s.pool_size(0, 20) == s.FOLD_ROWS * 2 * 21 == 168
    assert s.pool_size(s.MAX_DEPTH, s.MAX_LIMIT) == s.FOLD_ROWS * 2 * (s.MAX_DEPTH + s.MAX_LIMIT + 1)
    assert s.FOLD_ROWS > 1


def test_no_cursor_past_the_depth_cap(searcher: s.Searcher) -> None:
    res = searcher.search("void", s.Filters(), limit=1,
                          cursor=s.Cursor(s.MAX_DEPTH, ((16, -1.0, ""),)).encode())
    assert res["results"] and res["next_cursor"] is None


def test_keyword_search_folds_versions(versions: s.Searcher) -> None:
    # KJV and ASV both have "in the beginning": one passage.
    res = versions.search('"in the beginning"', s.Filters())
    assert res["total"] == 1
    top = res["results"][0]
    # Same rank (Scripture, same date): the first work id leads.
    assert top["chunk_id"] == "asv/gen#Gen.1.1" and top["matches"]
    assert top["versions"] == [
        {"chunk_id": "kjv/gen#Gen.1.1", "work_id": "kjv/gen", "canonical_ref": "Gen.1.1",
         "language": "eng", "source_label": "King James Version",
         "edition": "King James Version (1769)", "score": None}]
    # The total counts folded results, and pages are cut from them.
    res = versions.search('"the earth"', s.Filters(), limit=1)
    assert (_ids(res), res["total"]) == (["asv/gen#Gen.1.1"], 2)
    assert s.Cursor.decode(res["next_cursor"]) == s.Cursor(1)
    res = versions.search('"the earth"', s.Filters(), limit=1, cursor=res["next_cursor"])
    assert (_ids(res), res["total"], res["next_cursor"]) == (["kjv/gen#Gen.1.2"], 2, None)
    assert res["results"][0]["versions"] == []


def test_keyword_filters_apply_before_folding(versions: s.Searcher) -> None:
    res = versions.search('"in the beginning"', s.Filters(source=["kjv"]))
    assert (_ids(res), res["total"]) == (["kjv/gen#Gen.1.1"], 1)
    assert res["results"][0]["versions"] == []


def test_ranked_keyword_lead_is_the_closest_version(versions: s.Searcher) -> None:
    # Free text ranks the matches: KJV is closer to "creation" than ASV (1.0 vs 0.5).
    res = versions.search('"in the beginning" creation', s.Filters())
    assert (_ids(res), res["total"]) == (["kjv/gen#Gen.1.1"], 1)
    top = res["results"][0]
    assert top["score"] == 1.0
    assert [(v["chunk_id"], v["score"]) for v in _rounded(top["versions"])] == [
        ("asv/gen#Gen.1.1", 0.5)]


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
    assert (_ids(first), first["total"]) == (["kjv/gen#Gen.1.1"], 2)
    second = searcher.search('"the earth"', s.Filters(), limit=1, cursor=first["next_cursor"])
    assert (_ids(second), second["next_cursor"]) == (["kjv/gen#Gen.1.2"], None)


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
