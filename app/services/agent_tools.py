"""
The tools the merged claim agent can call: general policy Q&A tools
(`search_policy`, `list_documents`) plus the claim-triage tools that used to
live in a separate `triage_tools.py` before `ClaimAgent`/`ClaimTriageAgent`
were merged into one class - `get_claim`, `compute_payout`, and six further
tools grounded in real tables in the indexed documents.

Every tool function takes a single `args: dict` and returns a small dict the
agent logs and feeds back into the next prompt. A tool never raises for a
bad but plausible call - it returns an error string in the result instead,
so a single bad tool call costs one step, not the whole run.

The merge restores `search_policy`'s description to reference `list_documents`
again for file-name discovery - the triage-only version of this file had
rewritten that reference away, since the triage agent never had
`list_documents` before. Now it does, so the original wording applies again.
The `_resolve_source` fix (below) still stays regardless: it protects
against a guessed name whether or not `list_documents` was actually called.
"""

from app.core.config import settings
from app.services.claims_data import get_claim_record
from app.services.document_loader import SUPPORTED_EXTENSIONS
from app.services.retrieval_service import RetrievalService

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


# Tool schemas in the OpenAI/Groq function-calling shape. This model
# (openai/gpt-oss-20b) has a built-in, server-enforced notion of "the model
# called a tool" - asking it to hand-write tool-shaped JSON as plain text
# collides with that (Groq rejects it: "Tool choice is none, but model
# called a tool") rather than just being parsed as text. Declaring the
# tools properly through `tools=` and reading `message.tool_calls` uses the
# API the way it is actually built, instead of fighting it.
#
# `finish` is unified across both jobs this agent can do: a pure policy
# question leaves `decision`/`payout` null; a claim triage fills them in and
# still writes a prose `answer` restating the decision. One contract, two
# legitimate shapes of its content - not two contracts.
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_policy",
            "description": (
                "Search the indexed policy and procedure documents for text relevant to "
                "the query. Never returns claim-specific facts (amount, notes, peril) - that "
                "is get_claim's job. Leave `source` unset to search everything. Set `source` "
                "to one exact file name (from list_documents) only once you already suspect "
                "the fact you need lives in that specific document - for example, once you "
                "suspect the answer depends on settlement authority or claims procedure "
                "rather than an endorsement."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look up."},
                    "source": {"type": "string", "description": "An exact file name to restrict the search to, or omit to search everything."},
                    "top_k": {"type": "integer", "description": "How many chunks to return, default 5."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_documents",
            "description": "List the exact file names of every indexed document, so a later search_policy call can name a document that actually exists.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_claim",
            "description": (
                "Retrieve the case file for ONE claim by its claim ID: claimed amount, "
                "policy form and endorsements attached, and the adjuster's notes describing "
                "what happened. This is the only tool that returns claim-specific facts - it "
                "never returns policy wording, exclusions or deductible amounts. Only call "
                "this when the input actually names a claim ID (CLM-####) - never for a "
                "general policy question with no claim to pull. Call it exactly once per "
                "claim, first."
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
                "Only relevant when triaging a specific claim (never for a general policy "
                "question). Call this only after you already know, from search_policy, "
                "whether the loss is covered and what deductible applies - this tool does no "
                "coverage lookups of its own, it only does the arithmetic once you supply the "
                "numbers."
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
                "End the task with the final answer. For a general policy question, leave "
                "`decision` and `payout` unset. For a claim triage, call this only after "
                "compute_payout and report exactly the numbers compute_payout returned - do "
                "not recompute or round the payout yourself, and still write a prose `answer` "
                "restating the decision. Keep `answer` to two or three sentences."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {
                        "type": "string",
                        "description": (
                            "The final answer, citing sources by file name and heading. "
                            "PLAIN TEXT ONLY - no markdown, no bold, no bullet points, no "
                            "line breaks, so the answer stays valid as one JSON string."
                        ),
                    },
                    "decision": {
                        "type": "string",
                        "enum": CLAIM_STATUSES,
                        "description": "Only for a claim triage: the final coverage decision. Leave unset for a general policy question.",
                    },
                    "payout": {
                        "type": "number",
                        "description": "Only for a claim triage: the final payout amount, exactly as compute_payout returned it. Leave unset for a general policy question.",
                    },
                    "sources": {"type": "array", "items": {"type": "string"}, "description": "File names actually used."},
                },
                "required": ["answer"],
            },
        },
    },
]
