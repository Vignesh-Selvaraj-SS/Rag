"""
Unit tests for HttpRetrieverProxy (mcp_servers/http_retriever_proxy.py)
against a mocked HTTP transport - no live main app, no network, and
critically no Qdrant dependency at all, which is the entire point of this
class existing (see its module docstring for the conflict it avoids).
"""

import httpx
import pytest

from mcp_servers.http_retriever_proxy import HttpRetrieverProxy

SEARCH_RESPONSE_BODY = {
    "question": "water backup deductible",
    "hits": [
        {
            "rank": 1, "chunk_id": "endorsement-HO-2026-01-water-backup.md::1",
            "source": "endorsement-HO-2026-01-water-backup.md", "heading": "Deductible",
            "page": "p.1", "score": 0.85, "dense_score": 0.85,
            "text": "A separate deductible of $500 applies to each water backup occurrence.",
        }
    ],
    "best_score": 0.85,
    "passes_gate": True,
    "min_score": 0.6,
}


def _mock_post(monkeypatch, handler):
    """Redirects httpx.post (the proxy's only network call) through a MockTransport, no real socket involved."""

    transport = httpx.MockTransport(handler)

    def fake_post(url, **kwargs):
        with httpx.Client(transport=transport) as client:
            return client.post(url, **kwargs)

    monkeypatch.setattr(httpx, "post", fake_post)


def test_retrieve_calls_the_search_endpoint_and_returns_a_retrieval_service_shaped_dict(monkeypatch):

    captured_url = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured_url["value"] = str(request.url)
        return httpx.Response(200, json=SEARCH_RESPONSE_BODY)

    _mock_post(monkeypatch, handler)

    proxy = HttpRetrieverProxy(base_url="http://testserver")
    result = proxy.retrieve("water backup deductible", top_k=5, source=None, mode="hybrid")

    assert captured_url["value"] == "http://testserver/api/v1/search"
    assert result["hits"] == SEARCH_RESPONSE_BODY["hits"]
    assert result["best_score"] == 0.85
    assert result["passes_gate"] is True
    assert result["min_score"] == 0.6


def test_retrieve_sends_the_requested_params_in_the_json_body(monkeypatch):

    import json

    seen_body = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_body.update(json.loads(request.content))
        return httpx.Response(200, json=SEARCH_RESPONSE_BODY)

    _mock_post(monkeypatch, handler)

    proxy = HttpRetrieverProxy(base_url="http://testserver")
    proxy.retrieve("deductible", top_k=3, min_score=0.7, source="a.md", mode="rerank")

    assert seen_body == {"question": "deductible", "mode": "rerank", "top_k": 3, "min_score": 0.7, "source": "a.md"}


def test_retrieve_omits_unset_optional_params_from_the_json_body(monkeypatch):

    import json

    seen_body = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen_body.update(json.loads(request.content))
        return httpx.Response(200, json=SEARCH_RESPONSE_BODY)

    _mock_post(monkeypatch, handler)

    proxy = HttpRetrieverProxy(base_url="http://testserver")
    proxy.retrieve("deductible")

    assert seen_body == {"question": "deductible", "mode": "dense"}


def test_retrieve_raises_a_clear_error_when_the_main_app_is_unreachable(monkeypatch):

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _mock_post(monkeypatch, handler)

    proxy = HttpRetrieverProxy(base_url="http://testserver")

    with pytest.raises(RuntimeError, match="uvicorn app.main:app"):
        proxy.retrieve("anything")


def test_retrieve_raises_on_a_non_200_response(monkeypatch):

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"detail": "boom"})

    _mock_post(monkeypatch, handler)

    proxy = HttpRetrieverProxy(base_url="http://testserver")

    with pytest.raises(RuntimeError):
        proxy.retrieve("anything")
