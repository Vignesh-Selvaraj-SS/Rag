from typing import Literal

from pydantic import BaseModel, Field

RetrievalMode = Literal["dense", "hybrid", "rerank", "mmr", "rewrite", "hyde"]
ChunkStrategy = Literal["heading", "fixed_size"]


class ErrorResponse(BaseModel):
    detail: str
    request_id: str = ""


class RetrievalOptions(BaseModel):
    """Per-request overrides for the retrieval defaults."""

    mode: RetrievalMode = "dense"
    top_k: int | None = Field(default=None, ge=1, le=50)
    min_score: float | None = Field(default=None, ge=0.0, le=1.0)
    source: str | None = Field(default=None, max_length=255)


class RetrievedChunk(BaseModel):
    rank: int
    chunk_id: str
    source: str
    heading: str
    page: str
    score: float
    dense_score: float
    text: str


class Source(BaseModel):
    rank: int
    chunk_id: str
    source: str
    heading: str
    page: str
