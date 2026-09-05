def test_settings_exposes_catalog_and_no_secrets(client):

    response = client.get("/api/v1/settings")

    assert response.status_code == 200
    body = response.json()

    assert [mode["id"] for mode in body["modes"]] == ["dense", "hybrid", "rerank", "mmr", "rewrite", "hyde"]
    assert [strategy["id"] for strategy in body["strategies"]] == ["heading", "fixed_size"]
    assert body["defaults"]["top_k"] >= 1
    assert body["generation"]["prompt_version"] == "v1"
    assert body["constants"]["rrf_k"] == 60
    assert ".pdf" in body["supported_extensions"]
    assert "gsk_" not in response.text
    assert "GROQ_API_KEY" not in response.text


def test_health(client):

    body = client.get("/health").json()

    assert body["status"] == "ok"
    assert body["index_chunks"] == 2
    assert body["index_ready"] is True
    assert isinstance(body["llm_configured"], bool)


def test_unknown_route_has_error_shape(client):

    response = client.get("/api/v1/nothing")

    assert response.status_code == 404
    assert set(response.json()) == {"detail", "request_id"}
