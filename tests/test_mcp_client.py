"""
Unit tests for MCPToolClient and MCPToolRegistry (app/services/mcp_client.py)
against the real Week 9 MCP servers - not a fake of either side. fastmcp's
Client accepts a live FastMCP server instance directly over an in-memory
transport, so these tests exercise the real discovery/dispatch/error-
handling logic with no network, no subprocess, and no Qdrant dependency
(the search_policy proxy only makes an HTTP call if actually invoked).
"""

from app.services.mcp_client import MCPToolClient, MCPToolRegistry
from mcp_servers.claims_status_server import mcp as claims_status_mcp
from mcp_servers.claims_system_server import mcp as claims_system_mcp


def _client() -> MCPToolClient:
    return MCPToolClient(claims_system_mcp)


def _status_client() -> MCPToolClient:
    return MCPToolClient(claims_status_mcp)


def _registry() -> MCPToolRegistry:
    # Bypasses mcp_config.json entirely - the two real, live server
    # instances, in-memory, is what this file wants to prove works, not
    # file-reading (test_mcp_registry_reads_the_config_file_format below
    # covers that separately).
    return MCPToolRegistry(servers=[
        {"name": "claims-system", "url": claims_system_mcp},
        {"name": "claims-status-platform", "url": claims_status_mcp},
    ])


def test_list_tool_schemas_discovers_every_server_one_tool_in_groq_shape():

    # Week 9 Task Set D split get_claim onto a second server
    # (claims_status_server.py) - server one is these five now.
    schemas = _client().list_tool_schemas()
    names = {schema["function"]["name"] for schema in schemas}

    assert names == {"search_policy", "list_documents", "compute_payout", "check_settlement_authority", "flag_for_review"}
    for schema in schemas:
        assert schema["type"] == "function"
        assert schema["function"]["description"]  # every tool has a real docstring
        assert "parameters" in schema["function"]


def test_call_tool_does_pure_arithmetic_with_no_lookups():

    result = _client().call_tool(
        "compute_payout",
        {"claimed_amount": 6000, "excess_amount": 500, "claim_status": "approved"},
    )

    assert result["result"] == {"claim_status": "approved", "payout": 5500.0}


def test_call_tool_on_an_unknown_name_returns_an_error_not_a_crash():

    result = _client().call_tool("delete_everything", {})

    assert "error" in result
    assert "delete_everything" in result["error"]


def test_claims_status_server_exposes_only_get_claim():

    schemas = _status_client().list_tool_schemas()
    names = {schema["function"]["name"] for schema in schemas}

    assert names == {"get_claim"}


def test_claims_status_server_call_tool_returns_a_real_get_claim_result():

    result = _status_client().call_tool("get_claim", {"claim_id": "CLM-2001"})

    assert result["result"]["claim_id"] == "CLM-2001"
    assert result["result"]["claimed_amount"] == 6000


def test_claims_status_server_get_claim_error_is_recoverable():

    # Week 9 Task Set D: names the claim ID that failed and the expected
    # format - see docs/training/week9/error_before_after.md.
    result = _status_client().call_tool("get_claim", {"claim_id": "NOPE-9999"})

    assert "error" in result
    assert "NOPE-9999" in result["error"]
    assert "CLM-YYYY-nnnnn" in result["error"]


# --------------------------------------------------------------- registry

def test_registry_merges_tool_schemas_across_both_servers():

    names = {schema["function"]["name"] for schema in _registry().list_tool_schemas()}

    assert names == {
        "search_policy", "list_documents", "compute_payout",
        "check_settlement_authority", "flag_for_review", "get_claim",
    }


def test_registry_routes_a_call_to_whichever_server_declared_the_tool():

    registry = _registry()
    registry.list_tool_schemas()  # discovery always precedes a call, per agent_service.py's _tools_for

    # From server one:
    payout = registry.call_tool("compute_payout", {"claimed_amount": 6000, "excess_amount": 500, "claim_status": "approved"})
    assert payout["result"]["payout"] == 5500.0

    # From server two - the one Task Set D adds via config only:
    claim = registry.call_tool("get_claim", {"claim_id": "CLM-2001"})
    assert claim["result"]["claim_id"] == "CLM-2001"


def test_registry_errors_on_a_tool_no_configured_server_declared():

    registry = _registry()
    registry.list_tool_schemas()

    result = registry.call_tool("delete_everything", {})

    assert "error" in result
    assert "delete_everything" in result["error"]


def test_registry_reads_the_config_file_format(tmp_path):

    # Proves the production path (config_path, not the servers= override
    # every other test here uses) parses mcp_config.json's real shape.
    config_file = tmp_path / "mcp_config.json"
    config_file.write_text(
        '{"servers": [{"name": "claims-system", "url": "http://127.0.0.1:8100/mcp"}]}',
        encoding="utf-8",
    )

    registry = MCPToolRegistry(config_path=config_file)

    assert set(registry._clients) == {"claims-system"}
    assert registry._clients["claims-system"].server == "http://127.0.0.1:8100/mcp"
