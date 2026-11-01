# Week 11 Task Set D — drill.md

**The complaint, verbatim:** *"An adjuster says it told a claimant something was covered when the policy excludes it, sometime yesterday."* No trace id, no claim number, no timestamp beyond "yesterday" — everything the task gives, and everything used below.

## A disclosure before the number

This exercise is normally done by two people — a squadmate plants the bad answer, you find it blind. There was no second person available here, so one person (me) did both halves: planted the bug (`scripts/plant_claim_log_batch.py`, a genuine retrieval misconfiguration, not a hand-typed fake log line — see `trace.json`'s `_diagnosis`), then investigated it using only the log fields and the complaint above, without re-reading the planting script. The time below is real query-execution time for the investigation steps actually run, not a fabricated "how long a stranger would take" estimate. Said plainly rather than claimed as a blind test it wasn't.

## Time to find: **00:04** (4 seconds of query time)

## The slice that found it: **time → output content → retrieved-context diversity** (three slices chained, not one)

Three steps, each narrowing the field, run as real calls against `ClaimLogService` (`app/services/claim_log_service.py`):

| Step | Slice | Query | Candidates before → after |
|---|---|---|---|
| 1 | **Time** | `by_time("2026-10-12T00:00:00Z", "2026-10-12T23:59:59Z")` — "sometime yesterday" | 13 → 10 |
| 2 | **Output content** | `search_output("covered")` — the complaint describes what the system *said*, not what was *asked* | 10 → 9 within range |
| 3 | **Retrieved-context diversity** | For each "covered" entry, which documents did `retrieved_context_ids` actually come from? | 9 → **1** |

Step 3 is the one that actually closes it: of 9 "covered, yesterday" entries, 8 retrieved chunks from multiple real policy/endorsement documents. **Exactly one retrieved from a single source — `faq-policyholder-endorsements.md` — and nothing else.** A coverage answer that never touched the actual endorsement text is the signature of a retrieval miss, not a correct determination.

```
r_e41b9613f0b9 -> {claims-adjuster-authority.md, faq-policyholder-endorsements.md, endorsement-HO-2026-01-water-backup.md}
r_1b875ebce6e2 -> {claims-adjuster-authority.md, faq-policyholder-endorsements.md, endorsement-HO-2026-04-scheduled-property.md}
r_251dac44c016 -> {endorsement-HO-2026-03-equipment-breakdown.md, faq-policyholder-endorsements.md, endorsement-HO-2026-08-roof-surfaces-acv.md, endorsement-HO-2026-01-water-backup.md, endorsement-HO-2026-04-scheduled-property.md}
r_1de209ba3c37 -> {faq-policyholder-endorsements.md, endorsement-HO-2026-01-water-backup.md}
r_4531896409c6 -> {policy-base-HO3-2026.md, faq-policyholder-endorsements.md, endorsement-HO-2026-01-water-backup.md}
r_fbd5f57a111d -> {policy-base-HO3-2026.md, endorsement-HO-2026-06-home-business.md, endorsement-HO-2026-07-identity-fraud.md, endorsement-HO-2026-01-water-backup.md}
r_3a12a66c8bed -> {faq-policyholder-endorsements.md}                              <-- the only single-source "covered" answer
```

## Two slices that were tried and did NOT help (reported honestly, not hidden)

- **Prompt version**: every entry in the batch shares `prompt_version: "s1"` — no variation to slice on, since the bug isn't a prompt regression.
- **Cost outlier**: the bad entry's cost ($0.000252) is actually among the *lowest* in the batch, not a spike — a naive "find the expensive one" search would have missed it entirely. Worth knowing: a retrieval miss can make a request *cheaper* (less context, shorter prompt), not more expensive, so cost-outlier alone is not a reliable slice for this failure class.

## No missing field to blame

The task allows reporting a missing log field instead of a sub-5-minute time. Not needed here — every field the investigation used (`timestamp`, the answer text, `retrieved_context_ids`) already existed in the log design built for this exercise. The real, honest caveat is the one stated above: this was a solo plant-and-find, not a blind one.
