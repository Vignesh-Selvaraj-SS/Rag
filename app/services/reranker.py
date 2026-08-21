import sys

# Cached across calls - loading a cross-encoder is expensive, same
# reasoning as the embedding model cache in embedding_service.py.
_model = None

RERANKER_MODEL = "BAAI/bge-reranker-base"


def get_reranker():
    """
    Load the cross-encoder once. The first call on a fresh machine
    downloads the weights.
    """

    global _model

    if _model is None:

        # Same Windows console-encoding safeguard as pdf_ocr.py's
        # EasyOCR loader - some Hugging Face download progress output
        # can crash on the default cp1252 console encoding.
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

        from sentence_transformers import CrossEncoder

        _model = CrossEncoder(RERANKER_MODEL)

    return _model


def rerank(question: str, hits: list[dict], top_k: int) -> list[dict]:
    """
    Cross-encoder reranking: feed (question, chunk text) through a
    model that reads both TOGETHER, rather than comparing separately
    precomputed vectors - more accurate, but only affordable over a
    small candidate pool (`hits` should already be narrowed to ~20-25
    dense results before this is called, never the whole collection).

    Can only REORDER candidates already retrieved - never introduces
    a chunk the first-pass search missed entirely.

    "score" becomes the cross-encoder's relevance score (not a cosine
    similarity - MIN_SCORE's gate must not compare against it), so the
    original dense similarity is preserved as "dense_score", the same
    split used for hybrid search in hybrid_search.py.
    """

    if not hits:
        return hits[:top_k]

    pairs = [(question, hit.get("text", "")) for hit in hits]

    cross_scores = get_reranker().predict(pairs)

    scored = []

    for hit, cross_score in zip(hits, cross_scores):

        dense_score = hit.get("dense_score", hit["score"])

        scored.append({**hit, "score": float(cross_score), "dense_score": dense_score})

    scored.sort(key=lambda hit: hit["score"], reverse=True)

    return scored[:top_k]
