"""
A synchronous-facing wrapper around fastmcp's (necessarily async) client,
so ClaimAgent - and the rest of this fully synchronous codebase, built
around a blocking Groq client - never has to become async just to talk to
an MCP server. All async machinery lives in this one file; everywhere
else stays exactly as sync as before.

Each call opens a fresh MCP session (`asyncio.run(...)` per call) rather
than holding one connection open across the agent's whole run - simpler,
and this app is single-worker, low-QPS (a bootcamp claims-triage tool, not
a production message queue), so one extra connection-setup round trip per
tool call is negligible next to the ~1-30s Groq call latency already
dominating every step's wall-clock time.
"""

import asyncio
import json
import logging
from pathlib import Path

from fastmcp import Client
from fastmcp.exceptions import ClientError, ToolError

logger = logging.getLogger(__name__)


class MCPToolClient:
    """
    Discovers and calls tools from one MCP server, synchronously.

    `server` is normally a URL string (e.g. settings.MCP_SERVER_URL, a
    streamable-HTTP endpoint) but fastmcp's own Client also accepts a live
    FastMCP server instance directly, over an in-memory transport with no
    network or process involved - what tests/test_mcp_client.py uses to
    exercise this real class against the real server, hermetically.
    """

    def __init__(self, server):
        self.server = server

    def list_tool_schemas(self) -> list[dict]:
        """
        The server's tools, translated into the OpenAI/Groq function-calling
        schema shape ClaimAgent already sends as `tools=` - so switching a
        tool's SOURCE (local vs. MCP-discovered) never changes the shape the
        rest of agent_service.py works with. This is the actual "discovery"
        step: nothing here is a hard-coded list of tool names.
        """

        async def _list() -> list:
            async with Client(self.server) as client:
                return await client.list_tools()

        tools = asyncio.run(_list())

        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    "parameters": tool.inputSchema,
                },
            }
            for tool in tools
        ]

    def call_tool(self, name: str, args: dict) -> dict:
        """
        Executes one tool call on the MCP server, returning its result dict
        exactly as the tool produced it (e.g. `{"result": ...}` or
        `{"error": ...}` - agent_tools.py's own functions never raise for a
        bad-but-plausible call, they return an error dict, and that contract
        survives the trip through MCP unchanged). A genuine MCP-layer
        failure (server unreachable, unknown tool, protocol error) is
        caught here and turned into the same `{"error": ...}` shape, so a
        broken connection costs one step, not a crash.
        """

        async def _call():
            async with Client(self.server) as client:
                return await client.call_tool(name, args)

        try:
            result = asyncio.run(_call())
        except (ToolError, ClientError) as error:
            logger.warning("MCP tool call to %r failed: %s", name, error)
            return {"error": f"MCP tool call to {name!r} failed: {error}"}
        except Exception as error:  # connection refused, timeout, etc.
            logger.warning("MCP server unreachable calling %r: %s", name, error)
            return {"error": f"MCP server unreachable calling {name!r}: {error}"}

        return result.data


class MCPToolRegistry:
    """
    Fans out over every MCP server named in a config file (mcp_config.json
    by default) - one MCPToolClient per server - merging their discovered
    tools into one list and routing each tool call to whichever server
    actually declared that name.

    This is what ClaimAgent talks to (agent_service.py's self.mcp_client),
    not a single MCPToolClient directly. Week 9 Task Set D's entire
    exercise is proving that adding a server means editing the config
    file's "servers" list - never this class, MCPToolClient, or
    agent_service.py. See agent_diff.txt and
    docs/training/week9/task_set_d.md.
    """

    def __init__(self, config_path: Path | None = None, servers: list[dict] | None = None):
        """
        `servers` (a list of {"name", "url"} dicts) lets a test build a
        registry without a config file on disk. Production always goes
        through `config_path` (default settings.MCP_CONFIG_PATH) - imported
        lazily to avoid a hard dependency on app.core.config for a class
        that's equally useful pointed at any JSON file.
        """

        if servers is None:
            if config_path is None:
                from app.core.config import settings
                config_path = settings.MCP_CONFIG_PATH
            servers = json.loads(config_path.read_text(encoding="utf-8"))["servers"]

        self._clients = {entry["name"]: MCPToolClient(entry["url"]) for entry in servers}
        self._server_by_tool_name: dict[str, str] = {}

    def list_tool_schemas(self) -> list[dict]:
        """Discovers every server's tools fresh, remembering which server owns each name for call_tool."""

        schemas = []
        self._server_by_tool_name = {}

        for server_name, client in self._clients.items():
            for schema in client.list_tool_schemas():
                tool_name = schema["function"]["name"]
                self._server_by_tool_name[tool_name] = server_name
                schemas.append(schema)

        return schemas

    def call_tool(self, name: str, args: dict) -> dict:
        """Routes to the server list_tool_schemas() last saw declare this tool name."""

        server_name = self._server_by_tool_name.get(name)

        if server_name is None:
            return {"error": f"Unknown tool {name!r} - not declared by any configured MCP server."}

        return self._clients[server_name].call_tool(name, args)
