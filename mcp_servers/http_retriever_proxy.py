"""
A `RetrievalService`-shaped adapter that calls this app's own
`POST /api/v1/search` endpoint over HTTP instead of opening an embedded
Qdrant client directly.

Why: Qdrant's local/embedded mode locks its storage folder to one process.
The main FastAPI app already legitimately needs it (Chat, Documents,
Evaluation), and the claims-system MCP server used to open a second,
separate client for search_policy - a real, reproduced conflict (whichever
process touches Qdrant first wins the lock; the other hard-crashes with
"Storage folder .qdrant is already accessed by another instance"), not a
hypothetical one. Proxying through the already-running main app keeps
Qdrant access in exactly one place.

`agent_tools.search_policy(retriever, args)` only ever calls
`retriever.retrieve(question, top_k=..., min_score=..., source=..., mode=...)`
and reads `.hits` - so this class needs to match that shape and nothing
more; agent_tools.py itself never changes.
"""

import httpx

from app.core.config import settings


class HttpRetrieverProxy:
    """Same interface as RetrievalService.retrieve(), backed by an HTTP call instead of a local Qdrant client."""

    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        self.base_url = base_url or settings.MAIN_APP_URL
        self.timeout = timeout

    def retrieve(
        self,
        question: str,
        top_k: int | None = None,
        min_score: float | None = None,
        source: str | None = None,
        mode: str = "dense",
    ) -> dict:

        payload = {"question": question, "mode": mode}
        if top_k is not None:
            payload["top_k"] = top_k
        if min_score is not None:
            payload["min_score"] = min_score
        if source is not None:
            payload["source"] = source

        try:
            response = httpx.post(f"{self.base_url}/api/v1/search", json=payload, timeout=self.timeout)
            response.raise_for_status()
        except httpx.HTTPError as error:
            # Deliberately not swallowed into an empty-hits result - that
            # would look exactly like "nothing found" instead of "the main
            # app isn't reachable," which is a materially different, more
            # actionable failure. This propagates out of search_policy
            # uncaught, becomes a FastMCP ToolError, and surfaces to the
            # agent as a normal {"error": ...} tool result (see
            # app/services/mcp_client.py) - one wasted step, not a crash.
            raise RuntimeError(
                f"search_policy could not reach the main app's retrieval endpoint at "
                f"{self.base_url}/api/v1/search ({error}). Is `uvicorn app.main:app` running?"
            ) from error

        data = response.json()

        return {
            "question": data["question"],
            "hits": data["hits"],
            "best_score": data["best_score"],
            "passes_gate": data["passes_gate"],
            "min_score": data["min_score"],
        }
