"""
The two tools the claim-resolution agent can call.

Kept to exactly two, deliberately: the Week 7 task's own advice is to build
the loop by hand rather than reach for a framework, so the tool surface
stays small enough to read in one sitting. Each tool wraps a service that
already exists elsewhere in the app - no new retrieval or document logic is
introduced here, only a thin, LLM-describable interface over it.

Every tool function takes a single `args: dict` (as parsed from the model's
JSON action) and returns a small dict the agent logs and feeds back into the
next prompt. A tool never raises for a bad but plausible call (e.g. an
unknown source name) - it returns an error string in the result instead, so
a single bad tool call costs one step, not the whole run.
"""

from app.core.config import settings
from app.services.document_loader import SUPPORTED_EXTENSIONS
from app.services.retrieval_service import RetrievalService

# How much chunk text is shown to the agent per hit. Found the hard way,
# live: 320 chars cut off a real chunk (claims-adjuster-authority.md's
# settlement-authority table) right before the dollar figures it holds -
# the agent could see the chunk existed but never the numbers in it, and
# burned its whole step budget re-searching for a fact it could never see.
# 1200 comfortably covers this corpus's longest heading-based chunks
# (short intro sentence + a markdown table); llm_service.py and
# summary_service.py never truncate chunk text at all for the same reason.
SNIPPET_CHARS = 1200


def search_policy(retriever: RetrievalService, args: dict) -> dict:
    """
    Search the indexed policy documents. Optionally scoped to one file name
    (from list_documents) - the agent's way of "looking something up in a
    specific document" once it knows that document exists.
    """

    query = str(args.get("query") or "").strip()

    if not query:
        return {"error": "search_policy needs a non-empty 'query'."}

    source = args.get("source") or None
    top_k = int(args.get("top_k") or 5)
    top_k = max(1, min(top_k, 10))

    retrieval = retriever.retrieve(query, top_k=top_k, mode="hybrid", source=source)
    hits = retrieval["hits"]

    if not hits:
        return {"result": f"No chunks found for query {query!r}" + (f" in {source}" if source else "") + "."}

    return {
        "result": [
            {
                "source": hit["source"],
                "heading": hit["heading"],
                "page": hit["page"],
                "score": round(float(hit["dense_score"]), 3),
                "text": hit["text"][:SNIPPET_CHARS],
            }
            for hit in hits
        ]
    }


def list_documents(args: dict) -> dict:
    """
    Names of every indexed document, so the agent can decide to target a
    specific one (e.g. the claims procedure file) on a later search rather
    than guessing a source filename it was never told.
    """

    if not settings.DATA_DIR.exists():
        return {"result": []}

    names = sorted(
        path.name
        for path in settings.DATA_DIR.iterdir()
        if path.is_file()
        and not path.name.startswith(".")
        and path.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    return {"result": names}


# Tool schemas in the OpenAI/Groq function-calling shape. This model
# (openai/gpt-oss-20b) has a built-in, server-enforced notion of "the model
# called a tool" - asking it to hand-write tool-shaped JSON as plain text
# collides with that (Groq rejects it: "Tool choice is none, but model
# called a tool") rather than just being parsed as text. Declaring the
# tools properly through `tools=` and reading `message.tool_calls` uses the
# API the way it is actually built, instead of fighting it - this is still
# a hand-written loop (no LangChain/LangGraph), just the loop calls the
# chat API's own tool-calling parameter rather than reinventing a worse,
# less reliable version of it in prompt text.
#
# `finish` is declared as a tool like any other - the agent "calls" finish
# exactly the way it calls search_policy, so the loop needs no special
# prompt-level carve-out for ending the task.
TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_policy",
            "description": (
                "Search the indexed policy and procedure documents for text relevant to "
                "the query. Leave `source` unset to search everything. Set `source` to one "
                "exact file name (from list_documents) only once you already suspect the "
                "fact you need lives in that specific document - for example, once you "
                "suspect the answer depends on settlement authority or claims procedure "
                "rather than an endorsement."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look up."},
                    "source": {"type": "string", "description": "An exact file name to restrict the search to, or omit to search everything."},
                    "top_k": {"type": "integer", "description": "How many chunks to return, default 5."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_documents",
            "description": "List the exact file names of every indexed document, so a later search_policy call can name a document that actually exists.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "finish",
            "description": (
                "End the task with the final answer. Call this only once every distinct "
                "part of the claim description has been checked, not just the first part "
                "noticed - a claim naming two endorsements needs both looked up. Keep the "
                "answer to two or three sentences."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {
                        "type": "string",
                        "description": (
                            "The final answer, citing sources by file name and heading. "
                            "PLAIN TEXT ONLY - no markdown, no bold, no bullet points, no "
                            "line breaks, so the answer stays valid as one JSON string."
                        ),
                    },
                    "sources": {"type": "array", "items": {"type": "string"}, "description": "File names actually used."},
                },
                "required": ["answer"],
            },
        },
    },
]
