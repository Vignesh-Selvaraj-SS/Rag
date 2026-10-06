# Week 10 Task Set D — race_table.md

Same 9 Week 6 M6 claim-summary cases, both arms, same `eval_assertions.py` checks and the same `JudgeService` (v4) grading both. Judge tokens excluded from both arms' totals — grading is shared evaluation overhead, not a per-request production cost either arm actually pays.

**Cases named** (file order, none added or removed): `S1, S2, S3, S4, R-M6-V01, R-M6-V11, R-M6-V13, R-M6-V17, R-M6-V18`. `S1` carries the injected coverage-worker failure (see `failure_case.md`), picked before the race by file order, not after seeing results.

| Metric | Single agent (`SummaryService`) | Claims squad (manager + 2 specialists) |
|---|---|---|
| Pass rate | **67%** (6/9) | **22%** (2/9) |
| p50 latency | 604 ms | 14,198 ms |
| p99 latency | 857 ms | 23,274 ms |
| Total tokens (9 cases) | 15,097 | 34,324 |
| Cost per claim | $0.00034 | $0.00076 |

**Context re-send multiplier:** 34,324 / 15,097 = **2.3x**

**Dominant hand-off:** `manager -> coverage_worker`, 15,459 tokens, **45% of all squad tokens** — the hand-off that carries the full retrieved policy-source text (up to 5 chunks, each up to ~1,200 characters) on top of the extracted facts. See `handoffs.log` for the per-case breakdown.

## Per-case status, both arms

| Case | Single | Squad |
|---|---|---|
| S1 | pass | **fail** (injected failure) |
| S2 | pass | pass |
| S3 | pass | fail |
| S4 | fail | pass |
| R-M6-V01 | pass | fail |
| R-M6-V11 | fail | fail |
| R-M6-V13 | fail | fail |
| R-M6-V17 | pass | fail |
| R-M6-V18 | pass | fail |

## The real quality story behind 22%

Only 1 of the squad's 7 failures is the deliberately injected one (S1). The other 6 share a pattern, not random noise: in 4 of them (R-M6-V01, V11, V13, V18) the squad's final answer hedges to `"not established in the policy sources"` on a point the judge confirms the retrieved sources actually *do* settle — the opposite of the "lied by declaring covered" failure this task warns about, but still wrong, in the other direction. One (R-M6-V17) is the warned-against failure: a confident `"covered"` on a case that needed a specific exclusion read correctly. The likely mechanism: the coverage worker reasons from the summary worker's *condensed* facts rather than the full original notes alongside the sources together, the way the single agent does in one pass — losing exactly the texture a correct close read needs, in both directions (sometimes under-confident, once over-confident).
