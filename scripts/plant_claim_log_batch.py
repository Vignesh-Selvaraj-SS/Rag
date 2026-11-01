"""
Week 11 Task Set D: builds the claim-log batch the drill is found inside.

This script was already run once, live, against Groq - its output is the 13
real entries sitting in .runtime/claim_log.jsonl (not synthetic data; every
summary below is a genuine SummaryService.summarise() call). Re-running it
makes 13 more real Groq calls for no benefit, since the drill in
docs/training/week11/drill.md was investigated against the file this script
already produced. Kept in the repo so the method that produced that file is
reviewable, not just its output.

What is real and what is staged, stated plainly:
  - every summary's CONTENT, cost and latency are real Groq/Qdrant calls -
    nothing about the text or the numbers is fabricated
  - only the TIMESTAMPS are deliberately backdated (to simulate "yesterday"
    for the drill's complaint), via the `timestamp=` passthrough on
    ClaimLogService.record() - there is no other way to get requests spread
    across several days without actually waiting several days

One of these calls is not a normal case: PLANTED_BAD_NOTES is logged with
`source="faq-policyholder-endorsements.md"`, a real retrieval misconfiguration
(scoping the search to one document) rather than a hand-typed fake answer -
see docs/training/week11/trace.json's `_diagnosis` for why this produces a
wrongful "covered" determination.
"""

import json
from datetime import datetime, timedelta, timezone

from app.core.config import settings
from app.services.claim_log_service import ClaimLogService
from app.services.rag_service import RAGService
from app.services.summary_service import SummaryService

TODAY = datetime(2026, 10, 13, 9, 0, tzinfo=timezone.utc)
YESTERDAY = TODAY - timedelta(days=1)
TWO_DAYS_AGO = TODAY - timedelta(days=2)

PLANTED_BAD_NOTES = (
    "Claim CLM-2026-09001, date of loss 2026-08-20. Policyholder reports water "
    "has been seeping into the basement through the floor drain continuously over the past three "
    "weeks, gradually soaking the carpet and baseboards. Endorsement HO-2026-01 is attached. "
    "What is the coverage position and the deductible?"
)


def _load_real_m6_cases() -> list[dict]:
    """
    The app's own real M6 (claim-summary) eval cases, minus the one case
    this drill itself adds (R-M6-W11 - that one is logged separately below,
    deliberately, not mixed in as if it were an ordinary case).
    """

    cases = []
    with settings.eval_set_path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            case = json.loads(line)
            if case.get("mode") == "M6" and case["id"] != "R-M6-W11":
                cases.append(case)
    return cases


def main() -> None:

    rag = RAGService()
    summary_service = SummaryService(rag_service=rag)
    log = ClaimLogService(path=settings.claim_log_path, enabled=True)

    real_cases = _load_real_m6_cases()
    assert len(real_cases) == 9, f"expected 9 real M6 cases, found {len(real_cases)}"

    # 9 real requests, spread across yesterday.
    for index, case in enumerate(real_cases):
        timestamp = (YESTERDAY + timedelta(minutes=37 * index)).isoformat(timespec="seconds")
        outcome = summary_service.summarise(case["notes"], mode=case.get("retrieval_mode", "hybrid"))
        request_id = log.record(case["notes"], case["case"].get("claim_no"), outcome, timestamp=timestamp)
        print(f"logged {request_id} ({case['id']}) at {timestamp}")

    # The one planted bad answer, also yesterday - the needle in the drill.
    planted_timestamp = (YESTERDAY + timedelta(hours=10)).isoformat(timespec="seconds")
    planted_outcome = summary_service.summarise(
        PLANTED_BAD_NOTES, mode="hybrid", source="faq-policyholder-endorsements.md"
    )
    planted_id = log.record(
        PLANTED_BAD_NOTES, "CLM-2026-09001", planted_outcome, timestamp=planted_timestamp
    )
    print(f"logged {planted_id} (PLANTED) at {planted_timestamp}")

    # 2 extra real requests today, 1 extra two days ago - so "time" alone
    # cannot be the whole answer; the drill still has to narrow further.
    today_cases = real_cases[:2]
    for index, case in enumerate(today_cases):
        timestamp = (TODAY + timedelta(minutes=20 * index)).isoformat(timespec="seconds")
        outcome = summary_service.summarise(case["notes"], mode=case.get("retrieval_mode", "hybrid"))
        request_id = log.record(case["notes"], case["case"].get("claim_no"), outcome, timestamp=timestamp)
        print(f"logged {request_id} ({case['id']}, today) at {timestamp}")

    two_days_ago_case = real_cases[2]
    timestamp = TWO_DAYS_AGO.isoformat(timespec="seconds")
    outcome = summary_service.summarise(
        two_days_ago_case["notes"], mode=two_days_ago_case.get("retrieval_mode", "hybrid")
    )
    request_id = log.record(
        two_days_ago_case["notes"], two_days_ago_case["case"].get("claim_no"), outcome, timestamp=timestamp
    )
    print(f"logged {request_id} ({two_days_ago_case['id']}, two days ago) at {timestamp}")

    print(f"\nTotal entries now in {settings.claim_log_path}: {len(log.load_all())}")


if __name__ == "__main__":
    main()
