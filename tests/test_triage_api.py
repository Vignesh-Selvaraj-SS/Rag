"""
API tests for the /api/v1/triage endpoints, against fakes standing in for
ClaimTriageAgent/FixedClaimTriageWorkflow - no live model calls.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import deps  # noqa: E402
from app.core.errors import LLMUpstreamError  # noqa: E402
from app.main import app  # noqa: E402

_HAPPY_RESULT = {
    "decision": "approved", "payout": 5500.0, "reasoning": "Sewer backup covered, $500 deductible.",
    "sources": ["endorsement-HO-2026-01-water-backup.md"],
    "steps": [
        {"step": 1, "tool": "get_claim", "thought": "", "args": {"claim_id": "CLM-2001"}, "result": {"result": {"claim_id": "CLM-2001"}}, "latency_ms": 500, "tokens": 900},
        {"step": 2, "tool": "finish", "thought": "", "args": {"decision": "approved", "payout": 5500}, "result": None, "latency_ms": 400, "tokens": 200},
    ],
    "step_count": 2, "tokens_used": 1100, "cost_usd": 0.00022, "latency_ms": 900,
    "stopped_reason": "finished", "finished": True,
}


class _FakeSystem:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls: list[str] = []

    def run(self, claim_id: str) -> dict:
        self.calls.append(claim_id)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def triage_client():

    def _make(agent, workflow):
        app.dependency_overrides[deps.triage_agent] = lambda: agent
        app.dependency_overrides[deps.fixed_triage_workflow] = lambda: workflow
        return TestClient(app, raise_server_exceptions=False)

    yield _make

    app.dependency_overrides.pop(deps.triage_agent, None)
    app.dependency_overrides.pop(deps.fixed_triage_workflow, None)


def test_list_claims_returns_all_ten_fixture_claims(triage_client):

    client = triage_client(_FakeSystem(_HAPPY_RESULT), _FakeSystem(_HAPPY_RESULT))

    response = client.get("/api/v1/triage/claims")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 10
    assert body[0]["claim_id"] == "CLM-2001"
    assert "claimed_amount" in body[0] and "policy_form" in body[0]


def test_run_triage_returns_both_systems_results(triage_client):

    client = triage_client(_FakeSystem(_HAPPY_RESULT), _FakeSystem(_HAPPY_RESULT))

    response = client.post("/api/v1/triage/run", json={"claim_id": "CLM-2001"})

    assert response.status_code == 200
    body = response.json()
    assert body["claim_id"] == "CLM-2001"
    assert body["agent"]["decision"] == "approved"
    assert body["agent"]["payout"] == 5500.0
    assert len(body["agent"]["steps"]) == 2
    assert body["workflow"]["decision"] == "approved"


def test_run_triage_unknown_claim_id_is_a_404(triage_client):

    client = triage_client(_FakeSystem(_HAPPY_RESULT), _FakeSystem(_HAPPY_RESULT))

    response = client.post("/api/v1/triage/run", json={"claim_id": "CLM-9999"})

    assert response.status_code == 404


def test_run_triage_normalizes_the_fixed_workflows_different_step_shape(triage_client):

    # Regression test: found live through the UI. FixedClaimTriageWorkflow's
    # real steps use {action, result|raw|result_count}, not the agent's
    # {tool, args, result, thought} - without normalizing, FastAPI's response
    # validation rejected every workflow step outright ('tool' required).
    workflow_result = {
        "decision": "approved", "payout": 5500.0, "reasoning": "", "sources": [],
        "steps": [
            {"step": 1, "action": "get_claim (fixed)", "result": {"result": {"claim_id": "CLM-2001"}}, "latency_ms": 0},
            {"step": 2, "action": "search_policy (fixed, query = adjuster notes, top_k=8)", "result_count": 8, "latency_ms": 18},
            {"step": 3, "action": "generate coverage decision from the fixed retrieval", "raw": '{"claim_status":"approved"}', "latency_ms": 13744, "tokens": 1969},
            {"step": 4, "action": "compute_payout (fixed)", "result": {"result": {"claim_status": "approved", "payout": 5500.0}}, "latency_ms": 0},
        ],
        "step_count": 4, "tokens_used": 1969, "cost_usd": 0.0004, "latency_ms": 13762,
        "stopped_reason": "finished", "finished": True,
    }

    client = triage_client(_FakeSystem(_HAPPY_RESULT), _FakeSystem(workflow_result))

    response = client.post("/api/v1/triage/run", json={"claim_id": "CLM-2001"})

    assert response.status_code == 200
    steps = response.json()["workflow"]["steps"]
    assert [s["tool"] for s in steps] == ["get_claim", "search_policy", "generate_decision", "compute_payout"]
    assert steps[2]["result"]["raw"] == '{"claim_status":"approved"}'


def test_run_triage_isolates_a_failure_to_one_system(triage_client):

    # The agent hits a hard upstream failure; the workflow still succeeds -
    # the response should carry both, not fail the whole request.
    client = triage_client(
        _FakeSystem(error=LLMUpstreamError("Rate limit reached.")),
        _FakeSystem(_HAPPY_RESULT),
    )

    response = client.post("/api/v1/triage/run", json={"claim_id": "CLM-2001"})

    assert response.status_code == 200
    body = response.json()
    assert body["agent"]["error"] == "Rate limit reached."
    assert body["agent"]["finished"] is False
    assert body["workflow"]["decision"] == "approved"
    assert body["workflow"]["error"] is None
