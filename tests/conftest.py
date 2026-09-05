"""
API tests run against fakes for the heavy parts (vector store, embeddings,
language model). The fakes reproduce the exact dict shapes the real services
return, so the routers and schemas are exercised for real.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import deps  # noqa: E402
from app.core.errors import LLMNotConfiguredError  # noqa: E402
from app.main import app  # noqa: E402
from app.services.document_service import DocumentService  # noqa: E402
from app.services.evaluation_service import EvaluationService  # noqa: E402
from app.services.index_metadata import IndexMetadata  # noqa: E402
from app.services.trace_service import TraceService  # noqa: E402

CHUNKS = [
    {
        "chunk_id": "endorsement-HO-2026-01-water-backup.md::4",
        "text": "A separate deductible of $500 applies to each water backup loss.",
        "source": "endorsement-HO-2026-01-water-backup.md",
        "heading": "Deductible",
        "page_start": 1,
        "page_end": 1,
        "page": "p.1",
        "score": 0.83,
        "dense_score": 0.83,
    },
    {
        "chunk_id": "policy-base-HO3-2026.md::7",
        "text": "The all-perils deductible shown in the Declarations applies once per occurrence.",
        "source": "policy-base-HO3-2026.md",
        "heading": "Deductible",
        "page_start": 3,
        "page_end": 3,
        "page": "p.3",
        "score": 0.71,
        "dense_score": 0.71,
    },
]


class FakeVectorStore:

    def __init__(self, count: int = 2):
        self._count = count

    def count(self) -> int:
        return self._count


class FakeRetriever:
    """Returns CHUNKS for anything except questions containing 'football'."""

    def __init__(self):
        self.vector_store = FakeVectorStore()
        self.calls: list[dict] = []

    def retrieve(self, question, top_k=None, min_score=None, source=None, mode="dense"):

        self.calls.append(
            {"question": question, "top_k": top_k, "min_score": min_score, "source": source, "mode": mode}
        )

        top_k = 5 if top_k is None else top_k
        min_score = 0.6 if min_score is None else min_score

        hits = [] if "football" in question.lower() else [dict(chunk) for chunk in CHUNKS[:top_k]]

        if source:
            hits = [hit for hit in hits if hit["source"] == source]

        best = hits[0]["dense_score"] if hits else 0.0

        return {
            "question": question,
            "hits": hits,
            "best_score": hits[0]["score"] if hits else 0.0,
            "passes_gate": bool(hits) and best >= min_score,
            "min_score": min_score,
        }


class FakeLLM:

    def __init__(self, configured: bool = True):
        self.configured = configured

    def generate_answer(self, question, hits):

        if not self.configured:
            raise LLMNotConfiguredError()

        if "refuse" in question.lower():
            text = "I don't know - the documents provided don't cover this."
            return self._result(text, cited=[], invalid=[], refused=True)

        text = "A separate $500 deductible applies [S1]. It stacks with the base deductible [S2][S9]."
        return self._result(text, cited=[1, 2], invalid=["[S9]"], refused=False)

    @staticmethod
    def _result(text, cited, invalid, refused):
        return {
            "answer": text,
            "cited": cited,
            "invalid_citations": invalid,
            "refused": refused,
            "raw_output": text,
            "prompt_version": "v1",
            "temperature": 0.0,
            "max_tokens": 800,
        }


class FakeRAGService:
    """
    Mirrors RAGService.ask / search / ingest / index_status with the fakes
    above. The real orchestration in RAGService is covered separately by
    test_rag_service.py.
    """

    def __init__(self, index_metadata: IndexMetadata, llm_configured: bool = True):

        from app.services.rag_service import RAGService

        self.retriever = FakeRetriever()
        self.llm = FakeLLM(configured=llm_configured)
        self.index_metadata = index_metadata
        self._real = RAGService(retriever=self.retriever, llm=self.llm, index_metadata=index_metadata)
        self.ingest_calls: list[str] = []

    def ask(self, *args, **kwargs):
        return self._real.ask(*args, **kwargs)

    def search(self, *args, **kwargs):
        return self._real.search(*args, **kwargs)

    def chunk_count(self):
        return self.retriever.vector_store.count()

    def index_status(self):
        return self._real.index_status()

    def ingest(self, strategy="heading"):

        self.ingest_calls.append(strategy)

        result = {
            "strategy": strategy,
            "documents": 2,
            "words": 400,
            "chunks": 12,
            "per_document": [
                {"source": "endorsement-HO-2026-01-water-backup.md", "pages": 1, "words": 200, "chunks": 7},
                {"source": "policy-base-HO3-2026.md", "pages": 3, "words": 200, "chunks": 5},
            ],
        }
        metadata = self.index_metadata.write(result)
        return {**result, "built_at": metadata["built_at"]}


@pytest.fixture
def workspace(tmp_path):

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "endorsement-HO-2026-01-water-backup.md").write_text("# Water backup\n\nText.", encoding="utf-8")
    (data_dir / "policy-base-HO3-2026.md").write_text("# Base policy\n\nText.", encoding="utf-8")

    return {
        "root": tmp_path,
        "data_dir": data_dir,
        "index_metadata": IndexMetadata(tmp_path / ".qdrant" / "index_meta.json"),
        "traces_path": tmp_path / ".runtime" / "traces.jsonl",
        "golden_set_path": tmp_path / "evaluation" / "golden_set.jsonl",
        "runs_dir": tmp_path / ".runtime" / "evaluations",
    }


@pytest.fixture
def services(workspace):

    rag = FakeRAGService(workspace["index_metadata"])

    documents = DocumentService(
        data_dir=workspace["data_dir"],
        index_metadata=workspace["index_metadata"],
        max_upload_bytes=1024 * 1024,
    )

    traces = TraceService(path=workspace["traces_path"], enabled=True)

    evaluation = EvaluationService(
        golden_set_path=workspace["golden_set_path"],
        runs_dir=workspace["runs_dir"],
    )

    evaluation.save_golden_set(
        [
            {
                "id": "Q1",
                "question": "What deductible applies to a water backup claim?",
                "expected_chunk_id": CHUNKS[0]["chunk_id"],
                "expected_heading": "Deductible",
                "exact_token": "HO-2026-01",
            },
            {
                "id": "Q2",
                "question": "What is the base all-perils deductible?",
                "expected_chunk_id": "policy-base-HO3-2026.md::99",
                "expected_heading": None,
                "exact_token": None,
            },
        ]
    )

    return {"rag": rag, "documents": documents, "traces": traces, "evaluation": evaluation}


@pytest.fixture
def client(services):

    app.dependency_overrides[deps.rag_service] = lambda: services["rag"]
    app.dependency_overrides[deps.document_service] = lambda: services["documents"]
    app.dependency_overrides[deps.trace_service] = lambda: services["traces"]
    app.dependency_overrides[deps.evaluation_service] = lambda: services["evaluation"]

    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client

    app.dependency_overrides.clear()
