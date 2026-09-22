"""
Build evaluation/eval_set.jsonl from the Week 5 trace corpus.

Every regression case in the output names the trace it came from, so a mentor
can follow any test back to the run that failed. Nothing here is invented:
the questions are the questions that were actually asked, and the modes are
the failure modes those runs actually exhibited.

    python scripts/build_eval_set.py            # rewrite the eval set
    python scripts/build_eval_set.py --check    # verify it is still in sync

The output is committed. Regenerate it only when the taxonomy changes, since
a test set that moves under you makes before/after numbers meaningless.
"""

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

TRACES = REPO_ROOT / "docs" / "training" / "week5" / "traces.jsonl"
OUT = REPO_ROOT / "evaluation" / "eval_set.jsonl"

WIDE_TAG = re.compile(r"[【［]\s*S\d+\s*[】］]")
TERMINAL = (".", "!", "?", '"', "”", ")", "]", "*", "】", "］")

# Claim summary fixtures. The figures are the corpus's own: water backup and
# equipment breakdown carry a $500 deductible, identity fraud $250, and
# scheduled property none. S5 is a denial, which is what exercises A4; S6 asks
# something the corpus does not settle, which is what exercises the judge's
# "hedged honestly" criterion.
SUMMARY_CASES = [
    {
        "id": "S1",
        "mode": "M6",
        "notes": (
            "Claim CLM-2026-00417, date of loss 2026-03-14. Policyholder reports the finished "
            "basement flooded after the sump pump stopped during a storm. Carpet, drywall and a "
            "chest freezer damaged. Dwelling built 2015, basement finished 2019. Endorsement "
            "HO-2026-01 is attached. What is the coverage position and the deductible?"
        ),
        "case": {"claim_no": "CLM-2026-00417", "date_of_loss": "2026-03-14", "deductible": "$500"},
    },
    {
        "id": "S2",
        "mode": "M6",
        "notes": (
            "Claim CLM-2026-00892, date of loss 2026-04-02. Insured reports a credit card was "
            "opened in her name and a loan application was submitted. She has filed a police "
            "report. Endorsement HO-2026-07 is attached. Confirm the coverage position and the "
            "deductible that applies."
        ),
        "case": {"claim_no": "CLM-2026-00892", "date_of_loss": "2026-04-02", "deductible": "$250"},
    },
    {
        "id": "S3",
        "mode": "M6",
        "notes": (
            "Claim CLM-2026-01133, date of loss 2026-05-19. A scheduled diamond ring, appraised "
            "and listed on the schedule under endorsement HO-2026-04, was lost while the insured "
            "was travelling abroad. Confirm the settlement basis and what deductible applies."
        ),
        "case": {"claim_no": "CLM-2026-01133", "date_of_loss": "2026-05-19", "deductible": None},
    },
    {
        "id": "S4",
        "mode": "M6",
        "notes": (
            "Claim CLM-2026-00655, date of loss 2026-02-08. The central air conditioning unit "
            "failed suddenly. The unit was installed in 2013, so it is over ten years old. "
            "Endorsement HO-2026-03 is attached. State the settlement basis and the deductible."
        ),
        "case": {"claim_no": "CLM-2026-00655", "date_of_loss": "2026-02-08", "deductible": "$500"},
    },
    {
        "id": "S5",
        "mode": "M4",
        "notes": (
            "Claim CLM-2026-01470, date of loss 2026-06-11. Hail damage to an asphalt shingle "
            "roof. The risk sits in territory 41. The underwriting file shows endorsement "
            "HO-2026-08 was applied at inception. The insured is asking why the settlement is "
            "less than the contractor estimate. Set out the coverage position."
        ),
        "case": {"claim_no": "CLM-2026-01470", "date_of_loss": "2026-06-11", "deductible": None},
    },
    {
        "id": "S6",
        "mode": "M4",
        "notes": (
            "Claim CLM-2026-01688, date of loss 2026-07-23. The insured operates a dog grooming "
            "business from the garage and a client slipped on the driveway. Endorsement "
            "HO-2026-06 is attached. Confirm whether the driveway counts as the residence "
            "premises for this liability claim and what deductible applies."
        ),
        "case": {"claim_no": "CLM-2026-01688", "date_of_loss": "2026-07-23", "deductible": None},
    },
]

# Real failed claim-summary regressions (Task Set D extension, 2026-09-15).
# Unlike the M1/M2/M3 regressions above - which replay real Week 5 CHAT
# traces - Week 5 never produced claim summaries, so there is no Week 5
# summary corpus to regress from. These five instead replay real summaries
# THIS APP actually generated during judge validation (.runtime/judge/
# generated_summaries.json) that a human grader, reading the real sources,
# found to genuinely fail - see docs/training/week6/judge_validation.md and
# .runtime/judge/labels_25.json. Each `source_trace` is the judge-validation
# case id the notes and expected finding were taken from, verbatim.
REGRESSION_SUMMARY_CASES = [
    {
        "id": "R-M6-V01",
        "source_trace": "V01",
        "notes": (
            "Claim CLM-2026-02011, date of loss 2026-01-09. Sump pump failed during heavy rain "
            "in a finished basement built 2016, no battery backup or water alarm installed. "
            "Water backed up through the floor drain, damaging drywall and flooring. Endorsement "
            "HO-2026-01 attached. What is the coverage position and the deductible?"
        ),
        "case": {"claim_no": "CLM-2026-02011", "date_of_loss": "2026-01-09", "deductible": "$500"},
        "why": (
            "Real failure: wrongly reduced the limit to $2,500 by misapplying the post-2020 "
            "backup-system condition to a basement finished in 2016."
        ),
    },
    {
        "id": "R-M6-V11",
        "source_trace": "V11",
        "notes": (
            "Claim CLM-2026-02230, date of loss 2026-06-01. Roof claim under HO-2026-08 will be "
            "denied in part because depreciation was applied before the deductible. The adjuster "
            "wants to know what CP-09 requires before issuing the denial letter."
        ),
        "case": {"claim_no": "CLM-2026-02230", "date_of_loss": "2026-06-01", "deductible": None},
        "why": (
            "Real failure: BASIS correctly flags the calculation-order error as an audit "
            "failure, then NEXT ACTION contradicts it by instructing the denial letter be "
            "issued anyway."
        ),
    },
    {
        "id": "R-M6-V13",
        "source_trace": "V13",
        "notes": (
            "Claim CLM-2026-02278, date of loss 2026-07-02. Basement flooded from a sump pump "
            "failure and a chest freezer in the same basement lost its contents from the "
            "outage. Endorsements HO-2026-01 and HO-2026-03 both attached. Which endorsement "
            "responds to which loss?"
        ),
        "case": {"claim_no": "CLM-2026-02278", "date_of_loss": "2026-07-02", "deductible": None},
        "why": (
            "Real failure: asserted the pump was 'in proper working order' when the notes say "
            "it failed, and treated a power outage as a covered mechanical breakdown."
        ),
    },
    {
        "id": "R-M6-V17",
        "source_trace": "V17",
        "notes": (
            "Claim CLM-2026-02366, date of loss 2026-09-01. Home-sharing guest's car was broken "
            "into in the insured's driveway while renting a room under a home-sharing platform. "
            "Endorsement HO-2026-06, Part 3 attached. What is the coverage position?"
        ),
        "case": {"claim_no": "CLM-2026-02366", "date_of_loss": "2026-09-01", "deductible": None},
        "why": (
            "Real failure: cited the 'theft BY a guest' clause for a guest's own property "
            "stolen FROM them by an outside thief - a different fact pattern entirely."
        ),
    },
    {
        "id": "R-M6-V18",
        "source_trace": "V18",
        "notes": (
            "Claim CLM-2026-02390, date of loss 2026-09-14. Insured wants increased "
            "ordinance-or-law costs for asbestos abatement required by the rebuild permit. "
            "Endorsement HO-2026-05, 25% option elected."
        ),
        "case": {"claim_no": "CLM-2026-02390", "date_of_loss": "2026-09-14", "deductible": None},
        "why": (
            "Real failure: asserted the removal was 'required solely because of the covered "
            "loss' - the exact condition the notes never establish."
        ),
    },
]


def load_traces() -> dict:
    with TRACES.open(encoding="utf-8") as handle:
        return {t["trace_id"]: t for t in (json.loads(l) for l in handle if l.strip())}


def classify(traces: dict) -> dict:
    """
    Re-derive the failure modes from the traces rather than trusting a list.
    If the corpus is regenerated, the modes follow it.
    """

    answered = [t for t in traces.values() if not t["refused"]]

    wrong_refusal = [
        t for t in traces.values()
        if t["refused"] and t["refused_by"] == "model"
        # Kind E is genuinely out of scope, and kind F is too vague to answer,
        # so refusing either is correct behaviour, not a failure.
        and t.get("question_kind") not in {"E", "F"}
        and t["retrieved"] and t["retrieved"][0]["dense_score"] >= t["params"]["min_score"]
    ]

    truncated = [
        t for t in answered
        if t["answer"] and not t["answer"].rstrip().endswith(TERMINAL)
    ]

    uncited = [
        t for t in answered
        if not t["cited_chunk_ids"] and t not in truncated
    ]

    guards = [t for t in traces.values() if t.get("question_kind") == "E"]

    return {"M1": wrong_refusal, "M2": truncated, "M3": uncited, "GUARD": guards}


def build() -> list[dict]:

    traces = load_traces()
    groups = classify(traces)
    cases: list[dict] = []

    for trace in groups["M1"]:
        cases.append({
            "id": f"R-M1-{trace['trace_id']}",
            "mode": "M1",
            "type": "qa",
            "source_trace": trace["trace_id"],
            "question_kind": trace.get("question_kind"),
            "question": trace["question"],
            "retrieval_mode": trace["params"]["mode"],
            "must_answer": True,
            "must_cite": True,
            "why": "Week 5: refused although the retrieved chunks passed the gate",
        })

    for trace in groups["M2"]:
        cases.append({
            "id": f"R-M2-{trace['trace_id']}",
            "mode": "M2",
            "type": "qa",
            "source_trace": trace["trace_id"],
            "question_kind": trace.get("question_kind"),
            "question": trace["question"],
            "retrieval_mode": trace["params"]["mode"],
            "must_answer": True,
            "must_cite": True,
            "why": "Week 5: answer stopped mid-sentence",
        })

    for trace in groups["M3"]:
        cases.append({
            "id": f"R-M3-{trace['trace_id']}",
            "mode": "M3",
            "type": "qa",
            "source_trace": trace["trace_id"],
            "question_kind": trace.get("question_kind"),
            "question": trace["question"],
            "retrieval_mode": trace["params"]["mode"],
            "must_answer": True,
            "must_cite": True,
            "why": "Week 5: stated figures with no citation recorded against any chunk",
        })

    for trace in groups["GUARD"]:
        cases.append({
            "id": f"G-{trace['trace_id']}",
            "mode": "GUARD",
            "type": "qa",
            "source_trace": trace["trace_id"],
            "question_kind": trace.get("question_kind"),
            "question": trace["question"],
            "retrieval_mode": trace["params"]["mode"],
            "must_refuse": True,
            "must_cite": False,
            "why": "Out of scope: must keep being refused after any fix aimed at M1",
        })

    for fixture in SUMMARY_CASES:
        cases.append({
            "id": fixture["id"],
            "mode": fixture["mode"],
            "type": "summary",
            "notes": fixture["notes"],
            "case": fixture["case"],
            "retrieval_mode": "hybrid",
            "judge": True,
            "must_cite": True,
            "why": "Claim summary graded by the validated judge",
        })

    for fixture in REGRESSION_SUMMARY_CASES:
        cases.append({
            "id": fixture["id"],
            "mode": "M6",
            "type": "summary",
            "source_trace": fixture["source_trace"],
            "notes": fixture["notes"],
            "case": fixture["case"],
            "retrieval_mode": "hybrid",
            "judge": True,
            "must_cite": True,
            "why": fixture["why"],
        })

    return cases


def write(cases: list[dict]) -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=False) + "\n")


def main() -> int:

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify without rewriting")
    args = parser.parse_args()

    cases = build()

    counts: dict[str, int] = {}
    for case in cases:
        counts[case["mode"]] = counts.get(case["mode"], 0) + 1

    if args.check:
        if not OUT.exists():
            print("eval set missing")
            return 1
        existing = [json.loads(l) for l in OUT.read_text(encoding="utf-8").splitlines() if l.strip()]
        same = existing == cases
        print("in sync" if same else "OUT OF SYNC - rerun without --check")
        return 0 if same else 1

    write(cases)

    print(f"wrote {len(cases)} cases to {OUT.relative_to(REPO_ROOT)}")
    for mode in sorted(counts):
        print(f"  {mode:<6} {counts[mode]:>3}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
