"""
Run the golden-set retrieval evaluation against the live index.

    python scripts/evaluate.py --mode dense
    python scripts/evaluate.py --mode hybrid --label "after hybrid"

The same code path the Evaluation page uses (app/services/evaluation_service.py).
Stop the API server first: embedded Qdrant locks its folder to one process.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.catalog import MODE_IDS  # noqa: E402
from app.services.shared import get_evaluation_service, get_rag_service  # noqa: E402


def main() -> int:

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=MODE_IDS, default="dense")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--label", default=None)
    args = parser.parse_args()

    rag = get_rag_service()

    if rag.chunk_count() == 0:
        print("The index is empty. Run: python scripts/ingest.py")
        return 1

    run = get_evaluation_service().run(
        retriever=rag.retriever,
        mode=args.mode,
        index_metadata=rag.index_metadata.read(),
        top_k=args.top_k,
        label=args.label,
    )

    print(
        f"run={run['run_id']} mode={run['mode']} "
        f"hit_rate@3={run['hit_rate_at_3']:.3f} ({run['hits_at_3']}/{run['n_questions']}) "
        f"hit_rate@5={run['hit_rate_at_5']:.3f} mrr={run['mrr']:.3f} "
        f"p50_latency={run['p50_latency_ms']:.1f}ms"
    )

    for question in run["per_question"]:
        flag = "HIT " if question["hit_at_3"] else "MISS"
        print(f"  [{flag}] {question['id']:<5} rank={question['rank_of_expected']}  {question['question'][:70]}")

    for warning in run["warnings"]:
        print(f"\nWARNING: {warning}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
