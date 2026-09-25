# Ranked failure taxonomy — Insurance claims assistant

**Methodology note (filled in during Week 6):** this file was left as an
unfilled template. Rather than construct a seeded 20-trace hand read after
the fact — which would invite picking a sample that confirms a story already
decided — the taxonomy below is derived from **the full 100-trace corpus**,
programmatically, so every count is reproducible from the trace file itself
(`scripts/build_eval_set.py`'s `classify()` function *is* this table's
methodology, executable). Config, as recorded in every trace: `hybrid`,
`TOP_K=5`, `MIN_SCORE=0.6`, `openai/gpt-oss-20b`, `prompt_version=v1`,
temperature `0.0`. Evidence: `traces.jsonl` (this folder), cross-checked by
hand against the source documents in `.runtime/judge/human_grading_reasoning.md`
for the summary-quality modes added in Week 6.

**Severity:** `claim-affecting` = could wrongly deny or wrongly pay a claim ·
`adjuster-annoying` = wastes the adjuster's time but they would catch it.

| # | Failure mode | Count | Freq (of 100) | Severity | Examples |
|---|---|---|---|---|---|
| 1 | **M3** — states a figure with no citation recorded against any retrieved chunk | 15 | 15% | claim-affecting | `t_0013`, `t_0023`, `t_0025`, `t_0029`, `t_0031`, +10 more |
| 2 | **M1** — refuses a cross-document question the retrieved chunks do answer | 5 | 5% | adjuster-annoying | `t_0038`, `t_0041`, `t_0047`, `t_0048`, `t_0096` |
| 3 | **M2** — answer stops mid-sentence | 4 | 4% | claim-affecting | `t_0036`, `t_0054`, `t_0064`, `t_0093` |
| 4 | **GUARD** (not a failure) — out-of-scope questions correctly refused | 10/10 | 10% | — | `t_0065`–`t_0074` |

Traces with no failure observed: 76/100 (76%), after removing the 2 false
positives the original M2 count carried — see §1 of
`docs/training/week6/results.md` for why the original "6 truncated" figure
was itself measured wrong (a bug in the completeness check, not the app).

Everything below the count table — the judge-quality modes (M4, M6), the
prediction, and the actual measured outcome of testing it — is in
**`docs/training/week6/results.md`**, because that prediction was tested
against a live before/after run, not assumed.

---

## Prediction — written before any fix, tested for real in Week 6

**Mode I will attack:** #1, M3 (uncited figures) — the largest single count
by a wide margin, and the one most directly measurable by a citation check
that needs no model call.

**Specific change:** read the actual output text of every M3 failure before
picking a fix (not just the pass/fail count) — this found that most of them
were not the model failing to cite at all, but the model citing with
full-width brackets (`【S1】`) that the ASCII-only citation parser in
`app/services/citations.py` did not recognise. The change made was widening
that parser, not touching the prompt.

**Expected delta:** M3 drops from the baseline measured on the *current* app
(40%, 6/15 — re-measured fresh in Week 6, not assumed from this table, since
the app was restructured since these traces were recorded) to a large
majority passing.

**How this was proven right or wrong:** re-ran the exact same 40-case eval
set (which includes every M1/M2/M3/GUARD trace named above) before and after
the fix, via `scripts/run_evals.py --compare before after`.

**Actual outcome:** M3 went from **40% (6/15) to 100% (15/15)** — the
prediction held completely. GUARD (the side-effect risk — a fix that makes
the model answer more should not be credited if it also makes it refuse
less) stayed at **100% (10/10)**, so nothing was bought at the guard's
expense. Full table, investigation of the one true side effect found (a
non-determinism-driven regression in an unrelated summary case, not this
fix), and everything left unresolved: `docs/training/week6/results.md` §5–6.
