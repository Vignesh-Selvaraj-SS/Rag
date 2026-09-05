"""How the app serves the built frontend next to the API."""

from fastapi.testclient import TestClient

from app.api import deps
from app.main import create_app


class _StubRag:
    def chunk_count(self) -> int:
        return 0


def _client(frontend_dist) -> TestClient:
    # Never let these tests open the real embedded Qdrant store.
    app = create_app(frontend_dist=frontend_dist)
    app.dependency_overrides[deps.rag_service] = _StubRag
    return TestClient(app)


def test_without_a_frontend_build_root_describes_the_api(tmp_path):

    client = _client(tmp_path / "missing")

    body = client.get("/").json()

    assert body["docs"] == "/docs"
    assert "frontend" in body


def test_with_a_frontend_build_spa_routes_fall_back_to_index(tmp_path):

    (tmp_path / "index.html").write_text("<!doctype html><title>RAG</title>", encoding="utf-8")
    (tmp_path / "main.js").write_text("console.log(1)", encoding="utf-8")

    client = _client(tmp_path)

    assert client.get("/").text.startswith("<!doctype html>")
    assert client.get("/main.js").text == "console.log(1)"
    # A client-side route reloads to index.html ...
    assert client.get("/developer/traces/t_1").text.startswith("<!doctype html>")
    # ... but an unknown API path stays a JSON 404 with the standard shape.
    response = client.get("/api/v1/nothing")
    assert response.status_code == 404
    assert set(response.json()) == {"detail", "request_id"}
    assert client.get("/health").status_code == 200
