"""
The claim-summary judge: one model call that grades a summary on the things a
regex cannot settle.

Two deliberate choices, both aimed at making the judge's number trustworthy.

**Binary, not 1-10.** A one-to-ten score reads as precision the judge does not
have, and two people rarely agree on whether an answer is a 6 or a 7. Every
criterion below is pass or fail, which is what makes human agreement in
scripts/validate_judge.py a number worth reporting.

**Criteria a rule cannot do.** Claim-number format, date parsing, whether the
deductible is numeric and whether a denial cites a clause are all handled for
free in eval_assertions.py. Only judgement is left here.

An unvalidated judge is a confident number nobody should trust. Run
scripts/validate_judge.py and read the agreement before quoting any figure
this module produces.
"""

import json
import logging
import re
import time

from groq import Groq, GroqError

from app.core.config import settings
from app.core.errors import LLMNotConfiguredError, LLMUpstreamError

logger = logging.getLogger(__name__)

JUDGE_PROMPT_VERSION = "j4"

# v1 -> v2: validated against 20 hand-graded summaries (see
# docs/training/week6/judge_validation.md). v1 scored 61% agreement, mostly
# because J1 penalised the CLAIM and DATE OF LOSS lines for not tracing to a
# numbered source - but those two lines are copied verbatim from the adjuster
# notes by design (see summary_service.SYSTEM_PROMPT rule 4), never from the
# sources. v2 states that scope explicitly and reached 65%.
#
# v2 -> v3 (tried, NOT shipped): asked the judge to also verify each rule's
# own qualifying condition against the notes, aimed at J2's remaining 55%.
# Revalidated rather than assumed: agreement fell to 64% overall and J1 alone
# dropped 70% -> 55%, so the change made a real thing worse. Reverted to v2,
# archived at .runtime/judge/v2/ and v3 at .runtime/judge/v3/ (not used) -
# concrete evidence that a plausible-sounding prompt fix still needs
# revalidation, not just intuition, before it ships.
#
# v2 -> v4 (Task Set D extension, 2026-09-15): re-validated on 25 summaries
# using ONE combined pass/fail verdict per summary (pass only if all four
# criteria hold) rather than four separate agreement numbers. agreement_before
# = 56% (14/25) - see .runtime/judge/deliverables/. 8 of the 11 disagreements
# were the judge saying "pass" where a human said "fail", and the two clearest
# examples (V17, V21) shared one root cause: the judge found a rule that
# *resembled* what the summary cited and credited it, without checking whether
# that rule's own qualifying condition or scope actually applied to these
# specific facts. v4 adds those two disagreements as few-shot examples
# (judge_v2.txt) rather than rewording the criteria again, per
# prediction.txt (written before this change): expected to move agreement
# into the low-to-mid 70s while leaving the opposite-direction over-strict
# cases (V04, V08, V19) unresolved, since the examples don't address that
# pattern. Result measured in docs/training/week6/task_set_d_extension.md.

TEMPERATURE = 0.0
MAX_TOKENS = 1600
REASONING_EFFORT = "low"

CRITERIA = [
    {
        "id": "J1",
        "name": "Grounded",
        "question": (
            "Is every POLICY-DERIVED statement in the summary - a limit, a deductible, "
            "a settlement basis, a coverage determination, a procedural requirement - "
            "supported by the numbered sources? Do NOT apply this to the CLAIM number or "
            "DATE OF LOSS lines: those are copied from the adjuster notes by design and "
            "are not expected to appear in the policy sources."
        ),
    },
    {
        "id": "J2",
        "name": "Outcome correct",
        "question": (
            "Does the COVERAGE line state the outcome the sources actually support "
            "for these notes, rather than a different or vaguer outcome?"
        ),
    },
    {
        "id": "J3",
        "name": "Actionable",
        "question": (
            "Does the NEXT ACTION line name a concrete step an adjuster could take, "
            "consistent with the procedures in the sources?"
        ),
    },
    {
        "id": "J4",
        "name": "Hedged honestly",
        "question": (
            "Where the sources do not settle a point, does the summary say so instead "
            "of guessing? Fail if it states something the sources do not support."
        ),
    },
]

CRITERIA_BY_ID = {criterion["id"]: criterion for criterion in CRITERIA}

SYSTEM_PROMPT = """
You grade claim file summaries written by another assistant for Meridian Mutual.

You are given the adjuster notes, the numbered policy sources the assistant was
shown, and the summary it produced. Grade policy facts against the sources, not
against outside insurance knowledge, and do not reward or punish style.

The summary's CLAIM and DATE OF LOSS lines are copied verbatim from the
adjuster notes, not derived from the policy sources - check them against the
NOTES, never fault them for not appearing in the sources.

Work through each criterion in order. For each one:

1. Find the specific line of the summary the criterion is about.
2. Find the source that supports or contradicts it.
3. Decide pass or fail. There is no middle grade.

A criterion is "pass" only if it clearly holds. If the summary says a point is
"not established in the policy sources" and the sources genuinely do not settle
it, that is a pass, not a fail.

Finding a rule that SOUNDS related is not enough - check whether that rule's
own condition or scope actually applies to these specific facts before
crediting it. Two real examples this mistake was caught on:

EXAMPLE 1 - a home-sharing guest's own car was broken into by an outside
thief. The summary claimed "COVERAGE: covered ... theft of personal property
by a guest is covered up to $5,000" citing a source clause about theft BY a
guest. That clause covers the guest stealing something - a completely
different situation from a guest's own property being stolen FROM them by
someone else. The source mentions "theft" and "guest" but its condition
(the guest is the thief) does not match these facts. Correct verdict: J1 and
J2 FAIL - the summary cited the wrong clause for what actually happened.

EXAMPLE 2 - a $4,200 cyber-extortion negotiation and specialist-fee expense
was billed against a source clause requiring "prior written consent" before
a RANSOMWARE PAYMENT is reimbursed. Negotiation and specialist fees are a
separate, distinct expense category from an actual ransomware payment, and
the notes never describe any ransom being paid. The summary denied a real,
different expense using a condition that only applies to a different line
item. Correct verdict: J1 and J2 FAIL - the consent condition does not
govern this expense.

Reply with ONLY a JSON object, no prose and no code fence:

{"J1": {"verdict": "pass", "reason": "..."},
 "J2": {"verdict": "fail", "reason": "..."},
 "J3": {"verdict": "pass", "reason": "..."},
 "J4": {"verdict": "pass", "reason": "..."}}

Each reason is one short sentence naming the line and the source it turns on.
"""


class JudgeService:
    """Grades one claim summary per call."""

    def __init__(self):

        self.client = Groq(api_key=settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None
        self._reasoning_supported = True

    def judge(self, notes: str, summary: str, hits: list[dict]) -> dict:

        if self.client is None:
            raise LLMNotConfiguredError()

        sources = "\n\n".join(
            f"[S{number}] file: {hit['source']} | "
            f"section: {hit['heading']} | {hit['page']}\n{hit['text']}"
            for number, hit in enumerate(hits, start=1)
        )

        criteria = "\n".join(
            f"{criterion['id']} ({criterion['name']}): {criterion['question']}"
            for criterion in CRITERIA
        )

        prompt = (
            f"POLICY SOURCES\n{sources}\n\n"
            f"ADJUSTER NOTES\n{notes}\n\n"
            f"SUMMARY TO GRADE\n{summary}\n\n"
            f"CRITERIA\n{criteria}\n\n"
            "Grade every criterion and reply with the JSON object only."
        )

        started = time.perf_counter()
        raw_output = self._call(prompt)
        latency_ms = int((time.perf_counter() - started) * 1000)

        verdicts = _parse_verdicts(raw_output)

        return {
            "verdicts": verdicts,
            "passed": sum(1 for v in verdicts.values() if v["verdict"] == "pass"),
            "total": len(CRITERIA),
            "status": "pass" if all(v["verdict"] == "pass" for v in verdicts.values()) else "fail",
            "raw_output": raw_output,
            "judge_prompt_version": JUDGE_PROMPT_VERSION,
            "model": settings.MODEL_NAME,
            "latency_ms": latency_ms,
        }

    def _call(self, prompt: str, attempts: int = 3) -> str:

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ]

        last_error: Exception | None = None

        for attempt in range(attempts):

            extra = {"reasoning_effort": REASONING_EFFORT} if self._reasoning_supported else {}

            try:
                response = self.client.chat.completions.create(
                    model=settings.MODEL_NAME,
                    temperature=TEMPERATURE,
                    max_tokens=MAX_TOKENS,
                    messages=messages,
                    **extra,
                )
                return response.choices[0].message.content or ""

            except GroqError as error:
                last_error = error
                text = str(error).lower()

                if self._reasoning_supported and "reasoning_effort" in text:
                    self._reasoning_supported = False
                    continue

                if "rate limit" in text or "429" in text:
                    wait = 5 * (attempt + 1)
                    logger.warning("Judge rate limited; waiting %ss", wait)
                    time.sleep(wait)
                    continue

                break

        logger.warning("Judge call failed: %s", last_error)
        raise LLMUpstreamError() from last_error


def _parse_verdicts(raw_output: str) -> dict:
    """
    Pull the JSON object out of whatever the model returned.

    A judge that returns unparseable output must not silently score as a pass,
    so every criterion it failed to answer is recorded as "error" and counted
    against it in the run summary.
    """

    text = (raw_output or "").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()

    payload: dict = {}

    start, end = text.find("{"), text.rfind("}")

    if start != -1 and end > start:
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            payload = {}

    verdicts = {}

    for criterion in CRITERIA:

        entry = payload.get(criterion["id"])

        if isinstance(entry, dict):
            verdict = str(entry.get("verdict", "")).strip().lower()
            reason = str(entry.get("reason", "")).strip()
        elif isinstance(entry, str):
            verdict, reason = entry.strip().lower(), ""
        else:
            verdict, reason = "error", "judge returned no verdict for this criterion"

        if verdict not in {"pass", "fail"}:
            verdict, reason = "error", reason or f"unrecognised verdict {entry!r}"

        verdicts[criterion["id"]] = {
            "name": criterion["name"],
            "verdict": verdict,
            "reason": reason,
        }

    return verdicts
