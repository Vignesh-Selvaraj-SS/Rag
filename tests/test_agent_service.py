"""
Unit tests for the Week 7 agent loop, the fixed workflow, and the tools -
all against fakes, no live model calls.

The fakes simulate Groq's native tool-calling response shape
(`message.tool_calls[].function.{name,arguments}`), not plain-text JSON -
that is what the real API actually returns, confirmed by a live call before
this design shipped (see agent_service.py's module docstring for why the
plain-text-JSON approach was tried first and rejected by the real API).
"""

import json

import pytest
from groq import GroqError

from app.core.errors import LLMNotConfiguredError, LLMUpstreamError
from app.services.agent_service import ClaimAgent
from app.services.agent_tools import list_documents, search_policy
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
    to simulate the two live-observed tool-call-corruption errors.
    """

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
    """Returns one hit for source.md, nothing for unknown sources."""

    def __init__(self):
        self.vector_store = _FakeVectorStore()
        self.calls: list[dict] = []

    def retrieve(self, question, top_k=None, min_score=None, source=None, mode="dense"):
        self.calls.append({"question": question, "top_k": top_k, "source": source, "mode": mode})
        if source == "missing.md":
            hits = []
        else:
            hits = [
                {
                    "chunk_id": "a.md::1", "text": "A $500 deductible applies.",
                    "source": "a.md", "heading": "Deductible", "page_start": 1, "page_end": 1,
                    "page": "p.1", "score": 0.8, "dense_score": 0.8,
                }
            ]
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
    assert result["result"][0]["source"] == "a.md"
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


# -------------------------------------------------------------- agent loop

def test_agent_finishes_after_one_search_for_a_simple_claim():

    client = _FakeGroqClient([
        tool_call_message("search_policy", {"query": "water backup deductible"}),
        tool_call_message("finish", {"answer": "The deductible is $500 [a.md].", "sources": ["a.md"]}),
    ])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("What is the deductible?")

    assert result["finished"] is True
    assert result["stopped_reason"] == "finished"
    assert result["step_count"] == 2
    assert result["answer"] == "The deductible is $500 [a.md]."
    assert result["steps"][0]["tool"] == "search_policy"
    assert result["steps"][1]["tool"] == "finish"


def test_agent_can_take_a_second_targeted_search_before_finishing():

    client = _FakeGroqClient([
        tool_call_message("list_documents"),
        tool_call_message("search_policy", {"query": "subrogation", "source": "a.md"}),
        tool_call_message("finish", {"answer": "Deductible $500, subrogation per a.md.", "sources": ["a.md"]}),
    ])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("Compound claim needing two lookups")

    assert result["step_count"] == 3
    assert [s["tool"] for s in result["steps"]] == ["list_documents", "search_policy", "finish"]


def test_agent_treats_a_plain_text_reply_as_an_implicit_finish():

    client = _FakeGroqClient([plain_text_message("The deductible is $500, no tool needed.")])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("What is the deductible?")

    assert result["finished"] is True
    assert result["answer"] == "The deductible is $500, no tool needed."
    assert "implicit" in result["steps"][0]["tool"]


def test_agent_stops_at_the_step_limit_without_crashing():

    # Never calls finish - always searches again.
    client = _FakeGroqClient([tool_call_message("search_policy", {"query": "x"})] * 10)

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("An unanswerable loop", max_steps=3)

    assert result["stopped_reason"] == "step_limit"
    assert result["finished"] is False
    assert result["step_count"] == 3


def test_agent_stops_at_the_token_budget():

    client = _FakeGroqClient([tool_call_message("search_policy", {"query": "x"})] * 10, tokens_each=400)

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("x", max_steps=10, max_tokens=900)

    assert result["stopped_reason"] == "token_limit"
    assert result["tokens_used"] < 10 * 400


def test_agent_handles_an_unknown_tool_name_as_a_logged_error_not_a_crash():

    client = _FakeGroqClient([
        tool_call_message("delete_everything", {}),
        tool_call_message("finish", {"answer": "Recovered.", "sources": []}),
    ])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("x")

    assert result["steps"][0]["result"]["error"].startswith("Unknown tool")
    assert result["finished"] is True


def test_agent_retries_after_a_malformed_tool_call_response():

    # Both errors observed live: a long `finish` answer that failed to
    # valid-JSON-encode, and a stray formatting token corrupting the tool
    # name itself ("finish<|channel|>commentary"). Both should be retried,
    # not fail the run.
    client = _FakeGroqClient([
        GroqError("Failed to parse tool call arguments as JSON"),
        GroqError("Tool call validation failed: attempted to call tool 'finish<|channel|>commentary'"),
        tool_call_message("finish", {"answer": "Recovered after two retries.", "sources": []}),
    ])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)
    result = agent.run("x")

    assert result["finished"] is True
    assert result["answer"] == "Recovered after two retries."


def test_agent_does_not_retry_an_unrelated_error():

    client = _FakeGroqClient([GroqError("internal server error")])

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)

    with pytest.raises(LLMUpstreamError):
        agent.run("x")

    assert len(client.chat.completions.calls) == 1  # no retry spent on a different kind of error


def test_agent_retries_after_a_rate_limit_error(monkeypatch):

    # Live-observed: Groq's free-tier tokens-per-minute limit can be hit mid-run.
    # Nothing is malformed, so this should wait and retry, not fail the run.
    waits = []
    monkeypatch.setattr("app.services.agent_service.time.sleep", lambda s: waits.append(s))

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

    monkeypatch.setattr("app.services.agent_service.time.sleep", lambda s: None)

    client = _FakeGroqClient([GroqError("rate limit exceeded")] * 5)  # RATE_LIMIT_RETRIES + 1

    agent = ClaimAgent(retriever=_FakeRetriever(), client=client)

    with pytest.raises(LLMUpstreamError):
        agent.run("x")

    assert len(client.chat.completions.calls) == 5


def test_agent_raises_when_no_api_key_configured():

    agent = ClaimAgent(retriever=_FakeRetriever(), client=None)

    with pytest.raises(LLMNotConfiguredError):
        agent.run("x")


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


# ---------------------------------------------------------------- workflow

def test_fixed_workflow_always_takes_exactly_two_steps():

    client = _FakeGroqClient([_FakeMessage(content="The deductible is $500, per the fixed retrieval.")])
    retriever = _FakeRetriever()

    workflow = FixedClaimWorkflow(retriever=retriever, client=client)
    result = workflow.run("Any claim at all")

    assert result["step_count"] == 2
    assert result["finished"] is True
    assert retriever.calls[0]["top_k"] == 8
    assert retriever.calls[0]["source"] is None


def test_fixed_workflow_raises_when_no_api_key_configured():

    workflow = FixedClaimWorkflow(retriever=_FakeRetriever(), client=None)

    with pytest.raises(LLMNotConfiguredError):
        workflow.run("x")
