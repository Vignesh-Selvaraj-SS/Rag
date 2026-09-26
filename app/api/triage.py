"""
Claims-triage endpoints: run the agent and the fixed workflow on one claim
and return both full step-by-step traces, so the UI can show the path an
answer took side by side, not just the final decision.
"""

import logging

from fastapi import APIRouter

from app.api.deps import FixedTriageWorkflowDep, TriageAgentDep
from app.core.errors import AppError, NotFoundError
from app.schemas.triage import TriageClaimSummary, TriageRunRequest, TriageRunResponse
from app.services.claims_data import all_claim_ids, get_claim_record
from app.services.step_trace import normalize_steps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/triage", tags=["Triage"])


@router.get("/claims", response_model=list[TriageClaimSummary])
def list_claims():
    """The 10 fixture claims, for the claim picker."""

    return [
        {
            "claim_id": claim_id,
            "claimed_amount": get_claim_record(claim_id)["claimed_amount"],
            "policy_form": get_claim_record(claim_id)["policy_form"],
        }
        for claim_id in all_claim_ids()
    ]


def _run_system(run_fn, claim_id: str) -> dict:
    """
    Runs one system on one claim, isolating a hard upstream failure (a Groq
    rate limit, live-observed happening mid-race in this same project) to
    this one system's result instead of failing the whole request - the
    other system's result, if it already succeeded, still reaches the UI.
    """

    try:
        result = run_fn(claim_id)
    except AppError as error:
        logger.warning("Triage run failed for %s: %s", claim_id, error)
        return {
            "decision": None, "payout": None, "reasoning": "", "sources": [],
            "steps": [], "step_count": 0, "tokens_used": 0, "cost_usd": 0.0,
            "latency_ms": 0, "stopped_reason": "error", "finished": False,
            "error": error.message,
        }

    return {
        "decision": result["decision"],
        "payout": result["payout"],
        "reasoning": result.get("reasoning", ""),
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


@router.post("/run", response_model=TriageRunResponse)
def run_triage(request: TriageRunRequest, agent: TriageAgentDep, workflow: FixedTriageWorkflowDep):
    """
    Run both systems on one claim ID and return both full traces. Each
    system's failure is independent - one can fail while the other's result
    still comes back.
    """

    if get_claim_record(request.claim_id) is None:
        raise NotFoundError(f"No claim found with id {request.claim_id!r}.")

    return {
        "claim_id": request.claim_id,
        "agent": _run_system(agent.run, request.claim_id),
        "workflow": _run_system(workflow.run, request.claim_id),
    }
