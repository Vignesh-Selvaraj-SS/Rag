"""
Draw a seeded random sample of trace_ids from the trace file.

    python week5/sample.py --seed 20260902 --n 20

The frame is every trace in the file with the given origin - not a question
list, not the demo claims. Re-running with the same seed gives the same 20,
which is what makes the sample provable rather than merely claimed.
"""

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from week5.trace_logger import TRACE_FILE, load_traces


def main() -> int:

    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--n", type=int, default=20)
    parser.add_argument("--origin", default="random")
    args = parser.parse_args()

    traces = [t for t in load_traces() if t["origin"] == args.origin]

    if len(traces) < args.n:
        print(f"Only {len(traces)} traces on file; need {args.n}. Run run_traces.py first.")
        return 1

    frame = sorted(trace["trace_id"] for trace in traces)

    generator = random.Random(args.seed)
    selected = sorted(generator.sample(frame, args.n))

    by_id = {trace["trace_id"]: trace for trace in traces}

    print(f"trace file : {TRACE_FILE}")
    print(f"frame      : {len(frame)} trace_ids (origin={args.origin})")
    print(f"seed       : {args.seed}")
    print(f"selected   : {args.n}")
    print()
    print(",".join(selected))
    print()

    for trace_id in selected:
        trace = by_id[trace_id]
        print(
            f"  {trace_id}  {trace['question_id']} [{trace['question_kind']}]  "
            f"{'refused' if trace['refused'] else 'answered'}  {trace['question'][:72]}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
