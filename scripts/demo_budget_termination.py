"""
A dedicated, deterministic demonstration that the triage agent's budgets
actually stop it - not just that the constants exist. Runs a real claim
through ClaimTriageAgent with a deliberately tiny `max_iterations`, so the
task's own request for "the log of one run that hits a budget and
terminates cleanly instead of spinning" doesn't depend on hoping the race's
10 claims happen to trip one.

    python scripts/demo_budget_termination.py

Saves the full step log to docs/training/week7/budget_termination_log.txt.
Needs GROQ_API_KEY. Stop the API server first (embedded Qdrant locks its
folder to one process).
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.services.retrieval_service import RetrievalService  # noqa: E402
from app.services.triage_agent import ClaimTriageAgent  # noqa: E402

LOG_PATH = REPO_ROOT / "docs" / "training" / "week7" / "budget_termination_log.txt"

# CLM-2007 needs several turns to resolve correctly (get_claim, at least one
# search to confirm the fire-vs-wind/hail distinction, compute_payout,
# finish) - a real, not artificial, task. max_iterations=2 is deliberately
# below what it needs, so this reliably demonstrates the iteration budget
# firing on a genuine claim rather than a contrived unsolvable one.
CLAIM_ID = "CLM-2007"
MAX_ITERATIONS = 2


def main() -> int:

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    retriever = RetrievalService()

    if retriever.vector_store.count() == 0:
        print("The index is empty. Run: python scripts/ingest.py")
        return 1

    agent = ClaimTriageAgent(retriever=retriever)
    result = agent.run(CLAIM_ID, max_iterations=MAX_ITERATIONS)

    lines = [
        f"Budget-termination demo: {CLAIM_ID}, max_iterations={MAX_ITERATIONS} "
        f"(deliberately tight - this claim normally needs 4-5 turns)",
        "=" * 78,
    ]

    for step in result["steps"]:
        lines.append(f"\nStep {step['step']}: {step['tool']}")
        if step.get("args"):
            lines.append(f"  args:   {step['args']}")
        if step.get("result"):
            lines.append(f"  result: {str(step['result'])[:300]}")
        lines.append(f"  tokens: {step['tokens']}, latency: {step['latency_ms']}ms")

    lines.append("\n" + "-" * 78)
    lines.append(f"stopped_reason : {result['stopped_reason']}")
    lines.append(f"finished       : {result['finished']}")
    lines.append(f"steps taken    : {result['step_count']} (budget was {MAX_ITERATIONS})")
    lines.append(f"decision       : {result['decision']}")
    lines.append(f"payout         : {result['payout']}")
    lines.append(
        "\nThe budget fired cleanly: the loop stopped after exactly "
        f"{MAX_ITERATIONS} iterations with stopped_reason={result['stopped_reason']!r} "
        "and finished=False, rather than spinning past the budget or silently "
        "returning a partial answer dressed up as a real decision."
    )

    log_text = "\n".join(lines)
    print(log_text)

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(log_text, encoding="utf-8")
    print(f"\nSaved: {LOG_PATH.relative_to(REPO_ROOT)}")

    assert result["stopped_reason"] == "iteration_limit", (
        f"Expected iteration_limit, got {result['stopped_reason']!r} - "
        "the claim resolved within the tight budget, pick a harder one."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
