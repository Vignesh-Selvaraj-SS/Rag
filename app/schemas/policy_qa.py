"""
Schemas for the "Ask the Agent" page: a free-text policy question, run
through the Week 7 agent (ClaimAgent) and its fixed workflow
(FixedClaimWorkflow), returned side by side with full step-by-step traces -
the same idea as app/schemas/triage.py, for the other agent/workflow pair.
"""

from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.triage import TriageStep

PolicyQaSystemChoice = Literal["both", "agent", "workflow"]


class PolicyQaRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    system: PolicyQaSystemChoice = "both"


class PolicyQaSystemResult(BaseModel):
    answer: str | None
    sources: list[str]
    steps: list[TriageStep]
    step_count: int
    tokens_used: int
    latency_ms: int
    stopped_reason: str
    finished: bool
    error: str | None = None


class PolicyQaResponse(BaseModel):
    question: str
    agent: PolicyQaSystemResult | None
    workflow: PolicyQaSystemResult | None
