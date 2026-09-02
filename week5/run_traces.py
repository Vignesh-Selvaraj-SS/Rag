"""
Generate the trace corpus by running every question in the pool.

    python week5/run_traces.py --mode hybrid

Traces accumulate in week5/traces.jsonl. Run this BEFORE reading anything,
then freeze app/ - the whole sample has to come from one version of the app.
"""

import argparse
import re
import sys
import time
from pathlib import Path

# Running this as a file puts week5/ on sys.path, not the project root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.shared import rag_service
from week5.trace_logger import TRACE_FILE, append_trace, build_trace, load_traces

POOL_FILE = Path(__file__).resolve().parent / "question_pool.md"

QUESTION_LINE = re.compile(r"^(Q\d{3})\s*\|\s*([A-G])\s*\|\s*(.+?)\s*$")


def load_pool(path: Path = POOL_FILE) -> list[tuple[str, str, str]]:

    questions = []

    for line in path.read_text(encoding="utf-8").splitlines():

        match = QUESTION_LINE.match(line.strip())

        if match:
            questions.append(match.groups())

    return questions


def main() -> int:

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="hybrid")
    parser.add_argument("--strategy", default="heading")
    parser.add_argument("--origin", default="random")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--ids",
        default=None,
        help="Comma-separated question ids to run instead of the whole pool.",
    )
    parser.add_argument("--sleep", type=float, default=1.0)
    args = parser.parse_args()

    if rag_service.chunk_count() == 0:
        print("The index is empty. Run: python ingest.py")
        return 1

    pool = load_pool()

    if args.ids:
        wanted = {value.strip() for value in args.ids.split(",")}
        pool = [entry for entry in pool if entry[0] in wanted]

    if args.limit:
        pool = pool[: args.limit]

    already = len(load_traces())

    print(f"{len(pool)} questions to run; {already} traces already on file")

    for number, (question_id, kind, question) in enumerate(pool, start=already + 1):

        trace_id = f"t_{number:04d}"

        started = time.perf_counter()

        try:
            result = rag_service.ask(question, mode=args.mode)
        except Exception as error:
            print(f"  {trace_id} {question_id} FAILED: {type(error).__name__}: {error}")
            time.sleep(args.sleep)
            continue

        latency_ms = int((time.perf_counter() - started) * 1000)

        trace = build_trace(
            trace_id=trace_id,
            question=question,
            result=result,
            latency_ms=latency_ms,
            chunk_strategy=args.strategy,
            question_id=question_id,
            question_kind=kind,
            origin=args.origin,
        )

        append_trace(trace)

        state = "refused" if trace["refused"] else "answered"

        print(f"  {trace_id} {question_id} [{kind}] {state} {latency_ms}ms")

        time.sleep(args.sleep)

    traces = load_traces()

    print(f"\n{len(traces)} traces in {TRACE_FILE}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
