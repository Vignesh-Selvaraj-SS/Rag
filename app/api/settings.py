from fastapi import APIRouter

from app import __version__
from app.api.deps import RagDep
from app.core.config import settings
from app.schemas.settings import AppSettings, HealthResponse
from app.services import catalog
from app.services.chunk_service import FIXED_CHUNK_OVERLAP_WORDS, FIXED_CHUNK_WORDS
from app.services.document_loader import SUPPORTED_EXTENSIONS
from app.services.hybrid_search import RRF_K
from app.services.llm_service import MAX_TOKENS, PROMPT_VERSION, TEMPERATURE
from app.services.mmr import MMR_LAMBDA
from app.services.reranker import RERANKER_MODEL
from app.services.retrieval_service import CANDIDATE_POOL_SIZE
from app.services.vector_store import HNSW_EF_CONSTRUCT, HNSW_EF_SEARCH, HNSW_M

router = APIRouter(tags=["Settings"])

APP_NAME = "Insurance Claims RAG"


@router.get("/api/v1/settings", response_model=AppSettings)
def get_settings():
    """
    Public, non-secret configuration: what the server is running with and
    which retrieval modes and chunking strategies it offers.
    """

    return {
        "app_name": APP_NAME,
        "version": __version__,
        "embedding_model": settings.EMBEDDING_MODEL,
        "collection": settings.COLLECTION_NAME,
        "defaults": {
            "mode": "dense",
            "top_k": settings.TOP_K,
            "min_score": settings.MIN_SCORE,
        },
        "generation": {
            "model": settings.MODEL_NAME,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
            "prompt_version": PROMPT_VERSION,
            "configured": settings.llm_configured,
        },
        "constants": {
            "candidate_pool_size": CANDIDATE_POOL_SIZE,
            "rrf_k": RRF_K,
            "mmr_lambda": MMR_LAMBDA,
            "reranker_model": RERANKER_MODEL,
            "fixed_chunk_words": FIXED_CHUNK_WORDS,
            "fixed_chunk_overlap_words": FIXED_CHUNK_OVERLAP_WORDS,
            "hnsw_m": HNSW_M,
            "hnsw_ef_construct": HNSW_EF_CONSTRUCT,
            "hnsw_ef_search": HNSW_EF_SEARCH,
        },
        "modes": catalog.RETRIEVAL_MODES,
        "strategies": catalog.CHUNK_STRATEGIES,
        "traces_enabled": settings.RECORD_TRACES,
        "max_upload_mb": settings.MAX_UPLOAD_MB,
        "supported_extensions": sorted(SUPPORTED_EXTENSIONS),
    }


@router.get("/health", response_model=HealthResponse)
def health(rag: RagDep):

    chunks = rag.chunk_count()

    return {
        "status": "ok",
        "version": __version__,
        "index_chunks": chunks,
        "index_ready": chunks > 0,
        "llm_configured": settings.llm_configured,
    }
