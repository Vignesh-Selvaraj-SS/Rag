import io


def test_list_documents_before_any_index_build(client):

    response = client.get("/api/v1/documents")

    assert response.status_code == 200
    body = response.json()

    assert [doc["name"] for doc in body["documents"]] == [
        "endorsement-HO-2026-01-water-backup.md",
        "policy-base-HO3-2026.md",
    ]
    assert all(doc["status"] == "pending" for doc in body["documents"])
    assert body["index"]["strategy"] is None
    assert body["index"]["chunks"] == 2


def test_rebuild_then_documents_are_indexed(client, services):

    response = client.post("/api/v1/index/rebuild", json={"strategy": "fixed_size"})

    assert response.status_code == 200
    assert response.json()["strategy"] == "fixed_size"
    assert response.json()["built_at"]
    assert services["rag"].ingest_calls == ["fixed_size"]

    body = client.get("/api/v1/documents").json()

    assert all(doc["status"] == "indexed" for doc in body["documents"])
    assert body["documents"][0]["chunks"] == 7
    assert body["index"]["strategy"] == "fixed_size"
    assert body["index"]["documents"] == 2

    status = client.get("/api/v1/index").json()
    assert status["ready"] is True
    assert status["built_at"] == body["index"]["built_at"]


def test_rebuild_with_no_body_uses_heading_strategy(client, services):

    response = client.post("/api/v1/index/rebuild")

    assert response.status_code == 200
    assert services["rag"].ingest_calls == ["heading"]


def test_legacy_ingest_alias_still_works(client, services):

    response = client.post("/api/v1/ingest", json={"strategy": "heading"})

    assert response.status_code == 200
    assert services["rag"].ingest_calls == ["heading"]


def test_rebuild_rejects_unknown_strategy(client):

    assert client.post("/api/v1/index/rebuild", json={"strategy": "magic"}).status_code == 422


def test_upload_saves_file_and_marks_pending(client, workspace):

    client.post("/api/v1/index/rebuild")

    response = client.post(
        "/api/v1/documents",
        files={"file": ("faq.txt", io.BytesIO(b"Q: what?\nA: that."), "text/plain")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "faq.txt"
    assert body["replaced"] is False
    assert (workspace["data_dir"] / "faq.txt").read_bytes() == b"Q: what?\nA: that."

    documents = {doc["name"]: doc for doc in client.get("/api/v1/documents").json()["documents"]}
    assert documents["faq.txt"]["status"] == "pending"
    assert documents["policy-base-HO3-2026.md"]["status"] == "indexed"


def test_upload_strips_directory_components(client, workspace):

    response = client.post(
        "/api/v1/documents",
        files={"file": ("../../evil.md", io.BytesIO(b"# hi"), "text/markdown")},
    )

    assert response.status_code == 201
    assert response.json()["name"] == "evil.md"
    assert (workspace["data_dir"] / "evil.md").exists()
    assert not (workspace["root"] / "evil.md").exists()


def test_upload_rejects_unsupported_type_and_empty_and_oversized(client):

    bad_type = client.post(
        "/api/v1/documents", files={"file": ("macro.xlsm", io.BytesIO(b"x"), "application/octet-stream")}
    )
    assert bad_type.status_code == 400
    assert "Unsupported file type" in bad_type.json()["detail"]

    empty = client.post("/api/v1/documents", files={"file": ("empty.md", io.BytesIO(b""), "text/markdown")})
    assert empty.status_code == 400

    oversized = client.post(
        "/api/v1/documents",
        files={"file": ("big.txt", io.BytesIO(b"a" * (1024 * 1024 + 1)), "text/plain")},
    )
    assert oversized.status_code == 400
    assert "too large" in oversized.json()["detail"]


def test_delete_document_then_status_is_removed_until_rebuild(client, workspace):

    client.post("/api/v1/index/rebuild")

    response = client.delete("/api/v1/documents/policy-base-HO3-2026.md")

    assert response.status_code == 200
    assert not (workspace["data_dir"] / "policy-base-HO3-2026.md").exists()

    documents = {doc["name"]: doc for doc in client.get("/api/v1/documents").json()["documents"]}
    assert documents["policy-base-HO3-2026.md"]["status"] == "removed"
    assert documents["policy-base-HO3-2026.md"]["chunks"] == 5


def test_delete_missing_document_is_404(client):

    response = client.delete("/api/v1/documents/nope.md")

    assert response.status_code == 404
    assert "request_id" in response.json()


def test_delete_cannot_escape_data_dir(client, workspace):

    outside = workspace["root"] / "secret.md"
    outside.write_text("x", encoding="utf-8")

    response = client.delete("/api/v1/documents/..%2Fsecret.md")

    assert response.status_code == 404
    assert outside.exists()
