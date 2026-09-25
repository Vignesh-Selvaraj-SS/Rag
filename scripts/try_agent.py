"""
Try the Week 7 agent (and, optionally, the fixed workflow) on any claim you
type in - for manually watching the steps yourself, not for the race.

    python scripts/try_agent.py "What is the deductible for a water backup claim under HO-2026-01?"
    python scripts/try_agent.py --compare "A senior field adjuster wants to settle a $120,000 water backup claim under HO-2026-01. What deductible applies, and is that within the adjuster's settlement authority?"

Stop the API server first: embedded Qdrant locks its folder to one process.
Needs GROQ_API_KEY.
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.services.agent_service import ClaimAgent  # noqa: E402
from app.services.fixed_claim_workflow import FixedClaimWorkflow  # noqa: E402
from app.services.retrieval_service import RetrievalService  # noqa: E402


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
    print(f"latency        : {result['latency_ms']}ms")
    print(f"\nANSWER: {result['answer']}")
    print(f"SOURCES: {result['sources']}")


def print_workflow_result(result: dict) -> None:

    print(f"\n{'=' * 70}\nFIXED WORKFLOW\n{'=' * 70}")

    for step in result["steps"]:
        print(f"\nStep {step['step']}: {step['action']}")

    print(f"\n{'-' * 70}")
    print(f"steps taken    : {result['step_count']}")
    print(f"tokens used    : {result['tokens_used']}")
    print(f"latency        : {result['latency_ms']}ms")
    print(f"\nANSWER: {result['answer']}")
    print(f"SOURCES: {result['sources']}")


def main() -> int:

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("claim", nargs="*", help="the claim description to try (or you'll be prompted)")
    parser.add_argument("--compare", action="store_true", help="also run the fixed workflow on the same claim")
    parser.add_argument("--max-steps", type=int, default=6)
    args = parser.parse_args()

    claim = " ".join(args.claim).strip()

    if not claim:
        claim = input("Claim description: ").strip()

    if not claim:
        print("No claim given.")
        return 1

    retriever = RetrievalService()

    if retriever.vector_store.count() == 0:
        print("The index is empty. Run: python scripts/ingest.py")
        return 1

    print(f"\nCLAIM: {claim}")

    agent = ClaimAgent(retriever=retriever)
    print_agent_result(agent.run(claim, max_steps=args.max_steps))

    if args.compare:
        workflow = FixedClaimWorkflow(retriever=retriever)
        print_workflow_result(workflow.run(claim))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
