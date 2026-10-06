"""
Unit tests for ClaimsSquadService (Week 10 Task Set D) - against a fake
Groq client and a fake RAG service, no live model calls. Proves the
three-hand-off structure, the token/cost accounting, and the output shape
match what eval_assertions.py and JudgeService expect (the same contract
SummaryService produces), before trusting any live race numbers built on
top of it.
"""

import pytest

from app.core.errors import LLMNotConfiguredError
from app.services.claims_squad_service import ClaimsSquadService

NOTES = (
    "Claim CLM-2026-02011, date of loss 2026-01-09. Sump pump failed during "
    "heavy rain in a finished basement built 2016, no battery backup or "
    "water alarm installed. Water backed up through the floor drain."
)


class _FakeUsage:
    def __init__(self, total_tokens):
        self.total_tokens = total_tokens


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content, tokens):
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage(tokens)


class _FakeCompletions:
    """Returns one scripted (text, tokens) pair per call, in order."""

    def __init__(self, scripted: list[tuple[str, int]]):
        self._queue = list(scripted)
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if not self._queue:
            raise AssertionError("fake Groq client ran out of scripted responses")
        content, tokens = self._queue.pop(0)
        return _FakeResponse(content, tokens)


class _FakeChat:
    def __init__(self, completions):
        self.completions = completions


class _FakeGroqClient:
    def __init__(self, scripted: list[tuple[str, int]]):
        self.chat = _FakeChat(_FakeCompletions(scripted))


class _FakeRagService:
    def search(self, question, top_k=None, mode="hybrid"):
        return {
            "hits": [
                {
                    "chunk_id": "endorsement-HO-2026-01-water-backup.md::1",
                    "source": "endorsement-HO-2026-01-water-backup.md",
                    "heading": "Conditions",
                    "page": "p.1",
                    "text": "Coverage applies only if the sump pump was in proper working order...",
                },
            ],
        }


FACTS_OUTPUT = (
    "CLAIM NUMBER: CLM-2026-02011\n"
    "DATE OF LOSS: 2026-01-09\n"
    "CAUSE OF LOSS: Sump pump failure during heavy rain\n"
    "CONDITIONS NOTED: Finished basement built 2016, no battery backup or water alarm\n"
    "AMOUNTS MENTIONED: none mentioned"
)

COVERAGE_OUTPUT = (
    "COVERAGE POSITION: partially covered\n"
    "APPLICABLE CLAUSE(S): HO-2026-01\n"
    "REASONING: Basement finished after 2020 would need a backup system, but this one was finished in 2016 [S1].\n"
    "DEDUCTIBLE: $500"
)

SYNTHESIS_OUTPUT = (
    "CLAIM: CLM-2026-02011\n"
    "DATE OF LOSS: 2026-01-09\n"
    "COVERAGE: partially covered\n"
    "BASIS: The 2016 basement predates the 2020 backup-system requirement, so full coverage applies under [S1].\n"
    "DEDUCTIBLE: $500\n"
    "NEXT ACTION: Confirm sump pump service records before issuing payment."
)


def _service(scripted):
    client = _FakeGroqClient(scripted)
    service = ClaimsSquadService(rag_service=_FakeRagService())
    service.client = client
    return service, client


def test_process_runs_three_handoffs_in_order():

    service, client = _service([(FACTS_OUTPUT, 300), (COVERAGE_OUTPUT, 500), (SYNTHESIS_OUTPUT, 400)])

    result = service.process(NOTES)

    assert [h["to"] for h in result["handoffs"]] == ["summary_worker", "coverage_worker", "manager"]
    assert result["handoffs"][0]["from"] == "manager"
    assert result["handoffs"][1]["from"] == "manager"
    assert result["handoffs"][2]["from"] == "summary_worker+coverage_worker"
    assert [h["tokens"] for h in result["handoffs"]] == [300, 500, 400]


def test_process_sums_tokens_and_computes_cost_the_same_way_as_summary_service():

    service, client = _service([(FACTS_OUTPUT, 300), (COVERAGE_OUTPUT, 500), (SYNTHESIS_OUTPUT, 400)])

    result = service.process(NOTES)

    assert result["tokens_used"] == 1200
    assert result["cost_usd"] == round(1200 / 1_000_000 * 0.20, 6)


def test_process_output_fields_match_the_summary_service_contract():

    service, client = _service([(FACTS_OUTPUT, 300), (COVERAGE_OUTPUT, 500), (SYNTHESIS_OUTPUT, 400)])

    result = service.process(NOTES)

    assert result["summary"] == SYNTHESIS_OUTPUT
    assert result["fields"]["CLAIM"] == "CLM-2026-02011"
    assert result["fields"]["COVERAGE"] == "partially covered"
    assert result["fields"]["DEDUCTIBLE"] == "$500"
    assert result["refused"] is False
    assert "retrieved" in result and "cited_chunk_ids" in result


def test_coverage_worker_receives_the_summary_workers_facts_and_the_retrieved_sources():

    service, client = _service([(FACTS_OUTPUT, 300), (COVERAGE_OUTPUT, 500), (SYNTHESIS_OUTPUT, 400)])

    service.process(NOTES)

    coverage_call_messages = client.chat.completions.calls[1]["messages"]
    user_content = coverage_call_messages[1]["content"]

    assert FACTS_OUTPUT in user_content
    assert "endorsement-HO-2026-01-water-backup.md" in user_content


def test_manager_synthesis_receives_both_workers_outputs_and_the_original_notes():

    service, client = _service([(FACTS_OUTPUT, 300), (COVERAGE_OUTPUT, 500), (SYNTHESIS_OUTPUT, 400)])

    service.process(NOTES)

    synth_call_messages = client.chat.completions.calls[2]["messages"]
    user_content = synth_call_messages[1]["content"]

    assert FACTS_OUTPUT in user_content
    assert COVERAGE_OUTPUT in user_content
    assert NOTES in user_content


def test_fail_coverage_worker_skips_that_call_and_marks_the_handoff_as_errored():

    # Week 10's injected failure: only 2 scripted responses needed, since
    # the coverage worker never actually gets called.
    service, client = _service([(FACTS_OUTPUT, 300), (SYNTHESIS_OUTPUT, 400)])

    result = service.process(NOTES, fail_coverage_worker=True)

    assert result["worker_error"] is not None
    assert "500" in result["worker_error"]
    assert result["handoffs"][1]["to"] == "coverage_worker"
    assert result["handoffs"][1]["tokens"] == 0
    assert "error" in result["handoffs"][1]
    assert len(client.chat.completions.calls) == 2


def test_fail_coverage_worker_tells_the_manager_the_worker_failed():

    service, client = _service([(FACTS_OUTPUT, 300), (SYNTHESIS_OUTPUT, 400)])

    service.process(NOTES, fail_coverage_worker=True)

    synth_call_messages = client.chat.completions.calls[1]["messages"]
    user_content = synth_call_messages[1]["content"]

    assert "WORKER FAILED" in user_content
    assert "500" in user_content


def test_raises_when_no_api_key_configured():

    service = ClaimsSquadService(rag_service=_FakeRagService())
    service.client = None

    with pytest.raises(LLMNotConfiguredError):
        service.process(NOTES)
