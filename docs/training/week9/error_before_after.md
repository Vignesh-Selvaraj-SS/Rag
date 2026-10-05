# Week 9 Task Set D — Docstring-as-prompt + recoverable error, before/after

**Tool changed:** `get_claim` on `mcp_servers/claims_status_server.py` (server two). Underlying error message lives in `app/services/agent_tools.py`'s `get_claim`, reused unchanged by the MCP wrapper — one source of truth, not duplicated logic.

**Same failing call, both runs:** `ClaimAgent().run("CLM-20010")` — a claim ID with one extra digit, a realistic typo of the real claim `CLM-2001`. Both transcripts below are real, live runs (`openai/gpt-oss-safeguard-20b` via Groq), captured by temporarily reverting the code to its old shape, running it, then restoring the new shape and running the identical query again — not hand-written.

## Before

**`get_claim`'s docstring** (old): *"Retrieve the case file for ONE claim by its claim ID... Only call this when the input actually names a claim ID (CLM-####)."* — describes the tool, gives no guidance on what to do if the ID turns out to be wrong.

**Error returned on a miss** (old): `{"error": "Error: lookup failed."}`

**What the model did:**

```
1. get_claim({"claim_id": "CLM-20010"}) -> {"error": "Error: lookup failed."}
2. flag_for_review({"claim_id": "CLM-20010", "reason": "Claim ID not found"})
   -> "Claim CLM-20010 flagged for human review: Claim ID not found"

Final answer: "Escalated for human review: Claim ID not found"
```

The model had no way to tell a typo apart from the claims system being genuinely down — exactly the failure mode Task Set D's common-mistakes section names. It gave up immediately and escalated a case that a one-digit correction would have resolved in the same turn.

## After

**`get_claim`'s docstring** (new): adds *"Claim IDs look like CLM-YYYY-nnnnn (e.g. CLM-2001). If this returns 'claim ... not found', that almost always means the ID doesn't match that shape, not that the claims platform is down — check the ID against the pattern and confirm it with the user before answering anything about coverage or payout with no claim actually loaded."* — this is the docstring functioning as a prompt: it tells the model what to *do*, not just what the tool *returns*.

**Error returned on a miss** (new): `{"error": "claim 'CLM-20010' not found: claim numbers look like CLM-YYYY-nnnnn, e.g. CLM-2001."}`

**What the model did:**

```
1. get_claim({"claim_id": "CLM-20010"})
   -> {"error": "claim 'CLM-20010' not found: claim numbers look like CLM-YYYY-nnnnn, e.g. CLM-2001."}

Final answer: "I couldn't find a claim with the ID CLM-20010. Could you double-check
the number (it should be in the form CLM-YYYY-nnnnn) and resend it?"
```

One step instead of two. No escalation. The model directly named the likely cause (a malformed ID) and asked the user to confirm it — the correct next action for a typo, which this almost certainly is.

## What actually changed the outcome

Two things moved together and both mattered: the **error string** now carries the expected format inline (so the model has the fact it needs, right when it needs it), and the **docstring** explicitly tells the model what a not-found error *means* and what to do about it (so the model has the instruction to act on that fact, not just the fact itself). Shipping either alone would likely have been weaker — the old docstring gave no reason to suspect a format problem even with a better error string, and a bare docstring change with the same vague error would have given the model good instructions with no data to apply them to.
