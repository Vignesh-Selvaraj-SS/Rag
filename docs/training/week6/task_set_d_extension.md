# Week 6 Practical — Task Set D extension

Validate the claim-summary judge before you trust its number. This extends
`docs/training/week6/results.md` (the original Week 6 build); it does not
replace it. All deliverable files referenced below live under
`.runtime/judge/` and `.runtime/judge/deliverables/` (git-ignored — nothing
in this exercise was committed, per instruction; see §7 for what a mentor
who specifically wants git-log proof would need).

---

## 1. Eval set: 45 cases, one command

`python scripts/run_evals.py --label task_set_d_extension` — full terminal
output saved at `.runtime/judge/deliverables/eval_terminal_output.txt`.

```
35/45 passed (78%)  errors=0  in 531.7s

mode      passed   total    rate
--------------------------------
GUARD         10      10    100%
M1             1       5     20%
M2             3       4     75%
M3            15      15    100%
M4             2       2    100%
M6             4       9     44%
```

40 of the 45 cases are unchanged from the original build. **5 new cases are
the "real failed claim trace" regressions this task requires**
(`R-M6-V01`, `R-M6-V11`, `R-M6-V13`, `R-M6-V17`, `R-M6-V18`, added in
`scripts/build_eval_set.py`). A genuine constraint worth stating plainly:
Week 5 only ever recorded chat Q&A traces, never claim summaries, so there is
no Week-5 corpus of *failed summaries* to regress from the way M1/M2/M3
regress from real Week 5 chat traces. Instead, these five replay real
summaries this app actually generated during judge validation
(`.runtime/judge/generated_summaries.json`) that a human, reading the real
sources, found to genuinely fail — each one is a verbatim replay, not an
invented case. In this run, 4 of 5 still fail (V13 via the judge, V01/V11/V17
via the deterministic `A4` clause-citation check) — V18 currently passes,
noted honestly rather than dropped from the set.

---

## 2. Assertions vs. judged criteria — the split, with counts

**9 deterministic assertions, 4 judged criteria, zero overlap.**

| Deterministic (no model call) | Judged (needs judgement) |
|---|---|
| A1 claim number in `CLM-YYYY-NNNNN` form | J1 Grounded — every policy-derived statement supported by the sources |
| A2 date of loss parses and matches | J2 Outcome correct — does COVERAGE match what the sources support |
| A3 deductible is a number (or explicitly "no deductible" / "not established") | J3 Actionable — is NEXT ACTION concrete and consistent |
| A4 a denial names a clause id | J4 Hedged honestly — does it say "not established" rather than guess |
| A5 didn't wrongly refuse · A5b correctly refused out-of-scope · A6 output complete · A7 cites a source · A8 no invalid citation | |

None of A1–A4 were ever criteria in the judge's prompt to begin with — they
were built as regex/logic checks from the start specifically *because* the
task's own common-mistakes list warns against paying a model to check
something a regex settles for free. There was no extraction step because
there was never an overlap to remove; this section exists to state that
plainly and prove it with the counts above, since the rubric asks for the
report even when the answer is "already separated."

---

## 3. Blind labels — 25 summaries, one combined criterion, provable order

**The single binary criterion**: *"Would this summary be safe to act on as
written — no groundedness, outcome, actionability or honesty problem serious
enough to send it back?"* Rather than invent a fifth question, this reuses
`JudgeService.judge()`'s own existing `status` field (pass only if all four
of J1–J4 hold) — the same combined bar the running app already computes, so
"does the judge agree with a human on this app's own pass/fail bar" is
exactly what gets measured.

**Labels saved to `.runtime/judge/labels_25.json`, before the judge ever
saw the new criterion.** Provenance, by file modification time (no commit
was made, per instruction — see §7):

| File | Timestamp | |
|---|---|---|
| `labels_25.json` | 2026-09-15 01:24:13 | ← human labels saved **first** |
| `judge_verdicts.json` (v2 prompt) | 2026-09-15 01:24:43 | judge run, 30s later |
| `prediction.txt` | 2026-09-15 01:25:45 | written before touching the prompt |
| `deliverables/judge_v1.txt` | 2026-09-15 01:25:55 | snapshot of the prompt as it stood |
| `deliverables/judge_v2.txt` | 2026-09-15 01:26:48 | after the few-shot edit |
| `judge_verdicts_v4.json` | 2026-09-15 01:32:22 | re-judged, well after all of the above |

20 of the 25 labels are derived from the per-criterion grades already locked
into `human_grades.json` on 2026-09-07 (well before this exercise even
started) — pass only if all four of that file's J1–J4 grades were pass,
matching the judge's own combined rule. The other 5 (`V21`–`V25`, new
fixtures for this task) were graded fresh against the real retrieved
sources; reasoning for each is inline in the generation script and summarised
in §5.

---

## 4. Agreement, before → after

Two different agreement numbers exist in this project now, from two
different validation exercises — named explicitly so they are never
conflated:

- **Per-criterion agreement** (original Week 6 build, 20 summaries × 4
  separate criteria, 80 pairs): 61% → 65%. See `results.md` §3.
- **Combined single-criterion agreement** (this extension, 25 summaries × 1
  combined verdict, 25 pairs):

```
agreement_before = 14/25 = 56%   (judge prompt v2, unchanged)
agreement_after  = 15/25 = 60%   (judge prompt v4, few-shot examples added)
```

A combined "all four must hold" verdict is strictly harder to agree on than
four separate ones — one wrong criterion flips the whole case — so a lower
number here than the per-criterion 65% is expected, not a contradiction.

**Both numbers stay well below any reasonable trust bar.** This judge's
combined verdict should not be used to route work automatically.

---

## 5. Prediction, then the iteration, then what actually happened

**`prediction.txt`, written before touching the prompt:**

> Adding V17 and V21 as few-shot examples of the judge's own "found a
> related rule, did not check whether its specific condition/scope applies
> to these exact facts" pattern will raise combined agreement into roughly
> the low-to-mid 70s... It will NOT fix the opposite-direction disagreements
> (V04, V08, V19), since those are a different failure mode.

**What the disagreements at `agreement_before` actually looked like**: 8 of
11 were the judge saying "pass" where a human said "fail" — the dominant,
fixable direction. `V17` and `V21` were the two clearest, most teachable
examples of one specific root cause: the judge found a source clause that
*sounded* related and credited it, without checking whether that clause's
own condition (who did what to whom; which specific expense it governs)
actually matched these facts. Both were added as literal worked examples
inside the judge's own system prompt (`judge_v2.txt`, diffed against
`judge_v1.txt` in `.runtime/judge/deliverables/`).

**Actual result**: agreement moved from 56% to 60% — a real, measured
improvement, but nowhere near the predicted low-70s, and not clean:

- **`V17` — fixed exactly as predicted.** The re-judged verdict: *"Summary
  claims coverage, but S1 states theft by a guest is covered, not theft by
  an outsider"* — the judge now reasons through the precise distinction the
  worked example taught it. Verdict: **the judge was wrong before, the fix
  worked, human and judge now agree.**
- **`V21` — NOT fixed, despite being taught with itself, verbatim.** The
  worked example in the prompt describes this *exact* case and states the
  correct answer outright. Re-judged anyway: *"Coverage denied matches S1's
  requirement of prior consent"* — the identical shallow reasoning as
  before, on the very case used to teach against it. Verdict: **the judge
  is still wrong, and directly showing it its own mistake did not transfer
  to a live re-ask of that same case** — a stronger and more useful finding
  than a clean win would have been, since it shows this specific technique
  has a real limit worth knowing before relying on it.
- **`V03` — a new, unpredicted regression.** Previously agreed (judge said
  fail, correctly). After the edit: judge says pass, now disagreeing. Not
  a case either example targeted. This is the exact failure the task's own
  common-mistakes section warns about ("the average will happily hide a
  regression") — surfaced here because agreement was measured on the full
  set, not spot-checked on the two taught cases alone.

**The prediction was wrong on magnitude** (60%, not the low-70s) **and
incomplete on scope** (it did not anticipate `V03` regressing) **but right
on direction and on the two named cases only partially** — one fixed, one
not. Reported as measured, not adjusted after the fact.

**Decision: keep judge v4, not revert.** Unlike the earlier v3 attempt in
the original build (which made every metric worse and was reverted), v4 is
a genuine net improvement (15/25 vs 14/25) even though it is small and
carries a new regression — kept and documented, with the honest caveat that
"kept" does not mean "trusted."

---

## 6. Bonus (RAGAS) — not attempted

Deliberately out of scope for this pass, given the size of the rest of the
work above; noted rather than silently skipped.

---

## 7. On the commit-order requirement

The rubric gives 25 points specifically for provable ordering, and names
"commit hash or timestamp" as acceptable evidence. Nothing in this
extension was committed, per your explicit instruction throughout this
project. The timestamp evidence in §3 is real and checkable (`ls --time-style=full-iso`
against the actual files), but a mentor who specifically wants git-log proof
would need one command run once, on your decision:

```
git add .runtime/judge/labels_25.json && git commit -m "labels_25.json: blind human grades, before any judge run"
```

Nothing else needs to be committed for that proof to stand — `labels_25.json`
alone, committed before `judge_verdicts_v4.json` is ever touched again, is
sufficient.
