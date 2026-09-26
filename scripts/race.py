"""
Race the merged ClaimAgent against its fixed workflow, over either eval set:

  --suite triage  (default) the 10 claim-triage cases (evaluation/triage_claims.json),
                  scored by decision/payout match - the Week 7/8 deliverable suite.
                  Saves .runtime/triage_race/results.json and docs/training/week7/race.csv.
  --suite policy  the 6 free-text policy-question scenarios
                  (evaluation/agent_race_scenarios.json), scored by keyword coverage.
                  Saves .runtime/agent_race/results.json.
  --suite both    runs both suites in sequence.

    python scripts/race.py
    python scripts/race.py --suite policy
    python scripts/race.py --suite triage --only CLM-2002 CLM-2003
    python scripts/race.py --sleep 20   # pace calls under the Groq rate limit

Stop the API server first: embedded Qdrant locks its folder to one process.
Needs GROQ_API_KEY.
"""

import argparse
import csv
import json
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.core.errors import AppError  # noqa: E402
from app.services.agent_service import ClaimAgent  # noqa: E402
from app.services.claims_data import all_claim_ids, get_claim_record  # noqa: E402
from app.services.fixed_claim_workflow import FixedClaimWorkflow  # noqa: E402
from app.services.retrieval_service import RetrievalService  # noqa: E402

POLICY_SCENARIOS_PATH = REPO_ROOT / "evaluation" / "agent_race_scenarios.json"
POLICY_RESULTS_PATH = REPO_ROOT / ".runtime" / "agent_race" / "results.json"

TRIAGE_RESULTS_PATH = REPO_ROOT / ".runtime" / "triage_race" / "results.json"
TRIAGE_RACE_CSV_PATH = REPO_ROOT / "docs" / "training" / "week7" / "race.csv"

# A payout within a dollar of the expected figure still passes - guards only
# against float rounding from the arithmetic itself, not against the system
# getting the wrong deductible or decision.
PAYOUT_TOLERANCE = 1.0


def p50(values: list[int]) -> int:
    return int(statistics.median(values)) if values else 0


# ---------------------------------------------------------------- policy suite

def score_reliability(answer: str, expected_keywords: list[str]) -> tuple[int, int]:
    """
    How many of the facts the question actually asked for show up in the
    answer, case-insensitive substring match. Deterministic and free - not a
    judgement call, so no model call is spent checking it.
    """

    answer_lower = (answer or "").lower()
    found = sum(1 for kw in expected_keywords if kw.lower() in answer_lower)

    return found, len(expected_keywords)


def _run_policy_system(run_fn, question: str, expected_keywords: list[str]) -> dict:
    """Isolates a hard upstream failure to this one system/scenario cell instead of losing the whole race."""

    try:
        result = run_fn(question)
    except AppError as error:
        return {
            "answer": None, "sources": [], "steps": [], "step_count": 0,
            "tokens_used": 0, "latency_ms": 0, "stopped_reason": "error",
            "finished": False, "keywords_found": 0,
            "keywords_total": len(expected_keywords), "error": str(error),
        }

    found, total = score_reliability(result["answer"] or "", expected_keywords)

    return {
        "answer": result["answer"],
        "sources": result["sources"],
        "steps": result["steps"],
        "step_count": result["step_count"],
        "tokens_used": result["tokens_used"],
        "latency_ms": result["latency_ms"],
        "stopped_reason": result.get("stopped_reason", "finished"),
        "finished": result["finished"],
        "keywords_found": found,
        "keywords_total": total,
    }


def run_policy_scenario(scenario: dict, agent: ClaimAgent, workflow: FixedClaimWorkflow) -> dict:

    question = scenario["claim"]
    expected_keywords = scenario["expected_keywords"]

    return {
        "id": scenario["id"],
        "complexity": scenario["complexity"],
        "claim": question,
        "expected_keywords": expected_keywords,
        "agent": _run_policy_system(agent.run, question, expected_keywords),
        "workflow": _run_policy_system(workflow.run, question, expected_keywords),
    }


def run_policy_suite(agent: ClaimAgent, workflow: FixedClaimWorkflow, only: list[str] | None, sleep: float) -> int:

    scenarios = json.loads(POLICY_SCENARIOS_PATH.read_text(encoding="utf-8"))

    if only:
        wanted = set(only)
        scenarios = [s for s in scenarios if s["id"] in wanted]

    results = []

    for i, scenario in enumerate(scenarios):
        if i > 0 and sleep:
            print(f"(sleeping {sleep}s to stay under the rate limit)")
            time.sleep(sleep)
        print(f"[{scenario['id']}] ({scenario['complexity']}) racing ...", end="", flush=True)
        started = time.perf_counter()
        result = run_policy_scenario(scenario, agent, workflow)
        results.append(result)
        print(f" done ({time.perf_counter() - started:.1f}s)")

        POLICY_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        POLICY_RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    if not results:
        print("No scenarios completed.")
        return 1

    print()
    header = f"{'id':<5}{'complexity':<11}{'agent steps':>12}{'agent tok':>11}{'agent ms':>10}{'agent rel':>11}{'fixed tok':>11}{'fixed ms':>10}{'fixed rel':>11}"
    print(header)
    print("-" * len(header))

    for r in results:
        a, w = r["agent"], r["workflow"]
        a_rel = f"{a['keywords_found']}/{a['keywords_total']}"
        w_rel = f"{w['keywords_found']}/{w['keywords_total']}"
        print(
            f"{r['id']:<5}{r['complexity']:<11}{a['step_count']:>12}{a['tokens_used']:>11}"
            f"{a['latency_ms']:>10}{a_rel:>11}{w['tokens_used']:>11}{w['latency_ms']:>10}{w_rel:>11}"
        )

    total_agent_tokens = sum(r["agent"]["tokens_used"] for r in results)
    total_workflow_tokens = sum(r["workflow"]["tokens_used"] for r in results)
    total_agent_ms = sum(r["agent"]["latency_ms"] for r in results)
    total_workflow_ms = sum(r["workflow"]["latency_ms"] for r in results)
    agent_rel = sum(r["agent"]["keywords_found"] for r in results)
    workflow_rel = sum(r["workflow"]["keywords_found"] for r in results)
    total_keywords = sum(r["agent"]["keywords_total"] for r in results)

    print()
    print(f"totals: agent {total_agent_tokens} tok, {total_agent_ms}ms, {agent_rel}/{total_keywords} facts covered")
    print(f"        fixed {total_workflow_tokens} tok, {total_workflow_ms}ms, {workflow_rel}/{total_keywords} facts covered")
    print(f"\nSaved: {POLICY_RESULTS_PATH.relative_to(REPO_ROOT)}")

    return 0


# ---------------------------------------------------------------- triage suite

def triage_scores(decision: str | None, payout, expected: dict) -> bool:

    if decision is None or payout is None:
        return False

    if decision.lower() != expected["decision"]:
        return False

    return abs(float(payout) - float(expected["payout"])) <= PAYOUT_TOLERANCE


def _run_triage_system(run_fn, claim_id: str, expected: dict) -> dict:
    """Isolates a hard upstream failure to this one system/claim cell instead of losing the whole race."""

    try:
        result = run_fn(claim_id)
    except AppError as error:
        steps = getattr(error, "steps", [])
        tokens_used = getattr(error, "tokens_used", 0)
        return {
            "decision": None, "payout": None, "sources": [], "steps": steps,
            "step_count": len(steps), "tokens_used": tokens_used, "cost_usd": 0.0, "latency_ms": 0,
            "stopped_reason": "error", "finished": False, "passed": False,
            "error": str(error),
        }

    return {
        "decision": result["decision"],
        "payout": result["payout"],
        "sources": result["sources"],
        "steps": result["steps"],
        "step_count": result["step_count"],
        "tokens_used": result["tokens_used"],
        "cost_usd": result["cost_usd"],
        "latency_ms": result["latency_ms"],
        "stopped_reason": result["stopped_reason"],
        "finished": result["finished"],
        "passed": triage_scores(result["decision"], result["payout"], expected),
    }


def run_triage_claim(claim_id: str, agent: ClaimAgent, workflow: FixedClaimWorkflow, expected: dict) -> dict:

    return {
        "claim_id": claim_id,
        "dependent": expected.get("dependent", False),
        "expected": expected,
        "agent": _run_triage_system(agent.run, claim_id, expected),
        "workflow": _run_triage_system(workflow.run, claim_id, expected),
    }


def run_triage_suite(agent: ClaimAgent, workflow: FixedClaimWorkflow, only: list[str] | None, sleep: float) -> int:

    claim_ids = only if only else all_claim_ids()

    results = []

    for i, claim_id in enumerate(claim_ids):
        if i > 0 and sleep:
            print(f"(sleeping {sleep}s to stay under the rate limit)")
            time.sleep(sleep)

        expected = get_claim_record(claim_id)["expected"]
        dependent = get_claim_record(claim_id).get("dependent", False)
        expected = {**expected, "dependent": dependent}

        print(f"[{claim_id}]{' (dependent)' if dependent else ''} racing ...", end="", flush=True)
        started = time.perf_counter()
        result = run_triage_claim(claim_id, agent, workflow, expected)
        results.append(result)
        print(f" done ({time.perf_counter() - started:.1f}s) "
              f"agent={'PASS' if result['agent']['passed'] else 'FAIL'} "
              f"fixed={'PASS' if result['workflow']['passed'] else 'FAIL'}")

        TRIAGE_RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        TRIAGE_RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    if not results:
        print("No claims completed.")
        return 1

    n = len(results)
    agent_pass = sum(1 for r in results if r["agent"]["passed"])
    workflow_pass = sum(1 for r in results if r["workflow"]["passed"])
    agent_p50 = p50([r["agent"]["latency_ms"] for r in results])
    workflow_p50 = p50([r["workflow"]["latency_ms"] for r in results])
    agent_tokens = sum(r["agent"]["tokens_used"] for r in results)
    workflow_tokens = sum(r["workflow"]["tokens_used"] for r in results)
    agent_cost = sum(r["agent"]["cost_usd"] for r in results)
    workflow_cost = sum(r["workflow"]["cost_usd"] for r in results)

    print()
    print(f"{'system':<10}{'pass rate':>12}{'p50 ms':>10}{'tokens':>10}{'cost/claim':>12}")
    print("-" * 54)
    print(f"{'agent':<10}{f'{agent_pass}/{n}':>12}{agent_p50:>10}{agent_tokens:>10}{f'${agent_cost / n:.5f}':>12}")
    print(f"{'fixed':<10}{f'{workflow_pass}/{n}':>12}{workflow_p50:>10}{workflow_tokens:>10}{f'${workflow_cost / n:.5f}':>12}")
    print(f"\nSaved: {TRIAGE_RESULTS_PATH.relative_to(REPO_ROOT)}")

    TRIAGE_RACE_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TRIAGE_RACE_CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["system", "pass_rate", "p50_latency_ms", "total_tokens", "cost_per_claim_usd"])
        writer.writerow(["agent", f"{agent_pass}/{n}", agent_p50, agent_tokens, round(agent_cost / n, 6)])
        writer.writerow(["fixed_workflow", f"{workflow_pass}/{n}", workflow_p50, workflow_tokens, round(workflow_cost / n, 6)])
    print(f"Saved: {TRIAGE_RACE_CSV_PATH.relative_to(REPO_ROOT)}")

    return 0


# --------------------------------------------------------------------- main

def main() -> int:

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--suite", choices=["triage", "policy", "both"], default="triage")
    parser.add_argument("--only", nargs="+", default=None, help="restrict to these scenario/claim ids")
    parser.add_argument("--sleep", type=float, default=0.0, help="seconds to pause between runs, to stay under the Groq rate limit")
    args = parser.parse_args()

    retriever = RetrievalService()

    if retriever.vector_store.count() == 0:
        print("The index is empty. Run: python scripts/ingest.py")
        return 1

    agent = ClaimAgent(retriever=retriever)
    workflow = FixedClaimWorkflow(retriever=retriever)

    exit_code = 0

    if args.suite in ("triage", "both"):
        exit_code = run_triage_suite(agent, workflow, args.only, args.sleep) or exit_code

    if args.suite in ("policy", "both"):
        if args.suite == "both":
            print()
        exit_code = run_policy_suite(agent, workflow, args.only, args.sleep) or exit_code

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
