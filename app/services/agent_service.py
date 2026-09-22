"""
A hand-built agent loop for claim resolution, using the chat API's own
tool-calling parameter rather than a framework (LangChain, LangGraph), per
the Week 7 brief: the loop control - which tool to try, when to stop, how a
step is logged - is all written here in plain Python, so it is never a
black box.

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
from app.services.agent_tools import TOOL_SCHEMAS, list_documents, search_policy
from app.services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)

_UNSET = object()  # distinct from a caller explicitly passing client=None

AGENT_PROMPT_VERSION = "a2"

# a1 -> a2: a1 asked the model to hand-write {"tool": ..., "args": ...} as
# plain-text JSON. Live-tested before shipping (per the same discipline as
# the Week 6 judge iterations): Groq rejected every call with "Tool choice
# is none, but model called a tool" - this model's own tool-calling
# behaviour fires regardless of whether the API was told about any tools.
# a2 declares the three tools properly via `tools=` and reads
# `message.tool_calls`, which is what the API is actually built for.

TEMPERATURE = 0.0
MAX_TOKENS_PER_CALL = 700

# openai/gpt-oss-20b has three live-observed ways of corrupting its own
# response that Groq rejects server-side before this code ever sees a
# result - all three only ever happened on the long, free-text `finish`
# call, never on the other tools' short scalar arguments:
#   - "Failed to parse tool call arguments as JSON" - the answer failed to
#     valid-JSON-encode as the argument string.
#   - "Tool call validation failed ... 'finish<|channel|>commentary' which
#     was not in request.tools" - a stray internal formatting token from the
#     model's own multi-channel response format leaks into the tool NAME.
#   - "Parsing failed. The model generated output that could not be parsed"
#     (code output_parse_failed) - the model's own internal reasoning text
#     leaked out as the entire raw response, with no tool call or clean
#     message ever produced at all.
# All three are the same underlying category (this model's "harmony"
# response format occasionally fails to close out cleanly on a longer
# synthesis, not a deterministic failure) so a couple of retries is worth it
# rather than failing the whole run - but this is itself real evidence for
# the agent-vs-workflow comparison: a fixed workflow's single free-text
# generation call has no tool-call structure to corrupt, so none of these
# three failure modes can happen to it at all.
RETRYABLE_TOOL_ERRORS = (
    "parse tool call arguments",
    "tool call validation failed",
    "could not be parsed",
    "output_parse_failed",
)
TOOL_PARSE_RETRIES = 2

# The agent uses roughly 2.5-3x the tokens of the fixed workflow (see
# results.md's race numbers), so it hits Groq's free-tier tokens-per-minute
# limit far sooner in back-to-back runs - live-observed running the race
# script twice in a row. A genuinely different problem from the three above
# (nothing is malformed; the account is just over its budget for this
# minute) so it gets its own, more patient retry: a real wait, not a
# temperature bump, and not counted against TOOL_PARSE_RETRIES.
RATE_LIMIT_RETRIES = 4
RATE_LIMIT_WAIT_S = 15

# Stop conditions - the task explicitly requires these, so each one is a
# named, checkable field on the result, not just an implicit loop bound.
DEFAULT_MAX_STEPS = 6
DEFAULT_MAX_TOKENS = 6000
DEFAULT_MAX_SECONDS = 45.0

SYSTEM_PROMPT = """
You are a claims resolution agent for Meridian Mutual. You are given a claim
description that may touch one or more endorsements, or may need a claims
procedure document, and you have to work out the full answer using the
tools available - not from memory, only from what you retrieve.

Rules:
1. Call one tool per turn.
2. Do not call `finish` until every distinct part of the claim description
   has been checked - a claim naming two endorsements needs both looked up,
   not just the first one noticed.
3. If a search returns nothing useful, try a different, more specific query
   before giving up - do not `finish` with an unsupported guess.
4. Cite sources by file name and heading in the final answer. Never invent
   a fact that did not appear in a tool result.
5. Keep the final answer brief - two or three sentences covering every part
   of the claim, not a full written report.
"""


class AgentStoppedError(Exception):
    """Raised internally when a budget is exhausted; caught to produce a clean result."""


class ClaimAgent:
    """
    Runs the think -> act -> observe loop for one claim description.
    """

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
        claim_description: str,
        max_steps: int = DEFAULT_MAX_STEPS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        max_seconds: float = DEFAULT_MAX_SECONDS,
    ) -> dict:

        if self.client is None:
            raise LLMNotConfiguredError()

        started = time.perf_counter()
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"CLAIM DESCRIPTION\n{claim_description}"},
        ]

        steps: list[dict] = []
        tokens_used = 0
        stopped_reason = "finished"
        answer = None
        sources: list[str] = []

        try:
            for step_number in range(1, max_steps + 1):

                if time.perf_counter() - started > max_seconds:
                    raise AgentStoppedError("time_limit")

                if tokens_used >= max_tokens:
                    raise AgentStoppedError("token_limit")

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
                        "step": step_number, "thought": raw_text,
                        "tool": "finish (implicit - no tool call made)",
                        "args": {}, "result": None, "latency_ms": latency_ms, "tokens": call_tokens,
                    })
                    break

                if tool_name == "finish":
                    answer = str(args.get("answer") or "").strip()
                    sources = [str(s) for s in (args.get("sources") or [])]
                    steps.append({
                        "step": step_number, "thought": raw_text, "tool": "finish", "args": args,
                        "result": None, "latency_ms": latency_ms, "tokens": call_tokens,
                    })
                    break

                steps.append({
                    "step": step_number, "thought": raw_text, "tool": tool_name, "args": args,
                    "result": result, "latency_ms": latency_ms, "tokens": call_tokens,
                })

            else:
                # The for/else fires when max_steps was exhausted without a `break`
                # (i.e. without ever calling finish) - a genuine, named stop
                # condition, not an accidental fall-through.
                stopped_reason = "step_limit"

        except AgentStoppedError as stopped:
            stopped_reason = str(stopped)
        except GroqError as error:
            logger.warning("Agent call failed: %s: %s", type(error).__name__, error)
            raise LLMUpstreamError() from error

        return {
            "claim_description": claim_description,
            "answer": answer,
            "sources": sources,
            "steps": steps,
            "step_count": len(steps),
            "tokens_used": tokens_used,
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

        response = self._create_completion(messages)

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

    def _create_completion(self, messages: list[dict]):
        """
        One call, with two independent, separately-budgeted retry paths -
        each real, live-observed, and each needing a different response:

          rate limit    the account is over its tokens-per-minute budget for
                         this minute; nothing is wrong with the request, so
                         wait a real amount of time and ask again unchanged.
          tool-call      the model itself corrupted the call (see
          corruption     RETRYABLE_TOOL_ERRORS above); waiting does not fix a
                         generation problem, so nudge the temperature instead.

        Any other error is raised immediately - this is not a general
        retry-everything loop.
        """

        last_error: GroqError | None = None

        for rate_attempt in range(RATE_LIMIT_RETRIES + 1):

            for tool_attempt in range(TOOL_PARSE_RETRIES + 1):

                # temperature=0 can reproduce the exact same corrupted tool
                # call on a bare retry - live-tested and observed happening.
                # A small bump on retry asks for a genuinely different
                # generation, without giving up the run's normal
                # determinism on the first attempt.
                retry_temperature = TEMPERATURE if tool_attempt == 0 else 0.4

                try:
                    return self.client.chat.completions.create(
                        model=settings.MODEL_NAME,
                        temperature=retry_temperature,
                        max_tokens=MAX_TOKENS_PER_CALL,
                        messages=messages,
                        tools=TOOL_SCHEMAS,
                        tool_choice="auto",
                    )
                except GroqError as error:
                    last_error = error
                    text = str(error).lower()

                    if "rate limit" in text or "429" in text:
                        break  # out of the tool-corruption loop, into the rate-limit wait below

                    retryable = any(marker in text for marker in RETRYABLE_TOOL_ERRORS)
                    if not retryable or tool_attempt == TOOL_PARSE_RETRIES:
                        raise
                    logger.info("Retrying after a malformed tool-call response (attempt %d): %s",
                                tool_attempt + 1, text[:120])
            else:
                continue  # the tool-corruption loop ran out without a rate limit - unreachable, raise above already fired

            # Reached only via the `break` above: a rate limit was hit.
            if rate_attempt == RATE_LIMIT_RETRIES:
                raise last_error

            wait = RATE_LIMIT_WAIT_S * (rate_attempt + 1)
            logger.warning("Rate limited (attempt %d/%d); waiting %ss", rate_attempt + 1, RATE_LIMIT_RETRIES, wait)
            time.sleep(wait)

        raise last_error  # pragma: no cover - loop always returns or raises above

    def _call_tool(self, tool_name: str, args: dict) -> dict:

        if tool_name == "search_policy":
            return search_policy(self.retriever, args)

        if tool_name == "list_documents":
            return list_documents(args)

        return {"error": f"Unknown tool {tool_name!r}."}
