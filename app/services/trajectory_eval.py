"""
Trajectory scoring for the claims-triage agent: did it take a legitimate
path to its answer, not just reach the right number.

Operates on the raw trace dict `ClaimAgent.run()` produces when given a
claim id (or, when loaded from scripts/race.py's saved triage-suite results,
the `agent` sub-dict of one claim's race entry) - a dict with `steps` (each
`{tool, args, result, ...}`), `step_count`, `tokens_used`, `cost_usd`,
`stopped_reason`.

Four numbers, one classifier, one pass/fail:
  score_tool_choice        - did the actual tool sequence match one of the
                              claim's accepted sequences (a SET, not one
                              exact sequence - see evaluation/
                              trajectory_expected.json for which claims
                              legitimately accept more than one path).
  score_argument_validity   - were the numbers and file names the agent used
                              real, cross-checked against the actual corpus
                              and the claim's own earlier tool results, or
                              fluent fiction.
  score_step_efficiency     - steps taken / steps actually needed.
  classify_failure_mode     - names *why* a trajectory failed, so failures
                              can be counted per mode, not just totaled.
"""

from app.core.config import settings

KNOWN_DEDUCTIBLES = {0, 250, 500, 1000}

# Named failure modes, most specific first - classify_failure_mode returns
# the first one that applies, or None for a clean trajectory.
FAILURE_MODES = (
    "unresolved",           # hit a budget or a hard error before finishing
    "implicit_finish",      # answered in plain text instead of calling `finish`
    "skipped_exclusion_check",  # never called search_policy at all
    "skipped_required_tool",    # finished, but skipped a different required tool (e.g. compute_payout)
    "hallucinated_argument",    # a number or file name that isn't real
    "redundant_search",     # more search_policy calls than any accepted sequence uses
    "wrong_order",          # every required tool present, but not in an accepted order
)


def _real_source_names() -> set[str]:
    if not settings.DATA_DIR.exists():
        return set()
    return {
        path.name for path in settings.DATA_DIR.iterdir()
        if path.is_file() and not path.name.startswith(".")
    }


def score_tool_choice(trace: dict, expected: dict) -> bool:
    """Does the actual tool-name sequence match one of the accepted sequences (a set, not a single one)?"""

    actual = [step["tool"] for step in trace["steps"]]
    return actual in expected["expected_sequences"]


def score_argument_validity(trace: dict, real_sources: set[str] | None = None) -> tuple[int, int, list[str]]:
    """
    Checks every claim-specific number/file name the agent actually used
    against ground truth already visible in the same trace or the real
    corpus. Returns (valid_count, checked_count, violations).
    """

    if real_sources is None:
        real_sources = _real_source_names()

    valid = 0
    checked = 0
    violations: list[str] = []
    claimed_amount_from_get_claim = None

    for step in trace["steps"]:
        tool = step.get("tool")
        args = step.get("args") or {}

        if tool == "get_claim":
            result = (step.get("result") or {}).get("result") or {}
            claimed_amount_from_get_claim = result.get("claimed_amount")

        elif tool == "search_policy":
            source = args.get("source")
            if source:
                checked += 1
                if source in real_sources:
                    valid += 1
                else:
                    violations.append(f"search_policy source {source!r} is not a real file in the corpus")

        elif tool == "compute_payout":
            checked += 1
            claimed = args.get("claimed_amount")
            if claimed_amount_from_get_claim is not None and claimed == claimed_amount_from_get_claim:
                valid += 1
            else:
                violations.append(
                    f"compute_payout claimed_amount {claimed!r} does not match get_claim's {claimed_amount_from_get_claim!r}"
                )

            checked += 1
            excess = args.get("excess_amount")
            if excess in KNOWN_DEDUCTIBLES:
                valid += 1
            else:
                violations.append(f"compute_payout excess_amount {excess!r} is not a known real deductible figure")

    return valid, checked, violations


def score_step_efficiency(trace: dict, steps_needed: int) -> float:
    """steps taken / steps actually needed - 1.0 is perfectly efficient, above 1.0 means wasted steps."""

    return trace["step_count"] / steps_needed


def classify_failure_mode(trace: dict, expected: dict) -> str | None:
    """The first failure mode that applies, or None for a clean trajectory."""

    if trace.get("stopped_reason") != "finished":
        return "unresolved"

    tools_used = [step["tool"] for step in trace["steps"]]

    # Live-observed, 4 of 10 claims in one real race: the model answers in
    # plain text instead of calling `finish` (ClaimAgent.run's "implicit
    # finish" fallback). stopped_reason is still "finished" and every
    # required tool may well have been called, but decision/payout never
    # get set - a materially different, and far more common, problem than a
    # generic sequencing mistake, and it silently bypasses the compute_payout
    # gate (that gate only fires on a structured `finish` tool call).
    if tools_used and tools_used[-1].startswith("finish (implicit"):
        return "implicit_finish"

    for required in expected.get("must_include", []):
        if required not in tools_used:
            # search_policy missing is the specific failure this week's problem
            # statement is about (reached a payout without ever opening the
            # exclusions); any other missing required tool is a real, distinct
            # failure too (live-observed: CLM-2003/CLM-2004 both finished
            # having skipped compute_payout entirely, asserting the payout
            # without the auditable arithmetic step) - it must not collapse
            # into "unresolved", which is reserved for a budget/hard-error
            # stop, a materially different situation from a clean finish that
            # merely skipped a step.
            if required == "search_policy":
                return "skipped_exclusion_check"
            return "skipped_required_tool"

    _, _, violations = score_argument_validity(trace)
    if violations:
        return "hallucinated_argument"

    if tools_used not in expected["expected_sequences"]:
        max_accepted_searches = max(seq.count("search_policy") for seq in expected["expected_sequences"])
        if tools_used.count("search_policy") > max_accepted_searches:
            return "redundant_search"
        return "wrong_order"

    return None


def trajectory_pass(trace: dict, expected: dict) -> bool:
    return classify_failure_mode(trace, expected) is None


def evaluate_claim(claim_id: str, trace: dict, expected: dict, outcome_passed: bool) -> dict:
    """One claim's full trajectory scorecard."""

    valid, checked, violations = score_argument_validity(trace)
    failure_mode = classify_failure_mode(trace, expected)
    trajectory_passed = failure_mode is None

    return {
        "claim_id": claim_id,
        "tool_choice_ok": score_tool_choice(trace, expected),
        "argument_valid": valid,
        "argument_checked": checked,
        "argument_violations": violations,
        "step_efficiency": score_step_efficiency(trace, expected["steps_needed"]),
        "failure_mode": failure_mode,
        "trajectory_passed": trajectory_passed,
        "outcome_passed": outcome_passed,
        "right_answer_wrong_path": outcome_passed and not trajectory_passed,
        "tokens_used": trace["tokens_used"],
        "cost_usd": trace["cost_usd"],
        "tool_sequence": [step["tool"] for step in trace["steps"]],
    }


def _percentile(sorted_values: list[float], pct: int) -> float:

    if not sorted_values:
        return 0.0
    index = max(0, min(len(sorted_values) - 1, round(pct / 100 * (len(sorted_values) - 1))))
    return sorted_values[index]


def summarize(evaluations: list[dict]) -> dict:
    """The results table: the four required numbers, the gap, and per-mode counts."""

    n = len(evaluations)
    if n == 0:
        return {
            "n": 0, "tool_choice_accuracy": 0.0, "argument_validity_rate": 0.0,
            "mean_step_efficiency": 0.0, "cost_p50": 0.0, "cost_max": 0.0,
            "outcome_pass_rate": 0.0, "trajectory_pass_rate": 0.0, "gap": 0.0,
            "failure_mode_counts": {}, "right_answer_wrong_path_claims": [],
        }

    total_valid = sum(e["argument_valid"] for e in evaluations)
    total_checked = sum(e["argument_checked"] for e in evaluations)
    costs = sorted(e["cost_usd"] for e in evaluations)

    mode_counts: dict[str, int] = {}
    for e in evaluations:
        if e["failure_mode"]:
            mode_counts[e["failure_mode"]] = mode_counts.get(e["failure_mode"], 0) + 1

    outcome_pass_rate = sum(e["outcome_passed"] for e in evaluations) / n
    trajectory_pass_rate = sum(e["trajectory_passed"] for e in evaluations) / n

    return {
        "n": n,
        "tool_choice_accuracy": sum(e["tool_choice_ok"] for e in evaluations) / n,
        "argument_validity_rate": (total_valid / total_checked) if total_checked else 1.0,
        "mean_step_efficiency": sum(e["step_efficiency"] for e in evaluations) / n,
        "cost_p50": _percentile(costs, 50),
        "cost_max": max(costs),
        "outcome_pass_rate": outcome_pass_rate,
        "trajectory_pass_rate": trajectory_pass_rate,
        "gap": outcome_pass_rate - trajectory_pass_rate,
        "failure_mode_counts": mode_counts,
        "right_answer_wrong_path_claims": [e["claim_id"] for e in evaluations if e["right_answer_wrong_path"]],
    }
