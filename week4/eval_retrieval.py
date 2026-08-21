"""
Measure hit-rate@3 and p50 latency for the golden set against whichever
retriever mode is selected. Same 12 questions, same k, only the retrieval
mechanism changes between "dense" (baseline) and "hybrid" (after).

Calls the REAL production retrieval code (VectorStore.search /
.search_hybrid, app/services/hybrid_search.py) against an isolated
index - not a separate reimplementation - so this evaluation can never
silently drift from what the app actually runs.

    python week4/eval_retrieval.py --mode dense  --out week4/baseline_results.json
    python week4/eval_retrieval.py --mode hybrid --out week4/after_results.json
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from qdrant_client import QdrantClient

from app.core.config import DATA_DIR
from app.services.chunk_service import create_chunks_for_all
from app.services.document_loader import load_file
from app.services.embedding_service import EmbeddingService
from app.services.vector_store import VectorStore

GOLDEN_SET_PATH = Path(__file__).parent / "golden_set.jsonl"
EVAL_TOP_K = 10  # retrieved breadth for measurement, independent of the app's TOP_K=5

# This harness gets its OWN Qdrant storage, isolated from .qdrant (the
# app's live embedded-mode store). Embedded Qdrant locks its folder to
# one process at a time, so if the app server is running, a second
# QdrantClient at the same path would crash - this avoids that
# entirely rather than requiring the app server to be stopped first.
EVAL_QDRANT_PATH = str(REPO_ROOT / "week4" / ".qdrant_eval")
EVAL_COLLECTION_NAME = "week4_eval"


def build_eval_index(embedding_service):
    """
    Scoped to only the *.md files DATA_DIR held when the golden set
    was built - not everything currently in data/. data/ has since
    picked up an unrelated uploaded PDF (from a separate feature test);
    silently folding it into this comparison would mean the "same
    corpus, only retrieval mechanism changed" measurement could shift
    for reasons that have nothing to do with the retrieval change
    actually being evaluated, and every future run of this script
    would depend on whatever happens to be in data/ at the time.
    """

    vector_store = VectorStore(
        collection_name=EVAL_COLLECTION_NAME,
        embedding_service=embedding_service,
        client=QdrantClient(path=EVAL_QDRANT_PATH),
    )

    documents = [load_file(path) for path in sorted(DATA_DIR.glob("*.md"))]
    documents = [doc for doc in documents if doc is not None]

    chunks = create_chunks_for_all(documents)
    vector_store.rebuild_index(chunks)

    return vector_store


def load_golden_set():
    with open(GOLDEN_SET_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def rank_of(expected_chunk_id, ranked_hits):
    for position, hit in enumerate(ranked_hits, start=1):
        if hit["chunk_id"] == expected_chunk_id:
            return position
    return None


def retrieve(vector_store, embedding_service, question, top_k, mode):
    """
    Call the production retrieval path directly - VectorStore.search()
    for dense, VectorStore.search_hybrid() for hybrid - the exact
    methods app/services/retrieval_service.py calls for a real request.
    """

    query_embedding = embedding_service.generate_query_embedding(question)

    if mode == "hybrid":
        return vector_store.search_hybrid(
            query_embedding=query_embedding,
            question=question,
            top_k=top_k,
        )

    return vector_store.search(query_embedding=query_embedding, top_k=top_k)


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["dense", "hybrid"], default="dense")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    embedding_service = EmbeddingService()
    vector_store = build_eval_index(embedding_service)

    golden_set = load_golden_set()

    per_question = []
    latencies = []

    for item in golden_set:

        start = time.perf_counter()
        ranked_hits = retrieve(
            vector_store, embedding_service, item["question"], EVAL_TOP_K, args.mode
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        latencies.append(elapsed_ms)

        position = rank_of(item["expected_chunk_id"], ranked_hits)
        hit_at_3 = position is not None and position <= 3

        per_question.append({
            "id": item["id"],
            "question": item["question"],
            "expected_chunk_id": item["expected_chunk_id"],
            "exact_token": item["exact_token"],
            "rank_of_expected": position,
            "hit_at_3": hit_at_3,
            "latency_ms": round(elapsed_ms, 1),
            "top5_chunk_ids": [h["chunk_id"] for h in ranked_hits[:5]],
        })

    hit_rate_at_3 = sum(1 for q in per_question if q["hit_at_3"]) / len(per_question)
    p50_latency = statistics.median(latencies)

    result = {
        "mode": args.mode,
        "n_questions": len(per_question),
        "hit_rate_at_3": hit_rate_at_3,
        "p50_latency_ms": round(p50_latency, 1),
        "per_question": per_question,
    }

    Path(args.out).write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"mode={args.mode}  hit_rate@3={hit_rate_at_3:.3f} ({sum(1 for q in per_question if q['hit_at_3'])}/{len(per_question)})  p50_latency={p50_latency:.1f}ms")
    for q in per_question:
        flag = "HIT " if q["hit_at_3"] else "MISS"
        print(f"  [{flag}] {q['id']}  rank={q['rank_of_expected']}  {q['question'][:70]}")


if __name__ == "__main__":
    raise SystemExit(main())
