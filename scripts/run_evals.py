"""
The one-command Week 6 test set. Scores every case in evaluation/eval_set.jsonl
against the live application and prints a table grouped by failure mode.

    python scripts/run_evals.py --label before
    ... make one change ...
    python scripts/run_evals.py --label after
    python scripts/run_evals.py --compare before after

Runs the real RAGService / SummaryService / JudgeService - not a
reimplementation - so this can never silently drift from what the app
actually does. Stop the API server first: embedded Qdrant locks its folder to
one process.

Needs GROQ_API_KEY: every case in the set either generates an answer or grades
one, so this is not a retrieval-only measurement (see scripts/evaluate.py for
that).
"""

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.services.eval_service import compare  # noqa: E402
from app.services.shared import (  # noqa: E402
    get_eval_service,
    get_judge_service,
    get_rag_service,
    get_summary_service,
)

STATUS_ICON = {"pass": "PASS", "fail": "FAIL", "review": "RVW "}


def _progress(position: int, total: int, case: dict) -> None:
    print(f"  [{position:>2}/{total}] {case['id']:<14} {case['mode']:<6} ...", end="", flush=True)


def run(args: argparse.Namespace) -> int:

    rag = get_rag_service()

    if rag.chunk_count() == 0:
        print("The index is empty. Run: python scripts/ingest.py")
        return 1

    summary_service = get_summary_service() if not args.no_judge else None
    judge_service = get_judge_service() if not args.no_judge else None

    eval_service = get_eval_service()

    def progress(position, total, case):
        _progress(position, total, case)

    result = eval_service.run(
        rag_service=rag,
        summary_service=summary_service,
        judge_service=judge_service,
        label=args.label,
        only=args.only,
        use_judge=not args.no_judge,
        sleep=args.sleep,
        progress=progress,
    )

    # progress() printed a prefix with no newline per case; finish each line here.
    print()

    for case in result["cases"]:
        icon = STATUS_ICON.get(case["status"], case["status"].upper())
        print(f"  {icon}  {case['id']:<14} {case['mode']:<6} {case['latency_ms']:>6}ms", end="")
        if case["error"]:
            print(f"  ERROR: {case['error']}")
        else:
            failing = [c["id"] for c in case["checks"] if c["status"] == "fail"]
            print(f"  {'failed: ' + ','.join(failing) if failing else ''}")

    print(f"\n=== {result['label']} ===")
    print(f"{result['totals']['passed']}/{result['totals']['cases']} passed "
          f"({result['totals']['pass_rate']:.0%})  "
          f"errors={result['totals']['errors']}  "
          f"in {result['duration_s']}s\n")

    print(f"{'mode':<8}{'passed':>8}{'total':>8}{'rate':>8}")
    print("-" * 32)
    for row in result["by_mode"]:
        print(f"{row['mode']:<8}{row['passed']:>8}{row['total']:>8}{row['pass_rate']:>8.0%}")

    print(f"\n{'assertion':<28}{'pass':>6}{'fail':>6}{'review':>8}{'skip':>6}")
    print("-" * 54)
    for row in result["by_assertion"]:
        print(f"{row['id']:<28}{row['pass']:>6}{row['fail']:>6}{row['review']:>8}{row['skip']:>6}")

    if result["judge"]:
        j = result["judge"]
        print(f"\njudge: {j['cases']} summaries, {j['all_pass']} passed every criterion")
        for cid, row in j["by_criterion"].items():
            print(f"  {cid} {row['name']:<20} pass={row['pass']} fail={row['fail']} error={row['error']}")

    print(f"\nSaved: .runtime/evals/{result['label']}.json")

    return 0


def show_compare(args: argparse.Namespace) -> int:

    eval_service = get_eval_service()

    before = eval_service.load_run(args.compare[0])
    after = eval_service.load_run(args.compare[1])

    rows = compare(before, after)

    print(f"{'mode':<8}{'before':>16}{'after':>16}{'delta':>10}")
    print("-" * 50)

    for row in rows:
        b = f"{row['before_passed']}/{row['before_total']} ({row['before_rate']:.0%})" if row["before_total"] else "-"
        a = f"{row['after_passed']}/{row['after_total']} ({row['after_rate']:.0%})" if row["after_total"] else "-"
        d = f"{row['delta']:+.0%}" if row["delta"] is not None else "-"
        print(f"{row['mode']:<8}{b:>16}{a:>16}{d:>10}")

    print(f"\noverall: {before['totals']['pass_rate']:.0%} -> {after['totals']['pass_rate']:.0%} "
          f"({after['totals']['pass_rate'] - before['totals']['pass_rate']:+.0%})")

    return 0


def main() -> int:

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="run", help="name this run is saved and compared under")
    parser.add_argument("--only", nargs="+", default=None, help="restrict to these case ids or mode names")
    parser.add_argument("--no-judge", action="store_true", help="skip the LLM judge (assertions only)")
    parser.add_argument("--sleep", type=float, default=1.0, help="seconds between cases (free-tier rate limit)")
    parser.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"), help="print a delta table for two saved runs")
    args = parser.parse_args()

    if args.compare:
        return show_compare(args)

    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
