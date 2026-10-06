"""
Week 10 Task Set D: a manager plus two specialists, racing against
SummaryService (the single agent) on the same Week 6 M6 claim-summary
cases, scored by the same deterministic assertions and the same judge.

Three agents, three hand-offs, three separate Groq calls per case:

  1. summary_worker   - reads the raw adjuster notes only. Narrow job:
                         extract the facts (cause of loss, conditions met
                         or not, dates, amounts mentioned). No policy
                         search, no coverage opinion - deliberately kept to
                         the one thing it's for for, per the task's own
                         warning against handing a specialist every tool
                         the single agent had.
  2. coverage_worker   - reads the extracted facts (hand-off 1's full
                         output) plus the retrieved policy sources (the
                         same retrieval the single agent runs). Narrow
                         job: decide the coverage position and cite the
                         clauses. No notes re-interpretation of its own -
                         it trusts the facts worker 1 already extracted.
  3. manager_synthesize - the manager's own distinct job: reads BOTH
                         workers' raw outputs plus the original notes
                         again, and writes the final rigid six-line form
                         SummaryService also produces, so the output is
                         scored by eval_assertions.py and JudgeService
                         exactly as the single agent's is - the race is
                         fair because the finish line is identical.

Every hand-off re-sends full context from scratch (no conversation memory
between the three calls) - this is deliberate, not an oversight: it is the
real-world cost pattern Week 10 is about measuring, not hiding.
"""

import logging
import time

from groq import Groq, GroqError

from app.core.config import settings
from app.core.errors import LLMNotConfiguredError, LLMUpstreamError
from app.services.summary_service import UNSETTLED, parse_summary_fields

logger = logging.getLogger(__name__)

SQUAD_PROMPT_VERSION = "squad1"
TEMPERATURE = 0.0
MAX_TOKENS_PER_CALL = 1200

# Matches summary_service.py's own constant, so both arms of the race are
# costed by the same assumption, not two different blended-rate guesses.
ASSUMED_COST_PER_MILLION_TOKENS = 0.20

SUMMARY_WORKER_SYSTEM = f"""
You are the adjuster-note summary specialist on a claims triage team. Your
only job is reading raw adjuster notes and extracting the facts another
specialist will use to decide coverage - you never decide coverage
yourself, and you never search or cite policy documents.

Reply with EXACTLY these lines and nothing else:

CLAIM NUMBER: <exactly as it appears in the notes>
DATE OF LOSS: <exactly as it appears in the notes>
CAUSE OF LOSS: <one sentence, the proximate cause>
CONDITIONS NOTED: <every condition, qualifier or exception the notes mention - e.g. backup system present/absent, basement finished year, prior maintenance - or "none noted">
AMOUNTS MENTIONED: <every dollar figure in the notes, verbatim, or "none mentioned">

Quote figures and dates exactly as written. Do not interpret coverage. Do
not guess a fact the notes do not state.
"""

COVERAGE_WORKER_SYSTEM = f"""
You are the coverage/exclusions specialist on a claims triage team. You
receive another specialist's extracted facts (not the raw notes) and the
indexed policy sources relevant to this claim. Your only job is deciding
the coverage position and citing exactly which source supports it - you
never write the final claim file summary, and you never re-interpret the
adjuster notes yourself; trust the facts you were given.

Reply with EXACTLY these lines and nothing else:

COVERAGE POSITION: <one of: covered | partially covered | denied | {UNSETTLED}>
APPLICABLE CLAUSE(S): <the specific form/clause id(s) relied on, e.g. HO-2026-01>
REASONING: <one or two sentences, citing sources by tag, e.g. [S1]>
DEDUCTIBLE: <the amount as a figure such as $500, or "{UNSETTLED}">

Cite only tags you were actually given (e.g. [S1]). Never invent a tag. If
the sources do not settle a point, say "{UNSETTLED}" rather than guessing.
"""

MANAGER_SYNTHESIZE_SYSTEM = f"""
You are the manager on a claims triage team, writing the final file
summary an adjuster reads before acting on a claim - the same deliverable
a single claims assistant would produce alone. You receive two
specialists' outputs (an adjuster-note summary and a coverage/exclusions
opinion) plus the original adjuster notes. A wrong figure here can wrongly
pay or wrongly deny, so synthesise faithfully - never upgrade a qualified
or missing determination into a confident one.

If the coverage specialist's output is missing, marked failed, or does not
state a clear coverage position, you must write "{UNSETTLED}" on the
COVERAGE line and say so plainly in NEXT ACTION - never assert a coverage
position (covered, denied, or partial) that the coverage specialist did
not actually state, and never treat silence or an error as "covered."

Reply with EXACTLY these six lines and nothing else:

CLAIM: <the claim number exactly as it appears in the notes>
DATE OF LOSS: <the date of loss exactly as it appears in the notes>
COVERAGE: <one of: covered | partially covered | denied | {UNSETTLED}>
BASIS: <one or two sentences citing the sources relied on, e.g. [S1]>
DEDUCTIBLE: <the amount as a figure such as $500, or "{UNSETTLED}">
NEXT ACTION: <one sentence naming what the adjuster must do next>

Rules:

1. Quote figures, limits, deductibles and deadlines exactly as the
specialists or notes state them. Do not round or estimate them.

2. Cite with the source tags the coverage specialist used, for example
[S1]. Never invent a tag.

3. If you state or imply any part of the claim is denied or excluded, the
BASIS line must cite the specific form or clause id relied on.

4. Copy the claim number and date of loss from the notes verbatim.
"""


class CoverageWorkerFailure(Exception):
    """Raised to simulate the coverage/exclusions worker returning a 500 - Week 10's injected failure case."""


class ClaimsSquadService:
    """Manager + two specialists, producing output scored identically to SummaryService's."""

    def __init__(self, rag_service):

        self.rag = rag_service
        self.client = Groq(api_key=settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None

    def process(
        self,
        notes: str,
        top_k: int | None = None,
        mode: str = "hybrid",
        fail_coverage_worker: bool = False,
    ) -> dict:
        """
        `fail_coverage_worker=True` simulates the coverage/exclusions
        worker returning a 500 on this case (Week 10's injected-failure
        requirement) - the manager still runs its synthesis step and
        whatever it actually produces, unscripted, is what gets recorded.
        """

        if self.client is None:
            raise LLMNotConfiguredError()

        started = time.perf_counter()
        handoffs: list[dict] = []
        worker_error: str | None = None

        # Hand-off 1: manager -> summary_worker (the full raw notes, first use)
        facts_raw, facts_tokens = self._call(SUMMARY_WORKER_SYSTEM, f"ADJUSTER NOTES\n{notes}")
        handoffs.append({"from": "manager", "to": "summary_worker", "tokens": facts_tokens})

        retrieval = self.rag.search(notes, top_k=top_k, mode=mode)
        hits = retrieval["hits"]
        sources_block = "\n\n".join(
            f"[S{number}] file: {hit['source']} | section: {hit['heading']} | {hit['page']}\n{hit['text']}"
            for number, hit in enumerate(hits, start=1)
        )

        # Hand-off 2: manager -> coverage_worker (facts + full policy sources
        # re-sent - this is the hand-off expected to dominate token share,
        # since it carries the retrieved chunk text nothing else needs).
        if fail_coverage_worker:
            worker_error = "HTTP 500 (simulated) from the coverage/exclusions worker"
            coverage_raw = f"[WORKER FAILED: {worker_error}]"
            coverage_tokens = 0
            handoffs.append({"from": "manager", "to": "coverage_worker", "tokens": 0, "error": worker_error})
        else:
            coverage_input = f"EXTRACTED FACTS\n{facts_raw}\n\nPOLICY SOURCES\n{sources_block}"
            coverage_raw, coverage_tokens = self._call(COVERAGE_WORKER_SYSTEM, coverage_input)
            handoffs.append({"from": "manager", "to": "coverage_worker", "tokens": coverage_tokens})

        # Hand-off 3: both workers' outputs + the original notes, re-sent a
        # third time, to the manager's own synthesis call.
        synth_input = (
            f"ADJUSTER-NOTE SUMMARY SPECIALIST OUTPUT\n{facts_raw}\n\n"
            f"COVERAGE/EXCLUSIONS SPECIALIST OUTPUT\n{coverage_raw}\n\n"
            f"ORIGINAL ADJUSTER NOTES\n{notes}"
        )
        summary_raw, synth_tokens = self._call(MANAGER_SYNTHESIZE_SYSTEM, synth_input)
        handoffs.append({"from": "summary_worker+coverage_worker", "to": "manager", "tokens": synth_tokens})

        summary = summary_raw.strip()
        tokens_used = facts_tokens + coverage_tokens + synth_tokens

        from app.services.citations import CITATION_PARSER_VERSION, parse_citations

        cited, invalid = parse_citations(summary, len(hits))

        return {
            "notes": notes,
            "summary": summary,
            "raw_output": summary_raw,
            "fields": parse_summary_fields(summary),
            "retrieved": hits,
            "cited": cited,
            "cited_chunk_ids": [hits[number - 1]["chunk_id"] for number in cited],
            "invalid_citations": invalid,
            "refused": False,
            "model": settings.MODEL_NAME,
            "squad_prompt_version": SQUAD_PROMPT_VERSION,
            "citation_parser_version": CITATION_PARSER_VERSION,
            "handoffs": handoffs,
            "worker_error": worker_error,
            "intermediate": {"summary_worker": facts_raw, "coverage_worker": coverage_raw},
            "tokens_used": tokens_used,
            "cost_usd": round(tokens_used / 1_000_000 * ASSUMED_COST_PER_MILLION_TOKENS, 6),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    def _call(self, system_prompt: str, user_content: str, attempts: int = 3) -> tuple[str, int]:
        """One Groq call for one agent's turn. Returns (text, total_tokens)."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        last_error: Exception | None = None

        for attempt in range(attempts):
            try:
                response = self.client.chat.completions.create(
                    model=settings.MODEL_NAME,
                    temperature=TEMPERATURE,
                    max_tokens=MAX_TOKENS_PER_CALL,
                    messages=messages,
                )
                tokens = response.usage.total_tokens if response.usage else 0
                return response.choices[0].message.content or "", tokens

            except GroqError as error:
                last_error = error
                text = str(error).lower()
                if "rate limit" in text or "429" in text:
                    wait = 5 * (attempt + 1)
                    logger.warning("Rate limited; waiting %ss before retry", wait)
                    time.sleep(wait)
                    continue
                break

        logger.warning("Squad call failed: %s", last_error)
        raise LLMUpstreamError() from last_error
