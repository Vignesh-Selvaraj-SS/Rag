"""
Week 10 Task Set D: race the claims squad (manager + 2 specialists,
app/services/claims_squad_service.py) against the single agent
(SummaryService) on the same Week 6 M6 claim-summary cases, scored by the
same deterministic assertions and the same judge.

    python scripts/race_claims_squad.py
    python scripts/race_claims_squad.py --only S1 S2
    python scripts/race_claims_squad.py --sleep 10   # pace calls under the Groq rate limit

A thin CLI wrapper around app/services/squad_race_service.py - the same
class the UI's "Run race" button drives (app/api/squad.py), so the two
entry points can never silently diverge. Saves incrementally to
.runtime/claims_squad_race/results.json after every single case/arm, so a
partial run (quota, rate limit) is never lost - the next invocation
resumes rather than re-paying for completed cases.

Judge cost is deliberately excluded from each arm's tokens_used/cost_usd:
grading is a shared, one-time evaluation overhead applied identically to
both arms, not a per-request production cost either agent actually pays.

Stop the API server first: embedded Qdrant locks its folder to one process.
Needs GROQ_API_KEY.
"""

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.core.config import settings  # noqa: E402
from app.services.shared import (  # noqa: E402
    get_claims_squad_service,
    get_judge_service,
    get_rag_service,
    get_summary_service,
)
from app.services.squad_race_service import SquadRaceService  # noqa: E402

RESULTS_PATH = REPO_ROOT / ".runtime" / "claims_squad_race" / "results.json"


def print_report(status: dict) -> None:

    single_summary = status["single_summary"]
    squad_summary = status["squad_summary"]

    if not single_summary or not squad_summary:
        print("Not enough completed cases yet for a full report.")
        return

    n = min(single_summary["n"], squad_summary["n"])
    print(f"\n{'=' * 70}\nRACE TABLE ({n} cases completed per arm)\n{'=' * 70}")
    print(f"{'metric':<20}{'single agent':>18}{'claims squad':>18}")
    print("-" * 56)
    print(f"{'pass rate':<20}{single_summary['pass_rate']:>17.0%} {squad_summary['pass_rate']:>17.0%}")
    print(f"{'p50 latency ms':<20}{single_summary['p50_latency_ms']:>18.0f}{squad_summary['p50_latency_ms']:>18.0f}")
    print(f"{'p99 latency ms':<20}{single_summary['p99_latency_ms']:>18.0f}{squad_summary['p99_latency_ms']:>18.0f}")
    print(f"{'total tokens':<20}{single_summary['total_tokens']:>18}{squad_summary['total_tokens']:>18}")
    print(f"{'cost/claim $':<20}{single_summary['cost_per_claim_usd']:>18.5f}{squad_summary['cost_per_claim_usd']:>18.5f}")

    if status["context_resend_multiplier"] is not None:
        print(f"\nContext re-send multiplier (squad tokens / single tokens): {status['context_resend_multiplier']:.1f}x")

    if status["handoff_totals"]:
        grand_total = sum(status["handoff_totals"].values())
        print("\nHand-off token share (summed across all completed squad cases):")
        for key, total in sorted(status["handoff_totals"].items(), key=lambda kv: -kv[1]):
            print(f"  {key:<45}{total:>8} tok  ({total / grand_total:.0%})")


def main() -> int:

    parser = argparse.ArgumentParser()
    parser.add_argument("--only", nargs="+", help="restrict to these M6 case ids")
    parser.add_argument("--sleep", type=float, default=5.0, help="seconds to pause between calls")
    args = parser.parse_args()

    rag = get_rag_service()
    if rag.chunk_count() == 0:
        print("The index is empty. Run: python scripts/ingest.py")
        return 1

    service = SquadRaceService(
        results_path=RESULTS_PATH,
        rag_service=rag,
        summary_service=get_summary_service(),
        squad_service=get_claims_squad_service(),
        judge_service=get_judge_service(),
        eval_set_path=settings.eval_set_path,
        eval_runs_dir=settings.eval_runs_dir,
    )

    status = service.start(only=args.only, sleep=args.sleep)

    last_current = None
    while status["running"]:
        if status["current"] != last_current:
            last_current = status["current"]
            print(f"[{last_current}] ...", end="", flush=True)
        time.sleep(1.0)
        status = service.status()
        if status["current"] != last_current:
            print(" done")

    if status["error"]:
        print(f"\nRace stopped early: {status['error']}")

    print_report(status)
    print(f"\nSaved: {RESULTS_PATH.relative_to(REPO_ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
