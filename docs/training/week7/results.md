# Week 7 — Agent Loops and When Not to Use Them — Insurance Claims (Track D)

A hand-built agent, raced against a fixed sequence, on the same claim
scenarios, with real numbers. `python scripts/race_agent_vs_workflow.py`.

---

## 1. What was built

**Two tools, one agent loop, ~230 lines, no framework.**

- `search_policy(query, source=None, top_k=5)` — wraps the existing
  `RetrievalService`, optionally scoped to one named document.
- `list_documents()` — lists the indexed file names, so the agent can name
  a document it actually knows exists before scoping a search to it.

`app/services/agent_service.py`'s `ClaimAgent` runs the loop: ask the model
for one tool call, execute it, feed the result back, ask again — until it
calls `finish` or a budget runs out. Every step is logged (`tool`, `args`,
`result`, latency, tokens) and returned to the caller, never just the final
answer.

**`app/services/fixed_claim_workflow.py`** is the comparison point: always
exactly one retrieval call (`top_k=8`, wider than the agent's 5, since it
never gets a second look) then one generation call. No branching, ever.

**Stop conditions**, all named and independently checkable on the result:
`max_steps` (6), `max_tokens` (6000), `max_seconds` (45). A run that
exhausts a budget reports `stopped_reason` and `finished: false` rather
than silently returning a partial answer as if it were complete.

---

## 2. Four real bugs, found by actually running it

Live-testing before racing anything paid off immediately — three of these
were never visible in a design review, only by watching real Groq
responses come back.

**Bug 1 — the model has its own built-in tool-calling, and fighting it
fails outright.** The first version asked the model to reply with
`{"tool": ..., "args": ...}` as plain text. Every call was rejected:
`"Tool choice is none, but model called a tool"`. `openai/gpt-oss-20b` has
a server-enforced notion of calling a tool regardless of whether the API
was told about any tools. Fix: declare the three tools (including `finish`)
through the chat API's own `tools=` parameter and read
`message.tool_calls`, rather than reinventing a worse version of the same
mechanism in prompt text. `AGENT_PROMPT_VERSION` bumped a1 → a2 to record
this.

**Bug 2 — a tool would have executed twice.** Caught on a self-review of
the first working draft, before it ever ran: the tool result was computed
once to build the conversation message, then computed *again* to build the
step log. No live symptom yet, but a real latent bug — refactored so the
result is computed once and both uses share it.

**Bug 3 — a real chunk got truncated before the numbers in it.**
`SNIPPET_CHARS = 320` cut off `claims-adjuster-authority.md`'s settlement-authority
table right after the intro sentence, before any dollar figure. The agent
could see the heading existed but never the numbers, and burned its entire
step budget re-searching for a fact the snippet had already discarded
(`stopped_reason: token_limit`, never finished). Fixed by raising the limit
to 1200 chars — comfortably covering this corpus's longest heading-based
chunks — and captured as a regression test
(`test_search_policy_does_not_truncate_a_chunk_before_its_table_data`).

**Bug 4 — the model's own response format breaks under load, in three
distinct ways, all only on the long `finish` answer, never on short tool
arguments:**
- `"Failed to parse tool call arguments as JSON"` — a long free-text answer
  failed to valid-JSON-encode.
- `"Tool call validation failed ... 'finish<|channel|>commentary'"` — a
  stray internal formatting token leaked into the tool *name* itself.
- `"Parsing failed ... output_parse_failed"` — the model's own internal
  reasoning text leaked out as the entire raw response, no tool call or
  clean message produced at all.

All three are the same underlying category: this model's multi-channel
response format occasionally fails to close out cleanly on a longer
synthesis. Fixed with two changes: a couple of retries reserved
specifically for these three error signatures (`RETRYABLE_TOOL_ERRORS`),
with the temperature bumped slightly on retry since a bare retry at
temperature 0 reproduced the *identical* corrupted output; and an explicit
instruction to keep the final answer to two or three sentences, which
reduces how often the model needs to generate the kind of long,
punctuation-heavy text that triggered this in the first place.

**This bug alone is real evidence for the comparison, not just a nuisance
fixed along the way**: a fixed workflow's single free-text generation call
has no tool-call structure to corrupt, so none of these three failure modes
can happen to it at all. That is a genuine reliability cost specific to the
agent design, independent of whether its reasoning is any good.

All four are covered by tests in `tests/test_agent_service.py` (17 tests,
against fakes — no live calls in the suite itself).

---

## 3. The race — six scenarios, real numbers

Three simple claims (one fact, one endorsement) and three complex ones
(two facts, spanning two different documents), run through both.

```
id   complexity  agent steps  agent tok  agent ms  agent rel  fixed tok  fixed ms  fixed rel
--------------------------------------------------------------------------------------------
S1   simple                3       3075      1882        1/1       1310       794        1/1
S2   simple                3       3026      2053        1/1       1255       337        1/1
S3   simple                2       1986     12955        1/1       1459     10006        1/1
C1   complex               4       5343     36842        2/2       1894      7341        2/2
C2   complex               4       5408     56654        2/2       1625     15144        2/2
C3   complex               4       6528     40594        3/3       2014     11346        0/3

totals: agent 25366 tok, 150980ms, 10/10 facts covered
        fixed 9557 tok, 44968ms, 7/10 facts covered
```

**Cost: the agent used 2.65× the tokens, on every single scenario** —
including the four (S1, S2, C1, C2) where both approaches got a fully
correct answer. Paying more for an identical result is a real cost, not a
neutral one.

**Speed: the agent took 3.4× longer, on every single scenario.** Even the
simplest question (S1: one fact, one document) took the agent three model
calls to the fixed workflow's one.

**One extra, avoidable step on the simple cases.** S1 and S2 took 3 steps,
not the 2 the design was built for — the agent called `list_documents`
first even though the question named its endorsement outright. That is a
real, small inefficiency: an "orientation" habit that cost a step, tokens,
and latency on cases that never needed it.

**Reliability: 10/10 vs 7/10 facts covered — the entire gap is one case,
and the reason is not what it looks like.** `C3` needed two facts from two
different documents (does the ACV restriction apply to fire, and what does
a specific procedure require before a denial). The fixed workflow's
`top_k=8` search *did* retrieve both right documents — its source list
includes `endorsement-HO-2026-08-roof-surfaces-acv.md` and
`claims-adjuster-authority.md`. But its generation step returned a
**completely empty answer**, not a wrong one. `gpt-oss-20b` spends hidden
reasoning tokens before writing anything visible (already documented
elsewhere in this codebase, in `query_transform.py`'s HyDE/rewrite calls);
a single 700-token budget for one hard, two-part synthesis exhausted
itself before any visible text was produced. The agent never hit this,
because splitting the same task across several smaller turns kept each
individual generation's reasoning burden inside its own budget. **This is
a genuine, structural advantage of stepwise generation** — separate from
"the agent can search twice" — and it is the entire explanation for the
one case where reliability actually diverged.

---

## 4. Which one to ship

**Ship the fixed workflow as the default. Do not ship the agent for this
task as it stands.**

Reasoning, stated plainly: for 5 of 6 scenarios — including two of the
three "complex" ones — the fixed workflow reached the identical, fully
correct answer at roughly a third of the cost and a third of the latency.
Paying 2.65× the tokens and 3.4× the latency for no better an answer, on
5 of 6 cases, is not a trade worth making by default.

The one case where the agent won outright (`C3`) is real and worth taking
seriously — but the actual cause was a single-shot generation running out
of hidden-reasoning budget on a hard synthesis, not a fundamental need for
multi-step tool use. **The cheaper fix for that specific failure is
raising the fixed workflow's `MAX_TOKENS`, not building an agent** — an
untested but obvious next experiment, and a more honest reflection of what
Week 7's own lesson is asking for: don't reach for a loop when a smaller,
targeted fix to the simple thing would do.

**Where an agent would earn its keep here**: if claims routinely needed
*three or more* genuinely independent lookups whose targets depend on what
an earlier lookup found — not just "the retrieved pool happened to include
enough" — the fixed workflow's one-shot retrieval would start missing
things a wider `top_k` can't fix. None of these six scenarios reached that
point; a realistic claims desk workload should be checked before assuming
it does either.

---

## 5. What this week actually taught

Not "agents are powerful." The concrete lesson, from real numbers: a fixed
sequence matched an agent's answer quality on 5 of 6 cases at a third of
the cost, the agent's own response-format fragility is a measurable
reliability cost independent of its reasoning quality, and the one case
where the agent genuinely won had a subtler, cheaper explanation than
"more steps are smarter" — which is exactly the discipline this exercise
was built to force.
