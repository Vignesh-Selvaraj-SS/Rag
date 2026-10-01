# Week 9 — MCP, Multi-agent & A2A (Track D: Insurance Claims)

**Task:** Connect the agent to a tool over MCP so it discovers the tool instead of it being wired in by hand, then build a small MCP server exposing one real capability of the app that another agent could call.

> This document covers the initial build-week work (concepts, the first
> server, ClaimAgent's MCP client). The actual graded deliverable, **Task
> Set D**, is a separate, more specific exercise on top of this - see
> `docs/training/week9/task_set_d.md` for that one: the config-only
> second-server proof, the annotated raw wire exchange, the docstring/error
> rewrite, and the risk note.

## 1. What MCP actually is (the plain-words answer)

MCP (Model Context Protocol) is a standard "socket" between an AI and the tools/data it uses - the same idea as USB standardizing how peripherals plug into a computer. Before this week, every tool `ClaimAgent` could call was a Python function imported directly and dispatched by an `if tool_name == "...":` chain in `agent_service.py`. That only works for *this* agent, calling *this* code, in *this* process. MCP replaces that with a client/server split: a server declares what it can do, and any MCP-speaking client can discover and call it - not just the client that happened to be written for it.

**The three roles, and where the AI runs (the mentor's own question):**

| Role | What it is here | Runs an LLM? |
|---|---|---|
| Host | The process making decisions - `ClaimAgent`, running inside our FastAPI app | **Yes** - this is the only place Groq is ever called |
| Client | `app/services/mcp_client.py`'s `MCPToolClient` - the host's connection to one server | No |
| Server | `mcp_servers/claims_system_server.py` - a separate, standalone process | **No, never** |

The claims-system server only executes deterministic lookups and arithmetic (a dict lookup, a subtraction, a table scan). It has no idea an LLM exists, and it never runs one. This is true of MCP servers generally: they expose capabilities, not intelligence. Swapping which model powers `ClaimAgent` (as this session did more than once, chasing Groq's daily quota) never requires touching the server at all - that's the actual payoff of the split.

## 2. What was built

- **`mcp_servers/claims_system_server.py`** - a FastMCP server exposing 6 tools (`search_policy`, `list_documents`, `get_claim`, `compute_payout`, `check_settlement_authority`, `flag_for_review`) over streamable HTTP (`http://127.0.0.1:8100/mcp`). Each is a thin, typed wrapper around the *actual, unchanged* functions in `app/services/agent_tools.py` - FastMCP generates the JSON schema a client sees straight from the wrapper's type hints and docstring, so no schema was hand-written for these tools this time.
- **`app/services/mcp_client.py`** - `MCPToolClient`, a synchronous-facing wrapper around fastmcp's (necessarily async) client, so `ClaimAgent` - built around a blocking Groq client from Week 7 - never had to become async. All async machinery lives in this one file.
- **`app/services/agent_service.py`** rewritten: `_call_tool` is now one line (`return self.mcp_client.call_tool(tool_name, args)`) - no per-tool branches. `_tools_for` discovers the server's current tool list live, every `run()` call, instead of importing a static schema dict.
- **`scripts/demo_external_mcp_client.py`** - a standalone script with zero imports from this app's agent code, proving a genuinely unrelated client can discover and call the server.

## 3. Mentor checklist, mapped to evidence

| # | Check | Evidence |
|---|---|---|
| 1 | Does the agent use a tool through MCP, discovered rather than hard-coded? | `agent_service.py`'s `_tools_for` calls `self.mcp_client.list_tool_schemas()` live; `_call_tool` dispatches generically. Live-verified: `ClaimAgent().run("CLM-2001")` end to end, real Groq call, real MCP round trips for every tool - see §5. |
| 2 | Can they add a second tool without changing the agent's code? | `test_triage_tools_include_a_brand_new_mcp_tool_with_no_code_change` (`tests/test_agent_service.py`) - a fake server exposes a tool `ClaimAgent` has never heard of, and it appears in the tools sent to the model, with zero edits to `agent_service.py`. To prove it live: add one more `@mcp.tool` function to `claims_system_server.py`, restart the server, run the agent again - no other file changes. |
| 3 | Did they build their own server that another person's agent could call? | `scripts/demo_external_mcp_client.py` - imports nothing from `app/services/agent_service.py` or `mcp_client.py`, only fastmcp's generic `Client`. Run live (§5): discovers all 6 tools, calls two of them, gets real data back. |
| 4 | Can they explain, in plain words, where the AI runs and where it doesn't? | §1's table. The server process has never made a Groq call, ever - by construction, not by convention. |

## 4. A real bug found live, and its fix (not part of the checklist, found doing this work)

Running the new MCP server and the existing FastAPI app at the same time crashed the *second* one to touch retrieval, with `RuntimeError: Storage folder .qdrant is already accessed by another instance of Qdrant client`. Reproduced directly, not hypothesized: the claims-system server's `search_policy` used to open its own `RetrievalService` (hence its own embedded-Qdrant client), and the main app already legitimately needs its own for Chat/Documents/Evaluation - embedded Qdrant locks its storage folder to exactly one process.

**Fix**: `mcp_servers/http_retriever_proxy.py` - `search_policy` now proxies to the main app's own `POST /api/v1/search` over HTTP instead of opening a second Qdrant client. `agent_tools.py` didn't change at all (the proxy just implements the same `.retrieve()` shape `RetrievalService` does). The other 5 tools are unaffected - `get_claim`/`compute_payout`/`check_settlement_authority`/`flag_for_review` never touch Qdrant, and `list_documents` only lists files on disk.

**The tradeoff, stated plainly**: `search_policy` now has a real runtime dependency on the main app being up. The other 5 tools remain fully standalone (this is why the demo script in §3 deliberately calls `get_claim`/`compute_payout`, not `search_policy` - it needs nothing else running to prove the point). Verified live, both processes running at once (§5).

## 5. Live verification (real Groq calls, real MCP round trips, both processes running simultaneously)

```
ClaimAgent().run("CLM-2001")
  1 get_claim
  2 search_policy       <- proxied through the main app's /api/v1/search
  3 compute_payout
  4 check_settlement_authority
  5 finish
stopped_reason: finished | decision: approved | payout: 5500.0 | tokens: 9970
```

```
python scripts/demo_external_mcp_client.py
Discovered 6 tools - never hard-coded in this script:
  - search_policy, list_documents, get_claim, compute_payout,
    check_settlement_authority, flag_for_review
Calling get_claim('CLM-2001'): {claim_id, claimed_amount: 6000, ...}
Calling compute_payout(6000, 500, 'approved'): {payout: 5500.0}
```

## 6. How to run this (two processes, in either order)

```powershell
# Terminal 1 - the main app (Chat/Documents/Evaluation/Agent UI)
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload

# Terminal 2 - the claims-system MCP server (search_policy needs Terminal 1 up)
.\.venv\Scripts\python.exe -m mcp_servers.claims_system_server
```

`ClaimAgent` reads `MCP_SERVER_URL` from `.env`/`app/core/config.py` (default `http://127.0.0.1:8100/mcp`, matching the server's own default port).

## 7. Scope notes

- `fixed_claim_workflow.py` (the deterministic Week 7/8 racing baseline) still calls `agent_tools.py`'s functions directly, unchanged - the task asks to connect *the agent* to MCP, and that baseline is explicitly not the agent.
- Triage mode sends every tool the server discovers, unfiltered (the literal "add a tool, no code change" property); a general policy question still gets a curated subset (`search_policy`, `list_documents`) - a business-scoping decision, not a hard-coded schema, since `get_claim`/`compute_payout`/etc. never make sense for a question with no claim to pull.
- Full test suite: 155 passing, including 5 new tests for `HttpRetrieverProxy` (mocked HTTP, no live server needed) and 5 for `MCPToolClient` against the real server in-memory (fastmcp's in-process transport - no network, no subprocess).
