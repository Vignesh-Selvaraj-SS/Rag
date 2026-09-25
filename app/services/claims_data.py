"""
The claim record store behind get_claim(). A fixture, not a database - Task
Set D's own extension is scoped to "the app you already built," and this app
never had a claims system, only a policy-document index. Ten synthetic
claims, each grounded in real clauses from the indexed policy documents
(see evaluation/triage_claims.json for the claim data and the expected
decision/payout used to score the race), so search_policy's answers about
them are genuine lookups, not fabricated numbers.
"""

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
TRIAGE_CLAIMS_PATH = REPO_ROOT / "evaluation" / "triage_claims.json"

_claims_by_id: dict[str, dict[str, Any]] | None = None


def _load() -> dict[str, dict[str, Any]]:
    global _claims_by_id
    if _claims_by_id is None:
        records = json.loads(TRIAGE_CLAIMS_PATH.read_text(encoding="utf-8"))
        _claims_by_id = {record["claim_id"]: record for record in records}
    return _claims_by_id


def all_claim_ids() -> list[str]:
    return list(_load().keys())


def get_claim_record(claim_id: str) -> dict[str, Any] | None:
    """The full fixture record, including the expected answer - callers that
    hand this to the model must strip `expected`/`why`/`dependent` first
    (see get_claim() in triage_tools.py)."""
    return _load().get(claim_id)
