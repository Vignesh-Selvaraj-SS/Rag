"""
Runs the evaluation set and scores every case.

One run does three things per case, cheapest first:

    1. exercise the app (a chat answer, or a claim summary)
    2. apply the deterministic assertions   - free, no model call
    3. ask the judge                        - only for summary cases

Results are grouped by failure mode, because "83% pass" hides the thing that
matters: which mode moved. A change that fixes M3 while breaking the
out-of-scope guard is not an improvement, and only a per-mode table shows it.
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from app.core.errors import AppError, BadRequestError, NotFoundError
from app.services import eval_assertions
from app.services.citations import CITATION_PARSER_VERSION
from app.services.judge_service import CRITERIA, JUDGE_PROMPT_VERSION
from app.services.llm_service import MAX_TOKENS, PROMPT_VERSION
from app.services.summary_service import SUMMARY_PROMPT_VERSION

logger = logging.getLogger(__name__)

REQUIRED_FIELDS = ("id", "type", "mode")

# Batch runs make far more model calls per minute than an interactive user
# ever would, so the free-tier rate limit is expected here, not exceptional.
# The production chat path deliberately does not retry (a real request should
# fail fast); this loop exists only for the evaluation runner.
RATE_LIMIT_RETRIES = 4
RATE_LIMIT_WAIT_S = 20


def _call_with_retry(fn, *args, **kwargs):

    last_error: AppError | None = None

    for attempt in range(RATE_LIMIT_RETRIES):

        try:
            return fn(*args, **kwargs)
        except AppError as error:
            if error.status_code != 502:
                raise
            last_error = error
            wait = RATE_LIMIT_WAIT_S * (attempt + 1)
            logger.warning("Upstream error (attempt %d/%d); waiting %ss: %s",
                           attempt + 1, RATE_LIMIT_RETRIES, wait, error.message)
            time.sleep(wait)

    raise last_error


class EvalService:

    def __init__(self, eval_set_path: Path, runs_dir: Path):

        self.eval_set_path = eval_set_path
        self.runs_dir = runs_dir

    # ------------------------------------------------------------- eval set

    def load_cases(self) -> list[dict]:

        if not self.eval_set_path.exists():
            raise NotFoundError(
                f"No evaluation set at {self.eval_set_path}. See docs/training/week6/results.md."
            )

        cases = []

        with self.eval_set_path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    case = json.loads(line)
                except json.JSONDecodeError as error:
                    raise BadRequestError(f"Line {number} of the eval set is not valid JSON: {error}")

                for field in REQUIRED_FIELDS:
                    if not case.get(field):
                        raise BadRequestError(f"Case on line {number} is missing '{field}'")

                cases.append(case)

        return cases

    # ----------------------------------------------------------------- run

    def run(
        self,
        rag_service,
        summary_service=None,
        judge_service=None,
        label: str | None = None,
        only: list[str] | None = None,
        use_judge: bool = True,
        sleep: float = 0.5,
        progress=None,
    ) -> dict:

        cases = self.load_cases()

        if only:
            wanted = set(only)
            cases = [case for case in cases if case["id"] in wanted or case["mode"] in wanted]

        if not cases:
            raise BadRequestError("No cases selected.")

        results = []
        started_at = time.perf_counter()

        for position, case in enumerate(cases, start=1):

            if progress:
                progress(position, len(cases), case)

            result = self._run_case(case, rag_service, summary_service, judge_service, use_judge)
            results.append(result)

            if sleep and position < len(cases):
                time.sleep(sleep)

        run = self._aggregate(results, label, use_judge)
        run["duration_s"] = round(time.perf_counter() - started_at, 1)

        self._save(run)

        return run

    def _run_case(self, case, rag_service, summary_service, judge_service, use_judge) -> dict:

        record = {
            "id": case["id"],
            "mode": case["mode"],
            "type": case["type"],
            "source_trace": case.get("source_trace"),
            "prompt": case.get("question") or case.get("notes"),
            "error": None,
            "checks": [],
            "judge": None,
        }

        started = time.perf_counter()

        try:
            if case["type"] == "summary":
                if summary_service is None:
                    raise BadRequestError("Summary cases need a summary service.")
                outcome = _call_with_retry(
                    summary_service.summarise, case["notes"], mode=case.get("retrieval_mode", "hybrid")
                )
                outcome["answer"] = outcome["summary"]
            else:
                outcome = _call_with_retry(
                    rag_service.ask, case["question"], mode=case.get("retrieval_mode", "dense")
                )
                # ask() names citations "sources" (a list of retrieved-hit
                # dicts); the assertions and trace_checks expect the same
                # "cited_chunk_ids" shape a recorded trace carries. Without
                # this every QA case would read as uncited regardless of
                # what the model actually did.
                outcome["cited_chunk_ids"] = [hit["chunk_id"] for hit in outcome.get("sources", [])]

            record["output"] = outcome.get("summary") or outcome.get("answer")
            record["refused"] = bool(outcome.get("refused"))
            record["refused_by"] = outcome.get("refused_by")
            record["cited_chunk_ids"] = outcome.get("cited_chunk_ids") or []
            record["retrieved_chunk_ids"] = [hit["chunk_id"] for hit in outcome.get("retrieved", [])]
            record["checks"] = eval_assertions.run_assertions(case, outcome)

            if use_judge and case["type"] == "summary" and case.get("judge", True):
                if judge_service is None:
                    raise BadRequestError("Summary cases need a judge service, or pass use_judge=False.")
                record["judge"] = _call_with_retry(
                    judge_service.judge, case["notes"], outcome["summary"], outcome.get("retrieved", [])
                )

        except Exception as error:  # noqa: BLE001 - one bad case must not lose the run
            logger.warning("Case %s failed: %s: %s", case["id"], type(error).__name__, error)
            record["error"] = f"{type(error).__name__}: {error}"
            record["checks"] = [
                {"id": "run", "name": "Case ran", "status": "fail", "detail": record["error"]}
            ]

        record["latency_ms"] = int((time.perf_counter() - started) * 1000)
        record["status"] = self._status(record)

        return record

    @staticmethod
    def _status(record: dict) -> str:

        assertion_status = eval_assertions.summarise(record["checks"])

        judge = record.get("judge")

        if judge and judge["status"] != "pass" and assertion_status == "pass":
            return "fail"

        return assertion_status

    # ----------------------------------------------------------- aggregate

    def _aggregate(self, results: list[dict], label: str | None, use_judge: bool) -> dict:

        by_mode: dict[str, dict] = {}

        for record in results:

            bucket = by_mode.setdefault(
                record["mode"], {"mode": record["mode"], "total": 0, "passed": 0, "failed": 0, "review": 0}
            )
            bucket["total"] += 1

            if record["status"] == "pass":
                bucket["passed"] += 1
            elif record["status"] == "review":
                bucket["review"] += 1
            else:
                bucket["failed"] += 1

        for bucket in by_mode.values():
            bucket["pass_rate"] = round(bucket["passed"] / bucket["total"], 4)

        by_assertion: dict[str, dict] = {}

        for record in results:
            for check in record["checks"]:
                bucket = by_assertion.setdefault(
                    check["id"],
                    {"id": check["id"], "name": check["name"], "pass": 0, "fail": 0, "review": 0, "skip": 0},
                )
                bucket[check["status"]] = bucket.get(check["status"], 0) + 1

        judged = [record["judge"] for record in results if record.get("judge")]

        judge_summary = None

        if judged:
            judge_summary = {
                "cases": len(judged),
                "all_pass": sum(1 for j in judged if j["status"] == "pass"),
                "by_criterion": {
                    criterion["id"]: {
                        "name": criterion["name"],
                        "pass": sum(1 for j in judged if j["verdicts"][criterion["id"]]["verdict"] == "pass"),
                        "fail": sum(1 for j in judged if j["verdicts"][criterion["id"]]["verdict"] == "fail"),
                        "error": sum(1 for j in judged if j["verdicts"][criterion["id"]]["verdict"] == "error"),
                    }
                    for criterion in CRITERIA
                },
            }

        passed = sum(1 for record in results if record["status"] == "pass")

        return {
            "label": label or "run",
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "versions": {
                "prompt_version": PROMPT_VERSION,
                "summary_prompt_version": SUMMARY_PROMPT_VERSION,
                "judge_prompt_version": JUDGE_PROMPT_VERSION,
                "citation_parser_version": CITATION_PARSER_VERSION,
                "max_tokens": MAX_TOKENS,
            },
            "totals": {
                "cases": len(results),
                "passed": passed,
                "failed": sum(1 for record in results if record["status"] == "fail"),
                "review": sum(1 for record in results if record["status"] == "review"),
                "errors": sum(1 for record in results if record["error"]),
                "pass_rate": round(passed / len(results), 4) if results else 0.0,
            },
            "judge_used": use_judge,
            "judge": judge_summary,
            "by_mode": [by_mode[key] for key in sorted(by_mode)],
            "by_assertion": [by_assertion[key] for key in sorted(by_assertion)],
            "cases": results,
        }

    # ---------------------------------------------------------------- store

    def _save(self, run: dict) -> Path:

        self.runs_dir.mkdir(parents=True, exist_ok=True)

        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in run["label"])
        path = self.runs_dir / f"{safe}.json"
        path.write_text(json.dumps(run, indent=2, ensure_ascii=False), encoding="utf-8")

        run["path"] = str(path)

        return path

    def load_run(self, label: str) -> dict:

        safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in label)
        path = self.runs_dir / f"{safe}.json"

        if not path.is_file():
            raise NotFoundError(f"No evaluation run labelled '{label}'.")

        return json.loads(path.read_text(encoding="utf-8"))


def compare(before: dict, after: dict) -> list[dict]:
    """Per-mode before/after deltas, the table the week is graded on."""

    before_modes = {row["mode"]: row for row in before["by_mode"]}
    after_modes = {row["mode"]: row for row in after["by_mode"]}

    rows = []

    for mode in sorted(set(before_modes) | set(after_modes)):

        old = before_modes.get(mode)
        new = after_modes.get(mode)

        rows.append(
            {
                "mode": mode,
                "before_passed": old["passed"] if old else None,
                "before_total": old["total"] if old else None,
                "before_rate": old["pass_rate"] if old else None,
                "after_passed": new["passed"] if new else None,
                "after_total": new["total"] if new else None,
                "after_rate": new["pass_rate"] if new else None,
                "delta": round(new["pass_rate"] - old["pass_rate"], 4) if old and new else None,
            }
        )

    return rows
