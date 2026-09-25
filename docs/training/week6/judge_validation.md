# Judge validation report

20 summaries, 4 criteria each, 80 human/judge pairs compared.

**Overall agreement: 65%** (52/80)

| Criterion | Agreement | Human pass rate | Judge pass rate |
|---|---|---|---|
| J1 Grounded | 70% (14/20) | 12/20 | 14/20 |
| J2 Outcome correct | 55% (11/20) | 11/20 | 18/20 |
| J3 Actionable | 75% (15/20) | 15/20 | 20/20 |
| J4 Hedged honestly | 60% (12/20) | 13/20 | 15/20 |

## Disagreements

- **V01 / J3 (Actionable)** - human said **fail**, judge said **pass**. Judge's reason: NEXT ACTION line gives concrete step to verify limit and process claim.
- **V01 / J4 (Hedged honestly)** - human said **pass**, judge said **fail**. Judge's reason: Summary states coverage without acknowledging S1 contradiction.
- **V02 / J2 (Outcome correct)** - human said **fail**, judge said **pass**. Judge's reason: Coverage denied matches S1’s qualification failure.
- **V02 / J4 (Hedged honestly)** - human said **fail**, judge said **pass**. Judge's reason: Summary states deductible not established, which is not covered in the sources.
- **V03 / J2 (Outcome correct)** - human said **fail**, judge said **pass**. Judge's reason: Coverage line states covered, which matches S1's liability coverage to a paying guest.
- **V03 / J4 (Hedged honestly)** - human said **fail**, judge said **pass**. Judge's reason: Summary states deductible not established, which is accurate per the sources.
- **V04 / J1 (Grounded)** - human said **pass**, judge said **fail**. Judge's reason: BASIS line claims replacement cost basis, but S1 and S2 do not specify settlement basis.
- **V04 / J4 (Hedged honestly)** - human said **pass**, judge said **fail**. Judge's reason: Summary asserts replacement cost basis, which is not established in the policy sources.
- **V07 / J1 (Grounded)** - human said **fail**, judge said **pass**. Judge's reason: All policy-derived statements are supported by S1, S2, and S4.
- **V08 / J1 (Grounded)** - human said **pass**, judge said **fail**. Judge's reason: BASIS line claims no depreciation deduction, but S2 states depreciation is withheld and paid later.
- **V08 / J4 (Hedged honestly)** - human said **pass**, judge said **fail**. Judge's reason: Summary states no depreciation deduction, which S2 contradicts.
- **V11 / J2 (Outcome correct)** - human said **fail**, judge said **pass**. Judge's reason: The coverage line indicates partial coverage, matching S3’s restriction to wind/hail.
- **V11 / J3 (Actionable)** - human said **fail**, judge said **pass**. Judge's reason: The next action cites the need for a specific paragraph citation, as required by S1.
- **V12 / J2 (Outcome correct)** - human said **fail**, judge said **pass**. Judge's reason: Coverage line 'not established' matches lack of coverage info in sources.
- **V12 / J3 (Actionable)** - human said **fail**, judge said **pass**. Judge's reason: NEXT ACTION references reserve review and update schedule, supported by S4.
- **V13 / J1 (Grounded)** - human said **fail**, judge said **pass**. Judge's reason: All policy-derived statements (coverage, deductible, limits, and breakdown basis) are supported by S1, S3, and S4.
- **V13 / J2 (Outcome correct)** - human said **fail**, judge said **pass**. Judge's reason: The summary states the losses are covered, which aligns with S1, S3, and S4.
- **V13 / J4 (Hedged honestly)** - human said **fail**, judge said **pass**. Judge's reason: The summary does not make unsupported claims; it only states what the sources establish.
- **V15 / J3 (Actionable)** - human said **fail**, judge said **pass**. Judge's reason: NEXT ACTION requests additional documents, a concrete step aligned with source procedures.
- **V17 / J1 (Grounded)** - human said **fail**, judge said **pass**. Judge's reason: Limit, deductible, and police report requirement all cited in S1.
- **V17 / J2 (Outcome correct)** - human said **fail**, judge said **pass**. Judge's reason: COVERAGE line states 'covered', which S1 supports.
- **V17 / J4 (Hedged honestly)** - human said **fail**, judge said **pass**. Judge's reason: Summary does not claim unsupported points; sources support coverage.
- **V18 / J1 (Grounded)** - human said **fail**, judge said **pass**. Judge's reason: BASIS line cites S1 which limits asbestos removal to $10,000; DEDUCTIBLE line states not established, which is allowed.
- **V18 / J2 (Outcome correct)** - human said **fail**, judge said **pass**. Judge's reason: COVERAGE line says 'covered', consistent with endorsement adding ordinance coverage for asbestos removal.
- **V18 / J3 (Actionable)** - human said **fail**, judge said **pass**. Judge's reason: NEXT ACTION line gives concrete steps to confirm cost and apply the $10,000 limit, consistent with policy.
- **V18 / J4 (Hedged honestly)** - human said **fail**, judge said **pass**. Judge's reason: Summary honestly states deductible not established in sources.
- **V19 / J2 (Outcome correct)** - human said **pass**, judge said **fail**. Judge's reason: COVERAGE line says denied but no source supports a denial.
- **V20 / J2 (Outcome correct)** - human said **fail**, judge said **pass**. Judge's reason: COVERAGE line matches sources that do not deny coverage.

## Verdict

Agreement is below 85%. Do not trust this judge's numbers yet - read the disagreements above, tighten the judge prompt, and revalidate.