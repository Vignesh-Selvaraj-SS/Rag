"""Unit tests for the Week 6 evaluation machinery: citations, assertions, and
the eval_service orchestration - all against fakes, no live model calls."""

from app.services import eval_assertions
from app.services.citations import has_citation, parse_citations
from app.services.eval_service import EvalService, compare
from app.services.summary_service import parse_summary_fields


# --------------------------------------------------------------- citations

def test_citation_parser_resolves_ascii_tags():

    cited, invalid = parse_citations("A fact [S1]. Another [S2][S9].", source_count=3)

    assert cited == [1, 2]
    assert invalid == ["[S9]"]


def test_citation_parser_also_resolves_the_full_width_shape_the_model_actually_uses():

    # v1 (ASCII-only) undercounted citations: the Week 6 baseline measured
    # openai/gpt-oss-20b reliably citing with full-width brackets, and v1
    # recorded those answers as uncited in production, not just in a
    # historical trace. v2 (the shipped fix) resolves both shapes the same way.
    cited, invalid = parse_citations("The deductible is $500【S1】. Also 【S9】.", source_count=3)

    assert cited == [1]
    assert invalid == ["【S9】"]
    assert has_citation("The deductible is $500【S1】.") is True
    assert has_citation("The deductible is $500, no citation here.") is False


# -------------------------------------------------------------- summary parse

def test_parse_summary_fields_reads_the_rigid_six_line_form():

    summary = (
        "CLAIM: CLM-2026-00417\n"
        "DATE OF LOSS: 2026-03-14\n"
        "COVERAGE: covered\n"
        "BASIS: Water backup is covered per [S1].\n"
        "DEDUCTIBLE: $500\n"
        "NEXT ACTION: Issue payment per the endorsement.\n"
    )

    fields = parse_summary_fields(summary)

    assert fields["CLAIM"] == "CLM-2026-00417"
    assert fields["DATE OF LOSS"] == "2026-03-14"
    assert fields["DEDUCTIBLE"] == "$500"
    assert "[S1]" in fields["BASIS"]


def test_parse_summary_fields_missing_a_line_reports_none_not_a_crash():

    fields = parse_summary_fields("CLAIM: CLM-2026-00417\nCOVERAGE: covered\n")

    assert fields["CLAIM"] == "CLM-2026-00417"
    assert fields["DATE OF LOSS"] is None
    assert fields["DEDUCTIBLE"] is None


# -------------------------------------------------------------------- A1-A4

def _summary_result(text: str, retrieved=None) -> dict:
    return {
        "summary": text,
        "answer": text,
        "fields": parse_summary_fields(text),
        "retrieved": retrieved or [],
        "refused": False,
        "cited_chunk_ids": [],
        "invalid_citations": [],
    }


def test_a1_claim_number_must_match_the_case():

    case = {"claim_no": "CLM-2026-00417"}

    ok = eval_assertions.claim_number_echoed(case, _summary_result("CLAIM: CLM-2026-00417\n"))
    assert ok["status"] == "pass"

    wrong = eval_assertions.claim_number_echoed(case, _summary_result("CLAIM: CLM-2026-99999\n"))
    assert wrong["status"] == "fail"

    missing = eval_assertions.claim_number_echoed(case, _summary_result("no claim line here\n"))
    assert missing["status"] == "fail"


def test_a2_date_of_loss_must_parse_and_match():

    case = {"date_of_loss": "2026-03-14"}

    ok = eval_assertions.date_of_loss_parseable(case, _summary_result("DATE OF LOSS: 2026-03-14\n"))
    assert ok["status"] == "pass"

    alt_format = eval_assertions.date_of_loss_parseable(case, _summary_result("DATE OF LOSS: March 14, 2026\n"))
    assert alt_format["status"] == "pass"

    wrong = eval_assertions.date_of_loss_parseable(case, _summary_result("DATE OF LOSS: 2026-04-01\n"))
    assert wrong["status"] == "fail"


def test_a3_deductible_must_be_a_number_but_no_deductible_and_unsettled_both_pass():

    case = {"deductible": "$500"}

    numeric = eval_assertions.deductible_is_numeric(case, _summary_result("DEDUCTIBLE: $500\n"))
    assert numeric["status"] == "pass"

    prose = eval_assertions.deductible_is_numeric(case, _summary_result("DEDUCTIBLE: whatever applies\n"))
    assert prose["status"] == "fail"

    no_ded_case = {"deductible": None}
    no_deductible = eval_assertions.deductible_is_numeric(
        no_ded_case, _summary_result("DEDUCTIBLE: no deductible applies\n")
    )
    assert no_deductible["status"] == "pass"

    unsettled = eval_assertions.deductible_is_numeric(
        no_ded_case, _summary_result("DEDUCTIBLE: not established in the policy sources\n")
    )
    assert unsettled["status"] == "pass"

    mismatched = eval_assertions.deductible_is_numeric(case, _summary_result("DEDUCTIBLE: $250\n"))
    assert mismatched["status"] == "fail"


def test_a4_denial_requires_a_clause_id():

    denies_without_clause = eval_assertions.denial_cites_clause(
        {}, _summary_result("COVERAGE: denied\nBASIS: This is excluded.\n")
    )
    assert denies_without_clause["status"] == "fail"

    denies_with_clause = eval_assertions.denial_cites_clause(
        {}, _summary_result("COVERAGE: denied\nBASIS: Excluded under HO-2026-08 territory restriction.\n")
    )
    assert denies_with_clause["status"] == "pass"

    no_denial = eval_assertions.denial_cites_clause({}, _summary_result("COVERAGE: covered\n"))
    assert no_denial["status"] == "skip"


# -------------------------------------------------------------------- A5-A8

def test_a5_regression_check_fails_only_when_an_answerable_question_is_refused():

    answered = eval_assertions.did_not_refuse({"must_answer": True}, {"refused": False})
    assert answered["status"] == "pass"

    refused = eval_assertions.did_not_refuse(
        {"must_answer": True}, {"refused": True, "refused_by": "model"}
    )
    assert refused["status"] == "fail"

    not_required = eval_assertions.did_not_refuse({}, {"refused": True})
    assert not_required["status"] == "skip"


def test_guard_check_fails_if_an_out_of_scope_question_gets_answered():

    correctly_refused = eval_assertions.must_refuse(
        {"must_refuse": True}, {"refused": True, "refused_by": "gate"}
    )
    assert correctly_refused["status"] == "pass"

    wrongly_answered = eval_assertions.must_refuse({"must_refuse": True}, {"refused": False})
    assert wrongly_answered["status"] == "fail"


def test_a7_distinguishes_the_three_reasons_a_citation_can_be_missing():

    # Genuinely uncited - no tag of any kind. A model problem.
    uncited = {"refused": False, "answer": "A fact with no tag.", "cited_chunk_ids": [], "invalid_citations": []}
    checked = eval_assertions.citation_present({}, uncited)
    assert checked["status"] == "fail"
    assert "does not require" not in checked["detail"]

    # Every tag present pointed outside the sources given - A8's problem,
    # called out here rather than blamed on a parsing gap.
    invalid_only = {"refused": False, "answer": "A fact [S9].", "cited_chunk_ids": [], "invalid_citations": ["[S9]"]}
    checked_invalid = eval_assertions.citation_present({}, invalid_only)
    assert checked_invalid["status"] == "fail"
    assert "see A8" in checked_invalid["detail"]

    # A real citation, in the full-width shape v2 now resolves, is no longer
    # reported as missing at all - the exact regression this fix targets.
    full_width = {"refused": False, "answer": "A fact【S1】.", "cited_chunk_ids": ["a.md::1"], "invalid_citations": []}
    checked_full_width = eval_assertions.citation_present({}, full_width)
    assert checked_full_width["status"] == "pass"


def test_run_assertions_applies_summary_checks_only_to_summary_cases():

    qa_case = {"type": "qa", "must_cite": True}
    qa_result = {"refused": False, "answer": "Fact [S1].", "cited_chunk_ids": ["a::1"], "invalid_citations": []}

    checks = eval_assertions.run_assertions(qa_case, qa_result)
    assert {c["id"] for c in checks} == {"A6", "A7", "A8"}

    summary_case = {
        "type": "summary",
        "case": {"claim_no": "CLM-2026-00417", "date_of_loss": "2026-03-14", "deductible": "$500"},
        "must_cite": True,
    }
    summary_result = _summary_result(
        "CLAIM: CLM-2026-00417\nDATE OF LOSS: 2026-03-14\nCOVERAGE: covered\n"
        "BASIS: Covered per [S1].\nDEDUCTIBLE: $500\nNEXT ACTION: Pay the claim.\n"
    )
    summary_result["cited_chunk_ids"] = ["a::1"]

    summary_checks = eval_assertions.run_assertions(summary_case, summary_result)
    assert {c["id"] for c in summary_checks} >= {"A1", "A2", "A3", "A6", "A7", "A8"}


def test_summarise_prioritises_fail_over_review_over_pass():

    assert eval_assertions.summarise([{"status": "pass"}, {"status": "review"}]) == "review"
    assert eval_assertions.summarise([{"status": "fail"}, {"status": "pass"}]) == "fail"
    assert eval_assertions.summarise([{"status": "pass"}]) == "pass"


# --------------------------------------------------------------- eval_service

class _FakeRag:

    def ask(self, question, mode="dense"):

        if "refuse" in question.lower():
            return {
                "answer": "I don't know - the documents provided don't cover this.",
                "refused": True,
                "refused_by": "gate",
                "sources": [],
                "invalid_citations": [],
                "retrieved": [],
            }

        return {
            "answer": "A $500 deductible applies [S1].",
            "refused": False,
            "refused_by": None,
            "sources": [{"chunk_id": "a.md::1"}],
            "invalid_citations": [],
            "retrieved": [{"chunk_id": "a.md::1"}],
        }


def test_eval_service_normalises_ask_output_so_citation_checks_see_it(tmp_path):

    eval_set = tmp_path / "eval_set.jsonl"
    eval_set.write_text(
        '{"id": "Q1", "type": "qa", "mode": "M1", "question": "cite this", '
        '"must_answer": true, "must_cite": true}\n'
        '{"id": "Q2", "type": "qa", "mode": "GUARD", "question": "please refuse", '
        '"must_refuse": true, "must_cite": false}\n',
        encoding="utf-8",
    )

    service = EvalService(eval_set_path=eval_set, runs_dir=tmp_path / "runs")

    result = service.run(rag_service=_FakeRag(), use_judge=False, sleep=0, label="test")

    by_id = {case["id"]: case for case in result["cases"]}

    assert by_id["Q1"]["status"] == "pass"
    assert by_id["Q1"]["cited_chunk_ids"] == ["a.md::1"]
    assert by_id["Q2"]["status"] == "pass"

    assert result["totals"]["cases"] == 2
    assert result["totals"]["passed"] == 2
    assert {row["mode"] for row in result["by_mode"]} == {"M1", "GUARD"}


def test_eval_service_records_a_case_error_without_losing_the_run(tmp_path):

    eval_set = tmp_path / "eval_set.jsonl"
    eval_set.write_text('{"id": "Q1", "type": "summary", "mode": "M6", "notes": "x"}\n', encoding="utf-8")

    service = EvalService(eval_set_path=eval_set, runs_dir=tmp_path / "runs")

    # No summary_service passed -> BadRequestError inside _run_case, caught and recorded.
    result = service.run(rag_service=_FakeRag(), use_judge=False, sleep=0, label="test")

    assert result["cases"][0]["status"] == "fail"
    assert result["cases"][0]["error"] is not None
    assert result["totals"]["errors"] == 1


def test_compare_produces_a_delta_row_per_mode():

    before = {"by_mode": [{"mode": "M1", "passed": 1, "total": 5, "pass_rate": 0.2}]}
    after = {"by_mode": [{"mode": "M1", "passed": 4, "total": 5, "pass_rate": 0.8}]}

    rows = compare(before, after)

    assert rows == [
        {
            "mode": "M1",
            "before_passed": 1, "before_total": 5, "before_rate": 0.2,
            "after_passed": 4, "after_total": 5, "after_rate": 0.8,
            "delta": 0.6,
        }
    ]


def test_eval_service_load_cases_rejects_missing_required_fields(tmp_path):

    from app.core.errors import BadRequestError

    eval_set = tmp_path / "eval_set.jsonl"
    eval_set.write_text('{"id": "Q1"}\n', encoding="utf-8")

    service = EvalService(eval_set_path=eval_set, runs_dir=tmp_path / "runs")

    import pytest
    with pytest.raises(BadRequestError):
        service.load_cases()
