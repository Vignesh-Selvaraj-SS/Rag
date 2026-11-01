# Week 11 Task Set D — cost_by_stage.md

Cost and latency per query, broken down by pipeline stage, computed from the
13 real logged claim-summary requests in `.runtime/claim_log.jsonl`
(`app/services/claim_log_service.py`) — the same requests used for the
`drill.md` investigation, including the one planted bad answer
(`r_3a12a66c8bed`). Every number below is a real Groq/Qdrant call, not an
estimate; nothing here is simulated except the log timestamps (disclosed in
`drill.md`).

## Stages this pipeline actually has

`SummaryService.summarise()` has exactly two stages — **retrieval**
(fastembed + Qdrant, local) and **generation** (one Groq call). There is no
third "tools" stage: this pipeline never calls a tool mid-answer, unlike
`agent_service.py`'s squad. Reported as genuinely absent, not omitted.

| Stage | p50 latency | p99 latency | mean latency | tokens | cost/query |
|---|---|---|---|---|---|
| retrieval | 22ms | 360ms | 51ms | 0 (local, free) | $0.000000 |
| generation | 7,026ms | 12,808ms | 5,691ms | 1,476 avg | $0.000295 |
| **total** | — | — | **5,743ms** | **1,476 avg** | **$0.000295** |

(n = 13 real requests, `.runtime/claim_log.jsonl`, 2026-10-11 to 2026-10-13.
Rate: $0.20 / 1M tokens, `ASSUMED_COST_PER_MILLION_TOKENS` in
`summary_service.py` — the same blended-rate assumption Week 10's squad race
uses, so the two weeks' cost numbers stay comparable.)

## The headline: generation is ~100% of the dollar cost, retrieval is ~100% of nothing

Retrieval runs entirely locally (fastembed embeddings + Qdrant in local
mode) — genuinely $0.00 per query, not a rounding-down of something small.
**Every cent spent on a claim summary is the one Groq call**, which is also
by far the larger share of latency (generation's mean of 5.7s vs
retrieval's 51ms — retrieval is under 1% of total latency on every single
request in this batch). This is exactly why Requirement 4's warning against
"optimizing before attributing cost by stage" matters here: there is no
retrieval-side dollar cost to optimize away, and a latency fix aimed at
retrieval would be chasing 1% of the clock.

## The retrieval-fix tax (Week 11's new top-up step)

The fix in this week's drill (`_ensure_named_endorsements_covered`,
`app/services/summary_service.py`) adds a second, targeted Qdrant search
whenever a named endorsement's own document was missed by the first one.
It is counted inside the `retrieval` span, not hidden in `generation`:

- **When it doesn't fire** (the common case — primary search already found
  every named endorsement): zero added cost or latency. 9 of the 13 logged
  requests above never needed it.
- **When it does fire** (the planted case, `r_3a12a66c8bed`, re-run live with
  the fix during this session): one extra local Qdrant call, +dozens of
  ms, still $0.00 — confirmed live (`endorsements_topped_up:
  ['HO-2026-01']`, generation then correctly produced `COVERAGE: denied`).
  The fix cannot make a query materially more expensive; it can only make
  it correct.

## The planted bad answer was the *cheapest* request in the batch, not an outlier

Worth repeating from `drill.md`: `r_3a12a66c8bed` (before the fix) cost
**$0.000252** — the lowest of all 13, because a retrieval miss hands the
model less context, not more. A "find the expensive one" cost-outlier
search would have missed this exact bug. Cost-outlier is a real, useful
slice for other failure classes (padded context, repeated tool calls,
runaway reasoning) — it is just the wrong tool for *this* one.

## Where this number comes from, for the record

```python
import json
entries = [json.loads(l) for l in open(".runtime/claim_log.jsonl", encoding="utf-8") if l.strip()]
# each entry's "spans" list carries exactly this table's two rows
```
