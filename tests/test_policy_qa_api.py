"""
API tests for /api/v1/policy-qa/ask, against fakes standing in for
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

_HAPPY_AGENT_RESULT = {
    "answer": "The deductible is $500.", "sources": ["endorsement-HO-2026-01-water-backup.md"],
    "steps": [
        {"step": 1, "tool": "search_policy", "thought": "", "args": {"query": "water backup deductible"}, "result": {"result": []}, "latency_ms": 500, "tokens": 900},
        {"step": 2, "tool": "finish", "thought": "", "args": {"answer": "The deductible is $500.", "sources": []}, "result": None, "latency_ms": 200, "tokens": 100},
    ],
    "step_count": 2, "tokens_used": 1000, "latency_ms": 700, "stopped_reason": "finished", "finished": True,
}

_HAPPY_WORKFLOW_RESULT = {
    "answer": "The deductible is $500.", "sources": ["endorsement-HO-2026-01-water-backup.md"],
    "steps": [
        {"step": 1, "action": "search_policy (fixed, top_k=8, whole corpus)", "result_count": 8, "latency_ms": 20},
        {"step": 2, "action": "generate answer from the fixed retrieval", "latency_ms": 900, "tokens": 500},
    ],
    "step_count": 2, "tokens_used": 500, "latency_ms": 920, "stopped_reason": "finished", "finished": True,
}


class _FakeSystem:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls: list[str] = []

    def run(self, question: str) -> dict:
        self.calls.append(question)
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def policy_qa_client():

    def _make(agent, workflow):
        app.dependency_overrides[deps.policy_agent] = lambda: agent
        app.dependency_overrides[deps.fixed_policy_workflow] = lambda: workflow
        return TestClient(app, raise_server_exceptions=False)

    yield _make

    app.dependency_overrides.pop(deps.policy_agent, None)
    app.dependency_overrides.pop(deps.fixed_policy_workflow, None)


def test_ask_returns_both_systems_results(policy_qa_client):

    client = policy_qa_client(_FakeSystem(_HAPPY_AGENT_RESULT), _FakeSystem(_HAPPY_WORKFLOW_RESULT))

    response = client.post("/api/v1/policy-qa/ask", json={"question": "What is the water backup deductible?"})

    assert response.status_code == 200
    body = response.json()
    assert body["agent"]["answer"] == "The deductible is $500."
    assert [s["tool"] for s in body["agent"]["steps"]] == ["search_policy", "finish"]
    assert body["workflow"]["answer"] == "The deductible is $500."
    # the fixed workflow's {action: ...} steps normalize to the same shape
    assert [s["tool"] for s in body["workflow"]["steps"]] == ["search_policy", "generate_decision"]


def test_ask_rejects_an_empty_question(policy_qa_client):

    client = policy_qa_client(_FakeSystem(_HAPPY_AGENT_RESULT), _FakeSystem(_HAPPY_WORKFLOW_RESULT))

    response = client.post("/api/v1/policy-qa/ask", json={"question": ""})

    assert response.status_code == 422


def test_ask_agent_only_skips_the_workflow_entirely(policy_qa_client):

    agent = _FakeSystem(_HAPPY_AGENT_RESULT)
    workflow = _FakeSystem(_HAPPY_WORKFLOW_RESULT)
    client = policy_qa_client(agent, workflow)

    response = client.post("/api/v1/policy-qa/ask", json={"question": "What is the water backup deductible?", "system": "agent"})

    assert response.status_code == 200
    body = response.json()
    assert body["agent"]["answer"] == "The deductible is $500."
    assert body["workflow"] is None
    assert workflow.calls == []  # never actually called - not just hidden in the response


def test_ask_workflow_only_skips_the_agent_entirely(policy_qa_client):

    agent = _FakeSystem(_HAPPY_AGENT_RESULT)
    workflow = _FakeSystem(_HAPPY_WORKFLOW_RESULT)
    client = policy_qa_client(agent, workflow)

    response = client.post("/api/v1/policy-qa/ask", json={"question": "What is the water backup deductible?", "system": "workflow"})

    assert response.status_code == 200
    body = response.json()
    assert body["agent"] is None
    assert body["workflow"]["answer"] == "The deductible is $500."
    assert agent.calls == []


def test_ask_isolates_a_failure_to_one_system(policy_qa_client):

    client = policy_qa_client(
        _FakeSystem(error=LLMUpstreamError("Rate limit reached.")),
        _FakeSystem(_HAPPY_WORKFLOW_RESULT),
    )

    response = client.post("/api/v1/policy-qa/ask", json={"question": "What is the water backup deductible?"})

    assert response.status_code == 200
    body = response.json()
    assert body["agent"]["error"] == "Rate limit reached."
    assert body["agent"]["finished"] is False
    assert body["workflow"]["answer"] == "The deductible is $500."
    assert body["workflow"]["error"] is None
