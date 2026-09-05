"""
FastAPI dependencies. Routers depend on these providers rather than on the
concrete instances so tests can swap in fakes with `app.dependency_overrides`.
"""

from typing import Annotated

from fastapi import Depends

from app.core.errors import IndexEmptyError
from app.services import shared
from app.services.document_service import DocumentService
from app.services.evaluation_service import EvaluationService
from app.services.rag_service import RAGService
from app.services.trace_service import TraceService


def rag_service() -> RAGService:
    return shared.get_rag_service()


def document_service() -> DocumentService:
    return shared.get_document_service()


def trace_service() -> TraceService:
    return shared.get_trace_service()


def evaluation_service() -> EvaluationService:
    return shared.get_evaluation_service()


RagDep = Annotated[RAGService, Depends(rag_service)]
DocumentsDep = Annotated[DocumentService, Depends(document_service)]
TracesDep = Annotated[TraceService, Depends(trace_service)]
EvaluationDep = Annotated[EvaluationService, Depends(evaluation_service)]


def require_index(rag: RAGService) -> None:

    if rag.chunk_count() == 0:
        raise IndexEmptyError()
