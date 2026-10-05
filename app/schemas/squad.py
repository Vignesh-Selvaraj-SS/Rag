"""
Schemas for the claims squad (Week 10): one adjuster-note input, run through
the manager + two specialists (app/services/claims_squad_service.py), with
each agent's own output and token count returned alongside the final
synthesized summary - so the UI can show how the answer was actually
produced, not just the answer itself.
"""

from pydantic import BaseModel, Field


class SquadRunRequest(BaseModel):
    notes: str = Field(min_length=1, max_length=4000)
    simulate_coverage_worker_failure: bool = False


class SquadRunResponse(BaseModel):
    notes: str
    summary: str | None
    fields: dict[str, str | None]
    sources: list[str]
    handoffs: list[dict]
    intermediate: dict[str, str]
    worker_error: str | None
    tokens_used: int
    cost_usd: float
    latency_ms: int
    error: str | None = None


class SquadRaceStartRequest(BaseModel):
    only: list[str] | None = None
    sleep: float = Field(default=5.0, ge=0, le=60)


class SquadRaceArmSummary(BaseModel):
    n: int
    pass_rate: float
    p50_latency_ms: float
    p99_latency_ms: float
    total_tokens: int
    cost_per_claim_usd: float


class SquadRaceCaseStatus(BaseModel):
    id: str
    single_status: str | None
    squad_status: str | None
    fail_injected: bool


class SquadRaceStatusResponse(BaseModel):
    running: bool
    current: str | None
    error: str | None
    total_cases: int
    completed_pairs: int
    total_pairs: int
    per_case: list[SquadRaceCaseStatus]
    single_summary: SquadRaceArmSummary | None
    squad_summary: SquadRaceArmSummary | None
    context_resend_multiplier: float | None
    handoff_totals: dict[str, int]
