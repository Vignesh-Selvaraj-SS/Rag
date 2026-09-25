"""
The three tools the claim-triage agent can call, plus the shared `finish`
contract both the agent and the fixed workflow report through.

Task Set D's own common-mistakes list names the trap directly: fixing tool
thrash by prompt-bolting instead of sharpening overlapping descriptions.
The two starting tools are `get_claim` (claim-specific facts: amount, peril,
notes) and `search_policy` (imported from agent_tools.py, unchanged -
policy-wide text: exclusions, endorsements, deductibles, authority limits).
Neither ever answers the other's question, stated as the first sentence of
each description below, not left implicit.

`compute_payout` is the new third tool this extension adds. One job only -
arithmetic on numbers the agent already determined - and it takes an enum
`claim_status` parameter rather than a free-text status string, so a
malformed status can't silently produce a wrong number.

Six further tools follow `compute_payout`: `check_settlement_authority`,
`check_subrogation_required`, `calculate_acv_depreciation`,
`get_special_sublimit`, `validate_denial_letter` and `flag_for_review` (the
one action/write tool - every other tool here only reads or computes). Each
is grounded in a real table or requirement already in the indexed policy
documents (see each function's docstring for the source section), and each
states what it does NOT do in its own description, for the same reason.
"""

from app.services.claims_data import get_claim_record

CLAIM_STATUSES = ["approved", "denied", "partial"]

# search_policy's underlying function is imported unchanged from
# agent_tools.py (see triage_agent.py/fixed_triage_workflow.py) - only its
# schema is redeclared here, because agent_tools.py's description references
# list_documents ("from list_documents"), a tool this agent doesn't have.
# Repeating a stale cross-reference would be its own description bug, the
# exact trap this task's common-mistakes list warns about.
_SEARCH_POLICY_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_policy",
        "description": (
            "Search the underwriting POLICY and procedure documents - exclusions, "
            "endorsement wording, deductibles, settlement authority - for text relevant to "
            "the query. Never returns claim-specific facts (amount, notes, peril) - that is "
            "get_claim's job. Set `source` to one exact file name only once you already "
            "suspect the answer lives in that specific document."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look up, e.g. 'water backup flood exclusion' or 'equipment breakdown manufacturer warranty'."},
                "source": {"type": "string", "description": "An exact file name to restrict the search to. There is no way to list file names directly - never guess one from an endorsement code or policy form (e.g. 'HO-2026-01' is NOT a file name). Leave this unset on your first search; only set it on a later search, copied exactly from a 'source' field a previous search result already returned."},
                "top_k": {"type": "integer", "description": "How many chunks to return, default 5."},
            },
            "required": ["query"],
        },
    },
}


def get_claim(args: dict) -> dict:
    """
    Retrieve one claim's own case file by ID: claimed amount, reported
    peril, the policy form and endorsements attached, and the adjuster's
    notes. Never returns policy wording - that is search_policy's job.
    """

    claim_id = str(args.get("claim_id") or "").strip()

    if not claim_id:
        return {"error": "get_claim needs a non-empty 'claim_id'."}

    record = get_claim_record(claim_id)

    if record is None:
        return {"error": f"No claim found with id {claim_id!r}."}

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
# step grounded in real content already in the indexed policy documents -
# added so the agent has more to genuinely decide between, not because the
# core triage task needed them. Each states, in its schema description,
# what it does NOT do, for the same reason get_claim/search_policy/
# compute_payout do: closing the ambiguity that causes tool-choice thrash
# before the next tool is the fix, not a prompt bolted on afterward.
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

# claims-adjuster-authority.md §6 - triggers requiring Recovery unit referral
# regardless of amount.
_SUBROGATION_TRIGGER_PHRASES = (
    "utility", "contractor excavation", "excavation", "manufacturing defect",
    "municipal sewer", "contractor was working", "contractor on",
)
_SUBROGATION_AMOUNT_THRESHOLD = 5_000

# endorsement-HO-2026-08-roof-surfaces-acv.md - depreciation schedule.
_ROOF_DEPRECIATION = {
    "composition_shingle": (0.050, 0.80),
    "architectural_shingle": (0.033, 0.70),
    "wood_shake": (0.040, 0.75),
    "metal_panel": (0.025, 0.60),
    "clay_tile": (0.020, 0.50),
    "slate": (0.017, 0.50),
    "modified_bitumen": (0.050, 0.80),
}

# policy-base-HO3-2026.md - Coverage C special limits of liability, per
# occurrence. None of these apply once the item is separately scheduled.
_SPECIAL_SUBLIMITS = {
    "money_bank_notes_bullion_coins": 250,
    "securities_deeds_manuscripts_tickets": 1_750,
    "watercraft": 1_750,
    "trailers_not_with_watercraft": 1_750,
    "jewelry_watches_furs_theft": 2_000,
    "firearms_theft": 2_750,
    "silverware_goldware_theft": 2_750,
    "business_property_on_premises": 3_000,
    "business_property_away": 750,
    "portable_electronics_in_vehicle": 1_750,
}


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


def check_subrogation_required(args: dict) -> dict:
    """
    Determine whether subrogation must be evaluated and referred to the
    Recovery unit, from the payout amount and a short description of the
    cause of loss. Does not look up coverage or compute anything - a pure
    policy-procedure check.
    """

    try:
        payout_amount = float(args.get("payout_amount"))
    except (TypeError, ValueError):
        return {"error": "check_subrogation_required needs a numeric 'payout_amount'."}

    cause_of_loss = str(args.get("cause_of_loss") or "").lower()

    above_threshold = payout_amount > _SUBROGATION_AMOUNT_THRESHOLD
    matched_trigger = next((p for p in _SUBROGATION_TRIGGER_PHRASES if p in cause_of_loss), None)

    required = above_threshold or matched_trigger is not None
    reason = (
        matched_trigger and f"cause of loss matches a mandatory-referral trigger: {matched_trigger!r}"
        or above_threshold and f"payout exceeds the ${_SUBROGATION_AMOUNT_THRESHOLD:,} evaluation threshold"
        or "no threshold or trigger matched"
    )

    return {"result": {"subrogation_required": required, "reason": reason}}


def calculate_acv_depreciation(args: dict) -> dict:
    """
    Compute actual cash value from replacement cost, roof material and roof
    age, using the endorsement's depreciation schedule. Pure arithmetic -
    does not decide whether the ACV basis applies to this loss at all (that
    depends on cause of loss - wind/hail only - which is a coverage
    judgment, not this tool's job).
    """

    material = str(args.get("roof_material") or "").strip().lower()

    if material not in _ROOF_DEPRECIATION:
        return {"error": f"roof_material must be one of {sorted(_ROOF_DEPRECIATION)}, got {material!r}."}

    try:
        replacement_cost = float(args.get("replacement_cost"))
        roof_age_years = float(args.get("roof_age_years"))
    except (TypeError, ValueError):
        return {"error": "calculate_acv_depreciation needs numeric 'replacement_cost' and 'roof_age_years'."}

    annual_rate, max_depreciation = _ROOF_DEPRECIATION[material]
    depreciation_pct = min(max_depreciation, annual_rate * max(0.0, roof_age_years))
    acv = round(replacement_cost * (1 - depreciation_pct), 2)

    return {"result": {"depreciation_pct": round(depreciation_pct, 4), "acv": acv}}


def get_special_sublimit(args: dict) -> dict:
    """
    Look up the base form's special limit of liability for one item
    category. Does not check whether the item is covered at all - only
    returns the sub-limit ceiling that would apply if it is.
    """

    category = str(args.get("item_category") or "").strip().lower()
    is_scheduled = bool(args.get("is_scheduled", False))

    if category not in _SPECIAL_SUBLIMITS:
        return {"error": f"item_category must be one of {sorted(_SPECIAL_SUBLIMITS)}, got {category!r}."}

    if is_scheduled:
        return {"result": {"sublimit": None, "note": "Item is separately scheduled (HO-2026-04) - the base form's special limit does not apply."}}

    return {"result": {"sublimit": _SPECIAL_SUBLIMITS[category]}}


def validate_denial_letter(args: dict) -> dict:
    """
    Check a proposed denial against CP-09's 5 hard requirements before it
    can be issued. Does not decide whether to deny the claim - only whether
    a denial, once decided, is procedurally ready to send.
    """

    checks = {
        "second_adjuster_review": bool(args.get("has_second_adjuster_review", False)),
        "cites_specific_paragraph": bool(args.get("cites_specific_paragraph", False)),
        "plain_language_explanation": bool(args.get("has_plain_language_explanation", False)),
        "appeal_route_included": bool(args.get("has_appeal_route", False)),
        "evidence_retained": bool(args.get("evidence_retained", False)),
    }

    missing = [name for name, passed in checks.items() if not passed]

    return {"result": {"ready_to_issue": not missing, "missing_requirements": missing}}


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


# Tool schemas in the OpenAI/Groq function-calling shape (see agent_tools.py
# for why this model requires native `tools=`, not prompt-text JSON).
TRIAGE_TOOL_SCHEMAS = [
    _SEARCH_POLICY_SCHEMA,
    {
        "type": "function",
        "function": {
            "name": "get_claim",
            "description": (
                "Retrieve the case file for ONE claim by its claim ID: claimed amount, "
                "policy form and endorsements attached, and the adjuster's notes describing "
                "what happened. This is the only tool that returns claim-specific facts - it "
                "never returns policy wording, exclusions or deductible amounts. Call it "
                "exactly once per claim, first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string", "description": "The claim ID, e.g. 'CLM-2001'."},
                },
                "required": ["claim_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "compute_payout",
            "description": (
                "Compute the payable amount after the excess/deductible has been subtracted. "
                "Call this only after you already know, from search_policy, whether the loss "
                "is covered and what deductible applies - this tool does no coverage lookups "
                "of its own, it only does the arithmetic once you supply the numbers."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "claimed_amount": {"type": "number", "description": "The amount claimed."},
                    "excess_amount": {"type": "number", "description": "The applicable deductible/excess. Use 0 if none applies or the claim is denied."},
                    "claim_status": {
                        "type": "string",
                        "enum": CLAIM_STATUSES,
                        "description": "Your coverage decision: 'approved' (fully covered), 'denied' (not covered, payout is 0), or 'partial' (part of the loss is excluded).",
                    },
                },
                "required": ["claimed_amount", "excess_amount", "claim_status"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_settlement_authority",
            "description": (
                "Look up which adjuster grade's settlement authority covers a payout amount. "
                "Does not decide coverage or compute the payout itself - call this only after "
                "compute_payout, to check who is allowed to approve the resulting number."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "payout_amount": {"type": "number", "description": "The payout amount to check, exactly as compute_payout returned it."},
                },
                "required": ["payout_amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_subrogation_required",
            "description": (
                "Determine whether subrogation must be evaluated and referred to the Recovery "
                "unit. Does not look up coverage or compute a payout - a pure claims-procedure "
                "check, based only on the payout amount and the cause of loss."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "payout_amount": {"type": "number", "description": "The payout amount, exactly as compute_payout returned it."},
                    "cause_of_loss": {"type": "string", "description": "A short description of what caused the loss, e.g. 'contractor excavation damaged the service line'."},
                },
                "required": ["payout_amount", "cause_of_loss"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_acv_depreciation",
            "description": (
                "Compute actual cash value from a replacement cost, the roof material and the "
                "roof's age, using the depreciation schedule. Pure arithmetic - does not decide "
                "whether ACV settlement even applies to this loss (that depends on cause of "
                "loss - wind/hail only - a coverage judgment made from search_policy, not here)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "replacement_cost": {"type": "number", "description": "The replacement-cost estimate for the roof surfacing."},
                    "roof_material": {
                        "type": "string",
                        "enum": sorted(_ROOF_DEPRECIATION),
                        "description": "The roof surfacing material.",
                    },
                    "roof_age_years": {"type": "number", "description": "Age of the roof surfacing in years."},
                },
                "required": ["replacement_cost", "roof_material", "roof_age_years"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_special_sublimit",
            "description": (
                "Look up the base form's special limit of liability for one item category "
                "(e.g. jewelry, firearms, cash). Does not check whether the item is covered at "
                "all - only the sub-limit ceiling that would apply if it is, and whether that "
                "ceiling is bypassed because the item is separately scheduled."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "item_category": {
                        "type": "string",
                        "enum": sorted(_SPECIAL_SUBLIMITS),
                        "description": "The item category.",
                    },
                    "is_scheduled": {"type": "boolean", "description": "True if the item is separately scheduled under HO-2026-04."},
                },
                "required": ["item_category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "validate_denial_letter",
            "description": (
                "Check a proposed denial against CP-09's 5 hard requirements before it can be "
                "issued. Does not decide whether to deny the claim - only whether a denial, "
                "once decided, is procedurally ready to send."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "has_second_adjuster_review": {"type": "boolean"},
                    "cites_specific_paragraph": {"type": "boolean"},
                    "has_plain_language_explanation": {"type": "boolean"},
                    "has_appeal_route": {"type": "boolean"},
                    "evidence_retained": {"type": "boolean"},
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "flag_for_review",
            "description": (
                "Escalate a claim for human review instead of finishing it - the only action/"
                "write tool available; every other tool reads or computes. Use this instead of "
                "`finish` when the claim genuinely can't be resolved from the available tools."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "claim_id": {"type": "string"},
                    "reason": {"type": "string", "description": "Why this claim needs human review."},
                },
                "required": ["claim_id", "reason"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": (
                "End the task with the final triage decision. Call this only after calling "
                "compute_payout, and report exactly the numbers compute_payout returned - do "
                "not recompute or round the payout yourself."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "decision": {"type": "string", "enum": CLAIM_STATUSES, "description": "The final coverage decision."},
                    "payout": {"type": "number", "description": "The final payout amount, exactly as compute_payout returned it."},
                    "reasoning": {"type": "string", "description": "One or two sentences citing the specific policy/endorsement wording relied on. Plain text only."},
                    "sources": {"type": "array", "items": {"type": "string"}, "description": "File names actually used."},
                },
                "required": ["decision", "payout"],
            },
        },
    },
]
