"""
Unit tests for SquadRaceService (app/services/squad_race_service.py) -
against fakes standing in for SummaryService/ClaimsSquadService/JudgeService
and a tiny temp eval set (2 cases, not the real 9), so these run fast and
deterministically, no live model calls and no dependency on the real
evaluation/eval_set.jsonl.
"""

import json
import time

import pytest

from app.core.errors import BadRequestError
from app.services.squad_race_service import SquadRaceService

CASES = [
    # "S1" matches squad_race_service.FAILURE_INJECTION_CASE_ID exactly -
    # the real constant, not reconfigurable per-test, so the fake case set
    # has to use the same id to exercise the injection path.
    {"id": "S1", "mode": "M6", "type": "summary", "notes": "Claim notes one", "judge": True, "retrieval_mode": "hybrid"},
    {"id": "T2", "mode": "M6", "type": "summary", "notes": "Claim notes two", "judge": True, "retrieval_mode": "hybrid"},
]

PASSING_SUMMARY = "CLAIM: CLM-2026-00001\nDATE OF LOSS: 2026-01-01\nCOVERAGE: covered\nBASIS: per [S1]\nDEDUCTIBLE: $500\nNEXT ACTION: pay it"


class _FakeSummaryService:
    def __init__(self, delay: float = 0.0):
        self.delay = delay
        self.calls: list[str] = []

    def summarise(self, notes, mode="hybrid"):
        self.calls.append(notes)
        if self.delay:
            time.sleep(self.delay)
        return {
            "summary": PASSING_SUMMARY,
            "fields": {"CLAIM": "CLM-2026-00001", "COVERAGE": "covered"},
            "retrieved": [{"chunk_id": "a::1", "source": "a.md"}],
            "cited_chunk_ids": ["a::1"],
            "invalid_citations": [],
            "refused": False,
            "tokens_used": 500,
            "cost_usd": 0.0001,
            "latency_ms": 50,
        }


class _FakeSquadService:
    def __init__(self):
        self.calls: list[tuple[str, bool]] = []

    def process(self, notes, mode="hybrid", fail_coverage_worker=False):
        self.calls.append((notes, fail_coverage_worker))
        return {
            "summary": PASSING_SUMMARY,
            "fields": {"CLAIM": "CLM-2026-00001", "COVERAGE": "covered"},
            "retrieved": [{"chunk_id": "a::1", "source": "a.md"}],
            "cited_chunk_ids": ["a::1"],
            "invalid_citations": [],
            "refused": False,
            "handoffs": [
                {"from": "manager", "to": "summary_worker", "tokens": 100},
                {"from": "manager", "to": "coverage_worker", "tokens": 200},
                {"from": "summary_worker+coverage_worker", "to": "manager", "tokens": 150},
            ],
            "worker_error": "simulated" if fail_coverage_worker else None,
            "intermediate": {"summary_worker": "...", "coverage_worker": "..."},
            "tokens_used": 450,
            "cost_usd": 0.00009,
            "latency_ms": 60,
        }


class _FakeJudgeService:
    def judge(self, notes, summary, hits):
        return {"status": "pass", "verdicts": {"J1": {"verdict": "pass"}}}


class _FakeRagService:
    def chunk_count(self):
        return 5


def _service(tmp_path, summary_service=None, sleep_between=0.0):

    eval_set_path = tmp_path / "eval_set.jsonl"
    eval_set_path.write_text("\n".join(json.dumps(c) for c in CASES), encoding="utf-8")

    return SquadRaceService(
        results_path=tmp_path / "results.json",
        rag_service=_FakeRagService(),
        summary_service=summary_service or _FakeSummaryService(),
        squad_service=_FakeSquadService(),
        judge_service=_FakeJudgeService(),
        eval_set_path=eval_set_path,
        eval_runs_dir=tmp_path / "runs",
    )


def _wait_until_done(service, timeout=5.0):
    started = time.time()
    while service.status()["running"]:
        if time.time() - started > timeout:
            raise AssertionError("race did not finish in time")
        time.sleep(0.02)


def test_status_before_any_run_shows_nothing_completed(tmp_path):

    service = _service(tmp_path)

    status = service.status()

    assert status["running"] is False
    assert status["total_cases"] == 2
    assert status["completed_pairs"] == 0
    assert status["single_summary"] is None
    assert status["squad_summary"] is None
    assert [c["single_status"] for c in status["per_case"]] == [None, None]


def test_start_runs_both_arms_for_every_case_and_fills_in_the_summary(tmp_path):

    service = _service(tmp_path, sleep_between=0.0)

    service.start(sleep=0.0)
    _wait_until_done(service)

    status = service.status()
    assert status["completed_pairs"] == 4  # 2 cases x 2 arms
    assert status["single_summary"]["n"] == 2
    assert status["squad_summary"]["n"] == 2
    assert status["context_resend_multiplier"] == round(900 / 1000, 1)  # 2x450 squad vs 2x500 single


def test_start_injects_the_failure_only_on_the_designated_case(tmp_path):

    squad = _FakeSquadService()
    service = _service(tmp_path)
    service.squad_service = squad

    service.start(sleep=0.0)
    _wait_until_done(service)

    calls_by_notes = {notes: fail for notes, fail in squad.calls}
    assert calls_by_notes["Claim notes one"] is True   # case "S1" - the designated case
    assert calls_by_notes["Claim notes two"] is False


def test_start_raises_if_a_race_is_already_running(tmp_path):

    slow_summary = _FakeSummaryService(delay=0.3)
    service = _service(tmp_path, summary_service=slow_summary)

    service.start(sleep=0.0)
    with pytest.raises(BadRequestError):
        service.start(sleep=0.0)

    _wait_until_done(service)


def test_results_persist_incrementally_to_the_results_file(tmp_path):

    service = _service(tmp_path)
    service.start(sleep=0.0)
    _wait_until_done(service)

    saved = json.loads(service.results_path.read_text(encoding="utf-8"))
    assert len(saved) == 4
    assert {(r["id"], r["arm"]) for r in saved} == {("S1", "single"), ("S1", "squad"), ("T2", "single"), ("T2", "squad")}


def test_handoff_totals_sum_across_both_completed_cases(tmp_path):

    service = _service(tmp_path)
    service.start(sleep=0.0)
    _wait_until_done(service)

    status = service.status()
    assert status["handoff_totals"]["manager -> coverage_worker"] == 400  # 200 x 2 cases
