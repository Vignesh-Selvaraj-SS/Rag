"""Unit tests for Week 11's claim-summary request log - all against fakes
and a tmp_path file, no live model calls."""

from app.services.claim_log_service import (
    ClaimLogService,
    build_claim_log_entry,
    classify_input_type,
)


def _outcome(**overrides) -> dict:
    base = {
        "summary": "CLAIM: CLM-2026-09001\nCOVERAGE: covered\n",
        "fields": {"CLAIM": "CLM-2026-09001", "COVERAGE": "covered"},
        "retrieved": [{"chunk_id": "c1", "source": "faq-policyholder-endorsements.md"}],
        "cited_chunk_ids": ["c1"],
        "spans": [
            {"name": "retrieval", "latency_ms": 20, "tokens": 0, "cost_usd": 0.0},
            {"name": "generation", "latency_ms": 900, "tokens": 1200, "cost_usd": 0.00024},
        ],
        "tokens_used": 1200,
        "cost_usd": 0.00024,
        "latency_ms": 920,
        "summary_prompt_version": "s2",
    }
    base.update(overrides)
    return base


# ------------------------------------------------------------- classify_input_type

def test_classify_input_type():

    assert classify_input_type("The claim was denied due to exclusion.") == "denial_review"
    assert classify_input_type("What deductible applies here?") == "deductible_only"
    assert classify_input_type("Is this water damage covered?") == "coverage_question"


# --------------------------------------------------------- build_claim_log_entry

def test_build_claim_log_entry_redacts_and_carries_through_fields():

    notes = "Claim CLM-2026-09001, insured Priya Raghavan reports a loss."
    entry = build_claim_log_entry(
        request_id="r_test123",
        notes=notes,
        claim_no="CLM-2026-09001",
        outcome=_outcome(),
        timestamp="2026-10-12T09:00:00+00:00",
    )

    assert entry["request_id"] == "r_test123"
    assert entry["claim_no"] == "[CLAIM_NO]"
    assert "CLM-2026-09001" not in entry["notes_redacted"]
    assert "Priya Raghavan" not in entry["notes_redacted"]
    assert entry["prompt_version"] == "s2"
    assert entry["retrieved_context_ids"] == ["c1"]
    assert entry["cited_chunk_ids"] == ["c1"]
    assert entry["spans"][1]["tokens"] == 1200
    assert entry["endorsements_topped_up"] == []
    assert entry["tokens_used"] == 1200
    assert entry["cost_usd"] == 0.00024
    assert entry["latency_ms"] == 920


def test_build_claim_log_entry_carries_endorsements_topped_up():

    entry = build_claim_log_entry(
        request_id="r_test456",
        notes="Endorsement HO-2026-01 is attached.",
        claim_no="CLM-2026-09001",
        outcome=_outcome(endorsements_topped_up=["HO-2026-01"]),
    )

    assert entry["endorsements_topped_up"] == ["HO-2026-01"]


# --------------------------------------------------------------- ClaimLogService

def test_record_and_get_round_trip(tmp_path):

    log = ClaimLogService(path=tmp_path / "claim_log.jsonl")

    request_id = log.record("Some adjuster notes.", "CLM-2026-09001", _outcome())
    assert request_id is not None

    fetched = log.get(request_id)
    assert fetched["request_id"] == request_id


def test_record_is_a_noop_when_disabled(tmp_path):

    log = ClaimLogService(path=tmp_path / "claim_log.jsonl", enabled=False)

    request_id = log.record("Some adjuster notes.", "CLM-2026-09001", _outcome())

    assert request_id is None
    assert log.load_all() == []


def test_by_prompt_version(tmp_path):

    log = ClaimLogService(path=tmp_path / "claim_log.jsonl")

    log.record("Notes A.", None, _outcome(summary_prompt_version="s1"))
    log.record("Notes B.", None, _outcome(summary_prompt_version="s2"))

    s1_entries = log.by_prompt_version("s1")
    assert len(s1_entries) == 1
    assert s1_entries[0]["prompt_version"] == "s1"


def test_by_input_type(tmp_path):

    log = ClaimLogService(path=tmp_path / "claim_log.jsonl")

    log.record("Was this claim denied?", None, _outcome())
    log.record("What deductible applies?", None, _outcome())

    denial_entries = log.by_input_type("denial_review")
    assert len(denial_entries) == 1

    deductible_entries = log.by_input_type("deductible_only")
    assert len(deductible_entries) == 1


def test_cost_outliers_sorts_descending(tmp_path):

    log = ClaimLogService(path=tmp_path / "claim_log.jsonl")

    log.record("Cheap one.", None, _outcome(cost_usd=0.0001))
    log.record("Expensive one.", None, _outcome(cost_usd=0.0009))
    log.record("Mid one.", None, _outcome(cost_usd=0.0005))

    outliers = log.cost_outliers(n=2)

    assert [entry["cost_usd"] for entry in outliers] == [0.0009, 0.0005]


def test_search_output_finds_by_answer_content_not_question():
    """
    The key fix this log exists for: a complaint describing what the system
    SAID ("it told the claimant something was covered") must be findable
    even though the question never used the word "covered".
    """

    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as tmp:
        log = ClaimLogService(path=Path(tmp) / "claim_log.jsonl")

        log.record(
            "Water seeped into the basement over three weeks.",
            None,
            _outcome(summary="CLAIM: CLM-2026-09001\nCOVERAGE: covered\n", fields={"COVERAGE": "covered"}),
        )
        log.record(
            "Fire damaged the kitchen last week.",
            None,
            _outcome(summary="CLAIM: CLM-2026-00001\nCOVERAGE: denied\n", fields={"COVERAGE": "denied"}),
        )

        hits = log.search_output("covered")

        assert len(hits) == 1
        assert "covered" in hits[0]["summary_redacted"].lower()


def test_by_time_filters_a_range(tmp_path):

    log = ClaimLogService(path=tmp_path / "claim_log.jsonl")

    log.record("Yesterday's claim.", None, _outcome(), timestamp="2026-10-12T09:00:00+00:00")
    log.record("Today's claim.", None, _outcome(), timestamp="2026-10-13T09:00:00+00:00")

    yesterday_only = log.by_time("2026-10-12T00:00:00+00:00", "2026-10-12T23:59:59+00:00")

    assert len(yesterday_only) == 1
    assert yesterday_only[0]["timestamp"] == "2026-10-12T09:00:00+00:00"
