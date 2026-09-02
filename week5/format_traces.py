"""
Render the append-only trace log into a readable, pretty-printed file.

    python week5/format_traces.py                 # all traces -> week5/traces.json
    python week5/format_traces.py --trace-id t_0036   # print one trace

The logger appends to traces.jsonl one compact object per line, because an
append-only line log survives a crash mid-run. Reading is a different job, so
that log is rendered here into indented JSON - the same records, one readable
block each.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from week5.trace_logger import TRACE_FILE, load_traces

PRETTY_FILE = Path(__file__).resolve().parent / "traces.json"


def main() -> int:

    parser = argparse.ArgumentParser()
    parser.add_argument("--trace-id", default=None)
    parser.add_argument("--origin", default=None)
    args = parser.parse_args()

    traces = load_traces()

    if not traces:
        print(f"No traces in {TRACE_FILE}. Run run_traces.py first.")
        return 1

    if args.origin:
        traces = [t for t in traces if t["origin"] == args.origin]

    if args.trace_id:

        match = [t for t in traces if t["trace_id"] == args.trace_id]

        if not match:
            print(f"No trace with trace_id {args.trace_id}")
            return 1

        print(json.dumps(match[0], indent=2, ensure_ascii=False))
        return 0

    rendered = json.dumps(traces, indent=2, ensure_ascii=False)

    PRETTY_FILE.write_text(rendered + "\n", encoding="utf-8")

    print(f"source : {TRACE_FILE}  ({len(traces)} traces, {len(traces)} lines)")
    print(f"written: {PRETTY_FILE}  ({rendered.count(chr(10)) + 1} lines)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
