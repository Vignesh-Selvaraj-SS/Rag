"""
Replay one trace from the trace alone and show the result beside the original.

    python week5/replay.py --seed 20260902

The trace to replay is itself chosen at random from a seed, so the choice
cannot be quietly steered towards a trace that happens to replay cleanly.

Two replays are run, because they prove different things:

  retrieval  - re-run retrieval with the trace's recorded params and compare
               the chunk_ids and scores that come back
  generation - rebuild the model call from the chunks stored IN the trace
               (not from a fresh search) and compare the raw output

If generation matches while retrieval does not, the index moved. If retrieval
matches while generation does not, the model or prompt moved.
"""

import argparse
import difflib
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.shared import rag_service
from week5.trace_logger import load_traces


def show(title: str, body: str) -> None:

    print()
    print(title)
    print("-" * len(title))
    print(body)


def main() -> int:

    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--trace-id", default=None)
    parser.add_argument("--origin", default="random")
    args = parser.parse_args()

    traces = [t for t in load_traces() if t["origin"] == args.origin]

    if not traces:
        print("No traces on file. Run run_traces.py first.")
        return 1

    if args.trace_id:
        trace = next(t for t in traces if t["trace_id"] == args.trace_id)
    else:
        frame = sorted(traces, key=lambda t: t["trace_id"])
        trace = random.Random(args.seed).choice(frame)

    params = trace["params"]

    print(f"seed          : {args.seed}")
    print(f"frame         : {len(traces)} trace_ids")
    print(f"trace_id      : {trace['trace_id']}")
    print(f"recorded at   : {trace['timestamp']}")
    print(f"model         : {trace['model']}")
    print(f"prompt_version: {trace['prompt_version']}")
    print(f"params        : {json.dumps(params)}")
    print(f"question      : {trace['question']}")

    # ---------------------------------------------------------- retrieval
    fresh = rag_service.search(
        trace["question"],
        top_k=params["top_k"],
        min_score=params["min_score"],
        source=params["source_filter"],
        mode=params["mode"],
    )

    original_chunks = [(h["chunk_id"], h["score"]) for h in trace["retrieved"]]
    replayed_chunks = [
        (h["chunk_id"], round(float(h["score"]), 4)) for h in fresh["hits"]
    ]

    show(
        "RETRIEVAL - original (from the trace)",
        "\n".join(f"  {rank}. {cid}  score={score}" for rank, (cid, score) in enumerate(original_chunks, 1)),
    )
    show(
        "RETRIEVAL - replayed",
        "\n".join(f"  {rank}. {cid}  score={score}" for rank, (cid, score) in enumerate(replayed_chunks, 1)),
    )
    retrieval_match = original_chunks == replayed_chunks
    print(f"\nretrieval identical: {retrieval_match}")

    # --------------------------------------------------------- generation
    # Rebuilt from the trace's own stored chunks, so this replay does not
    # depend on the index still holding what it held at the time.
    hits = [
        {
            "chunk_id": hit["chunk_id"],
            "source": hit["source"],
            "heading": hit["heading"],
            "page": hit["page"],
            "text": hit["text"],
        }
        for hit in trace["retrieved"]
    ]

    if not trace["passes_gate"]:
        print("\nTrace was refused by the gate before any model call - nothing to regenerate.")
        return 0

    regenerated = rag_service.llm.generate_answer(trace["question"], hits)

    show("GENERATION - original raw_output (from the trace)", trace["raw_output"])
    show("GENERATION - replayed raw_output", regenerated["raw_output"])

    generation_match = trace["raw_output"].strip() == regenerated["raw_output"].strip()
    print(f"\ngeneration identical: {generation_match}")

    if not generation_match:
        show(
            "GENERATION - diff",
            "\n".join(
                difflib.unified_diff(
                    trace["raw_output"].splitlines(),
                    regenerated["raw_output"].splitlines(),
                    fromfile="original",
                    tofile="replayed",
                    lineterm="",
                )
            ),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
