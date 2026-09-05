def _ask(client, question, **extra):
    response = client.post("/api/v1/chat", json={"question": question, **extra})
    assert response.status_code == 200
    return response.json()


def test_trace_list_detail_and_checks(client):

    answered = _ask(client, "What deductible applies?")
    _ask(client, "Please refuse this one", mode="hybrid")
    _ask(client, "football scores")

    listed = client.get("/api/v1/traces").json()

    assert listed["total"] == 3
    assert {item["refused_by"] for item in listed["items"]} == {None, "model", "gate"}

    detail = client.get(f"/api/v1/traces/{answered['trace_id']}").json()

    assert detail["question"] == "What deductible applies?"
    assert detail["params"]["mode"] == "dense"
    assert detail["retrieved"][0]["rank"] == 1
    assert detail["cited_chunk_ids"] == [
        "endorsement-HO-2026-01-water-backup.md::4",
        "policy-base-HO3-2026.md::7",
    ]
    checks = {check["id"]: check["status"] for check in detail["checks"]}
    assert checks == {
        "refusal": "pass",
        "output_complete": "pass",
        "citation_present": "pass",
        "no_invalid_citations": "fail",
    }
    assert detail["check_status"] == "fail"


def test_trace_filters(client):

    _ask(client, "What deductible applies?")
    _ask(client, "Please refuse this one", mode="hybrid")

    assert client.get("/api/v1/traces", params={"refused": "true"}).json()["total"] == 1
    assert client.get("/api/v1/traces", params={"mode": "hybrid"}).json()["total"] == 1
    assert client.get("/api/v1/traces", params={"search": "deductible"}).json()["total"] == 1
    assert client.get("/api/v1/traces", params={"limit": 1}).json()["items"].__len__() == 1


def test_trace_stats(client):

    _ask(client, "What deductible applies?")
    _ask(client, "Please refuse this one")
    _ask(client, "football")

    stats = client.get("/api/v1/traces/stats").json()

    assert stats["total"] == 3
    assert stats["answered"] == 1
    assert stats["refused"] == 2
    assert stats["refused_by_gate"] == 1
    assert stats["refused_by_model"] == 1
    assert stats["with_invalid_citations"] == 1
    assert stats["by_mode"] == {"dense": 3}
    # answered with an invented tag -> fail; model refusal -> review;
    # gate refusal -> every check skipped -> pass
    assert stats["checks"] == {"pass": 1, "review": 1, "fail": 1}
    assert stats["top_sources"][0]["source"] == "endorsement-HO-2026-01-water-backup.md"
    assert len(stats["by_day"]) == 1


def test_trace_stats_when_empty(client):

    stats = client.get("/api/v1/traces/stats").json()

    assert stats["total"] == 0
    assert stats["latency_p50_ms"] == 0
    assert stats["top_sources"] == []


def test_seeded_sample_is_reproducible(client):

    for number in range(6):
        _ask(client, f"Question number {number}")

    first = client.get("/api/v1/traces/sample", params={"seed": 42, "n": 3}).json()
    second = client.get("/api/v1/traces/sample", params={"seed": 42, "n": 3}).json()
    other = client.get("/api/v1/traces/sample", params={"seed": 7, "n": 3}).json()

    ids = [item["trace_id"] for item in first["items"]]

    assert first["frame"] == 6
    assert first["selected"] == 3
    assert ids == [item["trace_id"] for item in second["items"]]
    assert ids != [item["trace_id"] for item in other["items"]]


def test_replay_compares_retrieval_and_generation(client):

    trace_id = _ask(client, "What deductible applies?")["trace_id"]

    response = client.post(f"/api/v1/traces/{trace_id}/replay")

    assert response.status_code == 200
    body = response.json()

    assert body["retrieval"]["identical"] is True
    assert body["retrieval"]["same_chunks"] is True
    assert body["generation"]["skipped"] is False
    assert body["generation"]["identical"] is True
    assert body["generation"]["diff"] == []


def test_replay_of_gate_refusal_skips_generation(client):

    trace_id = _ask(client, "football")["trace_id"]

    body = client.post(f"/api/v1/traces/{trace_id}/replay").json()

    assert body["retrieval"]["original"] == []
    assert body["generation"]["skipped"] is True


def test_unknown_trace_is_404(client):

    assert client.get("/api/v1/traces/t_missing").status_code == 404
    assert client.post("/api/v1/traces/t_missing/replay").status_code == 404
