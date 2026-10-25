"""Tests for scripts.ingest.hudra (offline: Firestore is mocked)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx
import pytest

from scripts.ingest import hudra


def _doc(fields: dict) -> dict:
    def value(v: object) -> dict:
        if isinstance(v, str):
            return {"stringValue": v}
        if isinstance(v, int):
            return {"integerValue": str(v)}
        if isinstance(v, list):
            return {"arrayValue": {"values": [value(x) for x in v]}}
        assert isinstance(v, dict)
        return {"mapValue": {"fields": {k: value(x) for k, x in v.items()}}}
    return {"fields": {k: value(v) for k, v in fields.items()}}


def _page_text(text: str) -> dict:
    return {"type": "doc", "content": [{"type": "paragraph",
                                        "content": [{"type": "text", "text": text}]}]}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hudra.time, "sleep", lambda s: None)


def _client(responses: dict[str, list[httpx.Response]]) -> httpx.Client:
    """A client answering each document path with its responses in turn."""
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path.split("/documents/", 1)[1]
        queue = responses[path]
        return queue.pop(0) if len(queue) > 1 else queue[0]
    return httpx.Client(transport=httpx.MockTransport(handler))


def _book(slug: str, pages: int) -> httpx.Response:
    return httpx.Response(200, json=_doc({
        "title": "Taksa d'Raze Editio Typica",
        "author": "Congregation for the Oriental Churches",
        "pages": [{"pageId": f"p{n}", "pageNumber": n} for n in range(1, pages + 1)],
    }))


def test_fetch_doc_retries_server_errors() -> None:
    ok = httpx.Response(200, json=_doc({"a": "b"}))
    client = _client({"pages/p1": [httpx.Response(503), ok]})
    assert hudra._fetch_doc(client, "pages/p1") == {"a": "b"}


def test_fetch_doc_gives_up_on_client_errors() -> None:
    client = _client({"pages/p1": [httpx.Response(404)]})
    assert hudra._fetch_doc(client, "pages/p1") is None


def test_ingest_book_licence_and_failed_page(tmp_path: Path, caplog: pytest.LogCaptureFixture
                                             ) -> None:
    conf = hudra._BOOKS[1]
    client = _client({
        f"books/{conf['slug']}": [_book(conf["slug"], 3)],
        "pages/p1": [httpx.Response(200, json=_doc({"currentTextJson": _page_text("ܫܘܒܚܐ")}))],
        "pages/p2": [httpx.Response(200, json=_doc({"currentTextJson": {"type": "doc"}}))],
        "pages/p3": [httpx.Response(500)],
    })
    with caplog.at_level(logging.ERROR):
        work = hudra._ingest_book(client, conf, tmp_path, force=True)
    assert work is not None
    assert work.license == "used-with-permission"
    assert work.work_id == "hudra/taksa-draze-2003"
    assert "used with permission" in (work.edition or "")
    # Page 2 is untranscribed (skipped quietly); page 3 failed, which is an ERROR (no stamp).
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == [
        f"{conf['slug']}: page 3 (p3) could not be fetched; left out"]
    data = json.loads((tmp_path / "taksa-draze-2003.json").read_text(encoding="utf-8"))
    assert data["paragraphs"] == [{"ref": "EastSyrLit.Taksa.001", "text": "ܫܘܒܚܐ"}]
