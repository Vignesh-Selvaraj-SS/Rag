# Week 11 Task Set D — tenx.md

**What breaks first at 10x claim volume: the Groq daily token-per-day (TPD)
rate limit, not cost and not per-request latency.**

## The number, caught live, not guessed

While re-running this week's eval suite in this exact session, a real Groq
call failed with:

```
Rate limit reached for model `openai/gpt-oss-120b` in organization
`org_01m3f2zwbjeyt8mxkr13grdtx8` service tier `on_demand` on tokens per
day (TPD): Limit 200000, Used 198756, Requested 1562.
```

**200,000 tokens/day, shared across the whole org** (every week of this
project, every developer, every eval run, every chat question — not a
per-claim or per-user allowance). This is the same cap this project has
hit before (noted after Week 7); it is a real, repeatedly-confirmed
ceiling, not a one-off fluke.

## Doing the arithmetic against real traffic, not a guess

The 13 real claim-summary requests logged this week
(`.runtime/claim_log.jsonl`, see `cost_by_stage.md`) average **1,476
tokens/query**. At that rate:

```
200,000 tokens/day  ÷  1,476 tokens/query  ≈  135 claim summaries/day
```

That is the entire daily budget for the **whole org**, spent on claim
summaries alone, with nothing left over for the chat Q&A path, the Week 10
claims-squad race, or this week's own eval runs — all of which draw from
the same 200,000-token pool. **10x today's actual logged volume (13 → 130
claim summaries/day) would already consume ~96% of the daily quota by
itself** (130 × 1,476 ≈ 191,880 tokens), before a single chat question or
eval run is accounted for. In practice the cap would be hit well before
130/day, on the first day anything else shares the quota — which today it
always does.

## Why it is not cost or latency

| Candidate | At 10x volume (130 summaries/day) | Verdict |
|---|---|---|
| **Cost** | 130 × $0.000295/query ≈ **$0.038/day** | Nowhere close to a constraint — four cents a day |
| **Latency** | ~5.7s mean generation time per request, independent of how many other requests ran that day (no shared serial bottleneck observed in this pipeline) | Unchanged by volume — each request is still answered in the same few seconds |
| **Rate limit (TPD)** | ~192,000 of 200,000 tokens consumed by volume alone | **This is the wall** — hit today, for real, at far less than 10x any day this project has logged |

## What this means in practice

This pipeline is architecturally cheap (two stages, one of them free) and
fast enough per request — the thing that cannot scale 10x on the current
setup is Groq's free/on-demand tier quota, shared org-wide. The fix is not
a code change: it is either rate-limiting/queuing claim-summary traffic
client-side to stay under the daily cap, or moving to Groq's paid Dev Tier
(named directly in the error message's own suggestion) for a materially
higher TPD ceiling. No prompt, retrieval, or caching change in this app
raises a quota set by the provider.
