def test_golden_set_roundtrip(client):

    response = client.get("/api/v1/evaluation/golden-set")

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == ["Q1", "Q2"]

    update = client.put(
        "/api/v1/evaluation/golden-set",
        json={
            "items": [
                {"id": "Q1", "question": "A?", "expected_chunk_id": "a.md::0", "expected_heading": " Intro "},
            ]
        },
    )

    assert update.status_code == 200
    assert update.json()["items"] == [
        {"id": "Q1", "question": "A?", "expected_chunk_id": "a.md::0", "expected_heading": "Intro", "exact_token": None}
    ]


def test_golden_set_rejects_duplicates_and_blank_fields(client):

    duplicate = client.put(
        "/api/v1/evaluation/golden-set",
        json={
            "items": [
                {"id": "Q1", "question": "A?", "expected_chunk_id": "a.md::0"},
                {"id": "Q1", "question": "B?", "expected_chunk_id": "b.md::0"},
            ]
        },
    )
    assert duplicate.status_code == 400
    assert "Duplicate" in duplicate.json()["detail"]

    blank = client.put(
        "/api/v1/evaluation/golden-set",
        json={"items": [{"id": "Q1", "question": "A?", "expected_chunk_id": "   "}]},
    )
    assert blank.status_code == 400


def test_run_evaluation_reports_hit_rates_and_ranks(client):

    client.post("/api/v1/index/rebuild")

    response = client.post("/api/v1/evaluation/runs", json={"mode": "hybrid", "label": "first"})

    assert response.status_code == 200
    run = response.json()

    assert run["run_id"].startswith("run_")
    assert run["mode"] == "hybrid"
    assert run["label"] == "first"
    assert run["n_questions"] == 2
    assert run["hits_at_3"] == 1
    assert run["hit_rate_at_3"] == 0.5
    assert run["mrr"] == 0.5
    assert run["index"]["strategy"] == "heading"
    assert run["warnings"] == []

    by_id = {q["id"]: q for q in run["per_question"]}
    assert by_id["Q1"]["rank_of_expected"] == 1
    assert by_id["Q1"]["top_hits"][0]["expected"] is True
    assert by_id["Q2"]["rank_of_expected"] is None
    assert by_id["Q2"]["hit_at_3"] is False


def test_run_evaluation_warns_when_index_strategy_is_not_heading(client):

    client.post("/api/v1/index/rebuild", json={"strategy": "fixed_size"})

    run = client.post("/api/v1/evaluation/runs", json={"mode": "dense"}).json()

    assert any("fixed_size" in warning for warning in run["warnings"])


def test_runs_are_persisted_listed_fetched_and_deleted(client):

    first = client.post("/api/v1/evaluation/runs", json={"mode": "dense"}).json()
    second = client.post("/api/v1/evaluation/runs", json={"mode": "hybrid"}).json()

    listed = client.get("/api/v1/evaluation/runs").json()

    assert [run["run_id"] for run in listed] == [second["run_id"], first["run_id"]]
    assert "per_question" not in listed[0]

    fetched = client.get(f"/api/v1/evaluation/runs/{first['run_id']}").json()
    assert fetched["per_question"][0]["id"] == "Q1"

    assert client.delete(f"/api/v1/evaluation/runs/{first['run_id']}").status_code == 204
    assert client.get(f"/api/v1/evaluation/runs/{first['run_id']}").status_code == 404
    assert client.get("/api/v1/evaluation/runs/../../etc/passwd").status_code == 404


def test_run_ids_cannot_reach_outside_the_runs_folder(services, workspace):

    import pytest

    from app.core.errors import NotFoundError

    outside = workspace["root"] / "secret.json"
    outside.write_text("{}", encoding="utf-8")

    evaluation = services["evaluation"]

    with pytest.raises(NotFoundError):
        evaluation.get_run("../secret")

    with pytest.raises(NotFoundError):
        evaluation.delete_run("../secret")

    assert outside.exists()


def test_run_evaluation_requires_index_and_golden_set(client, services):

    client.put("/api/v1/evaluation/golden-set", json={"items": []})
    empty = client.post("/api/v1/evaluation/runs", json={"mode": "dense"})
    assert empty.status_code == 400
    assert "golden set is empty" in empty.json()["detail"]

    services["rag"].retriever.vector_store._count = 0
    assert client.post("/api/v1/evaluation/runs", json={"mode": "dense"}).status_code == 503


def test_inspect_question_marks_expected_chunk(client):

    response = client.post("/api/v1/evaluation/inspect", json={"question_id": "Q1", "mode": "dense"})

    assert response.status_code == 200
    body = response.json()

    assert body["expected_was_shown"] is True
    assert body["retrieved"][0]["expected"] is True
    assert body["retrieved"][1]["expected"] is False
    assert body["cited_chunk_ids"] == [
        "endorsement-HO-2026-01-water-backup.md::4",
        "policy-base-HO3-2026.md::7",
    ]
    assert body["invalid_citations"] == ["[S9]"]

    assert client.post("/api/v1/evaluation/inspect", json={"question_id": "Q99"}).status_code == 404
