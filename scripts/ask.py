"""
Ask a question against the ingested documents from the command line.

    python scripts/ask.py "What deductible applies to a water backup claim?"
    python scripts/ask.py --search-only "Why is my roof cheque smaller than the estimate?"
    python scripts/ask.py --mode hybrid "Which territories prohibit roof ACV settlement?"

Stop the API server first: embedded Qdrant locks its folder to one process.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.services.catalog import MODE_IDS  # noqa: E402
from app.services.shared import get_rag_service  # noqa: E402


def print_hits(hits: list[dict], min_score: float) -> None:

    print(f"\nRetrieved {len(hits)} chunks (gate: {min_score:.2f}):")

    for number, hit in enumerate(hits, start=1):
        # The gate checks dense_score (a cosine similarity) even in hybrid
        # mode, where "score" is a fused RRF value on a different scale.
        flag = "pass" if hit["dense_score"] >= min_score else "weak"
        print(
            f"  [S{number}] score={hit['score']:.3f} {flag}  "
            f"{hit['source']} > {hit['heading']}  ({hit['page']})"
        )


def main() -> int:

    parser = argparse.ArgumentParser()
    parser.add_argument("question", nargs="*")
    parser.add_argument("--top-k", type=int, default=settings.TOP_K)
    parser.add_argument("--min-score", type=float, default=settings.MIN_SCORE)
    parser.add_argument("--source", default=None)
    parser.add_argument("--search-only", action="store_true")
    parser.add_argument("--mode", choices=MODE_IDS, default="dense")
    args = parser.parse_args()

    question = " ".join(args.question)

    if not question:
        parser.error("a question is required")

    rag = get_rag_service()

    if rag.chunk_count() == 0:
        print("The index is empty. Run: python scripts/ingest.py")
        return 1

    options = {
        "top_k": args.top_k,
        "min_score": args.min_score,
        "source": args.source,
        "mode": args.mode,
    }

    if args.search_only:
        retrieval = rag.search(question, **options)
        print_hits(retrieval["hits"], args.min_score)
        print(f"\nbest_score={retrieval['best_score']:.3f} passes_gate={retrieval['passes_gate']}")
        return 0

    result = rag.ask(question, **options)

    print_hits(result["retrieved"], args.min_score)
    print(f"\nA: {result['answer']}")

    if result["refused"]:
        print(f"\nRefused by the {result['refused_by']}.")
        return 0

    print("\nSources:")
    for hit in result["sources"]:
        print(f"  {hit['source']} > {hit['heading']} ({hit['page']})")

    if result["invalid_citations"]:
        print(f"\nWARNING: invented citations {result['invalid_citations']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
