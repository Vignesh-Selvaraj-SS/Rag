def test_chat_returns_answer_with_cited_sources_only(client):

    response = client.post("/api/v1/chat", json={"question": "What deductible applies?"})

    assert response.status_code == 200
    body = response.json()

    assert body["refused"] is False
    assert body["refused_by"] is None
    assert body["mode"] == "dense"
    assert body["trace_id"].startswith("t_")
    assert body["debug"] is None
    assert [source["chunk_id"] for source in body["sources"]] == [
        "endorsement-HO-2026-01-water-backup.md::4",
        "policy-base-HO3-2026.md::7",
    ]
    assert body["sources"][0]["rank"] == 1
    assert response.headers["X-Request-ID"]


def test_chat_debug_includes_retrieved_chunks_params_and_invalid_citations(client):

    response = client.post(
        "/api/v1/chat",
        json={"question": "What deductible applies?", "include_debug": True, "mode": "hybrid", "top_k": 1},
    )

    assert response.status_code == 200
    debug = response.json()["debug"]

    assert [hit["chunk_id"] for hit in debug["retrieved"]] == ["endorsement-HO-2026-01-water-backup.md::4"]
    assert debug["params"] == {
        "mode": "hybrid",
        "top_k": 1,
        "min_score": 0.6,
        "source_filter": None,
        "temperature": 0.0,
        "max_tokens": 800,
    }
    assert debug["invalid_citations"] == ["[S9]"]
    assert debug["passes_gate"] is True
    assert debug["prompt_version"] == "v1"


def test_chat_refused_by_gate_makes_no_model_call(client, services):

    response = client.post("/api/v1/chat", json={"question": "Who won the football world cup?"})

    assert response.status_code == 200
    body = response.json()

    assert body["refused"] is True
    assert body["refused_by"] == "gate"
    assert body["sources"] == []
    assert body["answer"].startswith("I don't know")


def test_chat_refused_by_model(client):

    response = client.post("/api/v1/chat", json={"question": "Please refuse this one"})

    body = response.json()

    assert body["refused"] is True
    assert body["refused_by"] == "model"


def test_chat_records_a_trace(client, services):

    client.post("/api/v1/chat", json={"question": "What deductible applies for claimant Maria Delgado?"})

    traces = services["traces"].load_all()

    assert len(traces) == 1
    assert traces[0]["question"] == "What deductible applies for claimant [CLAIMANT]?"
    assert traces[0]["identifiers_redacted"] == 1
    assert traces[0]["origin"] == "chat"


def test_chat_passes_retrieval_overrides_through(client, services):

    client.post(
        "/api/v1/chat",
        json={
            "question": "What deductible applies?",
            "mode": "mmr",
            "top_k": 3,
            "min_score": 0.5,
            "source": "policy-base-HO3-2026.md",
        },
    )

    call = services["rag"].retriever.calls[-1]

    assert call == {
        "question": "What deductible applies?",
        "top_k": 3,
        "min_score": 0.5,
        "source": "policy-base-HO3-2026.md",
        "mode": "mmr",
    }


def test_chat_validates_input(client):

    assert client.post("/api/v1/chat", json={"question": ""}).status_code == 422
    assert client.post("/api/v1/chat", json={"question": "x", "mode": "magic"}).status_code == 422
    assert client.post("/api/v1/chat", json={"question": "x", "top_k": 0}).status_code == 422

    body = client.post("/api/v1/chat", json={"question": "x", "min_score": 2}).json()
    assert body["detail"].startswith("min_score")
    assert "request_id" in body


def test_chat_with_empty_index_returns_503(client, services):

    services["rag"].retriever.vector_store._count = 0

    response = client.post("/api/v1/chat", json={"question": "anything"})

    assert response.status_code == 503
    assert "indexed" in response.json()["detail"]


def test_chat_without_llm_key_returns_503(client, services):

    services["rag"].llm.configured = False

    response = client.post("/api/v1/chat", json={"question": "anything"})

    assert response.status_code == 503
    assert "GROQ_API_KEY" in response.json()["detail"]


def test_search_returns_hits_without_generating(client, services):

    response = client.post("/api/v1/search", json={"question": "deductible", "mode": "hybrid"})

    assert response.status_code == 200
    body = response.json()

    assert len(body["hits"]) == 2
    assert body["hits"][0]["rank"] == 1
    assert body["passes_gate"] is True
    assert body["min_score"] == 0.6
    assert body["mode"] == "hybrid"
    assert services["traces"].load_all() == []


def test_search_below_gate(client):

    body = client.post("/api/v1/search", json={"question": "football"}).json()

    assert body["hits"] == []
    assert body["passes_gate"] is False
