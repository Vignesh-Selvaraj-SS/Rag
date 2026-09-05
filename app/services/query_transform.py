from groq import Groq

from app.core.config import settings

# Cached, same reasoning as every other lazily-built client/model in
# app/services/ - built once, reused across calls.
_client = None

REWRITE_SYSTEM_PROMPT = (
    "Rewrite the user's question into a single, clear, specific search "
    "query suitable for searching an insurance policy document. Keep "
    "any exact codes, numbers or names unchanged. Reply with ONLY the "
    "rewritten query, nothing else - no preamble, no quotes."
)

HYDE_SYSTEM_PROMPT = (
    "Write a short, plausible-sounding passage (2-3 sentences) in the "
    "style of an insurance policy document that would answer the "
    "user's question. It does not need to be factually correct - it "
    "only needs to read like real policy wording, so its phrasing can "
    "be compared against real document chunks. Reply with ONLY the "
    "passage, nothing else."
)


def _get_client():

    global _client

    if _client is None:
        _client = Groq(api_key=settings.GROQ_API_KEY) if settings.GROQ_API_KEY else None

    return _client


def _transform(question: str, system_prompt: str) -> str:
    """
    Shared plumbing for both transforms below: one short, cheap Groq
    call, falling back to the original question if no key is
    configured or the call fails - a transform step must never be the
    reason a search silently returns nothing.
    """

    client = _get_client()

    if client is None:
        return question

    try:
        response = client.chat.completions.create(
            model=settings.MODEL_NAME,
            temperature=0.0,
            # openai/gpt-oss-20b (and similar reasoning models) spend
            # hidden "thinking" tokens before any visible output - a
            # tight budget here returns an EMPTY response, not a short
            # one. Confirmed directly: 150 -> "", 400 -> a real answer.
            max_tokens=400,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": question},
            ],
        )
        text = (response.choices[0].message.content or "").strip()
        return text or question

    except Exception:
        return question


def rewrite_query(question: str) -> str:
    """
    Query rewriting: turn a messy, conversational question into a
    cleaner search query before it gets embedded. Exact codes/numbers
    are explicitly preserved by the prompt, since those matter for
    keyword/hybrid search downstream.
    """

    return _transform(question, REWRITE_SYSTEM_PROMPT)


def generate_hyde_passage(question: str) -> str:
    """
    HyDE (Hypothetical Document Embeddings): generate a fake but
    plausible-sounding answer passage, then embed THAT instead of the
    raw question. A fake answer's wording often resembles the real
    document's wording more closely than a question does, which can
    help dense search on questions phrased very differently from how
    the source documents are written.
    """

    return _transform(question, HYDE_SYSTEM_PROMPT)
