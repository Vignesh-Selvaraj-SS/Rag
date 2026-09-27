"""
Unit tests for the trajectory scoring library, against hand-built fake
traces - proving the scoring logic itself is right before trusting it on
any real agent run.
"""

from app.services.trajectory_eval import (
    classify_failure_mode,
    evaluate_claim,
    score_argument_validity,
    score_step_efficiency,
    score_tool_choice,
    summarize,
    trajectory_pass,
)

EXPECTED_SIMPLE = {
    "expected_sequences": [["get_claim", "search_policy", "compute_payout", "finish"]],
    "steps_needed": 4,
    "must_include": ["search_policy", "compute_payout"],
}

EXPECTED_DEPENDENT = {
    "expected_sequences": [
        ["get_claim", "search_policy", "compute_payout", "finish"],
        ["get_claim", "search_policy", "search_policy", "compute_payout", "finish"],
    ],
    "steps_needed": 4,
    "must_include": ["search_policy", "compute_payout"],
}

REAL_SOURCES = {"endorsement-HO-2026-01-water-backup.md", "policy-base-HO3-2026.md"}


def _step(tool, args=None, result=None):
    return {"tool": tool, "args": args or {}, "result": result}


def _get_claim_step(claimed_amount=6000):
    return _step("get_claim", {"claim_id": "CLM-2001"}, {"result": {"claim_id": "CLM-2001", "claimed_amount": claimed_amount}})


def _clean_trace(extra_search=False, claimed_amount=6000, excess_amount=500, source=None):
    steps = [_get_claim_step(claimed_amount)]
    steps.append(_step("search_policy", {"query": "water backup deductible", "source": source}))
    if extra_search:
        steps.append(_step("search_policy", {"query": "sump pump conditions"}))
    steps.append(_step("compute_payout", {"claimed_amount": claimed_amount, "excess_amount": excess_amount, "claim_status": "approved"}))
    steps.append(_step("finish", {"decision": "approved", "payout": claimed_amount - excess_amount}))
    return {
        "steps": steps, "step_count": len(steps), "stopped_reason": "finished",
        "tokens_used": 5000, "cost_usd": 0.001,
    }


def test_score_tool_choice_matches_the_single_expected_sequence():

    trace = _clean_trace()

    assert score_tool_choice(trace, EXPECTED_SIMPLE) is True


def test_score_tool_choice_accepts_a_legitimate_second_search():

    trace = _clean_trace(extra_search=True)

    assert score_tool_choice(trace, EXPECTED_DEPENDENT) is True


def test_score_tool_choice_rejects_a_sequence_outside_the_accepted_set():

    # Three searches when only one or two are ever accepted.
    trace = _clean_trace(extra_search=True)
    trace["steps"].insert(2, _step("search_policy", {"query": "a third search"}))
    trace["step_count"] = len(trace["steps"])

    assert score_tool_choice(trace, EXPECTED_DEPENDENT) is False


def test_score_argument_validity_all_real():

    trace = _clean_trace(source="endorsement-HO-2026-01-water-backup.md")

    valid, checked, violations = score_argument_validity(trace, real_sources=REAL_SOURCES)

    assert violations == []
    assert valid == checked


def test_score_argument_validity_flags_a_fabricated_source_file():

    trace = _clean_trace(source="policy-HO-2026-01.md")  # not a real file name

    valid, checked, violations = score_argument_validity(trace, real_sources=REAL_SOURCES)

    assert valid < checked
    assert any("not a real file" in v for v in violations)


def test_score_argument_validity_flags_a_claimed_amount_that_does_not_match_get_claim():

    trace = _clean_trace(claimed_amount=6000)
    # compute_payout silently used a different number than get_claim returned
    trace["steps"][2]["args"]["claimed_amount"] = 9000

    valid, checked, violations = score_argument_validity(trace, real_sources=REAL_SOURCES)

    assert any("does not match get_claim" in v for v in violations)


def test_score_argument_validity_flags_an_invented_deductible():

    trace = _clean_trace(excess_amount=475)  # not one of the real deductible figures

    valid, checked, violations = score_argument_validity(trace, real_sources=REAL_SOURCES)

    assert any("not a known real deductible" in v for v in violations)


def test_score_step_efficiency():

    trace = _clean_trace()  # 4 steps

    assert score_step_efficiency(trace, steps_needed=4) == 1.0

    trace_with_extra = _clean_trace(extra_search=True)  # 5 steps

    assert score_step_efficiency(trace_with_extra, steps_needed=4) == 1.25


def test_classify_failure_mode_clean_trajectory_is_none():

    trace = _clean_trace(source="endorsement-HO-2026-01-water-backup.md")

    assert classify_failure_mode(trace, EXPECTED_SIMPLE) is None
    assert trajectory_pass(trace, EXPECTED_SIMPLE) is True


def test_classify_failure_mode_implicit_finish():

    # Live-observed, 4 of 10 claims in one real race: the model answered in
    # plain text instead of calling `finish` - decision/payout never get
    # set even though compute_payout ran correctly, and this silently
    # bypasses the compute_payout finish-gate (which only fires on a
    # structured finish tool call). Was previously mislabeled "wrong_order",
    # hiding how common and distinct this actually is.
    trace = _clean_trace()
    trace["steps"][-1] = _step("finish (implicit - no tool call made)", {})

    assert classify_failure_mode(trace, EXPECTED_SIMPLE) == "implicit_finish"
    assert trajectory_pass(trace, EXPECTED_SIMPLE) is False


def test_classify_failure_mode_skipped_exclusion_check():

    # The exact failure this week is about: right answer, no search_policy call at all.
    trace = {
        "steps": [
            _get_claim_step(),
            _step("compute_payout", {"claimed_amount": 6000, "excess_amount": 500, "claim_status": "approved"}),
            _step("finish", {"decision": "approved", "payout": 5500}),
        ],
        "step_count": 3, "stopped_reason": "finished", "tokens_used": 3000, "cost_usd": 0.0006,
    }

    assert classify_failure_mode(trace, EXPECTED_SIMPLE) == "skipped_exclusion_check"
    assert trajectory_pass(trace, EXPECTED_SIMPLE) is False


def test_classify_failure_mode_wrong_order_search_after_computing():

    trace = {
        "steps": [
            _get_claim_step(),
            _step("compute_payout", {"claimed_amount": 6000, "excess_amount": 500, "claim_status": "approved"}),
            _step("search_policy", {"query": "water backup deductible"}),
            _step("finish", {"decision": "approved", "payout": 5500}),
        ],
        "step_count": 4, "stopped_reason": "finished", "tokens_used": 4000, "cost_usd": 0.0008,
    }

    assert classify_failure_mode(trace, EXPECTED_SIMPLE) == "wrong_order"


def test_classify_failure_mode_skipped_required_tool_other_than_search():

    # Regression test: live-observed on CLM-2003/CLM-2004 - the model
    # finished normally (no budget/error stop) but never called
    # compute_payout at all, asserting the payout directly in finish. This
    # must NOT collapse into "unresolved" (reserved for a genuine budget or
    # hard-error stop) - it's a distinct, real failure of its own.
    trace = {
        "steps": [
            _get_claim_step(),
            _step("search_policy", {"query": "water backup deductible"}),
            _step("finish", {"decision": "approved", "payout": 5500}),
        ],
        "step_count": 3, "stopped_reason": "finished", "tokens_used": 3000, "cost_usd": 0.0006,
    }

    assert classify_failure_mode(trace, EXPECTED_SIMPLE) == "skipped_required_tool"


def test_classify_failure_mode_redundant_search():

    trace = _clean_trace(extra_search=True)
    trace["steps"].insert(2, _step("search_policy", {"query": "a third, unnecessary search"}))
    trace["step_count"] = len(trace["steps"])

    assert classify_failure_mode(trace, EXPECTED_DEPENDENT) == "redundant_search"


def test_classify_failure_mode_unresolved_when_not_finished():

    trace = _clean_trace()
    trace["stopped_reason"] = "iteration_limit"

    assert classify_failure_mode(trace, EXPECTED_SIMPLE) == "unresolved"


def test_classify_failure_mode_accepts_an_optional_settlement_authority_check():

    # Regression test: a live CLM-2001 run (post settlement-authority
    # description fix) legitimately called check_settlement_authority on a
    # $5,500 payout before compute_payout - a real, correct verification
    # step, not a sequencing mistake. Was mislabeled "wrong_order" before
    # trajectory_expected.json's CLM-2001 entry was broadened to accept it,
    # the same over-brittleness class as the earlier search-count fix.
    expected_with_authority_check = {
        "expected_sequences": [
            ["get_claim", "search_policy", "compute_payout", "finish"],
            ["get_claim", "search_policy", "search_policy", "compute_payout", "finish"],
            ["get_claim", "search_policy", "check_settlement_authority", "compute_payout", "finish"],
        ],
        "steps_needed": 4,
        "must_include": ["search_policy", "compute_payout"],
    }
    trace = _clean_trace()
    trace["steps"].insert(2, _step("check_settlement_authority", {"payout_amount": 5500}))
    trace["step_count"] = len(trace["steps"])

    assert classify_failure_mode(trace, expected_with_authority_check) is None


def test_evaluate_claim_flags_right_answer_wrong_path():

    # Outcome eval passed (decision/payout were correct, tracked externally),
    # but the trajectory skipped the exclusion check - the exact gap this
    # week is about.
    trace = {
        "steps": [
            _get_claim_step(),
            _step("compute_payout", {"claimed_amount": 6000, "excess_amount": 500, "claim_status": "approved"}),
            _step("finish", {"decision": "approved", "payout": 5500}),
        ],
        "step_count": 3, "stopped_reason": "finished", "tokens_used": 3000, "cost_usd": 0.0006,
    }

    evaluation = evaluate_claim("CLM-2001", trace, EXPECTED_SIMPLE, outcome_passed=True)

    assert evaluation["right_answer_wrong_path"] is True
    assert evaluation["failure_mode"] == "skipped_exclusion_check"
    assert evaluation["outcome_passed"] is True
    assert evaluation["trajectory_passed"] is False


def test_summarize_computes_the_gap_and_mode_counts():

    clean = evaluate_claim("CLM-2001", _clean_trace(source="endorsement-HO-2026-01-water-backup.md"), EXPECTED_SIMPLE, outcome_passed=True)

    skipped_trace = {
        "steps": [
            _get_claim_step(),
            _step("compute_payout", {"claimed_amount": 6000, "excess_amount": 500, "claim_status": "approved"}),
            _step("finish", {"decision": "approved", "payout": 5500}),
        ],
        "step_count": 3, "stopped_reason": "finished", "tokens_used": 3000, "cost_usd": 0.0006,
    }
    skipped = evaluate_claim("CLM-2002", skipped_trace, EXPECTED_SIMPLE, outcome_passed=True)

    summary = summarize([clean, skipped])

    assert summary["n"] == 2
    assert summary["outcome_pass_rate"] == 1.0
    assert summary["trajectory_pass_rate"] == 0.5
    assert summary["gap"] == 0.5
    assert summary["failure_mode_counts"] == {"skipped_exclusion_check": 1}
    assert summary["right_answer_wrong_path_claims"] == ["CLM-2002"]
    assert summary["cost_max"] == 0.001  # clean's cost_usd (0.001) is the higher of the two
    assert summary["cost_p50"] == 0.0006  # nearest-rank p50 of [0.0006, 0.001] picks the lower index
