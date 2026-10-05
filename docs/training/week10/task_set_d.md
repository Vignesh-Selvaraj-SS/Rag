# Week 10 Task Set D — "Race the claims squad against your single agent"

**Problem statement:** does the manager + 2 specialist orchestrator beat the existing single agent, or just cost more per claim? Race both on the same 9 Week 6 M6 claim-summary eval cases and report the bill alongside the pass rate.

## The two arms

| | Single agent | Claims squad |
|---|---|---|
| File | `app/services/summary_service.py` | `app/services/claims_squad_service.py` |
| Agents | 1 | 3 (manager, adjuster-note summary worker, coverage/exclusions worker) |
| Groq calls per case | 1 | 3 |
| Output contract | rigid 6-line `CLAIM/DATE OF LOSS/COVERAGE/BASIS/DEDUCTIBLE/NEXT ACTION` | identical — the manager's synthesis step produces the same format, so the same assertions and judge score both unchanged |

**Why these 9 cases, not 10:** this app's actual Week 6 eval set (`evaluation/eval_set.jsonl`, built in `scripts/build_eval_set.py`) has exactly 9 "M6" (claim-summary) cases — 4 original plus 5 real-failed-summary regressions added in the Task Set D extension (`docs/training/week6/task_set_d_extension.md`). The task sheet's generic "10 Week-6 eval cases" doesn't match our actual history by one case; stated honestly rather than padded to 10 with an invented case, which the task's own rules forbid ("do not write new cases").

## Rubric, mapped to evidence

| # | Criterion | Points | Evidence |
|---|---|---|---|
| 1 | All four numbers, both arms, same cases | 30 | `race_table.md` — pass rate 67% vs 22%, p50 604ms vs 14,198ms, p99 857ms vs 23,274ms, tokens 15,097 vs 34,324, cost/claim $0.00034 vs $0.00076. All from a real, live race (`scripts/race_claims_squad.py`), saved incrementally so the one background-timeout interruption mid-run lost zero data. |
| 2 | Context re-send multiplier, attributed to a named hand-off | 25 | **2.3x** (34,324/15,097). Dominant hand-off: `manager -> coverage_worker`, 15,459 tokens, **45%** of all squad tokens — the hand-off carrying the full retrieved policy-source text. Full per-case breakdown in `handoffs.log`. |
| 3 | Worker failure injected, actual behavior recorded honestly | 20 | `failure_case.md` — coverage worker forced to fail on case S1. The manager **degraded, did not retry, did not lie** (never asserted a coverage position it hadn't determined) — but still produced the wrong outcome for the eval, since the one fact that would have answered it correctly died with the failed worker. |
| 4 | Verdict cites ≥2 numbers, names sunk-cost bias | 15 | `verdict.md` — KILL, citing pass rate, tokens, cost, and p99; sunk-cost bias named explicitly before the numbers are given. |
| 5 | Hand-off log with per-hand-off token counts | 10 | `handoffs.log` — every hand-off, every case, with its token count and totals. |

## How the race was actually run

`scripts/race_claims_squad.py` runs both arms over the same `EvalService.load_cases()` output filtered to `mode == "M6"`, scores both with the unmodified `eval_assertions.run_assertions()` and `JudgeService.judge()`, and saves after every single case/arm — the live run was interrupted once by a background execution time limit at 17 of 18 case/arm pairs complete; resuming the same command picked up exactly where it left off and finished the 18th with zero re-work or re-spend.

One real bug found and fixed during this build, before trusting any number: the first live attempt showed both arms failing on a bogus `"empty answer"` assertion despite neither output being empty - `eval_assertions.py`'s shared checks read `result["answer"]`, which `eval_service.py`'s own runner sets (`outcome["answer"] = outcome["summary"]`) but this race script's first draft didn't. Fixed before the real 9-case run, not after seeing a suspicious number and rationalizing it.

## Common mistakes, checked against

- **Declaring a winner on pass rate alone, ignoring token cost** — not done; all four numbers are reported together in `race_table.md`, and the verdict cites more than one.
- **Building a fresh eval set because Week 6's "doesn't suit" the orchestrator** — not done; same 9 cases, stated honestly as 9 rather than the task's assumed 10.
- **Re-sending full adjuster-note history on every hop and blaming the pattern** — the re-send is real and reported (2.3x), but attributed to its actual cause (the coverage worker's hand-off carrying retrieved policy text), not asserted as an inherent multi-agent tax.
- **Giving the exclusions worker every tool the single agent had** — not done; the coverage worker never calls `search_policy` itself or holds any tool — it receives pre-retrieved sources and the summary worker's extracted facts only, kept deliberately narrower than the single agent.
- **Letting synthesis round a qualified answer up to a clean one** — checked directly: the one real over-confident miss (R-M6-V17, `covered` for a case needing a specific exclusion) is named in `race_table.md`'s quality-story section, not hidden.
- **Reporting p50 only** — both p50 and p99 are in `race_table.md`; p99 (23.3s) is the more damning number and is not the one reported alone.

## Deliverable files (submission checklist)

- `race_table.md` — 4 metrics × 2 arms, same 9 cases named ✅
- `handoffs.log` — every hand-off with its token count ✅
- Multiplier line: 2.3x, dominant hand-off named ✅ (in `race_table.md`)
- `failure_case.md` — the injected failure and what the squad actually did ✅
- `verdict.md` — keep/kill, two numbers cited, sunk-cost named ✅
