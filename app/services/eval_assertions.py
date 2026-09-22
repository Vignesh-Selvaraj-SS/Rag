"""
Deterministic checks, run before any judge is asked anything.

Every criterion here was taken OUT of the judge prompt on purpose: a regex
settles a claim-number format for free and never has an off day, and paying a
model to confirm that a number is numeric is the mistake this week warns
against. The judge is reserved for what a rule genuinely cannot decide.

A1-A4 score a claim summary against its case fixture.
A5-A8 score any answer, and delegate to app/services/trace_checks.py so the
running application and the evaluation apply exactly the same rules.

Each check returns {id, name, status, detail} where status is one of
pass / fail / review / skip, matching trace_checks.
"""

import re
from datetime import datetime

from app.services.citations import has_citation
from app.services.trace_checks import (
    check_citation_present,
    check_no_invalid_citations,
    check_output_complete,
)

CLAIM_NO = re.compile(r"\bCLM-(20\d{2})-(\d{5})\b")

MONEY = re.compile(r"\$\s?\d{1,3}(?:,\d{3})*(?:\.\d{2})?\b")

CLAUSE_ID = re.compile(r"\b(?:HO-20\d{2}-\d{2}[A-Z]?|CP-\d{2})\b")

DENIAL_WORDS = re.compile(
    r"\b(den(?:y|ied|ial)|not covered|no coverage|excluded|exclusion applies"
    r"|outside the scope of coverage)\b",
    re.IGNORECASE,
)

DATE_PATTERNS = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}"
    r"|\d{1,2}\s+[A-Z][a-z]+\s+20\d{2}"
    r"|[A-Z][a-z]+\s+\d{1,2},\s*20\d{2}"
    r"|\d{1,2}/\d{1,2}/20\d{2})\b"
)

DATE_FORMATS = ("%Y-%m-%d", "%d %B %Y", "%B %d, %Y", "%B %d %Y", "%m/%d/%Y", "%d/%m/%Y")

UNSETTLED = "not established in the policy sources"


def _result(check_id: str, name: str, status: str, detail: str = "") -> dict:
    return {"id": check_id, "name": name, "status": status, "detail": detail}


def parse_date(text: str) -> datetime | None:
    """The first date in `text` that actually parses, or None."""

    for candidate in DATE_PATTERNS.findall(text or ""):
        for fmt in DATE_FORMATS:
            try:
                return datetime.strptime(candidate.strip(), fmt)
            except ValueError:
                continue

    return None


# --------------------------------------------------------------- A1 to A4

def claim_number_echoed(case: dict, result: dict) -> dict:
    """A1 - the claim number appears in CLM-YYYY-NNNNN form and is the right one."""

    name = "A1 claim number echoed"
    expected = (case.get("claim_no") or "").strip()

    if not expected:
        return _result("A1", name, "skip", "case carries no claim number")

    found = CLAIM_NO.findall(result.get("summary") or "")
    literals = [f"CLM-{year}-{number}" for year, number in found]

    if not literals:
        return _result("A1", name, "fail", "no claim number in CLM-YYYY-NNNNN form")

    if expected not in literals:
        return _result(
            "A1", name, "fail",
            f"claim number mismatch: summary has {', '.join(literals)}, case is {expected}",
        )

    return _result("A1", name, "pass")


def date_of_loss_parseable(case: dict, result: dict) -> dict:
    """A2 - a date of loss is present and parses to the case's date."""

    name = "A2 date of loss parseable"
    expected = (case.get("date_of_loss") or "").strip()

    if not expected:
        return _result("A2", name, "skip", "case carries no date of loss")

    line = (result.get("fields") or {}).get("DATE OF LOSS") or result.get("summary") or ""
    parsed = parse_date(line)

    if parsed is None:
        return _result("A2", name, "fail", f"no parseable date in {line[:60]!r}")

    if parsed.date().isoformat() != expected:
        return _result(
            "A2", name, "fail",
            f"{parsed.date().isoformat()} does not match date of loss {expected}",
        )

    return _result("A2", name, "pass")


def deductible_is_numeric(case: dict, result: dict) -> dict:
    """A3 - an excess/deductible figure is stated as a number, not prose."""

    name = "A3 deductible is numeric"
    fields = result.get("fields") or {}
    line = fields.get("DEDUCTIBLE")

    if line is None:
        return _result("A3", name, "fail", "no DEDUCTIBLE line in the summary")

    if UNSETTLED.lower() in line.lower():
        return _result("A3", name, "pass", "declared unsettled rather than guessed")

    # "no deductible applies" is a real policy outcome, not a missing figure:
    # scheduled property under HO-2026-04 carries none.
    if re.search(r"\bno deductible\b|\bnone\b|\$0\b", line, re.IGNORECASE):
        return _result("A3", name, "pass", "states that no deductible applies")

    if not MONEY.search(line):
        return _result("A3", name, "fail", f"deductible stated without a figure: {line[:60]!r}")

    expected = case.get("deductible")

    if expected:
        figures = [f.replace(" ", "") for f in MONEY.findall(line)]
        if expected not in figures:
            return _result(
                "A3", name, "fail",
                f"deductible {', '.join(figures)} does not match the expected {expected}",
            )

    return _result("A3", name, "pass")


def denial_cites_clause(case: dict, result: dict) -> dict:
    """A4 - if a denial is stated, an exclusion clause id must be cited."""

    name = "A4 denial cites a clause"
    fields = result.get("fields") or {}
    coverage = fields.get("COVERAGE") or ""
    basis = fields.get("BASIS") or ""
    text = f"{coverage} {basis}"

    match = DENIAL_WORDS.search(text)

    if not match:
        return _result("A4", name, "skip", "no denial stated")

    clauses = sorted(set(CLAUSE_ID.findall(text)))

    if not clauses:
        return _result(
            "A4", name, "fail",
            f"denial stated ({match.group(0)!r}) with no clause id cited",
        )

    return _result("A4", name, "pass", f"cites {', '.join(clauses)}")


SUMMARY_ASSERTIONS = (
    claim_number_echoed,
    date_of_loss_parseable,
    deductible_is_numeric,
    denial_cites_clause,
)


# --------------------------------------------------------------- A5 to A8

def did_not_refuse(case: dict, result: dict) -> dict:
    """
    A5 - a question the Week 5 traces show is answerable from the corpus must
    not be refused again. This is the regression test for failure mode M1.
    """

    name = "A5 answered rather than refused"

    if not case.get("must_answer"):
        return _result("A5", name, "skip", "case does not require an answer")

    if not result.get("refused"):
        return _result("A5", name, "pass")

    return _result(
        "A5", name, "fail",
        f"refused again (refused_by={result.get('refused_by')})",
    )


def must_refuse(case: dict, result: dict) -> dict:
    """
    The guard property. Out-of-scope questions must keep being refused, so a
    fix aimed at M1 cannot quietly buy its win by answering everything.
    """

    name = "A5b refused as out of scope"

    if not case.get("must_refuse"):
        return _result("A5b", name, "skip", "case is in scope")

    if result.get("refused"):
        return _result("A5b", name, "pass", f"refused by the {result.get('refused_by')}")

    return _result("A5b", name, "fail", "answered a question that is out of scope")


def output_complete(case: dict, result: dict) -> dict:
    """A6 - the answer does not stop mid-sentence. Regression test for M2."""

    checked = check_output_complete(result)

    return _result("A6", "A6 output is complete", checked["status"], checked["detail"])


def citation_present(case: dict, result: dict) -> dict:
    """A7 - an answered question cites at least one retrieved chunk. M3."""

    if case.get("must_cite") is False:
        return _result("A7", "A7 cites a source", "skip", "case does not require a citation")

    checked = check_citation_present(result)

    detail = checked["detail"]

    # Distinguish three reasons cited_chunk_ids can be empty - each points at
    # a different fix, and conflating them is exactly how the real bug here
    # (v1's ASCII-only parser silently dropping full-width citations) went
    # unnoticed: "no tag at all" is a model problem, "every tag pointed out
    # of range" is already A8's problem, and "a tag in a shape CITATION_TAG
    # does not resolve" would be a parser gap - kept distinct in case a new
    # shape appears, even though v2 now resolves every shape seen so far.
    if checked["status"] == "fail":
        text = result.get("answer") or result.get("summary") or ""
        if result.get("invalid_citations"):
            detail = "every citation tag pointed outside the sources given (see A8)"
        elif has_citation(text):
            detail = "answer carries a citation tag CITATION_TAG does not resolve - a new bracket shape?"

    return _result("A7", "A7 cites a source", checked["status"], detail)


def no_invalid_citations(case: dict, result: dict) -> dict:
    """A8 - no [S#] tag pointing at a source that was never provided."""

    checked = check_no_invalid_citations(result)

    return _result("A8", "A8 no invented citations", checked["status"], checked["detail"])


ANSWER_ASSERTIONS = (
    did_not_refuse,
    must_refuse,
    output_complete,
    citation_present,
    no_invalid_citations,
)

ASSERTION_COUNT = len(SUMMARY_ASSERTIONS) + len(ANSWER_ASSERTIONS)


def run_assertions(case: dict, result: dict) -> list[dict]:
    """
    Apply the checks that fit the case type. A summary is also an answer, so
    it gets the completeness and citation checks too.
    """

    checks = [assertion(case, result) for assertion in ANSWER_ASSERTIONS]

    if case.get("type") == "summary":
        checks = [assertion(case.get("case", {}), result) for assertion in SUMMARY_ASSERTIONS] + checks

    return [check for check in checks if check["status"] != "skip"] or checks


def summarise(checks: list[dict]) -> str:
    """One word for a list of results: fail beats review beats pass."""

    statuses = {check["status"] for check in checks}

    if "fail" in statuses:
        return "fail"

    if "review" in statuses:
        return "review"

    return "pass"
