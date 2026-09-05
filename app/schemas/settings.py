from pydantic import BaseModel


class RetrievalModeInfo(BaseModel):
    id: str
    label: str
    description: str
    requires_llm: bool


class ChunkStrategyInfo(BaseModel):
    id: str
    label: str
    description: str


class RetrievalDefaults(BaseModel):
    mode: str
    top_k: int
    min_score: float


class GenerationInfo(BaseModel):
    model: str
    temperature: float
    max_tokens: int
    prompt_version: str
    configured: bool


class RetrievalConstants(BaseModel):
    candidate_pool_size: int
    rrf_k: int
    mmr_lambda: float
    reranker_model: str
    fixed_chunk_words: int
    fixed_chunk_overlap_words: int
    hnsw_m: int
    hnsw_ef_construct: int
    hnsw_ef_search: int


class AppSettings(BaseModel):
    app_name: str
    version: str
    embedding_model: str
    collection: str
    defaults: RetrievalDefaults
    generation: GenerationInfo
    constants: RetrievalConstants
    modes: list[RetrievalModeInfo]
    strategies: list[ChunkStrategyInfo]
    traces_enabled: bool
    max_upload_mb: int
    supported_extensions: list[str]


class HealthResponse(BaseModel):
    status: str
    version: str
    index_chunks: int
    index_ready: bool
    llm_configured: bool
