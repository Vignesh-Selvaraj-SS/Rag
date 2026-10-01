"""
Week 9 Task Set D - "server one": the agent's own, pre-existing MCP server
(5 tools: search_policy, list_documents, compute_payout,
check_settlement_authority, flag_for_review).

`get_claim` used to live here too (all 6 Week-9 tools, one server); Task
Set D deliberately moves it to a second, genuinely separate server
(claims_status_server.py) to prove the agent discovers tools rather than
having them wired in - see that file's docstring, and
docs/training/week9/task_set_d.md for the full before/after story.

Exposes tools over the Model Context Protocol as a standalone process any
MCP-speaking agent can discover and call - not just ours. This is the
"host never runs on the tool server" half of MCP: this process only
executes deterministic lookups/arithmetic against the claims data and the
policy index; no LLM call happens here, ever.

Reuses app/services/agent_tools.py's actual functions rather than
reimplementing their logic, so a fact this server returns is provably the
same lookup the rest of the app already trusts and has tests for. Each
`@mcp.tool` function below is a thin, typed adapter: FastMCP generates the
JSON schema MCP clients see from the function's type hints and docstring,
so the underlying `args: dict`-shaped functions in agent_tools.py don't
need to change - this server just translates.

Run standalone:
    python -m mcp_servers.claims_system_server

ClaimAgent discovers this server (and any others) from mcp_config.json via
app/services/mcp_client.py's MCPToolRegistry - not from a URL hard-coded
here or in agent_service.py.

search_policy needs the main FastAPI app (`uvicorn app.main:app`) running
too - it proxies to that app's own POST /api/v1/search rather than opening
a second, separate embedded-Qdrant client (see http_retriever_proxy.py for
why: Qdrant's local mode locks its storage folder to one process, and this
is a real conflict, reproduced, not a hypothetical one). Every other tool
here has no such dependency - compute_payout/etc. never touch Qdrant, and
list_documents only lists files on disk.
"""

from fastmcp import FastMCP

from app.core.config import settings
from app.services import agent_tools
from mcp_servers.http_retriever_proxy import HttpRetrieverProxy

mcp = FastMCP(
    name="claims-system",
    instructions=(
        "Tools for Meridian Mutual's insurance claims workflow: search the "
        "indexed policy/endorsement documents, compute a payout, check "
        "settlement authority, and escalate a claim for human review. "
        "Deterministic lookups and arithmetic only - no model runs on this "
        "server. For a specific claim's own case file (claim status, "
        "adjuster notes), see the separate claims-status-platform server."
    ),
)

# Makes no connection at construction time (only per-call, via httpx) -
# safe to build eagerly at import time, unlike a real RetrievalService.
_retriever = HttpRetrieverProxy()


@mcp.tool
def search_policy(query: str, source: str | None = None, top_k: int = 5) -> dict:
    """
    Search the indexed policy and procedure documents for text relevant to
    the query. Never returns claim-specific facts (amount, notes, peril) -
    that is get_claim's job. Never use this to check an adjuster's
    settlement authority - call check_settlement_authority instead, which
    is exact and faster than searching for the authority table in text.
    Leave `source` unset to search everything. Set `source` to one exact
    file name (from list_documents) only once you already suspect the fact
    you need lives in that specific document.
    """

    return agent_tools.search_policy(_retriever, {"query": query, "source": source, "top_k": top_k})


@mcp.tool
def list_documents() -> dict:
    """List the exact file names of every indexed document, so a later search_policy call can name a document that actually exists."""

    return agent_tools.list_documents({})


@mcp.tool
def compute_payout(claimed_amount: float, excess_amount: float, claim_status: str) -> dict:
    """
    Compute the payable amount after the excess/deductible has been
    subtracted. Call this only after you already know, from search_policy,
    whether the loss is covered and what deductible applies -
    claim_status must be one of 'approved', 'denied', 'partial'.
    """

    return agent_tools.compute_payout({
        "claimed_amount": claimed_amount,
        "excess_amount": excess_amount,
        "claim_status": claim_status,
    })


@mcp.tool
def check_settlement_authority(payout_amount: float) -> dict:
    """
    Look up which adjuster grade's settlement authority covers a payout
    amount. Does not decide coverage or compute the payout itself - call
    this only after compute_payout, to check who is allowed to approve the
    resulting number.
    """

    return agent_tools.check_settlement_authority({"payout_amount": payout_amount})


@mcp.tool
def flag_for_review(claim_id: str, reason: str) -> dict:
    """
    Escalate a claim for human review instead of finishing it - the only
    action/write tool available; every other tool reads or computes. Use
    this when the claim genuinely can't be resolved from the tools
    available (contradictory notes, a document the corpus doesn't have).
    """

    return agent_tools.flag_for_review({"claim_id": claim_id, "reason": reason})


if __name__ == "__main__":
    mcp.run(transport="http", host=settings.MCP_SERVER_HOST, port=settings.MCP_SERVER_PORT)
