"""
Validate the claim-summary judge against a human's own grading, before
trusting any number it produces.

Three steps, run in this order so the human grading is never influenced by
having already seen the judge's verdict:

    python scripts/validate_judge.py generate
        Generates a summary for each of the 20 notes in
        evaluation/judge_validation_notes.json, and writes
        .runtime/judge/human_grading_sheet.md - a readable file with the
        notes, retrieved sources and summary for each case, and a blank
        verdict line per criterion for a person to fill in by hand.

    ... a human reads human_grading_sheet.md and fills in pass/fail for each
        criterion, then saves the grades to .runtime/judge/human_grades.json
        (a template with blanks is written alongside the sheet) ...

    python scripts/validate_judge.py judge
        Runs the judge on the SAME 20 generated summaries (not fresh ones -
        temperature is 0, so this is only for auditability, not to give the
        judge a different case than the human graded).

    python scripts/validate_judge.py compare
        Reports per-criterion agreement between human_grades.json and the
        judge's verdicts, and lists every disagreement with both reasons.

Stop the API server first: embedded Qdrant locks its folder to one process.
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.services.judge_service import CRITERIA  # noqa: E402
from app.services.shared import get_judge_service, get_summary_service  # noqa: E402

NOTES_PATH = REPO_ROOT / "evaluation" / "judge_validation_notes.json"
JUDGE_DIR = REPO_ROOT / ".runtime" / "judge"
GENERATED_PATH = JUDGE_DIR / "generated_summaries.json"
SHEET_PATH = JUDGE_DIR / "human_grading_sheet.md"
HUMAN_GRADES_PATH = JUDGE_DIR / "human_grades.json"
JUDGE_VERDICTS_PATH = JUDGE_DIR / "judge_verdicts.json"
REPORT_PATH = REPO_ROOT / "docs" / "training" / "week6" / "judge_validation.md"


def load_notes() -> list[dict]:
    return json.loads(NOTES_PATH.read_text(encoding="utf-8"))


def cmd_generate(args: argparse.Namespace) -> int:

    summary_service = get_summary_service()
    notes = load_notes()

    generated = []

    for position, item in enumerate(notes, start=1):
        print(f"  [{position:>2}/{len(notes)}] {item['id']} ...", end="", flush=True)
        result = summary_service.summarise(item["notes"], mode="hybrid")
        generated.append({**item, "result": result})
        print(" done")

    JUDGE_DIR.mkdir(parents=True, exist_ok=True)
    GENERATED_PATH.write_text(json.dumps(generated, indent=2, ensure_ascii=False), encoding="utf-8")

    write_grading_sheet(generated)

    if not HUMAN_GRADES_PATH.exists():
        template = {
            item["id"]: {criterion["id"]: None for criterion in CRITERIA}
            for item in generated
        }
        HUMAN_GRADES_PATH.write_text(json.dumps(template, indent=2), encoding="utf-8")
        print(f"\nBlank grading template written to {HUMAN_GRADES_PATH.relative_to(REPO_ROOT)}")

    print(f"Read {SHEET_PATH.relative_to(REPO_ROOT)} and fill in "
          f"{HUMAN_GRADES_PATH.relative_to(REPO_ROOT)} with 'pass' or 'fail' for every criterion, "
          f"BEFORE running the 'judge' step.")

    return 0


def write_grading_sheet(generated: list[dict]) -> None:

    lines = [
        "# Judge validation - grading sheet",
        "",
        "Grade every case below by hand, against the sources shown, before running "
        "`scripts/validate_judge.py judge`. Record pass/fail per criterion in "
        "`human_grades.json`. Do not look at the judge's output first.",
        "",
        "Criteria:",
        "",
    ]

    for criterion in CRITERIA:
        lines.append(f"- **{criterion['id']} ({criterion['name']})** - {criterion['question']}")

    lines.append("")

    for item in generated:

        result = item["result"]

        lines += [
            "---",
            f"## {item['id']}",
            "",
            f"**Adjuster notes**",
            "",
            item["notes"],
            "",
            f"**Expected (my own prediction, for reference only)**: {item.get('expect', '')}",
            "",
            "**Retrieved sources**",
            "",
        ]

        for number, hit in enumerate(result["retrieved"], start=1):
            lines.append(f"[S{number}] {hit['source']} > {hit['heading']} ({hit['page']})")
            lines.append("")
            lines.append(f"> {hit['text']}")
            lines.append("")

        lines += [
            "**Summary produced**",
            "",
            "```",
            result["summary"],
            "```",
            "",
            "**Grades** (fill in human_grades.json)",
            "",
        ]

        for criterion in CRITERIA:
            lines.append(f"- {criterion['id']} ({criterion['name']}): ____")

        lines.append("")

    SHEET_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nGrading sheet written to {SHEET_PATH.relative_to(REPO_ROOT)} ({len(generated)} cases)")


def cmd_judge(args: argparse.Namespace) -> int:

    if not GENERATED_PATH.exists():
        print("Run 'generate' first.")
        return 1

    generated = json.loads(GENERATED_PATH.read_text(encoding="utf-8"))
    judge_service = get_judge_service()

    verdicts = {}

    for position, item in enumerate(generated, start=1):
        print(f"  [{position:>2}/{len(generated)}] {item['id']} ...", end="", flush=True)
        result = item["result"]
        outcome = judge_service.judge(item["notes"], result["summary"], result["retrieved"])
        verdicts[item["id"]] = outcome
        print(f" {outcome['status']}")

    JUDGE_VERDICTS_PATH.write_text(json.dumps(verdicts, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nJudge verdicts written to {JUDGE_VERDICTS_PATH.relative_to(REPO_ROOT)}")

    return 0


def cmd_compare(args: argparse.Namespace) -> int:

    if not HUMAN_GRADES_PATH.exists() or not JUDGE_VERDICTS_PATH.exists():
        print("Need both human_grades.json and judge_verdicts.json. Run 'generate' then 'judge' first.")
        return 1

    human = json.loads(HUMAN_GRADES_PATH.read_text(encoding="utf-8"))
    judged = json.loads(JUDGE_VERDICTS_PATH.read_text(encoding="utf-8"))

    missing = [case_id for case_id, grades in human.items() if any(v is None for v in grades.values())]
    if missing:
        print(f"Human grading incomplete for: {', '.join(missing)}. Fill in human_grades.json first.")
        return 1

    per_criterion = {criterion["id"]: {"agree": 0, "disagree": 0, "human_pass": 0, "judge_pass": 0} for criterion in CRITERIA}
    disagreements = []
    total_pairs = 0
    total_agree = 0

    for case_id, human_grades in human.items():

        judge_result = judged.get(case_id)

        if judge_result is None:
            print(f"WARNING: no judge verdict for {case_id}, skipping")
            continue

        for criterion in CRITERIA:

            cid = criterion["id"]
            human_verdict = human_grades[cid]
            judge_verdict = judge_result["verdicts"][cid]["verdict"]

            total_pairs += 1

            if human_verdict == "pass":
                per_criterion[cid]["human_pass"] += 1
            if judge_verdict == "pass":
                per_criterion[cid]["judge_pass"] += 1

            if human_verdict == judge_verdict:
                per_criterion[cid]["agree"] += 1
                total_agree += 1
            else:
                per_criterion[cid]["disagree"] += 1
                disagreements.append({
                    "case": case_id,
                    "criterion": cid,
                    "name": criterion["name"],
                    "human": human_verdict,
                    "judge": judge_verdict,
                    "judge_reason": judge_result["verdicts"][cid]["reason"],
                })

    overall_agreement = total_agree / total_pairs if total_pairs else 0.0

    lines = [
        "# Judge validation report",
        "",
        f"{len(human)} summaries, {len(CRITERIA)} criteria each, {total_pairs} human/judge pairs compared.",
        "",
        f"**Overall agreement: {overall_agreement:.0%}** ({total_agree}/{total_pairs})",
        "",
        "| Criterion | Agreement | Human pass rate | Judge pass rate |",
        "|---|---|---|---|",
    ]

    for criterion in CRITERIA:
        cid = criterion["id"]
        row = per_criterion[cid]
        n = row["agree"] + row["disagree"]
        agreement = row["agree"] / n if n else 0.0
        lines.append(
            f"| {cid} {criterion['name']} | {agreement:.0%} ({row['agree']}/{n}) "
            f"| {row['human_pass']}/{n} | {row['judge_pass']}/{n} |"
        )

    lines += ["", "## Disagreements", ""]

    if not disagreements:
        lines.append("None. The judge agreed with every human grade.")
    else:
        for d in disagreements:
            lines.append(
                f"- **{d['case']} / {d['criterion']} ({d['name']})** - human said "
                f"**{d['human']}**, judge said **{d['judge']}**. Judge's reason: {d['judge_reason']}"
            )

    lines.append("")
    lines.append(
        "## Verdict\n\n"
        + ("The judge agrees with a human closely enough to trust its numbers for this report; "
           "see the disagreements above for the cases worth a second look."
           if overall_agreement >= 0.85 else
           "Agreement is below 85%. Do not trust this judge's numbers yet - "
           "read the disagreements above, tighten the judge prompt, and revalidate.")
    )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")

    print("\n".join(lines))
    print(f"\nWritten to {REPORT_PATH.relative_to(REPO_ROOT)}")

    return 0 if overall_agreement >= 0.85 else 2


def main() -> int:

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("generate")
    subparsers.add_parser("judge")
    subparsers.add_parser("compare")

    args = parser.parse_args()

    return {"generate": cmd_generate, "judge": cmd_judge, "compare": cmd_compare}[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
