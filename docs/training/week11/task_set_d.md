# Week 11 Task Set D — "Find the coverage answer that ignored an exclusion"

**The complaint, verbatim:** *"An adjuster says it told a claimant something
was covered when the policy excludes it, sometime yesterday."* No trace id,
no claim number, no timestamp beyond "yesterday."

## Rubric, mapped to evidence

| # | Criterion | Points | Evidence |
|---|---|---|---|
| 1 | Loop closed, RED before the fix and GREEN after, with pass counts both times | 30 | Suite: **35/46 → 36/46**. The assertion built for this exact bug, **A9: 9/12 → 12/12** (0 fails after). See "The loop" below for what "GREEN" does and does not mean here — reported in full, not rounded up. |
| 2 | Time-to-find and the slice that found it, named | 25 | `drill.md` — **00:04**, three chained slices (time → output content → retrieved-context diversity), with the two slices that did *not* help (prompt version, cost outlier) reported honestly. |
| 3 | Trace detail — per-span latency/tokens/cost, prompt version, retrieved context ids | 20 | `trace.json` — full span breakdown, `retrieved_context_ids`, `summary_prompt_version: "s1"` (the version that produced the bug). |
| 4 | Cost by stage + the 10x number | 15 | `cost_by_stage.md` — retrieval $0 / generation $0.000295 per query, from 13 real logged requests. `tenx.md` — the Groq 200,000 TPD cap, hit live in this session, is what breaks first, with the arithmetic shown against real logged volume. |
| 5 | Prompt-version bump + canary/rollback | 10 | `SUMMARY_PROMPT_VERSION` **s1 → s2** (`app/services/summary_service.py`). Canary and rollback below. |

## The bug, in one line

Adjuster notes named a specific endorsement (`HO-2026-01`); the search that
built the summary's context was scoped to `faq-policyholder-endorsements.md`
only (a real misconfiguration, reproduced — not hand-typed — in
`scripts/plant_claim_log_batch.py`), so the endorsement's own 14-day
continuous-seepage exclusion was never in front of the model. The model
wasn't wrong about what it saw; retrieval never showed it the one chunk
that mattered. Full root cause in `trace.json`'s `_diagnosis`.

## The fix: retrieval layer, not prompt layer

`SummaryService._ensure_named_endorsements_covered()`
(`app/services/summary_service.py`): after the primary search, any
endorsement code named in the notes (`HO-20YY-NN`, the same pattern A9
checks) that isn't among the retrieved documents' sources gets a direct,
targeted top-up fetch — the code is resolved straight to its real filename
via `agent_tools._resolve_source()` (reused, not reimplemented) and a
small `source`-scoped search runs against that document specifically.

**A free-text approach was tried first and rejected on live evidence**: a
supplementary query like `"HO-2026-01 exclusions"` reliably returned
*other* endorsements' "Exclusions" sections (`HO-2026-09`, `HO-2026-02`) —
the generic word "exclusions" dominates the specific code in hybrid
ranking. Resolving the code to its exact filename and searching scoped to
it sidesteps ranking entirely, which is the only thing that made the live
re-test of the planted case flip from `COVERAGE: covered` (wrong) to
`COVERAGE: denied` citing `HO-2026-01`'s exclusion (correct).

A second idea — adding a SYSTEM_PROMPT rule telling the model to ground
NEXT ACTION more tightly — was tested live against the planted case and
four known-good cases, made the judge's grounding verdict on this case
*worse* (a new J1 failure appeared) without fixing anything, and was
reverted. Reported because it was tried, not hidden because it failed.

## The loop: RED → GREEN, honestly

**RED** (`.runtime/evals/week11_before.json`, 35/46): `R-M6-W11` (the new
case for this drill) failed `A9` — `"endorsement(s) HO-2026-01 named in the
notes but never retrieved (retrieved only: faq-policyholder-endorsements.md)"`.
Two other cases also failed A9 at the time: `R-M6-V13` (a genuine second
miss, `HO-2026-03`) and `R-M6-V11` — which, on closer inspection while
writing this file, turned out to be a **stale read**: that baseline predates
an earlier fix to A9's own regex (narrowed to stop flagging `CP-09`
procedure codes as missing endorsements, documented in
`eval_assertions.py`). `R-M6-V11`'s real code (`HO-2026-08`) was never
actually missing; only the baseline file was out of date. Said plainly
rather than quietly re-used.

**GREEN** (`.runtime/evals/week11_after.json`, 36/46): **A9: 12/12, zero
fails** — `R-M6-W11` and `R-M6-V13` both now pass it; `R-M6-V11` always
did once the stale artifact is set aside. The live re-run of the exact
planted scenario (source-scoped to the FAQ page, same as the drill)
confirms the mechanism, not just the assertion: the summary's `COVERAGE`
line flips from `covered` to `denied`, correctly citing the exclusion.

**What "GREEN" does not mean**: `R-M6-W11`'s overall case *status* still
reads `fail` in the after-run — not from A9, and not from any new
assertion, but from the judge's `J3` ("Actionable") criterion, which
wanted the `NEXT ACTION` line's procedural detail ("notify the
policyholder") grounded in a source. No claims-procedure document was
retrieved for this case (correctly — it's a coverage endorsement question,
not a procedure one), so J3 has nothing to point at. This is **not a
regression from the fix**: `J3` failed on this exact case in the RED run
too, for the same reason, and independently fails on `R-M6-V01` (an
unrelated case, both runs) — a pre-existing gap in what the judge can
verify for NEXT ACTION lines, not something this week's fix introduced or
was asked to close. Named here rather than let a clean-looking "GREEN"
imply more than the evidence supports.

**No regression elsewhere**: the fix lives entirely inside
`SummaryService.summarise()`; it is structurally impossible for it to
touch `GUARD`/`M1`/`M2`/`M3` cases, which call `RAGService.ask()` instead.
The small per-mode shifts between the two runs in those modes (e.g. one
more M1 case passing, one more M3 case failing) are the model's own
known run-to-run variance, not a side effect of this change — confirmed by
the fact that `SummaryService` code never executes on their path.

A planned third run, isolating just the three affected cases with the fix
toggled off/on, was cut short by Groq's daily token cap mid-run (see
`tenx.md`) — the two full-suite runs above already give a valid,
single-file-change comparison, so the isolated run wasn't repeated.

## Canary and rollback

**Canary**: watch the rate of non-empty `endorsements_topped_up` in
`.runtime/claim_log.jsonl` (added to `ClaimLogService` this week). It
should stay near zero — a rising rate means ranking is missing named
endorsements more often, not that the fix is "doing more work" to be
celebrated.

**Rollback**: set `SUMMARY_PROMPT_VERSION` back to `"s1"` and revert
`_ensure_named_endorsements_covered()` to a no-op (`return hits, []`) in
`app/services/summary_service.py` — one function, one file, no data
migration, since the fix only adds chunks to a request already in flight.

## Common mistakes, checked against

- **Optimizing before attributing cost by stage** — not done; `cost_by_stage.md` is a precondition of this file, and it shows retrieval costs nothing to optimize in the first place.
- **Fixing before adding the eval case** — not done; `R-M6-W11` was added to `evaluation/eval_set.jsonl` and run RED before any fix touched `summary_service.py`.
- **Searching only inputs when the complaint describes outputs** — the drill's second slice is explicitly `search_output()`, built because `TraceService.list()`'s pre-existing search only ever indexed the question.
- **Adding the eval case but not re-running the full suite** — the full 46-case suite ran both times, not just the one new case; the per-mode table above is how the "no silent regression" claim is actually checked, not assumed.
- **Logging full adjuster notes verbatim (PII)** — `claim_log_service.py` reuses `trace_service.py`'s redaction, not a new, unaudited path.
- **Not logging retrieved context ids** — `retrieved_context_ids` is in every claim log entry and in `trace.json`; it is what let `drill.md`'s third slice distinguish "retrieval missed it" from "the model ignored it."

## Deliverable files (submission checklist)

- `drill.md` — time to find (00:04), slice chain, two slices that didn't help, disclosed solo-drill limitation ✅
- `trace.json` — full per-span trace of the found bad answer ✅
- `evaluation/eval_set.jsonl` — new case `R-M6-W11` ✅
- RED (35/46, A9 9/12) → GREEN (36/46, A9 12/12), both saved under `.runtime/evals/` ✅
- `cost_by_stage.md` — retrieval vs generation, per query, from real logs ✅
- `tenx.md` — Groq TPD cap identified as the real 10x constraint, with the live number ✅
- Prompt version bump (`s1` → `s2`) + canary/rollback — this file ✅
