"""
A hand-built agent loop for Meridian Mutual claims, using the chat API's own
tool-calling parameter rather than a framework (LangChain, LangGraph), per
the Week 7 brief: the loop control - which tool to try, when to stop, how a
step is logged - is all written here in plain Python, so it is never a
black box.

Originally two separate classes - `ClaimAgent` (free-text policy Q&A, 3
tools) and `ClaimTriageAgent` (claim-ID triage, 9 tools) - merged into this
one class to cut the duplication between them. The agent now tells the two
jobs apart from the input itself (a claim-ID-shaped input vs. a general
question), not from a caller-supplied flag; see SYSTEM_PROMPT for the one
piece of real judgment this requires and why it matters (a live trace,
asking the pre-merge ClaimAgent "CLM-2001" as if it were a policy question,
showed exactly what goes wrong without this rule - see the comment there).

The loop, in one sentence: ask the model for ONE tool call, run it, feed the
result back as a `role: tool` message, ask again - until it calls `finish`
or a budget runs out. This is the "ReAct" pattern (Reason + Act): the
model's own tool-call arguments are logged on every turn specifically so a
person reading the log can see what it decided and why.

Why native tool-calling, not "reply with JSON in your message text": tried
that first, and Groq rejected it - `openai/gpt-oss-20b` has a built-in,
server-enforced notion of calling a tool, and asking it to hand-write
tool-shaped JSON as plain text collides with that ("Tool choice is none,
but model called a tool") instead of just being parsed as text. Declaring
the tools through `tools=` and reading `message.tool_calls` uses the API
the way it is actually built.

Every run returns the full list of steps, never just the final answer - the
Week 7 mentor check is "are the steps visible," and a result object with no
step log fails that regardless of what the final answer says.
"""

import json
import logging
import time

from groq import Groq, GroqError

from app.core.config import settings
from app.core.errors import LLMNotConfiguredError, LLMUpstreamError
from app.services.agent_tools import (
    CLAIM_STATUSES,
    TOOL_SCHEMAS,
    calculate_acv_depreciation,
    check_settlement_authority,
    check_subrogation_required,
    compute_payout,
    flag_for_review,
    get_claim,
    get_special_sublimit,
    list_documents,
    search_policy,
    validate_denial_letter,
)
from app.services.groq_retry import create_completion_with_retry
from app.services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)

_UNSET = object()  # distinct from a caller explicitly passing client=None

# a1/t1 (the two pre-merge prompt versions) -> m1: one prompt covering both
# jobs, with an explicit input-shape routing rule neither predecessor needed
# on its own.
AGENT_PROMPT_VERSION = "m1"

TEMPERATURE = 0.0
MAX_TOKENS_PER_CALL = 700

# Approximate, blended $/token used only to compare systems' relative cost -
# not Groq's exact published billing rate, stated as an assumption for that
# reason.
ASSUMED_COST_PER_MILLION_TOKENS = 0.20

# All four budgets, each a named, checkable field on the result - not just
# an implicit loop bound.
DEFAULT_MAX_ITERATIONS = 8

# Live-tested (on the triage-flavoured, more tool-heavy runs): a real 4-turn
# run (get_claim, 2 searches, compute_payout) already used ~6750 tokens
# before ever reaching `finish`, averaging closer to 1700 tokens/turn than a
# plain policy question's ~1000, since every turn here can carry a larger
# case file plus retrieved passages. 6000 cut a correct run off one turn
# short of finishing; raised to give a full 8-iteration run room without
# silently truncating a right answer.
DEFAULT_MAX_TOKENS = 14000
DEFAULT_MAX_COST_USD = 0.01

# Live bug, full 10-claim race: 45s sounds generous for a handful of model
# calls, but the wall-clock check only runs between iterations, so a single
# call stuck retrying inside groq_retry.py (a rate-limit wait alone can be
# 15-60s, on top of normal ~10-15s call latency) can blow straight through
# it before the loop gets a chance to stop cleanly. Raised to give room for
# one real retry without turning this into a no-op budget; still short
# enough to catch a genuinely stuck run.
DEFAULT_MAX_SECONDS = 180.0

SYSTEM_PROMPT = f"""
You are a claims assistant for Meridian Mutual. You handle two different
kinds of request, and you must tell them apart from the input itself, not
from any label the caller gives you:

- A general policy question (no claim ID mentioned) - answer it from the
  policy documents alone. Never call get_claim or compute_payout for this.
- A specific claim to triage - the input names a claim ID in the form
  CLM-#### (e.g. "CLM-2001"). Pull the claim record first, investigate, and
  decide the coverage outcome and payout.

Live bug this rule exists to prevent: before this agent had get_claim at
all, asking it "CLM-2001" as if it were a policy question made it search
for the literal string "CLM-2001", get nothing useful, reformulate the same
dead-end query four more times, and burn its entire token budget without
ever finishing. The fix is not a smarter search - it is recognizing a claim
ID and switching to the triage tools instead of treating everything as a
document-search problem.

Rules for a policy question:
1. Call one tool per turn.
2. Do not call `finish` until every distinct part of the question has been
   checked - a question naming two endorsements needs both looked up, not
   just the first one noticed.
3. If a search returns nothing useful, try a different, more specific query
   before giving up - do not `finish` with an unsupported guess.
4. Cite sources by file name and heading. Never invent a fact that did not
   appear in a tool result. Leave `decision` and `payout` unset.
5. Keep the final answer brief - two or three sentences.

Rules for a claim triage:
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
   (one of {CLAIM_STATUSES}) and the correct excess amount.
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
   returned - do not recompute or round the payout yourself, and still
   write a prose `answer` restating the decision.
"""


class AgentStoppedError(Exception):
    """Raised internally when a budget is exhausted; caught to produce a clean result."""


class ClaimAgent:
    """Runs the think -> act -> observe loop for one input - a policy question or a claim ID."""

    def __init__(self, retriever: RetrievalService | None = None, client=_UNSET):

        self.retriever = retriever or RetrievalService()
        # client=_UNSET (the default) builds the real client from settings;
        # client=None explicitly forces "not configured" - tests need to be
        # able to say that even when a real GROQ_API_KEY is set in .env.
        self.client = (
            (Groq(api_key=settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None)
            if client is _UNSET else client
        )

    def run(
        self,
        user_input: str,
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
            {"role": "user", "content": user_input},
        ]

        steps: list[dict] = []
        tokens_used = 0
        stopped_reason = "finished"
        answer = None
        decision = None
        payout = None
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
                    # The model answered in plain text instead of calling a
                    # tool (e.g. it thinks it is already done). Treated as
                    # an implicit finish rather than forced to retry, since
                    # nothing useful is served by demanding a tool call the
                    # model has no reason to make.
                    answer = raw_text.strip()
                    steps.append({
                        "step": iteration, "thought": raw_text,
                        "tool": "finish (implicit - no tool call made)",
                        "args": {}, "result": None, "latency_ms": latency_ms, "tokens": call_tokens,
                    })
                    break

                if tool_name == "finish":
                    answer = str(args.get("answer") or "").strip()
                    decision = (str(args["decision"]).strip().lower() if args.get("decision") else None)
                    payout = args.get("payout")
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
                    reason = str(args.get("reason") or "").strip()
                    decision = "escalated"
                    answer = f"Escalated for human review: {reason}"
                    break

            else:
                # for/else fires when max_iterations was exhausted without a
                # `break` (i.e. without ever calling finish).
                stopped_reason = "iteration_limit"

        except AgentStoppedError as stopped:
            stopped_reason = str(stopped)
        except GroqError as error:
            logger.warning("Agent call failed: %s: %s", type(error).__name__, error)
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
            "user_input": user_input,
            "answer": answer,
            "decision": decision,
            "payout": payout,
            "sources": sources,
            "steps": steps,
            "step_count": len(steps),
            "tokens_used": tokens_used,
            "cost_usd": cost_usd,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "stopped_reason": stopped_reason,
            "finished": answer is not None,
            "agent_prompt_version": AGENT_PROMPT_VERSION,
        }

    def _next_action(self, messages: list[dict]) -> tuple[str | None, dict, dict | None, str, int]:
        """
        One model call. Returns (tool_name, args, result, raw_text, tokens):
        `result` is the executed tool's return value (None for `finish`, and
        meaningless when tool_name is None). Mutates `messages` in place
        with the assistant turn and, if a tool other than `finish` was
        called, the matching `role: tool` result message the API requires
        before the next call.
        """

        response = create_completion_with_retry(
            self.client, model=settings.MODEL_NAME, messages=messages,
            tools=TOOL_SCHEMAS, temperature=TEMPERATURE, max_tokens=MAX_TOKENS_PER_CALL,
        )

        message = response.choices[0].message
        tokens = response.usage.total_tokens if response.usage else 0
        tool_calls = getattr(message, "tool_calls", None) or []

        if not tool_calls:
            messages.append({"role": "assistant", "content": message.content or ""})
            return None, {}, None, message.content or "", tokens

        # One action per turn: only the first tool call is executed, even
        # if the model offered several - keeps one step meaning one action,
        # which is what the visible step log promises.
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

        if tool_name == "search_policy":
            return search_policy(self.retriever, args)

        if tool_name == "list_documents":
            return list_documents(args)

        if tool_name == "get_claim":
            return get_claim(args)

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
