"""
Claim file summaries from adjuster notes - the artefact the judge scores.

This is the Track D deliverable for Week 6. The adjuster reads this summary
before acting on a claim, so a wrong figure here can wrongly pay or wrongly
deny. That is why it is worth scoring.

The output format is deliberately rigid: one labelled line per field. That
makes the deterministic assertions in eval_assertions.py possible without a
model call - a regex can settle whether the claim number was echoed and
whether the deductible is a number, and paying a judge to confirm a number
is numeric is exactly the waste this week warns against.

Retrieval goes through the existing RAGService, so the summary is grounded in
the same chunks the chat answers use and nothing new is added to the pipeline.
"""

import logging
import re
import time

from groq import Groq, GroqError

from app.core.config import settings
from app.core.errors import LLMNotConfiguredError, LLMUpstreamError
from app.services.agent_tools import _resolve_source

logger = logging.getLogger(__name__)

# Bump when SYSTEM_PROMPT, the user prompt below, or retrieval behaviour
# changes, for the same reason llm_service.PROMPT_VERSION exists: a recorded
# run stays replayable. s2 (Week 11): SYSTEM_PROMPT's text is unchanged, but
# summarise() now always fetches a named endorsement's own document even
# when the primary search missed it (see _ensure_named_endorsements_covered
# below) - a behaviour change big enough to invalidate a run recorded under
# s1, so it gets its own version rather than hiding inside s1.
SUMMARY_PROMPT_VERSION = "s2"

# Matches eval_assertions.py's A9 check on purpose: that check is what
# proves this fix closes the gap, so both must agree on what "a named
# endorsement" looks like.
ENDORSEMENT_CODE = re.compile(r"\bHO-20\d{2}-\d{2}[A-Z]?\b")

# How many chunks to pull from a named endorsement's own document when the
# primary search missed it entirely. Small on purpose - this is a targeted
# top-up, not a second full retrieval.
ENDORSEMENT_TOP_UP_K = 2

TEMPERATURE = 0.0

# Higher than the chat cap. gpt-oss models spend hidden reasoning tokens
# before any visible output, and the summary is a six-line form rather than
# the two or three sentences chat asks for. A tight budget here returns a
# truncated form, which is the M2 failure mode this week measures.
MAX_TOKENS = 1600

# Keeps the hidden reasoning budget small so most of MAX_TOKENS reaches the
# visible answer. Dropped automatically if the configured model rejects it.
REASONING_EFFORT = "low"

# Week 10 Task Set D: matches agent_service.py's own assumption, so a
# single-agent-vs-squad token/cost comparison is computed the same way on
# both sides, not two different blended-rate guesses.
ASSUMED_COST_PER_MILLION_TOKENS = 0.20

UNSETTLED = "not established in the policy sources"

SYSTEM_PROMPT = f"""
You are a claims documentation assistant for Meridian Mutual. You write the
file summary an adjuster reads before acting on a claim.

You answer ONLY from the numbered policy sources given to you. If the sources
do not settle a point, write "{UNSETTLED}" for that line rather than guessing.

Reply with EXACTLY these six lines and nothing else:

CLAIM: <the claim number exactly as it appears in the notes>
DATE OF LOSS: <the date of loss exactly as it appears in the notes>
COVERAGE: <one of: covered | partially covered | denied | {UNSETTLED}>
BASIS: <one or two sentences citing the sources you relied on, e.g. [S1]>
DEDUCTIBLE: <the amount as a figure such as $500, or "{UNSETTLED}">
NEXT ACTION: <one sentence naming what the adjuster must do next>

Rules:

1. Quote figures, limits, deductibles and deadlines exactly as they appear in
the sources. Do not round or estimate them.

2. Cite with the source tags you were given, for example [S1]. Never invent a
tag you were not given.

3. If you state or imply that any part of the claim is denied or excluded, the
BASIS line must cite the specific form or clause id relied on, such as
HO-2026-08 or CP-09.

4. Copy the claim number and date of loss from the notes verbatim. Do not
reformat, abbreviate or invent them.
"""


class SummaryService:
    """
    Service responsible for turning adjuster notes into a claim file summary.
    """

    def __init__(self, rag_service):

        self.rag = rag_service
        self.client = Groq(api_key=settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None
        self._reasoning_supported = True

    def summarise(
        self,
        notes: str,
        top_k: int | None = None,
        mode: str = "hybrid",
        source: str | None = None,
    ) -> dict:
        """
        Retrieve policy context for the notes, then write the summary.

        `mode` defaults to hybrid because adjuster notes carry exact form
        codes such as HO-2026-01, which is where dense retrieval alone is
        weakest and BM25 keyword matching is strongest. `source` restricts
        retrieval to one document - normally unset; Week 11's planted
        failure uses it to reproduce a real misconfiguration (retrieval
        scoped to the wrong document, so the exclusions text is never seen).
        """

        if self.client is None:
            raise LLMNotConfiguredError()

        retrieval_started = time.perf_counter()
        retrieval = self.rag.search(notes, top_k=top_k, mode=mode, source=source)
        hits, topped_up = self._ensure_named_endorsements_covered(notes, retrieval["hits"], mode)
        retrieval_latency_ms = int((time.perf_counter() - retrieval_started) * 1000)

        sources = "\n\n".join(
            f"[S{number}] file: {hit['source']} | "
            f"section: {hit['heading']} | {hit['page']}\n{hit['text']}"
            for number, hit in enumerate(hits, start=1)
        )

        prompt = (
            f"POLICY SOURCES\n{sources}\n\n"
            f"ADJUSTER NOTES\n{notes}\n\n"
            "Write the claim file summary in the required format."
        )

        started = time.perf_counter()
        raw_output, tokens_used = self._call(prompt)
        latency_ms = int((time.perf_counter() - started) * 1000)

        summary = raw_output.strip()

        from app.services.citations import CITATION_PARSER_VERSION, parse_citations

        cited, invalid = parse_citations(summary, len(hits))

        return {
            "notes": notes,
            "summary": summary,
            "raw_output": raw_output,
            "fields": parse_summary_fields(summary),
            "retrieved": hits,
            "cited": cited,
            "cited_chunk_ids": [hits[number - 1]["chunk_id"] for number in cited],
            "invalid_citations": invalid,
            "refused": False,
            # Week 11 fix: which named endorsement codes needed a targeted
            # top-up fetch because the primary search missed their document.
            # Empty on almost every real run; non-empty here is a signal
            # worth watching in production, not just in the eval suite - see
            # the canary in docs/training/week11/task_set_d.md.
            "endorsements_topped_up": topped_up,
            "model": settings.MODEL_NAME,
            "summary_prompt_version": SUMMARY_PROMPT_VERSION,
            "citation_parser_version": CITATION_PARSER_VERSION,
            "params": {
                "mode": mode,
                "top_k": settings.TOP_K if top_k is None else top_k,
                "temperature": TEMPERATURE,
                "max_tokens": MAX_TOKENS,
                "reasoning_effort": REASONING_EFFORT if self._reasoning_supported else None,
            },
            "latency_ms": latency_ms,
            "tokens_used": tokens_used,
            "cost_usd": round(tokens_used / 1_000_000 * ASSUMED_COST_PER_MILLION_TOKENS, 6),
            # Week 11: per-span breakdown, not just one lump total - retrieval
            # (fastembed + Qdrant, local, so genuinely $0) and generation (the
            # one Groq call) are the only two stages this pipeline has; no
            # tool-calling here, so "tools" is honestly absent, not hidden.
            "spans": [
                {"name": "retrieval", "latency_ms": retrieval_latency_ms, "tokens": 0, "cost_usd": 0.0},
                {"name": "generation", "latency_ms": latency_ms, "tokens": tokens_used,
                 "cost_usd": round(tokens_used / 1_000_000 * ASSUMED_COST_PER_MILLION_TOKENS, 6)},
            ],
        }

    def _ensure_named_endorsements_covered(
        self, notes: str, hits: list[dict], mode: str
    ) -> tuple[list[dict], list[str]]:
        """
        Week 11 retrieval-layer fix for the drill in docs/training/week11/.

        Adjuster notes sometimes name a specific endorsement code (e.g.
        HO-2026-01). If the primary search above never retrieved so much as
        one chunk from that endorsement's own document - whether because a
        `source` scope hid it (the planted failure) or because ranking
        simply ranked it below top_k (a real risk whenever notes name more
        than one endorsement) - the model is left to answer from whatever
        it got, which reads as "grounded" to the judge even when it is
        wrong (see A9 in eval_assertions.py). Rather than trust ranking to
        find a document already named by its exact code, resolve the code
        straight to its real file name (`_resolve_source`, the same lookup
        agent_tools.py uses for the same reason) and fetch a few chunks
        from it directly.

        An earlier attempt used a free-text supplementary query like
        "HO-2026-01 exclusions" instead - a live test showed this reliably
        returns OTHER endorsements' "Exclusions" sections (the generic word
        dominates the specific code in ranking), not the named document, so
        it was dropped in favour of the direct, code-to-filename approach
        below.
        """

        codes = sorted(set(ENDORSEMENT_CODE.findall(notes or "")))

        if not codes:
            return hits, []

        covered_sources = {hit["source"] for hit in hits}
        topped_up: list[str] = []

        for code in codes:

            if any(code in source for source in covered_sources):
                continue

            resolved = _resolve_source(code)

            if resolved is None or resolved == code:
                # Nothing in the corpus matches this code's filename pattern
                # - not a retrieval bug, just a code the corpus doesn't have.
                continue

            top_up = self.rag.search(notes, top_k=ENDORSEMENT_TOP_UP_K, mode=mode, source=resolved)
            new_chunk_ids = {hit["chunk_id"] for hit in hits}

            for hit in top_up["hits"]:
                if hit["chunk_id"] not in new_chunk_ids:
                    hits.append(hit)
                    new_chunk_ids.add(hit["chunk_id"])

            if top_up["hits"]:
                topped_up.append(code)

        return hits, topped_up

    def _call(self, prompt: str, attempts: int = 3) -> tuple[str, int]:
        """
        One Groq call, retrying on the free tier's per-minute token limit
        rather than losing the case. `reasoning_effort` is dropped for the
        life of the process if the configured model does not accept it.
        Returns (text, total_tokens) - Week 10 needs a real cost number for
        the single-agent arm of the squad-vs-single race.
        """

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        last_error: Exception | None = None

        for attempt in range(attempts):

            extra = (
                {"reasoning_effort": REASONING_EFFORT}
                if self._reasoning_supported
                else {}
            )

            try:
                response = self.client.chat.completions.create(
                    model=settings.MODEL_NAME,
                    temperature=TEMPERATURE,
                    max_tokens=MAX_TOKENS,
                    messages=messages,
                    **extra,
                )
                tokens = response.usage.total_tokens if response.usage else 0
                return response.choices[0].message.content or "", tokens

            except GroqError as error:
                last_error = error
                text = str(error).lower()

                if self._reasoning_supported and "reasoning_effort" in text:
                    logger.info("Model rejects reasoning_effort; retrying without it")
                    self._reasoning_supported = False
                    continue

                if "rate limit" in text or "429" in text:
                    wait = 5 * (attempt + 1)
                    logger.warning("Rate limited; waiting %ss before retry", wait)
                    time.sleep(wait)
                    continue

                break

        logger.warning("Summary call failed: %s", last_error)
        raise LLMUpstreamError() from last_error


FIELD_LABELS = ("CLAIM", "DATE OF LOSS", "COVERAGE", "BASIS", "DEDUCTIBLE", "NEXT ACTION")


def parse_summary_fields(summary: str) -> dict:
    """
    Split the rigid six-line form into a dict. A label the model omitted maps
    to None, which is itself a finding rather than an error - the assertions
    report the missing line.
    """

    fields: dict[str, str | None] = {label: None for label in FIELD_LABELS}
    current: str | None = None

    for line in (summary or "").splitlines():

        stripped = line.strip().lstrip("*# ").strip()

        matched = None
        for label in FIELD_LABELS:
            if stripped.upper().startswith(f"{label}:"):
                matched = label
                break

        if matched:
            current = matched
            fields[matched] = stripped[len(matched) + 1 :].strip().strip("*").strip()
        elif current and stripped:
            fields[current] = f"{fields[current]} {stripped}".strip()

    return fields
