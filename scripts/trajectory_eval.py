"""
Week 8 Task Set D: score the agent's trajectory, not just its outcome.

Loads a race results file (default: the triage suite's saved results from
scripts/race.py --suite triage) plus evaluation/trajectory_expected.json,
and reports the four required trajectory numbers, the outcome-vs-trajectory
gap, the first right-answer-wrong-path claim found (with its full trace),
and a per-mode failure count table.

    python scripts/trajectory_eval.py
    python scripts/trajectory_eval.py --results .runtime/triage_race/results.json
    python scripts/trajectory_eval.py --compare-after .runtime/triage_race/results_after.json

No live calls - this only reads already-saved race data (see scripts/race.py
--suite triage, which is what produces that file).
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.services.trajectory_eval import evaluate_claim, summarize  # noqa: E402

DEFAULT_RESULTS_PATH = REPO_ROOT / ".runtime" / "triage_race" / "results.json"
EXPECTED_PATH = REPO_ROOT / "evaluation" / "trajectory_expected.json"


def load_expected() -> dict[str, dict]:
    records = json.loads(EXPECTED_PATH.read_text(encoding="utf-8"))
    return {record["claim_id"]: record for record in records}


def score_race_results(results_path: Path, expected_by_claim: dict[str, dict]) -> list[dict]:
    """
    Each entry in a race.py --suite triage results file already has a
    `passed` field (the outcome eval, computed by race.py's own
    triage_scores()) and an `agent` sub-dict shaped exactly like a raw
    ClaimAgent.run() trace - scored here for the trajectory.
    """

    race_results = json.loads(results_path.read_text(encoding="utf-8"))

    evaluations = []
    for entry in race_results:
        claim_id = entry["claim_id"]
        expected = expected_by_claim.get(claim_id)
        if expected is None:
            print(f"WARNING: no trajectory_expected.json entry for {claim_id!r} - skipped.")
            continue
        evaluations.append(evaluate_claim(claim_id, entry["agent"], expected, entry["agent"]["passed"]))

    return evaluations


def print_report(label: str, evaluations: list[dict]) -> dict:

    summary = summarize(evaluations)

    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")
    print(f"n claims               : {summary['n']}")
    print(f"tool-choice accuracy   : {summary['tool_choice_accuracy']:.0%}")
    print(f"argument validity rate : {summary['argument_validity_rate']:.0%}")
    print(f"mean step efficiency   : {summary['mean_step_efficiency']:.2f}")
    print(f"cost per claim, p50    : ${summary['cost_p50']:.5f}")
    print(f"cost per claim, max    : ${summary['cost_max']:.5f}")
    print(f"outcome pass rate      : {summary['outcome_pass_rate']:.0%}")
    print(f"trajectory pass rate   : {summary['trajectory_pass_rate']:.0%}")
    print(f"GAP (outcome - traj)   : {summary['gap']:+.0%}")

    print("\nPer-mode failure counts:")
    if summary["failure_mode_counts"]:
        for mode, count in sorted(summary["failure_mode_counts"].items(), key=lambda kv: -kv[1]):
            print(f"  {mode:<28} {count}")
    else:
        print("  (none - every claim had a clean trajectory)")

    if summary["right_answer_wrong_path_claims"]:
        print(f"\nRight-answer-wrong-path claims: {summary['right_answer_wrong_path_claims']}")
        example_id = summary["right_answer_wrong_path_claims"][0]
        example = next(e for e in evaluations if e["claim_id"] == example_id)
        print(f"\nTrace of {example_id} (outcome PASSED, trajectory FAILED, mode={example['failure_mode']}):")
        print(f"  tool sequence : {example['tool_sequence']}")
        print(f"  step efficiency: {example['step_efficiency']:.2f}")
        if example["argument_violations"]:
            print(f"  argument violations: {example['argument_violations']}")
    else:
        print("\nNo right-answer-wrong-path claims found in this run.")

    return summary


def print_regression(before: dict, after: dict) -> None:

    print(f"\n{'=' * 70}\nREGRESSION CHECK (per-mode counts, before -> after)\n{'=' * 70}")

    all_modes = set(before["failure_mode_counts"]) | set(after["failure_mode_counts"])
    if not all_modes:
        print("No failure modes appeared in either run.")
        return

    worsened = []
    appeared = []

    for mode in sorted(all_modes):
        b = before["failure_mode_counts"].get(mode, 0)
        a = after["failure_mode_counts"].get(mode, 0)
        flag = ""
        if a > b:
            flag = "  <-- WORSE"
            worsened.append(mode)
        elif b > 0 and mode not in after["failure_mode_counts"] and a == 0:
            flag = "  (fixed)"
        if mode not in before["failure_mode_counts"] and a > 0:
            flag = "  <-- NEW MODE"
            appeared.append(mode)
        print(f"  {mode:<28} {b} -> {a}{flag}")

    print()
    if worsened:
        print(f"Modes that got worse: {worsened}")
    if appeared:
        print(f"New modes the mitigation created: {appeared}")
    if not worsened and not appeared:
        print("No mode got worse and no new mode appeared.")

    top_mode_price = {
        "tokens_p50_before": before["cost_p50"], "tokens_p50_after": after["cost_p50"],
        "tokens_max_before": before["cost_max"], "tokens_max_after": after["cost_max"],
    }
    print(f"\nCost per claim, before -> after: p50 ${top_mode_price['tokens_p50_before']:.5f} -> ${top_mode_price['tokens_p50_after']:.5f}, "
          f"max ${top_mode_price['tokens_max_before']:.5f} -> ${top_mode_price['tokens_max_after']:.5f}")


def main() -> int:

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_PATH, help="race.py --suite triage results JSON to score")
    parser.add_argument("--compare-after", type=Path, default=None, help="a second results JSON (post-mitigation) to diff against --results")
    args = parser.parse_args()

    if not args.results.exists():
        print(f"No results file at {args.results} - run `python scripts/race.py --suite triage` first.")
        return 1

    expected_by_claim = load_expected()

    before_evaluations = score_race_results(args.results, expected_by_claim)
    before_summary = print_report("BEFORE", before_evaluations)

    if args.compare_after:
        if not args.compare_after.exists():
            print(f"\nNo --compare-after file at {args.compare_after}.")
            return 1
        after_evaluations = score_race_results(args.compare_after, expected_by_claim)
        after_summary = print_report("AFTER", after_evaluations)
        print_regression(before_summary, after_summary)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
