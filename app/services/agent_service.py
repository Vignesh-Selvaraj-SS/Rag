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

Week 9: this agent's tools are no longer wired in by hand. Every tool
except `finish` (the agent's own loop-control signal, never a claims-system
capability - see FINISH_SCHEMA) is discovered at the start of every run()
call from the claims-system MCP server (mcp_servers/claims_system_server.py)
over app/services/mcp_client.py, and every tool call is dispatched
generically through that same client - see _tools_for and _call_tool. The
host (this process, running the LLM) never runs on the tool server; the
server only ever executes deterministic lookups/arithmetic, the same
functions this file used to import and call directly.
"""

import json
import logging
import time

from groq import Groq, GroqError

from app.core.config import settings
from app.core.errors import LLMNotConfiguredError, LLMUpstreamError
from app.services.agent_tools import CLAIM_ID_PATTERN, CLAIM_STATUSES
from app.services.groq_retry import create_completion_with_retry
from app.services.mcp_client import MCPToolRegistry

logger = logging.getLogger(__name__)

_UNSET = object()  # distinct from a caller explicitly passing client=None

# a1/t1 (the two pre-merge prompt versions) -> m1 -> m2: m1 sent one prompt
# covering both jobs, plus all 11 tool schemas, on every single turn -
# roughly double the per-call cost of either original agent. A live run on
# CLM-2001 (previously a simple, 4-step claim) burned 17,204 tokens across 5
# steps and hit token_limit without ever finishing. m2 scopes both the
# prompt and the tool schemas by input shape (see CLAIM_ID_PATTERN in
# agent_tools.py) - one class, one run() method, but each call only pays for
# the job it's actually doing.
AGENT_PROMPT_VERSION = "m2"

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
#
# Raised again after two live CLM-2001 runs (14,539 and 14,204 tokens) both
# hit 14000 on a legitimate, non-redundant 5-step trajectory - one call
# short of `finish`. Per-turn cost climbs late in a run because the whole
# growing transcript is resent every call, so a 6th call lands ~15,000-
# 15,200. 18000 covers a correct 6-step run plus a claim needing one extra
# tool (subrogation/ACV/sublimit), without immediately re-hitting the wall.
DEFAULT_MAX_TOKENS = 1800000
DEFAULT_MAX_COST_USD = 0.01

# Live bug, full 10-claim race: 45s sounds generous for a handful of model
# calls, but the wall-clock check only runs between iterations, so a single
# call stuck retrying inside groq_retry.py (a rate-limit wait alone can be
# 15-60s, on top of normal ~10-15s call latency) can blow straight through
# it before the loop gets a chance to stop cleanly. Raised to give room for
# one real retry without turning this into a no-op budget; still short
# enough to catch a genuinely stuck run.
DEFAULT_MAX_SECONDS = 180.0

# Which prompt/tool subset a call gets is decided once, in run(), by a
# deterministic regex check on the input (CLAIM_ID_PATTERN) - not by asking
# the model to infer it from a combined prompt covering both jobs. That
# combined-prompt design (m1) was the actual cause of the token-budget
# regression described above; the model never had trouble telling the two
# jobs apart once given get_claim, it just paid for both jobs' instructions
# and tools on every call it made either way.

# Week 9: the tool SCHEMAS themselves now come from live MCP discovery
# (self.mcp_client.list_tool_schemas(), in _tools_for below) instead of a
# hard-coded dict - but a general policy question still shouldn't be
# offered get_claim/compute_payout/etc., which is a business-scoping
# decision, not "hard-coding a tool." Triage gets every tool the
# claims-system MCP server discovers, unfiltered - the literal "add a
# second tool without touching the agent's code" property: a new
# @mcp.tool function added to mcp_servers/claims_system_server.py shows up
# here on the very next call, with zero edits to this file.
QUESTION_TOOL_NAMES = {"search_policy", "list_documents"}

# `finish` is not a claims-system capability - it is this agent's own
# loop-control signal (see run()'s handling of it) - so it is never
# exposed over MCP, and stays a local, hand-written schema. Unified across
# both jobs: a pure policy question leaves `decision`/`payout` null; a
# claim triage fills them in and still writes a prose `answer` restating
# the decision. One contract, two legitimate shapes of its content.
FINISH_SCHEMA = {
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
}

QUESTION_SYSTEM_PROMPT = """
You are a claims assistant for Meridian Mutual, answering a general policy
question from the policy documents alone.

Rules:
1. Call one tool per turn.
2. Do not call `finish` until every distinct part of the question has been
   checked - a question naming two endorsements needs both looked up, not
   just the first one noticed.
3. If a search returns nothing useful, try a different, more specific query
   before giving up - do not `finish` with an unsupported guess.
4. Cite sources by file name and heading. Never invent a fact that did not
   appear in a tool result. Leave `decision` and `payout` unset.
5. Keep the final answer brief - two or three sentences.
"""

TRIAGE_SYSTEM_PROMPT = f"""
You are a claims assistant for Meridian Mutual, triaging one specific claim:
decide the coverage outcome and the payout, using only the tools available.

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
   (one of {CLAIM_STATUSES}) and the correct excess amount.
5. Further tools are available for specific situations - use them only when
   the claim actually calls for it, not on every claim:
   - check_settlement_authority, after compute_payout, if the payout is
     large enough that who can approve it matters.
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

    def __init__(self, client=_UNSET, mcp_client=None):

        # client=_UNSET (the default) builds the real client from settings;
        # client=None explicitly forces "not configured" - tests need to be
        # able to say that even when a real GROQ_API_KEY is set in .env.
        self.client = (
            (Groq(api_key=settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None)
            if client is _UNSET else client
        )
        # Week 9 Task Set D: reads mcp_config.json's server list - not a
        # single URL - so adding server two is a config-file edit, never a
        # change here. This line, and everything below it in this file, is
        # the "server one" baseline agent_diff.txt proves stays byte-for-
        # byte identical once server two is added.
        self.mcp_client = mcp_client or MCPToolRegistry()

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

        is_triage = bool(CLAIM_ID_PATTERN.match(user_input.strip()))
        tools = self._tools_for(is_triage)
        system_prompt = TRIAGE_SYSTEM_PROMPT if is_triage else QUESTION_SYSTEM_PROMPT

        started = time.perf_counter()
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input},
        ]

        steps: list[dict] = []
        tokens_used = 0
        stopped_reason = "finished"
        answer = None
        decision = None
        payout = None
        sources: list[str] = []
        compute_payout_called = False

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
                tool_name, args, result, raw_text, call_tokens, call_id = self._next_action(messages, tools)
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
                    proposed_decision = str(args["decision"]).strip().lower() if args.get("decision") else None

                    # Mitigation for the "skipped_required_tool" failure mode
                    # (live-observed on CLM-2003/CLM-2004: the model finished
                    # a triage claim - decision and payout both set - having
                    # never called compute_payout at all, asserting the
                    # payout instead of computing it). Rejected exactly like
                    # a bad tool call already is: a role:tool error message
                    # goes back, and the loop continues rather than accepting
                    # an incomplete trajectory as done.
                    if proposed_decision is not None and not compute_payout_called:
                        steps.append({
                            "step": iteration, "thought": raw_text,
                            "tool": "finish (rejected - compute_payout not yet called)", "args": args,
                            "result": None, "latency_ms": latency_ms, "tokens": call_tokens,
                        })
                        messages.append({
                            "role": "tool", "tool_call_id": call_id,
                            "content": json.dumps({
                                "error": "finish was rejected: you set a coverage decision without ever "
                                         "calling compute_payout. Call compute_payout now, then call finish "
                                         "again immediately, reporting exactly the numbers it returned. Do "
                                         "not call any other tool in between - every other fact you need, "
                                         "you already have from earlier steps.",
                            }),
                        })
                        continue

                    answer = str(args.get("answer") or "").strip()
                    decision = proposed_decision
                    payout = args.get("payout")
                    sources = [str(s) for s in (args.get("sources") or [])]
                    steps.append({
                        "step": iteration, "thought": raw_text, "tool": "finish", "args": args,
                        "result": None, "latency_ms": latency_ms, "tokens": call_tokens,
                    })
                    break

                if tool_name == "compute_payout" and result and "error" not in result:
                    compute_payout_called = True

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

    def _next_action(self, messages: list[dict], tools: list[dict]) -> tuple[str | None, dict, dict | None, str, int, str | None]:
        """
        One model call. Returns (tool_name, args, result, raw_text, tokens,
        call_id): `result` is the executed tool's return value (None for
        `finish`, and meaningless when tool_name is None). `call_id` is the
        tool call's id (None when no tool call was made) - run() needs it to
        append a rejection message if it decides a `finish` call is invalid
        (see the compute_payout precondition there) without which the API's
        "every tool_call needs a matching tool-role reply" rule would be
        violated on the next call. Mutates `messages` in place with the
        assistant turn and, if a tool other than `finish` was called, the
        matching `role: tool` result message the API requires before the
        next call. `tools` is the job-scoped subset run() picked - see
        AGENT_PROMPT_VERSION's m2 comment for why this isn't TOOL_SCHEMAS.
        """

        response = create_completion_with_retry(
            self.client, model=settings.MODEL_NAME, messages=messages,
            tools=tools, temperature=TEMPERATURE, max_tokens=MAX_TOKENS_PER_CALL,
        )

        message = response.choices[0].message
        tokens = response.usage.total_tokens if response.usage else 0
        tool_calls = getattr(message, "tool_calls", None) or []

        if not tool_calls:
            messages.append({"role": "assistant", "content": message.content or ""})
            return None, {}, None, message.content or "", tokens, None

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

        return call.function.name, args, result, message.content or "", tokens, call.id

    def _tools_for(self, is_triage: bool) -> list[dict]:
        """
        Discovers the claims-system server's current tool set over MCP -
        not a hard-coded list - then adds the local `finish` schema. Triage
        gets every discovered tool unfiltered (see QUESTION_TOOL_NAMES's
        comment above for why a policy question gets a curated subset
        instead): this is the actual "add a second tool without touching
        the agent's code" property, exercised end to end by
        test_triage_tools_include_a_brand_new_mcp_tool_with_no_code_change.
        """

        discovered = self.mcp_client.list_tool_schemas()

        if is_triage:
            tools = discovered
        else:
            tools = [schema for schema in discovered if schema["function"]["name"] in QUESTION_TOOL_NAMES]

        return tools + [FINISH_SCHEMA]

    def _call_tool(self, tool_name: str, args: dict) -> dict:
        """
        Every non-`finish` tool call, generic by construction: whatever
        name and args the model produced go straight to the MCP server -
        there is no per-tool branch here to update when a tool is added,
        renamed or removed on the server side.
        """

        return self.mcp_client.call_tool(tool_name, args)
