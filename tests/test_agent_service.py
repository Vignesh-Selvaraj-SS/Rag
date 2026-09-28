"""
Unit tests for the merged claim agent (ClaimAgent, one class handling both
free-text policy questions and claim-ID triage), its tools, and its fixed
workflow - all against fakes, no live model calls.

The fakes simulate Groq's native tool-calling response shape
(`message.tool_calls[].function.{name,arguments}`), not plain-text JSON -
that is what the real API actually returns, confirmed by a live call before
this design shipped (see agent_service.py's module docstring).
"""

import json

import pytest
from groq import GroqError

from app.core.errors import LLMNotConfiguredError, LLMUpstreamError
from app.services.agent_service import ClaimAgent
from app.services.agent_tools import (
    TOOL_SCHEMAS,
    check_settlement_authority,
    compute_payout,
    flag_for_review,
    get_claim,
    list_documents,
    search_policy,
)
from app.services.fixed_claim_workflow import FixedClaimWorkflow

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
    """
    Returns one scripted response per call, in order. An entry may be a
    GroqError instance instead of a message - raised instead of returned,
    to simulate the live-observed tool-call-corruption/rate-limit errors.
    A plain string is treated as plain-text model content.
    """

    def __init__(self, scripted: list, tokens_each: int = 50):
        self._queue = list(scripted)
        self.tokens_each = tokens_each
        self.calls: list[list[dict]] = []
        self.tools_sent: list[list[dict]] = []

    def create(self, **kwargs):
        self.calls.append(kwargs["messages"])
        self.tools_sent.append(kwargs.get("tools"))
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
    """Returns one water-backup hit; nothing for source='missing.md'."""

    def __init__(self):
        self.vector_store = _FakeVectorStore()
        self.calls: list[dict] = []

    def retrieve(self, question, top_k=None, min_score=None, source=None, mode="dense"):
        self.calls.append({"question": question, "top_k": top_k, "source": source, "mode": mode})
        if source == "missing.md":
            hits = []
        else:
            hits = [{
                "chunk_id": "endorsement-HO-2026-01-water-backup.md::1",
                "text": "A separate deductible of $500 applies to each water backup occurrence.",
                "source": "endorsement-HO-2026-01-water-backup.md", "heading": "Deductible",
                "page_start": 1, "page_end": 1, "page": "p.1", "score": 0.8, "dense_score": 0.8,
            }]
        best = hits[0]["dense_score"] if hits else 0.0
        return {"question": question, "hits": hits, "best_score": best, "passes_gate": bool(hits), "min_score": 0.6}


def tool_call_message(name, args=None, call_id="call_1"):
    """A model turn that calls exactly one tool - the normal case."""
    return _FakeMessage(content="", tool_calls=[_FakeToolCall(call_id, name, args or {})])


def plain_text_message(text):
    """A model turn that answers directly with no tool call."""
    return _FakeMessage(content=text, tool_calls=[])


# ------------------------------------------------------------------- tools

def test_search_policy_returns_snippets():

    result = search_policy(_FakeRetriever(), {"query": "deductible"})

    assert "result" in result
    assert result["result"][0]["source"] == "endorsement-HO-2026-01-water-backup.md"
    assert "500" in result["result"][0]["text"]


def test_search_policy_does_not_truncate_a_chunk_before_its_table_data():

    # Regression test: a live run against the real corpus found SNIPPET_CHARS=320
    # cut off claims-adjuster-authority.md's settlement-authority table right
    # before the dollar figures - the agent could see the heading existed but
    # never the numbers, and wasted its whole step budget re-searching for a
    # fact the snippet had already discarded. This chunk shape (a short intro
    # sentence, then a markdown table) is real, not synthetic.
    class _RetrieverWithLongChunk(_FakeRetriever):
        def retrieve(self, question, top_k=None, min_score=None, source=None, mode="dense"):
            long_text = (
                "No adjuster may settle above their authority. Authority applies to the "
                "total incurred on the claim, not to a single payment.\n\n"
                "| Role | Settlement authority | Reserve authority |\n"
                "| Senior field adjuster | $150,000 | $200,000 |\n"
            )
            hits = [{
                "chunk_id": "x::1", "text": long_text, "source": "claims-adjuster-authority.md",
                "heading": "1. Settlement authority limits", "page_start": 1, "page_end": 1,
                "page": "p.1", "score": 0.8, "dense_score": 0.8,
            }]
            return {"question": question, "hits": hits, "best_score": 0.8, "passes_gate": True, "min_score": 0.6}

    result = search_policy(_RetrieverWithLongChunk(), {"query": "settlement authority"})

    assert "$150,000" in result["result"][0]["text"]


def test_search_policy_rejects_empty_query():

    result = search_policy(_FakeRetriever(), {"query": "  "})

    assert "error" in result


def test_search_policy_reports_no_hits_cleanly():

    result = search_policy(_FakeRetriever(), {"query": "x", "source": "missing.md"})

    assert "No chunks found" in result["result"]


def test_search_policy_schema_does_not_invite_settlement_authority_checks():

    # Regression test: found live - search_policy's own description used to
    # cite "settlement authority" as an example reason to search policy
    # text, contradicting the existence of check_settlement_authority. The
    # model followed that description literally: given CLM-2001 (a $5,500
    # payout needing no authority check at all), it searched policy text for
    # "settlement authority payout 5500" instead of using the dedicated
    # tool - a wasted step that helped exhaust the token budget before the
    # run could reach `finish`.
    schema = next(s for s in TOOL_SCHEMAS if s["function"]["name"] == "search_policy")
    description = schema["function"]["description"].lower()

    assert "settlement authority" not in description or "never use this to check" in description
    assert "check_settlement_authority" in description


def test_search_policy_resolves_a_guessed_endorsement_code_to_the_real_file_name():

    # Regression test: found live running the Task Set D triage extension -
    # the model reliably guesses source="HO-2026-01" (the endorsement code
    # it already knows) rather than the real file name, and an exact-match
    # filter then returns zero hits, burning a step on a search that should
    # have worked.
    retriever = _FakeRetriever()

    search_policy(retriever, {"query": "x", "source": "HO-2026-01"})

    assert retriever.calls[0]["source"] == "endorsement-HO-2026-01-water-backup.md"


def test_list_documents_lists_supported_files_and_skips_hidden_ones(tmp_path, monkeypatch):

    (tmp_path / "policy.md").write_text("x", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / "image.png").write_text("x", encoding="utf-8")
    (tmp_path / ".~lock.policy.md#").write_text("x", encoding="utf-8")

    monkeypatch.setattr("app.core.config.settings.DATA_DIR", tmp_path)

    result = list_documents({})

    assert result["result"] == ["notes.txt", "policy.md"]


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

    result = compute_payout({"claimed_amount": 9000, "excess_amount": 500, "claim_status": "denied"})

    assert result["result"]["payout"] == 0


def test_compute_payout_rejects_a_status_outside_the_enum():

    result = compute_payout({"claimed_amount": 100, "excess_amount": 0, "claim_status": "maybe"})

    assert "error" in result


def test_check_settlement_authority_picks_the_lowest_covering_grade():

    assert check_settlement_authority({"payout_amount": 8000})["result"]["required_grade"] == "desk_adjuster_grade_1"
    assert check_settlement_authority({"payout_amount": 80000})["result"]["required_grade"] == "senior_field_adjuster"
    assert check_settlement_authority({"payout_amount": 2_000_000})["result"]["required_grade"] == "head_of_claims"


def test_flag_for_review_needs_both_fields():

    assert "error" in flag_for_review({"claim_id": "CLM-2001"})
    assert "error" in flag_for_review({"reason": "contradictory notes"})
    assert "result" in flag_for_review({"claim_id": "CLM-2001", "reason": "contradictory notes"})


# -------------------------------------------------------------- tool scoping

def test_agent_sends_only_question_tools_for_a_policy_question():

    # Regression test: the merged agent used to send all 11 tool schemas
    # plus both jobs' system-prompt rules on every call, roughly doubling
    # the per-call cost of either original agent - a live run on CLM-2001
    # burned 17,204 tokens across 5 steps and never reached `finish`.
    client = _FakeGroqClient([
        tool_call_message("finish", {"answer": "done", "sources": []}),
    ])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    agent.run("What is the deductible for a water backup claim?")

    sent_names = {schema["function"]["name"] for schema in client.chat.completions.tools_sent[0]}
    assert sent_names == {"search_policy", "list_documents", "finish"}


def test_agent_sends_only_triage_tools_for_a_claim_id():

    client = _FakeGroqClient([
        tool_call_message("compute_payout", {"claimed_amount": 6000, "excess_amount": 500, "claim_status": "approved"}),
        tool_call_message("finish", {"answer": "done", "decision": "approved", "payout": 5500, "sources": []}),
    ])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    agent.run("CLM-2001")

    sent_names = {schema["function"]["name"] for schema in client.chat.completions.tools_sent[0]}
    assert "get_claim" in sent_names
    assert "compute_payout" in sent_names
    assert "list_documents" not in sent_names  # not a triage tool - shouldn't be sent


# ------------------------------------------------------- agent: policy question

def test_agent_finishes_after_one_search_for_a_simple_question():

    client = _FakeGroqClient([
        tool_call_message("search_policy", {"query": "water backup deductible"}),
        tool_call_message("finish", {"answer": "The deductible is $500.", "sources": ["endorsement-HO-2026-01-water-backup.md"]}),
    ])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("What is the deductible for a water backup claim?")

    assert result["finished"] is True
    assert result["stopped_reason"] == "finished"
    assert result["step_count"] == 2
    assert result["answer"] == "The deductible is $500."
    assert result["decision"] is None  # a policy question never gets a coverage decision
    assert result["payout"] is None
    assert result["steps"][0]["tool"] == "search_policy"
    assert result["steps"][1]["tool"] == "finish"


def test_agent_can_use_list_documents_before_a_targeted_search():

    client = _FakeGroqClient([
        tool_call_message("list_documents"),
        tool_call_message("search_policy", {"query": "subrogation", "source": "endorsement-HO-2026-01-water-backup.md"}),
        tool_call_message("finish", {"answer": "Deductible $500, subrogation per the endorsement.", "sources": []}),
    ])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("Compound question needing two lookups")

    assert result["step_count"] == 3
    assert [s["tool"] for s in result["steps"]] == ["list_documents", "search_policy", "finish"]


def test_agent_treats_a_plain_text_reply_as_an_implicit_finish():

    client = _FakeGroqClient([plain_text_message("The deductible is $500, no tool needed.")])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("What is the deductible?")

    assert result["finished"] is True
    assert result["answer"] == "The deductible is $500, no tool needed."
    assert "implicit" in result["steps"][0]["tool"]


def test_agent_only_acts_on_the_first_tool_call_when_the_model_offers_several():

    two_calls_message = _FakeMessage(content="", tool_calls=[
        _FakeToolCall("call_1", "search_policy", {"query": "a"}),
        _FakeToolCall("call_2", "list_documents", {}),
    ])
    client = _FakeGroqClient([
        two_calls_message,
        tool_call_message("finish", {"answer": "done", "sources": []}),
    ])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("x")

    assert result["steps"][0]["tool"] == "search_policy"
    assert result["step_count"] == 2


def test_agent_handles_an_unknown_tool_name_as_a_logged_error_not_a_crash():

    client = _FakeGroqClient([
        tool_call_message("delete_everything", {}),
        tool_call_message("finish", {"answer": "Recovered.", "sources": []}),
    ])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("x")

    assert result["steps"][0]["result"]["error"].startswith("Unknown tool")
    assert result["finished"] is True


def test_agent_raises_when_no_api_key_configured():

    agent = ClaimAgent(retriever=_FakeRetriever(), client=None)

    with pytest.raises(LLMNotConfiguredError):
        agent.run("x")


# --------------------------------------------------------------- agent: triage

def test_agent_triages_a_claim_calling_get_claim_search_and_compute_payout():

    client = _FakeGroqClient([
        tool_call_message("get_claim", {"claim_id": "CLM-2001"}),
        tool_call_message("search_policy", {"query": "water backup deductible"}),
        tool_call_message("compute_payout", {"claimed_amount": 6000, "excess_amount": 500, "claim_status": "approved"}),
        tool_call_message("finish", {
            "answer": "Sewer backup covered under HO-2026-01, $500 deductible applies.",
            "decision": "approved", "payout": 5500,
            "sources": ["endorsement-HO-2026-01-water-backup.md"],
        }),
    ])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("CLM-2001")

    assert result["finished"] is True
    assert result["decision"] == "approved"
    assert result["payout"] == 5500
    assert result["stopped_reason"] == "finished"
    assert [s["tool"] for s in result["steps"]] == ["get_claim", "search_policy", "compute_payout", "finish"]


def test_agent_can_use_a_further_triage_tool_before_finishing():

    client = _FakeGroqClient([
        tool_call_message("get_claim", {"claim_id": "CLM-2007"}),
        tool_call_message("search_policy", {"query": "fire roof replacement cost"}),
        tool_call_message("compute_payout", {"claimed_amount": 120000, "excess_amount": 1000, "claim_status": "approved"}),
        tool_call_message("check_settlement_authority", {"payout_amount": 119000}),
        tool_call_message("finish", {
            "answer": "Fire loss, replacement cost basis; requires senior field adjuster authority.",
            "decision": "approved", "payout": 119000,
            "sources": ["claims-adjuster-authority.md"],
        }),
    ])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("CLM-2007")

    assert result["finished"] is True
    assert result["payout"] == 119000
    authority_step = next(s for s in result["steps"] if s["tool"] == "check_settlement_authority")
    assert authority_step["result"]["result"]["required_grade"] == "senior_field_adjuster"


def test_agent_rejects_a_finish_call_that_skips_compute_payout():

    # Week 8 mitigation for the "skipped_required_tool" failure mode -
    # live-observed on CLM-2003/CLM-2004: the model finished a triage claim
    # (decision + payout both set) having never called compute_payout at
    # all, asserting the payout instead of computing it. finish is now
    # rejected exactly like a bad tool call, and the loop must continue
    # rather than accept an incomplete trajectory as done.
    client = _FakeGroqClient([
        tool_call_message("get_claim", {"claim_id": "CLM-2003"}),
        tool_call_message("search_policy", {"query": "warranty exclusion"}),
        tool_call_message("finish", {"answer": "Denied.", "decision": "denied", "payout": 0, "sources": []}),
        tool_call_message("compute_payout", {"claimed_amount": 4200, "excess_amount": 0, "claim_status": "denied"}),
        tool_call_message("finish", {"answer": "Denied.", "decision": "denied", "payout": 0, "sources": []}),
    ])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("CLM-2003")

    assert result["finished"] is True
    assert result["decision"] == "denied"
    assert result["payout"] == 0
    rejected_step = next(s for s in result["steps"] if "rejected" in s["tool"])
    assert rejected_step is not None
    assert [s["tool"] for s in result["steps"]][-1] == "finish"


def test_finish_rejection_message_forbids_extra_tool_calls_before_retrying():

    # Regression test: a live CLM-2001 run showed the model correctly
    # calling compute_payout after a rejection, but then redundantly
    # re-calling check_settlement_authority (identical args/result to an
    # earlier step) instead of retrying finish - wasting a step and helping
    # exhaust the token budget. The rejection message is refined (not a
    # second mitigation - the same gate's wording) to explicitly say not to
    # call any other tool in between.
    client = _FakeGroqClient([
        tool_call_message("get_claim", {"claim_id": "CLM-2003"}),
        tool_call_message("finish", {"answer": "Denied.", "decision": "denied", "payout": 0, "sources": []}),
        tool_call_message("compute_payout", {"claimed_amount": 4200, "excess_amount": 0, "claim_status": "denied"}),
        tool_call_message("finish", {"answer": "Denied.", "decision": "denied", "payout": 0, "sources": []}),
    ])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    agent.run("CLM-2003")

    last_call_messages = client.chat.completions.calls[-1]
    rejection_messages = [
        m["content"] for m in last_call_messages
        if m.get("role") == "tool" and "error" in m.get("content", "")
    ]
    assert any("do not call any other tool" in m.lower() for m in rejection_messages)


def test_agent_flag_for_review_ends_the_run_as_escalated_not_decided():

    client = _FakeGroqClient([
        tool_call_message("get_claim", {"claim_id": "CLM-2001"}),
        tool_call_message("flag_for_review", {"claim_id": "CLM-2001", "reason": "notes contradict the policy form on file"}),
    ])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("CLM-2001")

    assert result["decision"] == "escalated"
    assert result["payout"] is None
    assert "notes contradict the policy form on file" in result["answer"]
    assert result["stopped_reason"] == "finished"


# ------------------------------------------------------------------ 4 budgets

def test_default_max_tokens_covers_a_full_six_step_triage_run():

    # Regression test: two live CLM-2001 runs (14,539 and 14,204 tokens)
    # both hit the old 14000 default on a legitimate, non-redundant 5-step
    # trajectory - one call short of `finish`. Guards against silently
    # dropping the budget back below what a real 6-step run needs.
    from app.services.agent_service import DEFAULT_MAX_TOKENS

    assert DEFAULT_MAX_TOKENS >= 16000


def test_agent_enforces_the_iteration_limit():

    client = _FakeGroqClient([tool_call_message("search_policy", {"query": "x"})] * 10)

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("x", max_iterations=3)

    assert result["stopped_reason"] == "iteration_limit"
    assert result["finished"] is False
    assert result["step_count"] == 3


def test_agent_enforces_the_token_limit():

    client = _FakeGroqClient([tool_call_message("search_policy", {"query": "x"})] * 10, tokens_each=400)

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("x", max_iterations=10, max_tokens=900)

    assert result["stopped_reason"] == "token_limit"
    assert result["tokens_used"] < 10 * 400


def test_agent_enforces_the_cost_limit():

    # 400 tokens/call at the assumed $0.20/1M rate is $0.00008/call - a
    # max_cost_usd of $0.00015 trips after the second call, well before the
    # iteration or token budgets would.
    client = _FakeGroqClient([tool_call_message("search_policy", {"query": "x"})] * 10, tokens_each=400)

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("x", max_iterations=10, max_tokens=100000, max_cost_usd=0.00015)

    assert result["stopped_reason"] == "cost_limit"
    assert result["step_count"] < 10


def test_agent_enforces_the_wall_clock_budget():

    client = _FakeGroqClient([tool_call_message("search_policy", {"query": "x"})] * 10)

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("x", max_iterations=10, max_seconds=0.0)

    assert result["stopped_reason"] == "time_limit"


# ---------------------------------------------------------------------- retry

def test_agent_retries_after_a_malformed_tool_call_response():

    # Both errors observed live: a long `finish` answer that failed to
    # valid-JSON-encode, and a stray formatting token corrupting the tool
    # name itself ("finish<|channel|>commentary"). Both should be retried.
    client = _FakeGroqClient([
        GroqError("Failed to parse tool call arguments as JSON"),
        GroqError("Tool call validation failed: attempted to call tool 'finish<|channel|>commentary'"),
        tool_call_message("finish", {"answer": "Recovered after two retries.", "sources": []}),
    ])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("x")

    assert result["finished"] is True
    assert result["answer"] == "Recovered after two retries."


def test_agent_survives_repeated_output_parse_failures():

    # Regression test: a live run hit Groq's "output_parse_failed" error
    # (the model's own chain-of-thought leaking out unparsed instead of a
    # clean `finish` tool call) three times in a row - the shared retry
    # helper's TOOL_PARSE_RETRIES=4 gives room to recover on the 4th retry.
    client = _FakeGroqClient([
        GroqError("Parsing failed. The model generated output that could not be parsed."),
        GroqError("Parsing failed. The model generated output that could not be parsed."),
        GroqError("Parsing failed. The model generated output that could not be parsed."),
        tool_call_message("compute_payout", {"claimed_amount": 8000, "excess_amount": 0, "claim_status": "approved"}),
        tool_call_message("finish", {"answer": "Recovered.", "decision": "approved", "payout": 8000, "sources": []}),
    ])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("CLM-2010")

    assert result["finished"] is True
    assert result["payout"] == 8000


def test_agent_does_not_retry_an_unrelated_error():

    client = _FakeGroqClient([GroqError("internal server error")])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)

    with pytest.raises(LLMUpstreamError):
        agent.run("x")

    assert len(client.chat.completions.calls) == 1  # no retry spent on a different kind of error


def test_agent_retries_after_a_rate_limit_error(monkeypatch):

    # Live-observed: Groq's tokens-per-minute/day limits can be hit mid-run.
    # Nothing is malformed, so this should wait and retry, not fail the run.
    # The shared retry helper lives in groq_retry.py, not agent_service.py -
    # patch the actual call site.
    waits = []
    monkeypatch.setattr("app.services.groq_retry.time.sleep", lambda s: waits.append(s))

    client = _FakeGroqClient([
        GroqError("Rate limit reached for model. Please try again in 2.3775s."),
        tool_call_message("finish", {"answer": "Recovered after a rate limit wait.", "sources": []}),
    ])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("x")

    assert result["finished"] is True
    assert result["answer"] == "Recovered after a rate limit wait."
    assert waits == [15]  # RATE_LIMIT_WAIT_S * (attempt 0 + 1)


def test_agent_gives_up_after_exhausting_rate_limit_retries(monkeypatch):

    monkeypatch.setattr("app.services.groq_retry.time.sleep", lambda s: None)

    client = _FakeGroqClient([GroqError("rate limit exceeded")] * 5)  # RATE_LIMIT_RETRIES + 1

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)

    with pytest.raises(LLMUpstreamError):
        agent.run("x")

    assert len(client.chat.completions.calls) == 5


def test_agent_attaches_steps_so_far_to_a_hard_failure():

    # Live bug, full-race run: a hard upstream failure (Groq's daily token
    # cap) hit mid-claim, and the caller had no way to see what the run had
    # already done, because that history was discarded on the way up as a
    # bare exception.
    client = _FakeGroqClient([
        tool_call_message("get_claim", {"claim_id": "CLM-2001"}),
        GroqError("internal server error"),
    ])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)

    with pytest.raises(LLMUpstreamError) as excinfo:
        agent.run("CLM-2001")

    assert [s["tool"] for s in excinfo.value.steps] == ["get_claim"]
    assert excinfo.value.tokens_used == 50


# ---------------------------------------------------------------- workflow

def test_fixed_workflow_answers_a_question_in_exactly_two_steps():

    client = _FakeGroqClient(["The deductible is $500, per the fixed retrieval."])
    retriever = _FakeRetriever()

    workflow = FixedClaimWorkflow(retriever=retriever, client=client)
    result = workflow.run("What is the deductible for water backup?")

    assert result["step_count"] == 2
    assert result["finished"] is True
    assert result["decision"] is None
    assert result["payout"] is None
    assert retriever.calls[0]["top_k"] == 8
    assert retriever.calls[0]["source"] is None


def test_fixed_workflow_triages_a_claim_id_in_exactly_four_steps():

    decision_json = json.dumps({
        "claim_status": "approved", "excess_amount": 500,
        "reasoning": "Sewer backup covered under HO-2026-01.",
        "sources": ["endorsement-HO-2026-01-water-backup.md"],
    })
    client = _FakeGroqClient([decision_json])

    workflow = FixedClaimWorkflow(retriever=_FakeRetriever(), client=client)
    result = workflow.run("CLM-2001")

    assert result["finished"] is True
    assert result["decision"] == "approved"
    assert result["payout"] == 5500  # 6000 - 500, computed by code, not the model
    assert result["step_count"] == 4
    assert len(client.chat.completions.calls) == 1  # exactly one generation call, no loop


def test_fixed_workflow_routes_by_input_shape_not_content():

    # A claim ID (however it's cased) triggers the triage branch; anything
    # else, even something claim-adjacent, gets the question branch.
    client = _FakeGroqClient(["An answer."])
    workflow = FixedClaimWorkflow(retriever=_FakeRetriever(), client=client)

    result = workflow.run("what is CLM-2001 about?")  # not itself a bare claim id

    assert result["step_count"] == 2  # question branch, not triage


def test_fixed_workflow_returns_an_error_result_on_unparseable_output():

    client = _FakeGroqClient(["not json at all"])

    workflow = FixedClaimWorkflow(retriever=_FakeRetriever(), client=client)
    result = workflow.run("CLM-2001")

    assert result["finished"] is False
    assert result["stopped_reason"] == "error"


def test_fixed_workflow_returns_an_error_result_for_an_unknown_claim():

    client = _FakeGroqClient([])  # never reached - fails at step 1

    workflow = FixedClaimWorkflow(retriever=_FakeRetriever(), client=client)
    result = workflow.run("CLM-9999")

    assert result["finished"] is False
    assert result["step_count"] == 1


def test_fixed_workflow_raises_when_no_api_key_configured():

    workflow = FixedClaimWorkflow(retriever=_FakeRetriever(), client=None)

    with pytest.raises(LLMNotConfiguredError):
        workflow.run("x")
