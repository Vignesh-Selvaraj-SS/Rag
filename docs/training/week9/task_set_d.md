# Week 9 Task Set D — "Bolt on the claims-system server without touching the agent"

**Problem statement's fiction:** the claims platform team stood up an MCP server exposing claim status + adjuster note history, and wants it used before Monday's caseload triage — no code release. Task: prove your agent's MCP discovery was real by adding this second server with config only.

## The two servers

| | Server one (pre-existing) | Server two (new this task) |
|---|---|---|
| File | `mcp_servers/claims_system_server.py` | `mcp_servers/claims_status_server.py` |
| MCP name | `claims-system` | `claims-status-platform` |
| Port | 8100 | 8101 |
| Tools | `search_policy`, `list_documents`, `compute_payout`, `check_settlement_authority`, `flag_for_review` (5) | `get_claim` (1) |

`get_claim` moved off server one specifically to make this task's proof meaningful: if it had stayed on server one, "adding server two" wouldn't hand the agent anything new to demonstrate.

## Rubric, mapped to evidence

| # | Criterion | Points | Evidence |
|---|---|---|---|
| 1 | Config-only server swap, zero changed lines in the agent module | 30 | `agent_diff.txt` — 0 bytes, `diff -u` exit code 0, real plain-file diff (not `git diff`; nothing this session is committed) between `agent_service.py` snapshotted right before and right after `mcp_config.json` gained server two. `config_diff.txt` shows the only actual change: one new `{"name": "claims-status-platform", "url": "..."}` entry. |
| 2 | Raw `initialize`/`tools/list`/`tools/call` captured and annotated, model-call location stated | 25 | `wire.json` — 4 real exchanges (`initialize`, `notifications/initialized`, `tools/list`, `tools/call`) captured with plain `httpx.post` against the live server two (not fastmcp's `Client`, specifically to see real wire bytes), every top-level field annotated by hand. `model_call_location` field states it directly: no LLM call occurs anywhere in this exchange - the model only exists in `ClaimAgent`, a separate process. |
| 3 | Docstring-as-prompt + recoverable-error rewrite, evidenced by a real before/after transcript | 20 | `error_before_after.md` — `get_claim`'s docstring rewritten to tell the model what a not-found error means and what to do about it; its error message rewritten from `"Error: lookup failed."` to name the claim ID tried and the expected `CLM-YYYY-nnnnn` format. Two live runs of the identical failing query (`CLM-20010`, a one-digit typo of the real `CLM-2001`) captured by temporarily reverting the code, running it, then restoring it and running again. |
| 4 | Tool count before → after, with names, from `tools/list` | 15 | Live, via the real agent's own `MCPToolRegistry` (not notes): **before, 5** (`check_settlement_authority`, `compute_payout`, `flag_for_review`, `list_documents`, `search_policy`) → **after, 6** (+ `get_claim`, live-confirmed present in a real `ClaimAgent().run("CLM-2001")` trace, step 1). |
| 5 | Five-line third-party risk note | 10 | `risk_note.md` — who wrote it, what it can reach, what it logs, what a stolen token could do, ship or don't. |

## How the config-only mechanism actually works

`app/services/agent_service.py`'s `ClaimAgent.__init__` does `self.mcp_client = mcp_client or MCPToolRegistry()` — a `MCPToolRegistry` (`app/services/mcp_client.py`) that reads `mcp_config.json`'s `"servers"` list, builds one `MCPToolClient` per entry, and on every `run()` call:

1. `list_tool_schemas()` — connects to *every* configured server, merges their `tools/list` results, remembers which server owns each tool name.
2. `call_tool(name, args)` — routes to whichever server last declared that name.

Neither method's code, nor `agent_service.py`'s constructor, nor the class `MCPToolRegistry` itself changed between the 5-tool and 6-tool states — only `mcp_config.json`'s content did. This is the literal mechanism `agent_diff.txt` proves, not just an assertion.

## Live proof, both servers running

```
BEFORE (server one only): 5 tools
 - check_settlement_authority
 - compute_payout
 - flag_for_review
 - list_documents
 - search_policy

AFTER (server one + two): 6 tools
 - check_settlement_authority
 - compute_payout
 - flag_for_review
 - get_claim        <- NEW, from server two
 - list_documents
 - search_policy
```

```
ClaimAgent().run("CLM-2001")
  step 1: get_claim({"claim_id": "CLM-2001"})   <- provably from server two;
          server one no longer has this tool at all
  -> {"result": {"claim_id": "CLM-2001", "claimed_amount": 6000, ...}}
```

## Common mistakes, checked against

- **Hard-coding the tool list after connecting** — not done: `_tools_for` in `agent_service.py` calls `self.mcp_client.list_tool_schemas()` fresh every `run()`, never a name literal for `get_claim` anywhere in that file.
- **An LLM call inside the MCP server** — not present in either server; both are plain FastMCP tool functions delegating to `agent_tools.py`'s deterministic functions. Confirmed in `wire.json`'s `model_call_location` field.
- **Exposing context as a tool** — `get_claim` genuinely is model-invoked per-claim (the model chooses which claim to look up), not static context every call needs, so it correctly stays a tool, not a resource.
- **Swallowing the unknown-claim case into a generic failure** — exactly the bug this task's own error-rewrite section fixes; see `error_before_after.md`.
- **Adding the third-party server without asking what it can reach** — addressed directly in `risk_note.md`.

## Deliverable files (submission checklist)

- `agent_diff.txt` — 0 changed lines ✅
- `config_diff.txt` — the one-line server-two addition ✅
- `wire.json` — annotated raw exchange ✅
- Tool count line — 5 → 6, with names (above) ✅
- `error_before_after.md` ✅
- `risk_note.md` — exactly 5 lines ✅
