from pydantic import BaseModel, Field

from app.schemas.common import RetrievalOptions, RetrievedChunk, Source


class ChatRequest(RetrievalOptions):
    question: str = Field(min_length=1, max_length=2000)
    include_debug: bool = False


class ChatDebug(BaseModel):
    retrieved: list[RetrievedChunk]
    params: dict
    model: str
    prompt_version: str
    passes_gate: bool
    best_score: float
    invalid_citations: list[str]
    raw_output: str | None


class ChatResponse(BaseModel):
    answer: str
    sources: list[Source]
    refused: bool
    refused_by: str | None
    mode: str
    latency_ms: int
    trace_id: str | None
    debug: ChatDebug | None = None


class SearchRequest(RetrievalOptions):
    question: str = Field(min_length=1, max_length=2000)


class SearchResponse(BaseModel):
    question: str
    hits: list[RetrievedChunk]
    best_score: float
    passes_gate: bool
    min_score: float
    mode: str
    latency_ms: int
