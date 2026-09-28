"""
Schemas for the merged agent: one input (a policy question or a claim ID),
run through ClaimAgent and its fixed workflow, returned side by side with
full step-by-step traces. Replaces the separate triage.py/policy_qa.py
schemas from before ClaimAgent/ClaimTriageAgent were merged into one class.
"""

from typing import Literal

from pydantic import BaseModel, Field

SystemChoice = Literal["both", "agent", "workflow"]


class AgentClaimSummary(BaseModel):
    claim_id: str
    claimed_amount: float
    policy_form: str


class AgentStep(BaseModel):
    step: int
    tool: str
    thought: str | None = None
    args: dict | None = None
    result: dict | None = None
    latency_ms: int
    tokens: int | None = None


class AgentRunRequest(BaseModel):
    user_input: str = Field(min_length=1, max_length=2000)
    system: SystemChoice = "both"


class AgentSystemResult(BaseModel):
    answer: str | None
    decision: str | None
    payout: float | None
    sources: list[str]
    steps: list[AgentStep]
    step_count: int
    tokens_used: int
    cost_usd: float
    latency_ms: int
    stopped_reason: str
    finished: bool
    error: str | None = None


class AgentRunResponse(BaseModel):
    user_input: str
    agent: AgentSystemResult | None
    workflow: AgentSystemResult | None
