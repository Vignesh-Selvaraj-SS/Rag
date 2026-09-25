"""
Unit tests for the Task Set D extension: the triage tools, the triage agent
loop (all four budgets), and the fixed triage workflow - all against fakes,
no live model calls.
"""

import json

import pytest
from groq import GroqError

from app.core.errors import LLMNotConfiguredError, LLMUpstreamError
from app.services.fixed_triage_workflow import FixedClaimTriageWorkflow
from app.services.triage_agent import ClaimTriageAgent
from app.services.triage_tools import (
    calculate_acv_depreciation,
    check_settlement_authority,
    check_subrogation_required,
    compute_payout,
    flag_for_review,
    get_claim,
    get_special_sublimit,
    validate_denial_letter,
)

# ------------------------------------------------------------------- fakes

class _FakeFunction:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _FakeToolCall:
    def __init__(self, call_id, name, arguments):
        self.id = call_id
        self.function = _FakeFunction(name, json.dumps(arguments))


class _FakeMessage:
    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeChoice:
    def __init__(self, message):
        self.message = message


class _FakeUsage:
    def __init__(self, total_tokens):
        self.total_tokens = total_tokens


class _FakeResponse:
    def __init__(self, message, tokens=50):
        self.choices = [_FakeChoice(message)]
        self.usage = _FakeUsage(tokens)


class _FakeCompletions:
    def __init__(self, scripted: list, tokens_each: int = 50):
        self._queue = list(scripted)
        self.tokens_each = tokens_each
        self.calls: list[list[dict]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs["messages"])
        if not self._queue:
            raise AssertionError("fake Groq client ran out of scripted responses")
        item = self._queue.pop(0)
        if isinstance(item, GroqError):
            raise item
        if isinstance(item, str):
            return _FakeResponse(_FakeMessage(content=item), self.tokens_each)
        return _FakeResponse(item, self.tokens_each)


class _FakeChat:
    def __init__(self, completions: _FakeCompletions):
        self.completions = completions


class _FakeGroqClient:
    def __init__(self, scripted: list, tokens_each: int = 50):
        self.chat = _FakeChat(_FakeCompletions(scripted, tokens_each))


class _FakeVectorStore:
    def count(self):
        return 5


class _FakeRetriever:
    def __init__(self):
        self.vector_store = _FakeVectorStore()
        self.calls: list[dict] = []

    def retrieve(self, question, top_k=None, min_score=None, source=None, mode="dense"):
        self.calls.append({"question": question, "top_k": top_k, "source": source, "mode": mode})
        hits = [{
            "chunk_id": "endorsement-HO-2026-01-water-backup.md::1",
            "text": "A separate deductible of $500 applies to each water backup occurrence.",
            "source": "endorsement-HO-2026-01-water-backup.md", "heading": "Deductible",
            "page_start": 1, "page_end": 1, "page": "p.1", "score": 0.8, "dense_score": 0.8,
        }]
        return {"question": question, "hits": hits, "best_score": 0.8, "passes_gate": True, "min_score": 0.6}


def tool_call_message(name, args=None, call_id="call_1"):
    return _FakeMessage(content="", tool_calls=[_FakeToolCall(call_id, name, args or {})])


# ------------------------------------------------------------------- tools

def test_get_claim_returns_the_case_file():

    result = get_claim({"claim_id": "CLM-2001"})

    assert "result" in result
    assert result["result"]["claim_id"] == "CLM-2001"
    assert "adjuster_notes" in result["result"]
    assert "expected" not in result["result"]  # the answer key never reaches the model


def test_get_claim_unknown_id_is_a_logged_error_not_a_crash():

    result = get_claim({"claim_id": "CLM-9999"})

    assert result["error"].startswith("No claim found")


def test_compute_payout_subtracts_the_excess_when_approved():

    result = compute_payout({"claimed_amount": 6000, "excess_amount": 500, "claim_status": "approved"})

    assert result["result"]["payout"] == 5500


def test_compute_payout_forces_zero_when_denied_even_with_nonzero_inputs():

    # A denied claim pays 0 regardless of what amounts are passed in - this
    # is the one job the tool has, not a general calculator.
    result = compute_payout({"claimed_amount": 9000, "excess_amount": 500, "claim_status": "denied"})

    assert result["result"]["payout"] == 0


def test_compute_payout_rejects_a_status_outside_the_enum():

    result = compute_payout({"claimed_amount": 100, "excess_amount": 0, "claim_status": "maybe"})

    assert "error" in result


def test_check_settlement_authority_picks_the_lowest_covering_grade():

    assert check_settlement_authority({"payout_amount": 8000})["result"]["required_grade"] == "desk_adjuster_grade_1"
    assert check_settlement_authority({"payout_amount": 80000})["result"]["required_grade"] == "senior_field_adjuster"
    assert check_settlement_authority({"payout_amount": 2_000_000})["result"]["required_grade"] == "head_of_claims"


def test_check_subrogation_required_on_amount_threshold():

    result = check_subrogation_required({"payout_amount": 6000, "cause_of_loss": "wear and tear"})

    assert result["result"]["subrogation_required"] is True


def test_check_subrogation_required_on_trigger_phrase_below_threshold():

    # Regression-shaped: a $2,000 loss still requires referral if a
    # contractor's excavation caused it - the trigger, not just the amount.
    result = check_subrogation_required({"payout_amount": 2000, "cause_of_loss": "contractor excavation nicked the line"})

    assert result["result"]["subrogation_required"] is True


def test_check_subrogation_not_required_below_threshold_with_no_trigger():

    result = check_subrogation_required({"payout_amount": 1000, "cause_of_loss": "accidental breakage"})

    assert result["result"]["subrogation_required"] is False


def test_calculate_acv_depreciation_caps_at_the_maximum():

    # 30 years on a 20-year-life composition shingle roof (5%/yr) would be
    # 150% uncapped - must clamp at the schedule's 80% maximum.
    result = calculate_acv_depreciation({"replacement_cost": 20000, "roof_material": "composition_shingle", "roof_age_years": 30})

    assert result["result"]["depreciation_pct"] == 0.80
    assert result["result"]["acv"] == 4000.0


def test_calculate_acv_depreciation_rejects_an_unknown_material():

    result = calculate_acv_depreciation({"replacement_cost": 1000, "roof_material": "thatch", "roof_age_years": 5})

    assert "error" in result


def test_get_special_sublimit_returns_the_base_form_ceiling():

    result = get_special_sublimit({"item_category": "jewelry_watches_furs_theft", "is_scheduled": False})

    assert result["result"]["sublimit"] == 2000


def test_get_special_sublimit_is_bypassed_once_scheduled():

    result = get_special_sublimit({"item_category": "jewelry_watches_furs_theft", "is_scheduled": True})

    assert result["result"]["sublimit"] is None


def test_validate_denial_letter_lists_missing_requirements():

    result = validate_denial_letter({"has_second_adjuster_review": True, "cites_specific_paragraph": False})

    assert result["result"]["ready_to_issue"] is False
    assert "cites_specific_paragraph" in result["result"]["missing_requirements"]
    assert "second_adjuster_review" not in result["result"]["missing_requirements"]


def test_validate_denial_letter_ready_when_all_five_present():

    result = validate_denial_letter({
        "has_second_adjuster_review": True, "cites_specific_paragraph": True,
        "has_plain_language_explanation": True, "has_appeal_route": True, "evidence_retained": True,
    })

    assert result["result"]["ready_to_issue"] is True
    assert result["result"]["missing_requirements"] == []


def test_flag_for_review_needs_both_fields():

    assert "error" in flag_for_review({"claim_id": "CLM-2001"})
    assert "error" in flag_for_review({"reason": "contradictory notes"})
    assert "result" in flag_for_review({"claim_id": "CLM-2001", "reason": "contradictory notes"})


# ------------------------------------------------------------------- agent

def test_triage_agent_happy_path_calls_all_three_tools_then_finishes():

    client = _FakeGroqClient([
        tool_call_message("get_claim", {"claim_id": "CLM-2001"}),
        tool_call_message("search_policy", {"query": "water backup deductible"}),
        tool_call_message("compute_payout", {"claimed_amount": 6000, "excess_amount": 500, "claim_status": "approved"}),
        tool_call_message("finish", {
            "decision": "approved", "payout": 5500,
            "reasoning": "Sewer backup covered under HO-2026-01, $500 deductible applies.",
            "sources": ["endorsement-HO-2026-01-water-backup.md"],
        }),
    ])

    agent = ClaimTriageAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("CLM-2001")

    assert result["finished"] is True
    assert result["decision"] == "approved"
    assert result["payout"] == 5500
    assert result["stopped_reason"] == "finished"
    assert [s["tool"] for s in result["steps"]] == ["get_claim", "search_policy", "compute_payout", "finish"]


def test_triage_agent_can_use_a_further_tool_before_finishing():

    client = _FakeGroqClient([
        tool_call_message("get_claim", {"claim_id": "CLM-2007"}),
        tool_call_message("search_policy", {"query": "fire roof replacement cost"}),
        tool_call_message("compute_payout", {"claimed_amount": 120000, "excess_amount": 1000, "claim_status": "approved"}),
        tool_call_message("check_settlement_authority", {"payout_amount": 119000}),
        tool_call_message("finish", {
            "decision": "approved", "payout": 119000,
            "reasoning": "Fire loss, replacement cost basis; requires senior field adjuster authority.",
            "sources": ["claims-adjuster-authority.md"],
        }),
    ])

    agent = ClaimTriageAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("CLM-2007")

    assert result["finished"] is True
    assert result["payout"] == 119000
    authority_step = next(s for s in result["steps"] if s["tool"] == "check_settlement_authority")
    assert authority_step["result"]["result"]["required_grade"] == "senior_field_adjuster"


def test_triage_agent_flag_for_review_ends_the_run_as_escalated_not_decided():

    client = _FakeGroqClient([
        tool_call_message("get_claim", {"claim_id": "CLM-2001"}),
        tool_call_message("flag_for_review", {"claim_id": "CLM-2001", "reason": "notes contradict the policy form on file"}),
    ])

    agent = ClaimTriageAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("CLM-2001")

    assert result["decision"] == "escalated"
    assert result["payout"] is None
    assert result["reasoning"] == "notes contradict the policy form on file"
    assert result["stopped_reason"] == "finished"


def test_triage_agent_enforces_the_iteration_limit():

    # Never calls finish - budget must stop it, not an infinite loop.
    client = _FakeGroqClient([tool_call_message("search_policy", {"query": "x"})] * 10)

    agent = ClaimTriageAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("CLM-2001", max_iterations=3)

    assert result["stopped_reason"] == "iteration_limit"
    assert result["finished"] is False
    assert result["step_count"] == 3


def test_triage_agent_enforces_the_token_limit():

    client = _FakeGroqClient([tool_call_message("search_policy", {"query": "x"})] * 10, tokens_each=400)

    agent = ClaimTriageAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("CLM-2001", max_iterations=10, max_tokens=900)

    assert result["stopped_reason"] == "token_limit"
    assert result["tokens_used"] < 10 * 400


def test_triage_agent_enforces_the_cost_limit():

    # 400 tokens/call at the assumed $0.20/1M rate is $0.00008/call - a
    # max_cost_usd of $0.00015 trips after the second call, well before the
    # iteration or token budgets would.
    client = _FakeGroqClient([tool_call_message("search_policy", {"query": "x"})] * 10, tokens_each=400)

    agent = ClaimTriageAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("CLM-2001", max_iterations=10, max_tokens=100000, max_cost_usd=0.00015)

    assert result["stopped_reason"] == "cost_limit"
    assert result["step_count"] < 10


def test_triage_agent_survives_repeated_output_parse_failures():

    # Regression test: a live run on CLM-2010 hit Groq's "output_parse_failed"
    # error (the model's own chain-of-thought leaking out unparsed instead of
    # a clean `finish` tool call) three times in a row - TOOL_PARSE_RETRIES=2
    # (2 retries, 3 attempts) wasn't enough and the run crashed. Raised to 4;
    # this checks recovery on the 4th attempt is actually reachable.
    client = _FakeGroqClient([
        GroqError("Parsing failed. The model generated output that could not be parsed."),
        GroqError("Parsing failed. The model generated output that could not be parsed."),
        GroqError("Parsing failed. The model generated output that could not be parsed."),
        tool_call_message("finish", {"decision": "approved", "payout": 8000, "sources": []}),
    ])

    agent = ClaimTriageAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("CLM-2010")

    assert result["finished"] is True
    assert result["payout"] == 8000


def test_triage_agent_enforces_the_wall_clock_budget():

    client = _FakeGroqClient([tool_call_message("search_policy", {"query": "x"})] * 10)

    agent = ClaimTriageAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("CLM-2001", max_iterations=10, max_seconds=0.0)

    assert result["stopped_reason"] == "time_limit"


def test_triage_agent_raises_when_no_api_key_configured():

    agent = ClaimTriageAgent(retriever=_FakeRetriever(), client=None)

    with pytest.raises(LLMNotConfiguredError):
        agent.run("CLM-2001")


def test_triage_agent_wraps_an_unrelated_groq_error():

    client = _FakeGroqClient([GroqError("internal server error")])

    agent = ClaimTriageAgent(retriever=_FakeRetriever(), client=client)

    with pytest.raises(LLMUpstreamError):
        agent.run("CLM-2001")


def test_triage_agent_attaches_steps_so_far_to_a_hard_failure():

    # Live bug, full-race run: a hard upstream failure (Groq's daily token
    # cap) hit mid-claim, and the caller had no way to see what the run had
    # already done - get_claim and one search had both already succeeded -
    # because that history was discarded on the way up as a bare exception.
    client = _FakeGroqClient([
        tool_call_message("get_claim", {"claim_id": "CLM-2001"}),
        GroqError("internal server error"),
    ])

    agent = ClaimTriageAgent(retriever=_FakeRetriever(), client=client)

    with pytest.raises(LLMUpstreamError) as excinfo:
        agent.run("CLM-2001")

    assert [s["tool"] for s in excinfo.value.steps] == ["get_claim"]
    assert excinfo.value.tokens_used == 50


# ------------------------------------------------------------------- workflow

def test_fixed_workflow_happy_path_runs_exactly_four_steps():

    decision_json = json.dumps({
        "claim_status": "approved", "excess_amount": 500,
        "reasoning": "Sewer backup covered under HO-2026-01.",
        "sources": ["endorsement-HO-2026-01-water-backup.md"],
    })
    client = _FakeGroqClient([decision_json])

    workflow = FixedClaimTriageWorkflow(retriever=_FakeRetriever(), client=client)
    result = workflow.run("CLM-2001")

    assert result["finished"] is True
    assert result["decision"] == "approved"
    assert result["payout"] == 5500  # 6000 - 500, computed by code, not the model
    assert result["step_count"] == 4
    assert len(client.chat.completions.calls) == 1  # exactly one generation call, no loop


def test_fixed_workflow_returns_an_error_result_on_unparseable_output():

    client = _FakeGroqClient(["not json at all"])

    workflow = FixedClaimTriageWorkflow(retriever=_FakeRetriever(), client=client)
    result = workflow.run("CLM-2001")

    assert result["finished"] is False
    assert result["stopped_reason"] == "error"


def test_fixed_workflow_returns_an_error_result_for_an_unknown_claim():

    client = _FakeGroqClient([])  # never reached - fails at step 1

    workflow = FixedClaimTriageWorkflow(retriever=_FakeRetriever(), client=client)
    result = workflow.run("CLM-9999")

    assert result["finished"] is False
    assert result["step_count"] == 1
