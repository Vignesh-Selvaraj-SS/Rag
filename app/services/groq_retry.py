"""
The Groq retry dance, shared by both agent_service.py's ClaimAgent and
fixed_claim_workflow.py's FixedClaimWorkflow - originally written once for
the (since-merged) triage-only agent/workflow pair, then adopted by the
original policy-QA pair too when the two agents were merged into one class,
replacing an older, separately-maintained copy of the same logic.

Two independently-budgeted retry paths, both live-observed on this model
(openai/gpt-oss-20b) during Week 7, not hypothetical:

  rate limit      the account is over its tokens-per-minute budget for this
                  minute; nothing is wrong with the request, so wait a real
                  amount of time and ask again unchanged.
  tool-call       the model itself corrupted the call (a long free-text
  corruption      answer failing to valid-JSON-encode, a stray formatting
                  token leaking into the tool name, or raw reasoning text
                  leaking out unparsed); waiting doesn't fix a generation
                  problem, so nudge the temperature instead.

`tools=None` covers the fixed workflows' single free-text call - it never
sees a tool-call-corruption error by construction, but rate limits can still
happen to it, so it goes through the same wrapper rather than a separate one.
"""

import logging
import time

from groq import GroqError

logger = logging.getLogger(__name__)

RETRYABLE_TOOL_ERRORS = (
    "parse tool call arguments",
    "tool call validation failed",
    "could not be parsed",
    "output_parse_failed",
)
# 2 (Week 7's original figure) wasn't enough for the triage task: a live run
# on CLM-2010 hit "output_parse_failed" 3 times in a row, even with the
# temperature bump on each retry, and only then gave up - this task's
# citation-heavy `finish` answers (citing specific documents and headings
# for a payout decision) apparently strain the same "harmony" formatting
# failure mode harder than Week 7's shorter policy-QA answers did.
TOOL_PARSE_RETRIES = 4
RATE_LIMIT_RETRIES = 4
RATE_LIMIT_WAIT_S = 15


def create_completion_with_retry(
    client,
    model: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_choice: str | None = None,
    temperature: float = 0.0,
    max_tokens: int = 700,
):

    last_error: GroqError | None = None

    kwargs = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if tools is not None:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = tool_choice or "auto"

    for rate_attempt in range(RATE_LIMIT_RETRIES + 1):

        for tool_attempt in range(TOOL_PARSE_RETRIES + 1):

            # temperature=0 can reproduce the exact same corrupted tool call
            # on a bare retry - live-tested and observed happening. A live
            # full-race run also found a flat 0.4 on every retry wasn't
            # always enough either: two claims reproduced the identical
            # corruption through every one of 4 retries at 0.4 and still
            # failed. Escalating (0.4, 0.6, 0.8, 1.0, ...) asks for a
            # progressively more different generation instead of repeatedly
            # asking the same "slightly less deterministic" question.
            retry_temperature = temperature if tool_attempt == 0 else min(1.0, max(temperature, 0.4) + 0.2 * (tool_attempt - 1))

            try:
                return client.chat.completions.create(temperature=retry_temperature, **kwargs)
            except GroqError as error:
                last_error = error
                text = str(error).lower()

                if "rate limit" in text or "429" in text:
                    break  # out of the tool-corruption loop, into the rate-limit wait below

                retryable = tools is not None and any(marker in text for marker in RETRYABLE_TOOL_ERRORS)
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
