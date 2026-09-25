"""
The fixed-sequence alternative to ClaimAgent: same task, same tools
available in principle, but the steps are hardcoded rather than decided by
a model. Exactly one retrieval call, then exactly one generation call,
every time - a simple claim and a claim naming three endorsements get
identical treatment.

This exists specifically to be raced against the agent (see
scripts/race_agent_vs_workflow.py). The point of the comparison is not to
make the fixed workflow look bad - it is deliberately a reasonable design a
non-agent engineer would actually write (a wider top_k to compensate for
not being able to look twice), not a strawman.
"""

import time

from groq import Groq, GroqError

from app.core.config import settings
from app.core.errors import LLMNotConfiguredError, LLMUpstreamError
from app.services.retrieval_service import RetrievalService

_UNSET = object()  # distinct from a caller explicitly passing client=None

WORKFLOW_PROMPT_VERSION = "w1"

TEMPERATURE = 0.0
MAX_TOKENS = 700

# Wider than the agent's per-search top_k (5), on purpose: since this
# workflow never gets a second, targeted look, it compensates by casting a
# wider net on the one search it gets.
FIXED_TOP_K = 8

# Same rate-limit reality as agent_service.py: the account's tokens-per-minute
# budget can run out mid-race even for this workflow's smaller per-call cost,
# since races run scenarios back to back. Same wait-and-retry shape.
RATE_LIMIT_RETRIES = 4
RATE_LIMIT_WAIT_S = 15

SYSTEM_PROMPT = """
You are a claims resolution agent for Meridian Mutual. You are given a claim
description and a fixed set of retrieved policy passages. Answer using only
those passages - if they do not cover part of the claim, say so plainly
rather than guessing. Cite sources by file name and heading.
"""


class FixedClaimWorkflow:
    """
    Step 1: one hybrid search over the whole corpus.
    Step 2: one generation call from whatever that search returned.
    No branching, no second look, regardless of what step 1 finds.
    """

    def __init__(self, retriever: RetrievalService | None = None, client=_UNSET):

        self.retriever = retriever or RetrievalService()
        self.client = (
            (Groq(api_key=settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None)
            if client is _UNSET else client
        )

    def run(self, claim_description: str) -> dict:

        if self.client is None:
            raise LLMNotConfiguredError()

        started = time.perf_counter()
        steps = []

        step_started = time.perf_counter()
        retrieval = self.retriever.retrieve(claim_description, top_k=FIXED_TOP_K, mode="hybrid")
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

        prompt = f"CLAIM DESCRIPTION\n{claim_description}\n\nRETRIEVED PASSAGES\n{sources_block}\n\nAnswer the claim, citing sources."

        step_started = time.perf_counter()
        response = self._create_completion(prompt)

        answer = (response.choices[0].message.content or "").strip()
        tokens_used = response.usage.total_tokens if response.usage else 0

        steps.append({
            "step": 2, "action": "generate answer from the fixed retrieval",
            "latency_ms": int((time.perf_counter() - step_started) * 1000),
            "tokens": tokens_used,
        })

        return {
            "claim_description": claim_description,
            "answer": answer,
            "sources": sorted({hit["source"] for hit in hits}),
            "steps": steps,
            "step_count": 2,
            "tokens_used": tokens_used,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "stopped_reason": "finished",
            "finished": True,
            "workflow_prompt_version": WORKFLOW_PROMPT_VERSION,
        }

    def _create_completion(self, prompt: str):
        """One call, with a real wait-and-retry reserved for rate limits only."""

        last_error: GroqError | None = None

        for attempt in range(RATE_LIMIT_RETRIES + 1):
            try:
                return self.client.chat.completions.create(
                    model=settings.MODEL_NAME,
                    temperature=TEMPERATURE,
                    max_tokens=MAX_TOKENS,
                    messages=[
                        {"role": "system", "content": SYSTEM_PROMPT},
                        {"role": "user", "content": prompt},
                    ],
                )
            except GroqError as error:
                last_error = error
                text = str(error).lower()
                if not ("rate limit" in text or "429" in text) or attempt == RATE_LIMIT_RETRIES:
                    raise LLMUpstreamError() from error
                wait = RATE_LIMIT_WAIT_S * (attempt + 1)
                time.sleep(wait)

        raise LLMUpstreamError() from last_error  # pragma: no cover
