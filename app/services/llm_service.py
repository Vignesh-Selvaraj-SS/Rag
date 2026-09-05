import logging
import re

from groq import Groq, GroqError

from app.core.config import settings
from app.core.errors import LLMNotConfiguredError, LLMUpstreamError

logger = logging.getLogger(__name__)

REFUSAL_MESSAGE = "I don't know - the documents provided don't cover this."

# Fixed generation settings, not configurable. Zero temperature means the
# same question gives the same answer every time - not something anyone
# would want to change per deployment. The token cap just bounds cost.
TEMPERATURE = 0.0
MAX_TOKENS = 800

# Bump this whenever SYSTEM_PROMPT or the user prompt below changes. A trace
# that records the version can be replayed later even once the prompt has
# moved on; a trace without one is only replayable by luck.
PROMPT_VERSION = "v1"

SYSTEM_PROMPT = f"""
You are a claims documentation assistant for Meridian Mutual.

You answer ONLY from the numbered sources given to you in the user
message.

Rules:

1. If the answer is not available in the sources,
reply exactly:

"{REFUSAL_MESSAGE}"

Do not use outside knowledge, even if you know the answer generally.

2. Cite after every fact using the source tags, for example [S1].
Never invent a tag you were not given.

3. Quote figures, limits, deductibles and deadlines exactly as they
appear. Do not round or estimate them.

4. Be brief. Two or three sentences is usually right.
"""


class LLMService:
    """
    Service responsible for generating grounded answers.
    """

    def __init__(self):

        self.client = Groq(
            api_key=settings.GROQ_API_KEY
        ) if settings.GROQ_API_KEY else None

    def generate_answer(self, question: str, hits: list[dict]) -> dict:

        if self.client is None:
            raise LLMNotConfiguredError()

        sources = "\n\n".join(
            f"[S{number}] file: {hit['source']} | "
            f"section: {hit['heading']} | {hit['page']}\n{hit['text']}"
            for number, hit in enumerate(hits, start=1)
        )

        prompt = (
            f"SOURCES\n{sources}\n\n"
            f"QUESTION: {question}\n\n"
            f"Answer using only the sources above, citing [S1]-style tags. "
            f'If the answer is not there, reply exactly: "{REFUSAL_MESSAGE}"'
        )

        try:
            response = self.client.chat.completions.create(
                model=settings.MODEL_NAME,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
        except GroqError as error:
            logger.warning("Groq call failed: %s: %s", type(error).__name__, error)
            raise LLMUpstreamError() from error

        raw_output = response.choices[0].message.content or ""

        text = raw_output.strip()

        # Verify citations against what was actually given - never trust
        # a [S#] tag the model emits without checking it's in range.
        cited = []
        invalid = []

        for tag in re.findall(r"\[S(\d+)\]", text):

            number = int(tag)

            if 1 <= number <= len(hits):
                if number not in cited:
                    cited.append(number)
            else:
                invalid.append(f"[S{tag}]")

        refused = (
            REFUSAL_MESSAGE.lower() in text.lower()
            or text.lower().startswith("i don't know")
        )

        return {
            "answer": text,
            "cited": cited,
            "invalid_citations": invalid,
            "refused": refused,
            # Kept separate from "answer" so a trace records what the model
            # actually emitted, not just what survived parsing.
            "raw_output": raw_output,
            "prompt_version": PROMPT_VERSION,
            "temperature": TEMPERATURE,
            "max_tokens": MAX_TOKENS,
        }
