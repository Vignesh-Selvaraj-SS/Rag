"""
"Ask the Agent": a free-text policy question, run through the Week 7 agent
(ClaimAgent) and its fixed workflow (FixedClaimWorkflow), returned side by
side with full step-by-step traces - the policy-QA counterpart to
app/api/triage.py.
"""

import logging

from fastapi import APIRouter

from app.api.deps import FixedPolicyWorkflowDep, PolicyAgentDep
from app.core.errors import AppError
from app.schemas.policy_qa import PolicyQaRequest, PolicyQaResponse
from app.services.step_trace import normalize_steps

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/policy-qa", tags=["Policy Q&A"])


def _run_system(run_fn, question: str) -> dict:
    """Same failure isolation as app/api/triage.py's _run_system - see there for why."""

    try:
        result = run_fn(question)
    except AppError as error:
        logger.warning("Policy Q&A run failed: %s", error)
        return {
            "answer": None, "sources": [], "steps": [], "step_count": 0,
            "tokens_used": 0, "latency_ms": 0, "stopped_reason": "error",
            "finished": False, "error": error.message,
        }

    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "steps": normalize_steps(result["steps"]),
        "step_count": result["step_count"],
        "tokens_used": result["tokens_used"],
        "latency_ms": result["latency_ms"],
        "stopped_reason": result["stopped_reason"],
        "finished": result["finished"],
        "error": None,
    }


@router.post("/ask", response_model=PolicyQaResponse)
def ask(request: PolicyQaRequest, agent: PolicyAgentDep, workflow: FixedPolicyWorkflowDep):
    """
    Run the requested system(s) on the same free-text question. `system`
    picks "both" (default), "agent" only or "workflow" only - the unrequested
    side is skipped entirely, not just hidden, so choosing one system doesn't
    still spend a live call on the other.
    """

    return {
        "question": request.question,
        "agent": _run_system(agent.run, request.question) if request.system in ("both", "agent") else None,
        "workflow": _run_system(workflow.run, request.question) if request.system in ("both", "workflow") else None,
    }
