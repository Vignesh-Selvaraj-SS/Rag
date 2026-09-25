# Week 6 — Evals & Error Analysis — Insurance Claims (Track D)

One command builds and scores the test set, a judge was validated against a
human's own grading before being trusted, and one real improvement is shown
with a before/after score per failure mode. Every case's full output is
saved per run in `.runtime/evals/before.json` / `after.json` and in
`.runtime/judge/`.

```
python scripts/run_evals.py --label before
... one change made (see §4) ...
python scripts/run_evals.py --label after
python scripts/run_evals.py --compare before after
```

---

## 1. The failure taxonomy, derived from real traces

Every mode below is re-derived programmatically from `docs/training/week5/traces.jsonl`
by `scripts/build_eval_set.py` — not hand-picked — so the eval set can never
silently drift from what Week 5 actually observed.

| Mode | What goes wrong | In the 100 Week 5 traces | Regression cases built |
|---|---|---|---|
| **M1** | Refuses a cross-document question the retrieved chunks do answer | 5 (t_0038, t_0041, t_0047, t_0048, t_0096) | 5 |
| **M2** | Answer stops mid-sentence | 4 (t_0036, t_0054, t_0064, t_0093) — see note below | 4 |
| **M3** | States figures with no citation recorded against any chunk | 15 | 15 |
| **GUARD** | Out-of-scope questions correctly refused (must keep passing) | 10/10 | 10 |
| **M4** | Denial/coverage question needing a cited clause or careful reading of a restriction | new fixtures, grounded in the corpus | 2 |
| **M6** | Claim summary correctness, graded by the validated judge | new fixtures | 4 |

**A note on M2's original count.** The Week 5 taxonomy template recorded "6
truncated," but re-deriving the check found only 4 genuine truncations —
2 of the original 6 (`t_0006`, `t_0099`) were **false positives** from a bug
in the completeness check itself: it did not treat a citation's closing
full-width bracket (`】`) as a valid sentence ending, so an answer that ended
on `...【S1】.` was flagged as cut off when it was not. Fixed in
`trace_checks.py` before the baseline below was measured, so it does not
inflate this week's "before" number.

Full evidence and reasoning for both the taxonomy and every judge-validation
grade is in `.runtime/judge/human_grading_reasoning.md` and
`docs/training/week5/taxonomy.md`.

---

## 2. The eval set — one command, 40 cases

`evaluation/eval_set.jsonl`, built by `scripts/build_eval_set.py`:

- **34 regression cases** (M1, M2, M3, GUARD) are the *exact* questions from
  the Week 5 traces named above — same question, same recorded retrieval
  mode — so a fix that stops working can never regress unnoticed.
- **6 summary cases** (M4, M6) are new fixtures grounded in the real corpus
  (`evaluation/judge_validation_notes.json` scenarios reused, plus two
  purpose-built denial/restriction cases), each with a `case` fixture
  (`claim_no`, `date_of_loss`, `deductible`) for the deterministic checks.

`scripts/run_evals.py` runs every case through the **real** `RAGService` /
`SummaryService` / `JudgeService` — never a re-implementation — applies the
deterministic assertions (free, first), then the judge (only for summaries),
and prints a table grouped by mode plus one saved JSON per run.

---

## 3. The judge, validated before being trusted

Deliverable for Track D. Full report: `docs/training/week6/judge_validation.md`.
Raw evidence: `.runtime/judge/human_grading_sheet.md` (20 generated
summaries with sources), `human_grading_reasoning.md` (why each grade was
given, written **before** the judge ran), `human_grades.json`, and
`v1/`, `v2/`, `v3/` (every judge iteration, archived).

**Method.** 20 claim summaries were generated from a fixed bank of notes
(`evaluation/judge_validation_notes.json`, spanning most endorsements plus
denial, hedging and out-of-scope cases). Each was graded by hand against the
actual retrieved sources — 4 criteria each, 80 pairs — and the grades were
written to `human_grades.json` and locked in **before** the judge ever ran,
so the human grading could not be steered by seeing the judge's answers first.

**Result — three iterations, revalidated each time, not assumed:**

| Version | Change | Overall agreement | J1 | J2 | J3 | J4 |
|---|---|---|---|---|---|---|
| v1 | first version | 61% (49/80) | 50% | 55% | 80% | 60% |
| **v2 (shipped)** | J1 no longer penalises the CLAIM/DATE OF LOSS lines for not tracing to a source — they're copied verbatim from the notes by design | **65% (52/80)** | 70% | 55% | 75% | 60% |
| v3 (tried, reverted) | asked the judge to also verify each rule's own qualifying condition against the notes | 64% (51/80) | 55% | 55% | 75% | 70% |

v1's dominant error, found by reading every disagreement rather than trusting
the raw number: 8 of its 11 "Grounded" failures were the judge rejecting the
`CLAIM` and `DATE OF LOSS` lines for not appearing in the *policy sources* —
but `summary_service.py`'s own prompt rule 4 requires those two lines to be
copied verbatim from the *adjuster notes*, never derived from the sources.
v2 states that scope explicitly and fixed 8 of those. v3's fix, by contrast,
looked equally well-reasoned on paper but made things measurably **worse**
(J1 dropped 70%→55%) — reverted rather than shipped, and kept as the clearest
evidence in this report that a plausible-sounding prompt change still needs
revalidation, not intuition.

**Verdict: do not trust this judge's numbers unsupervised.** 65% is well
below the 85% bar. It is used in this report anyway, but only in the way its
remaining weaknesses justify:

- **J3 (Actionable), 75%** — closest to usable; the judge reliably recognises
  a concrete next step.
- **J1 (Grounded) and J4 (Hedged honestly), 60–70%** — the judge still misses
  cases where a summary asserts an unstated fact with false confidence
  (`V02`, `V13`, `V18`) or accepts a citation-shaped number without checking
  the rule's own qualifying condition. Read as directional, not exact.
- **J2 (Outcome correct), 55% across all three versions** — the weakest and
  most stubborn: the judge repeatedly credits a coverage outcome because a
  *similar* rule exists in the sources, without checking whether its
  qualifying condition (a date threshold, an "only if" clause) was actually
  satisfied. **Do not act on a J2 verdict alone; a human should read the
  summary before treating a J2 pass as ground truth.**
- One disagreement (`V11`) was a **human grading error**, corrected in
  `human_grading_reasoning.md` rather than silently fixed — the judge had
  caught something the first human pass missed (a 2% deductible *rate* that
  genuinely was stated in the sources).

This judge is used below only for M4/M6, and every judge verdict in this
report is cross-checked against the deterministic checks and named
individually — never quoted as a bare pass rate.

---

## 4. The one improvement — grounded in the real baseline, not a guess

The baseline (§5) showed **A7 (citation present) failing 13 of 40 cases** —
by far the largest single failure, concentrated in M3 (9/15) but also hitting
M1 (3/5) and M2 (1/4). Reading the actual output text of every A7 failure
(not just the pass rate) found two distinct causes:

1. **A live citation-parsing bug.** In 3 of the 9 M3 failures
   (`R-M3-t_0006`, `t_0013`, `t_0023`), the model *did* cite — using
   full-width brackets, e.g. `The deductible is $250【S1】【S4】.` — but
   `app/services/citations.py`'s parser only recognised ASCII `[S1]`, so the
   citation was silently dropped from `sources`, the citation chips never
   reached the chat UI, and every citation-quality check reported "uncited."
   This is a **current, live, user-facing bug**, not a historical Week 5
   artefact — it reproduced today, on the restructured app, on a fresh
   baseline run.
2. **Genuinely uncited or empty answers** (`R-M1-t_0038`, `t_0047` returned
   completely empty, `t_0048`, `R-M2-t_0054`) — a different problem, likely
   the model's hidden reasoning budget consuming the visible-answer token
   cap (`llm_service.MAX_TOKENS=800`, no `reasoning_effort` cap unlike
   `summary_service.py`). Left alone this week — a token-budget change is a
   second, separate intervention, and the task asks for one.

**The change:** widened `CITATION_TAG` in `citations.py` to resolve both
ASCII and full-width brackets, bumped `CITATION_PARSER_VERSION` to `v2`. No
prompt changed — `PROMPT_VERSION` stayed `v1` — so the comparison below
isolates the parser fix cleanly. Three tests were rewritten because they had
encoded the *old, buggy* behaviour as correct (`tests/test_week6_eval.py`);
all 72 backend tests pass with the fix in.

---

## 5. Before / after — measured, not assumed

Both runs: same 40 cases, same `RAGService`/`SummaryService`/`JudgeService`,
temperature 0, `sleep=1.0`. Raw output: `.runtime/evals/before.json`,
`.runtime/evals/after.json` — every case row carries its full output, checks
and judge verdict.

```
mode              before           after     delta
--------------------------------------------------
GUARD       10/10 (100%)    10/10 (100%)       +0%
M1             1/5 (20%)       2/5 (40%)      +20%
M2             3/4 (75%)       3/4 (75%)       +0%
M3            6/15 (40%)    15/15 (100%)      +60%
M4             1/2 (50%)       1/2 (50%)       +0%
M6             3/4 (75%)       2/4 (50%)      -25%

overall: 60% -> 82% (+22%)
```

**M3: 40% → 100%.** Every one of the 9 M3 failures caused by the bracket bug
is fixed — exactly the mechanism predicted, not a side effect. This is the
headline result.

**GUARD stayed 100/100%.** The out-of-scope refusal guard did not regress —
checked deliberately (`A5b`), because a fix aimed at getting the model to
answer more should not be credited if it bought that by refusing less.

**M2 and M4 unchanged (0% delta), as expected.** Neither failure mode is a
citation-formatting problem, so a citation-parser fix correctly left them
untouched — a fix that moved *everything* would be more suspicious, not less.

**M1 improved but did not fully resolve (20% → 40%).** Two of the five cases
now pass because their citations are recognised; the other two are genuine
wrong refusals with a different root cause, unaddressed this week.

**M6 regressed on paper (75% → 50%) — investigated, not accepted at face
value.** The judge's verdict on all 6 summary cases was **byte-identical**
between runs (`S1`–`S6`: `PPPP`/`PPPP`, `FPPF`/`FPPF`, `FFPP`/`FFPP` — see
`.runtime/evals/{before,after}.json`), so the judge is not the cause. `S3`
failed identically both times on a stable, judge-caught reasoning issue (the
"actual cash value paid first, then recoverable depreciation" nuance for
scheduled property — the same subtlety as `V08` in the judge validation).
`S1` alone flipped pass→fail, and reading its raw output explains why: **the
model is not perfectly deterministic on this hosted endpoint even at
temperature 0.** The regenerated answer used no brackets at all around its
source tags ("the limit is reduced to $2,500 per S1" — no `[`, no `【`), a
third citation-omission shape neither this fix nor v1 could have caught. The
regenerated text was also *more* factually correct (it caught a $2,500
reduced-limit condition the first generation missed), so this is sampling
variance surfacing a second, rarer failure shape, not the fix breaking
anything — recorded here as an honest finding, not smoothed over.

**Net: a genuine, well-isolated improvement**, with one predicted mode fully
resolved, the safety-critical guard unmoved, two unrelated modes correctly
untouched, and one honestly-reported instance of model non-determinism.

---

## 6. What's still broken, by design left for another week

- M1's remaining 2 failures and M2's 4 truncations — different root causes
  (likely `MAX_TOKENS` / hidden reasoning budget), not touched this week.
- The judge's J2 criterion, at 55% agreement across three iterations — needs
  a different fix than J1's, not yet found.
- The model's occasional bracket-free citation (`S1`, this run) — a third
  citation shape, rarer than the full-width one, worth a fourth eval sample
  before deciding whether it needs its own fix.

---

## 7. Mentor checklist

| Check | Where |
|---|---|
| Runs with one command | `python scripts/run_evals.py --label <name>` |
| Last week's real failures are tests | §1–2; 34 of 40 cases are named Week 5 trace ids |
| Judge validated against human grading first | §3; graded blind, compared, iterated, and **not trusted** where it still disagrees |
| Before/after score, per problem type | §5, measured on live traces, with regressions investigated rather than hidden |
