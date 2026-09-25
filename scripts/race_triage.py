"""
Race ClaimTriageAgent (hand-built agent loop, 3 tools) against
FixedClaimTriageWorkflow (hardcoded 4-step sequence, same 3 tools) over the
same 10 claims, and report the four numbers the task requires for each
system: pass rate, p50 latency, total tokens, cost per claim.

    python scripts/race_triage.py
    python scripts/race_triage.py --only CLM-2002 CLM-2003
    python scripts/race_triage.py --sleep 20   # pace calls under the Groq TPM limit

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
from app.services.claims_data import all_claim_ids, get_claim_record  # noqa: E402
from app.services.fixed_triage_workflow import FixedClaimTriageWorkflow  # noqa: E402
from app.services.retrieval_service import RetrievalService  # noqa: E402
from app.services.triage_agent import ClaimTriageAgent  # noqa: E402

RESULTS_JSON_PATH = REPO_ROOT / ".runtime" / "triage_race" / "results.json"
RACE_CSV_PATH = REPO_ROOT / "docs" / "training" / "week7" / "race.csv"

# A payout within a dollar of the expected figure still passes - guards only
# against float rounding from the arithmetic itself, not against the
# system getting the wrong deductible or decision.
PAYOUT_TOLERANCE = 1.0


def scores(decision: str | None, payout, expected: dict) -> bool:

    if decision is None or payout is None:
        return False

    if decision.lower() != expected["decision"]:
        return False

    return abs(float(payout) - float(expected["payout"])) <= PAYOUT_TOLERANCE


def _run_system(run_fn, claim_id: str, expected: dict) -> dict:
    """
    Runs one system on one claim, isolating a hard upstream failure (e.g. the
    Groq account's daily token cap, hit live partway through a 10-claim race)
    to this one system/claim cell instead of losing the whole race. A caught
    failure is scored as a fail, not silently dropped from the totals.
    """

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
        "passed": scores(result["decision"], result["payout"], expected),
    }


def run_claim(claim_id: str, agent: ClaimTriageAgent, workflow: FixedClaimTriageWorkflow, expected: dict) -> dict:

    return {
        "claim_id": claim_id,
        "dependent": expected.get("dependent", False),
        "expected": expected,
        "agent": _run_system(agent.run, claim_id, expected),
        "workflow": _run_system(workflow.run, claim_id, expected),
    }


def p50(values: list[int]) -> int:
    return int(statistics.median(values)) if values else 0


def main() -> int:

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="+", default=None, help="restrict to these claim ids")
    parser.add_argument("--sleep", type=float, default=0.0, help="seconds to pause between claims, to stay under the Groq tokens-per-minute limit")
    args = parser.parse_args()

    claim_ids = args.only if args.only else all_claim_ids()

    retriever = RetrievalService()

    if retriever.vector_store.count() == 0:
        print("The index is empty. Run: python scripts/ingest.py")
        return 1

    agent = ClaimTriageAgent(retriever=retriever)
    workflow = FixedClaimTriageWorkflow(retriever=retriever)

    results = []

    for i, claim_id in enumerate(claim_ids):
        if i > 0 and args.sleep:
            print(f"(sleeping {args.sleep}s to stay under the rate limit)")
            time.sleep(args.sleep)

        expected = get_claim_record(claim_id)["expected"]
        dependent = get_claim_record(claim_id).get("dependent", False)
        expected = {**expected, "dependent": dependent}

        print(f"[{claim_id}]{' (dependent)' if dependent else ''} racing ...", end="", flush=True)
        started = time.perf_counter()
        result = run_claim(claim_id, agent, workflow, expected)
        results.append(result)
        print(f" done ({time.perf_counter() - started:.1f}s) "
              f"agent={'PASS' if result['agent']['passed'] else 'FAIL'} "
              f"fixed={'PASS' if result['workflow']['passed'] else 'FAIL'}")

        # Saved after every claim, not just at the end - a hard upstream
        # failure (Groq's daily token cap, live-observed mid-race) no longer
        # loses every claim run before it.
        RESULTS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        RESULTS_JSON_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

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

    print(f"\nSaved: {RESULTS_JSON_PATH.relative_to(REPO_ROOT)}")

    RACE_CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
    with RACE_CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["system", "pass_rate", "p50_latency_ms", "total_tokens", "cost_per_claim_usd"])
        writer.writerow(["agent", f"{agent_pass}/{n}", agent_p50, agent_tokens, round(agent_cost / n, 6)])
        writer.writerow(["fixed_workflow", f"{workflow_pass}/{n}", workflow_p50, workflow_tokens, round(workflow_cost / n, 6)])
    print(f"Saved: {RACE_CSV_PATH.relative_to(REPO_ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
