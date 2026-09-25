"""
The Task Set D extension's agent: same hand-built loop shape as
agent_service.py's ClaimAgent (think -> act -> observe until `finish` or a
budget runs out), retargeted at claim triage - pull the claim record, check
policy exclusions, compute the payout - with a third tool (compute_payout)
added and all four of the task's required budgets enforced explicitly:
max iterations, max tokens, max cost, wall-clock.

See app/services/triage_tools.py for why get_claim and search_policy don't
overlap, and why compute_payout is a single-purpose, enum-parameterised
addition rather than folded into either existing tool.
"""

import json
import logging
import time

from groq import Groq, GroqError

from app.core.config import settings
from app.core.errors import LLMNotConfiguredError, LLMUpstreamError
from app.services.agent_tools import search_policy
from app.services.groq_retry import create_completion_with_retry
from app.services.retrieval_service import RetrievalService
from app.services.triage_tools import (
    CLAIM_STATUSES,
    TRIAGE_TOOL_SCHEMAS,
    calculate_acv_depreciation,
    check_settlement_authority,
    check_subrogation_required,
    compute_payout,
    flag_for_review,
    get_claim,
    get_special_sublimit,
    validate_denial_letter,
)

logger = logging.getLogger(__name__)

_UNSET = object()  # distinct from a caller explicitly passing client=None

TRIAGE_AGENT_PROMPT_VERSION = "t1"

TEMPERATURE = 0.0
MAX_TOKENS_PER_CALL = 700

# Approximate, blended $/token used only to compare the two systems' relative
# cost in this race - not Groq's exact published billing rate, and stated as
# an assumption rather than a fact for that reason.
ASSUMED_COST_PER_MILLION_TOKENS = 0.20

# All four budgets the task requires, each a named, checkable field on the
# result - not just an implicit loop bound.
DEFAULT_MAX_ITERATIONS = 8

# Live-tested: a real 4-turn run (get_claim, 2 searches, compute_payout)
# already used ~6750 tokens before ever reaching `finish` - averaging closer
# to 1700 tokens/turn than the ~1000 Week 7's simpler policy-QA agent saw,
# since every turn here carries a larger case file plus retrieved passages.
# 6000 cut a correct run off one turn short of finishing; raised to give a
# full 8-iteration run room without silently truncating a right answer.
DEFAULT_MAX_TOKENS = 14000
DEFAULT_MAX_COST_USD = 0.01

# Live bug, full 10-claim race: 45s sounds generous for a handful of model
# calls, but the wall-clock check only runs between iterations, so a single
# call stuck retrying inside groq_retry.py (a rate-limit wait alone can be
# 15-60s, on top of normal ~10-15s call latency) can blow straight through
# it before the loop gets a chance to stop cleanly - 4 of 10 claims in one
# race hit "time_limit" this way despite the underlying reasoning being
# fine. Raised to give room for one real retry without turning this into a
# no-op budget; still short enough to catch a genuinely stuck run.
DEFAULT_MAX_SECONDS = 180.0

SYSTEM_PROMPT = f"""
You are a claims triage agent for Meridian Mutual. You are given a claim ID
and must decide the coverage outcome and the payout, using only the tools
available - never from memory or assumption.

Rules:
1. Call one tool per turn.
2. Always call get_claim first, to see the claimed amount, the policy form
   and endorsements attached, and the adjuster's notes. The notes often
   contain the one fact (the true cause of loss, an age, a warranty, a
   scheduled item) that changes which exclusion or deductible applies - read
   them closely before deciding what to search for.
3. Use search_policy to check whether the loss is covered and what
   deductible/excess applies, citing the specific document and heading. If a
   search returns nothing useful, try a more specific query before giving up.
4. Call compute_payout only after you have decided the coverage outcome
   (one of {CLAIM_STATUSES}) and the correct excess amount from step 3.
5. Further tools are available for specific situations - use them only when
   the claim actually calls for it, not on every claim:
   - check_settlement_authority, after compute_payout, if the payout is
     large enough that who can approve it matters.
   - check_subrogation_required if a third party (a contractor, a utility, a
     manufacturer) may be responsible for the loss.
   - calculate_acv_depreciation only for a roof loss where search_policy
     confirms the cause of loss is wind or hail (never for any other cause).
   - get_special_sublimit for a claim naming a specific high-value item
     category (jewelry, firearms, cash, etc.) that is not separately
     scheduled.
   - validate_denial_letter before finishing a "denied" decision that will
     be sent as a formal denial letter.
   - flag_for_review, instead of finish, only if the claim genuinely cannot
     be resolved from the tools available (contradictory notes, a document
     the corpus doesn't have) - not as a shortcut to avoid deciding.
6. Call `finish` only after compute_payout, reporting exactly the numbers it
   returned - do not recompute or round the payout yourself.
"""


class AgentStoppedError(Exception):
    """Raised internally when a budget is exhausted; caught to produce a clean result."""


class ClaimTriageAgent:
    """Runs the think -> act -> observe loop for one claim ID."""

    def __init__(self, retriever: RetrievalService | None = None, client=_UNSET):

        self.retriever = retriever or RetrievalService()
        self.client = (
            (Groq(api_key=settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None)
            if client is _UNSET else client
        )

    def run(
        self,
        claim_id: str,
        max_iterations: int = DEFAULT_MAX_ITERATIONS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_cost_usd: float = DEFAULT_MAX_COST_USD,
        max_seconds: float = DEFAULT_MAX_SECONDS,
    ) -> dict:

        if self.client is None:
            raise LLMNotConfiguredError()

        started = time.perf_counter()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"CLAIM ID\n{claim_id}"},
        ]

        steps: list[dict] = []
        tokens_used = 0
        stopped_reason = "finished"
        decision = None
        payout = None
        reasoning = ""
        sources: list[str] = []

        try:
            for iteration in range(1, max_iterations + 1):

                if time.perf_counter() - started > max_seconds:
                    raise AgentStoppedError("time_limit")

                if tokens_used >= max_tokens:
                    raise AgentStoppedError("token_limit")

                cost_so_far = tokens_used / 1_000_000 * ASSUMED_COST_PER_MILLION_TOKENS
                if cost_so_far >= max_cost_usd:
                    raise AgentStoppedError("cost_limit")

                step_started = time.perf_counter()
                tool_name, args, result, raw_text, call_tokens = self._next_action(messages)
                tokens_used += call_tokens
                latency_ms = int((time.perf_counter() - step_started) * 1000)

                if tool_name is None:
                    # Answered in plain text instead of calling a tool -
                    # treated as an implicit, unfinished stop: there is no
                    # structured decision/payout to report, so this is
                    # logged, not silently accepted as success.
                    steps.append({
                        "step": iteration, "thought": raw_text,
                        "tool": "none (no tool call made)",
                        "args": {}, "result": None, "latency_ms": latency_ms, "tokens": call_tokens,
                    })
                    raise AgentStoppedError("no_tool_call")

                if tool_name == "finish":
                    decision = str(args.get("decision") or "").strip().lower()
                    payout = args.get("payout")
                    reasoning = str(args.get("reasoning") or "").strip()
                    sources = [str(s) for s in (args.get("sources") or [])]
                    steps.append({
                        "step": iteration, "thought": raw_text, "tool": "finish", "args": args,
                        "result": None, "latency_ms": latency_ms, "tokens": call_tokens,
                    })
                    break

                steps.append({
                    "step": iteration, "thought": raw_text, "tool": tool_name, "args": args,
                    "result": result, "latency_ms": latency_ms, "tokens": call_tokens,
                })

                if tool_name == "flag_for_review":
                    # A second, deliberate way to end the loop besides
                    # `finish` - the claim isn't decided, it's handed off.
                    # decision="escalated" is distinct from any CLAIM_STATUSES
                    # value so a caller can't mistake this for a real
                    # coverage outcome.
                    decision = "escalated"
                    reasoning = str(args.get("reason") or "").strip()
                    break

            else:
                # for/else fires when max_iterations was exhausted without a
                # `break` (i.e. without ever calling finish).
                stopped_reason = "iteration_limit"

        except AgentStoppedError as stopped:
            stopped_reason = str(stopped)
        except GroqError as error:
            logger.warning("Triage agent call failed: %s: %s", type(error).__name__, error)
            upstream_error = LLMUpstreamError()
            # Attaches whatever steps/tokens were already accrued before the
            # hard failure - a live full-race run hit this mid-claim (Groq's
            # daily token cap) and the caught exception's fallback had no way
            # to show what the run actually did up to that point, purely
            # because this information was discarded on the way up.
            upstream_error.steps = steps
            upstream_error.tokens_used = tokens_used
            raise upstream_error from error

        cost_usd = round(tokens_used / 1_000_000 * ASSUMED_COST_PER_MILLION_TOKENS, 6)

        return {
            "claim_id": claim_id,
            "decision": decision,
            "payout": payout,
            "reasoning": reasoning,
            "sources": sources,
            "steps": steps,
            "step_count": len(steps),
            "tokens_used": tokens_used,
            "cost_usd": cost_usd,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "stopped_reason": stopped_reason,
            "finished": decision is not None,
            "agent_prompt_version": TRIAGE_AGENT_PROMPT_VERSION,
        }

    def _next_action(self, messages: list[dict]) -> tuple[str | None, dict, dict | None, str, int]:

        response = create_completion_with_retry(
            self.client, model=settings.MODEL_NAME, messages=messages,
            tools=TRIAGE_TOOL_SCHEMAS, temperature=TEMPERATURE, max_tokens=MAX_TOKENS_PER_CALL,
        )

        message = response.choices[0].message
        tokens = response.usage.total_tokens if response.usage else 0
        tool_calls = getattr(message, "tool_calls", None) or []

        if not tool_calls:
            messages.append({"role": "assistant", "content": message.content or ""})
            return None, {}, None, message.content or "", tokens

        # One action per turn, even if the model offered several.
        call = tool_calls[0]

        try:
            args = json.loads(call.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}

        messages.append({
            "role": "assistant", "content": message.content or "",
            "tool_calls": [{
                "id": call.id, "type": "function",
                "function": {"name": call.function.name, "arguments": call.function.arguments},
            }],
        })

        result = None

        if call.function.name != "finish":
            result = self._call_tool(call.function.name, args)
            messages.append({
                "role": "tool", "tool_call_id": call.id,
                "content": json.dumps(result, ensure_ascii=False)[:2000],
            })

        return call.function.name, args, result, message.content or "", tokens

    def _call_tool(self, tool_name: str, args: dict) -> dict:

        if tool_name == "get_claim":
            return get_claim(args)

        if tool_name == "search_policy":
            return search_policy(self.retriever, args)

        if tool_name == "compute_payout":
            return compute_payout(args)

        if tool_name == "check_settlement_authority":
            return check_settlement_authority(args)

        if tool_name == "check_subrogation_required":
            return check_subrogation_required(args)

        if tool_name == "calculate_acv_depreciation":
            return calculate_acv_depreciation(args)

        if tool_name == "get_special_sublimit":
            return get_special_sublimit(args)

        if tool_name == "validate_denial_letter":
            return validate_denial_letter(args)

        if tool_name == "flag_for_review":
            return flag_for_review(args)

        return {"error": f"Unknown tool {tool_name!r}."}
