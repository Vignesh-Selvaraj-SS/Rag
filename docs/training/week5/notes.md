# notes.md — Week 5 Task Set D · Insurance claims

Everything behind `taxonomy.md`: the seeded sample, the replay evidence, the 20
verbatim open-coding sentences, the zero-fix attestation, and the benchmark note.

| | |
|---|---|
| Author | \<your name\> |
| Task set | D — Insurance claims |
| Trace file | `week5/traces.json` — 100 traces, **8,056 lines**, 2026-09-02T18:01:14Z to 2026-09-02T18:18:06Z (rendered from the append-only log `traces.jsonl`, 100 lines, by `week5/format_traces.py`) |
| Traces read | 20 |
| Date traces generated | 2026-09-02 |
| Date read | \<YYYY-MM-DD\> |
| Code version | `ca8396c` on `week-4` + the four field additions below, all made **before** generation |
| Config (identical for all 100) | mode `hybrid`, `TOP_K=5`, `MIN_SCORE=0.6`, chunk strategy `heading` (122 chunks), model `openai/gpt-oss-20b`, `prompt_version=v1`, temperature `0.0`, `max_tokens=800` |

---

## 1. Redaction confirmation

> **Claimant names, claim numbers and policy numbers are redacted before the
> trace is written, not after.** `week5/trace_logger.py` — `build_trace()` passes
> the question, answer, `raw_output` and every retrieved chunk text through
> `redact()` / `scrub()`, and only then does `append_trace()` serialise the
> record. The unredacted string never reaches `traces.jsonl`.

Patterns:

| Input | Becomes |
|---|---|
| `CLM-482911` | `[CLAIM_NO]` |
| `HO-5591027` (7+ digits) | `[POLICY_NO]` |
| `claim 482911`, `claimant 482911` | `[CLAIM_NO]` |
| `claimant X`, `policyholder X`, `insured X`, `X (claim`, `X, policy`, `for X — his/her` | `[CLAIMANT]` |

Names are matched by **trigger**, never by shape alone — a bare title-case pair
would redact corpus headings like "Water Backup" out of the retrieved chunk text.

Beyond pattern matching, every identifier literal found in the question is also
scrubbed **by value** from the answer and `raw_output`. This was not a
precaution: the model is asked the real question, and it echoed a claimant name
back in a shape no trigger covered — *"The deductible for Maria Delgado's
water-backup claim is $500"* has neither a preceding "claimant" nor a following
", claim". Six traces written before that fix were deleted and regenerated.

**Verified on the finished corpus:** 0 unredacted identifiers across all 100
traces; 8 `[CLAIMANT]`, 6 `[CLAIM_NO]`, 2 `[POLICY_NO]` placeholders present;
0 of 122 indexed corpus chunks altered by a false positive.

---

## 2. Seeded random sample of 20

Sampling frame: **all 100 traces in the trace file** with `origin=random` —
not a question list, not the demo claims, not the ones I remembered breaking.

```
Command : python week5/sample.py --seed 20260902 --n 20
Seed    : 20260902
Frame   : 100 trace_ids
Selected: 20
```

```
t_0003, t_0012, t_0026, t_0036, t_0040, t_0047, t_0048, t_0059, t_0060, t_0062,
t_0070, t_0071, t_0074, t_0080, t_0081, t_0082, t_0087, t_0091, t_0094, t_0096
```

Nothing was re-rolled, swapped or dropped after seeing the contents. The seed was
fixed before the draw and the same 20 come back on every re-run. Full listing with
question text: `week5/sample-evidence.txt`.

Composition as drawn (not chosen): 2 kind A, 1 B, 5 C, 3 D, 3 E, 3 F, 3 G.
5 of the 20 were refused by the app, 15 answered.

---

## 3. Replay evidence

Trace picked for replay by seeded random choice over `trace_id`:

```
Command : python week5/replay.py --seed 20260902
Seed    : 20260902
trace_id: t_0036   (Q036, kind C, recorded 2026-09-02T18:06:13Z)
```

Full output: `week5/replay-evidence.txt`.

### 3.1 Fields the trace had to carry

Four of the seven were missing and had to be added. `ask()` returned no
`params`, no `prompt_version` and no unparsed output, and nothing was persisted
at all — the result was printed to the terminal and discarded.

| Field | Present at first attempt? | Note |
|---|---|---|
| `prompt_version` | **added** | Did not exist. Added `PROMPT_VERSION = "v1"` in `llm_service.py` and returned it, so a trace stays replayable once the prompt moves on |
| `retrieved[].chunk_id` | **added** | Present in the Qdrant payload but **dropped** by `retrieval_service.retrieve()` when it normalises hits — a trace could name the file and heading but not the exact chunk |
| `retrieved[].score` | yes | Already carried, with `dense_score` alongside it (the gate uses `dense_score` because hybrid `score` is a fused RRF value on a different scale) |
| `model` | yes | Already returned by `ask()` |
| `params` | **added** | `ask()` accepted them but never reported them. Now recorded as **resolved** values, so a trace shows what the run used even when the caller passed nothing |
| `raw_output` | **added** | Only the stripped, parsed answer was returned. Without the unparsed output, a truncated generation is invisible in the trace |
| `timestamp` | **added** | Nothing was logged before this week |

### 3.2 Original vs replayed

**Original** (from `traces.jsonl`, 261 chars)

```
For a contractor-caused service line failure, subrogation must be evaluated on
claims over $5,000 and a referral to the Recovery unit is mandatory within 5
business days [S1][S5]. The file must retain a failed-component evidence log,
all correspondence with the
```

**Replayed** (re-run from the trace alone)

```
For a contractor-caused service line failure, subrogation must be evaluated on
claims over $5,000 and a referral to the Recovery unit is required within 5
business days. The file must retain a failed-component evidence log, all
correspondence with the responsible party, and a final recovery reconciliation
showing gross, legal, and net recovery [S1][S3][S5]. The HO-2026-02 endorsement
provides coverage for the repair or replacement of the damaged line and
excavation costs, but it does not change the subrogation procedure or the
recovery timeline [S2].
```

**Match: differs, in two separate ways.**

*Retrieval* — the same five `chunk_id`s came back, but ranks 2 and 3 are swapped:

| Rank | Original | Replayed |
|---|---|---|
| 1 | `claims-adjuster-authority.md::6` (0.0328) | `claims-adjuster-authority.md::6` (0.0328) |
| 2 | `endorsement-HO-2026-02-service-line.md::1` (0.0315) | `claims-procedure-cp12-subrogation.pdf::5` (0.0315) |
| 3 | `claims-procedure-cp12-subrogation.pdf::5` (0.0315) | `endorsement-HO-2026-02-service-line.md::1` (0.0315) |
| 4 | `endorsement-HO-2026-02-service-line.md::6` (0.0313) | same |
| 5 | `claims-procedure-cp12-subrogation.pdf::2` (0.0308) | same |

Both tied chunks score 0.0315 exactly, so the RRF fusion tie-break is not stable
between runs. The chunk_id **set** replays exactly; only the order of two
equally-scored chunks moves.

*Generation* — the replay produced a longer, differently worded answer citing
`[S1][S3][S5]` where the original cited `[S1][S5]`.

**What I could not reconstruct:** the exact generated text. Temperature is `0.0`
and the prompt, model and source chunks were identical, so the difference is
provider-side non-determinism, not a config difference. The original also stops
mid-sentence at 261 characters (*"...all correspondence with the"*) while the
replay does not — so the truncation itself is not reproducible either. Six of the
100 traces end mid-sentence this way: `t_0006`, `t_0036`, `t_0054`, `t_0064`,
`t_0093`, `t_0099`.

---

## 4. Open coding — 20 verbatim observation sentences

**Rule:** each sentence describes what I **saw**. No category, no cause, no fix.
"I don't know why this failed" is used where that is the truth.

| | |
|---|---|
| Scores | "The answer says the water-backup deductible is $1,000; the endorsement text in retrieved chunk 4 says $500." |
| Does NOT score | "Retrieval missed the Deductible chunk, so it fell back to the base policy." |

Sentences are verbatim as written during the read — not tidied up afterwards.

1. `t_0003` — 
2. `t_0012` — 
3. `t_0026` — 
4. `t_0036` — 
5. `t_0040` — 
6. `t_0047` — 
7. `t_0048` — 
8. `t_0059` — 
9. `t_0060` — 
10. `t_0062` — 
11. `t_0070` — 
12. `t_0071` — 
13. `t_0074` — 
14. `t_0080` — 
15. `t_0081` — 
16. `t_0082` — 
17. `t_0087` — 
18. `t_0091` — 
19. `t_0094` — 
20. `t_0096` — 

---

## 5. Zero-fix attestation

No code changed between generating the traces and finishing the 20 sentences.

The four field additions (`prompt_version`, `raw_output`, `chunk_id`, `params`)
were all made **before** the corpus was generated. The redaction fix made
mid-generation changed only what gets *written*, never what the app answered; the
seven traces regenerated after it (`t_0094`–`t_0100`) came from identical app code.

```
<paste: git log --oneline --since="2026-09-02" -- app/ ask.py>
```

Trace-generation commit: `<sha>` · \<time\>
First commit after coding finished: `<sha>` · \<time\>
Files touched under `app/` in between: **none**

---

## 6. Why a public benchmark would have missed my top 3 modes

\<Three sentences, each naming one of your actual top-3 mode names. A generic
point about MMLU being multiple-choice will not earn the 10 marks.\>

1. 
2. 
3. 

---

## 7. Bonus — random sample vs curated demo set

Open-code 10 more traces drawn from the demo claims shown at the monthly review.
Generate them with `--origin demo` so they stay out of the random frame:

```
python week5/run_traces.py --mode hybrid --origin demo --ids <the demo question ids>
python week5/sample.py --seed <N> --n 10 --origin demo
```

| | Random sample | Demo set |
|---|---|---|
| n | 20 | 10 |
| Top mode (`<mode name>`) frequency | \<N\>/20 = \<N\>% | \<N\>/10 = \<N\>% |

1. `<trace_id>` — 
2. `<trace_id>` — 
3. `<trace_id>` — 
4. `<trace_id>` — 
5. `<trace_id>` — 
6. `<trace_id>` — 
7. `<trace_id>` — 
8. `<trace_id>` — 
9. `<trace_id>` — 
10. `<trace_id>` — 

**What the team has been telling itself:** \<one paragraph — the two numbers are
the whole point\>
