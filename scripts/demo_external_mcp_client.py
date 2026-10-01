"""
Week 9 deliverable: proof that "someone else's agent" - a client that has
never heard of ClaimAgent, MCPToolClient/MCPToolRegistry, or anything in
app/services/ - can discover and call both claims MCP servers. This script
uses nothing from this app's agent code, only fastmcp's own generic
Client talking to each server over the network, exactly as an unrelated
team's agent would.

Connects to BOTH servers deliberately - Task Set D's whole point is that
they're genuinely separate processes (get_claim moved to its own server,
claims_status_server.py, specifically to prove the agent picks up a whole
new server from config alone, not just a new function on the one it
already had). See docs/training/week9/task_set_d.md.

Run both servers first, each in its own terminal:
    python -m mcp_servers.claims_system_server     # :8100
    python -m mcp_servers.claims_status_server      # :8101

Then, from anywhere (this script only needs the two URLs - it never
imports app.services.agent_service or app.services.mcp_client):
    python scripts/demo_external_mcp_client.py

Note: claims_system_server's search_policy additionally needs the main
FastAPI app running (`uvicorn app.main:app`) - it proxies retrieval there
rather than opening a second Qdrant client (see
mcp_servers/http_retriever_proxy.py). This script only calls
compute_payout and get_claim, neither of which has that dependency, so it
stays runnable with just the two MCP servers up.
"""

import asyncio
import json
import sys

from fastmcp import Client

CLAIMS_SYSTEM_URL = "http://127.0.0.1:8100/mcp"     # server one: 5 tools
CLAIMS_STATUS_URL = "http://127.0.0.1:8101/mcp"     # server two: get_claim


async def main() -> None:

    print(f"Connecting to {CLAIMS_SYSTEM_URL} (server one) as a generic MCP client...\n")
    async with Client(CLAIMS_SYSTEM_URL) as client:
        tools = await client.list_tools()
        print(f"Discovered {len(tools)} tools - never hard-coded in this script:")
        for tool in tools:
            print(f"  - {tool.name}: {tool.description[:70]}...")

        print("\nCalling compute_payout(claimed_amount=6000, excess_amount=500, claim_status='approved'):")
        payout = await client.call_tool(
            "compute_payout",
            {"claimed_amount": 6000, "excess_amount": 500, "claim_status": "approved"},
        )
        print(" ", json.dumps(payout.data, indent=2))

    print(f"\nConnecting to {CLAIMS_STATUS_URL} (server two - added this task) as a generic MCP client...\n")
    async with Client(CLAIMS_STATUS_URL) as client:
        tools = await client.list_tools()
        print(f"Discovered {len(tools)} tool(s):")
        for tool in tools:
            print(f"  - {tool.name}: {tool.description[:70]}...")

        print("\nCalling get_claim('CLM-2001'):")
        claim = await client.call_tool("get_claim", {"claim_id": "CLM-2001"})
        print(" ", json.dumps(claim.data, indent=2))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        asyncio.run(main())
    except Exception as error:
        print(f"\nCould not reach a server - are both running? ({error})")
        print("Start them first: python -m mcp_servers.claims_system_server")
        print("             and: python -m mcp_servers.claims_status_server")
        raise SystemExit(1) from None
