"""
The fixed-sequence alternative to ClaimTriageAgent: same claim ID in, same
{decision, payout, reasoning, sources} contract out, same three tools
(get_claim, search_policy, compute_payout) - but the steps are hardcoded,
always exactly four, in a fixed order, regardless of what any step finds.
No loop, no branching on a tool's result: step 2 always runs one
search_policy call built from the claim's own notes; step 4 always runs
compute_payout with whatever step 3 decided.

The one judgment call a fixed sequence cannot avoid - is this loss covered,
and what deductible applies - is made in exactly one plain-text generation
call (step 3), not a tool call: this both matches the original Week 7
fixed_claim_workflow.py's insight (a single free-text call has no tool-call
structure to corrupt) and keeps the arithmetic itself (step 4) deterministic
code rather than something the model computes and might round or miscopy.
"""

import json
import logging
import time

from groq import Groq, GroqError

from app.core.config import settings
from app.core.errors import LLMNotConfiguredError, LLMUpstreamError
from app.services.groq_retry import create_completion_with_retry
from app.services.retrieval_service import RetrievalService
from app.services.triage_tools import CLAIM_STATUSES, compute_payout, get_claim

logger = logging.getLogger(__name__)

_UNSET = object()

TRIAGE_WORKFLOW_PROMPT_VERSION = "w1"

TEMPERATURE = 0.0

# Live bug, first run: 500 was too tight once the prompt grew to include a
# full claim record plus 8 retrieved passages - gpt-oss-20b spends hidden
# reasoning tokens before writing anything visible (same root cause as
# results.md's C3 case in Week 7), and the budget ran out before any JSON
# was written, returning empty content. 1000 then cut a real, otherwise-
# correct response off mid-string. Raised again rather than reaching for an
# agent loop - the same fix results.md already recommended for this exact
# failure mode.
MAX_TOKENS = 1500

# Wider than the agent's per-search top_k (5), on purpose, same reasoning as
# the Week 7 fixed_claim_workflow.py: this workflow never gets a second,
# targeted look, so it compensates by casting a wider net on its one search.
FIXED_TOP_K = 8

SYSTEM_PROMPT = f"""
You are a claims triage agent for Meridian Mutual. You are given one claim's
case file and a fixed set of retrieved policy passages. Decide the coverage
outcome and the applicable deductible/excess using only those passages - if
they do not clearly cover part of the claim, decide "denied" rather than
guessing.

Respond with ONLY a JSON object, no other text, no markdown fences, in
exactly this shape:
{{"claim_status": one of {CLAIM_STATUSES}, "excess_amount": number (0 if denied or no deductible applies), "reasoning": "one or two sentences citing the specific document and heading relied on", "sources": ["file names actually used"]}}
"""


class FixedClaimTriageWorkflow:
    """
    Step 1: get_claim (direct). Step 2: one search_policy call, query built
    from the claim's own notes (direct). Step 3: one generation call
    deciding claim_status and excess_amount. Step 4: compute_payout (direct,
    hardcoded arithmetic from the claim's real claimed_amount).
    """

    def __init__(self, retriever: RetrievalService | None = None, client=_UNSET):

        self.retriever = retriever or RetrievalService()
        self.client = (
            (Groq(api_key=settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None)
            if client is _UNSET else client
        )

    def run(self, claim_id: str) -> dict:

        if self.client is None:
            raise LLMNotConfiguredError()

        started = time.perf_counter()
        steps = []
        tokens_used = 0

        step_started = time.perf_counter()
        claim_result = get_claim({"claim_id": claim_id})
        steps.append({
            "step": 1, "action": "get_claim (fixed)",
            "result": claim_result, "latency_ms": int((time.perf_counter() - step_started) * 1000),
        })

        if "error" in claim_result:
            return self._error_result(claim_id, claim_result["error"], steps, started, tokens_used)

        claim = claim_result["result"]

        step_started = time.perf_counter()
        retrieval = self.retriever.retrieve(claim["adjuster_notes"], top_k=FIXED_TOP_K, mode="hybrid")
        hits = retrieval["hits"]
        steps.append({
            "step": 2, "action": "search_policy (fixed, query = adjuster notes, top_k=8)",
            "result_count": len(hits), "latency_ms": int((time.perf_counter() - step_started) * 1000),
        })

        sources_block = "\n\n".join(
            f"[{i}] file: {hit['source']} | section: {hit['heading']} | {hit['page']}\n{hit['text']}"
            for i, hit in enumerate(hits, start=1)
        )

        prompt = (
            f"CLAIM CASE FILE\nclaim_id: {claim['claim_id']}\n"
            f"claimed_amount: {claim['claimed_amount']}\n"
            f"policy_form: {claim['policy_form']}\n"
            f"adjuster_notes: {claim['adjuster_notes']}\n\n"
            f"RETRIEVED PASSAGES\n{sources_block}\n\n"
            "Decide the coverage outcome and excess amount, per the JSON shape you were given."
        )

        step_started = time.perf_counter()

        try:
            response = create_completion_with_retry(
                self.client, model=settings.MODEL_NAME,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=TEMPERATURE, max_tokens=MAX_TOKENS,
            )
        except GroqError as error:
            raise LLMUpstreamError() from error

        raw = (response.choices[0].message.content or "").strip()
        call_tokens = response.usage.total_tokens if response.usage else 0
        tokens_used += call_tokens

        decision_data = self._parse_decision(raw)

        steps.append({
            "step": 3, "action": "generate coverage decision from the fixed retrieval",
            "raw": raw, "latency_ms": int((time.perf_counter() - step_started) * 1000), "tokens": call_tokens,
        })

        if decision_data is None:
            return self._error_result(claim_id, f"Could not parse a decision from the model's output: {raw[:200]!r}", steps, started, tokens_used)

        step_started = time.perf_counter()
        payout_result = compute_payout({
            "claimed_amount": claim["claimed_amount"],
            "excess_amount": decision_data.get("excess_amount") or 0,
            "claim_status": decision_data.get("claim_status"),
        })
        steps.append({
            "step": 4, "action": "compute_payout (fixed)",
            "result": payout_result, "latency_ms": int((time.perf_counter() - step_started) * 1000),
        })

        if "error" in payout_result:
            return self._error_result(claim_id, payout_result["error"], steps, started, tokens_used)

        return {
            "claim_id": claim_id,
            "decision": payout_result["result"]["claim_status"],
            "payout": payout_result["result"]["payout"],
            "reasoning": decision_data.get("reasoning", ""),
            "sources": decision_data.get("sources", []),
            "steps": steps,
            "step_count": 4,
            "tokens_used": tokens_used,
            "cost_usd": round(tokens_used / 1_000_000 * 0.20, 6),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "stopped_reason": "finished",
            "finished": True,
            "workflow_prompt_version": TRIAGE_WORKFLOW_PROMPT_VERSION,
        }

    @staticmethod
    def _parse_decision(raw: str) -> dict | None:

        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`")
            text = text[4:] if text.lower().startswith("json") else text

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None

        if not isinstance(data, dict) or str(data.get("claim_status", "")).lower() not in CLAIM_STATUSES:
            return None

        return data

    @staticmethod
    def _error_result(claim_id: str, error: str, steps: list, started: float, tokens_used: int) -> dict:

        logger.warning("Fixed triage workflow failed for %s: %s", claim_id, error)

        return {
            "claim_id": claim_id,
            "decision": None,
            "payout": None,
            "reasoning": error,
            "sources": [],
            "steps": steps,
            "step_count": len(steps),
            "tokens_used": tokens_used,
            "cost_usd": round(tokens_used / 1_000_000 * 0.20, 6),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "stopped_reason": "error",
            "finished": False,
            "workflow_prompt_version": TRIAGE_WORKFLOW_PROMPT_VERSION,
        }
