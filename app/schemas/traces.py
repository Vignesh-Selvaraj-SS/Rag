from typing import Literal

from pydantic import BaseModel

CheckStatus = Literal["pass", "fail", "review", "skip"]


class TraceCheck(BaseModel):
    id: str
    name: str
    status: CheckStatus
    detail: str


class TraceSummary(BaseModel):
    trace_id: str
    timestamp: str | None
    origin: str | None
    question: str | None
    mode: str | None
    model: str | None
    refused: bool
    refused_by: str | None
    latency_ms: int
    retrieved_count: int
    cited_count: int
    invalid_citations: int
    check_status: Literal["pass", "fail", "review"]


class TraceListResponse(BaseModel):
    total: int
    items: list[TraceSummary]


class TraceChunk(BaseModel):
    rank: int
    chunk_id: str
    source: str
    heading: str
    page: str
    score: float
    dense_score: float
    text: str | None


class TraceDetail(BaseModel):
    trace_id: str
    timestamp: str | None
    origin: str | None
    question: str | None
    identifiers_redacted: int = 0
    model: str | None
    prompt_version: str | None
    params: dict
    chunk_strategy: str | None
    retrieved: list[TraceChunk]
    passes_gate: bool
    raw_output: str | None
    answer: str | None
    cited_chunk_ids: list[str]
    invalid_citations: list[str]
    refused: bool
    refused_by: str | None
    latency_ms: int
    checks: list[TraceCheck]
    check_status: Literal["pass", "fail", "review"]


class TraceSampleResponse(BaseModel):
    seed: int
    frame: int
    selected: int
    items: list[TraceSummary]


class SourceCount(BaseModel):
    source: str
    citations: int


class DayCount(BaseModel):
    day: str
    count: int


class TraceStats(BaseModel):
    total: int
    answered: int
    refused: int
    refused_by_gate: int
    refused_by_model: int
    answered_without_citation: int
    with_invalid_citations: int
    identifiers_redacted: int
    latency_p50_ms: int
    latency_p95_ms: int
    latency_avg_ms: int
    by_mode: dict[str, int]
    by_model: dict[str, int]
    checks: dict[str, int]
    top_sources: list[SourceCount]
    by_day: list[DayCount]


class ReplayChunk(BaseModel):
    chunk_id: str
    score: float


class ReplayRetrieval(BaseModel):
    original: list[ReplayChunk]
    replayed: list[ReplayChunk]
    identical: bool
    same_chunks: bool


class ReplayGeneration(BaseModel):
    skipped: bool
    reason: str | None = None
    original: str | None = None
    replayed: str | None = None
    identical: bool | None = None
    diff: list[str] = []
    prompt_version_then: str | None = None
    prompt_version_now: str | None = None


class ReplayResponse(BaseModel):
    trace_id: str
    retrieval: ReplayRetrieval
    generation: ReplayGeneration | None
