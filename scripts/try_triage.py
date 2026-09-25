"""
Try the Task Set D triage agent (and/or the fixed workflow) on any claim ID
in evaluation/triage_claims.json - for manually watching the steps yourself,
not for the race.

    python scripts/try_triage.py CLM-2007
    python scripts/try_triage.py CLM-2007 --compare
    python scripts/try_triage.py CLM-2007 --workflow-only
    python scripts/try_triage.py            # lists the available claim ids

Stop the API server first: embedded Qdrant locks its folder to one process.
Needs GROQ_API_KEY.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.services.claims_data import all_claim_ids  # noqa: E402
from app.services.fixed_triage_workflow import FixedClaimTriageWorkflow  # noqa: E402
from app.services.retrieval_service import RetrievalService  # noqa: E402
from app.services.triage_agent import ClaimTriageAgent  # noqa: E402


def print_agent_result(result: dict) -> None:

    print(f"\n{'=' * 70}\nAGENT\n{'=' * 70}")

    for step in result["steps"]:
        print(f"\nStep {step['step']}: {step['tool']}")
        if step["thought"]:
            print(f"  thought: {step['thought'][:200]}")
        if step["args"]:
            print(f"  args:    {step['args']}")
        if step["result"]:
            print(f"  result:  {str(step['result'])[:300]}")

    print(f"\n{'-' * 70}")
    print(f"finished       : {result['finished']}")
    print(f"stopped_reason : {result['stopped_reason']}")
    print(f"steps taken    : {result['step_count']}")
    print(f"tokens used    : {result['tokens_used']}")
    print(f"cost           : ${result['cost_usd']:.5f}")
    print(f"latency        : {result['latency_ms']}ms")
    print(f"\nDECISION: {result['decision']}")
    print(f"PAYOUT:   {result['payout']}")
    print(f"REASONING: {result['reasoning']}")
    print(f"SOURCES:  {result['sources']}")


def print_workflow_result(result: dict) -> None:

    print(f"\n{'=' * 70}\nFIXED WORKFLOW\n{'=' * 70}")

    for step in result["steps"]:
        print(f"\nStep {step['step']}: {step['action']}")

    print(f"\n{'-' * 70}")
    print(f"finished       : {result['finished']}")
    print(f"stopped_reason : {result['stopped_reason']}")
    print(f"steps taken    : {result['step_count']}")
    print(f"tokens used    : {result['tokens_used']}")
    print(f"cost           : ${result['cost_usd']:.5f}")
    print(f"latency        : {result['latency_ms']}ms")
    print(f"\nDECISION: {result['decision']}")
    print(f"PAYOUT:   {result['payout']}")
    print(f"REASONING: {result['reasoning']}")
    print(f"SOURCES:  {result['sources']}")


def main() -> int:

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("claim_id", nargs="?", help="the claim id to try, e.g. CLM-2007 (or you'll be prompted)")
    parser.add_argument("--compare", action="store_true", help="run both the agent and the fixed workflow")
    parser.add_argument("--workflow-only", action="store_true", help="run only the fixed workflow, not the agent")
    parser.add_argument("--max-iterations", type=int, default=8)
    args = parser.parse_args()

    claim_id = (args.claim_id or "").strip()

    retriever = RetrievalService()

    if retriever.vector_store.count() == 0:
        print("The index is empty. Run: python scripts/ingest.py")
        return 1

    if not claim_id:
        print("Available claim ids:", ", ".join(all_claim_ids()))
        claim_id = input("Claim id: ").strip()

    if not claim_id:
        print("No claim id given.")
        return 1

    print(f"\nCLAIM: {claim_id}")

    if not args.workflow_only:
        agent = ClaimTriageAgent(retriever=retriever)
        print_agent_result(agent.run(claim_id, max_iterations=args.max_iterations))

    if args.compare or args.workflow_only:
        workflow = FixedClaimTriageWorkflow(retriever=retriever)
        print_workflow_result(workflow.run(claim_id))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
