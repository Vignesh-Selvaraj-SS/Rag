"""
The inspection view: for each failing golden-set question, show the
question, exactly what was fetched (the TOP_K=5 chunks actually shown
to the LLM, matching production), and the final generated answer -
side by side, so a failure can be labelled R / G / Not-in-Corpus with
real evidence instead of a guess.

Points at the SAME isolated eval index eval_retrieval.py builds
(week4/.qdrant_eval), not the app's live .qdrant - so this never
competes with a running app server for the embedded-mode lock. Run
eval_retrieval.py at least once first so that index exists. Requires
a real GROQ_API_KEY - this calls the actual generation pipeline, not
a mock.

    python week4/inspect_failures.py --ids Q2
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from app.core.config import settings
from eval_retrieval import EVAL_COLLECTION_NAME, EVAL_QDRANT_PATH

settings.QDRANT_PATH = EVAL_QDRANT_PATH
settings.COLLECTION_NAME = EVAL_COLLECTION_NAME

from app.services.rag_service import RAGService

GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.jsonl"


def load_golden_set():
    with open(GOLDEN_SET_PATH, encoding="utf-8") as f:
        return {json.loads(line)["id"]: json.loads(line) for line in f if line.strip()}


def main():

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser()
    parser.add_argument("--ids", nargs="+", required=True, help="golden set ids to inspect, e.g. Q2 Q5")
    args = parser.parse_args()

    golden_set = load_golden_set()
    rag_service = RAGService()

    for qid in args.ids:

        item = golden_set[qid]
        question = item["question"]
        expected_chunk_id = item["expected_chunk_id"]
        expected_source, expected_index = expected_chunk_id.split("::")
        expected_heading = item["expected_heading"]

        print("=" * 100)
        print(f"{qid}: {question}")
        print(f"expected_chunk_id: {expected_chunk_id}  (source={expected_source}, heading={expected_heading!r})")
        print("-" * 100)

        result = rag_service.ask(question)

        def is_expected(hit):
            return hit["source"] == expected_source and hit["heading"] == expected_heading

        print("FETCHED (what was actually shown to the LLM, TOP_K=5):")
        expected_was_shown = False
        for number, hit in enumerate(result["retrieved"], start=1):
            marker = ""
            if is_expected(hit):
                marker = "  <-- EXPECTED CHUNK"
                expected_was_shown = True
            print(f"  [S{number}] score={hit['score']:.3f}  {hit['source']} > {hit['heading']!r}{marker}")
            print(f"        {hit['text'][:160]}...")

        print("-" * 100)
        print(f"expected chunk shown to LLM: {expected_was_shown}")
        print(f"refused: {result['refused']}  (by: {result['refused_by']})")
        print("FINAL ANSWER:")
        print(f"  {result['answer']}")
        print(f"cited sources: {[(h['source'], h['heading']) for h in result['sources']]}")
        print(f"invalid_citations: {result['invalid_citations']}")
        print()


if __name__ == "__main__":
    raise SystemExit(main())
