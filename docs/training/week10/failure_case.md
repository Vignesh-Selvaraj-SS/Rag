# Week 10 Task Set D — failure_case.md

**Injected failure:** case `S1` (`CLM-2026-00417`, sump pump overflow water backup claim). The coverage/exclusions worker's hand-off was made to raise an `HTTP 500` before it ever ran — simulated in code (`ClaimsSquadService.process(..., fail_coverage_worker=True)`), not a real outage, but the manager's downstream behavior from that point is real and unscripted.

## What the orchestrator actually did: **degraded to a partial answer — it did not retry, and it did not lie**

No retry: the code has no retry path around the coverage-worker call; on `fail_coverage_worker=True` it immediately records the failure and moves straight to synthesis with a `[WORKER FAILED: ...]` placeholder in place of that worker's output.

No lie: the manager's final synthesis did **not** declare the claim covered (the single-agent arm's real, correct answer for this exact case) with no exclusions check — the single clearest way this could have gone wrong, and the one Task Set D's own common-mistakes list names directly.

## The transcript

**Summary worker (ran normally, unaffected by the injected failure):**
```
CLAIM NUMBER: CLM-2026-00417
DATE OF LOSS: 2026-03-14
CAUSE OF LOSS: Sump pump stopped during a storm caused finished basement flooding.
CONDITIONS NOTED: finished basement, sump pump stopped during a storm, carpet,
drywall and a chest freezer damaged, dwelling built 2015, basement finished 2019,
endorsement HO-2026-01 attached
AMOUNTS MENTIONED: none mentioned
```

**Coverage/exclusions worker:** `[WORKER FAILED: HTTP 500 (simulated) from the coverage/exclusions worker]` — never ran.

**Manager's final synthesis (what the adjuster would actually see):**
```
CLAIM: CLM-2026-00417
DATE OF LOSS: 2026-03-14
COVERAGE: not established in the policy sources
BASIS: not established in the policy sources
DEDUCTIBLE: not established in the policy sources
NEXT ACTION: Obtain a coverage determination or review the policy and endorsement HO-2026-01.
```

**For comparison, the single agent — given the identical notes, no failure involved — correctly determined:**
```
COVERAGE: covered
BASIS: ...covered under endorsement HO-2026-01 per [S4]; the basement was finished
before 01 January 2020 so the backup system requirement does not apply... per [S1];
no exclusions apply per [S3].
DEDUCTIBLE: $500
```

## The real cost of degrading honestly

The manager's behavior here is the *safe* failure mode, not the feared one — it never asserted a coverage position it hadn't actually determined. But it still produced the **wrong outcome for the eval** (fails `A7`: no citation, and would fail the judge on `J2 Outcome correct` and `J4 Hedged honestly` had those criteria run against a real ground truth, since the true answer — covered, $500 deductible — was reachable from the sources the coverage worker never got to read). The reason the manager couldn't recover: by design, it never sees the raw retrieved policy sources itself — only the coverage worker's interpretation of them — so when that one worker fails, the fact that would have produced the right answer is gone with it, not just delayed. A single agent reasoning over the same notes and sources in one pass has no equivalent single point of failure for that specific fact.
