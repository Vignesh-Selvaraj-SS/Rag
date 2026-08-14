import re

from groq import Groq

from app.core.config import settings

REFUSAL_MESSAGE = "I don't know - the documents provided don't cover this."

# Fixed generation settings, not configurable. Zero temperature means the
# same question gives the same answer every time - not something anyone
# would want to change per deployment. The token cap just bounds cost.
TEMPERATURE = 0.0
MAX_TOKENS = 800

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

    @property
    def available(self) -> bool:
        return self.client is not None

    def generate_answer(self, question: str, hits: list[dict]) -> dict:

        if self.client is None:
            raise RuntimeError(
                "GROQ_API_KEY is not set. Copy .env.example to .env and "
                "add your key from https://console.groq.com/keys"
            )

        prompt = self._build_prompt(question, hits)

        response = self.client.chat.completions.create(
            model=settings.MODEL_NAME,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            messages=[
                {
                    "role": "system",
                    "content": SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ]
        )

        text = (response.choices[0].message.content or "").strip()

        cited, invalid = self._parse_citations(text, len(hits))

        refused = (
            REFUSAL_MESSAGE.lower() in text.lower()
            or text.lower().startswith("i don't know")
        )

        return {
            "answer": text,
            "cited": cited,
            "invalid_citations": invalid,
            "refused": refused,
        }

    @staticmethod
    def _build_prompt(question: str, hits: list[dict]) -> str:

        sources = "\n\n".join(
            f"[S{number}] file: {hit['source']} | "
            f"section: {hit['heading']} | {hit['page']}\n{hit['text']}"
            for number, hit in enumerate(hits, start=1)
        )

        return (
            f"SOURCES\n{sources}\n\n"
            f"QUESTION: {question}\n\n"
            f"Answer using only the sources above, citing [S1]-style tags. "
            f'If the answer is not there, reply exactly: "{REFUSAL_MESSAGE}"'
        )

    @staticmethod
    def _parse_citations(
        text: str,
        n_sources: int
    ) -> tuple[list[int], list[str]]:

        cited = []
        invalid = []

        for tag in re.findall(r"\[S(\d+)\]", text):

            number = int(tag)

            if 1 <= number <= n_sources:
                if number not in cited:
                    cited.append(number)
            else:
                invalid.append(f"[S{tag}]")

        return cited, invalid
