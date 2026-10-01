"""
The claims-system tool implementations: general policy Q&A tools
(`search_policy`, `list_documents`) plus the claim-triage tools that used to
live in a separate `triage_tools.py` before `ClaimAgent`/`ClaimTriageAgent`
were merged into one class - `get_claim`, `compute_payout`, and two further
situational tools (`check_settlement_authority`, `flag_for_review`).

Originally shipped with four more situational tools
(`check_subrogation_required`, `calculate_acv_depreciation`,
`get_special_sublimit`, `validate_denial_letter`) - cut once none of the 10
fixture claims in `evaluation/trajectory_expected.json` ever required them
(every claim's `must_include` is just `search_policy`/`compute_payout`), so
they had no live trigger case and no evidence they were ever exercised.

Every tool function takes a single `args: dict` and returns a small dict the
agent logs and feeds back into the next prompt. A tool never raises for a
bad but plausible call - it returns an error string in the result instead,
so a single bad tool call costs one step, not the whole run.

Week 9: these functions are no longer called directly by `ClaimAgent` (an
in-process if/elif dispatch by tool name). They are wrapped, unchanged, by
`mcp_servers/claims_system_server.py` (or, for `get_claim`, the separate
`mcp_servers/claims_status_server.py` - see Task Set D's docstring there
for why it's split out) and exposed over MCP - the agent discovers and
calls them through `app/services/mcp_client.py` instead, so this module
stays the single place the actual claims-system logic lives, reused (not
reimplemented) by every MCP server and this file's own `_resolve_source`
fix below.

`search_policy`'s description references `list_documents` for file-name
discovery, so a specific-document search doesn't have to guess a source
name it was never told.
"""

import re

from app.core.config import settings
from app.services.claims_data import get_claim_record
from app.services.document_loader import SUPPORTED_EXTENSIONS
from app.services.retrieval_service import RetrievalService

# Shared by ClaimAgent and FixedClaimWorkflow: a deterministic, code-level
# check for "is this input a claim id," not a model judgment call. Live bug
# this exists to fix: merging both jobs into one agent meant sending BOTH
# jobs' tool schemas and BOTH jobs' system-prompt rules on every single
# turn - roughly double the per-call token cost of either original agent -
# and a live run on CLM-2001 (previously a simple, 4-step claim) burned
# 17,204 tokens across 5 steps and hit token_limit without ever finishing.
# Scoping the tools and the prompt by input shape fixes the actual cost
# regression the merge introduced, not just its symptom (a bigger budget).
CLAIM_ID_PATTERN = re.compile(r"^CLM-\d+$", re.IGNORECASE)

# How much chunk text is shown to the agent per hit. Found the hard way,
# live: 320 chars cut off a real chunk (claims-adjuster-authority.md's
# settlement-authority table) right before the dollar figures it holds -
# the agent could see the chunk existed but never the numbers in it, and
# burned its whole step budget re-searching for a fact it could never see.
# 1200 comfortably covers this corpus's longest heading-based chunks
# (short intro sentence + a markdown table); llm_service.py and
# summary_service.py never truncate chunk text at all for the same reason.
SNIPPET_CHARS = 1200

CLAIM_STATUSES = ["approved", "denied", "partial"]


def _resolve_source(source: str | None) -> str | None:
    """
    Live bug, found running the Task Set D triage extension: the model
    reliably guesses a `source` from the endorsement code or policy form it
    already knows (e.g. "HO-2026-01") rather than the real file name
    ("endorsement-HO-2026-01-water-backup.md"), no matter how the tool
    description tells it not to - and an exact-match filter then returns
    zero hits, burning a step on a search that should have worked. Resolving
    a case-insensitive substring match against the real file names fixes
    this without relying on prompt compliance. Falls back to the value
    given, unchanged, when nothing matches (including in tests, which use
    file names like "a.md" that were never meant to resolve against the
    real corpus) or when the corpus can't be listed.
    """

    if not source or not settings.DATA_DIR.exists():
        return source

    names = [
        path.name for path in settings.DATA_DIR.iterdir()
        if path.is_file() and not path.name.startswith(".") and path.suffix.lower() in SUPPORTED_EXTENSIONS
    ]

    if source in names:
        return source

    needle = source.lower()
    matches = [name for name in names if needle in name.lower()]

    return matches[0] if len(matches) == 1 else source


def search_policy(retriever: RetrievalService, args: dict) -> dict:
    """
    Search the indexed policy documents. Never returns claim-specific facts
    (amount, notes, peril) - that is get_claim's job. Optionally scoped to
    one file name (from list_documents) - the agent's way of "looking
    something up in a specific document" once it knows that document exists.
    """

    query = str(args.get("query") or "").strip()

    if not query:
        return {"error": "search_policy needs a non-empty 'query'."}

    source = _resolve_source(args.get("source") or None)
    top_k = int(args.get("top_k") or 5)
    top_k = max(1, min(top_k, 10))

    retrieval = retriever.retrieve(query, top_k=top_k, mode="hybrid", source=source)
    hits = retrieval["hits"]

    if not hits:
        return {"result": f"No chunks found for query {query!r}" + (f" in {source}" if source else "") + "."}

    return {
        "result": [
            {
                "source": hit["source"],
                "heading": hit["heading"],
                "page": hit["page"],
                "score": round(float(hit["dense_score"]), 3),
                "text": hit["text"][:SNIPPET_CHARS],
            }
            for hit in hits
        ]
    }


def list_documents(args: dict) -> dict:
    """
    Names of every indexed document, so the agent can decide to target a
    specific one (e.g. the claims procedure file) on a later search rather
    than guessing a source filename it was never told.
    """

    if not settings.DATA_DIR.exists():
        return {"result": []}

    names = sorted(
        path.name
        for path in settings.DATA_DIR.iterdir()
        if path.is_file()
        and not path.name.startswith(".")
        and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    return {"result": names}


def get_claim(args: dict) -> dict:
    """
    Retrieve one claim's own case file by ID: claimed amount, reported
    peril, the policy form and endorsements attached, and the adjuster's
    notes. Never returns policy wording - that is search_policy's job. Only
    ever call this when the input actually names a claim ID (CLM-####) - a
    general policy question has no claim to pull.
    """

    claim_id = str(args.get("claim_id") or "").strip()

    if not claim_id:
        return {"error": "get_claim needs a non-empty 'claim_id', formatted like CLM-YYYY-nnnnn, e.g. CLM-2001."}

    record = get_claim_record(claim_id)

    if record is None:
        # Week 9 Task Set D: recoverable, not "Error: lookup failed" - names
        # what was tried and what a valid one looks like, so the model can
        # tell a typo'd claim number apart from a genuinely dead claims
        # system (a materially different situation - see error_before_after.md)
        # instead of quietly answering about coverage with no claim loaded.
        return {"error": f"claim {claim_id!r} not found: claim numbers look like CLM-YYYY-nnnnn, e.g. CLM-2001."}

    return {
        "result": {
            "claim_id": record["claim_id"],
            "claimed_amount": record["claimed_amount"],
            "policy_form": record["policy_form"],
            "adjuster_notes": record["adjuster_notes"],
        }
    }


def compute_payout(args: dict) -> dict:
    """
    Compute the payable amount after the excess/deductible, given a claim
    status the agent has already decided. Pure arithmetic, no lookups: if
    `claim_status` is "denied", the payout is 0 regardless of the amounts
    given; otherwise payout = max(0, claimed_amount - excess_amount).
    """

    claim_status = str(args.get("claim_status") or "").strip().lower()

    if claim_status not in CLAIM_STATUSES:
        return {"error": f"claim_status must be one of {CLAIM_STATUSES}, got {claim_status!r}."}

    try:
        claimed_amount = float(args.get("claimed_amount"))
        excess_amount = float(args.get("excess_amount"))
    except (TypeError, ValueError):
        return {"error": "compute_payout needs numeric 'claimed_amount' and 'excess_amount'."}

    if claim_status == "denied":
        payout = 0.0
    else:
        payout = max(0.0, claimed_amount - excess_amount)

    return {"result": {"claim_status": claim_status, "payout": payout}}


# --------------------------------------------------------------------------
# Six further tools, each a structured lookup or a single arithmetic/action
# step grounded in real content already in the indexed policy documents.
# Each states, in its schema description, what it does NOT do, for the same
# reason get_claim/search_policy/compute_payout do: closing the ambiguity
# that causes tool-choice thrash before the next tool is the fix, not a
# prompt bolted on afterward.
# --------------------------------------------------------------------------

# claims-adjuster-authority.md §1 - ordered lowest to highest; the first
# grade whose limit covers the payout is the one required.
_AUTHORITY_LEVELS = [
    ("desk_adjuster_grade_1", 10_000),
    ("desk_adjuster_grade_2", 25_000),
    ("field_adjuster", 75_000),
    ("senior_field_adjuster", 150_000),
    ("claims_team_manager", 350_000),
    ("large_loss_unit_manager", 1_000_000),
    ("head_of_claims", float("inf")),
]


def check_settlement_authority(args: dict) -> dict:
    """
    Look up which adjuster grade's settlement authority covers a payout
    amount. Does not decide coverage or compute the payout itself - call
    this only after compute_payout, to check who is allowed to approve it.
    """

    try:
        payout_amount = float(args.get("payout_amount"))
    except (TypeError, ValueError):
        return {"error": "check_settlement_authority needs a numeric 'payout_amount'."}

    for grade, limit in _AUTHORITY_LEVELS:
        if payout_amount <= limit:
            return {"result": {"required_grade": grade, "authority_limit": limit if limit != float("inf") else "policy_limits"}}

    return {"result": {"required_grade": "head_of_claims", "authority_limit": "policy_limits"}}  # pragma: no cover - inf always matches above


def flag_for_review(args: dict) -> dict:
    """
    Escalate a claim for human review instead of finishing it. The one
    action/write tool in this set - every other tool only reads or
    computes. Use this instead of `finish` when the claim genuinely can't
    be resolved from the available tools (e.g. contradictory notes, a
    document the corpus doesn't have).
    """

    claim_id = str(args.get("claim_id") or "").strip()
    reason = str(args.get("reason") or "").strip()

    if not claim_id or not reason:
        return {"error": "flag_for_review needs both a non-empty 'claim_id' and 'reason'."}

    return {"result": f"Claim {claim_id} flagged for human review: {reason}"}


# Week 9: these six functions' JSON schemas used to be hand-written here
# (a manual TOOL_SCHEMAS list) and sent to Groq directly. Now they are
# generated by FastMCP, from the typed wrapper functions in
# mcp_servers/claims_system_server.py, and ClaimAgent discovers them at
# runtime over MCP (app/services/mcp_client.py) instead of importing a
# static list - see agent_service.py's `_tools_for`. `finish` is not a
# claims-system capability - it is this agent's own loop-control signal -
# so it stays local, defined in agent_service.py, never exposed over MCP.
