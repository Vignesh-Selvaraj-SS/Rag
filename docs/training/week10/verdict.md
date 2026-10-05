# Week 10 Task Set D — verdict.md

**Verdict: KILL the claims squad. Keep the single agent (`SummaryService`).**

Sunk-cost bias named up front: we just spent this build week on the squad, which is exactly the pull to find a reason to keep it anyway — the numbers below are what actually decide it, not that effort.

Pass rate: **22% vs 67%** (2/9 vs 6/9, identical 9 cases). Tokens: **2.3x** (34,324 vs 15,097), at **2.2x the cost per claim** ($0.00076 vs $0.00034). p99 latency: **23.3s vs 0.9s**. All four numbers favor the single agent.

The quality loss traces to one cause: splitting "extract the facts" from "decide coverage" costs the coverage worker the full notes-plus-sources context the single agent reasons over in one pass — it mostly erred toward over-hedging, not the feared false confidence, but still wrong more often.

Multi-agent would be worth it here only if the two jobs needed different models/tools or could run in parallel — neither is true: both read the same notes and the same policy search, so splitting them only added hand-off cost with nothing independent to show for it.
