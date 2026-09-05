# Ranked failure taxonomy — Insurance claims assistant

Sample: 20 traces drawn at random from `week5/traces.jsonl`, frame of 100,
seed `20260902`. Read by hand \<YYYY-MM-DD\>, code frozen at `ca8396c` + the four
trace-field additions. Config: `hybrid`, `TOP_K=5`, `MIN_SCORE=0.6`,
`openai/gpt-oss-20b`, `prompt_version=v1`, temperature `0.0`.
Evidence: `notes.md`, `sample-evidence.txt`, `replay-evidence.txt`.

**Severity:** `claim-affecting` = could wrongly deny or wrongly pay a claim ·
`adjuster-annoying` = wastes the adjuster's time but they would catch it.

| # | Failure mode | Count | Freq | Severity | Example |
|---|---|---|---|---|---|
| 1 | \<applies the wrong form edition's exclusion list\> | \<6\> | \<30%\> | claim-affecting | `<t_0184>` |
| 2 | \<quotes the base policy deductible when an endorsement overrides it\> | \<4\> | \<20%\> | claim-affecting | `<t_0912>` |
| 3 | \<states a coverage limit that appears in no retrieved chunk\> | \<3\> | \<15%\> | claim-affecting | `<t_0007>` |
| 4 | \<refuses although the answer is in the retrieved chunks\> | \<3\> | \<15%\> | adjuster-annoying | `<t_0455>` |
| 5 | \<answers only the first of a two-part question\> | \<2\> | \<10%\> | adjuster-annoying | `<t_0631>` |

\<4–7 rows. Ordered by claim-affecting first, then by count. Replace every angle
bracket. Delete rows you do not have.\>

Traces with no failure observed: \<N\>/20 (\<N\>%).

---

## Prediction — written \<YYYY-MM-DD\>, before any fix

**Mode I will attack:** #\<n\> \<mode name\>

**Specific change:** \<one change, named precisely — e.g. "index `edition_date` as
chunk metadata and filter retrieval to the edition named in the question, falling
back to the newest edition when none is named"\>

**Expected delta:** \<mode name\> drops from **\<30%\> (6/20)** to **under \<10%\>
(≤2/20)** on a re-run of the same 20 trace_ids at seed `<N>`, same config.

**How this can be proven wrong:** re-run the same 20 questions after the change and
re-read them; if the count is \<3\>/20 or higher, the prediction failed.

**Expected side effect:** \<e.g. up to 2 additional refusals on questions that name
no edition\>
