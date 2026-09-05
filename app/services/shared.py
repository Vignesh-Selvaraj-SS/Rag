"""
Application-wide service instances.

One shared RAGService: Qdrant's embedded mode locks its data folder to a
single client, so each router creating its own instance would crash on
startup. Instances are built lazily so importing the app (e.g. in tests that
override these providers) does not open the vector store.
"""

from functools import lru_cache

from app.core.config import settings
from app.services.document_service import DocumentService
from app.services.evaluation_service import EvaluationService
from app.services.index_metadata import IndexMetadata
from app.services.rag_service import RAGService
from app.services.trace_service import TraceService


@lru_cache(maxsize=1)
def get_index_metadata() -> IndexMetadata:
    return IndexMetadata(settings.index_metadata_path)


@lru_cache(maxsize=1)
def get_rag_service() -> RAGService:
    return RAGService(index_metadata=get_index_metadata())


@lru_cache(maxsize=1)
def get_document_service() -> DocumentService:
    return DocumentService(
        data_dir=settings.DATA_DIR,
        index_metadata=get_index_metadata(),
        max_upload_bytes=settings.max_upload_bytes,
    )


@lru_cache(maxsize=1)
def get_trace_service() -> TraceService:
    return TraceService(path=settings.traces_path, enabled=settings.RECORD_TRACES)


@lru_cache(maxsize=1)
def get_evaluation_service() -> EvaluationService:
    return EvaluationService(
        golden_set_path=settings.golden_set_path,
        runs_dir=settings.evaluation_runs_dir,
    )
