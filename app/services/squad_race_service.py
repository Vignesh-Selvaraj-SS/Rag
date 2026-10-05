"""
Week 10: runs the claims-squad-vs-single-agent race over the Week 6 M6
cases, one case/arm at a time, saving incrementally to
.runtime/claims_squad_race/results.json - the single source of truth both
`scripts/race_claims_squad.py` (CLI) and `app/api/squad.py` (the UI's
"Run race" button, polling `status()`) read and write through this one
class, so neither path can silently drift from the other.

Runs in a background thread (`start()`), not the request thread - a full
race makes dozens of real Groq calls and takes minutes, which is not
something an HTTP request should block on. `status()` is cheap and safe to
poll frequently: it reads the same results file `_run` is writing to.
"""

import json
import logging
import os
import statistics
import threading
import time
from pathlib import Path

from app.core.errors import BadRequestError
from app.services import eval_assertions
from app.services.eval_service import EvalService, _call_with_retry

logger = logging.getLogger(__name__)

# Picked once, ahead of any race, by file order (first M6 case) - not
# chosen after seeing which case would make the squad look best or worst.
FAILURE_INJECTION_CASE_ID = "S1"


def status_for(checks: list[dict], judge: dict | None) -> str:
    assertion_status = eval_assertions.summarise(checks)
    if judge and judge["status"] != "pass" and assertion_status == "pass":
        return "fail"
    return assertion_status


def p50(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def p99(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round(0.99 * (len(ordered) - 1))))
    return ordered[index]


def run_single_agent_case(case: dict, summary_service, judge_service) -> dict:

    outcome = _call_with_retry(
        summary_service.summarise, case["notes"], mode=case.get("retrieval_mode", "hybrid")
    )
    outcome["answer"] = outcome["summary"]  # trace_checks.py's shared assertions read "answer"
    checks = eval_assertions.run_assertions(case, outcome)

    judge = None
    if case.get("judge", True):
        judge = _call_with_retry(
            judge_service.judge, case["notes"], outcome["summary"], outcome.get("retrieved", [])
        )

    return {
        "id": case["id"],
        "arm": "single",
        "status": status_for(checks, judge),
        "checks": checks,
        "judge": judge,
        "tokens_used": outcome["tokens_used"],
        "cost_usd": outcome["cost_usd"],
        "latency_ms": outcome["latency_ms"],
        "summary": outcome["summary"],
    }


def run_squad_case(case: dict, squad_service, judge_service, fail_coverage_worker: bool) -> dict:

    outcome = _call_with_retry(
        squad_service.process,
        case["notes"],
        mode=case.get("retrieval_mode", "hybrid"),
        fail_coverage_worker=fail_coverage_worker,
    )
    outcome["answer"] = outcome["summary"]  # trace_checks.py's shared assertions read "answer"
    checks = eval_assertions.run_assertions(case, outcome)

    judge = None
    if case.get("judge", True):
        judge = _call_with_retry(
            judge_service.judge, case["notes"], outcome["summary"], outcome.get("retrieved", [])
        )

    return {
        "id": case["id"],
        "arm": "squad",
        "status": status_for(checks, judge),
        "checks": checks,
        "judge": judge,
        "tokens_used": outcome["tokens_used"],
        "cost_usd": outcome["cost_usd"],
        "latency_ms": outcome["latency_ms"],
        "summary": outcome["summary"],
        "handoffs": outcome["handoffs"],
        "worker_error": outcome["worker_error"],
        "intermediate": outcome["intermediate"],
        "fail_injected": fail_coverage_worker,
    }


def arm_summary(records: list[dict]) -> dict:

    n = len(records)
    passed = sum(1 for r in records if r["status"] == "pass")
    latencies = [r["latency_ms"] for r in records]
    total_tokens = sum(r["tokens_used"] for r in records)
    total_cost = sum(r["cost_usd"] for r in records)

    return {
        "n": n,
        "pass_rate": round(passed / n, 4) if n else 0.0,
        "p50_latency_ms": p50(latencies),
        "p99_latency_ms": p99(latencies),
        "total_tokens": total_tokens,
        "cost_per_claim_usd": round(total_cost / n, 6) if n else 0.0,
    }


def handoff_totals(squad_records: list[dict]) -> dict[str, int]:

    totals: dict[str, int] = {}
    for record in squad_records:
        for handoff in record.get("handoffs", []):
            key = f"{handoff['from']} -> {handoff['to']}"
            totals[key] = totals.get(key, 0) + handoff["tokens"]
    return totals


class SquadRaceService:
    """Tracks one race run's live progress - drivable by either the CLI script or the API."""

    def __init__(self, results_path: Path, rag_service, summary_service, squad_service, judge_service, eval_set_path, eval_runs_dir):

        self.results_path = results_path
        self.rag_service = rag_service
        self.summary_service = summary_service
        self.squad_service = squad_service
        self.judge_service = judge_service
        self.eval_set_path = eval_set_path
        self.eval_runs_dir = eval_runs_dir

        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._running = False
        self._current: str | None = None
        self._error: str | None = None

    def _load_cases(self, only: list[str] | None) -> list[dict]:

        eval_service = EvalService(eval_set_path=self.eval_set_path, runs_dir=self.eval_runs_dir)
        cases = [case for case in eval_service.load_cases() if case["mode"] == "M6"]
        if only:
            wanted = set(only)
            cases = [case for case in cases if case["id"] in wanted]
        return cases

    def _load_results(self) -> dict[tuple[str, str], dict]:

        if not self.results_path.exists():
            return {}

        # Windows can also transiently deny a *read* while another thread's
        # os.replace() is mid-flight on the same path (not just deny the
        # replace itself) - the same race as _save's retry, other
        # direction. GET /race/status hits this for real while a race is
        # actively saving.
        text = ""
        for attempt in range(5):
            try:
                text = self.results_path.read_text(encoding="utf-8").strip()
                break
            except (PermissionError, FileNotFoundError):
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))

        if not text:
            return {}
        records = json.loads(text)
        return {(record["id"], record["arm"]): record for record in records}

    def _save(self, results_by_key: dict) -> None:
        """
        Writes to a sibling temp file, then atomically replaces the real
        path - `GET /race/status` reads this same file from the request
        thread while the background race thread keeps writing it, and a
        plain write_text() truncates the file before writing the new
        content, so a poll landing in that window sees an empty/partial
        file and the JSON parse blows up. os.replace() is atomic on both
        Windows and POSIX: a reader only ever sees the old complete file or
        the new complete file, never a half-written one.
        """

        self.results_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.results_path.with_suffix(".json.tmp")
        tmp_path.write_text(
            json.dumps(list(results_by_key.values()), indent=2, ensure_ascii=False), encoding="utf-8"
        )

        # Windows (unlike POSIX) can refuse to replace a file that another
        # thread has open for reading at that exact instant - live-hit here
        # by GET /race/status's _load_results() racing this same write.
        # The reader's handle is open/read/close in one call, so it's gone
        # within microseconds; a few short retries clears essentially every
        # real occurrence without masking a genuine, persistent lock.
        for attempt in range(5):
            try:
                os.replace(tmp_path, self.results_path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))

    def start(self, only: list[str] | None = None, sleep: float = 5.0) -> dict:

        with self._lock:
            if self._running:
                raise BadRequestError("A race is already running.")
            self._running = True
            self._error = None
            self._current = None
            self._thread = threading.Thread(target=self._run, args=(only, sleep), daemon=True)
            self._thread.start()

        return self.status()

    def _run(self, only: list[str] | None, sleep: float) -> None:

        try:
            cases = self._load_cases(only)
            results_by_key = self._load_results()

            for position, case in enumerate(cases):

                if (case["id"], "single") not in results_by_key:
                    if position > 0 or results_by_key:
                        time.sleep(sleep)
                    self._current = f"{case['id']} (single agent)"
                    try:
                        record = run_single_agent_case(case, self.summary_service, self.judge_service)
                        results_by_key[(case["id"], "single")] = record
                    except Exception as error:  # noqa: BLE001 - one bad case must not lose the run
                        logger.warning("Race case %s/single failed: %s", case["id"], error)
                    self._save(results_by_key)

                inject = case["id"] == FAILURE_INJECTION_CASE_ID

                if (case["id"], "squad") not in results_by_key:
                    time.sleep(sleep)
                    self._current = f"{case['id']} (claims squad{', failure injected' if inject else ''})"
                    try:
                        record = run_squad_case(case, self.squad_service, self.judge_service, fail_coverage_worker=inject)
                        results_by_key[(case["id"], "squad")] = record
                    except Exception as error:  # noqa: BLE001
                        logger.warning("Race case %s/squad failed: %s", case["id"], error)
                    self._save(results_by_key)

        except Exception as error:  # noqa: BLE001 - a bug here must still clear `running`, not hang the UI forever
            logger.exception("Race run failed")
            self._error = str(error)
        finally:
            self._current = None
            with self._lock:
                self._running = False

    def status(self) -> dict:

        results_by_key = self._load_results()
        all_cases = self._load_cases(only=None)
        case_ids = [case["id"] for case in all_cases]

        single = [results_by_key[(cid, "single")] for cid in case_ids if (cid, "single") in results_by_key]
        squad = [results_by_key[(cid, "squad")] for cid in case_ids if (cid, "squad") in results_by_key]

        per_case = [
            {
                "id": cid,
                "single_status": results_by_key.get((cid, "single"), {}).get("status"),
                "squad_status": results_by_key.get((cid, "squad"), {}).get("status"),
                "fail_injected": cid == FAILURE_INJECTION_CASE_ID,
            }
            for cid in case_ids
        ]

        single_summary = arm_summary(single) if single else None
        squad_summary = arm_summary(squad) if squad else None
        multiplier = (
            round(squad_summary["total_tokens"] / single_summary["total_tokens"], 1)
            if single_summary and single_summary["total_tokens"]
            else None
        )

        return {
            "running": self._running,
            "current": self._current,
            "error": self._error,
            "total_cases": len(case_ids),
            "completed_pairs": len(single) + len(squad),
            "total_pairs": len(case_ids) * 2,
            "per_case": per_case,
            "single_summary": single_summary,
            "squad_summary": squad_summary,
            "context_resend_multiplier": multiplier,
            "handoff_totals": handoff_totals(squad) if squad else {},
        }
