"""
Schemas for the claims-triage UI: run ClaimTriageAgent and
FixedClaimTriageWorkflow on one claim and show both step-by-step traces side
by side, so a person can watch the path an answer took, not just the answer -
this is the whole point of Week 8's trajectory work.
"""

from pydantic import BaseModel


class TriageClaimSummary(BaseModel):
    claim_id: str
    claimed_amount: float
    policy_form: str


class TriageStep(BaseModel):
    step: int
    tool: str
    thought: str | None = None
    args: dict | None = None
    result: dict | None = None
    latency_ms: int
    tokens: int | None = None


class TriageSystemResult(BaseModel):
    decision: str | None
    payout: float | None
    reasoning: str
    sources: list[str]
    steps: list[TriageStep]
    step_count: int
    tokens_used: int
    cost_usd: float
    latency_ms: int
    stopped_reason: str
    finished: bool
    error: str | None = None


class TriageRunRequest(BaseModel):
    claim_id: str


class TriageRunResponse(BaseModel):
    claim_id: str
    agent: TriageSystemResult
    workflow: TriageSystemResult
