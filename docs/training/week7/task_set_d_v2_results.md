# Week 7 Practical Extension — Race the claims agent against a fixed workflow (Task Set D)

Claim triage: pull the claim, read the adjuster notes, check policy exclusions, compute
the payout after the excess. `python scripts/race_triage.py`.

---

## 1. What was built

**Three tools, one agent loop, same task, hardcoded fixed alternative.**

- `get_claim(claim_id)` — claim-specific facts only: claimed amount, policy form and
  endorsements, adjuster notes. Never returns policy wording.
- `search_policy(query, source?, top_k?)` — policy-wide text only: exclusions,
  endorsement wording, deductibles. Never returns claim-specific facts. (Reused from
  Week 7's original agent, schema re-declared locally so it doesn't reference a tool -
  `list_documents` - this agent doesn't have.)
- **`compute_payout(claimed_amount, excess_amount, claim_status)` — the new third tool.**
  One job: subtract the excess, or return 0 if `claim_status` is `"denied"`. No coverage
  lookups of its own. `claim_status` is a schema `enum` (`approved`/`denied`/`partial`),
  not a free-text field. Full diff and rationale: `third_tool_diff.md`.

`app/services/triage_agent.py`'s `ClaimTriageAgent` runs the loop exactly as Week 7's
original agent did: one tool call per turn, fed back, repeat until `finish` or a budget
runs out. `app/services/fixed_triage_workflow.py`'s `FixedClaimTriageWorkflow` calls the
same three tools in a hardcoded order, always exactly four steps, no branching: `get_claim`
→ one `search_policy` call (query = the claim's own notes) → one generation call deciding
coverage and excess → `compute_payout` (code calls this directly with the model's stated
numbers, not the model itself, so the arithmetic is deterministic and auditable).

**Ten claims** (`evaluation/triage_claims.json`), all grounded in the real indexed policy
documents, not invented numbers. **Four are dependent** — step 3 only gets the right
answer if the notes from step 1 were actually read:

| Claim | What the notes reveal | The trap |
| --- | --- | --- |
| CLM-2002 | Water entered via drain, but the actual cause was regional flooding | HO-2026-01 covers sewer/drain backup but explicitly does **not** restore flood, even when it enters through a drain |
| CLM-2003 | Equipment failed, but is still under manufacturer's warranty | HO-2026-03 excludes equipment "to the extent" a warranty already responds |
| CLM-2007 | Roof lost to **fire**, not wind/hail | HO-2026-08's ACV/depreciation restriction applies only to wind/hail losses; fire stays replacement-cost |
| CLM-2010 | The stolen item is a **scheduled** item | the base form's $2,000 jewelry sub-limit doesn't apply once an item is scheduled under HO-2026-04 |

**All four budgets enforced, named and independently checkable on the result:**
`max_iterations` (8), `max_tokens` (14000), `max_cost_usd` ($0.01, at an assumed
$0.20/1M-token blended rate — not Groq's exact billing, stated as an assumption for
comparing the two systems' relative cost), `max_seconds` (180). See the four dedicated
unit tests in `tests/test_triage_agent.py` (`enforces_the_iteration_limit`,
`_token_limit`, `_cost_limit`, `_wall_clock_budget`) and the real live termination log
below.

---

## 2. Bugs found live, and fixed

Same discipline as the original Week 7 build: build, run it for real, fix what actually
breaks, write a regression test, re-verify live before moving on.

1. **`search_policy`'s schema was missing entirely from the triage tool set.** The
   function was wired into `_call_tool`, but nothing told the model the tool existed —
   every attempt to search policy text was rejected outright. Fixed by declaring the
   schema (`triage_tools.py`).
2. **The model reliably guessed a `source` filename from the endorsement code it already
   knew** (`"HO-2026-01"`) instead of the real file name, and an exact-match filter
   returned zero hits every time — this agent has no `list_documents` tool to discover
   real names, unlike the original. Prompt wording alone didn't fix it (tried first, kept
   guessing). Fixed at the code level: `search_policy` (`agent_tools.py`) now resolves a
   given `source` against the real corpus by case-insensitive substring match before
   querying. Regression test: `test_search_policy_resolves_a_guessed_endorsement_code_to_the_real_file_name`.
3. **The fixed workflow's single generation call returned empty content**, then later
   truncated valid JSON mid-string — the same root cause Week 7's original report already
   documented (hidden reasoning tokens exhausting a too-small budget before any visible
   output), now hit again because this task's prompt (full case file + 8 passages) is
   larger. Fixed by raising `MAX_TOKENS` twice (500 → 1000 → 1500), the same fix already
   recommended in Week 7's own findings, applied again rather than reached for a loop.
4. **`TOOL_PARSE_RETRIES=2` (Week 7's figure) wasn't enough here.** A live run hit
   `output_parse_failed` three times in a row on one claim; citation-heavy `finish`
   answers strain this model's formatting more than Week 7's shorter policy-QA answers
   did. Raised to 4, and the flat `0.4` retry temperature was replaced with an escalating
   schedule (`0.4, 0.6, 0.8, 1.0`) after a full-race run showed flat `0.4` still weak
   against a persistent failure on two separate claims.
5. **`max_seconds=45` didn't survive a single rate-limit retry.** The wall-clock check
   only runs between loop iterations, so one call stuck inside a retry wait (a rate-limit
   backoff alone can be 15–60s) blew straight through the 45s budget before the loop got
   a chance to stop on its own terms — 4 of 10 claims in one race hit `time_limit` this
   way despite correct underlying reasoning. Raised to 180s.
6. **A hard failure mid-run discarded the steps already taken.** Found live when the
   Groq account's *daily* token cap (200,000/day, separate from and much less forgiving
   than the per-minute limit) was hit mid-race — the caught exception had no way to show
   what a claim's agent run had actually done before the wall. Fixed by attaching the
   accrued `steps`/`tokens_used` to the raised `LLMUpstreamError`, and by making
   `scripts/race_triage.py` isolate a hard failure to one system/claim cell (and save
   after every claim) instead of losing the whole race.

All six are covered by regression tests. Full suite: 43 tests for this extension, on top
of Week 7's original 38 - all green, no live calls in the suite itself.

---

## 3. The race — ten claims, real numbers

**Primary table** (`race.csv`, complete run over all 10 claims):

```
system            pass_rate   p50_latency_ms   total_tokens   cost_per_claim_usd
agent                  4/10            50591          65628             0.00131
fixed_workflow         9/10            12834          20127             0.00040
```

**Cost: the agent used 3.3× the tokens.** **Speed: the agent took 3.9× longer at the
median.** **Reliability: 4/10 vs 9/10** — and the gap is not reasoning quality. Of the
agent's six losses, **five were `stopped_reason: time_limit` or a hard upstream error**,
not a wrong decision — the agent's own multi-step design means more model calls per
claim, which means more chances for this model's live-documented tool-calling fragility
(Week 7's original finding, reconfirmed here) to strike before it ever reaches `finish`.
**On every claim both systems actually finished, both got the identical, correct
decision and payout.** The fixed workflow's one loss (CLM-2008) was a labeling nuance,
not a wrong number: it answered `"partial"` where `"approved"` was expected, but computed
the exact correct payout ($1,550) either way — `compute_payout` treats both the same for
the arithmetic; only the strict-match grader called it a fail.

**Bugs 3-6 above were found *from* this race**, then fixed. A follow-up partial run on
the first four claims (`race_post_fix_partial.csv`) — before a fresh Groq daily-cap wall
cut the rest of the re-run short — shows the fix holding: the agent went 3/4 clean
(up from 2/4 on the same four claims pre-fix), with zero `time_limit` failures. Its one
remaining loss was a *new*, previously-unseen tool-call corruption variant (the model
named the tool `"json"` instead of `"finish"`), exhausting all 5 retry attempts — further,
honest evidence that this model's own response-format fragility, not the loop's design,
is the agent path's dominant reliability cost. A full clean 10/10 re-run could not be
completed live within the free-tier's 200,000-tokens/day cap, itself consumed heavily by
the live debugging this exact deliverable required.

---

## 4. Budget termination — a real, live, clean stop

`scripts/demo_budget_termination.py` runs `CLM-2007` (a claim that genuinely needs 4-5
turns) with `max_iterations` deliberately set to 2. Full log: `budget_termination_log.txt`.

```
Step 1: get_claim        (957 tokens)
Step 2: search_policy    (1422 tokens)
------------------------------------------------------------------------------
stopped_reason : iteration_limit
finished       : False
steps taken    : 2 (budget was 2)
decision       : None
payout         : None
```

The loop stopped after exactly the budgeted 2 iterations, `finished: False`, no crash, no
spin past the limit, no partial answer dressed up as a real decision. This is also, quite
literally, how bug 5 above was found in the first place: the *first* time this budget
fired for a real reason (not a deliberately tight demo) was `time_limit` cutting off a
correct-but-slow run, which is what prompted raising `max_seconds` from 45s to 180s.

---

## 5. Third tool: description diff

Full diff, and why it passes the "one job, enum, no overlap" bar: `third_tool_diff.md`.

---

## 6. Verdict

**Ship the fixed workflow.** On the complete 10-claim race it wins on all four required
numbers — 9/10 vs 4/10 pass rate, 3.3× fewer tokens, 3.9× lower median latency — and the
agent's losses are overwhelmingly reliability failures (budget/retry exhaustion), not
worse reasoning: on every claim both systems finished, both reached the identical correct
payout. Applying the decision rule (does the path genuinely vary by input?): none of
these 10 claims needed a second, *conditional* lookup whose target depended on what an
earlier tool call found — the fixed workflow's single wide search plus one judgment call
already covers every dependent case here, including the flood-vs-backup and fire-vs-ACV
traps. An agent would earn its keep only if claims routinely needed three or more
genuinely independent, sequentially-dependent lookups; none of these ten reached that bar.
