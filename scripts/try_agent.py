"""
Try the merged agent (and/or the fixed workflow) on any input - a free-text
policy question, or a claim id from evaluation/triage_claims.json - for
manually watching the steps yourself, not for the race.

    python scripts/try_agent.py "What is the deductible for a water backup claim under HO-2026-01?"
    python scripts/try_agent.py CLM-2007 --compare
    python scripts/try_agent.py CLM-2007 --workflow-only
    python scripts/try_agent.py            # lists the available claim ids, then prompts

Stop the API server first: embedded Qdrant locks its folder to one process.
Needs GROQ_API_KEY.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.services.agent_service import ClaimAgent  # noqa: E402
from app.services.claims_data import all_claim_ids  # noqa: E402
from app.services.fixed_claim_workflow import FixedClaimWorkflow  # noqa: E402
from app.services.retrieval_service import RetrievalService  # noqa: E402


def print_result(label: str, result: dict) -> None:

    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")

    for step in result["steps"]:
        label_bits = step.get("tool") or step.get("action")
        print(f"\nStep {step['step']}: {label_bits}")
        if step.get("thought"):
            print(f"  thought: {step['thought'][:200]}")
        if step.get("args"):
            print(f"  args:    {step['args']}")
        if step.get("result"):
            print(f"  result:  {str(step['result'])[:300]}")

    print(f"\n{'-' * 70}")
    print(f"finished       : {result['finished']}")
    print(f"stopped_reason : {result['stopped_reason']}")
    print(f"steps taken    : {result['step_count']}")
    print(f"tokens used    : {result['tokens_used']}")
    print(f"latency        : {result['latency_ms']}ms")
    if result.get("decision") is not None:
        print(f"\nDECISION: {result['decision']}")
        print(f"PAYOUT:   {result['payout']}")
    print(f"\nANSWER: {result['answer']}")
    print(f"SOURCES: {result['sources']}")


def main() -> int:

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("user_input", nargs="*", help="a policy question, or a claim id (or you'll be prompted)")
    parser.add_argument("--compare", action="store_true", help="also run the fixed workflow")
    parser.add_argument("--workflow-only", action="store_true", help="run only the fixed workflow, not the agent")
    parser.add_argument("--max-iterations", type=int, default=8)
    args = parser.parse_args()

    user_input = " ".join(args.user_input).strip()

    retriever = RetrievalService()

    if retriever.vector_store.count() == 0:
        print("The index is empty. Run: python scripts/ingest.py")
        return 1

    if not user_input:
        print("Available claim ids:", ", ".join(all_claim_ids()))
        user_input = input("Question or claim id: ").strip()

    if not user_input:
        print("No input given.")
        return 1

    print(f"\nINPUT: {user_input}")

    if not args.workflow_only:
        agent = ClaimAgent(retriever=retriever)
        print_result("AGENT", agent.run(user_input, max_iterations=args.max_iterations))

    if args.compare or args.workflow_only:
        workflow = FixedClaimWorkflow(retriever=retriever)
        print_result("FIXED WORKFLOW", workflow.run(user_input))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
