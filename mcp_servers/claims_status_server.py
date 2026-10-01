"""
Week 9 Task Set D - "server two": the claims platform team's new server,
added to prove that ClaimAgent's MCP discovery was real, not hard-coded.

The task's fiction: the platform team stood up a server exposing claim
status by claim number and the adjuster note history behind it, and wants
it used before Monday's caseload triage - without a code release. This
file plays that role. It is a genuinely separate process (own port,
own name, own `mcp.run()`), not a second tool added to
claims_system_server.py, because the point being proven is "the agent
picks up a whole new SERVER from config alone," not just a new function.

Run standalone:
    python -m mcp_servers.claims_status_server

Adding it to the agent is a config-only change - one more entry in
mcp_config.json's "servers" list. app/services/agent_service.py and
app/services/mcp_client.py do not change; see
docs/training/week9/task_set_d.md and agent_diff.txt for the proof.

Reuses agent_tools.get_claim unchanged - this server is a thin, typed
adapter, exactly like claims_system_server.py's tools (see that file's
docstring). get_claim's own error message was rewritten this week to be
recoverable (names the claim ID that failed and the expected format,
CLM-YYYY-nnnnn) instead of a bare lookup failure - see
docs/training/week9/error_before_after.md for the before/after model
transcript this produced.
"""

from fastmcp import FastMCP

from app.core.config import settings
from app.services import agent_tools

mcp = FastMCP(
    name="claims-status-platform",
    instructions=(
        "Claim status and adjuster note history, by claim number, from the "
        "claims platform. Deterministic lookup only - no model runs on "
        "this server. For policy coverage rules, payout arithmetic, "
        "settlement authority or escalation, see the separate "
        "claims-system server."
    ),
)


@mcp.tool
def get_claim(claim_id: str) -> dict:
    """
    Retrieve the case file for ONE claim by its claim ID: claimed amount,
    policy form and endorsements attached, and the adjuster's notes
    describing what happened. The only tool that returns claim-specific
    facts - never policy wording, exclusions or deductible amounts.

    Claim IDs look like CLM-YYYY-nnnnn (e.g. CLM-2001). If this returns
    "claim ... not found", that almost always means the ID doesn't match
    that shape, not that the claims platform is down - check the ID
    against the pattern and confirm it with the user before answering
    anything about coverage or payout with no claim actually loaded.
    """

    return agent_tools.get_claim({"claim_id": claim_id})


if __name__ == "__main__":
    mcp.run(transport="http", host=settings.MCP_SERVER_HOST, port=settings.CLAIMS_STATUS_SERVER_PORT)
