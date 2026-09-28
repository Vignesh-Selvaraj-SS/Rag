"""
The merged agent's endpoints: run ClaimAgent and its fixed workflow on one
input - a policy question or a claim ID - and return both full step-by-step
traces side by side. Replaces the separate triage.py/policy_qa.py routers
from before the two agents were merged into one class.
"""

import logging

from fastapi import APIRouter

from app.api.deps import AgentDep, FixedWorkflowDep
from app.core.errors import AppError
from app.schemas.agent import AgentClaimSummary, AgentRunRequest, AgentRunResponse
from app.services.claims_data import all_claim_ids, get_claim_record
from app.services.step_trace import normalize_steps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/agent", tags=["Agent"])


@router.get("/claims", response_model=list[AgentClaimSummary])
def list_claims():
    """The 10 fixture claim ids, for quick-fill sample chips in the UI."""

    return [
        {
            "claim_id": claim_id,
            "claimed_amount": get_claim_record(claim_id)["claimed_amount"],
            "policy_form": get_claim_record(claim_id)["policy_form"],
        }
        for claim_id in all_claim_ids()
    ]


def _run_system(run_fn, user_input: str) -> dict:
    """
    Runs one system on the input, isolating a hard upstream failure (a Groq
    rate limit, live-observed happening mid-race in this project) to this
    one system's result instead of failing the whole request - the other
    system's result, if it already succeeded, still reaches the caller.
    """

    try:
        result = run_fn(user_input)
    except AppError as error:
        logger.warning("Agent run failed: %s", error)
        return {
            "answer": None, "decision": None, "payout": None, "sources": [],
            "steps": [], "step_count": 0, "tokens_used": 0, "cost_usd": 0.0,
            "latency_ms": 0, "stopped_reason": "error", "finished": False,
            "error": error.message,
        }

    return {
        "answer": result["answer"],
        "decision": result["decision"],
        "payout": result["payout"],
        "sources": result["sources"],
        "steps": normalize_steps(result["steps"]),
        "step_count": result["step_count"],
        "tokens_used": result["tokens_used"],
        "cost_usd": result["cost_usd"],
        "latency_ms": result["latency_ms"],
        "stopped_reason": result["stopped_reason"],
        "finished": result["finished"],
        "error": None,
    }


@router.post("/run", response_model=AgentRunResponse)
def run_agent(request: AgentRunRequest, agent: AgentDep, workflow: FixedWorkflowDep):
    """
    Run the requested system(s) on the same input. `system` picks "both"
    (default), "agent" only or "workflow" only - the unrequested side is
    skipped entirely, not just hidden, so choosing one system doesn't still
    spend a live call on the other.
    """

    return {
        "user_input": request.user_input,
        "agent": _run_system(agent.run, request.user_input) if request.system in ("both", "agent") else None,
        "workflow": _run_system(workflow.run, request.user_input) if request.system in ("both", "workflow") else None,
    }
