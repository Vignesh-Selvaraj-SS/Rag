from pydantic import BaseModel, Field

from app.schemas.common import RetrievalMode


class GoldenQuestion(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    question: str = Field(min_length=1, max_length=2000)
    expected_chunk_id: str = Field(min_length=1, max_length=400)
    expected_heading: str | None = None
    exact_token: str | None = None


class GoldenSetResponse(BaseModel):
    items: list[GoldenQuestion]


class GoldenSetUpdate(BaseModel):
    items: list[GoldenQuestion] = Field(max_length=500)


class EvaluationRunRequest(BaseModel):
    mode: RetrievalMode = "dense"
    top_k: int = Field(default=10, ge=3, le=50)
    label: str | None = Field(default=None, max_length=80)


class EvaluationHit(BaseModel):
    rank: int
    chunk_id: str
    source: str
    heading: str
    score: float
    dense_score: float
    expected: bool


class EvaluationQuestionResult(BaseModel):
    id: str
    question: str
    expected_chunk_id: str
    expected_heading: str | None
    exact_token: str | None
    rank_of_expected: int | None
    hit_at_3: bool
    hit_at_5: bool
    latency_ms: float
    top_hits: list[EvaluationHit]


class EvaluationIndexInfo(BaseModel):
    strategy: str | None
    chunks: int | None
    built_at: str | None


class EvaluationRunSummary(BaseModel):
    run_id: str
    created_at: str
    label: str | None
    mode: str
    top_k: int
    index: EvaluationIndexInfo
    n_questions: int
    hit_rate_at_3: float
    hit_rate_at_5: float
    hits_at_3: int
    hits_at_5: int
    mrr: float
    p50_latency_ms: float
    warnings: list[str]


class EvaluationRun(EvaluationRunSummary):
    per_question: list[EvaluationQuestionResult]


class InspectRequest(BaseModel):
    question_id: str = Field(min_length=1, max_length=40)
    mode: RetrievalMode = "dense"


class InspectChunk(BaseModel):
    rank: int
    chunk_id: str
    source: str
    heading: str
    page: str
    score: float
    dense_score: float
    text: str
    expected: bool


class InspectResponse(BaseModel):
    question_id: str
    question: str
    expected_chunk_id: str
    expected_heading: str | None
    mode: str
    expected_was_shown: bool
    retrieved: list[InspectChunk]
    answer: str
    refused: bool
    refused_by: str | None
    cited_chunk_ids: list[str]
    invalid_citations: list[str]
    latency_ms: int
