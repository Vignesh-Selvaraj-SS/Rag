"""
API tests for /api/v1/squad, against a fake standing in for
ClaimsSquadService - no live model calls.
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
    "notes": "Claim CLM-2026-02011...",
    "summary": "CLAIM: CLM-2026-02011\nCOVERAGE: covered\nDEDUCTIBLE: $500",
    "fields": {"CLAIM": "CLM-2026-02011", "COVERAGE": "covered", "DEDUCTIBLE": "$500"},
    "retrieved": [{"chunk_id": "a::1", "source": "endorsement-HO-2026-01-water-backup.md"}],
    "cited": [1],
    "cited_chunk_ids": ["a::1"],
    "invalid_citations": [],
    "handoffs": [
        {"from": "manager", "to": "summary_worker", "tokens": 300},
        {"from": "manager", "to": "coverage_worker", "tokens": 500},
        {"from": "summary_worker+coverage_worker", "to": "manager", "tokens": 400},
    ],
    "worker_error": None,
    "intermediate": {"summary_worker": "CAUSE OF LOSS: ...", "coverage_worker": "COVERAGE POSITION: covered"},
    "tokens_used": 1200,
    "cost_usd": 0.00024,
    "latency_ms": 3500,
}


class _FakeSquad:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls: list[tuple[str, bool]] = []

    def process(self, notes: str, fail_coverage_worker: bool = False) -> dict:
        self.calls.append((notes, fail_coverage_worker))
        if self.error is not None:
            raise self.error
        return self.result


@pytest.fixture
def squad_client():

    def _make(squad):
        app.dependency_overrides[deps.squad_service] = lambda: squad
        return TestClient(app, raise_server_exceptions=False)

    yield _make

    app.dependency_overrides.pop(deps.squad_service, None)


def test_run_returns_the_final_summary_and_every_agents_own_output(squad_client):

    squad = _FakeSquad(_HAPPY_RESULT)
    client = squad_client(squad)

    response = client.post("/api/v1/squad/run", json={"notes": "Claim CLM-2026-02011..."})

    assert response.status_code == 200
    body = response.json()
    assert body["fields"]["COVERAGE"] == "covered"
    assert body["sources"] == ["endorsement-HO-2026-01-water-backup.md"]
    assert len(body["handoffs"]) == 3
    assert body["intermediate"]["summary_worker"] == "CAUSE OF LOSS: ..."
    assert body["tokens_used"] == 1200
    assert body["worker_error"] is None
    assert body["error"] is None


def test_run_passes_the_simulate_failure_flag_through(squad_client):

    squad = _FakeSquad(_HAPPY_RESULT)
    client = squad_client(squad)

    client.post("/api/v1/squad/run", json={"notes": "x", "simulate_coverage_worker_failure": True})

    assert squad.calls == [("x", True)]


def test_run_defaults_simulate_failure_to_false(squad_client):

    squad = _FakeSquad(_HAPPY_RESULT)
    client = squad_client(squad)

    client.post("/api/v1/squad/run", json={"notes": "x"})

    assert squad.calls == [("x", False)]


def test_run_rejects_empty_notes(squad_client):

    client = squad_client(_FakeSquad(_HAPPY_RESULT))

    response = client.post("/api/v1/squad/run", json={"notes": ""})

    assert response.status_code == 422


def test_run_reports_an_upstream_failure_without_crashing(squad_client):

    client = squad_client(_FakeSquad(error=LLMUpstreamError("Rate limit reached.")))

    response = client.post("/api/v1/squad/run", json={"notes": "x"})

    assert response.status_code == 200
    body = response.json()
    assert body["error"] == "Rate limit reached."
    assert body["summary"] is None


_IDLE_STATUS = {
    "running": False, "current": None, "error": None,
    "total_cases": 9, "completed_pairs": 0, "total_pairs": 18,
    "per_case": [], "single_summary": None, "squad_summary": None,
    "context_resend_multiplier": None, "handoff_totals": {},
}


class _FakeRace:
    def __init__(self, start_result=None, status_result=None, start_error=None):
        self.start_result = start_result or _IDLE_STATUS
        self.status_result = status_result or _IDLE_STATUS
        self.start_error = start_error
        self.start_calls: list[dict] = []

    def start(self, only=None, sleep=5.0):
        self.start_calls.append({"only": only, "sleep": sleep})
        if self.start_error is not None:
            raise self.start_error
        return self.start_result

    def status(self):
        return self.status_result


@pytest.fixture
def race_client():

    def _make(race):
        app.dependency_overrides[deps.squad_race_service] = lambda: race
        return TestClient(app, raise_server_exceptions=False)

    yield _make

    app.dependency_overrides.pop(deps.squad_race_service, None)


def test_race_start_returns_the_initial_status(race_client):

    race = _FakeRace(start_result={**_IDLE_STATUS, "running": True})
    client = race_client(race)

    response = client.post("/api/v1/squad/race/start", json={})

    assert response.status_code == 200
    assert response.json()["running"] is True
    assert race.start_calls == [{"only": None, "sleep": 5.0}]


def test_race_start_passes_only_and_sleep_through(race_client):

    race = _FakeRace()
    client = race_client(race)

    client.post("/api/v1/squad/race/start", json={"only": ["S1", "S2"], "sleep": 2.5})

    assert race.start_calls == [{"only": ["S1", "S2"], "sleep": 2.5}]


def test_race_start_reports_already_running_as_a_400(race_client):

    from app.core.errors import BadRequestError

    race = _FakeRace(start_error=BadRequestError("A race is already running."))
    client = race_client(race)

    response = client.post("/api/v1/squad/race/start", json={})

    assert response.status_code == 400


def test_race_status_reports_progress_and_the_table_once_data_exists(race_client):

    status = {
        "running": True, "current": "S2 (claims squad)", "error": None,
        "total_cases": 9, "completed_pairs": 3, "total_pairs": 18,
        "per_case": [
            {"id": "S1", "single_status": "pass", "squad_status": "fail", "fail_injected": True},
            {"id": "S2", "single_status": "pass", "squad_status": None, "fail_injected": False},
        ],
        "single_summary": {
            "n": 2, "pass_rate": 1.0, "p50_latency_ms": 600.0, "p99_latency_ms": 800.0,
            "total_tokens": 3000, "cost_per_claim_usd": 0.0003,
        },
        "squad_summary": {
            "n": 1, "pass_rate": 0.0, "p50_latency_ms": 14000.0, "p99_latency_ms": 14000.0,
            "total_tokens": 2500, "cost_per_claim_usd": 0.0005,
        },
        "context_resend_multiplier": 0.8,
        "handoff_totals": {"manager -> coverage_worker": 1500},
    }
    client = race_client(_FakeRace(status_result=status))

    response = client.get("/api/v1/squad/race/status")

    assert response.status_code == 200
    body = response.json()
    assert body["running"] is True
    assert body["current"] == "S2 (claims squad)"
    assert len(body["per_case"]) == 2
    assert body["single_summary"]["pass_rate"] == 1.0
    assert body["handoff_totals"]["manager -> coverage_worker"] == 1500
