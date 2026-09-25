# Third tool: description diff

The two starting tools for this extension (`app/services/triage_tools.py`):

- `get_claim(claim_id)` — claim-specific facts only: amount, policy form, adjuster notes.
- `search_policy(query, source?, top_k?)` — policy-wide text only: exclusions, endorsement wording, deductibles, authority limits.

`compute_payout` is the third tool added. Diff against the two-tool baseline:

```diff
 TRIAGE_TOOL_SCHEMAS = [
     _SEARCH_POLICY_SCHEMA,
     {
         "type": "function",
         "function": {
             "name": "get_claim",
             "description": (
                 "Retrieve the case file for ONE claim by its claim ID: claimed amount, "
                 "policy form and endorsements attached, and the adjuster's notes describing "
                 "what happened. This is the only tool that returns claim-specific facts - it "
                 "never returns policy wording, exclusions or deductible amounts. Call it "
                 "exactly once per claim, first."
             ),
             "parameters": {
                 "type": "object",
                 "properties": {
                     "claim_id": {"type": "string", "description": "The claim ID, e.g. 'CLM-2001'."},
                 },
                 "required": ["claim_id"],
             },
         },
     },
+    {
+        "type": "function",
+        "function": {
+            "name": "compute_payout",
+            "description": (
+                "Compute the payable amount after the excess/deductible has been subtracted. "
+                "Call this only after you already know, from search_policy, whether the loss "
+                "is covered and what deductible applies - this tool does no coverage lookups "
+                "of its own, it only does the arithmetic once you supply the numbers."
+            ),
+            "parameters": {
+                "type": "object",
+                "properties": {
+                    "claimed_amount": {"type": "number", "description": "The amount claimed."},
+                    "excess_amount": {"type": "number", "description": "The applicable deductible/excess. Use 0 if none applies or the claim is denied."},
+                    "claim_status": {
+                        "type": "string",
+                        "enum": ["approved", "denied", "partial"],
+                        "description": "Your coverage decision: 'approved' (fully covered), 'denied' (not covered, payout is 0), or 'partial' (part of the loss is excluded).",
+                    },
+                },
+                "required": ["claimed_amount", "excess_amount", "claim_status"],
+            },
+        },
+    },
     {
         "type": "function",
         "function": {
             "name": "finish",
             ...
```

## Why this passes the "one job, enum, no overlap" bar

- **One job.** `compute_payout` does exactly one thing — subtract the excess from the claimed amount, or return 0 if denied. It performs no retrieval and no coverage judgment; those stay with `search_policy` and the agent's own reasoning. Contrast with `get_claim` (returns facts, does no arithmetic) and `search_policy` (returns policy text, does no arithmetic) — none of the three tools' jobs overlap.
- **Enum, not free text.** `claim_status` is declared `"enum": ["approved", "denied", "partial"]`, not a free-text string. A malformed or synonymous status (`"accepted"`, `"Approved "`, `"rejected"`) is rejected by the API's own schema validation before it ever reaches `compute_payout`'s code, rather than silently producing a wrong number from a status string the function didn't recognize.
- **No description overlap.** `get_claim`'s description states up front it "never returns policy wording"; `search_policy`'s states it "never returns claim-specific facts"; `compute_payout`'s states it "does no coverage lookups of its own." Each tool's description names what it does *not* do, in the other tool's terms, specifically to close the ambiguity that causes tool-choice thrash on the next tool added later (the exact trap named in this task's common-mistakes list).

## The bug this design didn't catch, and the fix that did

The first live run against the real corpus found a live tool-choice bug anyway, just not the "overlap" kind: `search_policy`'s `source` parameter description told the model to use "one exact file name," but nothing in this tool set can tell the model what those file names *are* (unlike the original Week 7 agent, which has `list_documents` for exactly this). The model reliably guessed the endorsement code it already knew (`"HO-2026-01"`) instead, and an exact-match filter returned zero hits — wasting a step, every time, on every claim that named an endorsement.

Prompt wording alone didn't fix it (tried first, still guessed). Fixed at the code level instead: `search_policy` (`app/services/agent_tools.py`) now resolves a given `source` against the real corpus by case-insensitive substring match before querying, so `"HO-2026-01"` resolves to `endorsement-HO-2026-01-water-backup.md` automatically. Covered by a regression test (`test_search_policy_resolves_a_guessed_endorsement_code_to_the_real_file_name`, `tests/test_agent_service.py`).
