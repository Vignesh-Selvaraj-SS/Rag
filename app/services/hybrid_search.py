import re

from rank_bm25 import BM25Okapi

from app.services.chunk_service import embed_text

# Reciprocal Rank Fusion constant - matches the Week 4 evaluation
# (week4/hybrid_retrieval.py) that measured this before it shipped.
RRF_K = 60


def _tokenize(text: str) -> list[str]:
    # Keep hyphens and dots inside tokens so an exact identifier like
    # "HO-2026-08" or "DUP-01" survives as one token, not fragments.
    return re.findall(r"[a-z0-9][a-z0-9\-\.]*", text.lower())


class BM25Index:
    """
    Keyword (BM25) index over whatever chunks are currently stored.
    Cached on the VectorStore instance and only rebuilt after a
    re-ingest - see VectorStore.rebuild_index().
    """

    def __init__(self, chunks: list[dict]):

        self.chunk_by_id = {chunk["chunk_id"]: chunk for chunk in chunks}
        self.chunk_ids_in_order = [chunk["chunk_id"] for chunk in chunks]

        corpus = [_tokenize(embed_text(chunk)) for chunk in chunks]
        self.bm25 = BM25Okapi(corpus) if chunks else None

    def rank(self, question: str) -> dict:
        """chunk_id -> 1-based rank position, best match first."""

        if self.bm25 is None:
            return {}

        scores = self.bm25.get_scores(_tokenize(question))

        ranked = sorted(
            zip(self.chunk_ids_in_order, scores),
            key=lambda pair: pair[1],
            reverse=True,
        )

        return {chunk_id: position for position, (chunk_id, _) in enumerate(ranked, start=1)}


def fuse_with_rrf(
    dense_results: list[dict],
    bm25_rank: dict,
    chunk_by_id: dict,
    top_k: int,
) -> list[dict]:
    """
    Reciprocal Rank Fusion: fuse dense rank and BM25 rank by
    1/(RRF_K + rank) per list, summed. RRF fuses RANKS, not raw
    scores - cosine similarity and BM25 scores live on unrelated
    scales and were never meant to be added or averaged together.
    """

    dense_rank = {result["chunk_id"]: position for position, result in enumerate(dense_results, start=1)}
    dense_score_by_id = {result["chunk_id"]: result["score"] for result in dense_results}

    fused_scores = {}

    for chunk_id in set(dense_rank) | set(bm25_rank):

        score = 0.0

        if chunk_id in dense_rank:
            score += 1.0 / (RRF_K + dense_rank[chunk_id])

        if chunk_id in bm25_rank:
            score += 1.0 / (RRF_K + bm25_rank[chunk_id])

        fused_scores[chunk_id] = score

    fused_ranked = sorted(fused_scores.items(), key=lambda pair: pair[1], reverse=True)[:top_k]

    # "score" is the fused RRF value, used for ranking/ordering. It is
    # NOT a similarity and is not comparable to MIN_SCORE (a cosine
    # threshold) - dense_score carries the original cosine similarity
    # instead, specifically so the refusal gate keeps its real meaning
    # regardless of which ranking mode found the result. A chunk BM25
    # surfaced but dense search never saw gets dense_score=0.0.
    return [
        {
            **chunk_by_id[chunk_id],
            "score": score,
            "dense_score": dense_score_by_id.get(chunk_id, 0.0),
        }
        for chunk_id, score in fused_ranked
    ]
