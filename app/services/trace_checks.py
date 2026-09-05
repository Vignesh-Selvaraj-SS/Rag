"""
Deterministic quality checks over a recorded trace.

These are cheap, regex-level assertions that need no model call. Each check
returns a status:

    pass    the property holds
    fail    the property is violated
    review  cannot be settled automatically - a person should look
    skip    not applicable to this trace (e.g. citation checks on a refusal)

Recovered from the Week 6 assertions module (A5-A8), whose source was lost;
the behaviour is re-implemented from the documented criteria.
"""

TERMINAL_ENDINGS = (".", "!", "?", '"', "”", ")", "]", "*")


def check_output_complete(trace: dict) -> dict:
    """The answer does not stop mid-sentence."""

    if trace.get("refused"):
        return _result("output_complete", "Answer is complete", "skip", "refused")

    answer = (trace.get("answer") or "").rstrip()

    if not answer:
        return _result("output_complete", "Answer is complete", "fail", "empty answer")

    if answer.endswith(TERMINAL_ENDINGS):
        return _result("output_complete", "Answer is complete", "pass", "")

    return _result(
        "output_complete",
        "Answer is complete",
        "fail",
        f"ends mid-sentence: …{answer[-60:]}",
    )


def check_citation_present(trace: dict) -> dict:
    """An answered question cites at least one retrieved chunk."""

    if trace.get("refused"):
        return _result("citation_present", "Answer cites a source", "skip", "refused")

    if trace.get("cited_chunk_ids"):
        return _result("citation_present", "Answer cites a source", "pass", "")

    return _result(
        "citation_present",
        "Answer cites a source",
        "fail",
        "answer states facts without citing any retrieved chunk",
    )


def check_no_invalid_citations(trace: dict) -> dict:
    """No [S#] tag points at a source that was never provided."""

    invalid = trace.get("invalid_citations") or []

    if invalid:
        return _result(
            "no_invalid_citations",
            "No invented citations",
            "fail",
            "invented citations " + ", ".join(invalid),
        )

    return _result("no_invalid_citations", "No invented citations", "pass", "")


def check_refusal(trace: dict) -> dict:
    """
    A model refusal after retrieval passed the gate may be a wrong refusal
    (the answer was in the chunks) or a correct one (out of scope). That
    cannot be settled without reading, so it is flagged for review rather
    than judged.
    """

    if not trace.get("refused"):
        return _result("refusal", "Not refused", "pass", "")

    if trace.get("refused_by") == "gate":
        return _result(
            "refusal",
            "Not refused",
            "skip",
            "refused by the similarity gate before any model call",
        )

    best = max(
        (hit.get("dense_score", 0.0) for hit in trace.get("retrieved", [])),
        default=0.0,
    )

    return _result(
        "refusal",
        "Not refused",
        "review",
        f"model refused although retrieval passed the gate (best similarity {best:.2f}) - "
        "check whether the answer was in the retrieved chunks",
    )


CHECKS = (
    check_refusal,
    check_output_complete,
    check_citation_present,
    check_no_invalid_citations,
)


def run_checks(trace: dict) -> list[dict]:
    return [check(trace) for check in CHECKS]


def summarise_checks(results: list[dict]) -> str:
    """One word for a list of check results: fail > review > pass."""

    statuses = {result["status"] for result in results}

    if "fail" in statuses:
        return "fail"

    if "review" in statuses:
        return "review"

    return "pass"


def _result(check_id: str, name: str, status: str, detail: str) -> dict:
    return {"id": check_id, "name": name, "status": status, "detail": detail}
