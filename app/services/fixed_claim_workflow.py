"""
The fixed-sequence alternative to the merged ClaimAgent: same input in
(a policy question or a claim ID), same {answer, decision, payout, sources}
contract out, no loop - but "fixed" now covers two different hardcoded
sequences, not one, since the merged agent itself covers two different jobs.

Originally two separate classes - `FixedClaimWorkflow` (2 steps: one search,
one generation, for a policy question) and `FixedClaimTriageWorkflow` (4
steps: get_claim, one search, one decision generation, compute_payout) -
merged into one class that picks which fixed sequence to run by a
deterministic regex check on the input's shape (`CLM-####` or not), not by
any model judgment. That is still "no loop hiding inside it": one fixed
branch point, then one fixed sequence either way - never a decision the
model makes about how many steps to take.

The one judgment call a fixed sequence cannot avoid on the triage side - is
this loss covered, and what deductible applies - is made in exactly one
plain-text generation call, not a tool call: a single free-text call has no
tool-call structure to corrupt (this model's live-documented fragility), and
the arithmetic itself (compute_payout) stays deterministic code rather than
something the model computes and might round or miscopy.
"""

import json
import logging
import time

from groq import Groq, GroqError

from app.core.config import settings
from app.core.errors import LLMNotConfiguredError, LLMUpstreamError
from app.services.agent_tools import CLAIM_ID_PATTERN, CLAIM_STATUSES, compute_payout, get_claim
from app.services.groq_retry import create_completion_with_retry
from app.services.retrieval_service import RetrievalService

logger = logging.getLogger(__name__)

_UNSET = object()  # distinct from a caller explicitly passing client=None

WORKFLOW_PROMPT_VERSION = "m1"

TEMPERATURE = 0.0
MAX_TOKENS_QUESTION = 700

# Live bug, first run of the triage-only predecessor: 500 was too tight once
# the prompt grew to include a full claim record plus 8 retrieved passages -
# gpt-oss-20b spends hidden reasoning tokens before writing anything
# visible, and the budget ran out before any JSON was written, returning
# empty content. 1000 then cut a real, otherwise-correct response off
# mid-string. Settled on 1500 rather than reaching for an agent loop.
MAX_TOKENS_TRIAGE = 1500

# Wider than the agent's per-search top_k (5), on purpose: since this
# workflow never gets a second, targeted look, it compensates by casting a
# wider net on the one search it gets, on either branch.
FIXED_TOP_K = 8

QUESTION_SYSTEM_PROMPT = """
You are a claims assistant for Meridian Mutual. You are given a policy
question and a fixed set of retrieved policy passages. Answer using only
those passages - if they do not cover part of the question, say so plainly
rather than guessing. Cite sources by file name and heading.
"""

TRIAGE_SYSTEM_PROMPT = f"""
You are a claims assistant for Meridian Mutual. You are given one claim's
case file and a fixed set of retrieved policy passages. Decide the coverage
outcome and the applicable deductible/excess using only those passages - if
they do not clearly cover part of the claim, decide "denied" rather than
guessing.

Respond with ONLY a JSON object, no other text, no markdown fences, in
exactly this shape:
{{"claim_status": one of {CLAIM_STATUSES}, "excess_amount": number (0 if denied or no deductible applies), "reasoning": "one or two sentences citing the specific document and heading relied on", "sources": ["file names actually used"]}}
"""


class FixedClaimWorkflow:
    """
    Branches once, deterministically, on the input's shape:
      claim ID (CLM-####)  -> get_claim -> search -> decide -> compute_payout
      anything else        -> search -> generate an answer
    No further branching within either sequence, regardless of what any step finds.
    """

    def __init__(self, retriever: RetrievalService | None = None, client=_UNSET):

        self.retriever = retriever or RetrievalService()
        self.client = (
            (Groq(api_key=settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None)
            if client is _UNSET else client
        )

    def run(self, user_input: str) -> dict:

        if self.client is None:
            raise LLMNotConfiguredError()

        claim_id = user_input.strip()

        if CLAIM_ID_PATTERN.match(claim_id):
            return self._run_triage(claim_id)

        return self._run_question(user_input)

    # ------------------------------------------------------------- question

    def _run_question(self, question: str) -> dict:

        started = time.perf_counter()
        steps = []

        step_started = time.perf_counter()
        retrieval = self.retriever.retrieve(question, top_k=FIXED_TOP_K, mode="hybrid")
        hits = retrieval["hits"]
        steps.append({
            "step": 1, "action": "search_policy (fixed, top_k=8, whole corpus)",
            "result_count": len(hits),
            "latency_ms": int((time.perf_counter() - step_started) * 1000),
        })

        sources_block = "\n\n".join(
            f"[{i}] file: {hit['source']} | section: {hit['heading']} | {hit['page']}\n{hit['text']}"
            for i, hit in enumerate(hits, start=1)
        )

        prompt = f"QUESTION\n{question}\n\nRETRIEVED PASSAGES\n{sources_block}\n\nAnswer the question, citing sources."

        step_started = time.perf_counter()

        try:
            response = create_completion_with_retry(
                self.client, model=settings.MODEL_NAME,
                messages=[
                    {"role": "system", "content": QUESTION_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=TEMPERATURE, max_tokens=MAX_TOKENS_QUESTION,
            )
        except GroqError as error:
            raise LLMUpstreamError() from error

        answer = (response.choices[0].message.content or "").strip()
        tokens_used = response.usage.total_tokens if response.usage else 0

        steps.append({
            "step": 2, "action": "generate answer from the fixed retrieval",
            "latency_ms": int((time.perf_counter() - step_started) * 1000),
            "tokens": tokens_used,
        })

        return {
            "user_input": question,
            "answer": answer,
            "decision": None,
            "payout": None,
            "sources": sorted({hit["source"] for hit in hits}),
            "steps": steps,
            "step_count": 2,
            "tokens_used": tokens_used,
            "cost_usd": round(tokens_used / 1_000_000 * 0.20, 6),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "stopped_reason": "finished",
            "finished": True,
            "workflow_prompt_version": WORKFLOW_PROMPT_VERSION,
        }

    # --------------------------------------------------------------- triage

    def _run_triage(self, claim_id: str) -> dict:

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
            return self._triage_error_result(claim_id, claim_result["error"], steps, started, tokens_used)

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
                    {"role": "system", "content": TRIAGE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                temperature=TEMPERATURE, max_tokens=MAX_TOKENS_TRIAGE,
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
            return self._triage_error_result(
                claim_id, f"Could not parse a decision from the model's output: {raw[:200]!r}", steps, started, tokens_used
            )

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
            return self._triage_error_result(claim_id, payout_result["error"], steps, started, tokens_used)

        return {
            "user_input": claim_id,
            "answer": decision_data.get("reasoning", ""),
            "decision": payout_result["result"]["claim_status"],
            "payout": payout_result["result"]["payout"],
            "sources": decision_data.get("sources", []),
            "steps": steps,
            "step_count": 4,
            "tokens_used": tokens_used,
            "cost_usd": round(tokens_used / 1_000_000 * 0.20, 6),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "stopped_reason": "finished",
            "finished": True,
            "workflow_prompt_version": WORKFLOW_PROMPT_VERSION,
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
    def _triage_error_result(claim_id: str, error: str, steps: list, started: float, tokens_used: int) -> dict:

        logger.warning("Fixed workflow triage branch failed for %s: %s", claim_id, error)

        return {
            "user_input": claim_id,
            "answer": None,
            "decision": None,
            "payout": None,
            "sources": [],
            "steps": steps,
            "step_count": len(steps),
            "tokens_used": tokens_used,
            "cost_usd": round(tokens_used / 1_000_000 * 0.20, 6),
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "stopped_reason": "error",
            "finished": False,
            "workflow_prompt_version": WORKFLOW_PROMPT_VERSION,
        }
