"""
API tests for /api/v1/agent, against fakes standing in for the merged
ClaimAgent/FixedClaimWorkflow - no live model calls.
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.api import deps  # noqa: E402
from app.core.errors import LLMUpstreamError  # noqa: E402
from app.main import app  # noqa: E402

_HAPPY_TRIAGE_RESULT = {
    "answer": "Sewer backup covered, $500 deductible.", "decision": "approved", "payout": 5500.0,
    "sources": ["endorsement-HO-2026-01-water-backup.md"],
    "steps": [
        {"step": 1, "tool": "get_claim", "thought": "", "args": {"claim_id": "CLM-2001"}, "result": {"result": {"claim_id": "CLM-2001"}}, "latency_ms": 500, "tokens": 900},
        {"step": 2, "tool": "finish", "thought": "", "args": {"decision": "approved", "payout": 5500}, "result": None, "latency_ms": 400, "tokens": 200},
    ],
    "step_count": 2, "tokens_used": 1100, "cost_usd": 0.00022, "latency_ms": 900,
    "stopped_reason": "finished", "finished": True,
}

_HAPPY_QUESTION_RESULT = {
    "answer": "The deductible is $500.", "decision": None, "payout": None,
    "sources": ["endorsement-HO-2026-01-water-backup.md"],
    "steps": [
        {"step": 1, "tool": "search_policy", "thought": "", "args": {"query": "water backup deductible"}, "result": {"result": []}, "latency_ms": 500, "tokens": 900},
        {"step": 2, "tool": "finish", "thought": "", "args": {"answer": "The deductible is $500.", "sources": []}, "result": None, "latency_ms": 200, "tokens": 100},
    ],
    "step_count": 2, "tokens_used": 1000, "cost_usd": 0.0002, "latency_ms": 700,
    "stopped_reason": "finished", "finished": True,
}

_HAPPY_WORKFLOW_RESULT = {
    "answer": "The deductible is $500.", "decision": None, "payout": None,
    "sources": ["endorsement-HO-2026-01-water-backup.md"],
    "steps": [
        {"step": 1, "action": "search_policy (fixed, top_k=8, whole corpus)", "result_count": 8, "latency_ms": 20},
        {"step": 2, "action": "generate answer from the fixed retrieval", "latency_ms": 900, "tokens": 500},
    ],
    "step_count": 2, "tokens_used": 500, "cost_usd": 0.0001, "latency_ms": 920,
    "stopped_reason": "finished", "finished": True,
}


class _FakeSystem:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls: list[str] = []

    def run(self, user_input: str) -> dict:
        self.calls.append(user_input)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def agent_client():

    def _make(agent, workflow):
        app.dependency_overrides[deps.agent] = lambda: agent
        app.dependency_overrides[deps.fixed_workflow] = lambda: workflow
        return TestClient(app, raise_server_exceptions=False)

    yield _make

    app.dependency_overrides.pop(deps.agent, None)
    app.dependency_overrides.pop(deps.fixed_workflow, None)


def test_list_claims_returns_all_ten_fixture_claims(agent_client):

    client = agent_client(_FakeSystem(_HAPPY_TRIAGE_RESULT), _FakeSystem(_HAPPY_TRIAGE_RESULT))

    response = client.get("/api/v1/agent/claims")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 10
    assert body[0]["claim_id"] == "CLM-2001"
    assert "claimed_amount" in body[0] and "policy_form" in body[0]


def test_run_triages_a_claim_id_with_a_unified_decision_payout_contract(agent_client):

    client = agent_client(_FakeSystem(_HAPPY_TRIAGE_RESULT), _FakeSystem(_HAPPY_TRIAGE_RESULT))

    response = client.post("/api/v1/agent/run", json={"user_input": "CLM-2001"})

    assert response.status_code == 200
    body = response.json()
    assert body["user_input"] == "CLM-2001"
    assert body["agent"]["decision"] == "approved"
    assert body["agent"]["payout"] == 5500.0
    assert len(body["agent"]["steps"]) == 2
    assert body["workflow"]["decision"] == "approved"


def test_run_answers_a_policy_question_leaving_decision_and_payout_null(agent_client):

    client = agent_client(_FakeSystem(_HAPPY_QUESTION_RESULT), _FakeSystem(_HAPPY_WORKFLOW_RESULT))

    response = client.post("/api/v1/agent/run", json={"user_input": "What is the water backup deductible?"})

    assert response.status_code == 200
    body = response.json()
    assert body["agent"]["answer"] == "The deductible is $500."
    assert body["agent"]["decision"] is None
    assert body["agent"]["payout"] is None
    assert [s["tool"] for s in body["workflow"]["steps"]] == ["search_policy", "generate_decision"]


def test_run_rejects_an_empty_input(agent_client):

    client = agent_client(_FakeSystem(_HAPPY_QUESTION_RESULT), _FakeSystem(_HAPPY_WORKFLOW_RESULT))

    response = client.post("/api/v1/agent/run", json={"user_input": ""})

    assert response.status_code == 422


def test_run_normalizes_the_fixed_workflows_different_step_shape(agent_client):

    # Regression test: found live through the UI. The fixed workflow's real
    # steps use {action, result|raw|result_count}, not the agent's
    # {tool, args, result, thought} - without normalizing, FastAPI's response
    # validation rejected every workflow step outright ('tool' required).
    workflow_result = {
        "answer": "", "decision": "approved", "payout": 5500.0, "sources": [],
        "steps": [
            {"step": 1, "action": "get_claim (fixed)", "result": {"result": {"claim_id": "CLM-2001"}}, "latency_ms": 0},
            {"step": 2, "action": "search_policy (fixed, query = adjuster notes, top_k=8)", "result_count": 8, "latency_ms": 18},
            {"step": 3, "action": "generate coverage decision from the fixed retrieval", "raw": '{"claim_status":"approved"}', "latency_ms": 13744, "tokens": 1969},
            {"step": 4, "action": "compute_payout (fixed)", "result": {"result": {"claim_status": "approved", "payout": 5500.0}}, "latency_ms": 0},
        ],
        "step_count": 4, "tokens_used": 1969, "cost_usd": 0.0004, "latency_ms": 13762,
        "stopped_reason": "finished", "finished": True,
    }

    client = agent_client(_FakeSystem(_HAPPY_TRIAGE_RESULT), _FakeSystem(workflow_result))

    response = client.post("/api/v1/agent/run", json={"user_input": "CLM-2001"})

    assert response.status_code == 200
    steps = response.json()["workflow"]["steps"]
    assert [s["tool"] for s in steps] == ["get_claim", "search_policy", "generate_decision", "compute_payout"]
    assert steps[2]["result"]["raw"] == '{"claim_status":"approved"}'


def test_run_agent_only_skips_the_workflow_entirely(agent_client):

    agent = _FakeSystem(_HAPPY_QUESTION_RESULT)
    workflow = _FakeSystem(_HAPPY_WORKFLOW_RESULT)
    client = agent_client(agent, workflow)

    response = client.post("/api/v1/agent/run", json={"user_input": "What is the water backup deductible?", "system": "agent"})

    assert response.status_code == 200
    body = response.json()
    assert body["agent"]["answer"] == "The deductible is $500."
    assert body["workflow"] is None
    assert workflow.calls == []  # never actually called - not just hidden in the response


def test_run_workflow_only_skips_the_agent_entirely(agent_client):

    agent = _FakeSystem(_HAPPY_QUESTION_RESULT)
    workflow = _FakeSystem(_HAPPY_WORKFLOW_RESULT)
    client = agent_client(agent, workflow)

    response = client.post("/api/v1/agent/run", json={"user_input": "What is the water backup deductible?", "system": "workflow"})

    assert response.status_code == 200
    body = response.json()
    assert body["agent"] is None
    assert body["workflow"]["answer"] == "The deductible is $500."
    assert agent.calls == []


def test_run_isolates_a_failure_to_one_system(agent_client):

    client = agent_client(
        _FakeSystem(error=LLMUpstreamError("Rate limit reached.")),
        _FakeSystem(_HAPPY_WORKFLOW_RESULT),
    )

    response = client.post("/api/v1/agent/run", json={"user_input": "CLM-2001"})

    assert response.status_code == 200
    body = response.json()
    assert body["agent"]["error"] == "Rate limit reached."
    assert body["agent"]["finished"] is False
    assert body["workflow"]["answer"] == "The deductible is $500."
    assert body["workflow"]["error"] is None
